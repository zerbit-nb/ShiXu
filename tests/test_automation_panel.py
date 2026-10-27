"""Unread panel must include task details and every page, without changing task data."""
import asyncio
import json
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from tests.test_auto_organize import Model, message

def test_notice_details_and_pagination(tmp_path):
    app=create_app(Settings(llm_model='test'),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=Model())
    with TestClient(app) as c:
        async def prepare():
            w=app.state.automation;db=app.state.db
            w.configure(True,True);message(db)
            assert w.processing_count()==1
            await w.run_once()
            assert w.processing_count()==0
            original=w.notices()[0]
            with db.conn:
                for i in range(32):
                    db.conn.execute('INSERT INTO automation_notices VALUES (?,?,?,?,0)',('extra-'+str(i),'wechat',json.dumps(original['tasks']),'2026-10-26T13:00:00+00:00'))
        c.portal.call(prepare)
        first=c.get('/api/automation/notices').json()
        assert first['total']==33 and len(first['notices'])==30
        item=first['notices'][0]['tasks'][0]
        assert item['title']=='提交实验报告' and item['deadline']=='2026-12-30T20:00:00+08:00'
        assert item['source_group']=='测试群' and item['status']=='pending'
        second=c.get('/api/automation/notices?offset=30').json()
        assert len(second['notices'])==3
        assert not {n['id'] for n in first['notices']} & {n['id'] for n in second['notices']}
        assert c.get('/api/automation/notices?offset=-1').status_code==422
        assert len(c.get('/api/tasks').json()['tasks'])==1
