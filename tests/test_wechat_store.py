import sqlite3
import pytest
from app.database import Database
from app.services.wechat_store import init_storage, bind, checkpoint, baseline, commit_batch

IDENTITY = {'account': 'a'*64, 'group': 'b'*64}
PROFILE = {'alias_hash': 'c'*64, 'group_name': '测试群'}

@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path/'db')
    init_storage(db)
    scope = bind(db, PROFILE, IDENTITY)
    yield db, scope
    db.close()

def row(n=1, **kw):
    return dict(shard='message_0.db', local_id=n, kind='text', content='同一正文', sender=None, sent_at=None, **kw)

def test_baseline_is_persisted_and_never_resets(store):
    db, scope = store
    assert checkpoint(db, scope) is None
    baseline(db, scope, {'message_0.db': 10})
    assert checkpoint(db, scope) == {'message_0.db': 10}
    with pytest.raises(ValueError): baseline(db, scope, {'message_0.db': 99})
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 0

def test_commit_replay_and_same_text_distinct_ids(store):
    db, scope = store
    baseline(db, scope, {'message_0.db': 0})
    before, after = {'message_0.db': 0}, {'message_0.db': 2}
    commit_batch(db, scope, PROFILE, before, [row(), row(2)], after)
    commit_batch(db, scope, PROFILE, before, [row(), row(2)], after)
    assert checkpoint(db, scope) == after
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 2
    assert db.conn.execute('SELECT count(*) FROM wechat_receipts').fetchone()[0] == 2
    assert db.conn.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    assert db.conn.execute('SELECT count(*) FROM drafts').fetchone()[0] == 0
    assert db.conn.execute('SELECT sent_at FROM messages LIMIT 1').fetchone()[0] is None

def test_transaction_failure_does_not_ack_or_advance(store):
    db, scope = store; baseline(db, scope, {'message_0.db': 0})
    db.conn.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON wechat_receipts BEGIN SELECT RAISE(ABORT, 'test'); END")
    db.conn.commit()
    with pytest.raises(sqlite3.DatabaseError):
        commit_batch(db, scope, PROFILE, {'message_0.db': 0}, [row()], {'message_0.db': 1})
    assert checkpoint(db, scope) == {'message_0.db': 0}
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    db.conn.execute('DROP TRIGGER reject_receipt'); db.conn.commit()
    commit_batch(db, scope, PROFILE, {'message_0.db': 0}, [row()], {'message_0.db': 1})
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 1

def test_scope_mismatch_and_cursor_jump_rejected(store):
    db, scope = store; baseline(db, scope, {'message_0.db': 0})
    with pytest.raises(ValueError): bind(db, PROFILE, dict(IDENTITY, group='d'*64))
    with pytest.raises(ValueError): commit_batch(db, scope, PROFILE, {'message_0.db': 0}, [row()], {'message_0.db': 99})
    assert checkpoint(db, scope) == {'message_0.db': 0}

@pytest.mark.parametrize('bad', [dict(local_id=True), dict(shard='../escape.db'), dict(content='x'*20001), dict(sent_at='bad')])
def test_invalid_events_do_not_advance(store, bad):
    db, scope = store; baseline(db, scope, {'message_0.db': 0})
    event=row();event.update(bad)
    with pytest.raises(ValueError): commit_batch(db, scope, PROFILE, {'message_0.db': 0}, [event], {'message_0.db': 1})
    assert checkpoint(db, scope) == {'message_0.db': 0}

def test_nontext_checkpoint_and_restart(store):
    db, scope = store; baseline(db, scope, {})
    event=row();event.update(kind='unsupported', content='')
    commit_batch(db, scope, PROFILE, {}, [event], {'message_0.db': 1})
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
    other=Database(db.path); init_storage(other)
    assert bind(other, PROFILE, IDENTITY) == scope
    assert checkpoint(other, scope) == {'message_0.db': 1}
    other.close()


def test_same_local_id_in_different_shards_and_rewritten_receipt(store):
    db,scope=store
    baseline(db,scope,{'message_0.db':0,'message_1.db':0})
    first=row();second=dict(row(),shard='message_1.db')
    before={'message_0.db':0,'message_1.db':0};after={'message_0.db':1,'message_1.db':1}
    commit_batch(db,scope,PROFILE,before,[first,second],after)
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==2
    with pytest.raises(ValueError,match='source_identity_reused'):
        commit_batch(db,scope,PROFILE,before,[dict(first,content='changed'),second],after)
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==2


def test_additive_shard_commit_replay_restart_and_failure(store):
    db,scope=store
    before={'message_0.db':10};after={'message_0.db':11,'message_1.db':1}
    baseline(db,scope,before)
    events=[row(11),dict(row(1),shard='message_1.db')]
    db.conn.execute("CREATE TRIGGER reject_new_shard BEFORE INSERT ON wechat_receipts WHEN NEW.shard='message_1.db' BEGIN SELECT RAISE(ABORT, 'test'); END")
    db.conn.commit()
    with pytest.raises(sqlite3.DatabaseError):commit_batch(db,scope,PROFILE,before,events,after)
    assert checkpoint(db,scope)==before
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    db.conn.execute('DROP TRIGGER reject_new_shard');db.conn.commit()
    assert commit_batch(db,scope,PROFILE,before,events,after)==after
    assert commit_batch(db,scope,PROFILE,before,events,after)==after
    assert db.conn.execute('SELECT count(*) FROM messages').fetchone()[0]==2
    assert db.conn.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
    assert db.conn.execute('SELECT count(*) FROM drafts').fetchone()[0]==0
    other=Database(db.path)
    try:
        init_storage(other)
        assert checkpoint(other,scope)==after
    finally:other.close()
