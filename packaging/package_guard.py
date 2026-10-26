"""Fail closed if this installed desktop window or its backend is still running."""
import ctypes
from ctypes import wintypes
import hashlib
from pathlib import Path
import sys
import json
import os
import subprocess
import argparse


def check_napcat(root, probe):
    """Inspect with this release's read-only probe, never import old application code."""
    root = Path(root).resolve()
    boots = set((root/'third_party/napcat').glob('*/NapCatWinBootMain.exe'))
    boots.update((root/'NapCat').glob('**/NapCatWinBootMain.exe'))
    for boot in boots:
        config = (root/'NapCat/managed/config' if root/'third_party/napcat' in boot.parents
                  else boot.parent/'config')
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                   '-File', str(probe), '-BootPath', str(boot), '-CheckOnly', '-RequireStopped']
        record = config/'launch.json'
        try:
            if record.exists():
                value = json.loads(record.read_text(encoding='utf-8'))['qq_path']
                if not isinstance(value, str) or not Path(value).is_absolute() or Path(value).name.lower() != 'qq.exe':
                    return 'check_failed'
                command += ['-QQPath', value]
            result = subprocess.run(command, capture_output=True, timeout=25,
                env={k:v for k,v in os.environ.items() if k.lower() != 'psmodulepath'},
                creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            return 'check_failed'
        if result.returncode == 3:
            return 'running'
        if result.returncode != 0:
            return 'check_failed'
    return 'stopped'

def replacement_status(root, probe):
    root = Path(root).resolve()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    import os
    digest = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()
    handle = kernel.OpenMutexW(0x00100000, False, 'Local' + chr(92) + 'CampusFlowWindow-' + digest)
    if handle:
        kernel.CloseHandle(handle)
        return 10
    if ctypes.get_last_error() != 2:
        return 20
    # Do not execute the old installation's guard, imports or PowerShell scripts.
    try:
        state = check_napcat(root, probe)
        if state != 'stopped':
            return 10 if state == 'running' else 20
    except Exception:
        return 20
    # A refused Windows loopback connection can exceed a short HTTP timeout.
    # An exclusive bind proves the standard backend port is presently unused.
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', 8000))
        except OSError:
            pass  # Occupied or inaccessible: verify identity below; fail closed.
        else:
            return 0
    try:
        import httpx
        with httpx.Client(trust_env=False, timeout=2) as client:
            data = client.get('http://127.0.0.1:8000/api/health').json()
        expected = hashlib.sha256(str(root / 'config.local.json').encode()).hexdigest()
        if data.get('application') == 'CampusFlow' and data.get('instance') == expected:
            return 10
    except httpx.ConnectError:
        pass
    except Exception:
        return 20
    return 0


def safe_to_replace(root):
    return replacement_status(root, Path(root)/'scripts/stop_napcat.ps1') == 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--probe', type=Path)
    args = parser.parse_args()
    try:
        code = replacement_status(args.root, args.probe or args.root/'scripts/stop_napcat.ps1')
    except Exception:
        code = 20
    raise SystemExit(code)
