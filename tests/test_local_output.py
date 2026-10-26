import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.services.extraction import normalize_extraction
from app.services.llm_service import LLMService, parse_model_json


def test_local_requests_constrain_task_structure():
    def respond(request):
        payload = json.loads(request.content)
        output_format = payload.get('response_format', {})
        assert output_format.get('type') == 'json_schema'
        schema = output_format['json_schema']['schema']
        assert schema['additionalProperties'] is False
        assert schema['properties']['tasks']['type'] == 'array'
        task_ref = schema['properties']['tasks']['items']['$ref'].split('/')[-1]
        assert schema['$defs'][task_ref]['type'] == 'object'
        assert set(schema['$defs'][task_ref]['required']) == set(schema['$defs'][task_ref]['properties'])
        assert 'summary' in schema['required']
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
            'role': 'assistant', 'content': '{"is_actionable":false,"tasks":[],"summary":"无任务"}',
            'reasoning_content': '', 'tool_calls': [],
        }}]})
    result = asyncio.run(LLMService(Settings(llm_model='qwen3.8-27b'), transport=httpx.MockTransport(respond)).extract({'raw_text': '测试通知'}))
    assert normalize_extraction(result, None) == []


def test_qwen_explanation_and_fenced_json_remain_validated():
    content = '''根据提供的文本，这是一条提交实验报告的通知。
**分析：**
- title: 提交实验报告
**JSON 输出：**
```json
{"is_actionable":true,"tasks":[{"title":"提交实验报告","description":null,"deadline_text":"明天 20:00 前","deadline_iso":null,"location":null,"target_audience":null,"materials":[],"format_requirement":null,"submit_method":null,"priority":"normal","uncertain_fields":["deadline_iso"],"reason":"相对日期需核对"}],"summary":"提交实验报告"}
```'''
    draft = normalize_extraction(parse_model_json(content), None)[0]
    assert draft['fields']['title'] == '提交实验报告'
    assert draft['fields']['deadline'] is None
    assert draft['warnings']


@pytest.mark.parametrize('content', ['没有可以提取的 JSON', '{"is_actionable":true,"tasks":["提交材料"]}'])
def test_invalid_model_output_cannot_become_a_task(content):
    with pytest.raises(ValueError):
        normalize_extraction(parse_model_json(content), None)
