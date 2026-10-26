import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import start_qq_checked as checked


def setup_install(tmp_path, monkeypatch):
    from app.services import qq_login, napcat_bundle
    from app.services.bridge import find_installation
    vendor = napcat_bundle.bundled_folder(tmp_path)
    vendor.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'loadNapCat.js', 'napcat.mjs', 'qqnt.json'):
        (vendor/name).touch()
    install = find_installation(tmp_path)
    napcat_bundle.initialize(install)
    for name in ('qq.local.json', 'wechat.local.json'):
        (tmp_path/name).write_text('private-original-config')
    (tmp_path/'data').mkdir()
    (tmp_path/'data/campusflow.sqlite3').write_text('original-business-data')
    (install.config.parent/'entry.cjs').write_text('old-adapter')
    monkeypatch.setattr(qq_login, 'startup_lock', lambda folder: __import__('contextlib').nullcontext())
    monkeypatch.setattr(qq_login, 'boot_is_running', lambda boot: False)
    return install, qq_login


def test_checked_start_captures_original_error_before_it_is_hidden(tmp_path, monkeypatch):
    install, login_module = setup_install(tmp_path, monkeypatch)
    def failed(install): raise PermissionError(13, 'private-token', str(tmp_path))
    monkeypatch.setattr(login_module, 'launch', failed)
    async def offline(self, url): return False
    monkeypatch.setattr(login_module.QQLogin, 'management_alive', offline)
    report = asyncio.run(checked.start(tmp_path))
    assert report['result_state'] == 'start_failed'
    assert report['launch_error']['type'] == 'PermissionError' and report['launch_error']['errno'] == 13
    assert report['backup']['generated_files'] == 1
    assert (next((tmp_path/'runtime/backups').iterdir())/'entry.cjs').read_text() == 'old-adapter'
    assert not report['management_ready']
    assert 'private' not in json.dumps(report).replace('private_data_included', '')
    assert str(tmp_path) not in json.dumps(report)
    assert (tmp_path/'data/campusflow.sqlite3').read_text() == 'original-business-data'
    assert (tmp_path/'qq.local.json').read_text() == (tmp_path/'wechat.local.json').read_text() == 'private-original-config'


def test_checked_start_uses_original_flow_and_reports_real_readiness(tmp_path, monkeypatch):
    install, login_module = setup_install(tmp_path, monkeypatch)
    launched = []
    def launch(selected):
        launched.append(selected)
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(login_module, 'launch', launch)
    async def alive(self, url): return bool(launched)
    monkeypatch.setattr(login_module.QQLogin, 'management_alive', alive)
    report = asyncio.run(checked.start(tmp_path))
    assert report['result_state'] == 'running' and report['management_ready']
    assert report['phase'] == 'management_reachable' and launched == [install]


def test_checked_start_never_duplicates_existing_management(tmp_path, monkeypatch):
    install, login_module = setup_install(tmp_path, monkeypatch)
    monkeypatch.setattr(login_module, 'launch', lambda selected: pytest.fail('Never duplicate a running service'))
    async def alive(self, url): return True
    monkeypatch.setattr(login_module.QQLogin, 'management_alive', alive)
    report = asyncio.run(checked.start(tmp_path))
    assert report['management_ready'] and not report['launch_attempted']
    assert not (tmp_path/'runtime/backups').exists()


def test_checked_start_refuses_to_overwrite_generated_path_link(tmp_path, monkeypatch):
    install, login_module = setup_install(tmp_path, monkeypatch)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda self: self == install.config.parent/'entry.cjs' or original(self))
    async def offline(self, url): return False
    monkeypatch.setattr(login_module.QQLogin, 'management_alive', offline)
    monkeypatch.setattr(login_module, 'launch', lambda selected: pytest.fail('Unsafe path must not be touched'))
    report = asyncio.run(checked.start(tmp_path))
    assert report['launch_error']['type'] == 'RuntimeError'
    assert not report['launch_attempted'] and not report['management_ready']


def test_checked_start_rejects_non_bundled_installation(tmp_path):
    assert asyncio.run(checked.start(tmp_path))['error']['category'] == 'bundled_installation_required'
