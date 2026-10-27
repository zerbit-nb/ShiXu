"""Same-origin preferences and durable in-app notifications; no model trigger endpoint."""
import sqlite3
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix='/api/automation')

class Preference(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool
    allow_local: bool

def require_origin(request):
    if request.headers.get('origin') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, '请从拾序页面修改自动整理设置。')

@router.get('')
async def status(request: Request):
    return request.app.state.automation.public()

@router.put('')
async def configure(body: Preference, request: Request):
    require_origin(request)
    try:
        return request.app.state.automation.configure(body.enabled, body.allow_local)
    except sqlite3.Error:
        raise HTTPException(503, '自动整理设置保存失败，请检查磁盘与权限。') from None

@router.get('/notices')
async def notices(request: Request, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    worker = request.app.state.automation
    return {'notices': worker.notices(limit, offset), 'total': worker.notice_count(), 'processing_count': worker.processing_count()}

@router.post('/notices/{identity}/acknowledge')
async def acknowledge(identity: str, request: Request):
    require_origin(request)
    request.app.state.automation.acknowledge(identity)
    return {'ok': True}

@router.post('/tasks/{task_id}/viewed')
async def viewed(task_id: str, request: Request):
    require_origin(request)
    if not request.app.state.db.get_task(task_id):
        raise HTTPException(404, '任务不存在')
    try:
        request.app.state.automation.mark_viewed(task_id)
    except sqlite3.Error:
        raise HTTPException(503, '查看状态保存失败，待办仍在自动整理中，请重试。') from None
    return {'ok': True}
