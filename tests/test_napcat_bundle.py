import json
from pathlib import Path
from app.services.bridge import Installation
from app.services.napcat_bundle import initialize

def test_generated_config_is_private_and_preserved(tmp_path):
    a = Installation(tmp_path/'vendor'/'NapCatWinBootMain.exe', tmp_path/'user'/'config', True)
    initialize(a)
    first = (a.config/'webui.json').read_bytes()
    data = json.loads(first)
    assert data['host']=='127.0.0.1' and len(data['token'])==64
    assert data['autoLoginAccount']==''
    initialize(a)
    assert (a.config/'webui.json').read_bytes()==first
    b = Installation(tmp_path/'vendor2'/'NapCatWinBootMain.exe', tmp_path/'user2'/'config', True)
    initialize(b)
    assert json.loads((b.config/'webui.json').read_text())['token']!=data['token']

def test_legacy_initialization_has_no_side_effects(tmp_path):
    initialize(Installation(tmp_path/'boot',tmp_path/'config'))
    assert not (tmp_path/'config').exists()

def test_managed_discovery_and_legacy_precedence(tmp_path):
    from app.services.bridge import find_installation
    from app.services.napcat_bundle import bundled_folder
    folder=bundled_folder(tmp_path);folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe','NapCatWinBootHook.dll','napcat.mjs','loadNapCat.js','qqnt.json'):
        (folder/name).touch()
    assert find_installation(tmp_path).managed
    from tests.test_bridge import install
    old=install(tmp_path)
    assert find_installation(tmp_path).boot==old/'NapCatWinBootMain.exe'
    assert not find_installation(tmp_path).managed

def test_external_qq_exit_selection_is_descendant_only(tmp_path):
    import pytest
    from app.services.napcat_session import select_processes
    boot=tmp_path/'vendor'/'NapCatWinBootMain.exe'
    qq=tmp_path/'official'/'QQ.exe'
    rows=[dict(pid=1,parent=0,path=str(boot)),dict(pid=2,parent=1,path=str(qq)),
          dict(pid=3,parent=0,path=str(qq))]
    assert [p['pid'] for p in select_processes(boot,rows,qq)]==[1,2]
    with pytest.raises(RuntimeError):select_processes(boot,rows)

def test_managed_reporting_only_changes_owned_client(tmp_path):
    import asyncio,httpx
    from app.services.bridge import BridgeMonitor,find_installation
    from app.services.napcat_bundle import bundled_folder
    folder=bundled_folder(tmp_path);folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe','NapCatWinBootHook.dll','napcat.mjs','loadNapCat.js','qqnt.json'):
        (folder/name).touch()
    initialize(find_installation(tmp_path))
    unrelated={'name':'Other tool','url':'http://127.0.0.1:9999'}
    applied=[]
    config={'network':{'httpClients':[unrelated]}}
    def handler(r):
        nonlocal config
        route=r.url.path.rsplit('/',1)[-1]
        if route=='login':data={'Credential':'private-credential'}
        elif route=='CheckLoginStatus':data={'isLogin':True}
        elif route=='GetQQLoginInfo':data={'uin':'12345678'}
        elif route=='GetConfig':data=config
        elif route=='SetConfig':
            config=json.loads(json.loads(r.content)['config']);applied.append(config);data=None
        else:raise AssertionError(route)
        return httpx.Response(200,json={'code':0,'data':data})
    bridge=BridgeMonitor(tmp_path,httpx.MockTransport(handler))
    status=asyncio.run(bridge.inspect('12345678','secret-report-token',configure=True))
    assert status['state']=='ready'
    assert applied[0]['network']['httpClients'][0]==unrelated
    target=applied[0]['network']['httpClients'][1]
    assert target['name']=='Shixu' and target['token']=='secret-report-token'
    assert 'secret-report-token' not in str(status)

def test_uninstall_path_handles_arguments_and_spaces():
    from app.services.napcat_bundle import uninstall_executable
    assert uninstall_executable(chr(34)+'C:/Program Files/QQ/Uninstall.exe'+chr(34)+' /S')==Path('C:/Program Files/QQ/Uninstall.exe')
    assert uninstall_executable('E:/QQ App/Uninstall.exe /S')==Path('E:/QQ App/Uninstall.exe')
    assert uninstall_executable('invalid') is None

def test_qq_detection_requires_signature_and_isolates_modules(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import app.services.napcat_bundle as bundle
    qq=tmp_path/'QQ.exe';qq.touch()
    monkeypatch.setattr(bundle,'qq_candidates',lambda:iter([qq]))
    monkeypatch.setenv('PSModulePath','incompatible-powershell-modules')
    calls=[]
    def verify(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(bundle.subprocess,'run',verify)
    assert bundle.find_qq()==qq.resolve()
    assert all(k.lower()!='psmodulepath' for k in calls[0][1]['env'])
    monkeypatch.setattr(bundle.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    import pytest
    with pytest.raises(ValueError,match='im.qq.com'):bundle.find_qq()

def test_missing_qq_login_start_has_actionable_failure(tmp_path, monkeypatch):
    import asyncio,httpx,pytest
    from contextlib import nullcontext
    from app.services.bridge import BridgeMonitor
    from app.services.qq_login import QQLogin,LoginError
    from app.services.napcat_bundle import bundled_folder
    folder=bundled_folder(tmp_path);folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe','NapCatWinBootHook.dll','napcat.mjs','loadNapCat.js','qqnt.json'):(folder/name).touch()
    login=QQLogin(BridgeMonitor(tmp_path))
    async def offline(url):return False
    monkeypatch.setattr(login,'management_alive',offline)
    monkeypatch.setattr('app.services.qq_login.startup_lock',lambda p:nullcontext())
    monkeypatch.setattr('app.services.qq_login.boot_is_running',lambda p:False)
    def missing(install):raise ValueError('请从 im.qq.com 安装官方 QQ')
    monkeypatch.setattr('app.services.qq_login.launch',missing)
    with pytest.raises(LoginError) as error:asyncio.run(login.start())
    assert error.value.state=='start_failed' and 'im.qq.com' in error.value.message


def test_stopped_probe_rejects_active_and_failed_checks(monkeypatch):
    from types import SimpleNamespace
    import app.services.napcat_session as session
    calls=[]
    monkeypatch.setattr(session,'napcat_command',lambda boot:['powershell.exe','probe.ps1'])
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=3)
    monkeypatch.setattr(session.subprocess,'run',run)
    assert not session.napcat_stopped(Path('boot'))
    assert calls[0][-2:]==['-CheckOnly','-RequireStopped']
    monkeypatch.setattr(session.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    assert not session.napcat_stopped(Path('boot'))
    monkeypatch.setattr(session.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    assert session.napcat_stopped(Path('boot'))


def test_launch_entry_resolves_outside_qq_app_directory(tmp_path, monkeypatch):
    import shutil,subprocess
    from types import SimpleNamespace
    import app.services.napcat_bundle as bundle
    folder=tmp_path/'Shixu 中文 App'/'third_party'/'napcat'/bundle.VERSION
    folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe','NapCatWinBootHook.dll','loadNapCat.js','napcat.mjs'):
        (folder/name).write_text('',encoding='utf-8')
    (folder/'qqnt.json').write_text(json.dumps({'name':'qq-chat','main':'./loadNapCat.js','version':'9.9.22'}))
    qq=tmp_path/'QQ'/'QQ.exe';qq.parent.mkdir();qq.touch()
    qq_app=qq.parent/'versions'/'9.9.26-44725'/'resources'/'app';qq_app.mkdir(parents=True)
    original=qq_app/'package.json';original.write_text('{"main":"original.js"}')
    (qq.parent/'versions/config.json').write_text(json.dumps({'curVersion':'9.9.26-44725'}))
    install=Installation(folder/'NapCatWinBootMain.exe',tmp_path/'user'/'config',True)
    monkeypatch.setattr(bundle,'find_qq',lambda:qq)
    calls=[]
    with monkeypatch.context() as launch_mock:
        launch_mock.setattr(bundle.subprocess,'Popen',lambda cmd,**kw:calls.append((cmd,kw)) or SimpleNamespace())
        bundle.launch(install)
    env=calls[0][1]['env']
    patch=Path(env['NAPCAT_PATCH_PACKAGE'])
    assert patch!=folder/'qqnt.json'
    main=json.loads(patch.read_text(encoding='utf-8'))['main']
    assert not Path(main).is_absolute()
    entry=(qq_app/main).resolve()
    assert entry.suffix=='.cjs' and entry.is_file()
    assert json.loads((folder/'qqnt.json').read_text())['main']=='./loadNapCat.js'
    assert original.read_text()=='{"main":"original.js"}'
    # Reproduce Electron/Node resolution before the hook's CreateFileW read.
    if shutil.which('node'):
        result=subprocess.run(['node','-e',"const path=require('path');process.stdout.write(require.resolve(path.join(process.argv[1],process.argv[2])))",str(qq_app),main],capture_output=True,text=True,encoding='utf-8',check=True)
        assert Path(result.stdout)==entry
        # The vendor is type=module; importing its CommonJS .js entry fails.
        # Actually execute our entry from a .cjs caller, not node -e (which
        # supplies a global require and can hide this problem).
        (folder/'package.json').write_text('{"type":"module"}')
        marker=tmp_path/'engine-loaded'
        (folder/'napcat.mjs').write_text('import fs from "node:fs";fs.writeFileSync('+json.dumps(str(marker))+',"ok");')
        caller=tmp_path/'caller.cjs'
        caller.write_text('require('+json.dumps(str(entry))+');')
        subprocess.run(['node',str(caller)],env=env,capture_output=True,check=True)
        assert marker.read_text()=='ok'


def test_diagnostic_works_with_preview3_bundle_module(tmp_path,monkeypatch):
    import scripts.diagnose_qq as diagnostic
    import app.services.napcat_bundle as bundle
    monkeypatch.delattr(bundle,'qq_app_relative')
    monkeypatch.setattr(bundle,'qq_candidates',lambda:iter([]))
    monkeypatch.setattr(bundle,'find_qq',lambda:(_ for _ in ()).throw(ValueError()))
    report=diagnostic.collect(tmp_path)
    assert report['qq']['signed_official_found'] is False


def test_cross_drive_qq_alias_validates_existing_mapping(tmp_path):
    import app.services.napcat_bundle as bundle
    import pytest
    qq=tmp_path/'QQ'/'QQ.exe';qq.parent.mkdir();qq.touch()
    config=tmp_path/'NapCat/managed/config';config.mkdir(parents=True)
    import hashlib,os
    name=hashlib.sha256(os.path.normcase(str(qq.parent.resolve())).encode()).hexdigest()[:16]
    # Never repurpose a real directory or an unrelated reparse point.
    aliases=tmp_path/'runtime/qq-launch';aliases.mkdir(parents=True)
    (aliases/('qq-client-'+name)).mkdir()
    install=Installation(tmp_path/'boot',config,True)
    with pytest.raises(ValueError,match='映射'):bundle.qq_launch_alias(install,qq)


def test_cross_drive_launch_records_mapped_executable_for_scoped_exit(tmp_path,monkeypatch):
    import app.services.napcat_bundle as bundle
    from types import SimpleNamespace
    folder=tmp_path/'vendor';folder.mkdir()
    for name in ('NapCatWinBootMain.exe','NapCatWinBootHook.dll','loadNapCat.js','napcat.mjs','qqnt.json'):(folder/name).touch()
    qq=tmp_path/'official/QQ.exe';qq.parent.mkdir();qq.touch()
    app=qq.parent/'resources/app';app.mkdir(parents=True);(app/'package.json').write_text('{}')
    alias=tmp_path/'mapped/QQ.exe'
    install=Installation(folder/'NapCatWinBootMain.exe',tmp_path/'user/config',True)
    monkeypatch.setattr(bundle,'find_qq',lambda:qq)
    monkeypatch.setattr(bundle,'qq_launch_alias',lambda i,q:alias)
    original=bundle.os.path.relpath
    def relative(path,base):
        if base==app:raise ValueError('different drives')
        return original(path,base)
    monkeypatch.setattr(bundle.os.path,'relpath',relative)
    calls=[]
    monkeypatch.setattr(bundle.subprocess,'Popen',lambda cmd,**kw:calls.append(cmd) or SimpleNamespace())
    bundle.launch(install)
    assert calls[0][1]==str(alias)
    assert json.loads((install.config/'launch.json').read_text())['qq_path']==str(alias)


def test_launch_rejects_missing_loader_before_starting_qq(tmp_path,monkeypatch):
    import pytest
    import app.services.napcat_bundle as bundle
    folder=tmp_path/'vendor';folder.mkdir()
    install=Installation(folder/'NapCatWinBootMain.exe',tmp_path/'user'/'config',True)
    monkeypatch.setattr(bundle,'find_qq',lambda:tmp_path/'QQ.exe')
    monkeypatch.setattr(bundle.subprocess,'Popen',lambda *a,**kw:pytest.fail('must not start incomplete engine'))
    with pytest.raises(ValueError,match='NapCat'):
        bundle.launch(install)


def test_managed_start_reports_launcher_failure_and_preserves_reason(tmp_path,monkeypatch):
    import asyncio,httpx,pytest
    from contextlib import nullcontext
    from types import SimpleNamespace
    from app.services.bridge import BridgeMonitor,find_installation
    from app.services.qq_login import QQLogin,LoginError
    from app.services.napcat_bundle import bundled_folder,startup_failed
    folder=bundled_folder(tmp_path);folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe','NapCatWinBootHook.dll','napcat.mjs','loadNapCat.js','qqnt.json'):(folder/name).touch()
    def unavailable(request):raise httpx.ConnectError('private-path-and-token',request=request)
    login=QQLogin(BridgeMonitor(tmp_path,httpx.MockTransport(unavailable)))
    async def offline(url):return False
    monkeypatch.setattr(login,'management_alive',offline)
    monkeypatch.setattr('app.services.qq_login.startup_lock',lambda p:nullcontext())
    monkeypatch.setattr('app.services.qq_login.boot_is_running',lambda p:False)
    monkeypatch.setattr('app.services.qq_login.launch',lambda p:SimpleNamespace(poll=lambda:7,returncode=7))
    with pytest.raises(LoginError) as error:asyncio.run(login.start())
    assert error.value.state=='start_failed' and 'DiagnoseQQ.cmd' in error.value.message
    assert startup_failed(find_installation(tmp_path))
    with pytest.raises(LoginError) as error:asyncio.run(login.status(''))
    assert error.value.state=='start_failed' and 'private-path' not in error.value.message


def test_qq_diagnostic_does_not_disclose_login_or_raw_paths(tmp_path,monkeypatch):
    import scripts.diagnose_qq as diagnostic
    import app.services.napcat_bundle as bundle
    folder=bundle.bundled_folder(tmp_path);folder.mkdir(parents=True)
    for name in ('NapCatWinBootMain.exe','NapCatWinBootHook.dll','napcat.mjs','loadNapCat.js','qqnt.json'):(folder/name).touch()
    config=tmp_path/'NapCat/managed/config';config.mkdir(parents=True)
    secret='secret-auth-token-do-not-share'
    (config/'webui.json').write_text(json.dumps({'token':secret,'port':0,'autoLoginAccount':'12345678'}))
    (config.parent/'start-status.json').write_text(json.dumps({'state':'launcher_exited','exit_code':7,'raw':secret}))
    monkeypatch.setattr(bundle,'qq_candidates',lambda:iter([]))
    def missing():raise ValueError(secret)
    monkeypatch.setattr(bundle,'find_qq',missing)
    before=(config/'webui.json').read_bytes()
    report=diagnostic.collect(tmp_path)
    text=json.dumps(report)
    assert secret not in text and '12345678' not in text and str(tmp_path) not in text
    assert report['installation']=='bundled' and not report['relative_entry_correct']
    assert report['last_start']=={'state':'launcher_exited','exit_code':7}
    assert (config/'webui.json').read_bytes()==before


def test_active_qq_version_ignores_pending_updates_and_rejects_traversal(tmp_path):
    import pytest
    from app.services.napcat_bundle import qq_app_relative
    qq=tmp_path/'QQ.exe'
    app=tmp_path/'versions/9.9.15-27597/resources/app';app.mkdir(parents=True)
    (app/'package.json').write_text('{}')
    config=tmp_path/'versions/config.json'
    config.write_text(json.dumps({'curVersion':'9.9.15-27597','readyVersion':'9.9.28-46928'}))
    assert qq_app_relative(qq)==app.relative_to(tmp_path)
    config.write_text(json.dumps({'curVersion':'../../outside'}))
    with pytest.raises(ValueError):qq_app_relative(qq)
