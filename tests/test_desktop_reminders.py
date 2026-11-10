"""Native delivery uses existing tray, respects visibility and releases on failure."""
import threading
from types import SimpleNamespace
import httpx
from scripts.desktop_reminders import DesktopReminders


def test_native_claim_confirm_and_no_foreground_duplication():
    paths=[];notifications=[]
    def transport(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/claim'):
            return httpx.Response(200,json={'claim_id':'test','events':[{'tasks':[{'id':'a'}]}]})
        return httpx.Response(200,json={'events':[{'tasks':[{'id':'a'},{'id':'a'}]}]})
    tray=SimpleNamespace(ready=True,dispatch=lambda action:action(),notify_reminders=lambda n:notifications.append(n) or True)
    visible=SimpleNamespace(visible=True)
    bridge=DesktopReminders(None,tray,visible,threading.Event(),'http://testserver')
    with httpx.Client(base_url='http://testserver',transport=httpx.MockTransport(transport)) as client:
        bridge.deliver_once(client);assert not paths
        visible.visible=False;bridge.deliver_once(client)
    assert notifications==[1]
    assert paths==['/api/reminders/claim','/api/reminders/delivery/test/confirm']


def test_native_failure_or_visibility_change_releases_claim():
    for failure in ('show','focus','exception'):
        paths=[];visible=SimpleNamespace(visible=False)
        def transport(request):
            paths.append(request.url.path)
            if request.url.path.endswith('/claim'):data={'claim_id':'test','events':[{}]}
            else:data={'events':[{'tasks':[{'id':'a'}]}]}
            if failure=='focus' and request.url.path.endswith('/confirm'):visible.visible=True
            return httpx.Response(200,json=data)
        def notify(count):
            if failure=='exception':raise RuntimeError('native API unavailable')
            return False
        tray=SimpleNamespace(ready=True,dispatch=lambda action:action(),notify_reminders=notify)
        bridge=DesktopReminders(None,tray,visible,threading.Event(),'http://testserver')
        with httpx.Client(base_url='http://testserver',transport=httpx.MockTransport(transport)) as client:
            bridge.deliver_once(client)
        assert paths[-1].endswith('/release')


def test_stopped_bridge_never_polls():
    stopped=threading.Event();stopped.set()
    bridge=DesktopReminders(None,SimpleNamespace(ready=True),SimpleNamespace(visible=False),stopped,'http://testserver')
    bridge.deliver_once(None)
