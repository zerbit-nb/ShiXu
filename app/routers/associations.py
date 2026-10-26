from fastapi import APIRouter, HTTPException, Request
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from app.schemas import TaskFields, normalize_deadline
from app.services.task_changes import apply_change, task_history
from app.services.matching import find_matches, change_notice

router = APIRouter()


class LinkRequest(BaseModel):
    confirmed: bool
    task_id: str = Field(min_length=1, max_length=64)


@router.post('/api/drafts/{draft_id}/matches')
async def matches(draft_id: str, fields: TaskFields, request: Request):
    db = request.app.state.db
    draft = db.get_draft(draft_id)
    if not draft: raise HTTPException(404, '草稿不存在')
    message = db.get_message(draft['message_id'])
    return {'matches': find_matches(fields.model_dump(mode='json'), message, db.list_tasks(), db.get_message), 'change_notice': change_notice(message.get('raw_text', ''))}


@router.post('/api/drafts/{draft_id}/link')
async def link(draft_id: str, body: LinkRequest, request: Request):
    if not body.confirmed: raise HTTPException(422, '请先确认关联目标')
    try:
        return request.app.state.db.link_draft(draft_id, body.task_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/api/tasks/{task_id}/sources')
async def sources(task_id: str, request: Request):
    db = request.app.state.db
    if not db.get_task(task_id): raise HTTPException(404, '任务不存在')
    return {'messages': db.task_sources(task_id)}


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: bool
    task_id: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=64, max_length=64)
    action: Literal['deadline', 'cancel']
    deadline: str | None = None
    deadline_text: str | None = Field(default=None, max_length=300)

    @field_validator('deadline')
    @classmethod
    def valid_deadline(cls, value):
        return normalize_deadline(value)

    @model_validator(mode='after')
    def consistent(self):
        if self.action == 'deadline' and self.deadline is None:
            raise ValueError('更新期限时请填写确定的日期；不确定时请保留草稿')
        if self.action == 'cancel' and (self.deadline is not None or self.deadline_text is not None):
            raise ValueError('取消任务不会修改期限')
        return self


@router.post('/api/drafts/{draft_id}/apply-change')
async def change(draft_id: str, body: ChangeRequest, request: Request):
    if not body.confirmed: raise HTTPException(422, '请先核对并确认变更')
    try:
        return apply_change(request.app.state.db, draft_id, body)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/api/tasks/{task_id}/history')
async def history(task_id: str, request: Request):
    db = request.app.state.db
    if not db.get_task(task_id): raise HTTPException(404, '任务不存在')
    return {'history': task_history(db, task_id)}
