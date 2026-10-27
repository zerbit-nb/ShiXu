"""Opt-in, durable automatic organization. Never rewrites existing tasks."""
import asyncio
from datetime import datetime
import json
import sqlite3
from uuid import uuid4
from app.database import utc_now
from app.services.extraction import normalize_extraction
from app.services.matching import change_notice, find_matches
from app.services.llm_service import AutoExtractionResult


class AutoOrganizer:
    def __init__(self, db, settings, model_factory, model_lock):
        self.db, self.settings, self.model_factory, self.model_lock = db, settings, model_factory, model_lock
        self.revision = 0
        self.error = None
        self.retry_at = 0
        db.conn.executescript("""
        CREATE TABLE IF NOT EXISTS automation_settings (id INTEGER PRIMARY KEY CHECK(id=1),
            enabled INTEGER NOT NULL, allow_local INTEGER NOT NULL, start_rowid INTEGER NOT NULL);
        INSERT OR IGNORE INTO automation_settings VALUES (1,0,0,0);
        CREATE TABLE IF NOT EXISTS automation_jobs (message_id TEXT PRIMARY KEY REFERENCES messages(id),
            outcome TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS automation_notices (id TEXT PRIMARY KEY, source TEXT NOT NULL,
            tasks_json TEXT NOT NULL, created_at TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0);
        UPDATE automation_jobs SET outcome='interrupted' WHERE outcome='running';
        """)
        # One-time upgrade: only outstanding popup results become pending review.
        # Later popup dismissal and individual task viewing are independent.
        if not db.conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='automation_task_reviews'").fetchone():
            with db.conn:
                db.conn.execute('BEGIN')
                db.conn.execute('CREATE TABLE automation_task_reviews (task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE, viewed_at TEXT)')
                for notice in db.conn.execute('SELECT tasks_json FROM automation_notices WHERE acknowledged=0').fetchall():
                    for task in json.loads(notice['tasks_json']):
                        db.conn.execute('INSERT OR IGNORE INTO automation_task_reviews SELECT id,NULL FROM tasks WHERE id=?', (task['id'],))

    def public(self):
        row = self.db.conn.execute('SELECT * FROM automation_settings WHERE id=1').fetchone()
        reason = ('disabled' if not row['enabled'] else 'local_disabled' if self.settings.provider == 'local' and not row['allow_local']
                  else 'unconfigured' if not self.settings.llm_model or self.settings.provider != 'local' and not self.settings.api_key else 'ready')
        return dict(enabled=bool(row['enabled']), allow_local=bool(row['allow_local']), provider=self.settings.provider,
                    state=reason, error=self.error)

    def configure(self, enabled, allow_local):
        previous = self.public()
        with self.db.conn:
            if enabled and not previous['enabled']:
                cutoff = self.db.conn.execute('SELECT coalesce(max(rowid),0) FROM messages').fetchone()[0]
                self.db.conn.execute('UPDATE automation_settings SET start_rowid=? WHERE id=1', (cutoff,))
            self.db.conn.execute('UPDATE automation_settings SET enabled=?,allow_local=? WHERE id=1', (int(enabled),int(allow_local)))
        self.revision += 1
        self.error = None
        self.retry_at = 0
        return self.public()

    def destination(self):
        return (self.revision, self.settings.provider, self.settings.llm_model, self.settings.llm_base_url, self.settings.api_key)

    async def run_once(self):
        if self.public()['state'] != 'ready' or asyncio.get_running_loop().time() < self.retry_at:
            return
        db = self.db
        row = db.conn.execute("""SELECT m.* FROM messages m WHERE m.rowid >
            (SELECT start_rowid FROM automation_settings WHERE id=1) AND m.source IN ('qq','wechat')
            AND m.extraction_status='received'
            AND NOT EXISTS (SELECT 1 FROM automation_jobs j WHERE j.message_id=m.id)
            AND NOT EXISTS (SELECT 1 FROM message_trash t WHERE t.message_id=m.id)
            AND NOT EXISTS (SELECT 1 FROM drafts d WHERE d.message_id=m.id)
            ORDER BY m.rowid LIMIT 1""").fetchone()
        if not row:
            return
        message = dict(row)
        with db.conn:
            db.conn.execute('INSERT INTO automation_jobs VALUES (?,?,?)', (message['id'],'running',utc_now()))
            db.conn.execute("UPDATE messages SET extraction_status='extracting' WHERE id=?", (message['id'],))
        destination = self.destination()
        try:
            if '[非文本消息' in message['raw_text'] or change_notice(message['raw_text']):
                self.finish(message, 'review')
                return
            async with self.model_lock:
                if destination != self.destination() or self.public()['state'] != 'ready':
                    self.finish(message, 'review')
                    return
                result = AutoExtractionResult.model_validate(await self.model_factory().extract_auto(message)).model_dump()
            if destination != self.destination() or self.public()['state'] != 'ready':
                self.finish(message, 'review')
                return
            evidence = result.pop('evidence').strip()
            decision = result.pop('decision')
            candidates = normalize_extraction(result, datetime.fromisoformat(message['sent_at']) if message.get('sent_at') else None, message['raw_text'])
            if decision != 'notification' or not candidates or len(evidence) < 8 or evidence not in message['raw_text'] or any(d['warnings'] for d in candidates):
                self.finish(message, 'review')
                return
            tasks = db.list_tasks()
            for candidate in candidates:
                fields = candidate['fields']
                if find_matches(fields, message, tasks, db.get_message):
                    self.finish(message, 'review')
                    return
                tasks.append(dict(fields, id='candidate',message_id=message['id'],status='pending',source_group=message.get('source_group')))
            # One transaction covers every draft, task, job and unread notice.
            with db.conn:
                created = []
                for candidate in candidates:
                    draft = db.create_draft(message['id'], candidate['fields'], [], commit=False)
                    task = db.confirm_draft(draft['id'], candidate['fields'], commit=False)
                    db.conn.execute('INSERT INTO automation_task_reviews VALUES (?,NULL)', (task['id'],))
                    created.append({'id':task['id'],'title':task['title']})
                db.conn.execute('INSERT INTO automation_notices VALUES (?,?,?,?,0)', (uuid4().hex,message['source'],json.dumps(created,ensure_ascii=False),utc_now()))
                db.conn.execute("UPDATE messages SET extraction_status='ready' WHERE id=?", (message['id'],))
                db.conn.execute("UPDATE automation_jobs SET outcome='created',updated_at=? WHERE message_id=?", (utc_now(),message['id']))
            self.error = None
        except asyncio.CancelledError:
            self.finish(message, 'interrupted')
            raise
        except Exception:
            self.finish(message, 'failed')
            self.error = '自动整理失败；原消息已保留，可在收件箱手动分析。请检查模型连接与配置。'
            self.retry_at = asyncio.get_running_loop().time() + 60

    def finish(self, message, outcome):
        with self.db.conn:
            self.db.conn.execute('UPDATE automation_jobs SET outcome=?,updated_at=? WHERE message_id=?', (outcome,utc_now(),message['id']))
            self.db.conn.execute("UPDATE messages SET extraction_status=? WHERE id=? AND extraction_status='extracting'", ('failed' if outcome=='failed' else 'received',message['id']))

    async def run(self):
        while True:
            try:
                await self.run_once()
            except sqlite3.Error:
                self.error = '自动整理无法读写本机数据，请检查磁盘与权限。'
            await asyncio.sleep(3)

    def notices(self, limit=30, offset=0):
        rows = self.db.conn.execute('SELECT * FROM automation_notices WHERE acknowledged=0 ORDER BY created_at,rowid LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        notices = []
        for row in rows:
            tasks = []
            for saved in json.loads(row['tasks_json']):
                task = self.db.get_task(saved['id'])
                message = self.db.get_message(task['message_id']) if task else None
                tasks.append(dict(id=saved['id'], title=task['title'] if task else saved['title'],
                    description=task.get('description') if task else None, deadline=task.get('deadline') if task else None,
                    deadline_text=task.get('deadline_text') if task else None, location=task.get('location') if task else None,
                    priority=task.get('priority') if task else 'normal', status=task['status'] if task else 'deleted',
                    source_group=message.get('source_group') if message else None))
            notices.append(dict(id=row['id'],source=row['source'],tasks=tasks,created_at=row['created_at']))
        return notices

    def notice_count(self):
        return self.db.conn.execute('SELECT count(*) FROM automation_notices WHERE acknowledged=0').fetchone()[0]

    def pending_task_ids(self):
        return {row['task_id'] for row in self.db.conn.execute('SELECT task_id FROM automation_task_reviews WHERE viewed_at IS NULL')}

    def task_review_pending(self, task_id):
        row = self.db.conn.execute('SELECT viewed_at FROM automation_task_reviews WHERE task_id=?', (task_id,)).fetchone()
        return row['viewed_at'] is None if row else None

    def mark_viewed(self, task_id):
        with self.db.conn:
            self.db.conn.execute('UPDATE automation_task_reviews SET viewed_at=? WHERE task_id=? AND viewed_at IS NULL', (utc_now(),task_id))

    def processing_count(self):
        if self.public()['state'] != 'ready':
            return 0
        return self.db.conn.execute("""SELECT count(*) FROM messages m WHERE m.rowid >
            (SELECT start_rowid FROM automation_settings WHERE id=1) AND m.source IN ('qq','wechat')
            AND m.extraction_status IN ('received','extracting')
            AND NOT EXISTS (SELECT 1 FROM message_trash t WHERE t.message_id=m.id)
            AND NOT EXISTS (SELECT 1 FROM drafts d WHERE d.message_id=m.id)
            AND NOT EXISTS (SELECT 1 FROM automation_jobs j WHERE j.message_id=m.id AND j.outcome!='running')""").fetchone()[0]

    def acknowledge(self, identity):
        with self.db.conn:
            self.db.conn.execute('UPDATE automation_notices SET acknowledged=1 WHERE id=?', (identity,))
