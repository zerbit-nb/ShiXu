"""Temporary automatic tasks are reviewed individually, independently of popup dismissal."""
import asyncio
from fastapi.testclient import TestClient
from app.config import Settings
from app.database import Database
from app.main import create_app
from app.services.auto_organize import AutoOrganizer
from tests.test_auto_organize import Model, message, ORIGIN

def make_app(tmp_path):
    return create_app(Settings(llm_model='test'),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=Model())

def test_review_is_individual_durable_and_does_not_change_task_or_notice(tmp_path):
    app=make_app(tmp_path)
    with TestClient(app) as client:
        async def prepare():
            worker=app.state.automation;db=app.state.db;worker.configure(True,True)
            message(db)
            original=worker.model_factory().extract_auto
            async def two_tasks(msg):
                value=await original(msg);value['tasks'].append({'title':'参加项目说明会','location':'三楼会议室'})
                return value
            worker.model_factory().extract_auto=two_tasks
            await worker.run_once()
        client.portal.call(prepare)
        tasks=client.get('/api/tasks').json()['tasks'];assert len(tasks)==2
        assert all(t['automation_pending'] for t in tasks)
        first,second=tasks
        before=client.get('/api/tasks/'+first['id']).json()
        assert before['automation_pending'] is True
        notice=client.get('/api/automation/notices').json()['notices'][0]
        assert client.post('/api/automation/notices/'+notice['id']+'/acknowledge',headers=ORIGIN).status_code==200
        assert all(t['automation_pending'] for t in client.get('/api/tasks').json()['tasks']), 'dismissal is not review'
        url='/api/automation/tasks/'+first['id']+'/viewed'
        assert client.post(url).status_code==403
        assert client.post(url,headers=ORIGIN).status_code==200
        assert client.post(url,headers=ORIGIN).status_code==200
        after=client.get('/api/tasks/'+first['id']).json()
        assert after.pop('automation_pending') is False
        before.pop('automation_pending');assert after==before, 'review must not change title, deadline, status or version'
        assert next(t for t in client.get('/api/tasks').json()['tasks'] if t['id']==first['id'])['version']==first['version']
        assert client.get('/api/tasks/'+second['id']).json()['automation_pending'] is True
        assert client.post('/api/automation/tasks/missing/viewed',headers=ORIGIN).status_code==404
        assert client.get('/api/automation/notices').json()['notices']==[]
    with TestClient(make_app(tmp_path)) as client:
        values={t['id']:t['automation_pending'] for t in client.get('/api/tasks').json()['tasks']}
        assert values=={first['id']:False,second['id']:True}
        assert client.delete('/api/tasks/'+second['id']).status_code==200
        assert second['id'] not in client.app.state.automation.pending_task_ids()

def test_failed_review_keeps_task_pending_and_gives_retryable_error(tmp_path):
    app=make_app(tmp_path)
    with TestClient(app) as client:
        async def prepare():
            w=app.state.automation;w.configure(True,True);message(app.state.db);await w.run_once()
            app.state.db.conn.execute("CREATE TRIGGER reject_review BEFORE UPDATE ON automation_task_reviews BEGIN SELECT RAISE(ABORT,'test'); END")
            app.state.db.conn.commit()
        client.portal.call(prepare)
        task=client.get('/api/tasks').json()['tasks'][0]
        result=client.post('/api/automation/tasks/'+task['id']+'/viewed',headers=ORIGIN)
        assert result.status_code==503 and '重试' in result.json()['detail']
        assert client.get('/api/tasks/'+task['id']).json()['automation_pending'] is True

def test_first_upgrade_seeds_only_unacknowledged_existing_tasks(tmp_path):
    db=Database(tmp_path/'db');w=AutoOrganizer(db,Settings(llm_model='test'),lambda:Model(),asyncio.Lock())
    w.configure(True,True);message(db);asyncio.run(w.run_once())
    task=db.list_tasks()[0];notice=w.notices()[0]
    # Simulate old version with notices but no review table.
    db.conn.execute('DROP TABLE automation_task_reviews');db.conn.commit()
    w=AutoOrganizer(db,w.settings,w.model_factory,asyncio.Lock())
    assert w.pending_task_ids()=={task['id']}
    w.mark_viewed(task['id'])
    assert AutoOrganizer(db,w.settings,w.model_factory,asyncio.Lock()).pending_task_ids()==set(), 'restart never reimports unread popup'
    db.conn.execute('DROP TABLE automation_task_reviews');db.conn.commit();w.acknowledge(notice['id'])
    w=AutoOrganizer(db,w.settings,w.model_factory,asyncio.Lock())
    assert w.pending_task_ids()==set(), 'old acknowledged notices must not be resurrected'
    db.close()
