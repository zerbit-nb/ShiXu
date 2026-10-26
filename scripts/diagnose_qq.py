"""Read-only, shareable QQ startup diagnostics. Never starts QQ or reads sessions."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import re
import sys


def startup_checks(root, install, *, transport=None):
    """Inspect the installed launch path without starting services or changing files."""
    import httpx
    from app.services.desktop import boot_is_running
    root = Path(root).resolve()
    report = {}
    try:
        report['process_probe'] = {'completed': True, 'launcher_running': boot_is_running(install.boot)}
    except Exception as exc:
        allowed = {'CalledProcessError', 'TimeoutExpired', 'FileNotFoundError', 'PermissionError', 'OSError', 'TypeError', 'ValueError', 'JSONDecodeError', 'RuntimeError'}
        name = type(exc).__name__
        probe = {'completed': False, 'error': name if name in allowed else 'unknown'}
        code = getattr(exc, 'returncode', None)
        if type(code) is int: probe['exit_code'] = code
        report['process_probe'] = probe
    report['preparation'] = {
        'entry_exists': (install.config.parent/'entry.cjs').is_file(),
        'patch_exists': (install.config.parent/'qqnt.json').is_file(),
        'launch_record_exists': (install.config/'launch.json').is_file(),
        'start_record_exists': (install.config.parent/'start-status.json').is_file(),
    }
    try:
        policy = json.loads((root/'runtime/napcat-session.json').read_text(encoding='utf-8'))
        state = policy.get('state')
        report['session_state'] = state if state in {'active', 'exited', 'exiting', 'exit_failed'} else 'invalid'
    except FileNotFoundError:
        report['session_state'] = 'active'
    except (OSError, ValueError, AttributeError):
        report['session_state'] = 'unreadable'
    try:
        config = json.loads((install.config/'webui.json').read_text(encoding='utf-8-sig'))
        host = config.get('host', '127.0.0.1')
        report['management_config'] = {
            'host_is_loopback': host in {'127.0.0.1', 'localhost', '::1'},
            'port_valid': type(config.get('port')) is int and 1 <= config['port'] <= 65535,
            'enabled': config.get('disableWebUI') is not True,
            'credential_present': isinstance(config.get('token'), str) and bool(config['token']),
        }
    except (OSError, ValueError, AttributeError, TypeError):
        report['management_config'] = {'readable': False}
    try:
        with httpx.Client(timeout=2, trust_env=False, transport=transport, follow_redirects=False) as client:
            response = client.get('http://127.0.0.1:8000/api/health')
            data = response.json() if response.status_code == 200 else {}
            is_shixu = isinstance(data, dict) and data.get('application') == 'CampusFlow'
            expected = hashlib.sha256(str((root/'config.local.json').resolve()).encode()).hexdigest()
            report['backend'] = {'reachable': True, 'is_shixu': is_shixu,
                                 'matches_installation': is_shixu and data.get('instance') == expected}
    except (httpx.HTTPError, ValueError):
        report['backend'] = {'reachable': False}
    names = {'app/services/desktop.py', 'app/services/napcat_bundle.py', 'app/services/qq_login.py',
             'scripts/desktop.py', 'scripts/prepare_qq.ps1', 'scripts/verify_qq.ps1', 'app/static/qq-login.js'}
    try:
        manifest = json.loads((root/'release-manifest.json').read_text(encoding='utf-8'))
        expected = {item['path']: item['sha256'] for item in manifest['files'] if item['path'] in names}
        report['runtime_integrity'] = {name: (root/name).is_file() and hashlib.sha256((root/name).read_bytes()).hexdigest() == value
                                       for name, value in expected.items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        report['runtime_integrity'] = {'manifest_readable': False}
    log = root/'runtime/desktop-window.log'
    report['launcher_log'] = {'exists': log.is_file()}
    if log.is_file():
        try:
            # Bounded read, returning only known categories, never any log lines.
            with log.open('rb') as handle:
                handle.seek(0, 2)
                handle.seek(max(0, handle.tell()-65536))
                content = handle.read(65536).decode('utf-8', errors='replace')
            kinds = ('CalledProcessError', 'FileNotFoundError', 'PermissionError', 'TimeoutExpired', 'TypeError', 'UnicodeEncodeError', 'ValueError')
            report['launcher_log'].update(qq_check_failed='QQ 启动检查失败' in content,
                known_errors=[name for name in kinds if name+':' in content])
        except OSError:
            report['launcher_log']['readable'] = False
    return report


def qq_app_relative(qq):
    # Keep the standalone diagnostic compatible with the installed preview.3.
    config = qq.parent/'versions'/'config.json'
    if config.is_file():
        version = json.loads(config.read_text(encoding='utf-8-sig')).get('curVersion')
        if not isinstance(version,str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}-[0-9]+',version):
            raise ValueError('Invalid active version')
        return Path('versions')/version/'resources'/'app'
    return Path('resources')/'app'


def file_version(path):
    if os.name != 'nt':
        return None
    try:
        from ctypes import wintypes
        api = ctypes.WinDLL('version', use_last_error=True)
        api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
        unused = wintypes.DWORD()
        size = api.GetFileVersionInfoSizeW(str(path), ctypes.byref(unused))
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not api.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        pointer, length = ctypes.c_void_p(), wintypes.UINT()
        if not api.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)) or length.value < 16:
            return None
        signature, _, high, low = struct.unpack('<4I', ctypes.string_at(pointer, 16))
        if signature != 0xFEEF04BD:
            return None
        return '.'.join(map(str, (high >> 16, high & 65535, low >> 16, low & 65535)))
    except (OSError, ValueError):
        return None


def collect(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    from app.services.napcat_bundle import VERSION, bundled_folder, qq_candidates, find_qq
    from app.services import napcat_bundle
    from app.services.bridge import find_installation
    report = {'format_version': 1, 'windows_version': platform.version(),
              'privacy': 'No accounts, paths, messages, tokens, cookies, raw logs or exceptions included.'}
    folder = bundled_folder(root)
    names = ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'loadNapCat.js', 'napcat.mjs', 'qqnt.json')
    try:
        manifest = json.loads((root/'release-manifest.json').read_text(encoding='utf-8'))
        version = manifest.get('version')
        report['app_version'] = version if isinstance(version, str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+-preview\.[0-9]+', version) else 'unknown'
        expected = {Path(x['path']).name: x['sha256'] for x in manifest['files']
                    if x['path'].startswith('third_party/napcat/'+VERSION+'/') and Path(x['path']).name in names}
    except (OSError, ValueError, KeyError, TypeError):
        expected = {}
    report['engine_files'] = {name: {'exists': (folder/name).is_file(),
        'matches_release': hashlib.sha256((folder/name).read_bytes()).hexdigest() == expected[name]
        if (folder/name).is_file() and name in expected else None} for name in names}
    official = None
    try:
        candidates = list(dict.fromkeys(qq_candidates()))
        registered = list(dict.fromkeys(napcat_bundle.qq_registry_candidates())) if hasattr(napcat_bundle, 'qq_registry_candidates') else candidates
        report['qq'] = {'registered_candidates': len(registered),
                        'discovered_executables': sum(p.is_file() for p in candidates),
                        'versions': sorted({v for p in candidates if p.is_file() and (v := file_version(p))})}
        try:
            official = find_qq()
            report['qq'].update(signed_official_found=True, launcher_version=file_version(official))
            try:
                package = json.loads((official.parent/qq_app_relative(official)/'package.json').read_text(encoding='utf-8-sig'))
                version = package.get('version')
                if isinstance(version,str) and re.fullmatch(r'[0-9]+(?:[.][0-9]+){2}-[0-9]+',version):report['qq']['active_version']=version
            except Exception:pass
        except Exception:
            report['qq']['signed_official_found'] = False
    except Exception:
        report['qq'] = {'query_failed': True}
    try:
        install = find_installation(root)
        report['installation'] = 'bundled' if install and install.managed else 'legacy' if install else 'not_found'
        if install:
            report['startup_checks'] = startup_checks(root, install)
            config = json.loads((install.config/'webui.json').read_text(encoding='utf-8-sig'))
            port = config.get('port')
            report['management_tcp_open'] = False
            if type(port) is int and 1 <= port <= 65535:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=2):
                        report['management_tcp_open'] = True
                except OSError:
                    pass
            if install.managed:
                try:
                    patch = json.loads((install.config.parent/'qqnt.json').read_text(encoding='utf-8'))
                    main = Path(patch.get('main', ''))
                    launcher = official
                    record = json.loads((install.config/'launch.json').read_text(encoding='utf-8'))
                    alias = Path(record['qq_path'])
                    if official and alias.resolve() == official.resolve():
                        launcher = alias
                    entry = Path(os.path.normpath(launcher.parent/qq_app_relative(launcher)/main)) if launcher else None
                    report['relative_entry_correct'] = official is not None and not main.is_absolute() and entry == (install.config.parent/'entry.cjs').absolute() and entry.is_file()
                except (OSError, ValueError, TypeError):
                    report['relative_entry_correct'] = False
                try:
                    entry = json.loads((install.config.parent/'entry-status.json').read_text(encoding='utf-8'))
                    if entry.get('state') in {'entry_loaded','engine_imported','engine_failed'}:
                        code = entry.get('code')
                        report['entry'] = {'state':entry['state'], 'code':code if code in {'ERR_MODULE_NOT_FOUND','MODULE_NOT_FOUND','ERR_DLOPEN_FAILED'} else None}
                except (OSError, ValueError, TypeError):
                    pass
                try:
                    state = json.loads((install.config.parent/'start-status.json').read_text(encoding='utf-8'))
                    if state.get('state') in {'requested', 'ready', 'launcher_exited', 'timeout', 'qq_not_found', 'preparation_failed'}:
                        code = state.get('exit_code')
                        report['last_start'] = {'state': state['state'], 'exit_code': code if type(code) is int else None}
                        if state['state'] == 'preparation_failed' and hasattr(napcat_bundle, 'safe_start_failure'):
                            report['last_start'].update(napcat_bundle.safe_start_failure(state))
                except (OSError, ValueError, AttributeError):
                    pass
    except Exception:
        report['installation_check_failed'] = True
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(collect(args.root), ensure_ascii=False, indent=2), encoding='utf-8')
    print('QQ diagnostic report saved. No account or login settings changed.')
