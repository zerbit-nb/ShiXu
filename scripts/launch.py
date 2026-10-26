"""Start the local web app, open its page, and keep the console for shutdown."""
import argparse
from pathlib import Path
import sys
import threading
import time
import webbrowser

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def wait_and_open(url):
    with httpx.Client(trust_env=False,timeout=1) as client:
        for _ in range(40):
            try:
                response=client.get(url+'/api/health')
                if response.is_success and response.json().get('version'):
                    webbrowser.open(url)
                    return
            except (httpx.HTTPError,ValueError):
                pass
            time.sleep(.25)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Run CampusFlow on this computer.')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    url=f'http://127.0.0.1:{args.port}'
    if not args.no_browser:
        threading.Thread(target=wait_and_open,args=(url,),daemon=True).start()
    print(f'CampusFlow: {url}\nPress Ctrl+C to stop. Keep this window open while using the app.')
    server=uvicorn.Server(uvicorn.Config('app.main:app',host='127.0.0.1',port=args.port,
                                        lifespan='on',timeout_graceful_shutdown=20))
    if sys.platform != 'win32':
        server.run()
    else:
        from app.services.desktop_control import ControlSignals
        with ControlSignals.create() as signals:
            # Health exposes only process identity, never a credential or shutdown API.
            from app.main import app
            app.state.desktop_control={'pid':__import__('os').getpid(),'identity':signals.identity}
            server.config.app=app
            stopped=threading.Event()
            def watch():
                while not stopped.is_set():
                    if signals.wait_stop(200):
                        server.should_exit=True
                        return
            watcher=threading.Thread(target=watch,daemon=True);watcher.start()
            try:
                server.run()
                lifespan=server.lifespan
                success=(server.started and not lifespan.shutdown_failed and not lifespan.error_occurred)
                signals.finish(success)
            except BaseException:
                signals.finish(False)
                raise
            finally:
                stopped.set();watcher.join(timeout=2)
