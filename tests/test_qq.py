import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from tests.test_api import LocalModelStub

TOKEN = 'test-only-token-1234567890'

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(), db_path=tmp_path/'db', config_path=tmp_path/'config', llm=LocalModelStub())) as c:
        yield c


def configure(c, **extra):
    return c.put('/api/qq/config', json={'enabled':True, 'account_id':'12345678', 'group_ids':['87654321'], 'token':TOKEN, **extra})


def event(**extra):
    return {'post_type':'message', 'message_type':'group', 'self_id':12345678, 'group_id':87654321, 'message_id':-123, 'user_id':23456789, 'time':1791763200, 'sender':{'card':'班长'}, 'message':[{'type':'text','data':{'text':'请明天20:00前提交材料。'}}], **extra}


def send(c, payload=None, token=TOKEN):
    body=json.dumps(payload or event(),ensure_ascii=False).encode()
    sig='sha1='+hmac.new(token.encode(),body,hashlib.sha1).hexdigest()
    return c.post('/api/qq/events',content=body,headers={'content-type':'application/json','x-signature':sig})


def test_default_disabled_auth_and_scope(client):
    assert client.get('/api/qq/config').json()['enabled'] is False
    assert send(client).status_code == 403
    assert configure(client).status_code == 200
    assert send(client,token='wrong').status_code == 401
    for payload in [event(group_id=11111111),event(self_id=11111111),event(message_type='private'),{'post_type':'meta_event','self_id':12345678}]:
        assert send(client,payload).status_code == 204
    assert client.get('/api/qq/inbox').json()['messages'] == []
    assert send(client).status_code == 204
    assert client.get('/api/tasks').json()['tasks'] == []
    assert client.get('/api/drafts').json()['drafts'] == []


def test_receive_duplicate_and_manual_confirmation(client):
    configure(client)
    assert send(client).status_code == send(client).status_code == 204
    rows=client.get('/api/qq/inbox').json()['messages'];assert len(rows)==1
    m=rows[0];assert m['source']=='qq';assert m['sender']=='班长';assert m['source_group']=='QQ 群 87654321';assert m['sent_at'].endswith('+08:00')
    url='/api/qq/messages/'+m['id']+'/process'
    result=client.post(url,json={'action':'manual'}).json()
    assert len(result['drafts'])==1
    assert client.post(url,json={'action':'manual'}).status_code==409
    assert len(client.get('/api/drafts').json()['drafts'])==1
    d=result['drafts'][0]
    task=client.post('/api/drafts/'+d['id']+'/confirm',json={'confirmed':True,'fields':{'title':'提交材料'}})
    assert task.status_code==200
    assert send(client).status_code==204
    assert len(client.get('/api/qq/inbox').json()['messages'])==1


def test_analysis_failure_retry_and_ignore(client):
    configure(client);send(client,event(message=[{'type':'text','data':{'text':'bad'}}]))
    m=client.get('/api/qq/inbox').json()['messages'][0];url='/api/qq/messages/'+m['id']+'/process'
    result=client.post(url,json={'action':'analyze'}).json();assert result['error'];assert result['message']['extraction_status']=='failed'
    assert client.post(url,json={'action':'manual'}).status_code==200
    assert client.post(url,json={'action':'ignore'}).status_code==409
    send(client,event(message_id=99));m=client.get('/api/qq/inbox').json()['messages'][0]
    assert client.post('/api/qq/messages/'+m['id']+'/process',json={'action':'ignore'}).status_code==200
    assert client.get('/api/tasks').json()['tasks']==[]


def test_secrets_validation_and_stop(client):
    assert configure(client,group_ids=[]).status_code==422
    assert configure(client,token='short').status_code==422
    configure(client)
    assert TOKEN not in client.get('/api/qq/config').text
    assert client.get('/api/qq/config').json()['has_token'] is True
    assert configure(client,enabled=False,token=None).status_code==200
    assert send(client).status_code==403
    assert client.post('/api/messages/manual',json={'raw_text':'手动通知'}).status_code==200


def test_media_only_and_invalid_event(client):
    configure(client)
    assert send(client,event(message=[{'type':'image','data':{'file':'secret'}}])).status_code==204
    assert client.get('/api/qq/inbox').json()['messages']==[]
    assert send(client,event(time='invalid')).status_code==422
    assert client.post('/api/qq/events',content=b'x'*262145).status_code==413


def test_restart_keeps_config_receipts_and_messages(tmp_path):
    kwargs=dict(db_path=tmp_path/'db',config_path=tmp_path/'config',llm=LocalModelStub())
    with TestClient(create_app(Settings(),**kwargs)) as c:
        configure(c);send(c)
    with TestClient(create_app(Settings(),**kwargs)) as c:
        assert c.get('/api/qq/config').json()['enabled']
        assert send(c).status_code==204
        assert len(c.get('/api/qq/inbox').json()['messages'])==1



def test_bad_segments_empty_text_and_size_limits(client):
    configure(client)
    for message in [[{'type':'text','data':{'text':123}}], [{'type':'text','data':[]}], [123]]:
        assert send(client,event(message=message)).status_code==422
    assert send(client,event(message=[{'type':'text','data':{'text':'x'*20001}}])).status_code==422
    assert send(client,event(message=[])).status_code==204
    assert client.get('/api/qq/inbox').json()['messages']==[]


def test_receipt_failure_rolls_back_original_message(client):
    configure(client)
    db=client.app.state.db
    db.conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON qq_receipts BEGIN SELECT RAISE(ABORT,'receipt failure'); END")
    db.conn.commit()
    with pytest.raises(Exception,match='receipt failure'):
        send(client)
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==0


def test_text_string_escaping_and_paging(client):
    configure(client)
    send(client,event(message='通知&#91;CQ:fake&#93;[CQ:image,file=secret]'))
    send(client,event(message_id=100))
    first=client.get('/api/qq/inbox?limit=1').json()
    second=client.get('/api/qq/inbox?limit=1&offset=1').json()
    assert first['total']==2 and len(first['messages'])==1
    assert first['messages'][0]['id']!=second['messages'][0]['id']
    assert second['messages'][0]['raw_text']=='通知[CQ:fake][非文本消息，未解析]'


def test_valid_analysis_reuses_sender_time_and_does_not_confirm(client):
    configure(client);send(client)
    message=client.get('/api/qq/inbox').json()['messages'][0]
    url='/api/qq/messages/'+message['id']+'/process'
    result=client.post(url,json={'action':'analyze'}).json()
    assert result['error'] is None and len(result['drafts'])==2
    assert result['message']['sent_at']==message['sent_at']
    assert all(d['message_id']==message['id'] for d in result['drafts'])
    assert client.post(url,json={'action':'analyze'}).status_code==409
    assert client.get('/api/tasks').json()['tasks']==[]


def test_status_disabled_and_isolated_not_installed(client):
    state=client.get('/api/qq/status').json()
    assert state['state']=='disabled' and state['received_count']==0
    configure(client);send(client)
    state=client.get('/api/qq/status').json()
    assert state['state']=='not_installed' and state['received_count']==1
    assert state['last_message_at']
    assert TOKEN not in json.dumps(state)
