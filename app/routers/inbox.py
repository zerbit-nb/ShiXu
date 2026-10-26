"""Cross-platform inbox with reversible trash; processing endpoints stay authoritative."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
import sqlite3
from app.database import utc_now
from app.services.reception_filter import enabled

router = APIRouter()


class ReceptionFilterConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool


@router.get('/api/inbox/filter')
async def filter_config(request: Request):
    return {'enabled': enabled(request.app.state.db)}


@router.put('/api/inbox/filter')
async def save_filter_config(body: ReceptionFilterConfig, request: Request):
    if request.headers.get('origin') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, '请从拾序页面修改接收过滤。')
    db = request.app.state.db
    try:
        with db.conn:
            db.conn.execute('UPDATE reception_filter_settings SET enabled=? WHERE id=1', (int(body.enabled),))
    except sqlite3.Error:
        raise HTTPException(503, '接收过滤保存失败，请检查磁盘与权限后重试。') from None
    return {'enabled': enabled(db)}

@router.get('/api/inbox')
async def inbox(request: Request,
                source: Literal['all', 'qq', 'wechat', 'manual'] = 'all',
                status: Literal['all', 'pending', 'processed', 'task', 'ignored', 'no_action', 'failed'] = 'all',
                folder: Literal['inbox', 'trash'] = 'inbox',
                limit: int = Query(30, ge=1, le=100),
                offset: int = Query(0, ge=0, le=1000000)):
    db = request.app.state.db
    # Count live tasks through both original and later source associations, once each.
    linked = "(SELECT count(*) FROM tasks t WHERE t.message_id=m.id OR EXISTS (SELECT 1 FROM task_sources s WHERE s.task_id=t.id AND s.message_id=m.id))"
    membership = 'EXISTS (SELECT 1 FROM message_trash mt WHERE mt.message_id=m.id)'
    conditions = [membership if folder == 'trash' else 'NOT ' + membership]
    params = []
    if source != 'all':
        conditions.append('m.source=?')
        params.append(source)
    if status == 'pending':
        conditions.append("m.extraction_status IN ('received','pending','failed')")
    elif status == 'processed':
        conditions.append("(m.extraction_status='ready' OR " + linked + '>0)')
    elif status == 'task':
        conditions.append(linked + '>0')
    elif status != 'all':
        conditions.append('m.extraction_status=?')
        params.append(status)
    where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
    total = db.conn.execute('SELECT count(*) FROM messages m' + where, params).fetchone()[0]
    rows = db.conn.execute("SELECT m.*, (SELECT count(*) FROM drafts d WHERE d.message_id=m.id AND d.status='pending') AS pending_draft_count, " + linked + ' AS task_count FROM messages m' + where +
                           ' ORDER BY julianday(m.created_at) DESC, m.rowid DESC LIMIT ? OFFSET ?',
                           [*params, limit, offset]).fetchall()
    messages = [dict(row) for row in rows]
    if messages:
        placeholders = ','.join('?' for _ in messages)
        ids = [message['id'] for message in messages]
        associations = db.conn.execute(
            'SELECT message_id, id, title, status FROM tasks WHERE message_id IN (' + placeholders + ') '
            'UNION SELECT s.message_id, t.id, t.title, t.status FROM task_sources s JOIN tasks t ON t.id=s.task_id '
            'WHERE s.message_id IN (' + placeholders + ') ORDER BY id', ids + ids).fetchall()
        by_message = {message['id']: [] for message in messages}
        for row in associations:
            by_message[row['message_id']].append({'id': row['id'], 'title': row['title'], 'status': row['status']})
        for message in messages:
            message['tasks'] = by_message[message['id']]
    return {'messages': messages, 'total': total}


@router.post('/api/inbox/{message_id}/trash')
async def trash_message(message_id: str, request: Request):
    db = request.app.state.db
    message = db.get_message(message_id)
    if not message:
        raise HTTPException(404, '消息不存在')
    if message['extraction_status'] == 'extracting':
        raise HTTPException(409, '消息正在分析，请结束后再移入垃圾桶')
    with db.conn:
        db.conn.execute('INSERT INTO message_trash (message_id, trashed_at) VALUES (?, ?) ON CONFLICT(message_id) DO NOTHING', (message_id, utc_now()))
    return {'id': message_id, 'trashed': True}


@router.post('/api/inbox/{message_id}/restore')
async def restore_message(message_id: str, request: Request):
    db = request.app.state.db
    if not db.get_message(message_id):
        raise HTTPException(404, '消息不存在')
    with db.conn:
        db.conn.execute('DELETE FROM message_trash WHERE message_id=?', (message_id,))
    return {'id': message_id, 'trashed': False}
