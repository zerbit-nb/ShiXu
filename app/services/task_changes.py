import hashlib
import json
from uuid import uuid4
from app.database import utc_now


def task_version(task):
    # list_tasks adds source_group; the version covers the persisted task only.
    value = {k: v for k, v in task.items() if k != 'source_group'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def apply_change(db, draft_id, body):
    operation = body.model_dump(mode='json', exclude={'confirmed', 'version'})
    with db.conn:
        db.conn.execute('BEGIN IMMEDIATE')
        draft = db.get_draft(draft_id)
        task = db.get_task(body.task_id)
        if not draft or not task:
            raise LookupError('草稿或任务不存在')
        previous = db.conn.execute('SELECT operation_json FROM task_history WHERE draft_id=?', (draft_id,)).fetchone()
        if previous:
            if json.loads(previous['operation_json']) != operation:
                raise ValueError('此草稿已经确认过其他变更，不能重复处理')
            return task
        if draft['status'] != 'pending':
            raise ValueError('此草稿已处理，不能再次更新任务')
        if task_version(task) != body.version:
            raise ValueError('已有任务已发生变化，请重新核对后确认')
        if task['status'] != 'pending':
            raise ValueError('仅支持更新未完成任务，请先核对任务状态')
        now = utc_now()
        if body.action == 'deadline':
            if body.deadline == task['deadline']:
                raise ValueError('新旧期限相同，无需更新')
            precision = 'datetime' if 'T' in body.deadline else 'date_only'
            db.conn.execute('UPDATE tasks SET deadline=?, deadline_precision=?, deadline_text=?, updated_at=? WHERE id=?', (body.deadline, precision, body.deadline_text, now, body.task_id))
        else:
            db.conn.execute("UPDATE tasks SET status='cancelled', updated_at=? WHERE id=?", (now, body.task_id))
        after = db.get_task(body.task_id)
        db.conn.execute('INSERT INTO task_sources VALUES (?,?,?,?)', (body.task_id, draft['message_id'], draft_id, now))
        db.conn.execute('INSERT INTO task_history (id,task_id,draft_id,message_id,action,before_json,after_json,operation_json,confirmed_at) VALUES (?,?,?,?,?,?,?,?,?)', (uuid4().hex, body.task_id, draft_id, draft['message_id'], body.action, json.dumps(task, ensure_ascii=False), json.dumps(after, ensure_ascii=False), json.dumps(operation, ensure_ascii=False), now))
        db.conn.execute("UPDATE drafts SET status='applied', updated_at=? WHERE id=?", (now, draft_id))
    return after


def task_history(db, task_id):
    rows = db.conn.execute('SELECT * FROM task_history WHERE task_id=? ORDER BY rowid', (task_id,)).fetchall()
    entries = []
    for row in rows:
        entry = dict(row)
        entry['before'] = json.loads(entry.pop('before_json'))
        entry['after'] = json.loads(entry.pop('after_json'))
        entry.pop('operation_json')
        entry['message'] = db.get_message(entry['message_id'])
        entries.append(entry)
    return entries
