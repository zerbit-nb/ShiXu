"""Export a fresh, allowlisted source snapshot without local data or Git history."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
FILES = ('.gitignore', '.gitattributes', 'README.md', 'LICENSE.md', 'SECURITY.md',
         'THIRD_PARTY_NOTICES.md', 'requirements.txt', 'requirements-desktop.txt',
         'requirements-wechat.txt', 'pytest.ini', 'StartCampusFlow.cmd',
         'StartCampusFlowDesktop.vbs', 'docs/github-first-release.md',
         'docs/usage-v1.md', 'docs/release-v1.0.0.md', 'docs/release-v1.1.0.md')
TREES = ('app', 'scripts', 'tests', 'packaging', 'third_party/wechat_db', 'docs/images',
         'assets/brand/windows')
SUFFIXES = {'.py', '.js', '.cjs', '.css', '.html', '.svg', '.json', '.md',
            '.txt', '.cmd', '.ps1', '.iss', '.ico', '.png'}
FORBIDDEN_PARTS = {'.git', '__pycache__', 'node_modules', '.venv', 'data', 'runtime'}
SECRET = re.compile(r'(?:sk-[A-Za-z0-9_-]{24,}|github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def export(destination):
    destination = Path(destination).resolve()
    allowed_root = (ROOT / 'releases').resolve()
    if not destination.is_relative_to(allowed_root):
        raise ValueError('Destination must be below this workspace releases directory.')
    if destination.exists():
        raise ValueError('Refusing to overwrite an existing export.')
    selected = {ROOT / name for name in FILES}
    for folder in TREES:
        for path in (ROOT / folder).rglob('*'):
            relative = path.relative_to(ROOT)
            if any(part in FORBIDDEN_PARTS for part in relative.parts):
                continue
            if path.is_file() and (path.suffix in SUFFIXES or path.name == 'LICENSE'):
                selected.add(path)
    for path in selected:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('Refusing link or outside source: ' + str(path.relative_to(ROOT)))
        if '.local.' in path.name or path.suffix in {'.db', '.sqlite', '.log', '.key', '.pem'}:
            raise ValueError('Unexpected private file: ' + str(path.relative_to(ROOT)))
        if path.suffix not in {'.ico', '.png'} and SECRET.search(path.read_text(encoding='utf-8-sig')):
            raise ValueError('Potential credential pattern; inspect locally: ' + str(path.relative_to(ROOT)))
    destination.mkdir(parents=True)
    entries = []
    for path in sorted(selected):
        relative = path.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        entries.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    # Only the public release entry, without private development chronology.
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8-sig')
    public = changelog.split('## 拾序 0.5.0-preview.10')[0].rstrip() + '\n'
    (destination / 'CHANGELOG.md').write_text(public, encoding='utf-8')
    entries.append({'path': 'CHANGELOG.md', 'sha256': hashlib.sha256((destination / 'CHANGELOG.md').read_bytes()).hexdigest()})
    report = {'version': '1.1.0', 'files': entries, 'old_git_history_included': False,
              'credential_pattern_scan': 'passed; heuristic only, manual review still required'}
    (destination.parent / 'source-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'source': str(destination), 'files': len(entries), 'bytes': sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True)
    export(parser.parse_args().destination)
