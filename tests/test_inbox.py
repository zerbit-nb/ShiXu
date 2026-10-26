"""Cross-source order/filter/paging and real association regression checks."""
from tests.test_api import client, import_message


def test_inbox_paging_sources_and_state(client):
    db = client.app.state.db
    for i, (source, state) in enumerate([('qq','received'),('wechat','failed'),('manual','ignored'),('qq','no_action')]):
        db.create_message(dict(source=source, source_group='测试群', sender='同学', sent_at=None, raw_text='<原文>', extraction_status=state, created_at=f'2026-10-18T0{i}:00:00+00:00'))
    result = client.get('/api/inbox?limit=2').json()
    assert result['total'] == 4
    assert [m['extraction_status'] for m in result['messages']] == ['no_action','ignored']
    assert len(client.get('/api/inbox?offset=2&limit=2').json()['messages']) == 2
    assert client.get('/api/inbox?source=qq').json()['total'] == 2
    assert client.get('/api/inbox?source=wechat&status=pending').json()['total'] == 1
    assert client.get('/api/inbox?status=ignored').json()['total'] == 1
    assert client.get('/api/inbox?status=failed').json()['total'] == 1
    assert client.get('/api/inbox?offset=99').json()['messages'] == []
    for query in ['source=invalid','status=invalid','limit=0','offset=-1']:
        assert client.get('/api/inbox?'+query).status_code == 422


def test_inbox_live_tasks_and_links_survive_actions(client):
    first = import_message(client)
    draft = first['drafts'][0]
    task = client.post(f"/api/drafts/{draft['id']}/confirm",json={'confirmed':True,'fields':draft['fields']}).json()
    other = import_message(client, '补充通知')
    db=client.app.state.db
    db.link_draft(other['drafts'][0]['id'], task['id'])
    rows=client.get('/api/inbox?status=task').json()['messages']
    assert {row['id'] for row in rows} == {first['message']['id'],other['message']['id']}
    assert all(row['task_count']==1 for row in rows)
    assert all(row['tasks']==[{'id':task['id'],'title':task['title'],'status':'pending'}] for row in rows)
    assert all(row['pending_draft_count']==1 for row in rows)
    for action in ['complete','reopen']:
        assert client.post(f"/api/tasks/{task['id']}/{action}").status_code==200
        assert client.get('/api/inbox?status=task').json()['total']==2
    assert client.delete(f"/api/tasks/{task['id']}").status_code==200
    assert client.get('/api/inbox?status=task').json()['total']==0
    assert client.get('/api/inbox').json()['total']==2
    assert client.get('/api/inbox?status=processed').json()['total']==2


def test_trash_hides_each_source_and_restores_original_state(client):
    db = client.app.state.db
    ids = []
    for source in ['qq', 'wechat', 'manual']:
        m = db.create_message(dict(source=source, source_group='测试群', sender='测试', sent_at=None, raw_text='闲聊', extraction_status='ignored'))
        ids.append(m['id'])
        for _ in range(2):
            assert client.post(f"/api/inbox/{m['id']}/trash").status_code == 200
        assert client.get('/api/inbox?source='+source).json()['total'] == 0
        trashed = client.get('/api/inbox?folder=trash&source='+source).json()
        assert trashed['total'] == 1
        assert trashed['messages'][0]['extraction_status'] == 'ignored'
    assert client.get('/api/inbox').json()['total'] == 0
    assert client.get('/api/inbox?folder=trash&limit=2').json()['total'] == 3
    assert len(client.get('/api/inbox?folder=trash&limit=2&offset=2').json()['messages']) == 1
    for mid in ids:
        for _ in range(2):
            assert client.post(f'/api/inbox/{mid}/restore').status_code == 200
        assert db.get_message(mid)['extraction_status'] == 'ignored'
    assert client.get('/api/inbox').json()['total'] == 3
    assert client.get('/api/inbox?folder=trash').json()['total'] == 0


def test_trash_preserves_business_records(client):
    result = import_message(client)
    db = client.app.state.db
    draft = result['drafts'][0]
    task = db.confirm_draft(draft['id'], draft['fields'])
    before = {table: [tuple(r) for r in db.conn.execute('SELECT * FROM '+table)]
              for table in ['messages', 'drafts', 'tasks', 'task_sources', 'task_history']}
    mid = result['message']['id']
    assert client.post(f'/api/inbox/{mid}/trash').status_code == 200
    row = client.get('/api/inbox?folder=trash&status=task').json()['messages'][0]
    assert row['task_count'] == 1 and row['pending_draft_count'] == 1
    assert row['tasks'][0]['id'] == task['id']
    assert client.get(f'/api/messages/{mid}').status_code == 200
    assert client.post(f'/api/inbox/{mid}/restore').status_code == 200
    for table, rows in before.items():
        assert [tuple(r) for r in db.conn.execute('SELECT * FROM '+table)] == rows


def test_trash_validation_and_write_boundary(client):
    for action in ['trash', 'restore']:
        assert client.post('/api/inbox/missing/'+action).status_code == 404
    assert client.get('/api/inbox?folder=invalid').status_code == 422
    db = client.app.state.db
    m = db.create_message(dict(source='qq', source_group='', sender='', sent_at=None, raw_text='测试', extraction_status='extracting'))
    assert client.post(f"/api/inbox/{m['id']}/trash").status_code == 409
    db.set_message_status(m['id'], 'received')
    for action in ['trash', 'restore']:
        assert client.post(f"/api/inbox/{m['id']}/{action}", headers={'Origin':'https://other.example'}).status_code == 403
    assert client.get('/api/inbox').json()['total'] == 1


def test_trash_persists_when_database_reopens(client):
    from app.database import Database
    db = client.app.state.db
    m = db.create_message(dict(source='qq', source_group='', sender='', sent_at=None, raw_text='测试', extraction_status='received'))
    assert client.post(f"/api/inbox/{m['id']}/trash").status_code == 200
    reopened = Database(db.path)
    try:
        assert reopened.conn.execute('SELECT message_id FROM message_trash').fetchone()[0] == m['id']
        assert reopened.get_message(m['id'])['extraction_status'] == 'received'
    finally:
        reopened.close()


def test_trash_preserves_confirmed_change_history_and_sources(client):
    from tests.test_task_changes import original, draft, preview, change, history
    task = original(client)
    supplement = draft(client)
    assert change(client, supplement, preview(client, supplement)).status_code == 200
    before_history = history(client, task)
    assert len(before_history) == 1
    sources_url = f"/api/tasks/{task['id']}/sources"
    before_sources = client.get(sources_url).json()
    mids = [task['message_id'], supplement['message_id']]
    for action in ['trash', 'restore']:
        for mid in mids:
            assert client.post(f'/api/inbox/{mid}/{action}').status_code == 200
        assert history(client, task) == before_history
        assert client.get(sources_url).json() == before_sources
        assert client.get(f"/api/tasks/{task['id']}").json()['deadline'] == '2026-10-14'
