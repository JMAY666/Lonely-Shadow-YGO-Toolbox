"""Build an offline desktop payload from the WORKING COPY, never the original installation."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
import zipfile

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / 'src/trainer'))
from desktop_runtime import digest, resource_allowed


def main():
    runtime = WORKSPACE / '.local/YGOPro-Lite'
    bundle = WORKSPACE / '.local/desktop-bundle'
    downloads = WORKSPACE / '.local/desktop-downloads'
    bundle.mkdir(parents=True, exist_ok=True)
    downloads.mkdir(parents=True, exist_ok=True)
    lock = json.loads((WORKSPACE / 'scripts/desktop-lock.json').read_text('utf-8'))['python']
    archive = downloads / lock['url'].rsplit('/', 1)[-1]
    if not archive.exists():
        temporary = archive.with_suffix('.download')
        with urlopen(lock['url'], timeout=60) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output)
        if digest(temporary) != lock['sha256']:
            raise ValueError('Python 下载校验失败')
        temporary.replace(archive)
    if digest(archive) != lock['sha256']:
        raise ValueError('Python 归档校验失败')
    python = bundle / 'python'
    python.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        # Do not rewrite an identical executable that a development window may be using.
        for member in z.infolist():
            destination = python / member.filename
            data = z.read(member)
            if destination.is_file() and digest(destination) == hashlib.sha256(data).hexdigest():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    # No pip, environment site-packages, registry Python or developer PATH is needed at runtime.
    files = {}
    for path in sorted(runtime.rglob('*')):
        relative = path.relative_to(runtime).as_posix()
        if not path.is_file() or not resource_allowed(relative) or relative == 'system.conf':
            continue
        if path.is_symlink() or any(p.is_junction() or p.is_symlink() for p in [path.parent, *path.parents] if p.is_relative_to(runtime)):
            raise ValueError('资源中包含链接，拒绝将副本以外的文件打包')
        files[relative] = path
    files['system.conf'] = WORKSPACE / 'desktop/default-system.conf'
    for required in ('YGOPro.exe', 'cards.cdb', 'strings.conf', 'script/constant.lua', 'textures/cover.jpg'):
        if required not in files:
            raise ValueError(f'缺少必要运行资源：{required}')
    manifest_files = {name: {'size': p.stat().st_size, 'sha256': digest(p)} for name, p in files.items()}
    version = hashlib.sha256(json.dumps(manifest_files, sort_keys=True).encode()).hexdigest()
    manifest = {'schema': 1, 'version': version, 'files': manifest_files}
    target = bundle / 'runtime.zip'
    previous = None
    if target.exists():
        with zipfile.ZipFile(target) as z:
            previous = json.loads(z.read('bundle-manifest.json'))['version']
    if previous != version:
        temporary = target.with_suffix('.tmp')
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as z:
            for name, p in files.items():
                compression = zipfile.ZIP_STORED if p.suffix.lower() in {'.jpg', '.png'} else zipfile.ZIP_DEFLATED
                z.write(p, name, compress_type=compression)
            z.writestr('bundle-manifest.json', json.dumps(manifest, ensure_ascii=False))
        temporary.replace(target)
    notices = bundle / 'notices'
    notices.mkdir(exist_ok=True)
    shutil.copy2(WORKSPACE / 'docs/third-party.md', notices / 'THIRD-PARTY.md')
    shutil.copy2(WORKSPACE / 'licenses/YGOPro-GPL-2.0.txt', notices / 'YGOPro-GPL-2.0.txt')
    shutil.copy2(WORKSPACE / 'README.md', notices / 'README.md')
    for relative in ('AGENTS.md', 'docs/recording.md', 'docs/verification.md', 'docs/third-party.md', 'docs/superpre.md',
                     'docs/mdpro3-recognition.md', 'docs/mdpro3-live-follow.md', 'docs/duel-temporary-plans.md',
                     'docs/verification-1.44.0.md',
                     'licenses/YGOPro-GPL-2.0.txt', 'scripts/source-lock.json', 'scripts/desktop-lock.json'):
        destination = notices / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(WORKSPACE / relative, destination)
    # Corresponding source inputs + local modifications accompany the native binary.
    source_lock = json.loads((WORKSPACE / 'scripts/source-lock.json').read_text('utf-8'))
    with zipfile.ZipFile(notices / 'native-sources.zip', 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for item in [source_lock['client_archive'], *source_lock['inputs']]:
            matches = list((WORKSPACE / '.local/downloads').glob(item['name'] + '.*'))
            if len(matches) != 1 or digest(matches[0]) != item['sha256']:
                raise ValueError(f"原生源码归档缺失或校验失败：{item['name']}")
            z.write(matches[0], '.local/downloads/' + matches[0].name, compress_type=zipfile.ZIP_STORED)
        for relative in ('src/lite', 'patches', 'scripts', 'licenses'):
            for p in (WORKSPACE / relative).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc':
                    z.write(p, p.relative_to(WORKSPACE).as_posix())
        for relative in ('src/trainer/single_thread.inc', 'README.md', 'AGENTS.md', 'docs/third-party.md', 'docs/recording.md', 'docs/verification.md'):
            z.write(WORKSPACE / relative, relative)
    print(json.dumps({'files': len(files), 'bytes': sum(f['size'] for f in manifest_files.values()),
                      'runtime_version': version, 'python': lock['version'], 'bundle': str(bundle)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
