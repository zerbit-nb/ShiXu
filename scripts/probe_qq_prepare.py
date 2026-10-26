"""Isolated QQ launch preparation probe. Never starts QQ or changes user settings."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import uuid
from unittest.mock import patch


class PreparationComplete(BaseException):
    """Stop immediately before the real NapCat executable would be started."""


def error_summary(exc):
    known = {'ValueError', 'PermissionError', 'FileNotFoundError', 'FileExistsError',
             'OSError', 'TimeoutExpired', 'CalledProcessError', 'JSONDecodeError',
             'UnicodeEncodeError', 'TypeError', 'RuntimeError'}
    name = type(exc).__name__
    report = {'type': name if name in known else 'other'}
    for field in ('errno', 'winerror', 'returncode'):
        value = getattr(exc, field, None)
        if type(value) is int:
            report[field] = value
    categories = [('QQ 路径映射冲突', 'mapping_conflict'),
                  ('无法创建 QQ 跨磁盘路径映射', 'mapping_creation_failed'),
                  ('未检测到可用的官方 QQ', 'qq_not_found'),
                  ('mount', 'different_drives')]
    for text, category in categories:
        if text in str(exc):
            report['category'] = category
            break
    report['frames'] = [{'file': Path(frame.filename).name, 'function': frame.name,
                         'line': frame.lineno}
                        for frame in traceback.extract_tb(exc.__traceback__)
                        if Path(frame.filename).name in {'napcat_bundle.py', 'ntpath.py', 'pathlib.py'}]
    return report


def filesystem(path):
    if os.name != 'nt':
        return 'unavailable'
    try:
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        api.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR, wintypes.DWORD]
        volume, name = ctypes.create_unicode_buffer(32768), ctypes.create_unicode_buffer(128)
        if not api.GetVolumePathNameW(str(path.resolve()), volume, len(volume)):
            return 'unavailable'
        if not api.GetVolumeInformationW(volume.value, None, 0, None, None, None, name, len(name)):
            return 'unavailable'
        return name.value if name.value in {'NTFS', 'ReFS', 'exFAT', 'FAT32', 'FAT'} else 'other'
    except (OSError, ValueError):
        return 'unavailable'


def run_mapping(command, kwargs, run):
    """Invoke the unchanged helper and retain numeric errors it otherwise hides."""
    script = command[command.index('-File')+1]
    target = command[command.index('-QQDirectory')+1]
    link = command[command.index('-Destination')+1]
    env = dict(kwargs.get('env', os.environ))
    env.update(SHIXU_PROBE_SCRIPT=script, SHIXU_PROBE_TARGET=target, SHIXU_PROBE_LINK=link)
    wrapper = "$global:Error.Clear(); & $env:SHIXU_PROBE_SCRIPT -QQDirectory $env:SHIXU_PROBE_TARGET -Destination $env:SHIXU_PROBE_LINK; $probeExit=$LASTEXITCODE; if ($probeExit -ne 0 -and $global:Error.Count) { $e=$global:Error[0]; [PSCustomObject]@{ error_type=$e.Exception.GetType().Name; hresult=$e.Exception.HResult; line=$e.InvocationInfo.ScriptLineNumber } | ConvertTo-Json -Compress }; exit $probeExit"
    result = run([command[0], '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', wrapper],
                 **{**kwargs, 'env': env})
    details = {}
    if result.returncode:
        try:
            data = json.loads(result.stdout)
            kind = data.get('error_type')
            kinds = {'IOException', 'UnauthorizedAccessException', 'DirectoryNotFoundException',
                     'ItemNotFoundException', 'PSNotSupportedException', 'CommandNotFoundException',
                     'PSSecurityException', 'ArgumentException', 'RuntimeException', 'PSArgumentException'}
            details['type'] = kind if kind in kinds else 'other'
            for field in ('hresult', 'line'):
                if type(data.get(field)) is int: details[field] = data[field]
        except (ValueError, TypeError, AttributeError):
            details['type'] = 'unavailable'
    return result, details


def collect(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    from app.services import napcat_bundle as bundle
    from app.services.bridge import Installation, find_installation
    report = {'format_version': 1, 'purpose': 'isolated_launch_preparation',
              'qq_started': False, 'private_data_included': False}
    install = find_installation(root)
    if not install or not install.managed:
        report['error'] = {'category': 'bundled_installation_required'}
        return report
    try:
        qq = bundle.find_qq()
        target = qq.parent.resolve()
        name = hashlib.sha256(os.path.normcase(str(target)).encode()).hexdigest()[:16]
        alias = root/'runtime/qq-launch'/('qq-client-'+name)
        report['paths'] = {'same_drive': root.drive.lower() == qq.drive.lower(),
                           'app_filesystem': filesystem(root), 'qq_filesystem': filesystem(target),
                           'mapping_exists': alias.exists(), 'mapping_is_junction': alias.is_junction(),
                           'mapping_matches_qq': alias.is_junction() and alias.resolve() == target}
    except Exception as exc:
        report['error'] = error_summary(exc)
        return report
    # A unique private scratch root on the SAME volume as the installed app.
    # Existing user data, managed configs, mappings and startup records stay untouched.
    scratch = root/'runtime/qq-prepare-probes'/uuid.uuid4().hex
    assert scratch.is_relative_to(root/'runtime/qq-prepare-probes')
    config = scratch/'NapCat/managed/config'
    config.mkdir(parents=True)
    isolated = Installation(install.boot, config, True)
    original_popen, original_run = subprocess.Popen, subprocess.run
    helpers = {name: getattr(bundle, name) for name in ('qq_app_relative', 'qq_launch_alias')}
    report['steps'] = []

    def helper(name):
        def invoke(*args, **kwargs):
            report['steps'].append(name)
            return helpers[name](*args, **kwargs)
        return invoke

    def run(command, **kwargs):
        if isinstance(command, (list, tuple)) and any(Path(str(item)).name == 'prepare_qq.ps1' for item in command):
            result, details = run_mapping(command, kwargs, original_run)
            report['mapping_command_exit_code'] = result.returncode
            if details: report['mapping_error'] = details
            return result
        return original_run(command, **kwargs)

    def popen(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and command and Path(command[0]) == install.boot:
            report['prepared'] = True
            raise PreparationComplete()
        if isinstance(command, (list, tuple)) and command and Path(command[0]).name.lower() in {'qq.exe', 'napcatwinbootmain.exe'}:
            raise RuntimeError('Unexpected client launch was blocked')
        return original_popen(command, *args, **kwargs)

    try:
        with patch.object(bundle, 'find_qq', lambda: qq), \
             patch.object(bundle, 'qq_app_relative', helper('qq_app_relative')), \
             patch.object(bundle, 'qq_launch_alias', helper('qq_launch_alias')), \
             patch.object(subprocess, 'run', run), patch.object(subprocess, 'Popen', popen):
            bundle.launch(isolated)
    except PreparationComplete:
        pass
    except Exception as exc:
        report['prepared'] = False
        report['error'] = error_summary(exc)
    finally:
        # No recursive deletion: unlink only our generated scratch files and a
        # verified junction itself; never walk or delete through the QQ mapping.
        try:
            links = scratch/'runtime/qq-launch'
            for link in links.glob('qq-client-*'):
                if not link.is_junction() or link.resolve() != target:
                    raise RuntimeError('Unexpected scratch mapping')
                os.rmdir(link)
            for relative in ('NapCat/managed/config/webui.json', 'NapCat/managed/config/napcat.json',
                             'NapCat/managed/config/launch.json', 'NapCat/managed/entry.cjs',
                             'NapCat/managed/entry.tmp', 'NapCat/managed/qqnt.json',
                             'NapCat/managed/qqnt.tmp', 'NapCat/managed/start-status.json'):
                file = scratch/relative
                assert file.is_relative_to(scratch)
                file.unlink(missing_ok=True)
            for relative in ('runtime/qq-launch', 'runtime', 'NapCat/managed/config', 'NapCat/managed', 'NapCat'):
                directory = scratch/relative
                if directory.exists(): directory.rmdir()
            scratch.rmdir()
            report['scratch_cleaned'] = True
        except (OSError, RuntimeError):
            report['scratch_cleaned'] = False
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = collect(args.root)
    except Exception as exc:
        result = {'format_version': 1, 'qq_started': False, 'error': error_summary(exc)}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Preparation report saved. No QQ client started or user settings changed.')
