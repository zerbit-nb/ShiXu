"""Opt-in startup history, sharing source receipts with live ingestion."""
import asyncio
from datetime import datetime
import hashlib
from uuid import uuid4

from app.database import utc_now
from app.services.matching import change_notice
from app.services.reception_filter import is_trivial_reply
from app.services.time_parser import TZ


def window(now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(), now.isoformat()


def init_history(db):
    db.conn.executescript("""
    CREATE TABLE IF NOT EXISTS history_settings (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL);
    INSERT OR IGNORE INTO history_settings VALUES (1,0);
    CREATE TABLE IF NOT EXISTS history_runs (id TEXT PRIMARY KEY, source TEXT NOT NULL, scope TEXT NOT NULL,
        since TEXT NOT NULL, until TEXT NOT NULL, state TEXT NOT NULL, auto_allowed INTEGER NOT NULL,
        has_changes INTEGER NOT NULL DEFAULT 0, reason TEXT, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS history_messages (message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
        run_id TEXT NOT NULL REFERENCES history_runs(id), auto_allowed INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS history_messages_run ON history_messages(run_id);
    """)


def enabled(db):
    return bool(db.conn.execute('SELECT enabled FROM history_settings WHERE id=1').fetchone()[0])


def begin_run(db, source, scope, since, until, auto_allowed):
    identity = uuid4().hex
    with db.conn:
        db.conn.execute('INSERT INTO history_runs VALUES (?,?,?,?,?,?,?,0,NULL,?)',
                        (identity, source, scope, since, until, 'collecting', int(auto_allowed), utc_now()))
    return identity


def record_message(db, message_id, text, run_id):
    """Inside the source's receipt transaction. Never changes a human decision."""
    run = db.conn.execute('SELECT * FROM history_runs WHERE id=?', (run_id,)).fetchone()
    if not run or run['state'] != 'collecting':
        raise ValueError('history_run_not_active')
    db.conn.execute('INSERT INTO history_messages VALUES (?,?,?)', (message_id, run_id, run['auto_allowed']))
    if change_notice(text):
        db.conn.execute('UPDATE history_runs SET has_changes=1 WHERE id=?', (run_id,))
    # Only exact acknowledgements are confidently excluded locally. Ambiguous
    # short messages remain available; absence of a keyword is not proof of chat.
    if is_trivial_reply(text):
        db.conn.execute('INSERT OR IGNORE INTO message_trash VALUES (?,?)', (message_id, utc_now()))


def finish_run(db, run_id, state, reason=None):
    if state not in {'complete', 'partial'}:
        raise ValueError('invalid_history_state')
    with db.conn:
        db.conn.execute('UPDATE history_runs SET state=?,reason=?,updated_at=? WHERE id=?',
                        (state, reason, utc_now(), run_id))
        db.conn.execute('''UPDATE history_messages SET auto_allowed=0 WHERE run_id=? AND
            EXISTS (SELECT 1 FROM history_runs r WHERE r.id=run_id AND (r.state!='complete' OR r.has_changes=1))''', (run_id,))


class HistoryCatchup:
    def __init__(self, db, qq, login, wechat, automation):
        self.db, self.qq, self.login, self.wechat, self.automation = db, qq, login, wechat, automation
        self.wechat.history_permission = lambda: automation.public()['state'] == 'ready'
        init_history(db)
        with db.conn:
            db.conn.execute("UPDATE history_runs SET state='partial',reason='interrupted' WHERE state='collecting'")
            db.conn.execute("UPDATE history_messages SET auto_allowed=0 WHERE run_id IN (SELECT id FROM history_runs WHERE state='partial')")
        self.revision = 0
        self.qq_done = set()
        self.wechat_attempt = None

    def public(self):
        runs = self.db.conn.execute('''SELECT r.id,r.source,r.since,r.until,r.state,r.reason,r.has_changes,
            count(h.message_id) AS received,
            sum(CASE WHEN t.message_id IS NOT NULL THEN 1 ELSE 0 END) AS filtered
            FROM history_runs r LEFT JOIN history_messages h ON h.run_id=r.id
            LEFT JOIN message_trash t ON t.message_id=h.message_id
            WHERE r.rowid IN (SELECT max(rowid) FROM history_runs GROUP BY source,scope)
            GROUP BY r.id ORDER BY r.rowid DESC LIMIT 120''').fetchall()
        return {'enabled': enabled(self.db), 'timezone': 'Asia/Shanghai', 'runs': [dict(r) for r in runs]}

    def configure(self, value):
        with self.db.conn:
            self.db.conn.execute('UPDATE history_settings SET enabled=? WHERE id=1', (int(value),))
            if not value:
                self.db.conn.execute("UPDATE history_messages SET auto_allowed=0 WHERE run_id IN (SELECT id FROM history_runs WHERE state='collecting')")
        self.revision += 1
        self.qq_done.clear()
        self.wechat_attempt = None
        return self.public()

    async def catchup_qq(self, now=None):
        from app.routers.qq import QQEvent, receive
        qq = self.qq
        if not enabled(self.db) or not qq.enabled or self.login.policy.paused:
            return
        account, groups, revision = qq.account_id, tuple(qq.group_ids), self.revision
        try:
            status = await self.login.status(account)
            if not status.get('online') or status.get('account_id') != account:
                return
        except Exception:
            return
        for group in groups:
            key = (account, group)
            if key in self.qq_done:
                continue
            since, until = window(now)
            low, high = datetime.fromisoformat(since).timestamp(), datetime.fromisoformat(until).timestamp()
            scope = hashlib.sha256((account+':'+group).encode()).hexdigest()
            run = begin_run(self.db, 'qq', scope, since, until, self.automation.public()['state'] == 'ready')
            state, reason, anchor, previous_oldest, rows = 'partial', 'source_limit', None, None, {}
            try:
                # Bounded, backwards pagination. Short pages are not proof of exhaustion.
                for _ in range(100):
                    page = await self.login.history(account, group, anchor)
                    if revision != self.revision or not enabled(self.db) or self.login.policy.paused or qq.account_id != account or tuple(qq.group_ids) != groups:
                        raise ValueError('configuration_changed')
                    if not page:
                        state, reason = 'complete', None
                        break
                    validated = []
                    for raw in page:
                        if raw.get('self_id') is not None and str(raw['self_id']) != account:
                            raise ValueError('account_or_group_changed')
                        event = QQEvent.model_validate(dict(raw, self_id=int(account)))
                        if str(event.group_id) != group:
                            raise ValueError('account_or_group_changed')
                        sequence=raw.get('real_seq', raw.get('message_seq',len(validated)))
                        sequence=int(sequence) if str(sequence).isdigit() else len(validated)
                        validated.append((event, raw.get('message_id'),sequence))
                    oldest = min(e.time for e, _, _ in validated)
                    for event, _, _ in validated:
                        if low <= event.time <= high:
                            rows[str(event.message_id)] = event
                    if oldest < low:
                        state, reason = 'complete', None
                        break
                    if len(validated)==1 and str(validated[0][1])==str(anchor):
                        # The inclusive source returns only the boundary message:
                        # all records currently readable from this source were checked.
                        state, reason = 'complete', None
                        break
                    # Page overlap is normal; lack of timestamp progress may also
                    # be normal for many same-second messages. Track message IDs.
                    earliest = min(validated, key=lambda item: (item[0].time, item[2]))
                    next_anchor = earliest[1]
                    signature = frozenset(str(e.message_id) for e, _, _ in validated)
                    if signature == previous_oldest or next_anchor == anchor:
                        reason = 'pagination_stalled'
                        break
                    previous_oldest, anchor = signature, next_anchor
                    await asyncio.sleep(.1)
            except asyncio.CancelledError:
                finish_run(self.db, run, 'partial', 'interrupted')
                raise
            except Exception:
                state, reason = 'partial', 'source_unavailable'
            # No awaits while writing: auto organization cannot see a half batch.
            if revision == self.revision and enabled(self.db) and not self.login.policy.paused and qq.account_id == account and tuple(qq.group_ids) == groups:
                try:
                    texts = [e.message if isinstance(e.message, str) else ''.join(
                        str(s.get('data', {}).get('text', '')) for s in e.message if s.get('type') == 'text') for e in rows.values()]
                    if any(change_notice(text) for text in texts):
                        with self.db.conn:
                            self.db.conn.execute('UPDATE history_runs SET has_changes=1 WHERE id=?', (run,))
                    for event in sorted(rows.values(), key=lambda e: (e.time, e.message_id)):
                        receive(self.db, event, history_run=run)
                except Exception:
                    state, reason = 'partial', 'source_unavailable'
            else:
                state, reason = 'partial', 'configuration_changed'
            finish_run(self.db, run, state, reason)
            if state == 'complete':
                self.qq_done.add(key)

    async def run(self):
        while True:
            try:
                if enabled(self.db):
                    config = self.wechat.config
                    key = (config.alias_hash, config.group_name, tuple(g.id for g in config.groups))
                    if config.alias_hash and config.group_name and key != self.wechat_attempt:
                        self.wechat_attempt = key
                        if self.wechat.state == 'paused':
                            await self.wechat.start()
                    await self.catchup_qq()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Source errors are exposed by the source status/run, without
                # returning exception text that might contain upstream credentials.
                pass
            await asyncio.sleep(30)
