"""Optional real Windows WebView2 smoke against disposable synthetic data. No personal profile."""
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import traceback
import uvicorn
import webview
from tests.workbench_app import make_app


def main():
    with socket.socket() as guard:
        guard.bind(('127.0.0.1', 8781))
    outcome={'passed':False}
    with tempfile.TemporaryDirectory(prefix='campusflow-webview-') as folder:
        server=uvicorn.Server(uvicorn.Config(make_app(Path(folder)),host='127.0.0.1',port=8781,log_level='error'))
        thread=threading.Thread(target=server.run,daemon=True)
        thread.start()
        window=webview.create_window('CampusFlow isolated compatibility check','http://127.0.0.1:8781',width=1280,height=860,hidden=True)
        def wait_js(expression):
            for _ in range(80):
                try:
                    if window.evaluate_js(expression):return
                except Exception:pass
                time.sleep(.2)
            raise AssertionError('WebView2 condition timed out: '+expression)
        def probe():
            try:
                wait_js("!!document.querySelector('#taskList .task-open')")
                assert window.evaluate_js("!document.querySelector('#tasksView').hidden")
                assert window.evaluate_js("CSS.supports('selector(:modal)') && CSS.supports('selector(:has(*))') && 'showPopover' in HTMLElement.prototype")
                window.evaluate_js("document.querySelector('#taskList .task-open').click()")
                wait_js("document.querySelectorAll('#taskDetail .detail-source').length===2")
                window.evaluate_js("document.querySelector('#closeTaskDetail').click();document.querySelector('[data-view=messages]').click()")
                wait_js("document.querySelectorAll('[data-inbox-message]').length===30")
                assert window.evaluate_js("document.documentElement.scrollWidth<=innerWidth")
                outcome['passed']=True
            except Exception:
                outcome['error']=traceback.format_exc()
            finally:window.destroy()
        try:webview.start(probe,gui='edgechromium',debug=False,private_mode=True)
        finally:
            server.should_exit=True
            thread.join(10)
        print(json.dumps(outcome,ensure_ascii=False))
        if not outcome['passed']:raise SystemExit(1)

if __name__=='__main__':main()
