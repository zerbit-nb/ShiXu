import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.qq_login import LoginError
from tests.test_qq_login import service, upstream

class QuickUpstream:
    def __init__(self):
        self.ids=['12345678','87654321']
        self.info=[{'uin':'12345678','nickName':'测试账号','uid':'private-uid','facePath':'private-path','token':'private-token'}]
        self.online=False
        self.fail=False
        self.sent=[]
        self.base=upstream()
    def __call__(self,r):
        action=r.url.path.rsplit('/',1)[-1]
        if action=='GetQuickLoginList':data=self.ids
        elif action=='GetQuickLoginListNew':data=self.info
        elif action=='SetQuickLogin':
            self.sent.append(json.loads(r.content))
            if self.fail:return httpx.Response(200,json={'code':-1,'message':'unknown private-token'})
            data=None
        elif action=='CheckLoginStatus':data={'isLogin':self.online,'loginPhase':'waiting_qrcode','qrcodeurl':'https://qq.com/test-only-qr'}
        elif action=='GetQQLoginInfo':data={'uin':'12345678'}
        else:return self.base(r)
        return httpx.Response(200,json={'code':0,'data':data})

def test_list_safe_fields_and_no_login_side_effect(tmp_path):
    up=QuickUpstream();up.ids+=['bad', '12345678', True]
    login=service(tmp_path,up)
    async def flow():
        result=await login.quick_accounts()
        assert result['accounts']==[{'account_id':'12345678','nickname':'测试账号'},{'account_id':'87654321','nickname':''}]
        assert 'private' not in json.dumps(result)
        assert not up.sent
    asyncio.run(flow())

def test_empty_and_invalid_lists(tmp_path):
    up=QuickUpstream();login=service(tmp_path,up)
    async def flow():
        up.ids=[];assert (await login.quick_accounts())['accounts']==[]
        up.ids={'token':'private-token'}
        with pytest.raises(LoginError):await login.quick_accounts()
    asyncio.run(flow())

def test_explicit_quick_login_revalidates_and_waits_for_online(tmp_path):
    up=QuickUpstream();login=service(tmp_path,up)
    async def flow():
        result=await login.quick_login('12345678')
        assert result['state']=='submitted' and not result['online']
        assert up.sent==[{'uin':'12345678'}]
        assert (await login.status('12345678'))['state']=='submitted'
        up.online=True;assert (await login.status('87654321'))['account_mismatch']
    asyncio.run(flow())

def test_missing_account_and_failure_do_not_fake_success(tmp_path):
    up=QuickUpstream();login=service(tmp_path,up)
    async def flow():
        with pytest.raises(LoginError):await login.quick_login('99999999')
        assert not up.sent
        up.fail=True
        with pytest.raises(LoginError):await login.quick_login('12345678')
        status=await login.status('12345678')
        assert status['failure_stage']=='quick_login' and not status['online']
        assert 'private' not in json.dumps(status)
    asyncio.run(flow())

def test_paused_policy_never_starts_or_logs_in(tmp_path):
    up=QuickUpstream();login=service(tmp_path,up);login.policy.write('exited')
    async def flow():
        assert (await login.quick_accounts())['accounts']==[]
        with pytest.raises(LoginError):await login.quick_login('12345678')
        assert not up.sent
    asyncio.run(flow())

def test_routes_origin_validation_and_business_data(tmp_path):
    app=create_app(config_path=tmp_path/'config.json',db_path=tmp_path/'db.sqlite');up=QuickUpstream()
    with TestClient(app) as c:
        app.state.qq_login=service(tmp_path,up)
        response=c.get('/api/qq/login/quick/accounts')
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert len(response.json()['accounts'])==2
        assert c.post('/api/qq/login/quick',json={'account_id':'12345678'}).status_code==403
        headers={'Origin':'http://testserver'}
        assert c.post('/api/qq/login/quick',headers=headers,json={'account_id':'bad'}).status_code==422
        assert c.post('/api/qq/login/quick',headers=headers,json={'account_id':'12345678'}).json()['state']=='submitted'
        assert c.get('/api/tasks').json()['tasks']==[]
        assert c.get('/api/qq/inbox').json()['messages']==[]
