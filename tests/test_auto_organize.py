"""Automatic creation must be opt-in, conservative, durable and race-safe."""
import asyncio
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.services.auto_organize import AutoOrganizer

ORIGIN = {"Origin": "http://testserver"}
TEXT = "通知：请于2026年12月30日20:00前提交实验报告。"

class Model:
    calls = 0
    async def extract_auto(self, message):
        self.calls += 1
        return {"decision": "notification", "evidence": "请于2026年12月30日20:00前提交实验报告",
                "is_actionable": True, "tasks": [{"title": "提交实验报告", "deadline_text": "2026年12月30日20:00", "materials": ["实验报告"]}]}

def message(db, source="qq", text=TEXT):
    return db.create_message(dict(source=source, source_group="测试群", sender="测试者", sent_at="2026-10-26T12:00:00+08:00", raw_text=text, extraction_status="received"))

def test_settings_default_off_validation_and_persistence(tmp_path):
    for n in range(2):
        with TestClient(create_app(db_path=tmp_path/"db", config_path=tmp_path/"config")) as c:
            data=c.get("/api/automation").json()
            assert data["enabled"] == bool(n) and data["allow_local"] is False
            if not n:
                assert c.put("/api/automation",json={"enabled":True,"allow_local":False}).status_code==403
                assert c.put("/api/automation",json={"enabled":"true","allow_local":False},headers=ORIGIN).status_code==422
                assert c.put("/api/automation",json={"enabled":True,"allow_local":False},headers=ORIGIN).status_code==200

@pytest.fixture
def setup(tmp_path):
    from app.database import Database
    db=Database(tmp_path/"db")
    settings=Settings(llm_model="test")
    model=Model()
    worker=AutoOrganizer(db,settings,lambda:model,asyncio.Lock())
    yield db,worker,model
    db.close()

def test_new_messages_only_local_permission_atomic_tasks_notices_and_duplicates(setup):
    db,w,m=setup
    old=message(db)
    w.configure(True,False)
    new=message(db)
    asyncio.run(w.run_once());assert m.calls==0
    w.configure(True,True)
    asyncio.run(w.run_once())
    tasks=db.list_tasks();assert len(tasks)==1 and tasks[0]["message_id"]==new["id"]
    assert db.get_message(old["id"])["extraction_status"]=="received"
    assert len(w.notices())==1
    asyncio.run(w.run_once());assert m.calls==1
    duplicate=message(db,source="wechat")
    asyncio.run(w.run_once());assert len(db.list_tasks())==1
    assert db.get_message(duplicate["id"])["extraction_status"]=="received"
    assert w.notices()[0]["tasks"][0]["id"]==tasks[0]["id"]
    w.acknowledge(w.notices()[0]["id"]);assert w.notices()==[]

@pytest.mark.parametrize("kind",["uncertain","other","warnings","bad_evidence","change","failed","trash","manual"])
def test_review_messages_never_create_tasks_or_disappear(setup,kind):
    db,w,m=setup;w.configure(True,True)
    item=message(db,source="manual" if kind=="manual" else "wechat",text="会议取消了" if kind=="change" else TEXT)
    if kind=="trash":
        db.conn.execute("INSERT INTO message_trash VALUES (?,?)",(item["id"],"now"));db.conn.commit()
    original=m.extract_auto
    async def result(msg):
        if kind=="failed":raise RuntimeError("secret-provider-response")
        data=await original(msg)
        if kind in {"uncertain","other"}:data["decision"]=kind
        if kind=="warnings":data["tasks"][0]["uncertain_fields"]=["deadline_text"]
        if kind=="bad_evidence":data["evidence"]="编造的原文"
        return data
    m.extract_auto=result
    asyncio.run(w.run_once())
    assert db.list_tasks()==[] and w.notices()==[]
    assert db.get_message(item["id"])["extraction_status"] in {"received","failed"}
    assert db.conn.execute("SELECT count(*) FROM drafts").fetchone()[0]==0

def test_disable_during_model_request_does_not_commit(setup):
    db,w,m=setup;w.configure(True,True);item=message(db)
    original=m.extract_auto
    async def result(msg):
        data=await original(msg);w.configure(False,True);return data
    m.extract_auto=result
    asyncio.run(w.run_once())
    assert not db.list_tasks() and not w.notices()
    assert db.get_message(item["id"])["extraction_status"]=="received"

def test_atomic_rollback_on_notice_write_failure(setup):
    db,w,m=setup;w.configure(True,True);item=message(db)
    db.conn.execute("CREATE TRIGGER reject_notice BEFORE INSERT ON automation_notices BEGIN SELECT RAISE(ABORT,'test'); END");db.conn.commit()
    asyncio.run(w.run_once())
    assert db.list_tasks()==[] and w.notices()==[]
    assert db.conn.execute('SELECT count(*) FROM drafts').fetchone()[0]==0
    assert db.get_message(item['id'])["extraction_status"]=="failed"

def test_unread_notices_and_processed_messages_survive_restart(setup):
    db,w,m=setup;w.configure(True,True);message(db)
    asyncio.run(w.run_once());notice=w.notices()[0]
    reopened=AutoOrganizer(db,w.settings,lambda:m,asyncio.Lock())
    asyncio.run(reopened.run_once());assert m.calls==1
    assert reopened.notices()==[notice]
    reopened.acknowledge(notice['id'])
    assert AutoOrganizer(db,w.settings,lambda:m,asyncio.Lock()).notices()==[]

def test_disable_and_reenable_skips_messages_received_while_off(setup):
    db,w,m=setup;w.configure(True,True);w.configure(False,True);message(db)
    w.configure(True,True);asyncio.run(w.run_once());assert m.calls==0

def test_model_switch_during_request_keeps_message_for_review(setup):
    db,w,m=setup;w.configure(True,True);message(db)
    original=m.extract_auto
    async def result(msg):
        data=await original(msg);w.settings.llm_model='different-model';return data
    m.extract_auto=result
    asyncio.run(w.run_once());assert not db.list_tasks()

def test_shutdown_cancels_model_and_preserves_message(setup):
    db,w,m=setup;w.configure(True,True);item=message(db)
    async def scenario():
        entered=asyncio.Event()
        async def result(msg):entered.set();await asyncio.Event().wait()
        m.extract_auto=result
        task=asyncio.create_task(w.run_once());await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(scenario())
    assert not db.list_tasks() and db.get_message(item['id'])['extraction_status']=='received'

def test_background_loop_runs_without_webpage(tmp_path):
    import time
    model=Model()
    app=create_app(Settings(llm_model='test'),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=model)
    with TestClient(app) as c:
        c.put('/api/automation',json={'enabled':True,'allow_local':True},headers=ORIGIN)
        c.portal.call(lambda:message(app.state.db))
        for _ in range(60):
            if c.get('/api/automation/notices').json()['notices']:break
            time.sleep(.1)
        assert len(c.get('/api/tasks').json()['tasks'])==1
        assert c.get('/api/automation/notices').json()['notices']

@pytest.mark.parametrize('provider',['local','openai','deepseek'])
def test_automatic_model_request_schema_and_destination(provider):
    import httpx,json
    from app.services.llm_service import LLMService,AutoExtractionResult
    settings=Settings(provider=provider,llm_model='test-model',api_key='test-only-key')
    settings.validate()
    def handler(request):
        payload=json.loads(request.content)
        assert 'decision' in payload['messages'][0]['content']
        assert TEXT in json.loads(payload['messages'][1]['content'])['raw_text']
        assert request.url.host=={'local':'127.0.0.1','openai':'api.openai.com','deepseek':'api.deepseek.com'}[provider]
        if provider=='local':
            schema=payload['response_format']['json_schema']['schema']
            assert schema['additionalProperties'] is False and 'decision' in schema['required'] and 'evidence' in schema['required']
        value={'decision':'other','evidence':'','is_actionable':False,'tasks':[]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]})
    result=asyncio.run(LLMService(settings,transport=httpx.MockTransport(handler)).extract_auto({'raw_text':TEXT}))
    assert AutoExtractionResult.model_validate(result).decision=='other'

def test_real_wechat_ingestion_replay_creates_one_task(tmp_path):
    from app.services.wechat_store import bind,baseline,commit_batch
    from tests.test_wechat_store import PROFILE,IDENTITY,row
    app=create_app(Settings(llm_model='test'),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=Model())
    with TestClient(app) as c:
        c.put('/api/automation',json={'enabled':True,'allow_local':True},headers=ORIGIN)
        async def scenario():
            db=app.state.db
            scope=bind(db,PROFILE,IDENTITY);baseline(db,scope,{'message_0.db':0})
            before,after={'message_0.db':0},{'message_0.db':1}
            rows=[dict(row(),content=TEXT)]
            commit_batch(db,scope,PROFILE,before,rows,after)
            await app.state.automation.run_once()
            commit_batch(db,scope,PROFILE,before,rows,after)
            await app.state.automation.run_once()
        c.portal.call(scenario)
        assert len(c.get('/api/tasks').json()['tasks'])==1
        notice=c.get('/api/automation/notices').json()['notices'][0]
        assert notice['source']=='wechat'
        assert c.post('/api/automation/notices/'+notice['id']+'/acknowledge').status_code==403
        assert c.post('/api/automation/notices/'+notice['id']+'/acknowledge',headers=ORIGIN).status_code==200
        assert c.get('/api/automation/notices').json()['notices']==[]

def test_multi_task_message_commits_all_or_keeps_all_for_review(setup):
    db,w,m=setup;w.configure(True,True);message(db)
    original=m.extract_auto
    async def result(msg):
        value=await original(msg)
        value['tasks'].append({'title':'参加项目说明会','location':'三楼会议室'})
        return value
    m.extract_auto=result
    asyncio.run(w.run_once())
    assert len(db.list_tasks())==2 and len(w.notices()[0]['tasks'])==2
