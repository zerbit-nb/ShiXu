"""Use the existing Windows tray; no helper process survives application exit."""
import threading
import httpx


class DesktopReminders:
    def __init__(self, window, tray, visibility, stopped, url):
        self.window, self.tray, self.visibility, self.stopped, self.url = window, tray, visibility, stopped, url
        self.open_requested = threading.Event()
        self.worker = None
        self.has_notification = False

    def attach(self):
        self.tray.icon.BalloonTipClicked += self.open
        self.worker = threading.Thread(target=self.run, daemon=True)
        self.worker.start()

    def open(self, *_):
        if self.has_notification:
            self.open_requested.set()
            self.tray.restore()

    def deliver_once(self, client):
        if self.stopped.is_set() or self.visibility.visible or not self.tray.ready:
            return
        response = client.post('/api/reminders/claim', json={'channel':'system'})
        response.raise_for_status()
        claim = response.json()
        token = claim.get('claim_id')
        if not token:
            return
        shown = threading.Event()
        expired = threading.Event()
        successful = []
        try:
            response = client.post('/api/reminders/delivery/'+token+'/confirm')
            response.raise_for_status()
            events = response.json()['events']
            count = len({task['id'] for event in events for task in event['tasks']})
            if not count:
                return
            def present():
                try:
                    if not expired.is_set() and not self.stopped.is_set() and not self.visibility.visible:
                        successful.append(self.tray.notify_reminders(count))
                        self.has_notification = bool(successful[-1])
                except Exception:
                    successful.append(False)
                finally:
                    shown.set()
            self.tray.dispatch(present)
            if not shown.wait(3):
                expired.set()
        finally:
            if not successful or not successful[-1]:
                client.post('/api/reminders/delivery/'+token+'/release')

    def run(self):
        with httpx.Client(base_url=self.url, timeout=2, trust_env=False,
                          headers={'Origin':self.url}) as client:
            while not self.stopped.is_set():
                try:
                    if self.open_requested.is_set() and self.visibility.loaded.is_set() and self.visibility.visible:
                        self.open_requested.clear()
                        self.window.run_js("window.dispatchEvent(new Event('shixu-reminder-open'));")
                    if self.visibility.loaded.is_set():
                        self.deliver_once(client)
                except Exception:
                    # Claims expire if the UI or server disappears mid-delivery.
                    pass
                self.stopped.wait(5)

    def join(self):
        if self.worker is not None:
            self.worker.join(timeout=7)
