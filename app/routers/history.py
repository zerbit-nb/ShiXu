"""Startup history preference: local, same-origin, no arbitrary source access."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from app.routers.automation import require_origin
from app.routers.wechat import local_only

router = APIRouter(prefix='/api/history', dependencies=[Depends(local_only)])


class Preference(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool


@router.get('')
async def status(request: Request):
    return request.app.state.history.public()


@router.put('')
async def configure(body: Preference, request: Request):
    require_origin(request)
    return request.app.state.history.configure(body.enabled)
