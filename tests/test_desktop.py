import hashlib
from pathlib import Path
import httpx
from app.services.desktop import server_state, boot_is_running

def test_server_identity_and_port_conflict(tmp_path):
 expected=hashlib.sha256(str((tmp_path/'config.local.json').resolve()).encode()).hexdigest()
 def check(body):
  with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=body))) as c:
   return server_state(tmp_path,'http://127.0.0.1:8000',c)
 assert check({'application':'CampusFlow','instance':expected})=='ready'
 assert check({'application':'CampusFlow','instance':'other'})=='occupied'
 assert check({'version':'0.4.0','timezone':'Asia/Shanghai'})=='upgrade'
 assert check({'application':'unrelated'})=='occupied'

def test_boot_process_matching(tmp_path):
 boot=tmp_path/'NapCatWinBootMain.exe'
 assert boot_is_running(boot,[str(boot)])
 assert not boot_is_running(boot,[str(tmp_path/'other'/'NapCatWinBootMain.exe')])
from types import SimpleNamespace
from contextlib import nullcontext
import pytest

@pytest.mark.parametrize('state,starts',[('stopped',1),('ready',0)])
def test_desktop_reuses_or_starts_service(tmp_path,monkeypatch,state,starts):
 import scripts.desktop as desktop
 monkeypatch.setattr(desktop,'ROOT',tmp_path)
 monkeypatch.setattr(desktop,'startup_lock',lambda folder:nullcontext())
 monkeypatch.setattr(desktop,'find_installation',lambda root:None)
 values=iter([state,'ready'])
 monkeypatch.setattr(desktop,'server_state',lambda *args:next(values))
 calls=[]
 monkeypatch.setattr(desktop,'start_hidden',lambda *args:calls.append(args) or SimpleNamespace(poll=lambda:None))
 monkeypatch.setattr(desktop.sys,'argv',['desktop.py','--no-browser'])
 desktop.main()
 assert len(calls)==starts

@pytest.mark.parametrize('state',['occupied','upgrade'])
def test_desktop_refuses_port_conflict(tmp_path,monkeypatch,state):
 import scripts.desktop as desktop
 monkeypatch.setattr(desktop,'ROOT',tmp_path)
 monkeypatch.setattr(desktop,'startup_lock',lambda folder:nullcontext())
 monkeypatch.setattr(desktop,'server_state',lambda *args:state)
 monkeypatch.setattr(desktop,'start_hidden',lambda *args:pytest.fail('must not start'))
 monkeypatch.setattr(desktop.sys,'argv',['desktop.py','--no-browser'])
 with pytest.raises(RuntimeError): desktop.main()

@pytest.mark.parametrize('running,alive,starts',[(True,False,0),(False,True,0),(False,False,1)])
def test_desktop_does_not_duplicate_napcat(tmp_path,monkeypatch,running,alive,starts):
 import scripts.desktop as desktop
 from app.services.bridge import Installation
 folder=tmp_path/'napcat';folder.mkdir();(folder/'webui.json').write_text('{"port":6099}')
 monkeypatch.setattr(desktop,'ROOT',tmp_path)
 monkeypatch.setattr(desktop,'startup_lock',lambda folder:nullcontext())
 monkeypatch.setattr(desktop,'server_state',lambda *args:'ready')
 monkeypatch.setattr(desktop,'find_installation',lambda root:Installation(folder/'boot.exe',folder))
 monkeypatch.setattr(desktop,'boot_is_running',lambda boot:running)
 calls=[]
 monkeypatch.setattr(desktop,'start_hidden',lambda *args:calls.append(args))
 class Client:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def get(self,*args):return SimpleNamespace(status_code=200 if alive or calls else 503)
 monkeypatch.setattr(desktop.httpx,'Client',lambda **kwargs:Client())
 async def inspect(*args):return {'label':'test','hint':'test','state':'ready'}
 monkeypatch.setattr(desktop.BridgeMonitor,'inspect',inspect)
 monkeypatch.setattr(desktop.sys,'argv',['desktop.py','--no-browser'])
 desktop.main()
 assert len(calls)==starts

def test_connect_timeout_distinguishes_refused_port(tmp_path,monkeypatch):
 import socket
 import app.services.desktop as desktop
 def fail(r):raise httpx.ConnectTimeout('timeout',request=r)
 def refused(*args,**kwargs):raise ConnectionRefusedError()
 monkeypatch.setattr(desktop.socket,'create_connection',refused)
 with httpx.Client(transport=httpx.MockTransport(fail)) as client:
  assert server_state(tmp_path,'http://127.0.0.1:8000',client)=='stopped'
 monkeypatch.setattr(desktop.socket,'create_connection',lambda *args,**kwargs:nullcontext())
 with httpx.Client(transport=httpx.MockTransport(fail)) as client:
  assert server_state(tmp_path,'http://127.0.0.1:8000',client)=='occupied'


def test_check_only_never_starts_process(tmp_path,monkeypatch):
 import scripts.desktop as desktop
 monkeypatch.setattr(desktop,'ROOT',tmp_path)
 monkeypatch.setattr(desktop,'startup_lock',lambda folder:nullcontext())
 monkeypatch.setattr(desktop,'find_installation',lambda root:None)
 monkeypatch.setattr(desktop,'server_state',lambda *args:'stopped')
 monkeypatch.setattr(desktop,'start_hidden',lambda *args:pytest.fail('must not start'))
 monkeypatch.setattr(desktop.sys,'argv',['desktop.py','--check-only','--no-browser'])
 desktop.main()

@pytest.mark.parametrize('fault',['discovery','invalid_json','bad_port'])
def test_bridge_configuration_failure_still_opens_app(tmp_path,monkeypatch,fault):
 import scripts.desktop as desktop
 from app.services.bridge import Installation
 monkeypatch.setattr(desktop,'ROOT',tmp_path)
 monkeypatch.setattr(desktop,'startup_lock',lambda folder:nullcontext())
 monkeypatch.setattr(desktop,'server_state',lambda *args:'ready')
 if fault=='discovery':
  def discover(root):raise ValueError('ambiguous installation')
  monkeypatch.setattr(desktop,'find_installation',discover)
 else:
  (tmp_path/'webui.json').write_text('invalid' if fault=='invalid_json' else '{"port":0}')
  monkeypatch.setattr(desktop,'find_installation',lambda root:Installation(tmp_path/'boot.exe',tmp_path))
 opened=[]
 monkeypatch.setattr(desktop.webbrowser,'open',lambda url:opened.append(url))
 monkeypatch.setattr(desktop.sys,'argv',['desktop.py'])
 desktop.main()
 assert opened==['http://127.0.0.1:8000']
