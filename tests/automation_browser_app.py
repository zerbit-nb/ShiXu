"""Disposable browser fixture: synthetic QQ/WeChat messages and deterministic local model."""
from contextlib import asynccontextmanager
from pathlib import Path
import json
from uuid import uuid4
from datetime import datetime, timedelta, timezone
import sys
from fastapi import Request
from app.config import Settings
from app.main import create_app
from tests.test_auto_organize import Model, TEXT

root=Path(sys.argv[1])
class BrowserModel(Model):
    async def extract_auto(self, message):
        if message['source']=='wechat':
            return {'decision':'notification','evidence':'请于2026年12月31日18:00前提交活动报名表','is_actionable':True,
                    'tasks':[{'title':'填写活动报名表','deadline_text':'2026年12月31日18:00','materials':['活动报名表']}]}
        return await super().extract_auto(message)
app=create_app(Settings(llm_model='browser-fixture'),db_path=root/'db',config_path=root/'config',llm=BrowserModel())

@app.post('/test/receive/{source}')
async def receive(source: str, request: Request):
    text=TEXT if source=='qq' else '通知：请于2026年12月31日18:00前提交活动报名表。'
    item=request.app.state.db.create_message(dict(source=source,source_group='演示群',sender='演示成员',sent_at='2026-10-26T12:00:00+08:00',raw_text=text,extraction_status='received'))
    return item

@app.post('/test/batch')
async def batch(request: Request):
    db=request.app.state.db
    for i in range(35):
        item=db.create_message(dict(source='wechat',source_group='演示群',sender='测试者',sent_at='2026-10-26T12:00:00+08:00',raw_text='滚动测试原文',extraction_status='ready'))
        fields=dict(title=('核对 <img src=x onerror=alert(1)> 与材料清单' if i==0 else '核对第 '+str(i+1)+' 份项目材料'),description='请核对项目材料并提交确认表。',deadline='2026-12-31T18:00:00+08:00',deadline_text='12月31日18:00',priority='normal',location='项目办公室',materials=[])
        draft=db.create_draft(item['id'],fields,[])
        task=db.confirm_draft(draft['id'],fields)
        with db.conn:
            db.conn.execute('INSERT INTO automation_task_reviews VALUES (?,NULL)',(task['id'],))
            db.conn.execute('INSERT INTO automation_notices VALUES (?,?,?,?,0)',(uuid4().hex,'wechat',json.dumps([dict(id=task['id'],title=task['title'])]),'2026-10-26T13:00:00+00:00'))
    return {'created':35}

@app.post('/test/review-scenario')
async def review_scenario(request: Request):
    db=request.app.state.db;today=datetime.now(timezone(timedelta(hours=8))).date();ids={};automatic=[]
    for name,title,days in [('regular','手动创建的逾期待办',-2),('overdue','自动整理的逾期待办',-1),('today','自动整理的今日待办',0),('unknown','自动整理的无期限待办',None),('week','自动整理的近期待办',2)]:
        item=db.create_message(dict(source='manual' if name=='regular' else 'wechat',source_group='演示群',sender='测试者',sent_at='2026-10-26T12:00:00+08:00',raw_text='请核对项目材料并提交确认表。',extraction_status='ready'))
        fields=dict(title=title,deadline=(today+timedelta(days=days)).isoformat() if days is not None else None,deadline_precision='date_only' if days is not None else 'unknown',materials=[],priority='normal')
        draft=db.create_draft(item['id'],fields,[]);task=db.confirm_draft(draft['id'],fields);ids[name]=task['id']
        if name!='regular':
            with db.conn:db.conn.execute('INSERT INTO automation_task_reviews VALUES (?,NULL)',(task['id'],))
            automatic.append(dict(id=task['id'],title=task['title']))
    with db.conn:db.conn.execute('INSERT INTO automation_notices VALUES (?,?,?,?,0)',(uuid4().hex,'wechat',json.dumps(automatic),'2026-10-26T13:00:00+00:00'))
    return ids
