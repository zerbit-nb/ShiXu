"""Read-only, shareable diagnostics; never extracts keys or reads chat messages."""
import argparse
import contextlib
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone

STATES={'paused','starting','listening','waiting','stopping','error','unknown'}
STAGES={'load','connect','query','ack','spawn','read_frame','handle_frame'}
TYPES={'ValueError','TypeError','RuntimeError','PermissionError','FileNotFoundError','KeyError','AttributeError','ImportError','OSError','BrokenPipeError','ConnectionResetError','TimeoutError','JSONDecodeError','OperationalError','DatabaseError','MonitorError','SourceError'}


def status_summary(value, reasons):
    if not isinstance(value,dict):return {'available':False,'error':'invalid_status'}
    diagnostic=value.get('diagnostic')
    safe={}
    if isinstance(diagnostic,dict):
        if diagnostic.get('stage') in STAGES:safe['stage']=diagnostic['stage']
        if diagnostic.get('type') in TYPES:safe['type']=diagnostic['type']
    return {'available':True,'state':value.get('state') if value.get('state') in STATES else 'unknown',
            'reason':value.get('reason') if value.get('reason') in reasons else None,'diagnostic':safe}


def process_summary():
    if os.name!='nt':return {'available':False,'error':'windows_required'}
    # Report version numbers and access counts only, never paths, names or PIDs.
    command="[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process -Filter \"Name='Weixin.exe' OR Name='WeChat.exe'\" | ForEach-Object { $v=''; if ($_.ExecutablePath) { $v=[System.Diagnostics.FileVersionInfo]::GetVersionInfo($_.ExecutablePath).FileVersion }; [pscustomobject]@{pid=$_.ProcessId;version=$v} }) | ConvertTo-Json -Compress"
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:return {'available':False,'error':'process_query_failed'}
        rows=json.loads(result.stdout.strip() or '[]')
        if isinstance(rows,dict):rows=[rows]
        if not isinstance(rows,list):raise ValueError()
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        readable=0;versions=set()
        for row in rows[:64]:
            version=row.get('version','')
            if isinstance(version,str) and re.fullmatch(r'[0-9]+(?:[.][0-9]+){1,3}',version.strip()):versions.add(version.strip())
            pid=row.get('pid')
            if type(pid) is int and pid>0:
                handle=kernel.OpenProcess(0x0410,False,pid)
                if handle:readable+=1;kernel.CloseHandle(handle)
        return {'available':True,'count':len(rows),'versions':sorted(versions),'read_access_count':readable,
                'note':'Read access alone does not prove database compatibility.'}
    except Exception:return {'available':False,'error':'process_query_failed'}


def collect(root):
    root=Path(root).resolve()
    sys.path.insert(0,str(root))
    report={'format_version':1,'created_at':datetime.now(timezone.utc).isoformat(),'platform':platform.system(),
            'windows_version':platform.version(),'python_version':platform.python_version(),'python_bits':64 if sys.maxsize>2**32 else 32,
            'privacy':'No account/group names, file paths, messages, keys, tokens or raw exceptions included.'}
    dependencies={}
    for name,module in [('cryptography','cryptography.hazmat.primitives.ciphers'),('zstandard','zstandard'),('cffi','_cffi_backend')]:
        try:
            importlib.import_module(module)
            dependencies[name]={'available':True,'version':importlib.metadata.version(name)}
        except Exception:dependencies[name]={'available':False}
    report['dependencies']=dependencies
    report['wechat_process']=process_summary()
    try:
        from app.services.wechat_monitor import MESSAGES
        import httpx
        try:
            with httpx.Client(trust_env=False,timeout=5) as client:
                response=client.get('http://127.0.0.1:8000/api/health');response.raise_for_status();health=response.json()
                expected=hashlib.sha256(str(root/'config.local.json').encode()).hexdigest()
                if health.get('application')!='CampusFlow' or health.get('instance')!=expected:
                    report['receiver']={'available':False,'error':'different_installation'}
                else:
                    response=client.get('http://127.0.0.1:8000/api/wechat/status');response.raise_for_status()
                    report['receiver']=status_summary(response.json(),MESSAGES)
        except Exception:report['receiver']={'available':False,'error':'app_not_reachable'}
    except Exception:report['receiver']={'available':False,'error':'runtime_import_failed'}
    try:
        from app.services.wechat_reader import load_module
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            module,_=load_module()
            location=module.auto_detect_db_dir()
            count=len(module._find_account_dirs(location)) if location else 0
        report['source']={'module_valid':True,'data_root_found':bool(location),'account_directory_count':count}
    except Exception:report['source']={'module_valid':False,'error':'source_or_discovery_failed'}
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    root=Path(args.root).resolve()
    if not (root/'app/services/wechat_reader.py').is_file():raise SystemExit('Application directory not found.')
    report=collect(root)
    output=Path(args.output)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('Diagnostic report saved. No chat messages or credentials were collected.')

if __name__=='__main__':main()
