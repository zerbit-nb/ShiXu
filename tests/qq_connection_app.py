"""Disposable browser fixture: real app routes, simulated local NapCat only."""
from contextlib import asynccontextmanager
import copy
import httpx
from fastapi import Request
from app.main import create_app
from app.routers.qq import QQConfig
from tests.test_bridge import install
from tests.test_qq import TOKEN
from tests.test_qq_connection import NapCat


def make_app(root):
    install(root)
    app = create_app(db_path=root/'db', config_path=root/'config')
    napcat = NapCat()
    template = copy.deepcopy(napcat.config)
    configs = {napcat.account: napcat.config}
    lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fixture(application):
        async with lifespan(application):
            application.state.bridge.transport = httpx.MockTransport(napcat.handle)
            application.state.qq.save(QQConfig(enabled=True, account_id='12345678',
                                               group_ids=['87654321'], token=TOKEN))
            yield
    app.router.lifespan_context = fixture

    @app.post('/test/napcat')
    async def control(request: Request):
        data = await request.json()
        if 'account' in data:
            configs[napcat.account] = napcat.config
            napcat.account = data['account']
            napcat.config = configs.setdefault(napcat.account, copy.deepcopy(template))
        napcat.reject = data.get('reject', False)
        return {'ok': True}

    @app.get('/test/reporting')
    async def reporting():
        clients = napcat.config['network']['httpClients']
        return {'writes': napcat.writes, 'other_client_preserved': clients[0] == template['network']['httpClients'][0],
                'ours': [{'url': row.get('url'), 'enable': row.get('enable'),
                          'format': row.get('messagePostFormat'),
                          'token_matches': row.get('token') == app.state.qq.token}
                         for row in clients if row.get('name') == 'Shixu']}
    return app
