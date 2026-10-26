"""Local NapCat discovery, diagnostics and managed reporting setup. Never returns credentials."""
from dataclasses import dataclass
from pathlib import Path
import asyncio
import hashlib
import hmac
import json
import time
import httpx

@dataclass(frozen=True)
class Installation:
    boot: Path
    config: Path
    managed: bool = False

def find_installation(root):
    candidates = {}
    for webui in (Path(root)/'NapCat').glob('**/config/webui.json'):
        parents = list(webui.parents)
        possible = [p for p in parents if (p/'NapCatWinBootMain.exe').is_file() and (Path(root)/'NapCat').resolve() in p.resolve().parents]
        if not possible: continue
        folder = next((p for p in possible if (p/'QQ.exe').is_file()), possible[0])
        candidates[folder] = Installation(folder/'NapCatWinBootMain.exe', webui.parent)
    if len(candidates) > 1:
        raise ValueError('检测到多个 NapCat 安装，请保留一个使用目录。')
    if candidates:
        return next(iter(candidates.values()))
    from app.services.napcat_bundle import bundled_folder
    folder = bundled_folder(root)
    if all((folder/name).is_file() for name in ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'napcat.mjs', 'loadNapCat.js', 'qqnt.json')):
        return Installation(folder/'NapCatWinBootMain.exe', Path(root)/'NapCat'/'managed'/'config', True)
    return None

HINTS = {
 'not_installed': ('未找到 NapCat', '安装到项目 NapCat 文件夹后重新检查。'),
 'not_running': ('NapCat 未运行或管理页不可达', '点击“登录 QQ”启动；失败时运行 napcat.bat 并检查管理页端口。'),
 'config_error': ('NapCat 配置无法读取', '检查安装目录和 webui.json；管理页仅支持本机 HTTP 端口。'),
 'auth_failed': ('管理页认证失败', '在管理页检查 Token 或双重验证后重新检查。'),
 'qq_offline': ('QQ 未登录或已离线', '点击“登录 QQ”选择登录方式。'),
 'account_mismatch': ('登录账号已变化', '点击“检查连接”重新识别账号并配置上报。'),
 'report_disabled': ('HTTP 上报未启用', '点击“检查连接”自动配置上报。'),
 'report_mismatch': ('HTTP 上报配置未确认', '点击“检查连接”重试自动配置；仍失败时打开管理页检查权限或接口兼容性。'),
 'ready': ('QQ 在线，上报配置匹配', '等待群消息'),
}

def result(state, url=None):
    label, hint = HINTS[state]
    return {'state': state, 'label': label, 'hint': hint, 'webui_url': url}

class BridgeMonitor:
    def __init__(self, root, transport=None):
        self.root, self.transport = Path(root), transport
        self.credential, self.auth_key, self.auth_at = None, None, 0
        self.cache, self.cache_key, self.checked_at = None, None, 0
        self.lock = asyncio.Lock()

    async def inspect(self, account, token, callback='http://127.0.0.1:8000/api/qq/events', *, configure=False):
        async with self.lock:
            key = (account, token, callback, configure)
            if not configure and self.cache_key == key and time.monotonic()-self.checked_at < 10:
                return self.cache
            status = await self._inspect(account, token, callback, configure)
            self.cache, self.cache_key, self.checked_at = status, key, time.monotonic()
            return status

    async def _inspect(self, account, token, callback, configure=False):
        try:
            install = find_installation(self.root)
            if install is None: return result('not_installed')
            config = json.loads((install.config/'webui.json').read_text(encoding='utf-8-sig'))
            port, secret = config.get('port',6099), config.get('token')
            if type(port) is not int or not 1 <= port <= 65535 or not isinstance(secret,str) or not secret:
                return result('config_error')
        except (OSError, ValueError, TypeError):
            return result('config_error')
        url = f'http://127.0.0.1:{port}'
        try:
            async with httpx.AsyncClient(base_url=url, trust_env=False, timeout=2, transport=self.transport, follow_redirects=False) as client:
                auth_key = (url, secret)
                if self.auth_key != auth_key or time.monotonic()-self.auth_at >= 1800:
                    response = await client.post('/api/auth/login',json={'hash':hashlib.sha256((secret+'.napcat').encode()).hexdigest()})
                    response.raise_for_status(); body=response.json()
                    data=body.get('data') or {}
                    if body.get('code') != 0 or data.get('require2FA') or not isinstance(data.get('Credential'), str):
                        return result('auth_failed',url)
                    self.credential, self.auth_key, self.auth_at = data['Credential'], auth_key, time.monotonic()
                headers={'Authorization':'Bearer '+self.credential}
                async def read(path):
                    response=await client.post('/api/'+path,headers=headers)
                    response.raise_for_status(); body=response.json()
                    if body.get('code')!=0:
                        self.auth_at=0
                        raise PermissionError()
                    return body.get('data')
                status=await read('QQLogin/CheckLoginStatus')
                if not isinstance(status,dict): return result('config_error',url)
                if not status.get('isLogin'): return result('qq_offline',url)
                info=await read('QQLogin/GetQQLoginInfo')
                if str(info.get('uin',''))!=account: return result('account_mismatch',url)
                async def read_config():
                    config = await read('OB11Config/GetConfig')
                    if isinstance(config, str): config = json.loads(config)
                    network = config.get('network', {})
                    clients = network.get('httpClients', [])
                    if not isinstance(network, dict) or not isinstance(clients, list) or any(not isinstance(x, dict) for x in clients):
                        raise ValueError('Invalid reporting configuration')
                    return config, clients

                async def same_account():
                    status = await read('QQLogin/CheckLoginStatus')
                    if not isinstance(status, dict) or status.get('isLogin') is not True:
                        return False
                    info = await read('QQLogin/GetQQLoginInfo')
                    return isinstance(info, dict) and str(info.get('uin', '')) == account

                config, clients = await read_config()
                if configure and token:
                    # Only our named client or clients pointing to this application's
                    # exact callback belong to us. Preserve all other transports.
                    owned = [x for x in clients if x.get('name') == 'Shixu' or x.get('url') == callback]
                    desired = {'name': 'Shixu', 'enable': True, 'url': callback,
                               'messagePostFormat': 'array', 'token': token,
                               'reportSelfMessage': False, 'debug': False}
                    if owned: desired = {**owned[0], **desired}
                    if owned != [desired]:
                        if not await same_account(): return result('account_mismatch', url)
                        clients = [x for x in clients if x not in owned] + [desired]
                        config.setdefault('network', {})['httpClients'] = clients
                        response = await client.post('/api/OB11Config/SetConfig', headers=headers,
                            json={'config': json.dumps(config)})
                        response.raise_for_status()
                        if response.json().get('code') != 0:
                            return result('report_mismatch', url)
                        # A successful acknowledgement alone does not prove that
                        # this account's settings were saved and applied.
                        config, clients = await read_config()
                    if not await same_account(): return result('account_mismatch', url)

                targets=[x for x in clients if isinstance(x,dict) and x.get('url')==callback]
                if not targets: return result('report_mismatch',url)
                enabled=[x for x in targets if x.get('enable') is True]
                if not enabled: return result('report_disabled',url)
                if not any(x.get('messagePostFormat')=='array' and isinstance(x.get('token'),str) and token and hmac.compare_digest(x['token'].encode(),token.encode()) for x in enabled):
                    return result('report_mismatch',url)
                return result('ready',url)
        except PermissionError:
            return result('auth_failed',url)
        except httpx.HTTPError:
            return result('not_running',url)
        except (ValueError, TypeError, AttributeError, KeyError):
            return result('config_error',url)

async def inspect_bridge(root, account, token, transport=None):
    return await BridgeMonitor(root,transport).inspect(account,token)
