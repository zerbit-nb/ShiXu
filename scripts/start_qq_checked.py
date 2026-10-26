"""Run the installed QQ startup in place, retaining only safe failure evidence."""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import uuid
from unittest.mock import patch

# The shipped isolated Python does not add this tool's directory automatically.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_qq_prepare import error_summary


GENERATED_FILES = ('entry.cjs', 'entry.tmp', 'entry-status.json', 'qqnt.json', 'qqnt.tmp',
                   'start-status.json', 'start-status.tmp', 'config/launch.json', 'config/launch.tmp')


def file_states(folder):
    result = {}
    for name in GENERATED_FILES:
        file = folder/name
        try:
            info = {'exists': file.exists(), 'is_file': file.is_file(),
                    'is_directory': file.is_dir(), 'is_link': file.is_symlink() or file.is_junction()}
            if info['exists']:
                info['readonly'] = bool(getattr(file.stat(), 'st_file_attributes', 0) & 1)
            result[name] = info
        except OSError as exc:
            result[name] = {'error': error_summary(exc)}
    return result


async def start(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    from app.services.bridge import BridgeMonitor, find_installation
    from app.services import qq_login
    from app.services.qq_login import QQLogin
    report = {'format_version': 1, 'purpose': 'actual_installed_startup',
              'private_data_included': False, 'launch_attempted': False}
    install = find_installation(root)
    expected = root/'NapCat/managed/config'
    if not install or not install.managed or install.config.resolve() != expected:
        report['error'] = {'category': 'bundled_installation_required'}
        return report
    report['before'] = file_states(install.config.parent)
    original = qq_login.launch

    def checked_launch(selected):
        # QQLogin holds its existing interprocess startup lock at this point.
        report['phase'] = 'backup_generated_files'
        tag = datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        backup = root/'runtime/backups'/('qq-start-'+tag)
        assert backup.is_relative_to(root/'runtime/backups')
        backup.mkdir(parents=True)
        count = 0
        for name in GENERATED_FILES:
            report['backup_file'] = name
            file = selected.config.parent/name
            if file.is_symlink() or file.is_junction():
                raise RuntimeError('Generated startup path is a link')
            if file.is_file():
                if file.stat().st_size > 2*1024*1024:
                    raise RuntimeError('Generated startup file exceeds backup limit')
                target = backup/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
                count += 1
        report['backup'] = {'created': True, 'generated_files': count}
        report.pop('backup_file', None)
        report['phase'] = 'installed_launch'
        report['launch_attempted'] = True
        try:
            process = original(selected)
        except Exception as exc:
            report['launch_error'] = error_summary(exc)
            raise
        report['phase'] = 'waiting_for_management'
        return process

    def traced_launch(selected):
        try:
            return checked_launch(selected)
        except Exception as exc:
            if 'launch_error' not in report:
                report['launch_error'] = error_summary(exc)
            raise

    login = QQLogin(BridgeMonitor(root))
    try:
        with patch.object(qq_login, 'launch', traced_launch):
            result = await login.start()
        state = result.get('state')
        report['result_state'] = state if state in {'running', 'starting'} else 'other'
    except Exception as exc:
        if isinstance(exc, qq_login.LoginError):
            allowed = {'start_failed', 'config_error', 'not_installed', 'exit_failed', 'not_running'}
            report['result_state'] = exc.state if exc.state in allowed else 'other'
        else:
            report['error'] = error_summary(exc)
    try:
        report['management_ready'] = await login.management_alive(login.installation()[1])
    except Exception as exc:
        report['management_check_error'] = error_summary(exc)
    report['after'] = file_states(install.config.parent)
    if report.get('management_ready'):
        report['phase'] = 'management_reachable'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(start(args.root))
    except Exception as exc:
        result = {'format_version': 1, 'purpose': 'actual_installed_startup', 'error': error_summary(exc)}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if result.get('management_ready'):
        print('NapCat management is reachable. Return to Shixu to complete QQ login.')
    else:
        print('QQ startup was not confirmed. Please share qq-start-report.json only.')
