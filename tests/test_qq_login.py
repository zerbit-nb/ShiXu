import asyncio
import hashlib
import json
from contextlib import contextmanager
from unittest.mock import Mock
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.bridge import BridgeMonitor
from app.services.qq_login import QQLogin, LoginError
from tests.test_bridge import install


def service(root, handler):
    install(root)
    return QQLogin(BridgeMonitor(root, httpx.MockTransport(handler)))


def upstream(mode='waiting', calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request)
        path = request.url.path
        if path.endswith('/auth/login'):
            data = {'Credential': 'test-private-management-credential'}
        elif path.endswith('CheckLoginStatus'):
            data = {'isLogin': mode == 'online', 'loginPhase': 'waiting_qrcode', 'qrcodeurl': 'https://qq.com/test-only-qr'}
        elif path.endswith('GetQQLoginInfo'):
            data = {'uin': '12345678'}
        elif path.endswith('GetNewDeviceQRCode'):
            data = {'str_url':'https://qq.com/private-verification-material', 'bytes_token':'private-poll-token'}
        elif path.endswith('PasswordLogin'):
            if mode == 'challenge':
                data = {'needCaptcha': True, 'proofWaterUrl': 'https://qq.com/private-verification-material'}
            elif mode == 'newdevice':
                data = {'needNewDevice': True, 'jumpUrl': 'https://qq.com/private-verification-material', 'newDevicePullQrCodeSig': 'private-original-sig'}
            elif mode == 'failure':
                return httpx.Response(200, json={'code': -1, 'message': 'test-private-password secret-management-key'})
            else:
                data = None
        else:
            data = {'qrcodeurl': 'https://qq.com/test-only-qr'}
        return httpx.Response(200, json={'code': 0, 'data': data})
    return handler


def test_status_qr_local_image_and_online_mismatch(tmp_path):
    login = service(tmp_path, upstream())
    result = asyncio.run(login.status('12345678'))
    assert result['state'] == 'waiting_qrcode'
    assert result['qr_image'].startswith('data:image/png;base64,iVBOR')
    assert 'test-only-qr' not in json.dumps(result)
    login.bridge.transport = httpx.MockTransport(upstream('online'))
    result = asyncio.run(login.status('87654321'))
    assert result['online'] and result['account_mismatch']
    assert result['qr_image'] is None
    assert 'test-private-management-credential' not in json.dumps(result)


@pytest.mark.parametrize('value', ['http://qq.com/a', 'https://evil.example/a', 'https://qq.com.evil.example/a', 'https://u:p@qq.com/a', None, 'https://qq.com/'+('a'*2100)])
def test_untrusted_qr_not_rendered(value):
    assert QQLogin.qr_image(value) is None


@pytest.mark.parametrize('mode,state', [('waiting','submitted'), ('challenge','verification_required'), ('newdevice','device_verification')])
def test_password_hash_and_verification_redaction(tmp_path, mode, state):
    calls = []
    login = service(tmp_path, upstream(mode, calls))
    result = asyncio.run(login.password('12345678','test-private-password'))
    assert result['state'] == state
    request = next(r for r in calls if r.url.path.endswith('PasswordLogin'))
    assert json.loads(request.content) == {'uin': '12345678', 'passwordMd5': hashlib.md5(b'test-private-password').hexdigest()}
    assert 'test-private-password' not in request.content.decode()
    assert 'private-verification-material' not in json.dumps(result)
    assert 'test-private-password' not in repr(login.__dict__)
    with pytest.raises(LoginError) as error:
        asyncio.run(login.password('12345678','other'))
    assert error.value.state == 'rate_limited'


def test_password_failure_never_echoes_upstream(tmp_path):
    login = service(tmp_path, upstream('failure'))
    with pytest.raises(LoginError) as error:
        asyncio.run(login.password('12345678','test-private-password'))
    assert 'test-private-password' not in error.value.message
    assert 'secret-management-key' not in error.value.message


def test_2fa_and_unreachable(tmp_path):
    login = service(tmp_path, lambda r: httpx.Response(200,json={'code':0,'data':{'require2FA':True}}))
    with pytest.raises(LoginError) as error:
        asyncio.run(login.status(''))
    assert error.value.state == 'auth_failed'
    def fail(r):
        raise httpx.ConnectError('sensitive network detail',request=r)
    login.bridge.transport = httpx.MockTransport(fail)
    with pytest.raises(LoginError) as error:
        asyncio.run(login.status(''))
    assert error.value.state == 'not_running'
    assert 'sensitive' not in error.value.message


def test_concurrent_start_is_idempotent_and_quiet(tmp_path, monkeypatch):
    alive = False
    def handler(request):
        if not alive:
            raise httpx.ConnectError('not running',request=request)
        return httpx.Response(301,headers={'Location':'/webui/'})
    login = service(tmp_path, handler)
    @contextmanager
    def lock(folder):
        yield
    monkeypatch.setattr('app.services.qq_login.startup_lock',lock)
    monkeypatch.setattr('app.services.qq_login.boot_is_running',lambda path: False)
    monkeypatch.setattr('subprocess.CREATE_NO_WINDOW', 0x08000000, raising=False)
    monkeypatch.setattr('subprocess.CREATE_NEW_PROCESS_GROUP', 0x00000200, raising=False)
    def launch(*args, **kwargs):
        nonlocal alive
        alive = True
        assert kwargs['stdout'] == kwargs['stderr'] == -3
        assert kwargs['creationflags'] & 0x08000000
    popen = Mock(side_effect=launch)
    monkeypatch.setattr('app.services.qq_login.subprocess.Popen',popen)
    async def concurrent():
        return await asyncio.gather(login.start(),login.start())
    assert all(r['state']=='running' for r in asyncio.run(concurrent()))
    assert popen.call_count == 1


def test_routes_same_origin_no_store_and_no_data_changes(tmp_path):
    app = create_app(config_path=tmp_path/'config.json',db_path=tmp_path/'test.sqlite')
    with TestClient(app) as client:
        app.state.qq_login = service(tmp_path, upstream())
        origin = {'Origin':'http://testserver'}
        assert client.post('/api/qq/login/start').status_code == 403
        assert client.post('/api/qq/login/password',headers={'Origin':'https://evil.example'},json={'account_id':'12345678','password':'test-private-password'}).status_code == 403
        result = client.get('/api/qq/login/status')
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert not app.state.qq.enabled
        result = client.post('/api/qq/login/password',headers=origin,json={'account_id':'12345678','password':'test-private-password'})
        assert result.status_code == 200 and result.json()['state'] == 'submitted'
        result = client.post('/api/qq/login/password',headers=origin,json={'account_id':'oops','password':'test-private-password'})
        assert result.status_code == 422 and 'test-private-password' not in result.text
        assert client.get('/api/tasks').json()['tasks'] == []
        assert client.get('/api/qq/inbox').json()['messages'] == []



@pytest.mark.parametrize('failure', ['refused','timeout','invalid_device'])
def test_failed_password_feedback_survives_status_poll_and_clears_on_retry(tmp_path,failure):
    original=upstream();bad=True
    def handler(request):
        if bad and request.url.path.endswith('PasswordLogin'):
            if failure=='timeout':raise httpx.ReadTimeout('private-token-url',request=request)
            if failure=='invalid_device':return httpx.Response(200,json={'code':0,'data':{'needNewDevice':True}})
            return httpx.Response(200,json={'code':-1,'message':'test-private-password secret-management-key'})
        return original(request)
    login=service(tmp_path,handler)
    async def flow():
        nonlocal bad
        with pytest.raises(LoginError) as caught:await login.password('12345678','test-private-password')
        status=await login.status('12345678')
        assert status['state']==caught.value.state
        assert status['message']==caught.value.message
        assert status['qr_image'] is None
        assert status['failure_stage'] in {'password_submit','device_qr'}
        assert 'private' not in json.dumps(status)
        if failure=='timeout':assert caught.value.state=='password_timeout'
        bad=False;login.last_password=0
        await login.password('12345678','test-private-password')
        assert (await login.status('12345678'))['state']=='submitted'
        login.bridge.transport=httpx.MockTransport(upstream('online'))
        assert (await login.status('12345678'))['state']=='online'
    asyncio.run(flow())


def test_password_has_independent_authorization_wait_timeout(tmp_path):
    recorded=[];base=upstream()
    def handler(request):
        recorded.append((request.url.path,request.extensions['timeout']['read']))
        return base(request)
    login=service(tmp_path,handler)
    asyncio.run(login.password('12345678','test-private-password'))
    assert next(timeout for path,timeout in recorded if path.endswith('PasswordLogin'))==300
    assert next(timeout for path,timeout in recorded if path.endswith('CheckLoginStatus'))==15


@pytest.mark.parametrize('upstream_message,expected', [
    ('密码错误 https://qq.com/?token=private-token', '密码错误'),
    ('登录太频繁 private-token', '过于频繁'),
    ('需要验证码 https://qq.com/private-token', '安全验证'),
    ('新设备需要扫码验证 https://qq.com/private-token', '新设备验证'),
    ('uin is empty', '参数'),
    ('unknown private-token password', '未提供可识别'),
])
def test_password_rejection_safe_category(tmp_path,upstream_message,expected):
    base=upstream()
    def handler(request):
        if request.url.path.endswith('PasswordLogin'):
            return httpx.Response(200,json={'code':-1,'message':upstream_message})
        return base(request)
    login=service(tmp_path,handler)
    async def flow():
        with pytest.raises(LoginError) as error:await login.password('12345678','test-private-password')
        assert expected in error.value.message
        assert 'private-token' not in error.value.message and 'https://' not in error.value.message
        status=await login.status('12345678')
        assert status['message']==error.value.message
    asyncio.run(flow())
