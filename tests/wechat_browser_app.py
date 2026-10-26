"""Isolated browser fixture: synthetic receipts, stub model, no desktop capture."""
from contextlib import asynccontextmanager
from types import MethodType
from app.main import create_app
from app.config import Settings
from app.services.wechat_monitor import MonitorError
from tests.test_api import LocalModelStub
from tests.test_wechat_api import seed_wechat


def make_app(folder):
    app=create_app(Settings(),db_path=folder/'db.sqlite3',config_path=folder/'config.json',llm=LocalModelStub())
    original=app.router.lifespan_context
    @asynccontextmanager
    async def isolated(application):
        async with original(application):
            seed_wechat(application.state.db,['请核对材料 <img src=x onerror=alert(1)>','bad','闲聊']+['测试通知 '+str(i) for i in range(22)])
            async def start(monitor):
                if not monitor.config.alias_hash:raise MonitorError('not_configured')
                monitor.state='listening'
                return monitor.status()
            async def stop(monitor):
                monitor.state='paused'
                return monitor.status()
            application.state.wechat.start=MethodType(start,application.state.wechat)
            application.state.wechat.stop=MethodType(stop,application.state.wechat)
            yield
    app.router.lifespan_context=isolated
    return app
