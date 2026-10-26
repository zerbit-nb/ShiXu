import asyncio
import json
import pytest
from app.database import Database
from app.services.wechat_store import init_storage, checkpoint
from app.services.wechat_monitor import WeChatMonitor, MonitorError

class Input:
    def __init__(self):self.commands=[];self.onstop=None
    def write(self,data):
        command=json.loads(data);self.commands.append(command)
        if command['type']=='stop' and self.onstop:self.onstop()
    async def drain(self):pass
    def close(self):pass

class Process:
    def __init__(self):
        self.stdin=Input();self.stdout=asyncio.StreamReader();self.returncode=None;self.pid=99999999
        self.done=asyncio.Event();self.stdin.onstop=self.kill
    def kill(self):self.returncode=0;self.done.set();self.stdout.feed_eof()
    async def wait(self):await self.done.wait();return self.returncode
    def emit(self,value):self.stdout.feed_data((json.dumps(value)+'\n').encode())

async def until(predicate):
    for _ in range(200):
        if predicate():return
        await asyncio.sleep(.01)
    raise AssertionError('condition_timeout')

async def setup(tmp_path):
    db=Database(tmp_path/'db');init_storage(db)
    monitor=WeChatMonitor(db,tmp_path/'wechat.local.json')
    await monitor.configure('测试群','test-account')
    proc=Process()
    async def spawn(private):return proc
    monitor.spawn=spawn
    return db,monitor,proc

def test_singleton_stop_stale_events_and_ack_after_commit(tmp_path):
    async def run():
        db,m,p=await setup(tmp_path)
        try:
            await m.start();await until(lambda:len(p.stdin.commands)==1)
            generation=m.generation
            assert (await m.start())['state']=='starting'
            p.emit(dict(type='hello',generation=generation,identity={'account':'a'*64,'group':'b'*64}))
            await until(lambda:len(p.stdin.commands)==2)
            p.emit(dict(type='baseline',generation=generation,cursors={'message_0.db':0}))
            await until(lambda:m.state=='listening')
            event=dict(shard='message_0.db',local_id=1,kind='text',content='test',sender=None,sent_at=None)
            p.emit(dict(type='batch',generation=generation,before={'message_0.db':0},after={'message_0.db':1},rows=[event]))
            await until(lambda:len(p.stdin.commands)==4)
            assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==1
            assert p.stdin.commands[-1]['type']=='ack'
            old=generation
            await m.stop()
            assert m.state=='paused' and m.generation is None
            assert p.returncode==0
            assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==1
            assert not list(m.root.glob('session-*'))
            restarted=WeChatMonitor(db,m.path)
            assert restarted.state=='paused' and restarted.task is None
        finally:
            await m.stop();db.close()
    asyncio.run(run())

def test_failure_has_no_ack_and_does_not_leak_exception(tmp_path):
    async def run():
        db,m,p=await setup(tmp_path)
        try:
            await m.start();await until(lambda:len(p.stdin.commands)==1)
            p.emit(dict(type='error',generation=m.generation,reason='password=private-secret'))
            await until(lambda:m.task.done())
            assert m.state=='error'
            assert 'private-secret' not in json.dumps(m.status())
            assert not any(cmd['type']=='ack' for cmd in p.stdin.commands)
        finally:
            await m.stop();db.close()
    asyncio.run(run())

def test_cross_instance_lock_and_paused_configuration(tmp_path):
    async def run():
        db,m,p=await setup(tmp_path)
        other=WeChatMonitor(db,m.path);other.spawn=m.spawn
        try:
            await m.start();await until(lambda:len(p.stdin.commands)==1)
            with pytest.raises(MonitorError):await other.start()
            with pytest.raises(MonitorError):await m.configure('别的群','other')
        finally:
            await m.stop();await other.stop();db.close()
    asyncio.run(run())


def test_immediate_stop_and_wrong_generation(tmp_path):
    async def run():
        db,m,p=await setup(tmp_path)
        try:
            await m.start();await m.stop()
            assert not list(m.root.glob('session-*'))
            next_proc=Process()
            async def spawn(private):return next_proc
            m.spawn=spawn
            await m.start();await until(lambda:bool(next_proc.stdin.commands))
            next_proc.emit(dict(type='baseline',generation='old-session',cursors={'message_0.db':99}))
            await until(lambda:m.task.done())
            assert m.state=='error'
            assert db.conn.execute('SELECT count(*) FROM wechat_cursors').fetchone()[0]==0
        finally:
            await m.stop();db.close()
    asyncio.run(run())


def test_stop_still_revokes_if_persistence_fails(tmp_path):
    async def run():
        db,m,p=await setup(tmp_path)
        await m.start();await until(lambda:bool(p.stdin.commands))
        original=m._save
        def fail():raise OSError('private-path')
        m._save=fail
        result=await m.stop()
        assert result['state']=='error' and result['reason']=='config_write_failed'
        assert m.generation is None and p.returncode==0
        assert not list(m.root.glob('session-*'))
        m._save=original;await m.stop();db.close()
    asyncio.run(run())

def test_database_failure_has_no_batch_ack(tmp_path):
    async def run():
        db,m,p=await setup(tmp_path)
        try:
            await m.start();await until(lambda:bool(p.stdin.commands));gen=m.generation
            p.emit(dict(type='hello',generation=gen,identity={'account':'a'*64,'group':'b'*64}))
            await until(lambda:len(p.stdin.commands)==2)
            p.emit(dict(type='baseline',generation=gen,cursors={'message_0.db':0}))
            await until(lambda:m.state=='listening')
            db.conn.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON wechat_receipts BEGIN SELECT RAISE(ABORT,'test'); END");db.conn.commit()
            event=dict(shard='message_0.db',local_id=1,kind='text',content='test',sender=None,sent_at=None)
            p.emit(dict(type='batch',generation=gen,before={'message_0.db':0},after={'message_0.db':1},rows=[event]))
            await until(lambda:m.task.done())
            assert m.reason=='database_error'
            assert sum(cmd['type']=='ack' for cmd in p.stdin.commands)==1
            assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==0
        finally:
            await m.stop();db.close()
    asyncio.run(run())

def test_stale_cache_only_removed_after_known_worker_exit(tmp_path):
    import os
    from app.services.wechat_monitor import clean_stale_sessions
    root=tmp_path/'cache';root.mkdir()
    stale=root/'session-test';stale.mkdir()
    owner=stale/'owner.json'
    owner.write_text(json.dumps({'worker_pid':os.getpid()}))
    with pytest.raises(MonitorError):clean_stale_sessions(root)
    assert stale.exists()
    owner.write_text(json.dumps({'worker_pid':99999999}))
    clean_stale_sessions(root)
    assert not stale.exists()
