"""Conservative, reversible reception filtering for both message sources."""
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.reception_filter import is_trivial_reply
from app.services.wechat_store import bind, baseline, checkpoint, commit_batch
from tests.test_qq import configure, event, send
from tests.test_wechat_store import PROFILE, IDENTITY, row

ORIGIN={'Origin':'http://testserver'}

@pytest.mark.parametrize('text',['收到','收到。','好的！','谢谢～','OK!','哈哈哈','嗯嗯'])
def test_only_standalone_replies_match(text):
    assert is_trivial_reply(text)

@pytest.mark.parametrize('text',['会议取消了','地点改到三楼','收到后请提交材料','好的，明天交','收到？','@所有人 收到','收到\n请明天提交','请于周五前提交报名表','我不参加了','👍','1','你好',''])
def test_uncertain_or_actionable_messages_are_kept(text):
    assert not is_trivial_reply(text)

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=tmp_path/'db',config_path=tmp_path/'config')) as c:
        yield c

def enable(c,value=True):
    return c.put('/api/inbox/filter',json={'enabled':value},headers=ORIGIN)

def test_defaults_validation_origin_and_persistence(tmp_path):
    for attempt in range(2):
        with TestClient(create_app(db_path=tmp_path/'db',config_path=tmp_path/'config')) as c:
            assert c.get('/api/inbox/filter').json()=={'enabled':bool(attempt)}
            if not attempt:
                for headers in [{},{'Origin':'http://evil.invalid'}]:
                    assert c.put('/api/inbox/filter',json={'enabled':True},headers=headers).status_code==403
                for body in [{'enabled':'true'},{'enabled':1},{'enabled':True,'unknown':1}]:
                    assert c.put('/api/inbox/filter',json=body,headers=ORIGIN).status_code==422
                assert enable(c).json()=={'enabled':True}

def test_qq_new_messages_only_restoration_replay_and_disable(client):
    assert configure(client).status_code==200
    payload=lambda n,text:event(message_id=n,message=[{'type':'text','data':{'text':text}}])
    assert send(client,payload(1,'收到')).status_code==204
    assert enable(client).status_code==200
    for n,text in [(2,'收到。'),(3,'会议取消了'),(4,'收到后请提交材料')]:
        assert send(client,payload(n,text)).status_code==204
    assert client.get('/api/inbox').json()['total']==3
    trash=client.get('/api/inbox?folder=trash').json()
    assert trash['total']==1 and trash['messages'][0]['raw_text']=='收到。'
    ident=trash['messages'][0]['id']
    assert client.post('/api/inbox/'+ident+'/restore').status_code==200
    assert send(client,payload(2,'收到。')).status_code==204
    assert client.get('/api/inbox?folder=trash').json()['total']==0
    assert enable(client,False).status_code==200
    assert send(client,payload(5,'收到')).status_code==204
    assert client.get('/api/inbox').json()['total']==5
    assert client.get('/api/tasks').json()['tasks']==[]
    assert client.get('/api/drafts').json()['drafts']==[]

def test_wechat_cursor_replay_disable_and_atomic_receipts(client):
    db=client.app.state.db;scope=bind(db,PROFILE,IDENTITY);baseline(db,scope,{'message_0.db':0})
    assert enable(client).status_code==200
    events=[dict(row(1),content='好的'),dict(row(2),content='地点改到三楼')]
    before={'message_0.db':0};after={'message_0.db':2}
    commit_batch(db,scope,PROFILE,before,events,after)
    assert checkpoint(db,scope)==after
    assert client.get('/api/inbox').json()['total']==1
    trash=client.get('/api/inbox?folder=trash').json()
    assert trash['total']==1 and trash['messages'][0]['source']=='wechat'
    client.post('/api/inbox/'+trash['messages'][0]['id']+'/restore')
    commit_batch(db,scope,PROFILE,before,events,after)
    assert client.get('/api/inbox?folder=trash').json()['total']==0
    assert enable(client,False).status_code==200
    commit_batch(db,scope,PROFILE,after,[dict(row(3),content='好的')],{'message_0.db':3})
    assert client.get('/api/inbox').json()['total']==3
    assert db.conn.execute('SELECT count(*) FROM wechat_receipts').fetchone()[0]==3

def test_filter_failure_rolls_back_wechat_message_receipt_and_cursor(client):
    db=client.app.state.db;scope=bind(db,PROFILE,IDENTITY);baseline(db,scope,{'message_0.db':0});enable(client)
    db.conn.execute("CREATE TRIGGER reject_trash BEFORE INSERT ON message_trash BEGIN SELECT RAISE(ABORT,'test'); END");db.conn.commit()
    with pytest.raises(sqlite3.DatabaseError):
        commit_batch(db,scope,PROFILE,{'message_0.db':0},[dict(row(),content='收到')],{'message_0.db':1})
    assert checkpoint(db,scope)=={'message_0.db':0}
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    assert db.conn.execute('SELECT count(*) FROM wechat_receipts').fetchone()[0]==0

def test_save_failure_preserves_setting_and_no_manual_filter(client):
    db=client.app.state.db
    db.conn.execute("CREATE TRIGGER reject_setting BEFORE UPDATE ON reception_filter_settings BEGIN SELECT RAISE(ABORT,'private-error'); END");db.conn.commit()
    result=enable(client)
    assert result.status_code==503 and 'private-error' not in result.text
    assert client.get('/api/inbox/filter').json()=={'enabled':False}
    db.conn.execute('DROP TRIGGER reject_setting');db.conn.commit();enable(client)
    db.create_message(dict(source='manual',source_group=None,sender=None,sent_at=None,raw_text='收到',extraction_status='pending'))
    assert client.get('/api/inbox').json()['total']==1
