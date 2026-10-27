"""Actual WebView2 hide/restore validation with synthetic data and a model stub."""
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import traceback
import httpx
import uvicorn
import webview
from app.config import Settings
from app.main import create_app
from scripts.desktop_window import WindowVisibilityBridge
from scripts.desktop_tray import WindowsTray,TrayController
from tests.test_auto_organize import Model


def main():
    with socket.socket() as guard:guard.bind(('127.0.0.1',8788))
    with tempfile.TemporaryDirectory(prefix='shixu-automation-') as folder:
        root=Path(folder)
        app=create_app(Settings(llm_model='test-native'),db_path=root/'db',config_path=root/'config',llm=Model())
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8788,log_level='error'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        window=webview.create_window('拾序 · 自动整理隔离验证','http://127.0.0.1:8788/?desktop=1#connections',width=1280,height=860,hidden=True)
        stopped=threading.Event();bridge=WindowVisibilityBridge(window,stopped)
        tray=WindowsTray(window);controller=TrayController(window,tray,lambda:None)
        window.events.before_show+=bridge.attach
        window.events.before_show+=lambda:tray.install(controller)
        window.events.loaded+=bridge.page_loaded
        outcome={'passed':False}
        def wait_js(expression):
            for _ in range(100):
                try:
                    if window.evaluate_js(expression):return
                except Exception:pass
                time.sleep(.1)
            raise AssertionError('WebView2 timed out: '+expression)
        def probe():
            try:
                wait_js("!!document.querySelector('#automationToggle') && !document.querySelector('#automationToggle').disabled")
                with httpx.Client(base_url='http://127.0.0.1:8788',trust_env=False) as client:
                    assert client.put('/api/automation',json={'enabled':True,'allow_local':True},headers={'Origin':'http://127.0.0.1:8788'}).status_code==200
                    window.evaluate_js("document.querySelector('#automationToggle').disabled=true")
                    # Synthetic input, through the real signed QQ receiver.
                    from tests.test_qq import event,TOKEN
                    import hashlib,hmac
                    assert client.put('/api/qq/config',json={'enabled':True,'account_id':'12345678','group_ids':['87654321'],'token':TOKEN}).status_code==200
                    payload=event(message=[{'type':'text','data':{'text':'通知：请于2026年12月30日20:00前提交实验报告。'}}])
                    raw=json.dumps(payload,ensure_ascii=False).encode()
                    assert client.post('/api/qq/events',content=raw,headers={'X-Signature':'sha1='+hmac.new(TOKEN.encode(),raw,hashlib.sha1).hexdigest()}).status_code==204
                    for _ in range(100):
                        if client.get('/api/automation/notices').json()['notices']:break
                        time.sleep(.1)
                    assert client.get('/api/automation/notices').json()['notices']
                assert window.evaluate_js("document.querySelector('#automationCard').hidden && !automationNativeVisible")
                tray.restore()
                wait_js("automationNativeVisible && !document.querySelector('#automationCard').hidden")
                window.minimize()
                wait_js("!automationNativeVisible && document.querySelector('#automationCard').hidden")
                tray.restore()
                wait_js("automationNativeVisible && !document.querySelector('#automationCard').hidden")
                tray.dispatch(tray.hide)
                wait_js("!automationNativeVisible && document.querySelector('#automationCard').hidden")
                tray.restore()
                wait_js("automationNativeVisible && !document.querySelector('#automationCard').hidden")
                window.evaluate_js("document.querySelector('#automationCardDismiss').click()")
                wait_js("document.querySelector('#automationCard').hidden && automationNotices.length===0")
                outcome['passed']=True
            except Exception:outcome['error']=traceback.format_exc()
            finally:window.destroy()
        try:webview.start(probe,gui='edgechromium',debug=False,private_mode=True)
        finally:
            stopped.set()
            tray.dispose()
            if bridge.worker:bridge.worker.join(2)
            server.should_exit=True;thread.join(10)
        print(json.dumps(outcome,ensure_ascii=False))
        if not outcome['passed']:raise SystemExit(1)

if __name__=='__main__':main()
