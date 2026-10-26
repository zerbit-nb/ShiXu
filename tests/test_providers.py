import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.llm_service import LLMService, parse_model_json


@pytest.mark.parametrize('content', [
    '<think>我需要先分析，但最终只给 JSON。</think>\n{"is_actionable":false,"tasks":[],"summary":"无任务"}',
    '下面是结果：\n```json\n{"is_actionable":false,"tasks":[],"summary":"无任务"}\n```',
])
def test_reasoning_wrappers_are_removed_before_json_validation(content):
    assert parse_model_json(content)['tasks'] == []


def test_switch_preserves_profiles_and_never_returns_secrets(tmp_path):
    config = tmp_path/'config.json'
    with TestClient(create_app(Settings(),db_path=tmp_path/'db',config_path=config)) as client:
        response=client.put('/api/config',json={'provider':'deepseek','llm_model':'deepseek-chat','api_key':'test-not-real-key'})
        assert response.status_code == 200
        assert response.json()['profiles']['deepseek']['has_api_key']
        assert 'test-not-real-key' not in response.text
        assert 'test-not-real-key' not in config.read_text(encoding='utf-8')
        client.put('/api/config',json={'provider':'local','llm_base_url':'http://127.0.0.1:1234','llm_model':'Qwen3.8-27B-GGUF'})
        client.put('/api/config',json={'provider':'deepseek','llm_model':'deepseek-chat','api_key':''})
        assert client.get('/api/config').json()['profiles']['deepseek']['has_api_key']
        assert client.get('/api/config').json()['profiles']['local']['llm_model']=='Qwen3.8-27B-GGUF'
    settings=Settings();settings.load(config)
    assert settings.provider=='deepseek'
    assert settings.api_key=='test-not-real-key'


def test_cloud_destination_cannot_be_overridden(tmp_path):
    with TestClient(create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config')) as client:
        response=client.put('/api/config',json={'provider':'openai','llm_base_url':'https://evil.example/v1','llm_model':'example','api_key':'test-key'})
        assert response.status_code==422


def test_validation_never_echoes_submitted_key(tmp_path):
    with TestClient(create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config')) as client:
        key='private-'*300
        response=client.put('/api/config',json={'provider':'openai','api_key':key})
        assert response.status_code==422
        assert 'private-' not in response.text


@pytest.mark.parametrize('provider,host,model', [('openai','api.openai.com','user-selected-model'),('deepseek','api.deepseek.com','deepseek-chat'),('local','127.0.0.1','Qwen3.8-27B-GGUF')])
def test_official_provider_request_and_model_list(provider,host,model):
    settings=Settings(provider=provider,llm_model=model,api_key='test-only-key')
    settings.validate()
    captured=[]
    def handler(request):
        captured.append(request)
        assert request.url.host==host
        if provider!='local': assert request.headers['authorization']=='Bearer test-only-key'
        else: assert 'authorization' not in request.headers
        if request.method=='GET': return httpx.Response(200,json={'data':[{'id':model}]})
        payload=json.loads(request.content)
        assert payload['model']==model
        assert payload['messages'][1]['content'].find('提交测试材料')>=0
        if provider=='openai': assert 'max_completion_tokens' in payload and 'temperature' not in payload
        if provider=='deepseek': assert payload['response_format']=={'type':'json_object'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"is_actionable":false,"tasks":[],"summary":"测试"}'}}]})
    import asyncio
    async def run():
        service=LLMService(settings,transport=httpx.MockTransport(handler))
        assert await service.models()==[model]
        assert (await service.extract({'raw_text':'提交测试材料'}))['tasks']==[]
    asyncio.run(run())


def test_missing_key_fails_before_network():
    settings=Settings(provider='openai',llm_model='example',api_key='')
    settings.validate()
    import asyncio
    with pytest.raises(RuntimeError,match='API Key'):
        asyncio.run(LLMService(settings).extract({'raw_text':'通知'}))
