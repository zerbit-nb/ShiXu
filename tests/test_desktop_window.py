from types import SimpleNamespace
import pytest


def test_window_names(tmp_path):
    from scripts.desktop_window import instance_name
    assert instance_name(tmp_path) == instance_name(tmp_path / '.')
    assert instance_name(tmp_path) != instance_name(tmp_path / 'other')
    assert str(tmp_path) not in instance_name(tmp_path)


@pytest.mark.parametrize('state', ['occupied', 'stopped', 'upgrade'])
def test_refuses_unverified_backend(tmp_path, monkeypatch, state):
    import scripts.desktop_window as desktop
    monkeypatch.setattr(desktop.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(desktop, 'server_state', lambda *a: state)
    with pytest.raises(RuntimeError, match='8000'):
        desktop.prepare_backend(tmp_path)


def test_launcher_failure(tmp_path, monkeypatch):
    import scripts.desktop_window as desktop
    monkeypatch.setattr(desktop.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match='启动失败'):
        desktop.prepare_backend(tmp_path)


def test_ready_backend_reuses_launcher(tmp_path, monkeypatch):
    import scripts.desktop_window as desktop
    calls=[]
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(desktop.subprocess, 'run', run)
    monkeypatch.setattr(desktop, 'server_state', lambda *a: 'ready')
    desktop.prepare_backend(tmp_path)
    assert calls[0][0][-2:] == [str(tmp_path / 'scripts/desktop.py'), '--no-browser']
    assert calls[0][1]['cwd'] == tmp_path
    assert calls[0][1]['timeout'] <= 90


def test_no_python_api_and_explicit_close_semantics(monkeypatch):
    from scripts.desktop_window import open_window
    calls={}
    from webview.event import Event
    class View:
        settings={}
        def create_window(self, title, url, **kwargs):
            calls.update(url=url, options=kwargs)
            return SimpleNamespace(events=SimpleNamespace(**{name:Event(None) for name in ('before_show','shown','loaded','closing','closed')}))
        def start(self, **kwargs):
            calls['start']=kwargs
    import scripts.desktop_tray as tray
    monkeypatch.setattr(tray.WindowsTray,'dispose',lambda self:None)
    view=View()
    open_window(view)
    assert calls['url'] == 'http://127.0.0.1:8000/?desktop=1'
    assert calls['options']['confirm_close'] is False
    assert 'js_api' not in calls['options']
    assert calls['start']['gui'] == 'edgechromium'
    assert calls['start']['debug'] is False
    assert calls['start']['private_mode'] is True
    from scripts.desktop_window import ICON_PATH
    assert calls['start']['icon'] == str(ICON_PATH)
    assert ICON_PATH.is_file()
    assert view.settings['ALLOW_DOWNLOADS'] is False
    assert view.settings['ALLOW_FILE_URLS'] is False


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows named objects')
def test_single_window_signals_and_releases_handles(tmp_path):
    from scripts.desktop_window import WindowInstance
    with WindowInstance(tmp_path) as first:
        assert first.primary
        with WindowInstance(tmp_path) as second:
            assert not second.primary
        assert first.wait(1000)
        assert not first.wait(10)
    with WindowInstance(tmp_path) as reopened:
        assert reopened.primary


def test_missing_dependency_does_not_start_backend(monkeypatch, tmp_path):
    import builtins
    import scripts.desktop_window as desktop
    original=builtins.__import__
    def load(name, *a, **kw):
        if name == 'webview': raise ImportError('missing')
        return original(name, *a, **kw)
    monkeypatch.setattr(builtins, '__import__', load)
    monkeypatch.setattr(desktop, 'ROOT', tmp_path)
    monkeypatch.setattr(desktop, 'prepare_backend', lambda *a: pytest.fail('must not start'))
    messages=[]
    monkeypatch.setattr(desktop, 'show_error', messages.append)
    assert desktop.main() == 1
    assert 'requirements-desktop.txt' in messages[0]
