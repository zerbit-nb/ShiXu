"""Local reminder settings and atomic presentation claims."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.routers.automation import require_origin
from app.routers.wechat import local_only

router = APIRouter(prefix='/api/reminders', dependencies=[Depends(local_only)])


def write(request: Request):
    require_origin(request)


class Preference(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool
    daily_enabled: bool
    daily_time: str
    lead_minutes: int = Field(ge=0, le=43200)
    quiet_enabled: bool
    quiet_start: str
    quiet_end: str

    @field_validator('daily_time','quiet_start','quiet_end')
    @classmethod
    def clock(cls, value):
        import re
        if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', value):
            raise ValueError('请填写有效时刻')
        return value

    @model_validator(mode='after')
    def quiet_interval(self):
        if self.quiet_enabled and self.quiet_start==self.quiet_end:
            raise ValueError('静音开始和结束时间不能相同')
        return self


class TaskPreference(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    mode: Literal['default','off','custom']
    minutes: int = Field(ge=0, le=43200)


class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    channel: Literal['foreground','system']


class Snooze(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    minutes: Literal[15,60,180,1440]


@router.get('')
async def status(request: Request):
    worker = request.app.state.reminders
    return worker.public() | {'error':worker.error}


@router.put('', dependencies=[Depends(write)])
async def configure(body: Preference, request: Request):
    return request.app.state.reminders.configure(body.model_dump())


@router.get('/tasks/{task_id}')
async def task_config(task_id: str, request: Request):
    if not request.app.state.db.get_task(task_id):
        raise HTTPException(404,'任务不存在')
    return request.app.state.reminders.task_config(task_id)


@router.put('/tasks/{task_id}', dependencies=[Depends(write)])
async def set_task(task_id: str, body: TaskPreference, request: Request):
    try:
        return request.app.state.reminders.set_task(task_id,body.mode,body.minutes)
    except ValueError:
        raise HTTPException(404,'任务不存在') from None


@router.post('/claim', dependencies=[Depends(write)])
async def claim(body: Claim, request: Request):
    return request.app.state.reminders.claim(body.channel)


@router.post('/delivery/{token}/confirm', dependencies=[Depends(write)])
async def delivered(token: str, request: Request):
    return request.app.state.reminders.delivered(token)


@router.post('/delivery/{token}/release', dependencies=[Depends(write)])
async def release(token: str, request: Request):
    request.app.state.reminders.release(token)
    return {'ok':True}


@router.get('/events')
async def events(request: Request):
    return request.app.state.reminders.active()


@router.post('/events/{identity}/acknowledge', dependencies=[Depends(write)])
async def acknowledge(identity: str, request: Request):
    request.app.state.reminders.acknowledge(identity)
    return {'ok':True}


@router.post('/events/{identity}/snooze', dependencies=[Depends(write)])
async def snooze(identity: str, body: Snooze, request: Request):
    try:
        request.app.state.reminders.snooze(identity,body.minutes)
    except ValueError as exc:
        raise HTTPException(409,str(exc)) from None
    return {'ok':True}
