"""Managed, unmodified NapCat Shell; QQ remains a separately installed dependency."""
import json
import hashlib
import os
from pathlib import Path
import secrets
import socket
import subprocess
import re
from datetime import datetime, timezone

VERSION = 'v4.18.38'
START_HINT = 'NapCat 启动未完成。请运行安装目录的 DiagnoseQQ.cmd，将生成的 qq-diagnostic.json 发回排查；如 QQ 版本较旧，可先在官方 QQ 中更新后重试。'
QQ_NOT_FOUND_HINT = '未检测到可用的官方 QQ。请先打开电脑上的官方 QQ，保持运行后点击“启动 / 检查后台”；未安装时从 im.qq.com 安装。'


class QQNotFoundError(ValueError):
    pass


PREPARATION_STAGES = {
    'initialize': '初始化配置', 'find_qq': '查找官方 QQ', 'check_engine': '检查启动文件',
    'read_package': '读取 QQ 版本', 'write_entry': '写入启动入口',
    'map_qq_path': '准备跨盘映射', 'write_patch': '写入启动适配',
    'write_launch_record': '记录启动配置', 'start_process': '创建后台进程',
}
ERROR_TYPES = {'ValueError', 'PermissionError', 'FileNotFoundError', 'FileExistsError',
    'OSError', 'TimeoutExpired', 'CalledProcessError', 'JSONDecodeError',
    'UnicodeEncodeError', 'TypeError', 'RuntimeError', 'AttributeError'}


def safe_start_failure(data):
    """Allowlisted categories only; never serialize exception text or paths."""
    result = {}
    stage = data.get('stage')
    if isinstance(stage, str) and stage in PREPARATION_STAGES:
        result['stage'] = stage
    error = data.get('error')
    if isinstance(error, dict):
        kind = error.get('type')
        result['error'] = {'type': kind if isinstance(kind, str) and kind in ERROR_TYPES else 'other'}
        for field in ('errno', 'winerror', 'returncode'):
            if type(error.get(field)) is int:
                result['error'][field] = error[field]
    return result


def record_start(install, state, exit_code=None, *, stage=None, error=None):
    target = install.config.parent/'start-status.json'
    temporary = target.with_suffix('.tmp')
    data = {'state': state, 'exit_code': exit_code, 'at': datetime.now(timezone.utc).isoformat()}
    data.update(safe_start_failure({'stage': stage, 'error': error}))
    temporary.write_text(json.dumps(data), encoding='utf-8')
    temporary.replace(target)


def startup_failed(install):
    try:
        data = json.loads((install.config.parent/'start-status.json').read_text(encoding='utf-8'))
        return data.get('state') in {'launcher_exited', 'timeout', 'qq_not_found', 'preparation_failed'}
    except (OSError, ValueError, AttributeError):
        return False


def startup_hint(install):
    try:
        data = json.loads((install.config.parent/'start-status.json').read_text(encoding='utf-8'))
        if data.get('state') == 'qq_not_found': return QQ_NOT_FOUND_HINT
        if data.get('state') == 'preparation_failed':
            failure = safe_start_failure(data)
            label = PREPARATION_STAGES.get(failure.get('stage'), '启动准备')
            code = failure.get('error', {}).get('winerror')
            suffix = f'（系统错误 {code}）' if type(code) is int else ''
            return f'NapCat {label}失败{suffix}。请运行安装目录的 DiagnoseQQ.cmd，提供 qq-diagnostic.json；无需删除配置或重装。'
    except (OSError, ValueError, AttributeError):
        pass
    return START_HINT

def bundled_folder(root):
    return Path(root) / 'third_party' / 'napcat' / VERSION

def initialize(install):
    if not install.managed:
        return
    install.config.mkdir(parents=True, exist_ok=True)
    file = install.config / 'webui.json'
    if not file.exists():
        for port in range(6099, 6200):
            with socket.socket() as probe:
                try:
                    if os.name == 'nt':
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    probe.bind(('127.0.0.1', port))
                except OSError:
                    continue
                break
        else:
            raise ValueError('NapCat 本地端口不可用，请关闭冲突程序后重试。')
        try:
            with file.open('x', encoding='utf-8') as handle:
                json.dump({'host': '127.0.0.1', 'port': port, 'token': secrets.token_hex(32),
                           'autoLoginAccount': '', 'disableWebUI': False}, handle)
        except FileExistsError:
            pass  # Another local startup already initialized this installation.
    settings = install.config / 'napcat.json'
    if not settings.exists():
        try:
            with settings.open('x', encoding='utf-8') as handle:
                json.dump({'fileLog': False, 'consoleLog': False, 'autoTimeSync': False}, handle)
        except FileExistsError:
            pass

def qq_registry_candidates():
    """Read known app registrations plus QQ's variably named uninstall entry."""
    import winreg
    uninstall = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            access = winreg.KEY_READ | view
            keys = [uninstall + r'\QQ']
            try:
                with winreg.OpenKey(hive, uninstall, 0, access) as parent:
                    for index in range(4096):
                        try: name = winreg.EnumKey(parent, index)
                        except OSError: break
                        keys.append(uninstall + '\\' + name)
            except OSError:
                pass
            for key in keys:
                try:
                    with winreg.OpenKey(hive, key, 0, access) as handle:
                        if key != uninstall + r'\QQ':
                            name = winreg.QueryValueEx(handle, 'DisplayName')[0]
                            if not isinstance(name, str) or not re.fullmatch(r'(?:腾讯\s*)?QQ(?:NT)?(?:\s*[\d(（].*)?', name.strip(), re.I):
                                continue
                        try:
                            location = winreg.QueryValueEx(handle, 'InstallLocation')[0]
                            if isinstance(location, str) and location:
                                yield Path(os.path.expandvars(location.strip().strip('"'))) / 'QQ.exe'
                        except OSError:
                            pass
                        for field in ('UninstallString', 'DisplayIcon'):
                            try:
                                command = winreg.QueryValueEx(handle, field)[0]
                                executable = uninstall_executable(command)
                                if executable: yield executable.parent / 'QQ.exe'
                            except OSError:
                                pass
                except OSError:
                    continue
            try:
                with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\QQ.exe', 0, access) as handle:
                    executable = uninstall_executable(winreg.QueryValueEx(handle, '')[0])
                    if executable: yield executable
            except OSError:
                pass
            for key in (r'SOFTWARE\Tencent\QQ', r'SOFTWARE\Tencent\QQNT'):
                try:
                    with winreg.OpenKey(hive, key, 0, access) as handle:
                        for field in ('Install', 'InstallPath', 'Path'):
                            try:
                                location = winreg.QueryValueEx(handle, field)[0]
                                if isinstance(location, str) and location:
                                    yield Path(os.path.expandvars(location.strip().strip('"'))) / 'QQ.exe'
                            except OSError:
                                pass
                except OSError:
                    pass


def qq_process_candidates():
    # Paths only: never inspect account data or command-line login arguments.
    command = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process -Filter \"Name='QQ.exe'\" | Select-Object -ExpandProperty ExecutablePath) | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
            env={k:v for k,v in os.environ.items() if k.lower() != 'psmodulepath'},
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: return
        paths = json.loads(result.stdout.strip() or '[]')
        if isinstance(paths, str): paths = [paths]
        if not isinstance(paths, list): return
        for value in paths[:128]:
            if not isinstance(value, str) or not value or len(value) > 32768: continue
            path = Path(value)
            if not path.is_absolute() or path.name.lower() != 'qq.exe': continue
            # New QQ also runs a copy under versions/<active version>.
            if path.parent.parent.name.lower() == 'versions':
                yield path.parents[2]/'QQ.exe'
            yield path
    except (OSError, ValueError, subprocess.SubprocessError):
        return


def qq_default_candidates():
    for variable, children in (
        ('ProgramFiles', ('Tencent/QQ', 'Tencent/QQNT', 'QQ')),
        ('ProgramFiles(x86)', ('Tencent/QQ', 'Tencent/QQNT', 'QQ')),
        ('LOCALAPPDATA', ('Programs/QQ', 'Programs/Tencent/QQ', 'Tencent/QQ', 'Tencent/QQNT')),
    ):
        base = os.environ.get(variable)
        if base:
            for child in children: yield Path(base)/child/'QQ.exe'


def qq_candidates():
    seen = set()
    for discover in (qq_registry_candidates, qq_process_candidates, qq_default_candidates):
        for path in discover():
            key = os.path.normcase(str(path))
            if key not in seen:
                seen.add(key)
                yield path

def uninstall_executable(command):
    value = str(command).strip()
    if value.startswith(chr(34)):
        value = value.split(chr(34), 2)[1]
    else:
        ending = value.lower().find('.exe')
        if ending < 0:
            return None
        value = value[:ending+4]
    return Path(value) if value.lower().endswith('.exe') else None

def find_qq():
    for path in qq_candidates():
        if not path.is_file():
            continue
        script = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_qq.ps1'
        try:
            checked = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                '-ExecutionPolicy', 'Bypass', '-File', str(script), '-QQPath', str(path.resolve())], capture_output=True, env={k:v for k,v in os.environ.items() if k.lower() != 'psmodulepath'},
                timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            continue
        if checked.returncode == 0:
            return path.resolve()
    raise QQNotFoundError(QQ_NOT_FOUND_HINT)

def qq_app_relative(qq):
    """Select the active QQ package, never a pending update."""
    base = qq.parent
    config = base/'versions'/'config.json'
    if config.is_file():
        version = json.loads(config.read_text(encoding='utf-8-sig')).get('curVersion')
        import re
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){2}-[0-9]+', version):
            raise ValueError('QQ 当前版本信息无法读取，请先修复官方 QQ，再运行 DiagnoseQQ.cmd。')
        relative = Path('versions')/version/'resources'/'app'
    else:
        relative = Path('resources')/'app'
    if not (base/relative/'package.json').is_file():
        raise ValueError('未找到 QQ 当前版本的启动配置，请先修复官方 QQ，再运行 DiagnoseQQ.cmd。')
    return relative


def qq_launch_alias(install, qq):
    """Map QQ into our drive without copying or editing the official client.

    A directory junction is needed only for cross-drive Electron main paths.
    Never overwrite an existing directory or retarget an existing junction.
    """
    target = qq.parent.resolve()
    name = hashlib.sha256(os.path.normcase(str(target)).encode()).hexdigest()[:16]
    # Outside NapCat discovery: never recurse into the linked QQ installation.
    aliases = install.config.parents[2]/'runtime'/'qq-launch'
    aliases.mkdir(parents=True, exist_ok=True)
    alias = aliases / ('qq-client-' + name)
    if alias.exists() or alias.is_symlink() or alias.is_junction():
        if not alias.is_junction() or alias.resolve() != target:
            raise ValueError('QQ 路径映射冲突，请运行 DiagnoseQQ.cmd 排查；不要删除 QQ 或用户数据。')
    else:
        script = Path(__file__).resolve().parents[2]/'scripts'/'prepare_qq.ps1'
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
            '-ExecutionPolicy', 'Bypass', '-File', str(script), '-QQDirectory', str(target),
            '-Destination', str(alias)], capture_output=True, timeout=20,
            env={k:v for k,v in os.environ.items() if k.lower() != 'psmodulepath'},
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or not alias.is_junction() or alias.resolve() != target:
            raise ValueError('无法创建 QQ 跨磁盘路径映射，请运行 DiagnoseQQ.cmd；也可将拾序安装到 QQ 所在磁盘后重试。')
    return alias/'QQ.exe'


ENTRY = '''// Shixu startup adapter. Official NapCat files remain unchanged.
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
function state(value, code = null) {
  const file = path.join(__dirname, 'entry-status.json');
  fs.writeFileSync(file + '.tmp', JSON.stringify({state: value, code}));
  fs.renameSync(file + '.tmp', file);
}
state('entry_loaded');
import(pathToFileURL(process.env.NAPCAT_MAIN_PATH).href).then(
  () => state('engine_imported'),
  error => {
    const allowed = ['ERR_MODULE_NOT_FOUND', 'MODULE_NOT_FOUND', 'ERR_DLOPEN_FAILED'];
    state('engine_failed', allowed.includes(error.code) ? error.code : null);
    process.exitCode = 1;
  }
);
'''


def launch(install):
    progress = {'stage': 'initialize'}
    try:
        return _launch(install, progress)
    except QQNotFoundError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError, subprocess.SubprocessError) as exc:
        details = {'type': type(exc).__name__}
        for field in ('errno', 'winerror', 'returncode'):
            value = getattr(exc, field, None)
            if type(value) is int:
                details[field] = value
        try:
            record_start(install, 'preparation_failed', stage=progress['stage'], error=details)
        except (OSError, ValueError, TypeError):
            pass  # A blocked status file must not replace the actual launch error.
        raise


def _launch(install, progress):
    initialize(install)
    progress['stage'] = 'find_qq'
    try:
        qq = find_qq()
    except QQNotFoundError:
        record_start(install, 'qq_not_found')
        raise
    folder = install.boot.parent.resolve()
    progress['stage'] = 'check_engine'
    required = ('NapCatWinBootMain.exe', 'NapCatWinBootHook.dll', 'loadNapCat.js', 'napcat.mjs', 'qqnt.json')
    if not all((folder/name).is_file() for name in required):
        raise ValueError('NapCat 启动文件缺失，请重新安装拾序；可运行 DiagnoseQQ.cmd 检查文件完整性。')
    progress['stage'] = 'read_package'
    app_relative = qq_app_relative(qq)
    package = json.loads((qq.parent/app_relative/'package.json').read_text(encoding='utf-8-sig'))
    # .js in the vendor directory is ESM because its package declares type=module,
    # but loadNapCat.js uses require(). A private .cjs adapter avoids that mismatch.
    progress['stage'] = 'write_entry'
    entry = install.config.parent/'entry.cjs'
    entry.with_suffix('.tmp').write_text(ENTRY, encoding='utf-8')
    entry.with_suffix('.tmp').replace(entry)
    (install.config.parent/'entry-status.json').unlink(missing_ok=True)
    # Electron uses path.join(packagePath, main), not path.resolve.
    try:
        package['main'] = os.path.relpath(entry, qq.parent/app_relative)
    except ValueError:
        progress['stage'] = 'map_qq_path'
        qq = qq_launch_alias(install, qq)
        package['main'] = os.path.relpath(entry, qq.parent/app_relative)
    progress['stage'] = 'write_patch'
    patch = install.config.parent/'qqnt.json'
    temporary_patch = patch.with_suffix('.tmp')
    temporary_patch.write_text(json.dumps(package, ensure_ascii=False), encoding='utf-8')
    temporary_patch.replace(patch)
    env = {k: v for k, v in os.environ.items() if not k.startswith('NAPCAT_') and k != 'ACCOUNT'}
    for key, name in [('LOAD_PATH', 'loadNapCat.js'),
                      ('INJECT_PATH', 'NapCatWinBootHook.dll'), ('MAIN_PATH', 'napcat.mjs')]:
        env['NAPCAT_' + key] = str(folder / name)
    env['NAPCAT_PATCH_PACKAGE'] = str(patch.resolve())
    env['NAPCAT_WORKDIR'] = str(install.config.parent)
    # Only this exact executable is permitted as an external descendant on exit.
    progress['stage'] = 'write_launch_record'
    record = install.config / 'launch.json'
    temporary = record.with_suffix('.tmp')
    temporary.write_text(json.dumps({'qq_path': str(qq)}), encoding='utf-8')
    temporary.replace(record)
    record_start(install, 'requested')
    progress['stage'] = 'start_process'
    return subprocess.Popen([str(install.boot), str(qq), str(folder / 'NapCatWinBootHook.dll')],
        cwd=folder, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
