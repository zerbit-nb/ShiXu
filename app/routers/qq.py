"""Local OneBot 11 QQ group ingestion; never sends messages or quick actions."""
from datetime import datetime, timezone, timedelta
import asyncio
import hashlib
import hmac
import html
import json
from pathlib import Path
import re
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, ValidationError
from app.database import utc_now
from app.schemas import MessageInput, TaskFields
from app.secrets import protect, unprotect
from app.services.reception_filter import apply_filter


class QQConfig(BaseModel):
    enabled: bool = False
    account_id: str = Field(default='', pattern=r'^[0-9]{0,20}$')
    group_ids: list[str] = Field(default_factory=list, max_length=100)
    token: str | None = Field(default=None, min_length=16, max_length=200)


class QQEvent(BaseModel):
    self_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    message_id: int
    time: int = Field(ge=946684800, le=4102444800)
    message: list[dict] | str
    sender: dict = Field(default_factory=dict)


class ProcessRequest(BaseModel):
    action: str = Field(pattern='^(analyze|manual|ignore)$')


class QQReceiver:
    def __init__(self, path):
        self.path = Path(path)
        self.enabled, self.account_id, self.group_ids, self.token = False, '', [], ''
        self.last_event_at = None
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            self.enabled = saved['enabled']
            self.account_id, self.group_ids = saved['account_id'], saved['group_ids']
            self.token = unprotect(saved.get('encrypted_token', ''))

    def public(self):
        return {'enabled': self.enabled, 'account_id': self.account_id, 'group_ids': self.group_ids, 'has_token': bool(self.token), 'last_event_at': self.last_event_at}

    def save(self, body):
        groups = list(dict.fromkeys(body.group_ids))
        if any(not re.fullmatch(r'[1-9][0-9]{4,19}', g) for g in groups):
            raise ValueError('群号请填写 5 至 20 位数字，每行一个')
        token = body.token or self.token
        if body.enabled and (not groups or not re.fullmatch(r'[1-9][0-9]{4,19}', body.account_id) or not token):
            raise ValueError('启用前请填写 QQ 账号、至少一个群号和接收 Token')
        saved = {'enabled': body.enabled, 'account_id': body.account_id, 'group_ids': groups, 'encrypted_token': protect(token)}
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.path)
        self.enabled, self.account_id, self.group_ids, self.token = body.enabled, body.account_id, groups, token
        return self.public()


def init_storage(db):
    db.conn.execute('CREATE TABLE IF NOT EXISTS qq_receipts (account_id TEXT NOT NULL, group_id TEXT NOT NULL, event_id TEXT NOT NULL, message_id TEXT NOT NULL UNIQUE REFERENCES messages(id), PRIMARY KEY(account_id,group_id,event_id))')
    db.conn.commit()


def receive(db, event):
    key = (str(event.self_id), str(event.group_id), str(event.message_id))
    if db.conn.execute('SELECT 1 FROM qq_receipts WHERE account_id=? AND group_id=? AND event_id=?', key).fetchone():
        return
    # Array format is recommended; unsupported segments remain visibly marked.
    if isinstance(event.message, list):
        parts = []
        for segment in event.message:
            kind, data = segment.get('type'), segment.get('data', {})
            if not isinstance(data, dict):
                raise ValueError('消息段格式不正确')
            if kind == 'text':
                if not isinstance(data.get('text'), str):
                    raise ValueError('文本消息段格式不正确')
                parts.append(data['text'])
            else:
                parts.append('[非文本消息，未解析]')
        text = ''.join(parts)
        if not any(s.get('type') == 'text' and s.get('data', {}).get('text', '').strip() for s in event.message):
            return
    else:
        text = html.unescape(re.sub(r'\[CQ:[^\]]*\]', '[非文本消息，未解析]', event.message))
        if not text.replace('[非文本消息，未解析]', '').strip():
            return
    sender = event.sender.get('card') or event.sender.get('nickname') or str(event.user_id)
    data = MessageInput(source='qq', source_group='QQ 群 '+str(event.group_id), sender=sender, raw_text=text, sent_at=datetime.fromtimestamp(event.time, timezone(timedelta(hours=8)))).model_dump(mode='json')
    data.update(id=uuid4().hex, created_at=utc_now(), extraction_status='received')
    with db.conn:
        db.conn.execute('INSERT INTO messages (id,source,source_group,sender,sent_at,raw_text,extraction_status,created_at) VALUES (:id,:source,:source_group,:sender,:sent_at,:raw_text,:extraction_status,:created_at)', data)
        db.conn.execute('INSERT INTO qq_receipts VALUES (?,?,?,?)', (*key, data['id']))
        apply_filter(db, data['id'], text)


def create_router(extract_one, model_factory):
    router = APIRouter()

    @router.get('/api/qq/config')
    async def config(request: Request):
        return {**request.app.state.qq.public(), 'session_paused': request.app.state.qq_login.policy.paused}

    @router.get('/api/qq/status')
    async def connection_status(request: Request):
        qq, db = request.app.state.qq, request.app.state.db
        callback = 'http://127.0.0.1:' + str(request.url.port or 80) + '/api/qq/events'
        if request.app.state.qq_login.policy.paused:
            paused = request.app.state.qq_login.paused_status()
            status = {'state': paused['state'], 'label': '已退出 NapCat' if paused['state'] == 'exited' else 'NapCat 退出尚未确认', 'hint': paused['message'], 'webui_url': None}
        elif not qq.enabled:
            status = {'state': 'disabled', 'label': 'QQ 接收已停用', 'hint': '勾选启用并保存；已有消息仍可整理。', 'webui_url': None}
        else:
            try:
                status = await asyncio.wait_for(request.app.state.bridge.inspect(qq.account_id, qq.token, callback), timeout=9)
            except TimeoutError:
                status = {'state': 'not_running', 'label': 'NapCat 检查超时', 'hint': '双击 StartCampusFlow.cmd，然后重新检查。', 'webui_url': None}
        count = db.conn.execute('SELECT count(*) FROM qq_receipts').fetchone()[0]
        latest = db.conn.execute('SELECT created_at FROM messages JOIN qq_receipts ON messages.id=qq_receipts.message_id ORDER BY messages.rowid DESC LIMIT 1').fetchone()
        return {**status, 'checked_at': utc_now(), 'last_event_at': qq.last_event_at, 'last_message_at': latest[0] if latest else None, 'received_count': count}

    @router.put('/api/qq/config')
    async def configure(body: QQConfig, request: Request):
        try:
            async with request.app.state.qq_login.action_lock:
                return request.app.state.qq.save(body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post('/api/qq/events', status_code=204)
    async def events(request: Request):
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 262144:
                raise HTTPException(413, '事件内容超过大小限制')
            chunks.append(chunk)
        raw = b''.join(chunks)
        qq = request.app.state.qq
        if request.app.state.qq_login.policy.paused:
            raise HTTPException(403, 'NapCat 已退出或正在退出，消息接收已暂停')
        if not qq.enabled:
            raise HTTPException(403, 'QQ 接收已停用')
        signature = 'sha1='+hmac.new(qq.token.encode(), raw, hashlib.sha1).hexdigest()
        supplied = request.headers.get('x-signature', '')
        if not re.fullmatch(r'sha1=[0-9a-f]{40}', supplied) or not hmac.compare_digest(supplied, signature):
            raise HTTPException(401, 'QQ 上报签名不正确')
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
            if str(payload.get('self_id')) != qq.account_id:
                return Response(status_code=204)
            qq.last_event_at = utc_now()
            if payload.get('post_type') != 'message' or payload.get('message_type') != 'group' or str(payload.get('group_id')) not in qq.group_ids:
                return Response(status_code=204)
            if payload.get('sub_type') == 'notice':
                return Response(status_code=204)
            event = QQEvent.model_validate(payload)
            if not request.app.state.qq_login.policy.accepts(event.time):
                return Response(status_code=204)
            receive(request.app.state.db, event)
        except (ValueError, ValidationError, TypeError, OverflowError) as exc:
            raise HTTPException(422, 'QQ 事件格式不正确，请使用 OneBot 11 数组消息格式') from exc
        return Response(status_code=204)

    @router.get('/api/qq/inbox')
    async def inbox(request: Request, limit: int = 50, offset: int = 0):
        db = request.app.state.db
        visible = ' NOT EXISTS (SELECT 1 FROM message_trash mt WHERE mt.message_id=messages.id)'
        rows = db.conn.execute("SELECT messages.* FROM messages JOIN qq_receipts ON messages.id=qq_receipts.message_id WHERE" + visible + " ORDER BY messages.created_at DESC, messages.rowid DESC LIMIT ? OFFSET ?", (max(1,min(limit,100)), max(0,offset))).fetchall()
        total = db.conn.execute('SELECT count(*) FROM messages JOIN qq_receipts ON messages.id=qq_receipts.message_id WHERE' + visible).fetchone()[0]
        return {'messages': [dict(r) for r in rows], 'total': total}

    @router.post('/api/qq/messages/{message_id}/process')
    async def process(message_id: str, body: ProcessRequest, request: Request):
        db = request.app.state.db
        message = db.get_message(message_id)
        if not message or not db.conn.execute('SELECT 1 FROM qq_receipts WHERE message_id=?', (message_id,)).fetchone():
            raise HTTPException(404, 'QQ 消息不存在')
        if message['extraction_status'] not in {'received','failed'}:
            raise HTTPException(409, '这条消息已处理或正在分析，请在草稿区继续核对')
        if body.action == 'analyze':
            return await extract_one(message, model_factory())
        if body.action == 'ignore':
            db.set_message_status(message_id, 'ignored')
            return {'message': db.get_message(message_id), 'drafts': [], 'error': None}
        fields = TaskFields(title='请填写任务标题').model_dump(mode='json')
        draft = db.create_draft(message_id, fields, ['QQ 消息手动整理，请核对原文；非文本内容未解析。'])
        db.set_message_status(message_id, 'ready')
        return {'message': db.get_message(message_id), 'drafts': [draft], 'error': None}

    return router

