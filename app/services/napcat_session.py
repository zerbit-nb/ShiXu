"""Explicit exit policy and path-scoped NapCat control; no QQ credentials."""
import json
import math
import os
from pathlib import Path
import subprocess
import time

class SessionPolicy:
    def __init__(self, root):
        self.path = Path(root)/'runtime'/'napcat-session.json'
    def read(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('state') not in {'active', 'exiting', 'exited', 'exit_failed'}:
                raise ValueError()
            return data
        except FileNotFoundError:
            return {'state': 'active', 'accept_after': 0}
        except (OSError, ValueError, TypeError, AttributeError):
            return {'state': 'exit_failed', 'accept_after': 0}
    @property
    def paused(self):
        return self.read()['state'] != 'active'
    def write(self, state, accept_after=0):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'state': state, 'accept_after': accept_after}), encoding='utf-8')
        temporary.replace(self.path)
    def resume(self, accept_after=None):
        self.write('active', math.ceil(time.time()) if accept_after is None else accept_after)
    def accepts(self, event_time):
        data = self.read()
        return data['state'] == 'active' and event_time >= data.get('accept_after', 0)

def select_processes(boot, rows, qq_path=None):
    boot = Path(boot).resolve()
    selected = [r for r in rows if r.get('path') and Path(r['path']).resolve() == boot]
    if len(selected) > 1:
        raise RuntimeError('Multiple NapCat boot processes')
    ids = {r['pid'] for r in selected}
    while True:
        children = [r for r in rows if r['parent'] in ids and r['pid'] not in ids
                    and not (r.get('path') and Path(r['path']).resolve() == (Path(os.environ.get('WINDIR', 'C:/Windows'))/'System32'/'conhost.exe').resolve())]
        if not children: break
        for row in children:
            path = Path(row['path']).resolve() if row.get('path') else None
            if path is None or not ((path.parent == boot.parent and path.name.lower() in {'qq.exe', 'napcatwinbootmain.exe'}) or (qq_path and path == Path(qq_path).resolve())):
                raise RuntimeError('Untrusted NapCat descendant')
        selected.extend(children)
        ids.update(r['pid'] for r in children)
    owned = [r for r in rows if r.get('path') and Path(r['path']).resolve().parent == boot.parent and Path(r['path']).name.lower() in {'qq.exe', 'napcatwinbootmain.exe'}]
    if any(r['pid'] not in ids for r in owned):
        raise RuntimeError('Orphan NapCat process')
    return selected

def napcat_command(boot):
    if os.name != 'nt': raise RuntimeError('NapCat exit requires Windows')
    script = Path(__file__).resolve().parents[2]/'scripts'/'stop_napcat.ps1'
    command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-BootPath', str(Path(boot).resolve())]
    from app.services.napcat_bundle import bundled_folder
    root = Path(__file__).resolve().parents[2]
    if Path(boot).resolve().parent == bundled_folder(root).resolve():
        record = root/'NapCat'/'managed'/'config'/'launch.json'
        if record.exists():
            data = json.loads(record.read_text(encoding='utf-8'))
            command += ['-QQPath', data['qq_path']]
    return command

def napcat_stopped(boot):
    result = subprocess.run(napcat_command(boot) + ['-CheckOnly', '-RequireStopped'],
        capture_output=True, timeout=20, env={k:v for k,v in os.environ.items() if k.lower() != 'psmodulepath'}, creationflags=subprocess.CREATE_NO_WINDOW)
    return result.returncode == 0

def stop_napcat(boot):
    result = subprocess.run(napcat_command(boot), capture_output=True, text=True, timeout=20, env={k:v for k,v in os.environ.items() if k.lower() != 'psmodulepath'}, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0: raise RuntimeError('NapCat process stop failed')
