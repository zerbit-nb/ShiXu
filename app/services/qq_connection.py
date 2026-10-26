"""Same-origin connection repair, serialized with login and logout actions."""
import re
import secrets
from app.routers.qq import QQConfig
from app.services.bridge import result
from app.services.qq_login import LoginError


async def synchronize(login, receiver, callback):
    async with login.action_lock, login.launch_lock:
        if login.policy.paused:
            paused = login.paused_status()
            return {'state': paused['state'], 'label': 'QQ 接收已暂停',
                    'hint': paused['message'], 'webui_url': None}
        disabled = {'state': 'disabled', 'label': 'QQ 接收已停用',
                    'hint': '接收已停用；登录后可自动识别账号。', 'webui_url': None}
        try:
            status = await login.status(receiver.account_id)
        except LoginError:
            if not receiver.enabled: return disabled
            raise
        if not status.get('online'):
            if not receiver.enabled: return disabled
            return result('qq_offline', status.get('webui_url'))
        account = status.get('account_id', '')
        if not re.fullmatch(r'[1-9][0-9]{4,19}', account):
            raise LoginError('config_error', 'QQ 在线，但未取得有效账号。请稍后点击“检查连接”重试。')
        changed = account != receiver.account_id
        if changed or not receiver.token:
            try:
                receiver.save(QQConfig(enabled=receiver.enabled, account_id=account,
                                       group_ids=receiver.group_ids,
                                       token=receiver.token or secrets.token_urlsafe(32)))
            except (OSError, ValueError, RuntimeError):
                raise LoginError('sync_failed', '接收账号未能保存，请检查数据目录权限后重试。') from None
            if changed:
                receiver.last_event_at = None
        # Do not re-enable a receiver the user explicitly disabled, even after login.
        if not receiver.enabled:
            return {'state': 'disabled', 'label': 'QQ 接收已停用',
                    'hint': '账号已识别；选择接收群并启用后，将自动配置上报。',
                    'webui_url': status.get('webui_url'), 'receiver': receiver.public()}
        status = await login.bridge.inspect(account, receiver.token, callback, configure=True)
        return {**status, 'receiver': receiver.public()}
