from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings

def test_default_paused_controls_and_no_sensitive_input_echo(tmp_path):
    kwargs=dict(db_path=tmp_path/'db',config_path=tmp_path/'config')
    with TestClient(create_app(Settings(),**kwargs)) as c:
        assert c.get('/api/wechat/status').json()['state']=='paused'
        assert c.post('/api/wechat/start').status_code==409
        assert c.put('/api/wechat/config',json={'group_name':'测试群','account_alias':'private-account'}).status_code==200
        response=c.get('/api/wechat/config')
        assert response.json()['has_account'] and 'private-account' not in response.text
        bad=c.put('/api/wechat/config',json={'group_name':'','account_alias':'private-account'})
        assert bad.status_code==422 and 'private-account' not in bad.text
        assert c.post('/api/wechat/stop').json()['state']=='paused'
        assert c.get('/api/wechat/messages').json()=={'messages':[],'total':0}
        assert c.post('/api/wechat/start',headers={'origin':'https://evil.example'}).status_code==403
        assert c.get('/api/tasks').json()['tasks']==[]
    with TestClient(create_app(Settings(),**kwargs)) as c:
        assert c.get('/api/wechat/config').json()['group_name']=='测试群'
        assert c.get('/api/wechat/status').json()['state']=='paused'


def test_control_rejects_remote_client(tmp_path):
    app=create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config')
    with TestClient(app,client=('192.0.2.5',10000)) as c:
        assert c.get('/api/wechat/status').status_code==403
        assert c.post('/api/wechat/start').status_code==403

from app.services import wechat_store as store
from tests.test_api import LocalModelStub


def seed_wechat(db,texts):
    profile={'alias_hash':'c'*64,'group_name':'测试微信群'}
    scope=store.bind(db,profile,{'account':'a'*64,'group':'b'*64})
    store.baseline(db,scope,{'message_0.db':0})
    rows=[dict(shard='message_0.db',local_id=i+1,kind='text',content=text,sender=None,sent_at=None) for i,text in enumerate(texts)]
    store.commit_batch(db,scope,profile,{'message_0.db':0},rows,{'message_0.db':len(rows)})
    return [dict(r) for r in db.conn.execute('SELECT * FROM messages ORDER BY rowid')]


def test_wechat_manual_confirm_ownership_and_no_automatic_tasks(tmp_path):
    app=create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=LocalModelStub())
    with TestClient(app) as c:
        rows=c.portal.call(seed_wechat,app.state.db,['手动通知','忽略内容'])
        assert c.get('/api/drafts').json()['drafts']==[]
        assert c.get('/api/tasks').json()['tasks']==[]
        assert c.post('/api/wechat/messages/missing/process',json={'action':'manual'}).status_code==404
        unrelated=c.post('/api/messages/extract',json={'messages':[{'raw_text':'闲聊'}]}).json()['results'][0]['message']
        assert c.post('/api/wechat/messages/'+unrelated['id']+'/process',json={'action':'manual'}).status_code==404
        url='/api/wechat/messages/'+rows[0]['id']+'/process'
        result=c.post(url,json={'action':'manual'}).json()
        assert result['message']['extraction_status']=='ready'
        assert len(result['drafts'])==1
        assert c.post(url,json={'action':'manual'}).status_code==409
        assert c.get('/api/tasks').json()['tasks']==[]
        draft=result['drafts'][0]
        fields={**draft['fields'],'title':'已核对的微信群任务'}
        task=c.post('/api/drafts/'+draft['id']+'/confirm',json={'confirmed':True,'fields':fields})
        assert task.status_code==200 and c.get('/api/tasks').json()['tasks'][0]['source_group']=='测试微信群'
        assert c.get('/api/messages/'+rows[0]['id']).json()['raw_text']=='手动通知'
        ignored=c.post('/api/wechat/messages/'+rows[1]['id']+'/process',json={'action':'ignore'})
        assert ignored.json()['message']['extraction_status']=='ignored'
        assert len(c.get('/api/tasks').json()['tasks'])==1
        assert c.post(url,json={'action':'delete'}).status_code==422
        assert c.post(url,json={'action':'analyze'},headers={'origin':'https://evil.example'}).status_code==403


def test_wechat_analysis_failure_retry_and_source_preserved(tmp_path):
    class SwitchModel(LocalModelStub):
        calls=0
        fail=True
        async def extract(self,message):
            self.calls+=1
            if self.fail:raise ValueError('测试模型不可用')
            return await super().extract(message)
    model=SwitchModel()
    app=create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=model)
    with TestClient(app) as c:
        message=c.portal.call(seed_wechat,app.state.db,['原始通知 <script>不执行</script>'])[0]
        assert model.calls==0
        url='/api/wechat/messages/'+message['id']+'/process'
        result=c.post(url,json={'action':'analyze'}).json()
        assert result['error'] and result['message']['extraction_status']=='failed'
        assert c.get('/api/drafts').json()['drafts']==[]
        model.fail=False
        result=c.post(url,json={'action':'analyze'}).json()
        assert result['error'] is None and len(result['drafts'])==2
        assert result['message']['raw_text']==message['raw_text']
        assert result['message']['sent_at'] is None
        assert c.post(url,json={'action':'analyze'}).status_code==409
        assert c.get('/api/tasks').json()['tasks']==[]


def test_wechat_parallel_actions_cannot_duplicate_drafts(tmp_path):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered,release=threading.Event(),threading.Event()
    class BlockingModel(LocalModelStub):
        async def extract(self,message):
            entered.set()
            for _ in range(1000):
                if release.is_set():break
                await asyncio.sleep(.005)
            else:raise TimeoutError('test_release_timeout')
            return await super().extract(message)
    app=create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config',llm=BlockingModel())
    with TestClient(app) as c,ThreadPoolExecutor(max_workers=1) as pool:
        message=c.portal.call(seed_wechat,app.state.db,['并发测试通知'])[0]
        url='/api/wechat/messages/'+message['id']+'/process'
        first=pool.submit(c.post,url,json={'action':'analyze'})
        try:
            assert entered.wait(5)
            for action in ['analyze','manual','ignore']:
                assert c.post(url,json={'action':action}).status_code==409
            assert c.get('/api/drafts').json()['drafts']==[]
        finally:release.set()
        assert first.result(5).json()['error'] is None
        assert len(c.get('/api/drafts').json()['drafts'])==2
        assert c.get('/api/tasks').json()['tasks']==[]
