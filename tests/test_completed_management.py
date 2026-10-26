import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(), db_path=tmp_path/'db', config_path=tmp_path/'config')) as c:
        yield c

def add(c,title,status='complete'):
    d=c.post('/api/messages/manual',json={'raw_text':title}).json()['drafts'][0]
    t=c.post('/api/drafts/'+d['id']+'/confirm',json={'confirmed':True,'duplicate_reviewed':True,'fields':{'title':title}}).json()
    if status:c.post('/api/tasks/'+t['id']+'/'+status)
    return t

def targets(c):
    return [{'id':t['id'],'version':t['version']} for t in c.get('/api/tasks?view=completed').json()['tasks']]

@pytest.mark.parametrize('action',['restore','delete'])
def test_confirm_scope_and_originals(client,action):
    a=add(client,'课程A实验');b=add(client,'课程B报名');p=add(client,'课程C会议',None);c=add(client,'课程D安排','cancel');chosen=targets(client);url='/api/completed-tasks/manage'
    assert client.post(url,json={'action':action,'confirmed':False,'tasks':chosen}).status_code==422
    assert len(targets(client))==2
    r=client.post(url,json={'action':action,'confirmed':True,'tasks':chosen})
    assert r.status_code==200 and r.json()['affected']==2
    assert targets(client)==[]
    assert client.get('/api/tasks/'+p['id']).json()['status']=='pending'
    assert client.get('/api/tasks/'+c['id']).json()['status']=='cancelled'
    for t in [a,b]:
        assert client.get('/api/messages/'+t['message_id']).status_code==200
        r=client.get('/api/tasks/'+t['id'])
        if action=='delete':assert r.status_code==404
        else:assert r.json()['status']=='pending'

@pytest.mark.parametrize('change',['edit','reopen','delete'])
def test_changed_target_rejects_whole_batch(client,change):
    a=add(client,'课程A实验');b=add(client,'课程B报名');chosen=targets(client)
    if change=='edit':client.patch('/api/tasks/'+b['id'],json={'title':'修改后的标题'})
    elif change=='reopen':client.post('/api/tasks/'+b['id']+'/reopen')
    else:client.delete('/api/tasks/'+b['id'])
    r=client.post('/api/completed-tasks/manage',json={'action':'delete','confirmed':True,'tasks':chosen})
    assert r.status_code==409
    assert client.get('/api/tasks/'+a['id']).json()['status']=='completed'

def test_invalid_selection_and_transaction_rollback(client):
    a=add(client,'课程A实验');b=add(client,'课程B报名');chosen=targets(client);url='/api/completed-tasks/manage'
    for values in [[],[chosen[0],chosen[0]]]:
        assert client.post(url,json={'action':'delete','confirmed':True,'tasks':values}).status_code==422
    db=client.app.state.db
    db.conn.execute("CREATE TRIGGER reject_delete BEFORE DELETE ON tasks WHEN OLD.id='"+b['id']+"' BEGIN SELECT RAISE(ABORT,'delete failure'); END")
    db.conn.commit()
    with pytest.raises(Exception,match='delete failure'):
        client.post(url,json={'action':'delete','confirmed':True,'tasks':chosen})
    assert len(targets(client))==2
