"""Extract only the pinned, clean upstream NapCat release; never a live installation."""
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

SHA256 = '735f2e633247df3ffd6e8ee8b84d7039c315b2655f5807e5f0029f93d2c30016'
VERSION = 'v4.18.38'
SOURCE = 'https://github.com/NapNeko/NapCatQQ/releases/tag/' + VERSION

def copy_napcat(archive, destination, license_file):
    archive = Path(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('NapCat archive hash mismatch; use the pinned official release.')
    folder = Path(destination)/'third_party'/'napcat'/VERSION
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename or ':' in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Unsafe NapCat archive path')
            if item.is_dir():
                continue
            if path.parts[0] in {'logs', 'cache'} or (path.parts[0]=='config' and path.name!='napcat.json'):
                raise ValueError('Unexpected private NapCat data')
            target = folder.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(item) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
    shutil.copy2(license_file, folder/'LICENSE')
    (folder/'SOURCE.txt').write_text('NapCat '+VERSION+'\nCopyright © 2024 Mlikiowa\n'+SOURCE+'\nArchive SHA256: '+SHA256+'\nUnmodified upstream release. Non-commercial redistribution only; see LICENSE.\nQQ is not included; install the official Windows QQ separately.\n', encoding='utf-8')
    return {'version': VERSION, 'source': SOURCE, 'archive_sha256': SHA256}
