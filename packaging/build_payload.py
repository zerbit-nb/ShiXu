"""Build a clean Windows application payload from explicit source/dependency allowlists."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
from napcat_payload import copy_napcat

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_REQUIREMENTS = ('requirements.txt', 'requirements-desktop.txt', 'requirements-wechat.txt')
EXCLUDED_DISTRIBUTIONS = {'pytest', 'iniconfig', 'pluggy', 'pygments'}
SCRIPTS = ('desktop.py', 'desktop_window.py', 'desktop_tray.py', 'launch.py', 'wechat_worker.py', 'diagnose_wechat.py', 'diagnose_qq.py', 'stop_napcat.ps1', 'verify_qq.ps1', 'prepare_qq.ps1', 'exit_qq.py')
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo', 'site-packages', 'test', 'tests', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip')


def build(destination, napcat_shell):
    destination = Path(destination).resolve()
    if ROOT not in destination.parents:
        raise ValueError('Stage must be inside this workspace.')
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing stage; use a new directory.')
    if sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
        raise ValueError('Build with 64-bit CPython 3.12.')
    destination.mkdir(parents=True)
    shutil.copytree(ROOT / 'app', destination / 'app', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (destination / 'scripts').mkdir()
    for name in SCRIPTS:
        shutil.copy2(ROOT / 'scripts' / name, destination / 'scripts' / name)
    shutil.copytree(ROOT / 'third_party' / 'wechat_db', destination / 'third_party' / 'wechat_db',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'assets' / 'brand' / 'windows', destination / 'assets' / 'brand' / 'windows')
    shutil.copy2(ROOT / 'packaging' / 'package_guard.py', destination / 'package_guard.py')
    shutil.copy2(ROOT / 'packaging' / 'FIRST-RUN.txt', destination / 'FIRST-RUN.txt')
    python = destination / 'python'
    python.mkdir()
    base = Path(sys.base_prefix)
    for name in ('python.exe', 'pythonw.exe', 'python3.dll', 'python312.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
        shutil.copy2(base / name, python / name)
    shutil.copytree(base / 'Lib', python / 'Lib', ignore=IGNORE)
    shutil.copytree(base / 'DLLs', python / 'DLLs', ignore=shutil.ignore_patterns('*_test*', '*test*.pyd', '*.pdb'))
    (python / 'python312._pth').write_text(chr(10).join(['.', 'Lib', 'DLLs', 'Lib/site-packages', '..', 'import site', '']), encoding='utf-8')
    packages = []
    for filename in RUNTIME_REQUIREMENTS:
        for line in (ROOT / filename).read_text(encoding='utf-8').splitlines():
            if not line or line.startswith('#'):
                continue
            name, version = line.split('==')
            if name.lower() in EXCLUDED_DISTRIBUTIONS:
                continue
            dist = metadata.distribution(name)
            if dist.version != version:
                raise ValueError('Dependency version mismatch: ' + name)
            site = Path(dist.locate_file('')).resolve()
            for relative in dist.files or []:
                source = Path(dist.locate_file(relative)).resolve()
                try:
                    clean = source.relative_to(site)
                except ValueError:
                    continue  # Entry points outside site-packages are not needed.
                if not source.is_file() or source.suffix in {'.pyc', '.pyo'} or '__pycache__' in clean.parts:
                    continue
                target = python / 'Lib' / 'site-packages' / clean
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            packages.append({'name': name, 'version': version})
    shutil.copy2(ROOT / 'packaging' / 'start.cmd', destination / 'StartShixu.cmd')
    shutil.copy2(ROOT / 'packaging' / 'DiagnoseWeChat.cmd', destination / 'DiagnoseWeChat.cmd')
    shutil.copy2(ROOT / 'packaging' / 'DiagnoseQQ.cmd', destination / 'DiagnoseQQ.cmd')
    shutil.copy2(ROOT / 'packaging' / 'ExitQQ.cmd', destination / 'ExitQQ.cmd')
    napcat = copy_napcat(napcat_shell, destination, ROOT/'packaging/licenses/NapCat.txt')
    entries = []
    for file in sorted(destination.rglob('*')):
        if not file.is_file():
            continue
        relative = file.relative_to(destination).as_posix()
        if file.name in {'config.local.json', 'qq.local.json', 'wechat.local.json'} or relative.startswith(('data/', 'runtime/')):
            raise ValueError('Private file detected in payload: ' + relative)
        entries.append({'path': relative, 'bytes': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    manifest = {'app': 'Shixu', 'version': '1.1.0', 'napcat': napcat, 'python': sys.version.split()[0],
                'packages': packages, 'files': entries, 'private_data_included': False}
    (destination / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / 'THIRD-PARTY-NOTICES.txt').write_text(
        'Python license: python/LICENSE.txt' + chr(10) +
        'WeChat read-only component: third_party/wechat_db/LICENSE and NOTICE.md' + chr(10) +
        'Python packages retain their dist-info licenses and metadata under python/Lib/site-packages.' + chr(10) +
        'NapCat v4.18.38: third_party/napcat/v4.18.38/LICENSE and SOURCE.txt (non-commercial only). QQ, WeChat, LM Studio, model weights and API accounts are NOT distributed.' + chr(10),
        encoding='utf-8')
    print(json.dumps({'stage': str(destination), 'files': len(entries), 'bytes': sum(f['bytes'] for f in entries), 'packages': len(packages)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True)
    parser.add_argument('--napcat-shell', required=True, help='Pinned official NapCat.Shell.zip, never a live directory')
    args = parser.parse_args()
    build(args.stage, args.napcat_shell)
