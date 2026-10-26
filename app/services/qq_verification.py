"""Short-lived new-device verification, following installed NapCat WebUI APIs."""
import asyncio
import base64
from dataclasses import dataclass, field
import secrets
import time
from urllib.parse import urlparse, parse_qs

class LoginError(Exception):
    def __init__(self, state, message, url=None):
        self.state, self.message, self.url = state, message, url
        self.failure_stage = None

@dataclass(repr=False)
class PendingDevice:
    ident: str
    account: str
    digest: str = field(repr=False)
    signature: str = field(repr=False)
    token: str = field(repr=False)
    image: str = field(repr=False)
    expires_at: float
    state: str = 'device_verification'

class DeviceVerification:
    def __init__(self, login):
        self.login = login
        self.pending = None
        self.timer = None
        self.terminal = None
        self.ttl = 300

    def clear(self, state=None, ident=None):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.pending:
            self.pending.digest = self.pending.signature = self.pending.token = self.pending.image = ''
        self.pending = None
        self.terminal = {'state': state, 'verification_id': ident, 'online': False,
                         'qr_image': None} if state else None

    def expire(self, ident):
        if self.pending and self.pending.ident == ident:
            self.clear('verification_expired', ident)

    def view(self):
        pending = self.pending
        if pending and time.monotonic() >= pending.expires_at:
            self.expire(pending.ident)
            pending = None
        if pending:
            return {'state': pending.state, 'verification_id': pending.ident, 'online': False,
                    'account_id': '', 'qr_image': pending.image,
                    'message': '请用手机 QQ 扫描新设备验证二维码并确认；网页会继续完成登录。'}
        return self.terminal

    @staticmethod
    def safe_url(value):
        if not isinstance(value, str) or len(value) > 8192:
            return False
        try:
            parsed = urlparse(value)
            host = parsed.hostname or ''
            return parsed.scheme == 'https' and (host == 'qq.com' or host.endswith('.qq.com')) and not parsed.username and not parsed.password
        except ValueError:
            return False

    @staticmethod
    def valid_text(value):
        return isinstance(value, str) and 0 < len(value) <= 8192

    @staticmethod
    def valid_response(data):
        return isinstance(data, dict) and data.get('ActionStatus', 'OK') == 'OK' and data.get('ErrorCode', 0) == 0

    async def begin(self, account, digest, data):
        self.clear()
        jump, signature = data.get('jumpUrl'), data.get('newDevicePullQrCodeSig')
        if not self.safe_url(jump) or not self.valid_text(signature):
            raise LoginError('verification_error', '新设备验证信息不完整，请重新提交密码登录或改用扫码。')
        qr, _ = await self.login.call('GetNewDeviceQRCode', {'uin': account, 'jumpUrl': jump})
        if not self.valid_response(qr):
            raise LoginError('verification_error', '获取新设备验证二维码失败，请重新提交登录。')
        image = self.login.qr_image(qr.get('str_url'))
        token = qr.get('bytes_token')
        if not token and self.safe_url(qr.get('str_url')):
            nested = parse_qs(urlparse(qr['str_url']).query).get('str_url', [''])[0]
            # Same fallback as NapCat WebUI, without exposing the nested token URL.
            if nested:
                try: token = base64.b64encode(nested.encode('latin-1')).decode()
                except UnicodeEncodeError: token = None
        if not image or not self.valid_text(token):
            raise LoginError('verification_error', '验证二维码或确认令牌无效，请重新提交登录。')
        ident = secrets.token_hex(16)
        self.pending = PendingDevice(ident, account, digest, signature, token, image, time.monotonic()+self.ttl)
        self.timer = asyncio.get_running_loop().call_later(self.ttl, self.expire, ident)
        return self.view()

    def match(self, ident):
        view = self.view()
        if not view or view.get('verification_id') != ident:
            raise LoginError('verification_stale', '这次验证已结束或被新的登录替换，请重新打开登录面板。')
        return view

    async def poll(self, ident):
        view = self.match(ident)
        pending = self.pending
        if not pending:
            return view
        status = await self.login.status(pending.account)
        if status.get('online'):
            self.clear()
            return status
        if self.pending is not pending:
            return self.view() or {'state': 'verification_expired', 'qr_image': None}
        data, _ = await self.login.call('PollNewDeviceQR', {'uin': pending.account, 'bytesToken': pending.token})
        if self.pending is not pending:
            return self.view() or {'state': 'verification_expired', 'qr_image': None}
        if not self.valid_response(data):
            self.clear('verification_error', ident)
            raise LoginError('verification_error', '手机授权查询失败，请重新提交登录。')
        state = data.get('uint32_guarantee_status')
        if state != 1:
            pending.state = 'device_scanned' if state == 3 else 'device_verification'
            return self.view()
        success = data.get('str_nt_succ_token') or pending.signature
        if not self.valid_text(success):
            self.clear('verification_error', ident)
            raise LoginError('verification_error', '手机确认结果不完整，请重新登录。')
        # Consume before submission, so concurrent polls cannot submit twice.
        digest, account = pending.digest, pending.account
        self.clear('submitted', ident)
        try:
            result, url = await self.login.call('NewDeviceLogin', {
                'uin': account, 'passwordMd5': digest, 'newDevicePullQrCodeSig': success})
            if isinstance(result, dict) and result.get('needNewDevice'):
                return await self.begin(account, digest, result)
            if isinstance(result, dict) and result.get('needCaptcha'):
                self.clear('verification_required', ident)
                return {'state': 'verification_required', 'message': 'QQ 还需要滑块验证，请在 NapCat 管理页处理或改用扫码。', 'webui_url': url}
            self.login.bridge.checked_at = 0
            return {'state': 'submitted', 'online': False, 'verification_id': ident,
                    'qr_image': None, 'message': '手机已确认，验证结果已提交；正在等待 QQ 初始化。'}
        except LoginError:
            self.clear('verification_error', ident)
            raise
        finally:
            digest = success = ''
            pending.digest = pending.signature = pending.token = pending.image = ''

    def cancel(self, ident):
        self.match(ident)
        self.clear('verification_cancelled', ident)
        return {'state': 'verification_cancelled', 'online': False, 'qr_image': None,
                'message': '已取消验证，临时登录信息已清理。可以重新选择登录方式。'}
