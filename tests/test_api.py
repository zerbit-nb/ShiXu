import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.config import Settings


class LocalModelStub:
    async def extract(self, message):
        if message['raw_text'] == 'bad':
            raise ValueError('模型返回内容不是合法 JSON')
        if message['raw_text'] == '闲聊':
            return {'is_actionable': False, 'tasks': [], 'summary': '无需行动'}
        return {'is_actionable': True, 'tasks': [
            {'title': '提交材料', 'deadline_text': '明天 20:00', 'materials': ['成绩单']},
            {'title': '参加会议', 'location': '教室 A'}
        ], 'summary': '两项任务'}


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(), db_path=tmp_path / 'test.sqlite3', llm=LocalModelStub(), config_path=tmp_path / 'config.json')
    with TestClient(app) as c:
        yield c


def import_message(client, text='请明天 20:00 前提交材料，同时参加会议。'):
    return client.post('/api/messages/extract', json={'messages': [
        {'raw_text': text, 'sent_at': '2026-10-10T12:00:00+08:00', 'source_group': '测试群'}
    ]}).json()['results'][0]


def test_confirmation_is_required_and_idempotent(client):
    result = import_message(client)
    assert len(result['drafts']) == 2
    assert client.get('/api/tasks').json()['tasks'] == []
    draft = result['drafts'][0]
    assert draft['fields']['deadline'] == '2026-10-11T20:00:00+08:00'
    payload = {'confirmed': True, 'fields': draft['fields']}
    a = client.post(f"/api/drafts/{draft['id']}/confirm", json=payload)
    b = client.post(f"/api/drafts/{draft['id']}/confirm", json=payload)
    assert a.status_code == b.status_code == 200
    assert a.json()['id'] == b.json()['id']
    task = a.json()
    assert client.get(f"/api/messages/{task['message_id']}").json()['raw_text'] == '请明天 20:00 前提交材料，同时参加会议。'
    assert len(client.get('/api/tasks').json()['tasks']) == 1


def test_discard_and_rejection_never_create_task(client):
    draft = import_message(client)['drafts'][0]
    url = f"/api/drafts/{draft['id']}/confirm"
    assert client.post(url, json={'confirmed': False, 'fields': draft['fields']}).status_code == 422
    fields = {**draft['fields'], 'title': '  '}
    assert client.post(url, json={'confirmed': True, 'fields': fields}).status_code == 422
    client.post(f"/api/drafts/{draft['id']}/discard")
    assert client.post(url, json={'confirmed': True, 'fields': draft['fields']}).status_code == 409
    assert client.get('/api/tasks').json()['tasks'] == []


def test_batch_failure_isolated_and_non_actionable(client):
    response = client.post('/api/messages/extract', json={'messages': [
        {'raw_text': 'bad'}, {'raw_text': '闲聊'}, {'raw_text': '通知'}
    ]})
    failed, chat, good = response.json()['results']
    assert failed['message']['extraction_status'] == 'failed'
    assert failed['error']
    assert chat['drafts'] == []
    assert len(good['drafts']) == 2
    assert client.get('/api/tasks').json()['tasks'] == []


def test_task_edit_complete_delete_persist(client):
    draft = import_message(client)['drafts'][0]
    task = client.post(f"/api/drafts/{draft['id']}/confirm", json={'confirmed': True, 'fields': draft['fields']}).json()
    task_id = task['id']
    edited = client.patch(f'/api/tasks/{task_id}', json={'location': '线上', 'deadline': '2026-10-12'}).json()
    assert edited['deadline_precision'] == 'date_only'
    assert edited['location'] == '线上'
    assert client.patch(f'/api/tasks/{task_id}', json={'deadline': 'not a date'}).status_code == 422
    client.post(f'/api/tasks/{task_id}/complete')
    assert client.get('/api/tasks?view=completed').json()['tasks'][0]['status'] == 'completed'
    assert client.get('/api/tasks?view=pending').json()['tasks'] == []
    client.delete(f'/api/tasks/{task_id}')
    assert client.get(f'/api/tasks/{task_id}').status_code == 404
    assert client.post(f"/api/drafts/{draft['id']}/confirm", json={'confirmed': True, 'fields': draft['fields']}).status_code == 409


def test_foreign_origin_cannot_mutate_local_data(client):
    response = client.post('/api/messages/extract', headers={'origin': 'https://example.com'}, json={'messages': [{'raw_text': '通知'}]})
    assert response.status_code == 403


def test_manual_prefilled_fields_remain_draft_until_confirmation(client):
    fields={'title':'准备离散数学习题','deadline':'2026-10-25','description':'复习第五章','materials':['习题册'],'priority':'high'}
    response=client.post('/api/messages/manual',json={'raw_text':'手动创建的待办','fields':fields})
    assert response.status_code==200
    draft=response.json()['drafts'][0]
    assert draft['fields']['title']==fields['title']
    assert draft['fields']['deadline']=='2026-10-25'
    assert draft['fields']['materials']==['习题册']
    assert draft['fields']['description']==fields['description']
    assert draft['fields']['priority']=='high'
    assert draft['fields']['deadline_precision']=='date_only'
    assert 'fields' not in response.json()['message']
    assert client.get('/api/tasks').json()['tasks']==[]
    confirmed=client.post(f"/api/drafts/{draft['id']}/confirm",json={'confirmed':True,'fields':draft['fields']})
    assert confirmed.status_code==200
    assert confirmed.json()['title']==fields['title']


def test_manual_invalid_prefill_does_not_save_message(client):
    before=client.get('/api/inbox').json()['total']
    for fields in [{'title':'   '},{'title':'有效标题','deadline':'not-a-date'}]:
        assert client.post('/api/messages/manual',json={'raw_text':'手动创建的待办','fields':fields}).status_code==422
    assert client.get('/api/inbox').json()['total']==before
    assert client.get('/api/drafts').json()['drafts']==[]
