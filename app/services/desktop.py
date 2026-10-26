"""Desktop startup helpers; only starts executables in the local installation."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import socket
from urllib.parse import urlparse
import httpx

def server_state(root, url, client):
    try:
        response = client.get(url+'/api/health')
        if response.status_code != 200: return 'occupied'
        data = response.json()
        expected = hashlib.sha256(str((Path(root)/'config.local.json').resolve()).encode()).hexdigest()
        if data.get('application') == 'CampusFlow' and data.get('instance') == expected:
            return 'ready'
        if data.get('version') == '0.4.0' and data.get('timezone') == 'Asia/Shanghai':
            return 'upgrade'
        return 'occupied'
    except httpx.ConnectTimeout:
        endpoint = urlparse(url)
        try:
            with socket.create_connection((endpoint.hostname, endpoint.port or 80),timeout=3):
                return 'occupied'
        except ConnectionRefusedError:
            return 'stopped'
        except OSError:
            return 'occupied'
    except httpx.ConnectError:
        return 'stopped'
    except (httpx.HTTPError, ValueError, AttributeError):
        return 'occupied'

def boot_is_running(boot, executable_paths=None):
    if executable_paths is None:
        if os.name != 'nt': raise RuntimeError('统一启动目前支持 Windows。')
        output = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process -Filter \"Name='NapCatWinBootMain.exe'\" | Select-Object -ExpandProperty ExecutablePath) | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        executable_paths = json.loads(output.stdout.strip() or '[]')
        if isinstance(executable_paths,str): executable_paths=[executable_paths]
    return any(p and Path(p).resolve()==Path(boot).resolve() for p in executable_paths)

def start_hidden(command, cwd, log_path):
    with Path(log_path).open('ab') as log:
        return subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0, close_fds=True)


@contextmanager
def startup_lock(folder):
    import msvcrt
    folder.mkdir(exist_ok=True)
    with (folder/'startup.lock').open('a+b') as handle:
        handle.seek(0); handle.write(b'1'); handle.flush(); handle.seek(0)
        try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise RuntimeError('另一个启动器正在运行，请稍后再打开。')
        try: yield
        finally: handle.seek(0); msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
