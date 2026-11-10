"""Account-scoped selection, encrypted recall and independent multi-group progress."""
import asyncio
import hashlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.database import Database
from app.services import wechat_store as store
from app.services.wechat_monitor import WeChatMonitor, MonitorError
from tests.test_wechat_monitor import Process, until
from tests.test_bridge import install


GROUPS = [{'id': '100@chatroom', 'name': '项目群'}, {'id': '200@chatroom', 'name': '项目群'}]


def test_encrypted_account_recall_and_legacy_hash_config(tmp_path):
    async def run():
        db = Database(tmp_path/'db'); store.init_storage(db)
        try:
            monitor = WeChatMonitor(db, tmp_path/'wechat.local.json')
            await monitor.configure('原有群', 'test-account')
            assert 'test-account' not in monitor.path.read_text()
            restarted = WeChatMonitor(db, monitor.path)
            assert restarted.edit_config()['account_alias'] == 'test-account'
            assert 'test-account' not in json.dumps(restarted.status())
            assert restarted.state == 'paused'
            legacy = {'group_name': '原有群', 'alias_hash': hashlib.sha256(b'test-account').hexdigest(), 'paused': False}
            monitor.path.write_text(json.dumps(legacy))
            legacy_monitor = WeChatMonitor(db, monitor.path)
            assert legacy_monitor.edit_config()['account_alias'] == ''
            assert legacy_monitor.public_config()['has_account']
            assert legacy_monitor.config.group_name == '原有群'
        finally:
            db.close()
    asyncio.run(run())


def test_group_config_validation_and_no_account_echo_in_status(tmp_path):
    app = create_app(db_path=tmp_path/'db', config_path=tmp_path/'config')
    with TestClient(app) as client:
        response = client.put('/api/wechat/config', json={'account_alias': 'private-account', 'groups': GROUPS})
        assert response.status_code == 200
        assert response.json()['groups'] == GROUPS
        assert 'private-account' not in response.text
        edit = client.get('/api/wechat/config')
        assert edit.json()['account_alias'] == 'private-account'
        assert edit.headers['cache-control'] == 'no-store'
        assert 'private-account' not in client.get('/api/wechat/status').text
        for groups in [[], [GROUPS[0], GROUPS[0]], [{'id': '../bad', 'name': '群'}],
                       [{'id':str(i)+'@chatroom','name':'群'} for i in range(21)]]:
            assert client.put('/api/wechat/config', json={'account_alias': 'private-account', 'groups': groups}).status_code == 422
        assert client.get('/api/wechat/config').json()['groups'] == GROUPS


def test_multi_group_ack_isolation_and_legacy_checkpoint_migration(tmp_path):
    async def run():
        db = Database(tmp_path/'db'); store.init_storage(db)
        monitor = WeChatMonitor(db, tmp_path/'wechat.local.json')
        await monitor.configure('', 'test-account', GROUPS)
        alias_hash = monitor.config.alias_hash
        identities = {g['id']: {'account': 'a'*64, 'group': hashlib.sha256(g['id'].encode()).hexdigest()} for g in GROUPS}
        legacy = {'group_name': '项目群', 'alias_hash': alias_hash}
        old_scope = store.bind(db, legacy, identities[GROUPS[0]['id']])
        store.baseline(db, old_scope, {'message_0.db': 7})
        proc = Process()
        async def spawn(private): return proc
        monitor.spawn = spawn
        try:
            await monitor.start(); await until(lambda: len(proc.stdin.commands) == 1)
            generation = monitor.generation
            for index, group in enumerate(GROUPS):
                group_id = group['id']
                proc.emit(dict(type='hello', generation=generation, group_id=group_id, identity=identities[group_id]))
                await until(lambda: len(proc.stdin.commands) == 2 + index*2)
                resume = proc.stdin.commands[-1]
                assert resume['group_id'] == group_id
                assert resume['cursors'] == ({'message_0.db': 7} if index == 0 else None)
                if index == 1:
                    proc.emit(dict(type='baseline', generation=generation, group_id=group_id, cursors={'message_0.db': 7}))
                else:
                    event = dict(shard='message_0.db', local_id=8, kind='text', content='first', sender=None, sent_at=None)
                    proc.emit(dict(type='batch', generation=generation, group_id=group_id, before={'message_0.db': 7}, rows=[event], after={'message_0.db': 8}))
                await until(lambda: len(proc.stdin.commands) == 3 + index*2)
            event = dict(shard='message_0.db', local_id=8, kind='text', content='second', sender=None, sent_at=None)
            proc.emit(dict(type='batch', generation=generation, group_id=GROUPS[1]['id'], before={'message_0.db': 7}, rows=[event], after={'message_0.db': 8}))
            await until(lambda: len(proc.stdin.commands) == 6)
            assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 2
            assert store.checkpoint(db, old_scope) == {'message_0.db': 8}
            assert db.conn.execute('SELECT count(*) FROM wechat_streams').fetchone()[0] == 2
            await monitor.stop()
            assert not list(monitor.root.glob('session-*'))
            # IDs remain stable when renamed, and removing/readding retains progress.
            profile = {'alias_hash': alias_hash, 'group_name': '改名后', 'group_id': GROUPS[0]['id']}
            assert store.bind(db, profile, identities[GROUPS[0]['id']]) == old_scope
        finally:
            await monitor.stop(); db.close()
    asyncio.run(run())


@pytest.mark.parametrize('wrong_account',[False,True])
def test_reader_uses_one_verified_database_for_discovery_and_duplicate_name_groups(tmp_path,monkeypatch,wrong_account):
    import sqlite3
    from types import SimpleNamespace
    import app.services.wechat_reader as module
    alias='expected-account'
    class FakeDB:
        created=0
        def __init__(self,**kwargs):
            type(self).created+=1
            self.unkeyed=[];self._keys={};self._db_files=[('contact/contact.db','unused',0)]
        def _find_weixin_pids(self):return [1234]
        def _collect_db_files(self):return []
        @property
        def wxid(self):return 'self'
        def _open(self,path):
            conn=sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE contact(username,alias,nick_name,remark)')
            conn.execute('INSERT INTO contact VALUES (?,?,?,?)',('self','other-account' if wrong_account else alias,'本人',''))
            conn.executemany('INSERT INTO contact VALUES (?,?,?,?)',[(g['id'],'',g['name'],'') for g in GROUPS])
            return conn
    fake=SimpleNamespace(WeChatDB=FakeDB,auto_detect_db_dir=lambda:str(tmp_path),
                         _find_account_dirs=lambda root:[str(tmp_path/'account')])
    quiet=SimpleNamespace(warning_count=0)
    monkeypatch.setattr(module,'reader_class',lambda source:FakeDB)
    monkeypatch.setattr(module,'match_live_account',lambda source,accounts:[0])
    profile={'alias_hash':hashlib.sha256(alias.encode()).hexdigest(),'groups':GROUPS}
    reader=module.Reader(fake,quiet,profile,tmp_path/'cache')
    try:
        if wrong_account:
            with pytest.raises(module.SourceError,match='account_changed'):reader.ensure(discovery=True)
        else:
            assert reader.ensure()
            assert len(reader.identities)==2
            assert {g['id'] for g in reader.available_groups}=={g['id'] for g in GROUPS}
            assert FakeDB.created==1
            assert reader.ensure()
            assert FakeDB.created==1,'multiple groups share the same database instance'
    finally:reader.close()


def test_wechat_discovery_rejects_remote_and_running_capture(tmp_path):
    app = create_app(db_path=tmp_path/'db', config_path=tmp_path/'config')
    with TestClient(app) as client:
        monitor = app.state.wechat
        monitor.state = 'listening'
        result = client.post('/api/wechat/groups', json={'account_alias': 'private-account'})
        assert result.status_code == 409
        assert 'private-account' not in result.text
    with TestClient(app, client=('192.0.2.1', 1000)) as client:
        assert client.post('/api/wechat/groups', json={'account_alias': 'private-account'}).status_code == 403


@pytest.mark.parametrize('failure',[False,True])
def test_discovery_cleans_worker_without_persisting_or_ingesting(tmp_path,failure):
    async def run():
        db=Database(tmp_path/'db');store.init_storage(db)
        monitor=WeChatMonitor(db,tmp_path/'wechat.local.json');proc=Process()
        original_write=proc.stdin.write
        def write(raw):
            original_write(raw)
            command=json.loads(raw)
            assert 'private-account' not in raw.decode()
            if command['type']=='configure':
                frame={'type':'error','reason':'account_changed'} if failure else {'type':'groups','groups':GROUPS}
                proc.emit(dict(frame,generation=command['generation']))
                proc.kill()
        proc.stdin.write=write
        async def spawn(private):return proc
        monitor._spawn=spawn
        try:
            if failure:
                with pytest.raises(MonitorError,match='account_changed'):await monitor.discover('private-account')
            else:assert (await monitor.discover('private-account'))['groups']==GROUPS
            assert not monitor.path.exists()
            assert not list(monitor.root.glob('session-*'))
            assert monitor.state=='paused'
            assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==0
            assert db.conn.execute('SELECT count(*) FROM wechat_cursors').fetchone()[0]==0
        finally:db.close()
    asyncio.run(run())


def test_discovery_timeout_terminates_worker_and_preserves_config(tmp_path,monkeypatch):
    import app.services.wechat_monitor as module
    async def run():
        db=Database(tmp_path/'db');store.init_storage(db)
        monitor=WeChatMonitor(db,tmp_path/'wechat.local.json');proc=Process()
        await monitor.configure('原群','private-account')
        original=monitor.path.read_bytes()
        async def spawn(private):return proc
        monitor._spawn=spawn
        wait_for=asyncio.wait_for
        async def fast_wait(awaitable,timeout):return await wait_for(awaitable,min(timeout,.05))
        monkeypatch.setattr(module.asyncio,'wait_for',fast_wait)
        try:
            with pytest.raises(MonitorError,match='source_timeout'):await monitor.discover('private-account')
            assert proc.returncode==0
            assert monitor.path.read_bytes()==original
            assert not list(monitor.root.glob('session-*'))
        finally:db.close()
    asyncio.run(run())


def test_stop_during_discovery_cleans_worker_without_waiting_for_timeout(tmp_path):
    async def run():
        db=Database(tmp_path/'db');store.init_storage(db)
        monitor=WeChatMonitor(db,tmp_path/'wechat.local.json');proc=Process()
        async def spawn(private):return proc
        monitor._spawn=spawn
        task=asyncio.create_task(monitor.discover('private-account'))
        try:
            await until(lambda:bool(proc.stdin.commands))
            assert monitor.discovery_task is not None
            result=await asyncio.wait_for(monitor.stop(),timeout=3)
            assert result['state']=='paused'
            with pytest.raises(MonitorError,match='discovery_cancelled'):await task
            assert proc.returncode==0
            assert monitor.discovery_task is None
            assert not list(monitor.root.glob('session-*'))
        finally:
            await monitor.stop();db.close()
    asyncio.run(run())


def test_qq_groups_are_read_only_account_checked_and_sanitized(tmp_path):
    install(tmp_path)
    paths = []
    switched = False
    def handle(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/auth/login'): data = {'Credential': 'private-token'}
        elif request.url.path.endswith('CheckLoginStatus'): data = {'isLogin': True}
        elif request.url.path.endswith('GetQQLoginInfo'): data = {'uin': '22345678' if switched else '12345678'}
        elif request.url.path.endswith('/Debug/call'):
            assert json.loads(request.content) == {'action': 'get_group_list', 'params': {}}
            data = {'status': 'ok', 'retcode': 0, 'data': [{'group_id': 87654321, 'group_name': '协作群', 'member_count': 10}]}
        else: raise AssertionError(request.url.path)
        return httpx.Response(200, json={'code': 0, 'data': data})
    with TestClient(create_app(db_path=tmp_path/'db', config_path=tmp_path/'config')) as client:
        client.app.state.bridge.transport = httpx.MockTransport(handle)
        response = client.get('/api/qq/groups?account_id=12345678')
        assert response.status_code == 200
        assert response.json()['groups'] == [{'id': '87654321', 'name': '协作群'}]
        assert 'private-token' not in response.text
        assert not any('SetConfig' in path for path in paths)
        switched = True
        assert client.get('/api/qq/groups?account_id=12345678').status_code == 409
        client.app.state.qq_login.policy.write('exited')
        assert client.get('/api/qq/groups?account_id=12345678').status_code == 409
