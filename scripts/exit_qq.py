"""Explicit bridge exit for installed versions whose login UI hides the action."""
import argparse
import asyncio
from pathlib import Path
import sys


def backend_stopped(root):
    import httpx
    from app.services.desktop import server_state
    with httpx.Client(trust_env=False, timeout=3) as client:
        return server_state(root, 'http://127.0.0.1:8000', client) == 'stopped'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if Path(sys.executable).resolve() != (root/'python/python.exe').resolve() or not (root/'app/services/qq_login.py').is_file():
        print('未确认拾序安装目录，未执行退出。')
        return 1
    sys.path.insert(0, str(root))
    try:
        if not backend_stopped(root):
            print('请先从托盘完整退出拾序，再运行此工具。未执行退出。')
            return 1
    except Exception:
        print('无法确认拾序后台已停止，未执行退出。')
        return 1
    print('仅退出此安装目录的 NapCat，并暂停 QQ 消息接收。')
    print('保留待办、历史、配置及普通桌面 QQ；不删除文件，不启动 QQ。')
    if input('确认请键入 EXIT，其他输入取消：').strip() != 'EXIT':
        print('已取消。')
        return 0
    try:
        from app.services.bridge import BridgeMonitor
        from app.services.qq_login import QQLogin
        result = asyncio.run(QQLogin(BridgeMonitor(root)).logout())
        if result.get('state') != 'exited':
            raise RuntimeError()
    except Exception:
        print('退出未确认。请保留现场并运行 DiagnoseQQ.cmd，勿手动删除文件或强制结束 QQ。')
        return 1
    print('已确认 NapCat 退出。请再从托盘退出拾序，然后重新卸载或安装。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
