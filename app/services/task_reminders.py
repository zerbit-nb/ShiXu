"""Persistent rule-based reminders. No model, external service or extra process."""
import asyncio
from datetime import date, datetime, time, timedelta
import hashlib
import json
import sqlite3
from uuid import uuid4

from app.services.time_parser import TZ

DEFAULTS = dict(enabled=False, daily_enabled=True, daily_time='09:00', lead_minutes=60,
                quiet_enabled=False, quiet_start='22:00', quiet_end='08:00')


class TaskReminders:
    def __init__(self, db):
        self.db = db
        self.error = None
        db.conn.executescript('''
        CREATE TABLE IF NOT EXISTS reminder_settings (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS task_reminder_preferences (task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
            mode TEXT NOT NULL, minutes INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS reminder_events (id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL,
            task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE, kind TEXT NOT NULL, snapshot TEXT NOT NULL,
            due_at TEXT NOT NULL, state TEXT NOT NULL, snoozed INTEGER NOT NULL DEFAULT 0,
            claim_id TEXT, lease_until TEXT, channel TEXT);
        CREATE INDEX IF NOT EXISTS reminder_delivery ON reminder_events(state,due_at);
        ''')
        with db.conn:
            db.conn.execute('INSERT OR IGNORE INTO reminder_settings VALUES (1,?)', (json.dumps(DEFAULTS),))

    def public(self):
        return json.loads(self.db.conn.execute('SELECT config FROM reminder_settings WHERE id=1').fetchone()[0])

    def configure(self, config):
        values = {key: config[key] for key in DEFAULTS}
        if values != self.public():
            with self.db.conn:
                self.db.conn.execute('UPDATE reminder_settings SET config=? WHERE id=1', (json.dumps(values),))
                self.db.conn.execute("UPDATE reminder_events SET state='cancelled',claim_id=NULL WHERE state IN ('pending','claimed','delivered')")
        return self.public()

    def task_config(self, task_id):
        row = self.db.conn.execute('SELECT mode,minutes FROM task_reminder_preferences WHERE task_id=?', (task_id,)).fetchone()
        return dict(row) if row else dict(mode='default', minutes=self.public()['lead_minutes'])

    def set_task(self, task_id, mode, minutes):
        if not self.db.get_task(task_id):
            raise ValueError('任务不存在')
        with self.db.conn:
            self.db.conn.execute('INSERT INTO task_reminder_preferences VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET mode=excluded.mode,minutes=excluded.minutes',
                                 (task_id, mode, minutes))
            self.db.conn.execute("UPDATE reminder_events SET state='cancelled',claim_id=NULL WHERE task_id=? AND state IN ('pending','claimed','delivered')", (task_id,))
        return self.task_config(task_id)

    def _key(self, *values):
        return hashlib.sha256(json.dumps(values).encode()).hexdigest()

    def _add(self, key, task_id, kind, snapshot, due):
        self.db.conn.execute('''INSERT INTO reminder_events VALUES (?,?,?,?,?,?,'pending',0,NULL,NULL,NULL)
            ON CONFLICT(event_key) DO UPDATE SET state='pending',due_at=excluded.due_at,snoozed=0,claim_id=NULL
            WHERE reminder_events.state='cancelled' ''', (uuid4().hex,key,task_id,kind,snapshot,due.isoformat()))

    def _tasks(self, event):
        if event['task_id']:
            task = self.db.get_task(event['task_id'])
            return [task] if task and task['status']=='pending' else []
        day = event['snapshot']
        return [t for t in self.db.list_tasks('pending') if t.get('deadline') and t['deadline'][:10] <= day
                and self.task_config(t['id'])['mode'] != 'off']

    def _event(self, row):
        return dict(id=row['id'], kind=row['kind'], due_at=row['due_at'],
                    tasks=[{key:t.get(key) for key in ('id','title','deadline','deadline_precision','priority','status')} for t in self._tasks(row)])

    def _events(self, rows):
        events, seen = [], set()
        for row in sorted(rows, key=lambda r:r['kind']=='daily'):
            event = self._event(row)
            event['tasks'] = [t for t in event['tasks'] if t['id'] not in seen]
            seen.update(t['id'] for t in event['tasks'])
            if event['tasks']:
                events.append(event)
        return events

    def tick(self, now=None):
        now = (now or datetime.now(TZ)).astimezone(TZ)
        config = self.public()
        with self.db.conn:
            if not config['enabled']:
                self.db.conn.execute("UPDATE reminder_events SET state='cancelled',claim_id=NULL WHERE state IN ('pending','claimed','delivered')")
                return
            valid = set()
            for task in self.db.list_tasks('pending'):
                pref = self.task_config(task['id'])
                if pref['mode']=='off' or not task.get('deadline') or len(task['deadline'])==10:
                    continue
                deadline = datetime.fromisoformat(task['deadline'])
                deadline = deadline.replace(tzinfo=TZ) if deadline.tzinfo is None else deadline.astimezone(TZ)
                minutes = pref['minutes'] if pref['mode']=='custom' else config['lead_minutes']
                key = self._key('deadline',task['id'],task['deadline'],minutes)
                if now <= deadline + (timedelta(minutes=5) if minutes==0 else timedelta()):
                    valid.add(key)
                    due = deadline - timedelta(minutes=minutes)
                    if due <= now:
                        self._add(key, task['id'], 'deadline', task['deadline'], due)
            daily_due = datetime.combine(now.date(), time.fromisoformat(config['daily_time']), TZ)
            daily_key = self._key('daily',now.date().isoformat(),config['daily_time'])
            if config['daily_enabled']:
                valid.add(daily_key)
                if now >= daily_due:
                    self._add(daily_key, None, 'daily', now.date().isoformat(), daily_due)
            rows = self.db.conn.execute("SELECT * FROM reminder_events WHERE state IN ('pending','claimed','delivered')").fetchall()
            for row in rows:
                tasks = self._tasks(row)
                # User snooze may deliberately cross a deadline. Completion,
                # cancellation and rescheduling still invalidate its source.
                snooze_valid = row['snoozed'] and bool(tasks) and (
                    not row['task_id'] or tasks[0]['deadline']==row['snapshot'] and self.task_config(row['task_id'])['mode']!='off')
                if (row['event_key'] not in valid and not snooze_valid) or not tasks:
                    self.db.conn.execute("UPDATE reminder_events SET state='cancelled',claim_id=NULL WHERE id=?", (row['id'],))
            self.db.conn.execute("UPDATE reminder_events SET state='pending',claim_id=NULL WHERE state='claimed' AND lease_until<=?", (now.isoformat(),))

    def _quiet(self, now):
        config = self.public()
        if not config['quiet_enabled']:
            return False
        start, end, current = config['quiet_start'], config['quiet_end'], now.strftime('%H:%M')
        return start <= current < end if start < end else current >= start or current < end

    def claim(self, channel, now=None):
        now = (now or datetime.now(TZ)).astimezone(TZ)
        self.tick(now)
        if not self.public()['enabled'] or self._quiet(now):
            return {'claim_id':None,'events':[]}
        token = uuid4().hex
        with self.db.conn:
            rows = self.db.conn.execute("SELECT * FROM reminder_events WHERE state='pending' AND due_at<=? ORDER BY due_at,rowid LIMIT 100", (now.isoformat(),)).fetchall()
            for row in rows:
                self.db.conn.execute("UPDATE reminder_events SET state='claimed',claim_id=?,lease_until=?,channel=? WHERE id=? AND state='pending'",
                    (token,(now+timedelta(seconds=60)).isoformat(),channel,row['id']))
        return {'claim_id':token if rows else None, 'events':self._events(rows)}

    def delivered(self, token, now=None):
        self.tick(now)
        with self.db.conn:
            rows = self.db.conn.execute("SELECT * FROM reminder_events WHERE claim_id=? AND state='claimed'", (token,)).fetchall()
            self.db.conn.execute("UPDATE reminder_events SET state='delivered' WHERE claim_id=? AND state='claimed'", (token,))
            events = self._events(rows)
            visible = {event['id'] for event in events}
            for row in rows:
                if row['id'] not in visible:
                    self.db.conn.execute("UPDATE reminder_events SET state='acknowledged' WHERE id=?", (row['id'],))
        return {'events':events}

    def release(self, token):
        with self.db.conn:
            self.db.conn.execute("UPDATE reminder_events SET state='pending',claim_id=NULL WHERE claim_id=? AND state IN ('claimed','delivered')", (token,))

    def active(self):
        self.tick()
        rows = self.db.conn.execute("SELECT * FROM reminder_events WHERE state='delivered' ORDER BY due_at,rowid LIMIT 100").fetchall()
        return {'events':self._events(rows)}

    def acknowledge(self, identity):
        with self.db.conn:
            self.db.conn.execute("UPDATE reminder_events SET state='acknowledged',claim_id=NULL WHERE id=? AND state IN ('delivered','claimed')", (identity,))

    def snooze(self, identity, minutes, now=None):
        now = (now or datetime.now(TZ)).astimezone(TZ)
        self.tick(now)
        row = self.db.conn.execute("SELECT * FROM reminder_events WHERE id=? AND state IN ('delivered','claimed')", (identity,)).fetchone()
        if not row or not self._tasks(row):
            raise ValueError('提醒已失效，请刷新待办')
        with self.db.conn:
            self.db.conn.execute("UPDATE reminder_events SET due_at=?,state='pending',snoozed=1,claim_id=NULL WHERE id=?", ((now+timedelta(minutes=minutes)).isoformat(),identity))

    async def run(self):
        while True:
            try:
                self.tick()
                self.error = None
            except (sqlite3.Error, ValueError):
                self.error = '提醒暂不可用，请检查本机数据与时间设置。'
            await asyncio.sleep(15)
