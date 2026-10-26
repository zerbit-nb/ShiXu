"""Persist the real launch error without changing login or user data."""
import asyncio
from contextlib import nullcontext
import json

import httpx
import pytest

from app.services import napcat_bundle as bundle, qq_login
from app.services.bridge import BridgeMonitor, find_installation


def setup_install(tmp_path, monkeypatch):
    vendor = bundle.bundled_folder(tmp_path)
    vendor.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'loadNapCat.js', 'napcat.mjs', 'qqnt.json'):
        (vendor/name).touch()
    qq = tmp_path/'official/QQ.exe'
    qq.parent.mkdir()
    qq.touch()
    package = qq.parent/'resources/app/package.json'
    package.parent.mkdir(parents=True)
    package.write_text('{}')
    install = find_installation(tmp_path)
    bundle.initialize(install)
    monkeypatch.setattr(bundle, 'find_qq', lambda: qq)
    monkeypatch.setattr(qq_login, 'startup_lock', lambda path: nullcontext())
    monkeypatch.setattr(qq_login, 'boot_is_running', lambda boot: False)
    monkeypatch.setattr('app.services.desktop.boot_is_running', lambda boot: False)
    monkeypatch.setattr(bundle.subprocess, 'Popen', lambda *a, **kw: pytest.fail('Never start a client in these tests'))
    return install


def test_cross_drive_preparation_error_is_persisted_not_replaced_by_not_ready(tmp_path, monkeypatch):
    install = setup_install(tmp_path, monkeypatch)
    monkeypatch.setattr(bundle.os.path, 'relpath', lambda *a: (_ for _ in ()).throw(ValueError('different drives')))
    error = PermissionError(13, 'secret-token-and-path', str(tmp_path))
    error.winerror = 32
    monkeypatch.setattr(bundle, 'qq_launch_alias', lambda *a: (_ for _ in ()).throw(error))
    def offline(request):
        raise httpx.ConnectError('secret-network-path', request=request)
    login = qq_login.QQLogin(BridgeMonitor(tmp_path, httpx.MockTransport(offline)))
    async def flow():
        with pytest.raises(qq_login.LoginError) as first:
            await login.start()
        record = json.loads((install.config.parent/'start-status.json').read_text())
        assert record['state'] == 'preparation_failed'
        assert record['stage'] == 'map_qq_path'
        assert record['error'] == {'type': 'PermissionError', 'errno': 13, 'winerror': 32}
        for current in (login, qq_login.QQLogin(BridgeMonitor(tmp_path, httpx.MockTransport(offline)))):
            with pytest.raises(qq_login.LoginError) as later:
                await current.status('')
            assert later.value.state == first.value.state == 'start_failed'
            assert later.value.message == first.value.message
            assert '32' in later.value.message and 'DiagnoseQQ.cmd' in later.value.message
            assert str(tmp_path) not in later.value.message and 'secret' not in later.value.message
        assert 'secret' not in json.dumps(record) and str(tmp_path) not in json.dumps(record)
    asyncio.run(flow())


def test_readonly_diagnostic_preserves_failure_stage_and_filters_untrusted_values(tmp_path, monkeypatch):
    from scripts import diagnose_qq
    install = setup_install(tmp_path, monkeypatch)
    file = install.config.parent/'start-status.json'
    file.write_text(json.dumps({'state': 'preparation_failed', 'stage': 'write_patch',
        'error': {'type': 'PermissionError', 'winerror': 5, 'errno': 13, 'message': 'secret-token', 'path': str(tmp_path)},
        'exit_code': None, 'raw': 'secret-token'}))
    monkeypatch.setattr(bundle, 'qq_candidates', lambda: iter([]))
    before = file.read_bytes()
    report = diagnose_qq.collect(tmp_path)
    assert report['last_start'] == {'state': 'preparation_failed', 'exit_code': None,
        'stage': 'write_patch', 'error': {'type': 'PermissionError', 'errno': 13, 'winerror': 5}}
    assert file.read_bytes() == before
    assert 'secret' not in json.dumps(report) and str(tmp_path) not in json.dumps(report)
    file.write_text(json.dumps({'state': 'preparation_failed', 'stage': 'secret-path',
        'error': {'type': 'secret-token', 'winerror': 'secret-token', 'message': 'secret-token'}}))
    report = diagnose_qq.collect(tmp_path)
    assert 'secret' not in json.dumps(report)


def test_launch_failure_record_write_error_does_not_hide_original(tmp_path, monkeypatch):
    install = setup_install(tmp_path, monkeypatch)
    monkeypatch.setattr(bundle, 'qq_app_relative', lambda *a: (_ for _ in ()).throw(ValueError('secret-original')))
    monkeypatch.setattr(bundle, 'record_start', lambda *a, **kw: (_ for _ in ()).throw(PermissionError('secret-record')))
    with pytest.raises(ValueError, match='secret-original'):
        bundle.launch(install)


@pytest.mark.parametrize('error', [RuntimeError('secret-runtime'), TypeError('secret-type')])
def test_unexpected_preparation_failure_does_not_masquerade_as_start_lock(tmp_path, monkeypatch, error):
    install = setup_install(tmp_path, monkeypatch)
    monkeypatch.setattr(bundle, 'qq_app_relative', lambda *a: (_ for _ in ()).throw(error))
    def offline(request):
        raise httpx.ConnectError('secret-network', request=request)
    login = qq_login.QQLogin(BridgeMonitor(tmp_path, httpx.MockTransport(offline)))
    with pytest.raises(qq_login.LoginError) as caught:
        asyncio.run(login.start())
    assert caught.value.state == 'start_failed'
    assert 'secret' not in caught.value.message
    assert json.loads((install.config.parent/'start-status.json').read_text())['stage'] == 'read_package'


def test_corrupt_failure_fields_do_not_leak_or_break_hints():
    assert bundle.safe_start_failure({'stage': ['secret'], 'error': {'type': {'secret': True}, 'errno': True}}) == {'error': {'type': 'other'}}
