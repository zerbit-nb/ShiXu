"""Wechat receipts and per-shard checkpoints share the original-message transaction."""
from datetime import datetime
import hashlib
import json
import re
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.database import utc_now
from app.services.reception_filter import apply_filter

MAX_BATCH = 32
SHARD = re.compile(r'message_[0-9]+[.]db')

class Event(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    shard: str = Field(pattern=r'^message_[0-9]+[.]db$')
    local_id: int = Field(gt=0)
    kind: Literal['text', 'unsupported']
    content: str = Field(default='', max_length=20000)
    sender: str | None = Field(default=None, max_length=100)
    sent_at: str | None = None

    @field_validator('sent_at')
    @classmethod
    def valid_time(cls, value):
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError('timezone_required')
        return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def profile_key(profile):
    return digest([profile['alias_hash'], profile['group_name']])


def marks(value):
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError('invalid_checkpoint')
    if any(not isinstance(k, str) or not SHARD.fullmatch(k) or type(v) is not int or v < 0 for k, v in value.items()):
        raise ValueError('invalid_checkpoint')
    return dict(value)


def init_storage(db):
    db.conn.executescript("""
    CREATE TABLE IF NOT EXISTS wechat_streams (
      scope TEXT PRIMARY KEY, profile TEXT UNIQUE NOT NULL,
      account_hash TEXT NOT NULL, group_hash TEXT NOT NULL,
      initialized INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS wechat_cursors (
      scope TEXT NOT NULL REFERENCES wechat_streams(scope),
      shard TEXT NOT NULL, local_id INTEGER NOT NULL,
      PRIMARY KEY(scope, shard));
    CREATE TABLE IF NOT EXISTS wechat_receipts (
      scope TEXT NOT NULL REFERENCES wechat_streams(scope),
      shard TEXT NOT NULL, local_id INTEGER NOT NULL, payload_hash TEXT NOT NULL,
      message_id TEXT UNIQUE REFERENCES messages(id), received_at TEXT NOT NULL,
      PRIMARY KEY(scope, shard, local_id));
    """)


def bind(db, profile, identity):
    if set(identity) != {'account', 'group'} or any(not re.fullmatch('[0-9a-f]{64}', v) for v in identity.values()):
        raise ValueError('invalid_identity')
    scope = digest(identity)
    key = profile_key(profile)
    existing = db.conn.execute('SELECT scope FROM wechat_streams WHERE profile=?', (key,)).fetchone()
    if existing and existing[0] != scope:
        raise ValueError('identity_changed')
    with db.conn:
        db.conn.execute('INSERT OR IGNORE INTO wechat_streams(scope,profile,account_hash,group_hash) VALUES (?,?,?,?)',
                        (scope, key, identity['account'], identity['group']))
    # A renamed profile cannot silently acquire an existing scope's checkpoint.
    actual = db.conn.execute('SELECT profile FROM wechat_streams WHERE scope=?', (scope,)).fetchone()
    if actual[0] != key:
        raise ValueError('profile_changed')
    return scope


def checkpoint(db, scope):
    row = db.conn.execute('SELECT initialized FROM wechat_streams WHERE scope=?', (scope,)).fetchone()
    if not row:
        raise ValueError('unknown_scope')
    if not row[0]:
        return None
    return dict(db.conn.execute('SELECT shard,local_id FROM wechat_cursors WHERE scope=?', (scope,)))


def _write_marks(db, scope, value):
    for shard, local_id in value.items():
        db.conn.execute('INSERT INTO wechat_cursors VALUES (?,?,?) ON CONFLICT(scope,shard) DO UPDATE SET local_id=excluded.local_id',
                        (scope, shard, local_id))


def baseline(db, scope, value):
    value = marks(value)
    with db.conn:
        if checkpoint(db, scope) is not None:
            raise ValueError('baseline_already_initialized')
        _write_marks(db, scope, value)
        db.conn.execute('UPDATE wechat_streams SET initialized=1 WHERE scope=?', (scope,))


def commit_batch(db, scope, profile, before, rows, after):
    before, after = marks(before), marks(after)
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_BATCH:
        raise ValueError('invalid_batch_size')
    events = [Event.model_validate(row) for row in rows]
    calculated = dict(before)
    for event in events:
        if event.local_id <= calculated.get(event.shard, 0):
            raise ValueError('unordered_events')
        if event.kind == 'text' and not event.content.strip():
            raise ValueError('empty_text')
        if event.kind == 'unsupported' and (event.content or event.sender or event.sent_at):
            raise ValueError('nontext_payload_not_allowed')
        calculated[event.shard] = event.local_id
    if calculated != after:
        raise ValueError('checkpoint_jump')
    bound = db.conn.execute('SELECT profile FROM wechat_streams WHERE scope=?', (scope,)).fetchone()
    if not bound or bound[0] != profile_key(profile):
        raise ValueError('profile_changed')
    with db.conn:
        current = checkpoint(db, scope)
        if current not in (before, after):
            raise ValueError('stale_checkpoint')
        replay = current == after
        for event in events:
            key = (scope, event.shard, event.local_id)
            hashed = digest(event.model_dump())
            receipt = db.conn.execute('SELECT payload_hash FROM wechat_receipts WHERE scope=? AND shard=? AND local_id=?', key).fetchone()
            if receipt:
                if receipt[0] != hashed:
                    raise ValueError('source_identity_reused')
                continue
            if replay:
                raise ValueError('incomplete_replay')
            message_id = None
            now = utc_now()
            if event.kind == 'text':
                message_id = uuid4().hex
                db.conn.execute('INSERT INTO messages (id,source,source_group,sender,sent_at,raw_text,extraction_status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                    (message_id, 'wechat', profile['group_name'], event.sender, event.sent_at, event.content, 'received', now))
                apply_filter(db, message_id, event.content)
            db.conn.execute('INSERT INTO wechat_receipts VALUES (?,?,?,?,?,?)', (*key, hashed, message_id, now))
        _write_marks(db, scope, after)
    return after
