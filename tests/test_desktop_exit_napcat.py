"""Full tray exit releases only this installation; hiding is covered separately."""
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
import os
import shutil
import subprocess
import time
import socket
import sys
import httpx


def install(tmp_path, monkeypatch):
    import app.services.bridge as bridge
    boot=tmp_path/'third_party/napcat/v4.18.38/NapCatWinBootMain.exe'
    boot.parent.mkdir(parents=True);boot.touch()
    monkeypatch.setattr(bridge,'find_installation',lambda root:SimpleNamespace(boot=boot))
    return boot


def test_full_exit_waits_for_backend_then_scoped_napcat(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    calls=[]
    monkeypatch.setattr(control,'stop_backend',lambda *a,**kw:calls.append('backend'))
    monkeypatch.setattr(control,'stop_desktop_napcat',lambda root:calls.append(('napcat',root)))
    control.BackendStopper(tmp_path)()
    assert calls==['backend',('napcat',tmp_path)]


def test_napcat_failure_keeps_tray_and_retry_cleans_remaining_processes(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    from scripts.desktop_tray import TrayController
    calls=[]
    monkeypatch.setattr(control,'stop_backend',lambda *a,**kw:calls.append('backend'))
    def cleanup(root):
        calls.append('napcat')
        if calls.count('napcat')==1:raise RuntimeError('NapCat 尚未停止')
    monkeypatch.setattr(control,'stop_desktop_napcat',cleanup)
    stopper=control.BackendStopper(tmp_path)
    window=SimpleNamespace(destroy=lambda:calls.append('destroy'))
    tray=SimpleNamespace(confirm=lambda:True,busy=lambda _:None,dispatch=lambda f:f(),restore=lambda:calls.append('restore'),error=lambda message:calls.append(message))
    controller=TrayController(window,tray,stopper)
    controller.request_exit();controller.worker.join(2)
    assert 'destroy' not in calls and 'restore' in calls
    assert not stopper.require_verified, 'a NapCat failure must not poison successful backend cleanup'
    controller.request_exit();controller.worker.join(2)
    assert calls[-1]=='destroy' and calls.count('napcat')==2


def test_no_installation_needs_no_process_stop(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    monkeypatch.setattr('app.services.bridge.find_installation',lambda root:None)
    monkeypatch.setattr('app.services.napcat_session.stop_napcat',lambda *a,**kw:pytest.fail('no installation'))
    control.stop_desktop_napcat(tmp_path)


def test_exit_does_not_change_login_policy_or_business_data(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    from app.services.napcat_session import SessionPolicy
    boot=install(tmp_path,monkeypatch);policy=SessionPolicy(tmp_path);policy.resume(123)
    business=tmp_path/'history.sqlite3';business.write_bytes(b'unchanged synthetic business data')
    original=policy.path.read_bytes();calls=[]
    monkeypatch.setattr('app.services.napcat_session.stop_napcat',lambda target,**kw:calls.append((target,kw)))
    monkeypatch.setattr('app.services.napcat_session.napcat_stopped',lambda target,**kw:True)
    control.stop_desktop_napcat(tmp_path)
    assert calls==[(boot,{'root':tmp_path})]
    assert policy.path.read_bytes()==original and business.read_bytes()==b'unchanged synthetic business data'


def test_still_running_is_failure_and_sensitive_details_are_hidden(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    install(tmp_path,monkeypatch)
    monkeypatch.setattr('app.services.napcat_session.stop_napcat',lambda *a,**kw:None)
    monkeypatch.setattr('app.services.napcat_session.napcat_stopped',lambda *a,**kw:False)
    with pytest.raises(RuntimeError,match='NapCat'):control.stop_desktop_napcat(tmp_path)
    def fail(*a,**kw):raise RuntimeError('private-token-do-not-echo')
    monkeypatch.setattr('app.services.napcat_session.stop_napcat',fail)
    with pytest.raises(RuntimeError) as result:control.stop_desktop_napcat(tmp_path)
    assert 'private-token' not in str(result.value)


def test_undiscovered_boot_is_not_silently_ignored(monkeypatch,tmp_path):
    import app.services.desktop_control as control
    boot=install(tmp_path,monkeypatch)
    monkeypatch.setattr('app.services.bridge.find_installation',lambda root:None)
    with pytest.raises(RuntimeError,match='NapCat'):control.stop_desktop_napcat(tmp_path)


def test_command_uses_supplied_install_root_for_exact_qq_path(tmp_path):
    from app.services.napcat_session import napcat_command
    from app.services.napcat_bundle import bundled_folder
    boot=bundled_folder(tmp_path)/'NapCatWinBootMain.exe'
    record=tmp_path/'NapCat/managed/config/launch.json';record.parent.mkdir(parents=True)
    qq=tmp_path/'runtime/qq-launch/client/QQ.exe'
    record.write_text(json.dumps({'qq_path':str(qq)}),encoding='utf-8')
    command=napcat_command(boot,root=tmp_path)
    assert command[-2:]==['-QQPath',str(qq)]


def test_confirmation_explains_full_exit():
    from scripts.desktop_tray import EXIT_MESSAGE
    assert 'NapCat 后台' in EXIT_MESSAGE
    assert 'NapCat 登录及' not in EXIT_MESSAGE


@pytest.mark.skipif(os.name!='nt',reason='Windows process ownership verification')
def test_native_processes_survive_hide_then_exit_releases_installation(tmp_path,monkeypatch):
    """Real OS processes, synthetic executables; never runs or stops a user's QQ."""
    from scripts.desktop_tray import TrayController
    import app.services.desktop_control as control
    from app.services.napcat_bundle import bundled_folder
    from app.services.napcat_session import SessionPolicy, napcat_stopped
    compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():pytest.skip('C# compiler unavailable for isolated native-process fixture')
    root=tmp_path/'拾序 with spaces';folder=bundled_folder(root);folder.mkdir(parents=True)
    source=tmp_path/'fixture.cs'
    source.write_text(r'''using System; using System.Diagnostics; using System.IO; using System.Threading;
class Fixture { static void Main(string[] args) {
 if(args[0]=="boot") { var p=new ProcessStartInfo(args[1],"worker \""+args[2]+"\""); p.UseShellExecute=false;p.CreateNoWindow=true;Process.Start(p); }
 else { File.WriteAllText(args[1],Process.GetCurrentProcess().Id.ToString()); }
 Thread.Sleep(120000); }}''',encoding='utf-8')
    boot=folder/'NapCatWinBootMain.exe'
    subprocess.run([str(compiler),'/nologo','/target:winexe','/out:'+str(boot),str(source)],capture_output=True,check=True,timeout=30)
    qq=folder/'QQ.exe';shutil.copyfile(boot,qq)
    unrelated=tmp_path/'unrelated/QQ.exe';unrelated.parent.mkdir();shutil.copyfile(boot,unrelated)
    for name in ['NapCatWinBootHook.dll','napcat.mjs','loadNapCat.js','qqnt.json']:(folder/name).touch()
    policy=SessionPolicy(root);policy.resume(123);original=policy.path.read_bytes()
    marker=tmp_path/'child.pid';other_marker=tmp_path/'unrelated.pid';calls=[]
    process=subprocess.Popen([str(boot),'boot',str(qq),str(marker)],creationflags=subprocess.CREATE_NO_WINDOW)
    other=subprocess.Popen([str(unrelated),'worker',str(other_marker)],creationflags=subprocess.CREATE_NO_WINDOW)
    child=None
    try:
        for _ in range(100):
            if marker.exists() and other_marker.exists():break
            time.sleep(.05)
        assert marker.exists() and other_marker.exists(),'synthetic processes started'
        kernel=control.kernel_api();child=kernel.OpenProcess(0x00100001,False,int(marker.read_text()))
        assert child
        monkeypatch.setattr(control,'stop_backend',lambda *a,**kw:calls.append('backend'))
        window=SimpleNamespace(destroy=lambda:calls.append('destroy'))
        tray=SimpleNamespace(ready=True,hide=lambda:calls.append('hide'),confirm=lambda:True,busy=lambda _:None,dispatch=lambda f:f(),restore=lambda:calls.append('restore'),error=lambda m:calls.append(('error',m)))
        controller=TrayController(window,tray,control.BackendStopper(root))
        assert controller.closing() is False
        assert calls==['hide'] and process.poll() is None and other.poll() is None
        assert kernel.WaitForSingleObject(child,0)==258,'child still active in tray'
        from tests.test_package_guard import guard
        probe=Path(__file__).resolve().parents[1]/'scripts/stop_napcat.ps1'
        assert guard.check_napcat(root,probe)=='running','installer sees active fixture before exit'
        controller.request_exit();controller.worker.join(55)
        assert not controller.worker.is_alive(),calls
        assert calls==['hide','backend','destroy'],calls
        assert process.wait(5) is not None and kernel.WaitForSingleObject(child,5000)==0
        assert other.poll() is None,'independent QQ-named process preserved'
        assert napcat_stopped(boot,root=root)
        assert guard.check_napcat(root,probe)=='stopped','installer no longer blocked by NapCat'
        assert policy.path.read_bytes()==original,'next startup preferences preserved'
        # Windows permits rename only after executable/module file handles are released.
        moved=folder.with_name(folder.name+'-released');folder.rename(moved);moved.rename(folder)
        # Retry with no surviving NapCat is idempotent.
        control.BackendStopper(root)()
        assert other.poll() is None
    finally:
        for item in [process,other]:
            if item.poll() is None:item.kill()
            item.wait(5)
        if child:
            if kernel.WaitForSingleObject(child,0)!=0:
                import ctypes
                from ctypes import wintypes
                kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
                kernel.TerminateProcess.restype=wintypes.BOOL
                kernel.TerminateProcess(child,1)
                kernel.WaitForSingleObject(child,5000)
            kernel.CloseHandle(child)


@pytest.mark.skipif(os.name!='nt',reason='Windows backend control events')
def test_real_backend_continues_when_hidden_then_exits_and_reopens_with_data(tmp_path,monkeypatch):
    import app.services.desktop_control as control
    from scripts.desktop_tray import TrayController
    from app.services.napcat_session import SessionPolicy
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    root=tmp_path/'isolated-app';root.mkdir()
    policy=SessionPolicy(root);policy.resume(123);original=policy.path.read_bytes()
    code='''import sys,threading,uvicorn
from pathlib import Path
from app.services.desktop_control import ControlSignals
from app.main import create_app
from app.config import Settings
root=Path(sys.argv[1])
with ControlSignals.create() as signals:
 app=create_app(Settings(),db_path=root/'data.sqlite3',config_path=root/'config.local.json')
 app.state.desktop_control={'pid':__import__('os').getpid(),'identity':signals.identity}
 server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=int(sys.argv[2]),log_level='error',lifespan='on'))
 def watch():
  while not signals.wait_stop(100):pass
  server.should_exit=True
 threading.Thread(target=watch,daemon=True).start()
 server.run()
 signals.finish(server.started and not server.lifespan.shutdown_failed and not server.lifespan.error_occurred)
'''
    base='http://127.0.0.1:'+str(port);calls=[]
    real_stop=control.stop_backend
    monkeypatch.setattr(control,'stop_backend',lambda root,**kw:real_stop(root,url=base,**kw))
    def launch():
        process=subprocess.Popen([sys.executable,'-B','-X','utf8','-c',code,str(root),str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            if process.poll() is not None:raise AssertionError('isolated backend exited: '+process.stderr.read().decode('utf-8','replace'))
            try:
                if httpx.get(base+'/api/health',trust_env=False,timeout=.2).is_success:return process
            except httpx.HTTPError:pass
            time.sleep(.05)
        process.kill();process.wait(5);raise AssertionError('isolated backend timeout')
    process=launch()
    try:
        with httpx.Client(base_url=base,trust_env=False) as client:
            created=client.post('/api/messages/manual',json={'raw_text':'保留退出测试数据','fields':{'title':'退出后仍保留的待办'}})
            assert created.is_success,created.text
            draft=created.json()['drafts'][0]
            confirmed=client.post('/api/drafts/'+draft['id']+'/confirm',json={'fields':draft['fields'],'confirmed':True})
            assert confirmed.is_success,confirmed.text
            task_id=confirmed.json()['id']
            window=SimpleNamespace(destroy=lambda:calls.append('destroy'))
            tray=SimpleNamespace(ready=True,hide=lambda:calls.append('hide'),confirm=lambda:True,busy=lambda _:None,dispatch=lambda f:f(),restore=lambda:calls.append('restore'),error=lambda m:calls.append(('error',m)))
            controller=TrayController(window,tray,control.BackendStopper(root))
            assert controller.closing() is False
            assert client.get('/api/health').is_success and process.poll() is None
            assert client.get('/api/tasks/'+task_id).is_success,'hidden backend still serves tasks'
            controller.request_exit();controller.worker.join(50)
            assert not controller.worker.is_alive() and calls==['hide','destroy'],calls
            assert process.wait(5)==0 and policy.path.read_bytes()==original
        process=launch()
        with httpx.Client(base_url=base,trust_env=False) as client:
            assert client.get('/api/tasks/'+task_id).json()['title']=='退出后仍保留的待办'
        control.BackendStopper(root)();assert process.wait(5)==0
    finally:
        if process.poll() is None:process.kill();process.wait(5)
