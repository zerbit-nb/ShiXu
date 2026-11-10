"""Startup catch-up uses source identity, original times and explicit consent."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app.database import Database
from app.main import create_app
from app.routers.qq import QQEvent, init_storage, receive
from app.services.auto_organize import AutoOrganizer
from app.services.history import HistoryCatchup, begin_run, finish_run, init_history, window
from app.services.wechat_store import bind, checkpoint, commit_history, init_storage as init_wechat
from tests.test_auto_organize import Model, TEXT
from app.config import Settings


def test_window_uses_beijing_midnight():
    since, until = window(datetime.fromisoformat('2026-11-09T02:00:00+00:00'))
    assert since == '2026-11-09T00:00:00+08:00'
    assert until == '2026-11-09T10:00:00+08:00'


def test_preference_is_explicit_local_and_persistent(tmp_path):
    for enabled in (False, True):
        with TestClient(create_app(db_path=tmp_path/'db', config_path=tmp_path/'config')) as c:
            assert c.get('/api/history').json()['enabled'] is enabled
            assert c.put('/api/history', json={'enabled': True}).status_code == 403
            assert c.put('/api/history', json={'enabled': 'true'}, headers={'Origin':'http://testserver'}).status_code == 422
            assert c.put('/api/history', json={'enabled': True}, headers={'Origin':'http://testserver'}).status_code == 200


@pytest.fixture
def storage(tmp_path):
    db = Database(tmp_path/'db')
    init_storage(db); init_wechat(db); init_history(db)
    yield db
    db.close()


def event(n=1, text=TEXT):
    return QQEvent(self_id=12345678, group_id=123456, user_id=87654321,
                   message_id=n, time=1794186000+n, message=text)


def test_history_and_live_share_dedup_and_preserve_identical_messages(storage):
    db = storage
    run = begin_run(db, 'qq', 'test', *window(), auto_allowed=False)
    first = receive(db, event(), history_run=run)
    receive(db, event())
    receive(db, event(2), history_run=run)
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 2
    assert datetime.fromisoformat(db.get_message(first)['sent_at']).timestamp() == event().time
    assert db.conn.execute('SELECT count(*) FROM history_messages').fetchone()[0] == 2


def test_history_waits_for_completion_and_changes_force_review(storage):
    db = storage
    model = Model()
    worker = AutoOrganizer(db, Settings(llm_model='test'), lambda:model, asyncio.Lock())
    worker.configure(True, True)
    run = begin_run(db, 'qq', 'test', *window(), auto_allowed=True)
    receive(db, event(), history_run=run)
    asyncio.run(worker.run_once())
    assert model.calls == 0
    receive(db, event(2, '通知：实验报告延期到下周五提交。'), history_run=run)
    finish_run(db, run, 'complete')
    asyncio.run(worker.run_once())
    assert model.calls == 0 and not db.list_tasks()


def test_off_at_ingestion_never_becomes_automatic_when_enabled_later(storage):
    db = storage
    model = Model()
    worker = AutoOrganizer(db, Settings(llm_model='test'), lambda:model, asyncio.Lock())
    run = begin_run(db, 'qq', 'test', *window(), auto_allowed=False)
    receive(db, event(), history_run=run); finish_run(db, run, 'complete')
    worker.configure(True, True)
    asyncio.run(worker.run_once())
    assert model.calls == 0


def test_wechat_history_does_not_advance_live_cursor_and_replay_dedups(storage):
    db = storage
    profile = {'alias_hash':'c'*64, 'group_name':'测试群'}
    scope = bind(db, profile, {'account':'a'*64, 'group':'b'*64})
    run = begin_run(db, 'wechat', scope, *window(), auto_allowed=False)
    row = dict(shard='message_0.db', local_id=7, kind='text', content=TEXT,
               sender=None, sent_at='2026-11-09T09:00:00+08:00')
    commit_history(db, scope, profile, [row], run)
    commit_history(db, scope, profile, [row], run)
    assert checkpoint(db, scope) is None
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 1
    assert db.conn.execute('SELECT count(*) FROM wechat_receipts').fetchone()[0] == 1


def test_qq_pagination_exceeds_fifty_and_fails_closed_on_repeated_page(storage):
    async def flow(repeated):
        db = storage
        values = [dict(event(i).model_dump(), message_seq=i) for i in range(1, 152)]
        calls = []
        async def history(account, group, anchor=None):
            calls.append(anchor)
            return values[-100:] if anchor is None or repeated else values[:52] if anchor != 1 else []
        qq = SimpleNamespace(enabled=True, account_id='12345678', group_ids=['123456'])
        async def status(account): return {'online':True,'account_id':account}
        login = SimpleNamespace(policy=SimpleNamespace(paused=False), history=history, status=status)
        automation = SimpleNamespace(public=lambda:{'state':'disabled'})
        worker = HistoryCatchup(db, qq, login, SimpleNamespace(), automation)
        worker.configure(True)
        await worker.catchup_qq(datetime.fromtimestamp(values[-1]['time']).astimezone())
        run = db.conn.execute('SELECT * FROM history_runs ORDER BY rowid DESC LIMIT 1').fetchone()
        assert run['state'] == ('partial' if repeated else 'complete')
        assert len(calls) >= 2
        if not repeated:
            assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 151
    asyncio.run(flow(False))
    asyncio.run(flow(True))


def test_completed_history_creates_task_once_and_uses_original_time(storage):
    db = storage; model = Model()
    worker = AutoOrganizer(db, Settings(llm_model='test'), lambda:model, asyncio.Lock())
    worker.configure(True, True)
    run = begin_run(db, 'qq', 'test', *window(), auto_allowed=True)
    item = receive(db, event(), history_run=run)
    finish_run(db, run, 'complete')
    asyncio.run(worker.run_once()); asyncio.run(worker.run_once())
    assert model.calls == 1 and len(db.list_tasks()) == 1
    assert db.list_tasks()[0]['message_id'] == item


def test_history_transaction_failure_preserves_live_progress(storage):
    import sqlite3
    db = storage; profile = {'alias_hash':'c'*64, 'group_name':'测试群'}
    scope = bind(db, profile, {'account':'a'*64, 'group':'b'*64})
    run = begin_run(db, 'wechat', scope, *window(), auto_allowed=False)
    db.conn.execute("CREATE TRIGGER reject_history BEFORE INSERT ON history_messages BEGIN SELECT RAISE(ABORT,'test'); END")
    db.conn.commit()
    row = dict(shard='message_0.db', local_id=1, kind='text', content=TEXT,
               sender=None, sent_at='2026-11-09T09:00:00+08:00')
    with pytest.raises(sqlite3.DatabaseError):
        commit_history(db, scope, profile, [row], run)
    assert checkpoint(db, scope) is None
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    assert db.conn.execute('SELECT count(*) FROM wechat_receipts').fetchone()[0] == 0


def test_wechat_history_query_bounds_and_does_not_skip_over_fifty():
    import sqlite3
    from app.services.wechat_reader import query_history
    conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE messages(local_id INTEGER, create_time INTEGER)')
    stamp = int(datetime.fromisoformat('2026-11-09T09:00:00+08:00').timestamp())
    conn.executemany('INSERT INTO messages VALUES (?,?)', [(i,stamp) for i in range(1,152)] + [(152,stamp-86400),(153,stamp)])
    class Source:
        def _run_msg_query(self, group, build): return build([(conn,'messages')])
        def _shard_maps(self, tables): return {}
        def _shard_label(self, connection): return 'message_0.db'
        def _shard_rows(self, tables, sql, params, order_ext, per_shard_limit):
            return [dict(r,shard='message_0.db',type='文本',content=TEXT) for r in conn.execute(
                'SELECT * FROM messages '+sql+' '+order_ext+' LIMIT ?', (*params,per_shard_limit))]
        def _msg_row_to_dict(self, row, maps): return row
    cursors, seen = {}, []
    try:
        while True:
            rows, cursors = query_history(Source(), 'group', cursors, {'message_0.db':152},
                '2026-11-09T00:00:00+08:00','2026-11-09T10:00:00+08:00')
            if not rows: break
            seen.extend(r['local_id'] for r in rows)
        assert seen == list(range(1,152))
    finally: conn.close()


def test_monitor_history_commit_ack_and_first_baseline(storage, tmp_path):
    from app.services.wechat_monitor import WeChatMonitor
    from tests.test_wechat_monitor import Process, until
    async def flow():
        db = storage; monitor = WeChatMonitor(db, tmp_path/'wechat.local.json')
        db.conn.execute('UPDATE history_settings SET enabled=1'); db.conn.commit()
        await monitor.configure('测试群','test-account')
        proc = Process()
        async def spawn(private): return proc
        monitor.spawn = spawn
        try:
            await monitor.start(); await until(lambda:bool(proc.stdin.commands))
            tag = {'generation':monitor.generation}
            proc.emit(dict(type='hello',identity={'account':'a'*64,'group':'b'*64},**tag))
            await until(lambda:len(proc.stdin.commands)==2)
            assert proc.stdin.commands[-1]['history_since'].endswith('+08:00')
            proc.emit(dict(type='history_started',until='2026-11-09T10:00:00+08:00',**tag))
            row = dict(shard='message_0.db',local_id=1,kind='text',content=TEXT,sender=None,sent_at='2026-11-09T09:00:00+08:00')
            proc.emit(dict(type='history_batch',rows=[row],**tag))
            await until(lambda:len(proc.stdin.commands)==3)
            assert proc.stdin.commands[-1]['type']=='history_ack'
            assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==1
            proc.emit(dict(type='history_done',complete=True,**tag))
            proc.emit(dict(type='baseline',cursors={'message_0.db':1},**tag))
            await until(lambda:monitor.state=='listening')
            assert db.conn.execute('SELECT state FROM history_runs').fetchone()[0]=='complete'
        finally: await monitor.stop()
    asyncio.run(flow())


def test_napcat_history_uses_read_only_action_and_rechecks_account(tmp_path):
    import httpx
    import json
    from tests.test_qq_login import service
    from app.services.qq_verification import LoginError
    switched=False;calls=[]
    def handle(request):
        nonlocal switched
        route=request.url.path.rsplit('/',1)[-1]
        if route=='login':data={'Credential':'test-credential'}
        elif route=='CheckLoginStatus':data={'isLogin':True}
        elif route=='GetQQLoginInfo':data={'uin':'22345678' if switched else '12345678'}
        elif route=='call':
            body=json.loads(request.content);calls.append(body)
            assert body['action']=='get_group_msg_history'
            data={'status':'ok','retcode':0,'data':{'messages':[event().model_dump()]}}
        else:raise AssertionError(route)
        return httpx.Response(200,json={'code':0,'data':data})
    login=service(tmp_path,handle)
    async def flow():
        nonlocal switched
        assert len(await login.history('12345678','123456',77))==1
        assert calls[0]['params']=={'group_id':'123456','count':100,'reverse_order':False,
            'disable_get_url':True,'parse_mult_msg':False,'quick_reply':False,'message_seq':'77'}
        switched=True
        with pytest.raises(LoginError):await login.history('12345678','123456')
        assert len(calls)==1
    asyncio.run(flow())
