import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(), db_path=tmp_path / 'test.sqlite', config_path=tmp_path / 'config.json')) as c:
        yield c


def draft(client, text='实验报告提交截止时间延长至10月14日。'):
    return client.post('/api/messages/manual', json={'raw_text': text, 'source_group': '课程群'}).json()['drafts'][0]


def original(client):
    d = draft(client, '请于10月12日前提交实验报告。')
    return client.post(f"/api/drafts/{d['id']}/confirm", json={'confirmed': True, 'fields': {'title': '提交实验报告', 'deadline': '2026-10-12', 'location': '教学楼', 'materials': ['报告']}}).json()


def preview(client, d, deadline='2026-10-14'):
    return client.post(f"/api/drafts/{d['id']}/matches", json={'title': '提交实验报告', 'deadline': deadline, 'materials': ['报告']}).json()['matches'][0]


def change(client, d, match, **kwargs):
    payload = {'confirmed': True, 'task_id': match['task']['id'], 'version': match['version'], 'action': 'deadline', 'deadline': '2026-10-14', 'deadline_text': '10月14日'}
    return client.post(f"/api/drafts/{d['id']}/apply-change", json={**payload, **kwargs})


def history(client, task):
    return client.get(f"/api/tasks/{task['id']}/history").json()['history']


def test_confirmed_change_is_atomic_idempotent_and_preserves_other_fields(client):
    task = original(client)
    d = draft(client)
    m = preview(client, d)
    assert change(client, d, m, confirmed=False).status_code == 422
    assert client.get(f"/api/tasks/{task['id']}").json() == task
    response = change(client, d, m)
    assert response.status_code == 200
    updated = response.json()
    assert updated['deadline'] == '2026-10-14'
    assert updated['deadline_precision'] == 'date_only'
    for key in ['id', 'message_id', 'title', 'location', 'materials', 'status']:
        assert updated[key] == task[key]
    assert change(client, d, m).status_code == 200
    entries = history(client, task)
    assert len(entries) == 1
    assert entries[0]['before']['deadline'] == '2026-10-12'
    assert entries[0]['after']['deadline'] == '2026-10-14'
    assert entries[0]['message']['raw_text'] == '实验报告提交截止时间延长至10月14日。'
    assert entries[0]['confirmed_at']
    assert len(client.get(f"/api/tasks/{task['id']}/sources").json()['messages']) == 2
    assert change(client, d, m, deadline='2026-10-15').status_code == 409
    assert client.post(f"/api/drafts/{d['id']}/link", json={'confirmed': True, 'task_id': task['id']}).status_code == 409


def test_stale_preview_does_not_overwrite_current_values(client):
    task = original(client)
    d = draft(client)
    m = preview(client, d)
    client.patch(f"/api/tasks/{task['id']}", json={'deadline': '2026-10-13'})
    assert change(client, d, m).status_code == 409
    assert history(client, task) == []
    assert client.get(f"/api/tasks/{task['id']}").json()['deadline'] == '2026-10-13'
    assert change(client, d, preview(client, d)).status_code == 200


def test_multiple_rounds_and_cancel_have_ordered_history(client):
    task = original(client)
    a = draft(client)
    assert change(client, a, preview(client, a)).status_code == 200
    b = draft(client, '实验报告截止时间再次改为10月16日。')
    assert change(client, b, preview(client, b), deadline='2026-10-16').status_code == 200
    c = draft(client, '取消本次实验报告提交，请勿再提交。')
    m = preview(client, c)
    assert m['change_kind'] == 'cancel'
    assert change(client, c, m, action='cancel', deadline=None, deadline_text=None).status_code == 200
    assert change(client, c, m, action='cancel', deadline=None, deadline_text=None).status_code == 200
    entries = history(client, task)
    assert [e['action'] for e in entries] == ['deadline', 'deadline', 'cancel']
    assert entries[-1]['after']['status'] == 'cancelled'
    assert entries[-1]['after']['deadline'] == '2026-10-16'
    assert len(client.get('/api/tasks').json()['tasks']) == 1


def test_refusal_and_invalid_or_missing_deadline_do_not_modify_task(client):
    task = original(client)
    d = draft(client)
    m = preview(client, d)
    assert change(client, d, m, deadline='not-a-date').status_code == 422
    assert change(client, d, m, deadline=None).status_code == 422
    assert change(client, d, m, deadline=task['deadline']).status_code == 409
    assert client.post(f"/api/drafts/{d['id']}/discard").status_code == 200
    assert change(client, d, m).status_code == 409
    assert client.get(f"/api/tasks/{task['id']}").json() == task
    assert history(client, task) == []


def test_completed_task_requires_reopen_before_notification_update(client):
    task = original(client)
    d = draft(client)
    client.post(f"/api/tasks/{task['id']}/complete")
    assert change(client, d, preview(client, d)).status_code == 409
    assert history(client, task) == []


def test_failure_rolls_back_task_source_history_and_draft(client):
    task = original(client)
    d = draft(client)
    m = preview(client, d)
    db = client.app.state.db
    db.conn.execute("CREATE TRIGGER reject_history BEFORE INSERT ON task_history BEGIN SELECT RAISE(ABORT, 'history failure'); END")
    db.conn.commit()
    with pytest.raises(Exception, match='history failure'):
        change(client, d, m)
    assert db.get_task(task['id']) == task
    assert db.get_draft(d['id'])['status'] == 'pending'
    assert len(db.task_sources(task['id'])) == 1
    assert history(client, task) == []


def test_missing_target_and_reused_draft_are_rejected(client):
    task = original(client)
    d = draft(client)
    m = preview(client, d)
    assert change(client, d, m, task_id='missing').status_code == 404
    client.post(f"/api/drafts/{d['id']}/link", json={'confirmed': True, 'task_id': task['id']})
    assert change(client, d, m).status_code == 409


def test_existing_database_migration_and_restart_preserve_history(tmp_path):
    from app.database import Database
    path = tmp_path / 'legacy.sqlite'
    with TestClient(create_app(Settings(), db_path=path, config_path=tmp_path / 'config.json')) as c:
        task = original(c)
        c.app.state.db.conn.execute('DROP TABLE task_history')
        c.app.state.db.conn.commit()
    with TestClient(create_app(Settings(), db_path=path, config_path=tmp_path / 'config.json')) as c:
        d = draft(c)
        assert change(c, d, preview(c, d)).status_code == 200
    with TestClient(create_app(Settings(), db_path=path, config_path=tmp_path / 'config.json')) as c:
        assert history(c, task)[0]['after']['deadline'] == '2026-10-14'
        assert len(c.get(f"/api/tasks/{task['id']}/sources").json()['messages']) == 2
        c.delete(f"/api/tasks/{task['id']}")
        assert c.app.state.db.conn.execute('SELECT COUNT(*) FROM task_history').fetchone()[0] == 0
        assert c.app.state.db.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 2



def test_exact_time_is_normalized_and_retry_does_not_reapply_after_later_edit(client):
    task = original(client)
    d = draft(client)
    m = preview(client, d)
    response = change(client, d, m, deadline='2026-10-14T12:00:00Z')
    assert response.status_code == 200
    assert response.json()['deadline'] == '2026-10-14T20:00:00+08:00'
    assert response.json()['deadline_precision'] == 'datetime'
    client.patch(f"/api/tasks/{task['id']}", json={'deadline': '2026-10-18'})
    assert change(client, d, m, deadline='2026-10-14T12:00:00Z').json()['deadline'] == '2026-10-18'
    assert len(history(client, task)) == 1

