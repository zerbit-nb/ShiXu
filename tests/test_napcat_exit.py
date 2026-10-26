import asyncio
import json
import os
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import Mock
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_qq_login import service, upstream
from app.services.napcat_session import SessionPolicy, select_processes


def processes(folder):
    return [
        dict(pid=10, parent=1, path=str(folder/'NapCatWinBootMain.exe')),
        dict(pid=11, parent=10, path=str(folder/'QQ.exe')),
        dict(pid=12, parent=11, path=str(folder/'QQ.exe')),
        dict(pid=20, parent=1, path=str(folder.parent/'ordinary'/'QQ.exe')),
    ]


def test_process_selection_preserves_ordinary_qq(tmp_path):
    boot=tmp_path/'NapCat'/'NapCatWinBootMain.exe'
    rows=processes(boot.parent)+[dict(pid=13,parent=10,path=str(Path(os.environ.get('WINDIR','C:/Windows'))/'System32'/'conhost.exe'))]
    assert [p['pid'] for p in select_processes(boot,rows)]==[10,11,12]


def test_orphan_or_untrusted_descendant_refused(tmp_path):
    boot=tmp_path/'NapCat'/'NapCatWinBootMain.exe'
    rows=processes(boot.parent)
    with pytest.raises(RuntimeError):select_processes(boot,rows[1:])
    rows.append(dict(pid=30,parent=11,path=str(tmp_path/'other'/'QQ.exe')))
    with pytest.raises(RuntimeError):select_processes(boot,rows)


def test_policy_persists_and_does_not_change_config(tmp_path):
    policy=SessionPolicy(tmp_path)
    assert not policy.paused
    policy.write('exiting')
    assert SessionPolicy(tmp_path).paused
    policy.write('exit_failed')
    assert policy.paused
    policy.write('exited')
    policy.resume(123)
    assert not policy.paused and not policy.accepts(122) and policy.accepts(123)
    assert not (tmp_path/'qq.local.json').exists()


def test_exit_success_stays_stopped_on_reopen_and_resumes_explicitly(tmp_path,monkeypatch):
    login=service(tmp_path,upstream('online'))
    monkeypatch.setattr('app.services.qq_login.startup_lock',lambda p:nullcontext())
    stopped=[]
    monkeypatch.setattr('app.services.qq_login.stop_napcat',lambda boot:stopped.append(boot))
    def unavailable(request):raise httpx.ConnectError('unavailable',request=request)
    async def stop_check(url):return False
    monkeypatch.setattr(login,'management_alive',stop_check)
    result=asyncio.run(login.logout())
    assert result['state']=='exited' and not result['online'] and result['account_id']==''
    assert len(stopped)==1 and login.policy.paused
    login.bridge.transport=httpx.MockTransport(unavailable)
    assert asyncio.run(login.status('12345678'))['state']=='exited'
    reopened=type(login)(login.bridge)
    assert asyncio.run(reopened.status('12345678'))['state']=='exited'
    login.bridge.transport=httpx.MockTransport(upstream())
    checks=iter([False,True])
    async def alive(url):return next(checks)
    monkeypatch.setattr(login,'management_alive',alive)
    monkeypatch.setattr('app.services.qq_login.boot_is_running',lambda p:False)
    monkeypatch.setattr('app.services.qq_login.subprocess.Popen',lambda *a,**k:None)
    assert asyncio.run(login.start())['state']=='running'
    assert not login.policy.paused
    assert asyncio.run(login.status('12345678'))['state']=='waiting_qrcode'
    assert asyncio.run(login.password('12345678','test-only-password'))['state']=='submitted'


def test_exit_failure_never_claims_success_and_blocks_messages(tmp_path,monkeypatch):
    login=service(tmp_path,upstream('online'))
    monkeypatch.setattr('app.services.qq_login.startup_lock',lambda p:nullcontext())
    def fail(boot):raise RuntimeError('private process detail')
    monkeypatch.setattr('app.services.qq_login.stop_napcat',fail)
    with pytest.raises(Exception) as error:asyncio.run(login.logout())
    assert error.value.state=='exit_failed' and 'private process' not in str(error.value.message)
    assert login.policy.paused and asyncio.run(login.status(''))['state']=='exit_failed'
    with pytest.raises(Exception):asyncio.run(login.password('12345678','test-password'))


def test_management_port_still_alive_is_failure(tmp_path,monkeypatch):
    login=service(tmp_path,upstream('online'))
    monkeypatch.setattr('app.services.qq_login.startup_lock',lambda p:nullcontext())
    monkeypatch.setattr('app.services.qq_login.stop_napcat',lambda p:None)
    async def alive(url):return True
    monkeypatch.setattr(login,'management_alive',alive)
    with pytest.raises(Exception) as error:asyncio.run(login.logout())
    assert error.value.state=='exit_failed'


def test_exit_route_same_origin_and_business_data_unchanged(tmp_path,monkeypatch):
    app=create_app(config_path=tmp_path/'config.json',db_path=tmp_path/'test.sqlite')
    with TestClient(app) as client:
        app.state.qq_login=service(tmp_path,upstream('online'))
        monkeypatch.setattr('app.services.qq_login.startup_lock',lambda p:nullcontext())
        monkeypatch.setattr('app.services.qq_login.stop_napcat',lambda p:None)
        async def alive(url):return False
        monkeypatch.setattr(app.state.qq_login,'management_alive',alive)
        sample=client.post('/api/messages/manual',json={'source':'manual','raw_text':'Preserve this notification'}).json()
        draft=sample['drafts'][0]
        client.post('/api/drafts/'+draft['id']+'/confirm',json={'confirmed':True,'duplicate_reviewed':True,'fields':draft['fields']})
        before=client.get('/api/tasks').json()
        assert client.post('/api/qq/login/logout').status_code==403
        response=client.post('/api/qq/login/logout',headers={'Origin':'http://testserver'})
        assert response.status_code==200 and response.json()['state']=='exited'
        assert response.headers['cache-control']=='no-store'
        assert client.get('/api/tasks').json()==before
        assert client.get('/api/messages/'+sample['message']['id']).status_code==200
        assert client.post('/api/qq/events',content=b'{}').status_code==403


def test_desktop_does_not_restart_exited_napcat(tmp_path,monkeypatch):
    import scripts.desktop as desktop
    SessionPolicy(tmp_path).write('exited')
    monkeypatch.setattr(desktop,'ROOT',tmp_path)
    monkeypatch.setattr(desktop,'startup_lock',lambda folder:nullcontext())
    monkeypatch.setattr(desktop,'server_state',lambda *args:'ready')
    monkeypatch.setattr(desktop,'find_installation',lambda *args:pytest.fail('must not autostart NapCat'))
    monkeypatch.setattr(desktop.sys,'argv',['desktop.py','--no-browser'])
    desktop.main()


def test_old_signed_events_are_not_restored_after_new_connection(tmp_path):
    from tests.test_qq import configure,send,event
    app=create_app(config_path=tmp_path/'config.json',db_path=tmp_path/'test.sqlite')
    with TestClient(app) as client:
        configure(client)
        policy=app.state.qq_login.policy
        policy.write('exited')
        assert send(client).status_code==403
        policy.resume(1791763300)
        assert send(client,event(time=1791763200)).status_code==204
        assert client.get('/api/qq/inbox').json()['messages']==[]
        assert send(client,event(time=1791763300)).status_code==204
        assert len(client.get('/api/qq/inbox').json()['messages'])==1
