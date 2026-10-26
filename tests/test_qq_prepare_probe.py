import json
from types import SimpleNamespace
import pytest
from app.services import napcat_bundle as bundle
from scripts import probe_qq_prepare as probe


def setup_files(tmp_path, monkeypatch):
    from app.services.bridge import find_installation
    vendor = bundle.bundled_folder(tmp_path)
    vendor.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'loadNapCat.js', 'napcat.mjs', 'qqnt.json'):
        (vendor/name).touch()
    qq = tmp_path/'official/QQ.exe'
    qq.parent.mkdir()
    qq.touch()
    app = qq.parent/'resources/app'
    app.mkdir(parents=True)
    (app/'package.json').write_text('{}')
    install = find_installation(tmp_path)
    bundle.initialize(install)
    (install.config.parent/'entry.cjs').write_text('existing-user-startup-entry')
    (tmp_path/'data').mkdir()
    (tmp_path/'data/campusflow.sqlite3').write_text('existing-user-business-data')
    monkeypatch.setattr(bundle, 'find_qq', lambda: qq)
    return qq, install


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_probe_executes_real_preparation_but_never_launches_loader(tmp_path, monkeypatch):
    qq, install = setup_files(tmp_path, monkeypatch)
    original = snapshot(tmp_path)
    monkeypatch.setattr(bundle.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('Never start QQ'))
    report = probe.collect(tmp_path)
    assert report['prepared'] and not report['qq_started']
    assert report['scratch_cleaned']
    assert original == snapshot(tmp_path)
    assert str(tmp_path) not in json.dumps(report)


def test_probe_returns_exact_preparation_failure_with_no_secret(tmp_path, monkeypatch):
    qq, install = setup_files(tmp_path, monkeypatch)
    original = snapshot(tmp_path)
    def broken(qq): raise PermissionError(13, 'secret-token-and-account', str(tmp_path))
    monkeypatch.setattr(bundle, 'qq_app_relative', broken)
    report = probe.collect(tmp_path)
    assert not report['prepared'] and report['scratch_cleaned']
    assert report['error']['type'] == 'PermissionError' and report['error']['errno'] == 13
    assert report['steps'] == ['qq_app_relative']
    assert original == snapshot(tmp_path)
    assert 'secret' not in json.dumps(report) and str(tmp_path) not in json.dumps(report)


def test_probe_localizes_cross_disk_alias_failure(tmp_path, monkeypatch):
    qq, install = setup_files(tmp_path, monkeypatch)
    original = snapshot(tmp_path)
    monkeypatch.setattr(bundle.os.path, 'relpath', lambda *args: (_ for _ in ()).throw(ValueError('different mounts')))
    monkeypatch.setattr(bundle, 'qq_launch_alias', lambda *args: (_ for _ in ()).throw(ValueError('无法创建 QQ 跨磁盘路径映射，secret-path')))
    report = probe.collect(tmp_path)
    assert report['error']['category'] == 'mapping_creation_failed'
    assert report['steps'] == ['qq_app_relative', 'qq_launch_alias']
    assert report['scratch_cleaned'] and original == snapshot(tmp_path)
    assert 'secret' not in json.dumps(report)


def test_probe_rejects_legacy_and_does_not_modify_it(tmp_path):
    assert probe.collect(tmp_path)['error']['category'] == 'bundled_installation_required'
    assert snapshot(tmp_path) == {}


def test_mapping_error_is_allowlisted_and_paths_never_enter_command_text():
    command = ['powershell.exe', '-File', 'secret-script-path/prepare_qq.ps1', '-QQDirectory', 'secret-qq-path', '-Destination', 'secret-app-path']
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout=json.dumps({'error_type': 'UnauthorizedAccessException', 'hresult': -2147024891, 'line': 12, 'message': 'secret-token'}))
    result, details = probe.run_mapping(command, {'env': {}, 'capture_output': True}, run)
    assert result.returncode == 1
    assert details == {'type': 'UnauthorizedAccessException', 'hresult': -2147024891, 'line': 12}
    assert not any('secret' in arg for arg in calls[0][0])
    assert calls[0][1]['env']['SHIXU_PROBE_TARGET'] == 'secret-qq-path'
    assert 'secret' not in json.dumps(details)
