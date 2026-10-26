"""Account switching and reporting setup against an isolated NapCat API double."""
import asyncio
import copy
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.routers.qq import QQReceiver
from tests.test_bridge import install
from tests.test_qq import configure, send, event, TOKEN


class NapCat:
    def __init__(self):
        self.account = '23456789'
        self.online = True
        self.persist = True
        self.reject = False
        self.writes = 0
        self.config = {'network': {'httpClients': [
            {'name': 'Other tool', 'url': 'http://127.0.0.1:9999', 'enable': True}],
            'websocketClients': [{'name': 'keep-ws', 'enable': False}]}, 'musicSignUrl': 'keep'}

    def handle(self, request):
        route = request.url.path.rsplit('/', 1)[-1]
        code = 0
        if route == 'login': data = {'Credential': 'private-credential'}
        elif route == 'CheckLoginStatus': data = {'isLogin': self.online}
        elif route == 'GetQQLoginInfo': data = {'uin': self.account}
        elif route == 'GetConfig': data = copy.deepcopy(self.config)
        elif route == 'SetConfig':
            self.writes += 1
            if self.reject: code = -1
            elif self.persist: self.config = json.loads(json.loads(request.content)['config'])
            data = None
        else: raise AssertionError(route)
        return httpx.Response(200, json={'code': code, 'data': data,
                                         'message': 'private-upstream-diagnostic'})


@pytest.fixture
def setup(tmp_path):
    install(tmp_path)
    napcat = NapCat()
    with TestClient(create_app(db_path=tmp_path/'db', config_path=tmp_path/'config')) as client:
        client.app.state.bridge.transport = httpx.MockTransport(napcat.handle)
        yield client, napcat, tmp_path


def sync(client):
    return client.post('/api/qq/login/sync', headers={'Origin': 'http://testserver'})


def test_account_switch_persists_and_repairs_external_reporting(setup):
    client, napcat, root = setup
    configure(client)
    assert send(client).status_code == 204
    manual = client.post('/api/messages/manual', json={'raw_text': '保留已有业务数据', 'fields': {'title': '已有待办'}}).json()
    draft = manual['drafts'][0]
    task = client.post('/api/drafts/'+draft['id']+'/confirm', json={'confirmed': True, 'fields': draft['fields']}).json()
    task_before = client.get('/api/tasks/'+task['id']).json()
    drafts_before = client.get('/api/drafts').json()
    message_before = client.get('/api/messages/'+manual['message']['id']).json()
    before = copy.deepcopy(napcat.config)
    response = sync(client)
    assert response.status_code == 200
    result = response.json()
    assert result['state'] == 'ready'
    assert result['receiver']['account_id'] == napcat.account
    receiver = QQReceiver(root/'qq.local.json')
    assert receiver.account_id == napcat.account
    assert receiver.enabled and receiver.group_ids == ['87654321'] and receiver.token == TOKEN
    assert result['receiver']['last_event_at'] is None
    assert all(secret not in response.text for secret in (TOKEN, 'private-credential', 'private-upstream-diagnostic'))
    assert TOKEN not in (root/'qq.local.json').read_text()
    clients = napcat.config['network']['httpClients']
    assert clients[0] == before['network']['httpClients'][0]
    assert napcat.config['network']['websocketClients'] == before['network']['websocketClients']
    assert napcat.config['musicSignUrl'] == before['musicSignUrl']
    assert clients[1]['url'] == 'http://127.0.0.1:80/api/qq/events'
    assert clients[1]['token'] == TOKEN and clients[1]['messagePostFormat'] == 'array'
    assert clients[1]['enable'] is True
    assert sync(client).json()['state'] == 'ready' and napcat.writes == 1
    # Old account cannot enter the inbox; new account can. History is retained.
    assert send(client, event(message_id=2)).status_code == 204
    assert send(client, event(self_id=int(napcat.account), message_id=3)).status_code == 204
    assert len(client.get('/api/qq/inbox').json()['messages']) == 2
    assert client.get('/api/tasks/'+task['id']).json() == task_before
    assert client.get('/api/drafts').json() == drafts_before
    assert client.get('/api/messages/'+manual['message']['id']).json() == message_before
    assert response.headers['cache-control'] == 'no-store'


def test_disabled_stays_disabled_and_missing_token_is_generated_privately(setup):
    client, napcat, root = setup
    result = sync(client).json()
    assert result['state'] == 'disabled'
    assert result['receiver']['account_id'] == napcat.account
    assert not result['receiver']['enabled'] and result['receiver']['group_ids'] == []
    receiver = QQReceiver(root/'qq.local.json')
    assert len(receiver.token) >= 32 and result['receiver']['has_token']
    assert receiver.token not in json.dumps(result) and receiver.token not in receiver.path.read_text()
    assert napcat.writes == 0


@pytest.mark.parametrize('mode', ['reject', 'unpersisted'])
def test_setup_failure_is_explicit_and_never_ready(setup, mode):
    client, napcat, root = setup
    configure(client)
    napcat.reject = mode == 'reject'
    napcat.persist = mode != 'unpersisted'
    result = sync(client).json()
    assert result['state'] == 'report_mismatch'
    assert '重试' in result['hint']
    assert QQReceiver(root/'qq.local.json').account_id == napcat.account


@pytest.mark.parametrize('mode', ['offline', 'exited', 'invalid_account'])
def test_no_receiver_changes_without_valid_active_login(setup, mode):
    client, napcat, root = setup
    configure(client)
    before = (root/'qq.local.json').read_bytes()
    if mode == 'offline': napcat.online = False
    elif mode == 'exited': client.app.state.qq_login.policy.write('exited')
    else: napcat.account = 'invalid-private-upstream-value'
    response = sync(client)
    assert response.json()['state'] != 'ready'
    assert (root/'qq.local.json').read_bytes() == before
    assert napcat.writes == 0
    assert 'invalid-private-upstream-value' not in response.text


def test_origin_required_and_status_overview_does_not_sync_external_account(setup):
    client, napcat, root = setup
    configure(client)
    for headers in ({}, {'Origin': 'http://evil.example'}):
        assert client.post('/api/qq/login/sync', headers=headers).status_code == 403
    assert client.get('/api/qq/status').json()['state'] == 'account_mismatch'
    assert QQReceiver(root/'qq.local.json').account_id == '12345678'
    assert napcat.writes == 0


def test_save_failure_does_not_claim_synced_or_configure_napcat(setup, monkeypatch):
    client, napcat, root = setup
    configure(client)
    before = (root/'qq.local.json').read_bytes()
    def fail(_): raise OSError('private-path')
    monkeypatch.setattr(client.app.state.qq, 'save', fail)
    response = sync(client)
    assert response.status_code == 503
    assert response.json()['state'] == 'sync_failed'
    assert 'private-path' not in response.text
    assert (root/'qq.local.json').read_bytes() == before and napcat.writes == 0


@pytest.mark.parametrize('change_after_reads', [1, 2])
def test_setup_checks_for_account_change_before_write_and_after_readback(setup, change_after_reads):
    client, napcat, root = setup
    configure(client)
    handler = napcat.handle
    reads = 0
    def changing(request):
        nonlocal reads
        if request.url.path.endswith('GetConfig'):
            reads += 1
            if reads == change_after_reads: napcat.account = '34567890'
        return handler(request)
    client.app.state.bridge.transport = httpx.MockTransport(changing)
    result = sync(client).json()
    assert result['state'] == 'account_mismatch'
    assert napcat.writes == (0 if change_after_reads == 1 else 1)


def test_disabled_receiver_keeps_disabled_status_when_napcat_is_unavailable(setup):
    client, napcat, root = setup
    def unavailable(request): raise httpx.ConnectError('private-network-error', request=request)
    client.app.state.bridge.transport = httpx.MockTransport(unavailable)
    response = sync(client)
    assert response.status_code == 200 and response.json()['state'] == 'disabled'
    assert 'private-network-error' not in response.text
    assert not (root/'qq.local.json').exists()


def test_duplicate_owned_clients_are_repaired_without_changing_other_transports(setup):
    client, napcat, root = setup
    configure(client)
    before = copy.deepcopy(napcat.config)
    napcat.config['network']['httpClients'] += [
        {'name': 'legacy callback', 'url': 'http://127.0.0.1:80/api/qq/events', 'enable': False, 'custom': 'preserved'},
        {'name': 'Shixu', 'url': 'http://127.0.0.1:8000/api/qq/events', 'token': 'old-token'}]
    assert sync(client).json()['state'] == 'ready'
    rows = napcat.config['network']['httpClients']
    assert len(rows) == 2 and rows[0] == before['network']['httpClients'][0]
    assert rows[1]['name'] == 'Shixu' and rows[1]['custom'] == 'preserved'
    assert rows[1]['token'] == TOKEN and rows[1]['enable'] is True
    assert sync(client).json()['state'] == 'ready' and napcat.writes == 1


def test_readonly_managed_diagnostics_cannot_write_configuration(tmp_path):
    from app.services.bridge import BridgeMonitor, find_installation
    from app.services.napcat_bundle import bundled_folder, initialize
    folder = bundled_folder(tmp_path)
    folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'napcat.mjs', 'loadNapCat.js', 'qqnt.json'):
        (folder/name).touch()
    initialize(find_installation(tmp_path))
    napcat = NapCat()
    bridge = BridgeMonitor(tmp_path, httpx.MockTransport(napcat.handle))
    result = asyncio.run(bridge.inspect(napcat.account, TOKEN))
    assert result['state'] == 'report_mismatch' and napcat.writes == 0


def test_sync_waiting_for_logout_does_not_reactivate_session(setup):
    client, napcat, root = setup
    configure(client)
    from app.services.qq_connection import synchronize
    login, receiver = client.app.state.qq_login, client.app.state.qq
    async def run():
        async with login.action_lock:
            task = asyncio.create_task(synchronize(login, receiver, 'http://127.0.0.1:8000/api/qq/events'))
            await asyncio.sleep(0)
            login.policy.write('exited')
        return await task
    result = asyncio.run(run())
    assert result['state'] == 'exited' and receiver.account_id == '12345678' and napcat.writes == 0
