import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(), db_path=tmp_path / 'db.sqlite', config_path=tmp_path / 'config.json')) as c:
        yield c


def draft(client, group='测试群', text='请提交实验报告。'):
    return client.post('/api/messages/manual', json={'raw_text': text, 'source_group': group}).json()['drafts'][0]


def fields(title='提交实验报告', deadline='2026-10-12'):
    return {'title': title, 'deadline': deadline, 'materials': ['实验报告']}


def confirm(client, d, f=None, **extra):
    return client.post(f"/api/drafts/{d['id']}/confirm", json={'confirmed': True, 'fields': f or fields(), **extra})


def candidates(client, d, f=None):
    response = client.post(f"/api/drafts/{d['id']}/matches", json=f or fields())
    assert response.status_code == 200
    return response.json()['matches']


def test_duplicate_requires_explicit_choice_and_still_allows_new_task(client):
    first = confirm(client, draft(client)).json()
    second = draft(client)
    match = candidates(client, second)[0]
    assert match['task']['id'] == first['id']
    assert match['reasons']
    assert confirm(client, second).status_code == 409
    response = confirm(client, second, duplicate_reviewed=True)
    assert response.status_code == 200
    assert response.json()['id'] != first['id']
    assert len(client.get('/api/tasks').json()['tasks']) == 2


def test_different_group_same_activity_is_suggested_without_merging(client):
    first = confirm(client, draft(client, group='班群')).json()
    second = draft(client, group='课程群')
    match = candidates(client, second)[0]
    assert match['task']['id'] == first['id']
    assert '来源不同' in match['differences']
    assert len(client.get('/api/tasks').json()['tasks']) == 1


def test_similar_title_different_course_is_not_a_match(client):
    confirm(client, draft(client), fields('提交高等数学作业'))
    assert candidates(client, draft(client), fields('提交大学英语作业')) == []


def test_same_title_different_deadline_is_reviewable(client):
    confirm(client, draft(client))
    match = candidates(client, draft(client), fields(deadline='2026-10-14'))[0]
    assert '截止时间不同' in match['differences']
    assert client.get('/api/tasks').json()['tasks'][0]['deadline'] == '2026-10-12'


def test_link_preserves_fields_and_both_sources_and_is_idempotent(client):
    original = draft(client, text='原始实验报告通知')
    task = confirm(client, original).json()
    forwarded = draft(client, group='另一个群', text='转发实验报告通知')
    url = f"/api/drafts/{forwarded['id']}/link"
    body = {'confirmed': True, 'task_id': task['id']}
    assert client.post(url, json={**body, 'confirmed': False}).status_code == 422
    assert client.post(url, json=body).status_code == 200
    assert client.post(url, json=body).status_code == 200
    assert client.get(f"/api/tasks/{task['id']}").json() == task
    sources = client.get(f"/api/tasks/{task['id']}/sources").json()['messages']
    assert [m['raw_text'] for m in sources] == ['原始实验报告通知', '转发实验报告通知']
    assert len(client.get('/api/tasks').json()['tasks']) == 1
    assert client.post(f"/api/drafts/{forwarded['id']}/discard").status_code == 409
    assert confirm(client, forwarded, duplicate_reviewed=True).status_code == 409


def test_link_missing_target_leaves_draft_pending(client):
    d = draft(client)
    assert client.post(f"/api/drafts/{d['id']}/link", json={'confirmed': True, 'task_id': 'missing'}).status_code == 404
    assert any(row['id'] == d['id'] for row in client.get('/api/drafts').json()['drafts'])


def test_confirmation_retry_is_idempotent_even_after_matching_task_exists(client):
    d = draft(client)
    first = confirm(client, d).json()
    assert confirm(client, d).json()['id'] == first['id']


def test_current_edits_determine_matches_and_cancelled_tasks_are_excluded(client):
    task = confirm(client, draft(client)).json()
    d = draft(client)
    assert candidates(client, d, fields('参加新生讲座')) == []
    client.post(f"/api/tasks/{task['id']}/cancel")
    assert candidates(client, d) == []


def test_completed_tasks_are_visible_with_status(client):
    task = confirm(client, draft(client)).json()
    client.post(f"/api/tasks/{task['id']}/complete")
    assert candidates(client, draft(client))[0]['task']['status'] == 'completed'


def test_link_transaction_rolls_back_on_storage_failure(client):
    task = confirm(client, draft(client)).json()
    d = draft(client)
    db = client.app.state.db
    db.conn.execute("CREATE TRIGGER reject_link BEFORE UPDATE OF status ON drafts WHEN NEW.status='linked' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    db.conn.commit()
    with pytest.raises(Exception, match='test failure'):
        db.link_draft(d['id'], task['id'])
    assert db.get_draft(d['id'])['status'] == 'pending'
    assert len(db.task_sources(task['id'])) == 1


def test_existing_database_upgrade_and_multiple_sources_survive_restart(tmp_path):
    from app.database import Database
    db = Database(tmp_path / 'legacy.sqlite')
    message = db.create_message({'source':'manual','source_group':'旧群','sender':None,'sent_at':None,'raw_text':'旧通知','extraction_status':'ready'})
    d = db.create_draft(message['id'], fields(), [])
    task = db.confirm_draft(d['id'], fields())
    db.conn.execute('DROP TABLE task_sources')
    db.conn.commit()
    db.close()
    db = Database(tmp_path / 'legacy.sqlite')
    for text in ['转发一','转发二']:
        message = db.create_message({'source':'manual','source_group':'新群','sender':None,'sent_at':None,'raw_text':text,'extraction_status':'ready'})
        d = db.create_draft(message['id'], fields(), [])
        db.link_draft(d['id'], task['id'])
    db.close()
    db = Database(tmp_path / 'legacy.sqlite')
    assert db.get_task(task['id']) == task
    assert [m['raw_text'] for m in db.task_sources(task['id'])] == ['旧通知','转发一','转发二']
    db.delete_task(task['id'])
    assert db.conn.execute('SELECT count(*) FROM task_sources').fetchone()[0] == 0
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 3
    db.close()


def test_course_name_added_in_update_matches_using_original_notification(client):
    old = draft(client, group=None, text='请修读《物联网技术》课程的同学，于2026年10月15日20:00前提交实验报告。')
    original_fields = {'title': '提交实验报告', 'deadline': '2026-10-15T20:00:00+08:00', 'materials': []}
    task = confirm(client, old, original_fields).json()
    new = draft(client, group=None, text='关于《物联网技术》实验报告：提交截止时间延长至2026年10月18日20:00。')
    new_fields = {'title': '提交《物联网技术》实验报告', 'deadline': '2026-10-18T20:00:00+08:00', 'materials': []}
    found = candidates(client, new, new_fields)
    assert len(found) == 1
    assert found[0]['task']['id'] == task['id']
    assert '原通知课程相同' in found[0]['reasons']
    assert confirm(client, new, new_fields).status_code == 409
    response = client.post(f"/api/drafts/{new['id']}/apply-change", json={'confirmed': True, 'task_id': task['id'], 'version': found[0]['version'], 'action': 'deadline', 'deadline': new_fields['deadline'], 'deadline_text': '2026年10月18日20:00'})
    assert response.status_code == 200
    assert response.json()['deadline'] == new_fields['deadline']
    assert len(client.get('/api/tasks').json()['tasks']) == 1


def test_conflicting_courses_in_original_text_do_not_match_generic_titles(client):
    old = draft(client, text='《物联网技术》实验报告提交要求。')
    confirm(client, old, fields())
    new = draft(client, text='《大学物理》实验报告截止时间延长。')
    assert candidates(client, new, fields()) == []


def test_contained_titles_without_context_are_not_assumed_identical(client):
    old = draft(client, group=None, text='请提交实验报告。')
    confirm(client, old, {'title': '提交实验报告', 'materials': []})
    new = draft(client, group=None, text='提交《物联网技术》实验报告。')
    assert candidates(client, new, {'title': '提交《物联网技术》实验报告', 'materials': []}) == []


def test_scholarship_topic_matches_different_model_titles_and_updates_original(client):
    old = draft(client, group='学院奖学金通知群', text='关于2026年秋季奖学金申请：申请同学请于2026年10月20日18:00前，将奖学金申请表和成绩单合并为PDF文件，通过学院申报平台提交。')
    old_fields = {'title': '提交奖学金申请表', 'deadline': '2026-10-20T18:00:00+08:00', 'materials': ['奖学金申请表', '成绩单']}
    task = confirm(client, old, old_fields).json()
    new = draft(client, group='学院奖学金通知群', text='关于2026年秋季奖学金申请：申请材料提交截止时间由2026年10月20日18:00延长至2026年10月22日18:00。申请表、成绩单、PDF格式和学院申报平台提交方式均保持不变。')
    new_fields = {'title': '提交申请材料', 'deadline': '2026-10-22T18:00:00+08:00', 'materials': ['申请表', '成绩单']}
    found = candidates(client, new, new_fields)
    assert len(found) == 1
    assert found[0]['task']['id'] == task['id']
    assert '原通知主题相同' in found[0]['reasons']
    assert confirm(client, new, new_fields).status_code == 409
    response = client.post(f"/api/drafts/{new['id']}/apply-change", json={'confirmed': True, 'task_id': task['id'], 'version': found[0]['version'], 'action': 'deadline', 'deadline': new_fields['deadline'], 'deadline_text': '2026年10月22日18:00'})
    assert response.status_code == 200
    assert response.json()['deadline'] == new_fields['deadline']
    assert len(client.get('/api/tasks').json()['tasks']) == 1
    assert len(client.get(f"/api/tasks/{task['id']}/history").json()['history']) == 1


def test_different_notice_years_do_not_match_identical_titles(client):
    old = draft(client, text='关于2025年秋季奖学金申请：请提交申请材料。')
    confirm(client, old, {'title': '提交申请材料', 'materials': ['成绩单']})
    new = draft(client, text='关于2026年秋季奖学金申请：申请材料提交截止时间延长。')
    assert candidates(client, new, {'title': '提交申请材料', 'materials': ['成绩单']}) == []


def test_same_notice_topic_different_actions_do_not_match(client):
    old = draft(client, text='关于2026年秋季奖学金申请：请提交申请材料。')
    confirm(client, old, {'title': '提交申请材料', 'materials': ['成绩单']})
    new = draft(client, text='关于2026年秋季奖学金申请：请参加评审说明会，并携带成绩单。')
    assert candidates(client, new, {'title': '参加评审说明会', 'materials': ['成绩单']}) == []


def test_shared_material_and_group_without_topic_do_not_match_different_tasks(client):
    old = draft(client, text='请提交奖学金申请材料。')
    confirm(client, old, {'title': '提交奖学金申请材料', 'materials': ['成绩单']})
    new = draft(client, text='请提交转专业申请材料。')
    assert candidates(client, new, {'title': '提交转专业申请材料', 'materials': ['成绩单']}) == []


def test_unmatched_change_notice_needs_explicit_new_task_review(client):
    d = draft(client, text='申请材料提交截止时间延长至2026年10月22日18:00。')
    f = {'title': '提交申请材料', 'deadline': '2026-10-22T18:00:00+08:00'}
    response = client.post(f"/api/drafts/{d['id']}/matches", json=f)
    assert response.json()['matches'] == []
    assert response.json()['change_notice'] is True
    assert confirm(client, d, f).status_code == 409
    assert client.get('/api/tasks').json()['tasks'] == []
    assert confirm(client, d, f, duplicate_reviewed=True).status_code == 200


def test_topic_match_allows_missing_source_group_when_materials_and_action_match(client):
    old = draft(client, group=None, text='关于2026年校园创新项目申报：申请同学请于2026年10月25日18:00前，将项目申报表和项目计划书合并为PDF文件，通过学校项目申报平台提交。')
    task = confirm(client, old, {'title': '提交2026年校园创新项目申报', 'deadline': '2026-10-25T18:00:00+08:00', 'materials': ['项目申报表', '项目计划书']}).json()
    new = draft(client, group=None, text='关于2026年校园创新项目申报：项目材料提交截止时间由2026年10月25日18:00延长至2026年10月28日18:00。项目申报表、项目计划书、PDF格式和学校项目申报平台提交方式均保持不变。')
    found = candidates(client, new, {'title': '提交2026年校园创新项目材料', 'deadline': '2026-10-28T18:00:00+08:00', 'materials': ['项目申报表', '项目计划书']})
    assert len(found) == 1
    assert found[0]['task']['id'] == task['id']
    assert '原通知主题相同' in found[0]['reasons']
