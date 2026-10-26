"""One entry point for CampusFlow and the installed NapCat bridge."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import subprocess
import time
import webbrowser
import httpx

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from app.services.bridge import BridgeMonitor, find_installation
from app.services.desktop import server_state, boot_is_running, start_hidden, startup_lock
from app.secrets import unprotect
from app.services.napcat_session import SessionPolicy
from app.services.napcat_bundle import initialize, launch

def main():
    parser=argparse.ArgumentParser(description='Start CampusFlow and NapCat together.')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--check-only',action='store_true',help='Inspect without starting processes or opening pages.')
    args=parser.parse_args()
    if os.name!='nt': raise RuntimeError('统一启动目前支持 Windows。')
    runtime=ROOT/'runtime';url='http://127.0.0.1:8000'
    with startup_lock(runtime),httpx.Client(trust_env=False,timeout=2) as client:
        state=server_state(ROOT,url,client)
        if args.check_only:
            print('CampusFlow: '+state)
        elif state=='stopped':
            process=start_hidden([sys.executable,str(ROOT/'scripts/launch.py'),'--no-browser'],ROOT,runtime/'campusflow.log')
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                state=server_state(ROOT,url,client)
                if state=='ready': break
                if process.poll() is not None: break
                time.sleep(.25)
            if state!='ready': raise RuntimeError('CampusFlow 启动失败，请检查 runtime/campusflow.log；端口占用时先关闭冲突服务。')
            print('CampusFlow 已启动。')
        elif state=='ready': print('CampusFlow 已运行，复用现有服务。')
        elif state=='upgrade': raise RuntimeError('检测到旧版 CampusFlow，请先关闭旧服务，再双击此启动入口。')
        else: raise RuntimeError('8000 端口被其他程序或另一份 CampusFlow 占用，请先检查该程序。')
        try:
            if SessionPolicy(ROOT).paused:
                print('NapCat 已退出或退出尚未确认，不会自动启动。请在网页中主动登录或重试退出。')
                if not args.no_browser and not args.check_only: webbrowser.open(url)
                return
            install=find_installation(ROOT)
            if install is None:
                print('未找到 NapCat；CampusFlow 手动导入仍可使用。请按 docs/qq-setup.md 安装。')
            else:
                if not args.check_only: initialize(install)
                webui=json.loads((install.config/'webui.json').read_text(encoding='utf-8-sig'))
                port=webui.get('port',6099)
                if type(port) is not int or not 1<=port<=65535: raise RuntimeError('NapCat 管理页端口配置不正确。')
                management=f'http://127.0.0.1:{port}'
                try: alive=client.get(management).status_code==200
                except httpx.HTTPError: alive=False
                running=boot_is_running(install.boot)
                if not alive and not running and not args.check_only:
                    if install.managed: launch(install)
                    else: start_hidden([str(install.boot)],install.boot.parent,runtime/'napcat.log')
                    deadline=time.monotonic()+20
                    while time.monotonic()<deadline:
                        try:
                            if client.get(management).status_code==200: alive=True;break
                        except httpx.HTTPError: pass
                        time.sleep(.5)
                    print('NapCat 启动请求已发出。' if alive else 'NapCat 尚未就绪，请稍后检查 QQ 收件箱；也可手动运行 napcat.bat。')
                else: print('NapCat: '+('已运行，复用现有登录。' if alive or running else '未运行。'))
                config_file=ROOT/'qq.local.json'
                qq=json.loads(config_file.read_text(encoding='utf-8')) if config_file.exists() else {}
                status=asyncio.run(BridgeMonitor(ROOT).inspect(qq.get('account_id',''),unprotect(qq.get('encrypted_token',''))))
                print(status['label']+'。'+status['hint'])
                if not args.no_browser and not args.check_only and status['state'] == 'auth_failed':
                    webbrowser.open(management)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError, subprocess.SubprocessError):
            print("QQ 启动检查失败，请在 QQ 收件箱查看诊断并检查 NapCat 配置；CampusFlow 仍可使用。")
        if not args.no_browser and not args.check_only: webbrowser.open(url)
        if not args.check_only: print('启动完成。关闭本启动窗口不会停止服务。查看 QQ 收件箱中的连接诊断；日志位于 runtime。')

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print(str(exc) if isinstance(exc,RuntimeError) else '启动检查失败，请检查 NapCat 配置及 runtime 日志。')
        sys.exit(1)
