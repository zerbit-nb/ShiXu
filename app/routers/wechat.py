"""Local WeChat capture controls and explicit message-to-draft processing."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.schemas import TaskFields
from app.services.wechat_monitor import MonitorError, MESSAGES


def local_only(request:Request):
    if not request.client or request.client.host not in {'127.0.0.1','::1','testclient'}:
        raise HTTPException(403,'微信控制接口仅允许本机访问。')


class ConfigInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    group_name:str=Field(min_length=1,max_length=200)
    account_alias:str=Field(min_length=1,max_length=100)

class ProcessInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    action:Literal["analyze","manual","ignore"]


def create_router(extract_one,model_factory):
    router=APIRouter(prefix="/api/wechat",dependencies=[Depends(local_only)])

    @router.get('/config')
    async def config(request:Request):return request.app.state.wechat.public_config()

    @router.get('/status')
    async def status(request:Request):return request.app.state.wechat.status()

    async def control(operation):
        try:return await operation
        except MonitorError as exc:
            raise HTTPException(409,MESSAGES.get(exc.args[0],MESSAGES['source_error'])) from None
        except OSError:
            raise HTTPException(503,'无法保存微信配置或准备工作目录，请检查磁盘与权限。') from None

    @router.put('/config')
    async def configure(body:ConfigInput,request:Request):
        return await control(request.app.state.wechat.configure(body.group_name,body.account_alias))

    @router.post('/start')
    async def start(request:Request):return await control(request.app.state.wechat.start())

    @router.post('/stop')
    async def stop(request:Request):return await control(request.app.state.wechat.stop())

    @router.get('/messages')
    async def messages(request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=1000000)):
        db=request.app.state.db
        visible=' NOT EXISTS (SELECT 1 FROM message_trash mt WHERE mt.message_id=messages.id)'
        total=db.conn.execute('SELECT count(*) FROM messages JOIN wechat_receipts ON messages.id=wechat_receipts.message_id WHERE'+visible).fetchone()[0]
        rows=db.conn.execute('SELECT messages.* FROM messages JOIN wechat_receipts ON messages.id=wechat_receipts.message_id WHERE'+visible+' ORDER BY messages.rowid DESC LIMIT ? OFFSET ?',
                             (limit,offset)).fetchall()
        return {'messages':[dict(row) for row in rows],'total':total}

    @router.post('/messages/{message_id}/process')
    async def process(message_id:str,body:ProcessInput,request:Request):
        db=request.app.state.db
        message=db.get_message(message_id)
        if not message or not db.conn.execute('SELECT 1 FROM wechat_receipts WHERE message_id=?',(message_id,)).fetchone():
            raise HTTPException(404,'微信消息不存在。')
        if message['extraction_status'] not in {'received','failed'}:
            raise HTTPException(409,'消息已处理或正在分析，请在导入通知中核对草稿。')
        if body.action=='analyze':
            # extract_one sets extracting before its first await, preventing parallel processing.
            return await extract_one(message,model_factory())
        if body.action=='ignore':
            db.set_message_status(message_id,'ignored')
            return {'message':db.get_message(message_id),'drafts':[],'error':None}
        fields=TaskFields(title='请填写任务标题').model_dump(mode='json')
        draft=db.create_draft(message_id,fields,['微信消息手动整理，请核对原文、发送者和时间；仅接收文本。'])
        db.set_message_status(message_id,'ready')
        return {'message':db.get_message(message_id),'drafts':[draft],'error':None}

    return router
