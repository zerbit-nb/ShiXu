import pytest
import httpx
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


@pytest.mark.parametrize('failure,expected', [(httpx.ConnectError('offline'),'无法连接'), (httpx.ReadTimeout('slow'),'超时'), (RuntimeError('模型输出不完整或被拒绝'),'不完整')])
def test_model_failure_and_retry_preserve_confirmation_boundary(tmp_path,failure,expected):
    class RecoveringModel:
        recovering=False
        async def extract(self,message):
            if not self.recovering:
                raise failure
            return {'is_actionable':True,'tasks':[{'title':'提交报告','deadline_text':'明天20:00'}]}
    model=RecoveringModel()
    with TestClient(create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=model)) as client:
        result=client.post('/api/messages/extract',json={'messages':[{'raw_text':'请明天20:00提交报告。','sent_at':'2026-10-10T09:00:00+08:00'}]}).json()['results'][0]
        assert expected in result['error']
        assert result['drafts']==[]
        assert client.get('/api/tasks').json()['tasks']==[]
        assert client.get('/api/drafts').json()['drafts']==[]
        model.recovering=True
        recovered=client.post('/api/messages/'+result['message']['id']+'/retry').json()
        assert recovered['error'] is None
        assert len(recovered['drafts'])==1
        assert recovered['drafts'][0]['fields']['deadline']=='2026-10-11T20:00:00+08:00'
        assert client.get('/api/tasks').json()['tasks']==[]
        assert client.post('/api/messages/'+result['message']['id']+'/retry').status_code==409
