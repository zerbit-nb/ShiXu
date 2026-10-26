import asyncio
import hashlib
import json
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.qq_login import LoginError
from tests.test_qq_login import service,upstream

PRIVATE_URL='https://accounts.qq.com/device?sig=private-sig&uin-token=private-uin-token'
PRIVATE_SIG='private-original-sig'
PRIVATE_TOKEN='private-poll-token'
PRIVATE_SUCCESS='private-success-token'

class DeviceUpstream:
    def __init__(self):
        self.confirmed=False
        self.scanned=False
        self.online=False
        self.fail=False
        self.calls=[]
        self.second=0
        self.qr={'str_url':'https://accounts.qq.com/device-qr','bytes_token':PRIVATE_TOKEN}
    def __call__(self,r):
        action=r.url.path.rsplit('/',1)[-1];body=json.loads(r.content or b'{}');self.calls.append((action,body))
        if action=='login':data={'Credential':'private-management-token'}
        elif action=='CheckLoginStatus':data={'isLogin':self.online,'loginPhase':'initializing' if self.second else 'waiting_qrcode'}
        elif action=='GetQQLoginInfo':data={'uin':'12345678'}
        elif action=='PasswordLogin':data={'needNewDevice':True,'jumpUrl':PRIVATE_URL,'newDevicePullQrCodeSig':PRIVATE_SIG}
        elif action=='GetNewDeviceQRCode':data=self.qr
        elif action=='PollNewDeviceQR':
            if self.fail:raise httpx.ConnectError('private-transport-detail',request=r)
            data={'uint32_guarantee_status':1 if self.confirmed else 3 if self.scanned else 0,'str_nt_succ_token':PRIVATE_SUCCESS if self.confirmed else ''}
        elif action=='NewDeviceLogin':self.second+=1;data=None
        else:data=None
        return httpx.Response(200,json={'code':0,'data':data})

def assert_private(result):
    text=json.dumps(result)
    for value in [PRIVATE_SIG,PRIVATE_TOKEN,PRIVATE_SUCCESS,'private-sig','private-uin-token','test-password','private-management-token']:
        assert value not in text


def test_confirm_submits_second_login_once_and_waits_for_real_online(tmp_path):
    handler=DeviceUpstream();login=service(tmp_path,handler)
    async def flow():
        result=await login.password('12345678','test-password')
        assert result['state']=='device_verification' and result['qr_image'].startswith('data:image/png;base64,')
        ident=result['verification_id'];assert_private(result)
        assert (await login.status('12345678'))['state']=='device_verification'
        assert not any(x[0]=='PollNewDeviceQR' for x in handler.calls) # GET remains read-only
        handler.scanned=True
        assert (await login.poll_verification(ident))['state']=='device_scanned'
        handler.confirmed=True
        results=await asyncio.gather(login.poll_verification(ident),login.poll_verification(ident))
        assert all(r['state'] in {'submitted','initializing'} for r in results)
        assert handler.second==1
        body=next(b for a,b in handler.calls if a=='NewDeviceLogin')
        assert body=={'uin':'12345678','passwordMd5':hashlib.md5(b'test-password').hexdigest(),'newDevicePullQrCodeSig':PRIVATE_SUCCESS}
        assert login.device.pending is None
        handler.online=True
        assert (await login.status('12345678'))['online']
        assert all('test-password' not in json.dumps(b) for a,b in handler.calls)
    asyncio.run(flow())


def test_cancel_expire_and_refresh_remove_private_material(tmp_path):
    handler=DeviceUpstream();login=service(tmp_path,handler)
    async def flow():
        result=await login.password('12345678','test-password');ident=result['verification_id']
        assert (await login.cancel_verification(ident))['state']=='verification_cancelled'
        assert login.device.pending is None
        assert (await login.poll_verification(ident))['state']=='verification_cancelled'
        login.last_password=0
        result=await login.password('12345678','test-password');login.device.pending.expires_at=time.monotonic()-1
        assert (await login.poll_verification(result['verification_id']))['state']=='verification_expired'
        assert login.device.pending is None
        login.last_password=0
        await login.password('12345678','test-password');await login.refresh('12345678')
        assert login.device.pending is None
        login.last_password=0
        await login.password('12345678','test-password');login.clear_cache();assert login.device.pending is None
    asyncio.run(flow())


def test_timeout_timer_clears_material_without_browser_poll(tmp_path):
    login=service(tmp_path,DeviceUpstream())
    async def flow():
        login.device.ttl=.01
        await login.password('12345678','test-password');await asyncio.sleep(.03)
        assert login.device.pending is None
        assert login.device.view()['state']=='verification_expired'
    asyncio.run(flow())


def test_stale_challenge_cannot_cancel_new_attempt(tmp_path):
    login=service(tmp_path,DeviceUpstream())
    async def flow():
        old=await login.password('12345678','test-password');login.last_password=0
        new=await login.password('12345678','test-password')
        with pytest.raises(LoginError):await login.cancel_verification(old['verification_id'])
        assert login.device.pending is not None and login.device.view()['verification_id']==new['verification_id']
    asyncio.run(flow())


@pytest.mark.parametrize('qr',[{'str_url':'https://evil.example/x','bytes_token':PRIVATE_TOKEN},{'str_url':'https://qq.com/x'}, {'str_url':'https://qq.com/x','bytes_token':PRIVATE_TOKEN,'ActionStatus':'FAIL','ErrorCode':5}])
def test_invalid_qr_never_retains_password_digest(tmp_path,qr):
    handler=DeviceUpstream();handler.qr=qr;login=service(tmp_path,handler)
    async def flow():
        with pytest.raises(LoginError):await login.password('12345678','test-password')
        assert login.device.pending is None
    asyncio.run(flow())


def test_poll_failure_reports_retry_without_false_success(tmp_path):
    handler=DeviceUpstream();login=service(tmp_path,handler)
    async def flow():
        result=await login.password('12345678','test-password');handler.fail=True
        with pytest.raises(LoginError) as error:await login.poll_verification(result['verification_id'])
        assert 'private-transport' not in error.value.message
        assert login.device.pending is not None and handler.second==0
    asyncio.run(flow())


def test_verification_routes_same_origin_and_no_secrets(tmp_path):
    app=create_app(config_path=tmp_path/'config.json',db_path=tmp_path/'db.sqlite');handler=DeviceUpstream()
    with TestClient(app) as client:
        app.state.qq_login=service(tmp_path,handler)
        origin={'Origin':'http://testserver'}
        response=client.post('/api/qq/login/password',headers=origin,json={'account_id':'12345678','password':'test-password'})
        assert response.status_code==200
        data=response.json();assert_private(data)
        for route in ['verification/poll','verification/cancel']:
            assert client.post('/api/qq/login/'+route,json={'verification_id':data['verification_id']}).status_code==403
        response=client.post('/api/qq/login/verification/poll',headers=origin,json={'verification_id':data['verification_id']})
        assert response.status_code==200 and response.headers['cache-control']=='no-store';assert_private(response.json())
        assert client.get('/api/tasks').json()['tasks']==[]


def test_initialization_error_is_not_hidden_by_submitted_state(tmp_path):
    handler=DeviceUpstream();login=service(tmp_path,handler)
    original=login.call
    async def flow():
        result=await login.password('12345678','test-password');handler.confirmed=True
        await login.poll_verification(result['verification_id'])
        async def failed_status(route,payload=None):
            if route=='CheckLoginStatus':return {'isLogin':False,'loginError':{'message':'private-upstream-error'}},'http://127.0.0.1:6100'
            return await original(route,payload)
        login.call=failed_status
        status=await login.status('12345678')
        assert status['state']=='login_error'
        assert 'private-upstream-error' not in json.dumps(status)
    asyncio.run(flow())


def test_native_fallback_tokens_and_signature(tmp_path):
    handler=DeviceUpstream();handler.qr={'str_url':'https://qq.com/verify?str_url=opaque-token'};login=service(tmp_path,handler)
    original=login.call
    async def flow():
        result=await login.password('12345678','test-password')
        assert login.device.pending.token=='b3BhcXVlLXRva2Vu'
        async def no_success_token(route,payload=None):
            if route=='PollNewDeviceQR':return {'uint32_guarantee_status':1},'http://127.0.0.1:6100'
            return await original(route,payload)
        login.call=no_success_token
        await login.poll_verification(result['verification_id'])
        assert next(b for a,b in handler.calls if a=='NewDeviceLogin')['newDevicePullQrCodeSig']==PRIVATE_SIG
    asyncio.run(flow())
