"""Read-only cross-machine startup evidence without exposing login material."""
import hashlib
import json
import httpx
import pytest

from app.services.bridge import Installation
from scripts import diagnose_qq as diagnostic


def setup_install(tmp_path):
    config = tmp_path/'NapCat/managed/config'
    config.mkdir(parents=True)
    install = Installation(tmp_path/'vendor/NapCatWinBootMain.exe', config, True)
    (config/'webui.json').write_text(json.dumps({'port': 6099, 'host': '127.0.0.1', 'token': 'private-token'}))
    return install


def test_absent_preparation_and_other_backend_are_distinguished(tmp_path, monkeypatch):
    from app.services import desktop
    install = setup_install(tmp_path)
    monkeypatch.setattr(desktop, 'boot_is_running', lambda boot: False)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'application': 'CampusFlow', 'instance': 'other-directory'}))
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    report = diagnostic.startup_checks(tmp_path, install, transport=transport)
    assert report['process_probe'] == {'completed': True, 'launcher_running': False}
    assert report['preparation'] == {'entry_exists': False, 'patch_exists': False, 'launch_record_exists': False, 'start_record_exists': False}
    assert report['session_state'] == 'active'
    assert report['backend'] == {'reachable': True, 'is_shixu': True, 'matches_installation': False}
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_probe_failure_and_existing_stage_are_shareable(tmp_path, monkeypatch):
    import subprocess
    from app.services import desktop
    install = setup_install(tmp_path)
    (install.config.parent/'entry.cjs').write_text('private-account-token')
    (tmp_path/'runtime').mkdir()
    (tmp_path/'runtime/napcat-session.json').write_text(json.dumps({'state': 'exited', 'private': 'private-account-token'}))
    def failed(boot):
        raise subprocess.CalledProcessError(1, ['private-path'], stderr='private-account-token')
    monkeypatch.setattr(desktop, 'boot_is_running', failed)
    def offline(request): raise httpx.ConnectError('private-account-token', request=request)
    report = diagnostic.startup_checks(tmp_path, install, transport=httpx.MockTransport(offline))
    assert report['process_probe'] == {'completed': False, 'error': 'CalledProcessError', 'exit_code': 1}
    assert report['session_state'] == 'exited'
    assert report['preparation']['entry_exists']
    assert report['backend']['reachable'] is False
    text = json.dumps(report)
    assert 'private' not in text and str(tmp_path) not in text


@pytest.mark.parametrize('error', [TypeError('secret'), ValueError('secret'), PermissionError('secret')])
def test_probe_malformed_data_and_permissions_are_reported_safely(tmp_path, monkeypatch, error):
    from app.services import desktop
    install = setup_install(tmp_path)
    monkeypatch.setattr(desktop, 'boot_is_running', lambda boot: (_ for _ in ()).throw(error))
    report = diagnostic.startup_checks(tmp_path, install, transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    assert report['process_probe']['completed'] is False
    assert report['process_probe']['error'] == type(error).__name__
    assert 'secret' not in json.dumps(report)


def test_backend_identity_and_code_integrity_are_verified(tmp_path, monkeypatch):
    from app.services import desktop
    install = setup_install(tmp_path)
    monkeypatch.setattr(desktop, 'boot_is_running', lambda boot: True)
    target = tmp_path/'app/services/qq_login.py'
    target.parent.mkdir(parents=True)
    target.write_text('new')
    expected = hashlib.sha256(b'old').hexdigest()
    (tmp_path/'release-manifest.json').write_text(json.dumps({'files': [{'path': 'app/services/qq_login.py', 'sha256': expected}]}))
    identity = hashlib.sha256(str((tmp_path/'config.local.json').resolve()).encode()).hexdigest()
    report = diagnostic.startup_checks(tmp_path, install, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'application': 'CampusFlow', 'instance': identity})))
    assert report['backend']['matches_installation']
    assert report['runtime_integrity']['app/services/qq_login.py'] is False


def test_launcher_log_is_classified_without_returning_content(tmp_path, monkeypatch):
    from app.services import desktop
    install = setup_install(tmp_path)
    monkeypatch.setattr(desktop, 'boot_is_running', lambda boot: False)
    (tmp_path/'runtime').mkdir()
    (tmp_path/'runtime/desktop-window.log').write_text('Traceback: secret-path\nTypeError: secret-token\nQQ 启动检查失败', encoding='utf-8')
    report = diagnostic.startup_checks(tmp_path, install, transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    assert report['launcher_log']['exists']
    assert report['launcher_log']['qq_check_failed']
    assert report['launcher_log']['known_errors'] == ['TypeError']
    assert 'secret' not in json.dumps(report)
