"""Narrow local login endpoints, independent of message reception settings."""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, SecretStr
from app.services.qq_login import LoginError
from app.services.qq_connection import synchronize

router = APIRouter(prefix='/api/qq/login')

class PasswordLogin(BaseModel):
    account_id: str = Field(pattern=r'^[1-9][0-9]{4,19}$')
    password: SecretStr = Field(min_length=1, max_length=128)

async def respond(operation):
    try:
        return JSONResponse(await operation, headers={'Cache-Control': 'no-store'})
    except LoginError as exc:
        return JSONResponse({'state': exc.state, 'message': exc.message, 'webui_url': exc.url, 'failure_stage': exc.failure_stage},
                            status_code=503 if exc.state != 'rate_limited' else 429,
                            headers={'Cache-Control': 'no-store'})

def same_origin(request):
    # Browsers send Origin on these JSON POSTs. Require it even for loopback APIs.
    if request.headers.get('origin') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, '请从 CampusFlow 网页发起登录。')

@router.get('/status')
async def status(request: Request):
    return await respond(request.app.state.qq_login.status(request.app.state.qq.account_id))

@router.post('/sync')
async def sync(request: Request):
    same_origin(request)
    callback = 'http://127.0.0.1:' + str(request.url.port or 80) + '/api/qq/events'
    return await respond(synchronize(request.app.state.qq_login, request.app.state.qq, callback))

@router.post('/start')
async def start(request: Request):
    same_origin(request)
    return await respond(request.app.state.qq_login.start())

@router.post('/refresh')
async def refresh(request: Request):
    same_origin(request)
    return await respond(request.app.state.qq_login.refresh(request.app.state.qq.account_id))

@router.post('/password')
async def password(body: PasswordLogin, request: Request):
    same_origin(request)
    return await respond(request.app.state.qq_login.password(body.account_id, body.password.get_secret_value()))


@router.post('/logout')
async def logout(request: Request):
    same_origin(request)
    response = await respond(request.app.state.qq_login.logout())
    if response.status_code == 200:
        request.app.state.qq.last_event_at = None
    return response

class VerificationRequest(BaseModel):
    verification_id: str = Field(pattern=r'^[a-f0-9]{32}$')

@router.post('/verification/poll')
async def verification_poll(body: VerificationRequest, request: Request):
    same_origin(request)
    return await respond(request.app.state.qq_login.poll_verification(body.verification_id))

@router.post('/verification/cancel')
async def verification_cancel(body: VerificationRequest, request: Request):
    same_origin(request)
    return await respond(request.app.state.qq_login.cancel_verification(body.verification_id))


class QuickLoginRequest(BaseModel):
    account_id: str = Field(pattern=r'^[1-9][0-9]{4,19}$')

@router.get('/quick/accounts')
async def quick_accounts(request: Request):
    return await respond(request.app.state.qq_login.quick_accounts())

@router.post('/quick')
async def quick_login(body: QuickLoginRequest, request: Request):
    same_origin(request)
    return await respond(request.app.state.qq_login.quick_login(body.account_id))
