import importlib.util
from pathlib import Path
import json
from types import SimpleNamespace
import subprocess

spec=importlib.util.spec_from_file_location('installer_guard',Path(__file__).resolve().parents[1]/'packaging/package_guard.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)

def test_new_guard_checks_old_install_without_importing_old_application(tmp_path,monkeypatch):
    boot=tmp_path/'third_party/napcat/v4.18.38/NapCatWinBootMain.exe'
    boot.parent.mkdir(parents=True);boot.touch()
    config=tmp_path/'NapCat/managed/config';config.mkdir(parents=True)
    (config/'launch.json').write_text(json.dumps({'qq_path':str(tmp_path/'runtime/qq-launch/client/QQ.exe')}))
    (tmp_path/'package_guard.py').write_text('raise RuntimeError("old broken guard")')
    probe=tmp_path/'new-probe.ps1';probe.touch()
    calls=[]
    def run(cmd,**kwargs):
        calls.append(cmd);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(guard.subprocess,'run',run)
    assert guard.check_napcat(tmp_path,probe)=='stopped'
    assert str(probe) in calls[0] and '-CheckOnly' in calls[0] and '-RequireStopped' in calls[0]
    assert '-QQPath' in calls[0]
    assert not any('old broken' in x for x in calls[0])

def test_running_and_failed_probe_are_distinct_and_both_block(tmp_path,monkeypatch):
    boot=tmp_path/'third_party/napcat/v4.18.38/NapCatWinBootMain.exe'
    boot.parent.mkdir(parents=True);boot.touch()
    for code,expected in [(3,'running'),(1,'check_failed'),(0,'stopped')]:
        monkeypatch.setattr(guard.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=code))
        assert guard.check_napcat(tmp_path,tmp_path/'probe.ps1')==expected

def test_installer_extracts_new_guard_before_upgrade():
    source=(Path(__file__).resolve().parents[1]/'packaging/Shixu.iss').read_text(encoding='utf-8')
    assert "ExtractTemporaryFile('upgrade_guard.py')" in source
    assert "ExtractTemporaryFile('upgrade_probe.ps1')" in source
    assert r'{tmp}\upgrade_guard.py' in source

def test_installer_does_not_pass_redirection_guard_to_application():
    source=(Path(__file__).resolve().parents[1]/'packaging/Shixu.iss').read_text(encoding='utf-8')
    assert '[Run]' not in source
    assert 'RedirectionGuard=no' not in source
    assert '从桌面或开始菜单' in source

def test_invalid_record_or_failed_probe_never_allows_replacement(tmp_path,monkeypatch):
    boot=tmp_path/'third_party/napcat/v4.18.38/NapCatWinBootMain.exe'
    boot.parent.mkdir(parents=True);boot.touch()
    config=tmp_path/'NapCat/managed/config';config.mkdir(parents=True)
    (config/'launch.json').write_text('{broken')
    assert guard.check_napcat(tmp_path,tmp_path/'probe.ps1')=='check_failed'
    (config/'launch.json').unlink()
    def timeout(*a,**k):raise subprocess.TimeoutExpired('probe',25)
    monkeypatch.setattr(guard.subprocess,'run',timeout)
    assert guard.check_napcat(tmp_path,tmp_path/'probe.ps1')=='check_failed'

def test_running_and_uncertain_checks_keep_distinct_exit_codes(tmp_path,monkeypatch):
    def function(*a):pass
    kernel=SimpleNamespace(OpenMutexW=function,CloseHandle=function)
    monkeypatch.setattr(guard.ctypes,'WinDLL',lambda *a,**k:kernel)
    monkeypatch.setattr(kernel,'OpenMutexW',lambda *a:0)
    monkeypatch.setattr(guard.ctypes,'get_last_error',lambda:2)
    for state,code in [('running',10),('check_failed',20)]:
        monkeypatch.setattr(guard,'check_napcat',lambda *a:state)
        assert guard.replacement_status(tmp_path,tmp_path/'probe.ps1')==code
