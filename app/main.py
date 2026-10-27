from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import datetime
import asyncio
import json
import hashlib
from pathlib import Path
from copy import deepcopy
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
import httpx

from app.config import PROVIDERS, Settings
from app.database import Database
from app.schemas import ConfirmRequest, ExtractRequest, ManualDraftInput, MessageInput, TaskFields, TaskPatch
from app.services.extraction import normalize_extraction
from app.routers.associations import router as association_router
from app.routers.completed import router as completed_router
from app.routers.inbox import router as inbox_router
from app.services.task_changes import task_version
from app.routers.qq import QQReceiver, init_storage, create_router as qq_router
from app.services.matching import find_matches, change_notice
from app.services.llm_service import LLMService
from app.services.reminders import annotate, matches_view
from app.services.bridge import BridgeMonitor
from app.services.qq_login import QQLogin
from app.routers.qq_login import router as qq_login_router
from app.routers.wechat import create_router as wechat_router
from app.services.wechat_monitor import WeChatMonitor
from app.services.wechat_store import init_storage as init_wechat_storage
from app.services.auto_organize import AutoOrganizer
from app.routers.automation import router as automation_router

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / 'app' / 'static'


class ModelConfig(BaseModel):
    provider: Literal['local','deepseek','openai'] = 'local'
    llm_base_url: str | None = Field(default=None, max_length=300)
    llm_model: str = Field(default='', max_length=300)
    api_key: str | None = Field(default=None, max_length=1000)
    clear_api_key: bool = False


def create_app(settings=None, db_path=None, llm=None, config_path=None):
    settings = settings or Settings()
    config_path = Path(config_path or ROOT / 'config.local.json')
    settings.load(config_path)
    data_dir = settings.data_dir if settings.data_dir.is_absolute() else ROOT / settings.data_dir

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = Database(db_path or data_dir / 'campusflow.sqlite3')
        init_storage(app.state.db)
        init_wechat_storage(app.state.db)
        app.state.wechat = WeChatMonitor(app.state.db, config_path.with_name('wechat.local.json'))
        app.state.qq = QQReceiver(config_path.with_name('qq.local.json'))
        app.state.model_lock = asyncio.Lock()
        app.state.bridge = BridgeMonitor(config_path.parent)
        app.state.qq_login = QQLogin(app.state.bridge)
        app.state.automation = AutoOrganizer(app.state.db, settings, lambda: llm or LLMService(deepcopy(settings)), app.state.model_lock)
        automation_task = asyncio.create_task(app.state.automation.run())
        try:
            yield
        finally:
            automation_task.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await automation_task
            finally:
                try:
                    result = await app.state.wechat.stop()
                    if result.get('reason') in {'cleanup_failed', 'config_write_failed'}:
                        raise RuntimeError(result['reason'])
                finally:
                    app.state.qq_login.device.clear()
                    app.state.db.close()

    api = FastAPI(title='CampusFlow', version='1.1.0', lifespan=lifespan)
    api.include_router(association_router)
    api.include_router(completed_router)
    api.include_router(inbox_router)
    api.include_router(automation_router)
    api.include_router(qq_login_router)
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
    model = llm or LLMService(settings)

    @api.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not echo input values: a malformed config could contain API keys.
        return JSONResponse({'detail':[{'loc':list(e['loc']), 'msg':e['msg'], 'type':e['type']} for e in exc.errors()]}, status_code=422)

    @api.middleware('http')
    async def boundaries(request: Request, call_next):
        if request.method in {'POST','PATCH','PUT','DELETE'}:
            origin = request.headers.get('origin')
            if origin:
                expected = urlparse(str(request.base_url))
                supplied = urlparse(origin)
                if (supplied.scheme, supplied.netloc) != (expected.scheme, expected.netloc):
                    return JSONResponse({'detail': '禁止来自其他网站的写入请求'}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(('/api/qq/login/','/api/wechat/','/api/automation')):
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
        return response

    def require(value, description='记录'):
        if value is None: raise HTTPException(404, f'{description}不存在')
        return value

    def deadline_fields(fields):
        value = fields.get('deadline')
        fields['deadline_precision'] = 'date_only' if value and len(value) == 10 else ('datetime' if value else 'unknown')
        return fields

    def error_message(exc):
        if isinstance(exc, httpx.TimeoutException): return '模型响应超时，请检查连接或缩短通知后重试。'
        if isinstance(exc, httpx.HTTPStatusError):
            code=exc.response.status_code
            if code in {401,403}: return '服务拒绝认证，请核对 API Key、账户权限和模型权限。'
            if code in {402,429}: return '服务额度不足或请求受限，请检查余额、额度和频率。'
            if code in {400,404}: return '模型或请求参数不被服务支持，请核对模型 ID，并选择支持 Chat Completions 的文本模型。'
            return '模型服务返回错误，请稍后重试。'
        if isinstance(exc, httpx.HTTPError): return '无法连接所选模型服务。请检查地址、网络和模型服务状态。'
        if isinstance(exc, ValidationError): return '模型返回字段格式不符合要求。请重试，或使用手动整理。'
        if isinstance(exc, (ValueError, RuntimeError)):
            return str(exc).replace(settings.api_key,'[密钥已隐藏]')[:500] if settings.api_key else str(exc)[:500]
        return '提取失败，请检查模型配置或使用手动整理。'

    async def extract_one(message, request_model=None):
        db = api.state.db
        db.set_message_status(message['id'], 'extracting')
        try:
            async with api.state.model_lock:
                for attempt in range(2):
                    try:
                        result = await (request_model or model).extract(message)
                        normalized = normalize_extraction(result, datetime.fromisoformat(message['sent_at']) if message.get('sent_at') else None, message['raw_text'])
                        break
                    except (ValueError, ValidationError):
                        if attempt: raise
            # Validate all candidates before writing any drafts.
            drafts = [db.create_draft(message['id'], d['fields'], d['warnings']) for d in normalized]
            db.set_message_status(message['id'], 'ready' if drafts else 'no_action')
            return {'message': db.get_message(message['id']), 'drafts': drafts, 'summary': result.get('summary', ''), 'error': None}
        except Exception as exc:
            db.set_message_status(message['id'], 'failed')
            return {'message': db.get_message(message['id']), 'drafts': [], 'error': error_message(exc)}

    api.include_router(qq_router(extract_one, lambda: llm or LLMService(deepcopy(settings))))
    api.include_router(wechat_router(extract_one, lambda: llm or LLMService(deepcopy(settings))))

    def save_message(input):
        return api.state.db.create_message({**input.model_dump(mode='json'), 'extraction_status': 'pending'})

    @api.get('/api/health')
    async def health():
        return {'status': 'ok', 'version': '1.1.0', 'timezone': 'Asia/Shanghai', 'model_configured': bool(settings.llm_model), 'application': 'CampusFlow', 'instance': hashlib.sha256(str(config_path.resolve()).encode()).hexdigest(), 'desktop_control': getattr(api.state, 'desktop_control', None)}

    @api.get('/api/config')
    async def config():
        return settings.public()

    @api.put('/api/config')
    async def set_config(body: ModelConfig):
        async with api.state.model_lock:
            candidate = deepcopy(settings)
            profile = candidate.profiles[body.provider]
            if body.provider!='local' and body.llm_base_url and body.llm_base_url.rstrip('/')!=PROVIDERS[body.provider]['llm_base_url']:
                raise HTTPException(422,'官方 API 地址固定，不能将密钥发送到其他地址。')
            profile['llm_model']=body.llm_model.strip()
            if body.provider=='local' and body.llm_base_url: profile['llm_base_url']=body.llm_base_url
            if body.api_key and body.api_key.strip(): profile['api_key']=body.api_key.strip()
            if body.clear_api_key: profile['api_key']=''
            try:
                candidate.activate(body.provider)
                profile['llm_base_url']=candidate.llm_base_url
                candidate.save(config_path)
            except ValueError as exc:
                raise HTTPException(422,str(exc)) from exc
            settings.profiles=candidate.profiles
            settings.activate(body.provider)
        return await config()

    @api.get('/api/models')
    async def list_models():
        try:
            async with api.state.model_lock:
                return {'models': await LLMService(settings).models()}
        except Exception as exc:
            raise HTTPException(503, error_message(exc)) from exc

    @api.post('/api/messages/extract')
    async def extract(body: ExtractRequest):
        results = []
        # Pin the selected destination for the whole batch, even if settings change.
        request_model = llm or LLMService(deepcopy(settings))
        for item in body.messages:
            results.append(await extract_one(save_message(item), request_model))
        return {'results': results}

    @api.post('/api/messages/manual')
    async def manual(body: ManualDraftInput):
        message = save_message(MessageInput(**body.model_dump(exclude={'fields'})))
        fields = deadline_fields((body.fields or TaskFields(title='请填写任务标题', description=None)).model_dump(mode='json'))
        draft = api.state.db.create_draft(message['id'], fields, ['这是手动整理草稿，请根据原文填写任务信息。'])
        api.state.db.set_message_status(message['id'], 'ready')
        return {'message': api.state.db.get_message(message['id']), 'drafts': [draft], 'error': None}

    @api.get('/api/messages/{message_id}')
    async def get_message(message_id: str):
        return require(api.state.db.get_message(message_id), '原始消息')

    @api.post('/api/messages/{message_id}/retry')
    async def retry(message_id: str):
        message = require(api.state.db.get_message(message_id))
        if message['extraction_status'] != 'failed':
            raise HTTPException(409, '只有失败的消息可以重新提取，避免重复草稿。')
        return await extract_one(message, llm or LLMService(deepcopy(settings)))

    @api.get('/api/drafts')
    async def drafts():
        rows = api.state.db.conn.execute("SELECT id FROM drafts WHERE status='pending' ORDER BY created_at").fetchall()
        return {'drafts': [api.state.db.get_draft(row['id']) for row in rows]}

    @api.post('/api/drafts/{draft_id}/discard')
    async def discard(draft_id: str):
        require(api.state.db.get_draft(draft_id))
        if not api.state.db.discard_draft(draft_id): raise HTTPException(409, '该草稿已处理')
        return {'ok': True}

    @api.post('/api/drafts/{draft_id}/confirm')
    async def confirm(draft_id: str, body: ConfirmRequest):
        if not body.confirmed: raise HTTPException(422, '请先确认任务信息')
        draft = require(api.state.db.get_draft(draft_id))
        if draft['status'] == 'pending' and not body.duplicate_reviewed:
            message = api.state.db.get_message(draft['message_id'])
            matches = find_matches(body.fields.model_dump(mode='json'), message, api.state.db.list_tasks(), api.state.db.get_message)
            if matches or change_notice(message.get('raw_text', '')):
                raise HTTPException(409, '发现疑似重复或变更通知，请核对已有任务后选择更新、关联、仍然新建或丢弃。')
        try:
            task = api.state.db.confirm_draft(draft_id, deadline_fields(body.fields.model_dump(mode='json')))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if task is None: raise HTTPException(409, '此前创建的任务已经删除，不能重复确认旧草稿。')
        return task

    @api.get('/api/tasks')
    async def tasks(view: str = 'all', remind_hours: int = 24):
        if view not in {'all','pending','completed','cancelled','today','week','no_deadline','overdue'}:
            raise HTTPException(422, '无效筛选项')
        remind_hours = max(0, min(remind_hours, 168))
        pending_review = api.state.automation.pending_task_ids()
        values = [annotate(t, hours=remind_hours) | {'version': task_version(t), 'automation_pending': t['id'] in pending_review} for t in api.state.db.list_tasks(view)]
        return {'tasks': [t for t in values if matches_view(t, view)]}

    @api.get('/api/tasks/{task_id}')
    async def get_task(task_id: str):
        task = require(api.state.db.get_task(task_id), '任务')
        pending = api.state.automation.task_review_pending(task_id)
        return task | {'automation_pending': pending} if pending is not None else task

    @api.patch('/api/tasks/{task_id}')
    async def patch_task(task_id: str, body: TaskPatch):
        require(api.state.db.get_task(task_id), '任务')
        fields = body.model_dump(mode='json', exclude_unset=True)
        if 'deadline' in fields: deadline_fields(fields)
        return require(api.state.db.update_task(task_id, fields), '任务')

    @api.post('/api/tasks/{task_id}/{action}')
    async def task_action(task_id: str, action: str):
        status = {'complete': 'completed', 'reopen': 'pending', 'cancel': 'cancelled'}.get(action)
        if not status: raise HTTPException(404, '操作不存在')
        return require(api.state.db.update_task(task_id, {'status': status}), '任务')

    @api.delete('/api/tasks/{task_id}')
    async def delete(task_id: str):
        if not api.state.db.delete_task(task_id): raise HTTPException(404, '任务不存在')
        return {'ok': True}

    @api.get('/')
    async def index():
        return FileResponse(STATIC / 'index.html')

    if STATIC.exists():
        api.mount('/static', StaticFiles(directory=STATIC), name='static')
    return api


app = create_app()
