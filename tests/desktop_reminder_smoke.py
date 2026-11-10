"""Actual WebView2/tray delivery with disposable synthetic tasks and no accounts."""
from datetime import datetime, timedelta
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
from app.main import create_app
from scripts.desktop_window import WindowVisibilityBridge
from scripts.desktop_tray import WindowsTray, TrayController
from scripts.desktop_reminders import DesktopReminders


def main():
    port=8799;url=f'http://127.0.0.1:{port}'
    with socket.socket() as guard:guard.bind(('127.0.0.1',port))
    with tempfile.TemporaryDirectory(prefix='shixu-reminder-native-') as folder:
        root=Path(folder);app=create_app(db_path=root/'db',config_path=root/'config')
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error'))
        backend=threading.Thread(target=server.run,daemon=True);backend.start()
        window=webview.create_window('拾序 · 提醒隔离验证',url+'/?desktop=1#connections',width=1280,height=860,hidden=True)
        stopped=threading.Event();visibility=WindowVisibilityBridge(window,stopped)
        tray=WindowsTray(window);controller=TrayController(window,tray,lambda:None)
        native=DesktopReminders(window,tray,visibility,stopped,url);notifications=[]
        original=tray.notify_reminders
        def notify(count):
            result=original(count);notifications.append(count);return result
        tray.notify_reminders=notify
        window.events.before_show+=visibility.attach
        def attach():tray.install(controller);native.attach()
        window.events.before_show+=attach
        window.events.loaded+=visibility.page_loaded
        outcome={'passed':False}
        def wait(predicate):
            for _ in range(150):
                if predicate():return
                time.sleep(.1)
            raise AssertionError('Timed out')
        def probe():
            try:
                wait(lambda:visibility.loaded.is_set() and tray.ready)
                with httpx.Client(base_url=url,headers={'Origin':url},trust_env=False) as client:
                    deadline=(datetime.now().astimezone()+timedelta(minutes=30)).isoformat()
                    fields={'title':'提醒验证：核对测试清单','deadline':deadline}
                    draft=client.post('/api/messages/manual',json={'raw_text':'隔离测试，无需实际操作','fields':fields}).json()['drafts'][0]
                    response=client.post('/api/drafts/'+draft['id']+'/confirm',json={'confirmed':True,'fields':fields});response.raise_for_status()
                    config=client.get('/api/reminders').json();config.pop('error');config.update(enabled=True,daily_enabled=False)
                    response=client.put('/api/reminders',json=config);response.raise_for_status()
                    wait(lambda:len(notifications)==1)
                    assert window.evaluate_js("document.querySelector('#taskReminderCard').hidden")
                    native.open()  # Same handler as clicking the Windows notification.
                    wait(lambda:visibility.visible and window.evaluate_js("!document.querySelector('#taskReminderCard').hidden"))
                    assert notifications==[1]
                    window.evaluate_js("document.querySelector('#taskReminderDismiss').click()")
                    wait(lambda:not client.get('/api/reminders/events').json()['events'])
                    outcome.update(passed=True,native_api_called=1,foreground_reopened=True)
            except Exception:outcome['error']=traceback.format_exc()
            finally:stopped.set();window.destroy()
        try:webview.start(probe,gui='edgechromium',debug=False,private_mode=True)
        finally:
            stopped.set();native.join();tray.dispose()
            if visibility.worker:visibility.worker.join(2)
            server.should_exit=True;backend.join(10)
        outcome['reminder_thread_stopped']=not native.worker or not native.worker.is_alive()
        print(json.dumps(outcome,ensure_ascii=False))
        if not outcome['passed'] or not outcome['reminder_thread_stopped']:raise SystemExit(1)


if __name__=='__main__':main()
