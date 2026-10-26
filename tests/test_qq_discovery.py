"""Official QQ discovery without assuming one fixed uninstall registry key."""
import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
import sys
import httpx
import pytest
from app.services import napcat_bundle as bundle


class Registry:
    HKEY_CURRENT_USER = 1
    HKEY_LOCAL_MACHINE = 2
    KEY_WOW64_32KEY = 32
    KEY_WOW64_64KEY = 64
    KEY_READ = 1

    def __init__(self, records):
        self.records = records

    def OpenKey(self, hive, key, reserved=0, flags=0):
        if hive != 1 or key not in self.records: raise FileNotFoundError()
        return SimpleKey(self.records[key])

    def QueryValueEx(self, key, name):
        if name not in key.data: raise FileNotFoundError()
        return key.data[name], 1

    def EnumKey(self, key, index):
        try: return key.data.get('children', [])[index]
        except IndexError: raise OSError()


class SimpleKey:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass


UNINSTALL = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'


@pytest.mark.parametrize('source', ['uninstall_guid', 'app_paths', 'tencent_install'])
def test_registry_discovery_supports_nonlegacy_registration(tmp_path, monkeypatch, source):
    qq = tmp_path/'Custom QQ'/'QQ.exe'
    if source == 'uninstall_guid':
        records = {UNINSTALL: {'children': ['{qq-install-id}', 'browser']},
                   UNINSTALL+r'\{qq-install-id}': {'DisplayName': 'QQ', 'InstallLocation': str(qq.parent)},
                   UNINSTALL+r'\browser': {'DisplayName': 'QQ浏览器', 'InstallLocation': str(tmp_path/'browser')}}
    elif source == 'app_paths':
        records = {r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe': {'': '"'+str(qq)+'"'}}
    else:
        records = {r'SOFTWARE\Tencent\QQ': {'Install': str(qq.parent)}}
    monkeypatch.setitem(sys.modules, 'winreg', Registry(records))
    monkeypatch.setattr(bundle, 'qq_process_candidates', lambda: iter([]), raising=False)
    monkeypatch.setattr(bundle, 'qq_default_candidates', lambda: iter([]), raising=False)
    assert list(bundle.qq_candidates()) == [qq]


def test_running_qq_fallback_when_all_uninstall_keys_are_missing(tmp_path, monkeypatch):
    qq = tmp_path/'Unregistered QQ'/'QQ.exe'
    qq.parent.mkdir();qq.touch()
    monkeypatch.setitem(sys.modules, 'winreg', Registry({}))
    monkeypatch.setattr(bundle, 'qq_default_candidates', lambda: iter([]), raising=False)
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        if '-QQPath' in command: return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=0, stdout=json.dumps([str(qq), str(qq)]))
    monkeypatch.setattr(bundle.subprocess, 'run', run)
    assert bundle.find_qq() == qq.resolve()
    assert len(calls) == 2
    assert all(k.lower() != 'psmodulepath' for _, kw in calls for k in kw['env'])
    assert any('-QQPath' in command for command, _ in calls), 'Fallback must still verify Tencent signature'


def test_process_failure_does_not_hide_common_install_location(tmp_path, monkeypatch):
    qq = tmp_path/'Programs'/'QQ'/'QQ.exe'
    qq.parent.mkdir(parents=True);qq.touch()
    monkeypatch.setitem(sys.modules, 'winreg', Registry({}))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    def run(command, **kwargs):
        if '-QQPath' in command: return SimpleNamespace(returncode=0)
        raise bundle.subprocess.TimeoutExpired(command, 10)
    monkeypatch.setattr(bundle.subprocess, 'run', run)
    assert bundle.find_qq() == qq.resolve()


def test_rejected_or_timed_out_signature_does_not_launch_or_hide_next_candidate(tmp_path, monkeypatch):
    rows = [tmp_path/'bad'/'QQ.exe', tmp_path/'slow'/'QQ.exe', tmp_path/'good'/'QQ.exe']
    for row in rows: row.parent.mkdir();row.touch()
    monkeypatch.setattr(bundle, 'qq_candidates', lambda: iter(rows))
    def run(command, **kwargs):
        path = command[-1]
        if path == str(rows[1]): raise bundle.subprocess.TimeoutExpired(command, 20)
        return SimpleNamespace(returncode=0 if path == str(rows[2]) else 1)
    monkeypatch.setattr(bundle.subprocess, 'run', run)
    assert bundle.find_qq() == rows[2].resolve()


def test_missing_client_reason_survives_later_status_poll(tmp_path, monkeypatch):
    from app.services.bridge import BridgeMonitor
    from app.services.qq_login import QQLogin, LoginError
    folder = bundle.bundled_folder(tmp_path);folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'napcat.mjs', 'loadNapCat.js', 'qqnt.json'):
        (folder/name).touch()
    def unreachable(request): raise httpx.ConnectError('private-path', request=request)
    login = QQLogin(BridgeMonitor(tmp_path, httpx.MockTransport(unreachable)))
    monkeypatch.setattr('app.services.qq_login.startup_lock', lambda p: nullcontext())
    monkeypatch.setattr('app.services.qq_login.boot_is_running', lambda p: False)
    def missing(_): raise ValueError('未找到可用的官方 QQ，请先打开官方 QQ 后重试。')
    monkeypatch.setattr('app.services.qq_login.launch', missing)
    async def flow():
        with pytest.raises(LoginError) as first: await login.start()
        with pytest.raises(LoginError) as later: await login.status('')
        assert later.value.state == first.value.state == 'start_failed'
        assert later.value.message == first.value.message
        assert 'private-path' not in later.value.message
    asyncio.run(flow())


def test_saved_missing_client_stage_is_reported_after_backend_restart(tmp_path, monkeypatch):
    from app.services.bridge import BridgeMonitor, find_installation
    from app.services.qq_login import QQLogin, LoginError
    folder = bundle.bundled_folder(tmp_path);folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'napcat.mjs', 'loadNapCat.js', 'qqnt.json'):
        (folder/name).touch()
    install = find_installation(tmp_path)
    def missing(): raise bundle.QQNotFoundError(bundle.QQ_NOT_FOUND_HINT)
    monkeypatch.setattr(bundle, 'find_qq', missing)
    with pytest.raises(bundle.QQNotFoundError): bundle.launch(install)
    assert json.loads((install.config.parent/'start-status.json').read_text())['state'] == 'qq_not_found'
    def unreachable(request): raise httpx.ConnectError('private-path', request=request)
    login = QQLogin(BridgeMonitor(tmp_path, httpx.MockTransport(unreachable)))
    with pytest.raises(LoginError) as error: asyncio.run(login.status(''))
    assert error.value.state == 'start_failed' and error.value.message == bundle.QQ_NOT_FOUND_HINT


def test_valid_registry_candidate_does_not_probe_processes(tmp_path, monkeypatch):
    qq = tmp_path/'QQ.exe';qq.touch()
    monkeypatch.setattr(bundle, 'qq_registry_candidates', lambda: iter([qq]))
    def forbidden(): pytest.fail('Do not wait on process discovery when a valid registered QQ is available')
    monkeypatch.setattr(bundle, 'qq_process_candidates', forbidden)
    monkeypatch.setattr(bundle.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0))
    assert bundle.find_qq() == qq.resolve()


def test_running_version_executable_prefers_official_launcher(tmp_path, monkeypatch):
    qq = tmp_path/'QQ'/'versions'/'9.9.26-44725'/'QQ.exe'
    def run(*args, **kwargs): return SimpleNamespace(returncode=0, stdout=json.dumps(str(qq)))
    monkeypatch.setattr(bundle.subprocess, 'run', run)
    assert list(bundle.qq_process_candidates()) == [tmp_path/'QQ'/'QQ.exe', qq]


def test_diagnostics_distinguish_missing_registry_from_available_client(tmp_path, monkeypatch):
    from scripts.diagnose_qq import collect
    qq = tmp_path/'Custom QQ'/'QQ.exe';qq.parent.mkdir();qq.touch()
    monkeypatch.setattr(bundle, 'qq_candidates', lambda: iter([qq]))
    monkeypatch.setattr(bundle, 'qq_registry_candidates', lambda: iter([]))
    monkeypatch.setattr(bundle, 'find_qq', lambda: qq)
    (tmp_path/'release-manifest.json').write_text(json.dumps({'version': '0.5.0-preview.5', 'files': []}))
    report = collect(tmp_path)
    assert report['app_version'] == '0.5.0-preview.5'
    assert report['qq']['registered_candidates'] == 0
    assert report['qq']['discovered_executables'] == 1 and report['qq']['signed_official_found']
    assert str(tmp_path) not in json.dumps(report)
