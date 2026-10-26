"""Local-only NapCat login facade. Never persists login passwords or QR material."""
import asyncio
import base64
import hashlib
import io
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
import qrcode
from qrcode.image.pure import PyPNGImage
from app.services.bridge import find_installation
from app.services.napcat_bundle import initialize, launch, record_start, startup_failed, startup_hint, START_HINT
from app.services.napcat_session import SessionPolicy, stop_napcat
from app.services.desktop import boot_is_running, startup_lock
from app.services.qq_verification import LoginError, DeviceVerification

logger = logging.getLogger(__name__)

class QQLogin:
    def __init__(self, bridge):
        self.bridge = bridge
        self.launch_lock = asyncio.Lock()
        self.action_lock = asyncio.Lock()
        self.last_password = 0
        self.start_error = None
        self.policy = SessionPolicy(bridge.root)
        self.device = DeviceVerification(self)

    def installation(self):
        try:
            install = find_installation(self.bridge.root)
            if not install:
                raise LoginError('not_installed', '未找到 NapCat，请先安装到项目的 NapCat 文件夹。')
            initialize(install)
            config = json.loads((install.config/'webui.json').read_text(encoding='utf-8-sig'))
            port, secret = config.get('port', 6099), config.get('token')
            if type(port) is not int or not 1 <= port <= 65535 or not isinstance(secret, str) or not secret:
                raise ValueError()
            return install, f'http://127.0.0.1:{port}', secret
        except (OSError, ValueError, TypeError):
            raise LoginError('config_error', 'NapCat 安装或管理页配置无法读取。') from None

    @staticmethod
    def rejection_message(message):
        # Match only known categories; never return upstream text.
        text = message.lower()[:4096] if isinstance(message, str) else ''
        categories = [
            (('新设备', '异常设备'), 'QQ 要求新设备验证，但 NapCat 未返回可继续使用的验证信息。请在管理页检查本次登录验证。'),
            (('验证码', '安全验证', 'captcha'), 'QQ 要求安全验证，但 NapCat 未返回可继续使用的验证信息。请在管理页处理验证。'),
            (('密码错误', '密码不正确', '账号或密码错误', 'incorrect password'), 'NapCat 返回账号或密码错误，请核对 QQ 号和密码。'),
            (('频繁', 'too many', 'rate limit'), 'QQ 提示登录尝试过于频繁，请稍后再试，避免连续提交。'),
            (('冻结', '封禁', '账号限制'), 'QQ 返回账号限制，请在官方 QQ 中检查账号状态。'),
            (('uin is empty', 'passwordmd5 is empty'), 'NapCat 拒绝登录参数，请检查接口兼容性；这不代表用户密码错误。'),
            (('qq is logined',), 'NapCat 内部认为 QQ 已登录，但完整在线状态尚未确认，请等待初始化或在管理页检查状态。'),
        ]
        for words, description in categories:
            if any(word in text for word in words):
                return description
        return 'NapCat 拒绝了登录请求，返回内容未提供可识别的具体原因。不能据此认定密码错误，请在管理页检查本次登录。'

    async def call(self, route, payload=None):
        allowed = {'CheckLoginStatus', 'GetQQLoginInfo', 'GetQQLoginQrcode', 'RefreshQRcode', 'PasswordLogin', 'GetNewDeviceQRCode', 'PollNewDeviceQR', 'NewDeviceLogin', 'GetQuickLoginList', 'GetQuickLoginListNew', 'SetQuickLogin'}
        if route not in allowed:
            raise ValueError('Unsupported login route')
        install, url, secret = self.installation()
        async with self.bridge.lock:
            try:
                async with httpx.AsyncClient(base_url=url, timeout=15, trust_env=False,
                                             transport=self.bridge.transport, follow_redirects=False) as client:
                    key = (url, secret)
                    if self.bridge.auth_key != key or time.monotonic()-self.bridge.auth_at >= 1800:
                        response = await client.post('/api/auth/login', json={'hash': hashlib.sha256((secret+'.napcat').encode()).hexdigest()})
                        response.raise_for_status()
                        body = response.json()
                        data = body.get('data') or {}
                        if body.get('code') != 0 or data.get('require2FA') or not isinstance(data.get('Credential'), str):
                            raise LoginError('auth_failed', '管理页认证失败或需要双重验证，请打开 NapCat 管理页处理。', url)
                        self.bridge.credential = data['Credential']
                        self.bridge.auth_key, self.bridge.auth_at = key, time.monotonic()
                    # Native passwordLogin can wait for the user's phone authorization.
                    response = await client.post('/api/QQLogin/'+route, json=payload or {},
                                                 headers={'Authorization': 'Bearer '+self.bridge.credential},
                                                 timeout=httpx.Timeout(15, read=300) if route in {'PasswordLogin','NewDeviceLogin','SetQuickLogin'} else 15)
                    if response.status_code in {401, 403}:
                        self.bridge.auth_at = 0
                        raise LoginError('auth_failed', '管理页认证已失效，请重试或打开 NapCat 管理页。', url)
                    response.raise_for_status()
                    body = response.json()
                    if body.get('code') != 0:
                        # Upstream messages may contain credentials or verification URLs.
                        raise LoginError('login_error', self.rejection_message(body.get('message')), url)
                    self.start_error = None
                    return body.get('data'), url
            except httpx.ReadTimeout:
                if route in {'PasswordLogin', 'NewDeviceLogin', 'SetQuickLogin'}:
                    raise LoginError('password_timeout', '等待 NapCat 返回密码登录结果已超时。手机确认不等于 QQ 已在线，请检查 NapCat 管理页后重新登录。', url) from None
                raise LoginError('not_running', 'NapCat 状态查询超时，请稍后重试。', url) from None
            except httpx.HTTPError:
                if self.start_error is not None:
                    raise self.start_error from None
                if install.managed and startup_failed(install):
                    raise LoginError('start_failed', startup_hint(install), url) from None
                raise LoginError('not_running', 'NapCat 尚未就绪或连接超时，请稍后重试启动。', url) from None
            except (ValueError, TypeError, AttributeError, KeyError):
                raise LoginError('config_error', 'NapCat 登录接口返回格式异常，请检查版本。', url) from None

    async def management_alive(self, url):
        async with httpx.AsyncClient(timeout=2, trust_env=False, transport=self.bridge.transport) as client:
            try:
                await client.get(url+'/')
                return True
            except (httpx.ConnectError, httpx.ConnectTimeout):
                return False
            except httpx.HTTPError:
                return True

    def clear_cache(self):
        self.device.clear()
        self.bridge.credential = self.bridge.auth_key = self.bridge.cache = self.bridge.cache_key = None
        self.bridge.auth_at = self.bridge.checked_at = 0
        self.last_password = 0
        self.start_error = None

    def paused_status(self):
        state = self.policy.read()['state']
        message = {'exited': '已退出 NapCat，群消息接收已暂停。点击“启动并登录”可重新连接。',
                   'exiting': '正在退出 NapCat，群消息接收已暂停。',
                   'exit_failed': '无法确认 NapCat 已停止，QQ 可能仍在线。消息接收已暂停，请重试退出。'}[state]
        return {'state': state, 'online': False if state == 'exited' else None,
                'account_id': '', 'account_mismatch': False, 'qr_image': None, 'webui_url': None, 'message': message}

    async def logout(self):
        async with self.action_lock, self.launch_lock:
            self.device.clear()
            install, url, _ = self.installation()
            try:
                with startup_lock(self.bridge.root/'runtime'):
                    self.policy.write('exiting')
                    async with self.bridge.lock:
                        await asyncio.to_thread(stop_napcat, install.boot)
                        if await self.management_alive(url):
                            raise RuntimeError('Management endpoint remains reachable')
                        self.policy.write('exited')
                        self.clear_cache()
                return self.paused_status()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                try:
                    if self.policy.paused: self.policy.write('exit_failed')
                except OSError:
                    pass
                raise LoginError('exit_failed', '退出未完成，无法确认 NapCat 已停止。请重试退出；消息接收状态请查看本面板。') from None

    async def start(self):
        async with self.launch_lock:
            self.start_error = None
            install, url, _ = self.installation()
            process = None
            try:
                with startup_lock(self.bridge.root/'runtime'):
                    if await self.management_alive(url):
                        if self.policy.paused:
                            raise LoginError('exit_failed', 'NapCat 仍在运行，请先重试退出，再启动新连接。')
                        return {'state': 'running', 'message': 'NapCat 已运行，复用现有登录。'}
                    if not await asyncio.to_thread(boot_is_running, install.boot):
                        if install.managed:
                            try:
                                process = await asyncio.to_thread(launch, install)
                            except ValueError as exc:
                                self.start_error = LoginError('start_failed', startup_hint(install) if startup_failed(install) else str(exc), url)
                                raise self.start_error from None
                        else:
                            subprocess.Popen([str(install.boot)], cwd=install.boot.parent, stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
                    for _ in range(30):
                        if await self.management_alive(url):
                            if install.managed:
                                record_start(install, 'ready')
                            if self.policy.paused:
                                self.policy.resume()
                                self.clear_cache()
                            return {'state': 'running', 'message': 'NapCat 后台已启动。'}
                        if install.managed and process is not None and process.poll() not in {None, 0}:
                            record_start(install, 'launcher_exited', process.returncode)
                            raise LoginError('start_failed', START_HINT, url)
                        await asyncio.sleep(.5)
            except RuntimeError:
                if install.managed and startup_failed(install):
                    self.start_error = LoginError('start_failed', startup_hint(install), url)
                    raise self.start_error from None
                return {'state': 'starting', 'message': '启动器正在运行，请稍后重新检查。'}
            except (OSError, TypeError, AttributeError, subprocess.SubprocessError):
                if install.managed and startup_failed(install):
                    self.start_error = LoginError('start_failed', startup_hint(install), url)
                    raise self.start_error from None
                raise LoginError('start_failed', '后台启动失败，请检查 NapCat 安装或手动运行 napcat.bat。', url) from None
            if install.managed:
                record_start(install, 'timeout')
                raise LoginError('start_failed', START_HINT, url)
            return {'state': 'starting', 'message': '启动请求已发出，NapCat 正在准备，请稍后重新检查。'}

    @staticmethod
    def qr_image(value):
        if not isinstance(value, str) or len(value) > 2048:
            return None
        parsed = urlparse(value)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not (host == 'qq.com' or host.endswith('.qq.com')) or parsed.username or parsed.password:
            return None
        stream = io.BytesIO()
        qr = qrcode.QRCode(box_size=6, border=4)
        qr.add_data(value)
        qr.make(fit=True)
        qr.make_image(image_factory=PyPNGImage).save(stream)
        return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()

    async def status(self, expected_account):
        if self.policy.paused:
            return self.paused_status()
        data, url = await self.call('CheckLoginStatus')
        if not isinstance(data, dict):
            raise LoginError('config_error', 'NapCat 登录状态格式异常。', url)
        online = data.get('isLogin') is True
        phase = data.get('loginPhase')
        if phase not in {'waiting_qrcode', 'generating_qrcode', 'qrcode_scanned', 'initializing', 'reconnecting'}:
            phase = 'waiting_qrcode'
        account = ''
        if online:
            info, _ = await self.call('GetQQLoginInfo')
            account = str(info.get('uin', '')) if isinstance(info, dict) else ''
            if not re.fullmatch(r'[1-9][0-9]{4,19}', account):
                account = ''
        state = 'online' if online else ('login_error' if data.get('loginError') else phase)
        if self.policy.paused:
            return self.paused_status()
        if online:
            self.device.clear()
        elif state == 'login_error' and not self.device.pending and not (self.device.terminal or {}).get('failure_stage'):
            self.device.clear()
        elif self.device.view() and state not in {'initializing', 'reconnecting'}:
            return {**self.device.view(), 'webui_url': url}
        return {'state': state, 'online': online, 'account_id': account,
                'account_mismatch': bool(online and expected_account and account != expected_account),
                'qr_image': None if online or state != 'waiting_qrcode' else self.qr_image(data.get('qrcodeurl')),
                'webui_url': url}

    async def refresh(self, expected_account):
        async with self.action_lock:
            if self.policy.paused:
                raise LoginError('exited', '请先点击“启动并登录”，再刷新二维码。')
            self.device.clear()
            status = await self.status(expected_account)
            if status['online']:
                return status
            await self.call('RefreshQRcode')
            return await self.status(expected_account)

    async def password(self, account, password):
        async with self.action_lock:
            if self.policy.paused:
                raise LoginError('exited', '请先点击“启动并登录”，再提交登录。')
            now = time.monotonic()
            if now-self.last_password < 5:
                raise LoginError('rate_limited', '请等待 5 秒后再提交登录。')
            self.last_password = now
            self.device.clear()
            status = await self.status(account)
            if status['online']:
                return status
            digest = hashlib.md5(password.encode('utf-8')).hexdigest()
            stage, began = 'password_submit', time.monotonic()
            try:
                data, url = await self.call('PasswordLogin', {'uin': account, 'passwordMd5': digest})
                self.bridge.checked_at = 0
                if isinstance(data, dict) and data.get('needNewDevice'):
                    stage = 'device_qr'
                    return await self.device.begin(account, digest, data)
                if isinstance(data, dict) and data.get('needCaptcha'):
                    self.device.clear('verification_required')
                    self.device.terminal.update(message='QQ 要求安全验证，请在 NapCat 管理页重新发起登录并完成验证，或改用扫码登录。', webui_url=url)
                    return self.device.view()
                self.device.clear('submitted')
                self.device.terminal.update(message='登录请求已提交，正在等待 QQ 确认。', webui_url=url)
                return self.device.view()
            except LoginError as error:
                error.failure_stage = stage
                self.device.clear(error.state)
                self.device.terminal.update(message=error.message, webui_url=error.url, failure_stage=stage)
                # Only allowlisted state/stage and duration. Never upstream messages or login material.
                logger.warning('QQ password attempt failed stage=%s state=%s elapsed_seconds=%.1f', stage, error.state, time.monotonic()-began)
                raise
            finally:
                password = digest = ''



    async def poll_verification(self, ident):
        async with self.action_lock:
            if self.policy.paused:
                self.device.clear()
                return self.paused_status()
            return await self.device.poll(ident)

    async def cancel_verification(self, ident):
        async with self.action_lock:
            return self.device.cancel(ident)


    async def quick_accounts(self):
        if self.policy.paused:
            return {**self.paused_status(), 'accounts': []}
        rows, url = await self.call('GetQuickLoginList')
        if not isinstance(rows, list) or len(rows) > 100:
            raise LoginError('config_error', 'NapCat 快速登录列表格式异常。', url)
        accounts = {}
        for row in rows:
            value = row.get('uin') if isinstance(row, dict) else row
            if type(value) not in {str, int}:
                continue
            account = str(value)
            if re.fullmatch(r'[1-9][0-9]{4,19}', account):
                accounts.setdefault(account, {'account_id': account, 'nickname': ''})
        try:
            details, _ = await self.call('GetQuickLoginListNew')
            if isinstance(details, list):
                for row in details[:100]:
                    if not isinstance(row, dict): continue
                    account = str(row.get('uin', ''))
                    nickname = row.get('nickName')
                    if account in accounts and isinstance(nickname, str):
                        accounts[account]['nickname'] = ''.join(c for c in nickname[:80] if c.isprintable())
        except LoginError:
            # Older NapCat builds may only provide the numeric list.
            pass
        if self.policy.paused:
            return {**self.paused_status(), 'accounts': []}
        return {'state': 'quick_accounts', 'accounts': list(accounts.values()), 'webui_url': url}

    async def quick_login(self, account):
        async with self.action_lock:
            if self.policy.paused:
                raise LoginError('exited', '请先点击“启动并登录”，再使用快速登录。')
            listing = await self.quick_accounts()
            if account not in {row['account_id'] for row in listing['accounts']}:
                raise LoginError('quick_unavailable', '这个账号已不在快速登录列表中，请刷新或选择其他登录方式。')
            self.device.clear()
            status = await self.status(account)
            if status.get('online'):
                return status
            try:
                await self.call('SetQuickLogin', {'uin': account})
                self.bridge.checked_at = 0
                self.device.clear('submitted')
                self.device.terminal.update(message='快速登录请求已提交，正在等待 QQ 初始化。', online=False)
                return self.device.view()
            except LoginError as error:
                error.failure_stage = 'quick_login'
                self.device.clear(error.state)
                self.device.terminal.update(message=error.message, failure_stage='quick_login', webui_url=error.url)
                raise
