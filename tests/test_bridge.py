import asyncio
from pathlib import Path
import pytest
import httpx
from app.services.bridge import find_installation, inspect_bridge

def install(root):
 p=root/'NapCat'/'installed'; (p/'resources/app/napcat/config').mkdir(parents=True)
 (p/'NapCatWinBootMain.exe').touch()
 config=p/'resources/app/napcat/config'
 (config/'webui.json').write_text('{"port":6099,"token":"secret-management-key"}',encoding='utf-8')
 return p

def test_discovery_and_ambiguous_installations(tmp_path):
 assert find_installation(tmp_path) is None
 p=install(tmp_path); assert find_installation(tmp_path).boot==p/'NapCatWinBootMain.exe'
 other=tmp_path/'NapCat'/'other'; (other/'resources/app/napcat/config').mkdir(parents=True); (other/'NapCatWinBootMain.exe').touch()
 (other/'resources/app/napcat/config/webui.json').write_text('{}')
 with pytest.raises(ValueError): find_installation(tmp_path)

@pytest.mark.parametrize('mode,expected',[('online','ready'),('offline','qq_offline'),('mismatch','account_mismatch'),('token','report_mismatch'),('disabled','report_disabled'),('auth','auth_failed')])
def test_diagnostics_and_secret_redaction(tmp_path,mode,expected):
 install(tmp_path)
 def handler(r):
  if r.url.path.endswith('/auth/login'):return httpx.Response(200,json={'code':0,'data':{'Credential':'private-credential'}})
  assert r.headers['Authorization']=='Bearer private-credential'
  if mode=='auth': return httpx.Response(200,json={'code':-1,'message':'secret-management-key'})
  if r.url.path.endswith('CheckLoginStatus'):data={'isLogin':mode!='offline'}
  elif r.url.path.endswith('GetQQLoginInfo'):data={'uin':'99999' if mode=='mismatch' else '12345678'}
  else:data={'network':{'httpClients':[{'enable':mode!='disabled','url':'http://127.0.0.1:8000/api/qq/events','messagePostFormat':'array','token':'wrong' if mode=='token' else 'shared-report-token'}]}}
  return httpx.Response(200,json={'code':0,'data':data})
 result=asyncio.run(inspect_bridge(tmp_path,'12345678','shared-report-token',httpx.MockTransport(handler)))
 assert result['state']==expected
 assert all(key not in str(result) for key in ['secret-management-key','private-credential','shared-report-token'])

def test_unavailable_and_invalid_port(tmp_path):
 assert (asyncio.run(inspect_bridge(tmp_path,'12345678','x')))['state']=='not_installed'
 p=install(tmp_path)
 def fail(r):raise httpx.ConnectError('secret transport error',request=r)
 assert (asyncio.run(inspect_bridge(tmp_path,'12345678','x',httpx.MockTransport(fail))))['state']=='not_running'
 (p/'resources/app/napcat/config/webui.json').write_text('{"port":"https://bad.example","token":"x"}')
 assert (asyncio.run(inspect_bridge(tmp_path,'12345678','x')))['state']=='config_error'
