from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON')
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY, source TEXT NOT NULL, source_group TEXT,
          sender TEXT, sent_at TEXT, raw_text TEXT NOT NULL,
          extraction_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS message_trash (
          message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
          trashed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reception_filter_settings (
          id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL CHECK(enabled IN (0,1))
        );
        INSERT OR IGNORE INTO reception_filter_settings VALUES (1,0);
        CREATE TABLE IF NOT EXISTS drafts (
          id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(id),
          fields_json TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'pending', task_id TEXT UNIQUE,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
          id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(id),
          draft_id TEXT NOT NULL UNIQUE REFERENCES drafts(id), title TEXT NOT NULL,
          description TEXT, deadline TEXT, deadline_precision TEXT NOT NULL DEFAULT 'unknown',
          deadline_text TEXT, location TEXT, target_audience TEXT,
          materials_json TEXT NOT NULL DEFAULT '[]', format_requirement TEXT,
          submit_method TEXT, priority TEXT NOT NULL DEFAULT 'normal',
          status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        ''')
        self.conn.execute('CREATE TABLE IF NOT EXISTS task_sources (task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, message_id TEXT NOT NULL REFERENCES messages(id), draft_id TEXT NOT NULL UNIQUE REFERENCES drafts(id), linked_at TEXT NOT NULL, PRIMARY KEY(task_id, message_id, draft_id))')
        self.conn.commit()
        self.conn.execute('CREATE TABLE IF NOT EXISTS task_history (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, draft_id TEXT NOT NULL UNIQUE REFERENCES drafts(id), message_id TEXT NOT NULL REFERENCES messages(id), action TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL, operation_json TEXT NOT NULL, confirmed_at TEXT NOT NULL)')
        self.conn.commit()
        # A previous process may have stopped while a request was running.
        self.conn.execute("UPDATE messages SET extraction_status='failed' WHERE extraction_status='extracting'")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def create_message(self, data: dict[str, Any]) -> dict[str, Any]:
        row = {'id': uuid4().hex, 'created_at': utc_now(), **data}
        self.conn.execute('INSERT INTO messages (id, source, source_group, sender, sent_at, raw_text, extraction_status, created_at) VALUES (:id, :source, :source_group, :sender, :sent_at, :raw_text, :extraction_status, :created_at)', row)
        self.conn.commit()
        return dict(row)

    def set_message_status(self, message_id: str, status: str) -> None:
        self.conn.execute('UPDATE messages SET extraction_status=? WHERE id=?', (status, message_id))
        self.conn.commit()

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        row = self.conn.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
        return dict(row) if row else None

    def create_draft(self, message_id: str, fields: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
        now = utc_now()
        row = {'id': uuid4().hex, 'message_id': message_id, 'fields_json': json.dumps(fields, ensure_ascii=False), 'warnings_json': json.dumps(warnings, ensure_ascii=False), 'status': 'pending', 'task_id': None, 'created_at': now, 'updated_at': now}
        self.conn.execute('INSERT INTO drafts VALUES (:id,:message_id,:fields_json,:warnings_json,:status,:task_id,:created_at,:updated_at)', row)
        self.conn.commit()
        return self.get_draft(row['id'])

    def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        row = self.conn.execute('SELECT * FROM drafts WHERE id=?', (draft_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value['fields'] = json.loads(value.pop('fields_json'))
        value['warnings'] = json.loads(value.pop('warnings_json'))
        return value

    def discard_draft(self, draft_id: str) -> bool:
        cur = self.conn.execute("UPDATE drafts SET status='discarded', updated_at=? WHERE id=? AND status='pending'", (utc_now(), draft_id))
        self.conn.commit()
        return cur.rowcount == 1

    def confirm_draft(self, draft_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        draft = self.get_draft(draft_id)
        if not draft:
            return None
        if draft['status'] == 'confirmed':
            row = self.conn.execute('SELECT * FROM tasks WHERE id=?', (draft['task_id'],)).fetchone()
            return self._task(row) if row else None
        if draft['status'] != 'pending':
            raise ValueError('该提取结果已经处理，不能再次创建任务')
        task_id = uuid4().hex
        now = utc_now()
        row = {'id': task_id, 'message_id': draft['message_id'], 'draft_id': draft_id, 'title': fields['title'], 'description': fields.get('description'), 'deadline': fields.get('deadline'), 'deadline_precision': fields.get('deadline_precision', 'unknown'), 'deadline_text': fields.get('deadline_text'), 'location': fields.get('location'), 'target_audience': fields.get('target_audience'), 'materials_json': json.dumps(fields.get('materials', []), ensure_ascii=False), 'format_requirement': fields.get('format_requirement'), 'submit_method': fields.get('submit_method'), 'priority': fields.get('priority', 'normal'), 'status': 'pending', 'created_at': now, 'updated_at': now}
        with self.conn:
            self.conn.execute('INSERT INTO tasks VALUES (:id,:message_id,:draft_id,:title,:description,:deadline,:deadline_precision,:deadline_text,:location,:target_audience,:materials_json,:format_requirement,:submit_method,:priority,:status,:created_at,:updated_at)', row)
            self.conn.execute("UPDATE drafts SET fields_json=?, status='confirmed', task_id=?, updated_at=? WHERE id=?", (json.dumps(fields, ensure_ascii=False), task_id, now, draft_id))
        return self._task(self.conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())

    def _task(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        value = dict(row)
        value['materials'] = json.loads(value.pop('materials_json'))
        return value

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._task(self.conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())

    def list_tasks(self, view: str = 'all') -> list[dict[str, Any]]:
        query = 'SELECT tasks.*, messages.source_group FROM tasks JOIN messages ON tasks.message_id=messages.id'
        params: list[Any] = []
        if view == 'pending': query += " WHERE tasks.status='pending'"
        elif view == 'completed': query += " WHERE tasks.status='completed'"
        elif view == 'cancelled': query += " WHERE tasks.status='cancelled'"
        query += " ORDER BY CASE WHEN deadline IS NULL THEN 1 ELSE 0 END, deadline ASC, tasks.created_at DESC"
        return [self._task(row) for row in self.conn.execute(query, params)]

    def update_task(self, task_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {'title','description','deadline','deadline_precision','deadline_text','location','target_audience','format_requirement','submit_method','priority','materials','status'}
        values = {key: val for key, val in fields.items() if key in allowed}
        if not values: return self.get_task(task_id)
        if 'materials' in values:
            values['materials_json'] = json.dumps(values.pop('materials'), ensure_ascii=False)
        values['updated_at'] = utc_now()
        clause = ', '.join(f'{key}=?' for key in values)
        cur = self.conn.execute(f'UPDATE tasks SET {clause} WHERE id=?', (*values.values(), task_id))
        self.conn.commit()
        return self.get_task(task_id) if cur.rowcount else None

    def delete_task(self, task_id: str) -> bool:
        cur = self.conn.execute('DELETE FROM tasks WHERE id=?', (task_id,))
        self.conn.commit()
        return cur.rowcount == 1

    def link_draft(self, draft_id: str, task_id: str) -> dict[str, Any]:
        with self.conn:
            draft = self.get_draft(draft_id)
            task = self.get_task(task_id)
            if not draft or not task:
                raise LookupError('草稿或任务不存在')
            if draft['status'] == 'linked' and self.conn.execute('SELECT 1 FROM task_sources WHERE draft_id=? AND task_id=?', (draft_id, task_id)).fetchone():
                return task
            if draft['status'] != 'pending':
                raise ValueError('该草稿已处理，不能再次关联')
            now = utc_now()
            self.conn.execute('INSERT INTO task_sources VALUES (?,?,?,?)', (task_id, draft['message_id'], draft_id, now))
            # Existing drafts.task_id is UNIQUE; association uses task_sources instead.
            self.conn.execute("UPDATE drafts SET status='linked', updated_at=? WHERE id=?", (now, draft_id))
        return task

    def task_sources(self, task_id: str) -> list[dict[str, Any]]:
        task = self.get_task(task_id)
        if not task:
            return []
        rows = self.conn.execute('SELECT messages.* FROM messages JOIN task_sources ON messages.id=task_sources.message_id WHERE task_sources.task_id=? ORDER BY task_sources.rowid', (task_id,)).fetchall()
        seen = {task['message_id']}
        messages = [self.get_message(task['message_id'])]
        for row in rows:
            if row['id'] not in seen:
                seen.add(row['id'])
                messages.append(dict(row))
        return messages
