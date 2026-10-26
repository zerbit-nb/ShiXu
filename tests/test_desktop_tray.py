from types import SimpleNamespace
import threading
import pytest


def controller(stop=lambda: None, answer=True):
    from scripts.desktop_tray import TrayController
    calls=[]
    window=SimpleNamespace(destroy=lambda:calls.append('destroy'))
    tray=SimpleNamespace(ready=True, hide=lambda:calls.append('hide'), restore=lambda:calls.append('restore'),
        dispatch=lambda f:f(), confirm=lambda:answer, error=lambda s:calls.append(('error',s)),
        busy=lambda b:calls.append(('busy',b)))
    return TrayController(window,tray,stop),calls


def test_close_hides_without_destroying_or_stopping():
    c,calls=controller(lambda:pytest.fail('not an exit'))
    assert c.closing() is False
    assert calls==['hide']


def test_missing_tray_never_hides_window():
    c,calls=controller();c.tray.ready=False
    assert c.closing() is False
    assert 'hide' not in calls


def test_cancel_exit_keeps_backend_and_window():
    c,calls=controller(lambda:pytest.fail('cancelled'),False)
    c.request_exit()
    assert 'destroy' not in calls and not c.exiting


def test_success_destroys_only_after_backend_stops():
    finished=threading.Event()
    def stop(): assert 'destroy' not in calls;finished.set()
    c,calls=controller(stop);c.request_exit();c.worker.join(2)
    assert finished.is_set() and 'destroy' in calls and c.closing() is True


def test_failure_preserves_window_and_allows_retry():
    def fail():raise RuntimeError('清理失败')
    c,calls=controller(fail);c.request_exit();c.worker.join(2)
    assert 'destroy' not in calls and 'restore' in calls
    assert ('error','清理失败') in calls and not c.exiting
    c.stop_backend=lambda:None;c.request_exit();c.worker.join(2)
    assert 'destroy' in calls


def test_repeated_exit_does_not_start_two_shutdowns():
    gate=threading.Event();entered=threading.Event()
    def stop():entered.set();gate.wait(2)
    c,calls=controller(stop);c.request_exit();assert entered.wait(1)
    worker=c.worker;c.request_exit();assert c.worker is worker
    gate.set();worker.join(2);assert calls.count('destroy')==1


@pytest.mark.parametrize('state',['occupied','upgrade'])
def test_shutdown_refuses_other_service(monkeypatch,tmp_path,state):
    import app.services.desktop_control as control
    monkeypatch.setattr(control,'server_state',lambda *a:state)
    with pytest.raises(RuntimeError,match='身份'):
        control.stop_backend(tmp_path)


def test_stopped_backend_needs_no_control(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    monkeypatch.setattr(control,'server_state',lambda *a:'stopped')
    control.stop_backend(tmp_path)


def test_named_signals_hold_cleanup_result_after_owner_closes():
    from app.services.desktop_control import ControlSignals
    with ControlSignals.create() as owner:
        with ControlSignals.open(owner.identity) as peer:
            assert not owner.wait_stop(0)
            peer.request_stop();assert owner.wait_stop(1000)
            owner.finish(False)
            assert not peer.succeeded()
            assert peer.failed()
    with pytest.raises(RuntimeError):ControlSignals.open(owner.identity)


def test_shutdown_cleanup_failure_is_not_reported_as_success(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    app=create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config')
    async def fail():
        app.state.wechat.reason='cleanup_failed'
        return app.state.wechat.status()
    with pytest.raises(RuntimeError,match='cleanup_failed'):
        with TestClient(app):monkeypatch.setattr(app.state.wechat,'stop',fail)


def test_failed_stop_cannot_succeed_just_because_port_closed(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    monkeypatch.setattr(control,'server_state',lambda *a:'stopped')
    stop=control.BackendStopper(tmp_path);stop.require_verified=True
    with pytest.raises(RuntimeError,match='清理'):stop()


def test_failed_callback_sets_verification_latch(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    def fail(*a,**kw):raise RuntimeError('timeout')
    monkeypatch.setattr(control,'stop_backend',fail)
    stop=control.BackendStopper(tmp_path)
    with pytest.raises(RuntimeError):stop()
    assert stop.require_verified


def test_virtualenv_backend_image_is_accepted_but_unrelated_exe_is_not(tmp_path):
    import sys
    from app.services.desktop_control import trusted_backend_image
    assert trusted_backend_image(tmp_path,sys._base_executable)
    assert trusted_backend_image(tmp_path,tmp_path/'.venv/Scripts/pythonw.exe')
    assert not trusted_backend_image(tmp_path,tmp_path/'unrelated.exe')


def test_app_lifespan_stops_active_receiver_and_keeps_business_data(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.config import Settings
    from tests.test_wechat_monitor import Process,until
    import sqlite3
    app=create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config')
    async def start():
        monitor=app.state.wechat
        await monitor.configure('测试群','test-account')
        proc=Process()
        async def spawn(private):return proc
        monitor.spawn=spawn
        await monitor.start()
        await until(lambda:bool(proc.stdin.commands))
        return proc,monitor.private
    with TestClient(app) as client:
        proc,private=client.portal.call(start)
        assert private.exists() and proc.returncode is None
        assert client.get('/api/wechat/status').json()['state']=='starting'
    assert proc.returncode==0 and not private.exists()
    assert any(c['type']=='stop' for c in proc.stdin.commands)
    with sqlite3.connect(tmp_path/'db') as db:
        assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
    with TestClient(create_app(Settings(),db_path=tmp_path/'db',config_path=tmp_path/'config')) as client:
        assert client.get('/api/wechat/status').json()['state']=='paused'
