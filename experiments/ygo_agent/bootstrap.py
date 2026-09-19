"""Download pinned, public pilot assets into the ignored local directory."""
import hashlib
import json
from pathlib import Path
import argparse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local' / 'ygo-agent-pilot'
LOCK = Path(__file__).with_name('assets.lock.json')


def verify(content, record):
    if len(content) != record['bytes'] or hashlib.sha256(content).hexdigest() != record['sha256']:
        raise ValueError(f'Asset integrity mismatch: {record["path"]}')


def verify_assets():
    manifest = json.loads(LOCK.read_text(encoding='utf-8'))
    for record in manifest['files']:
        target = (LOCAL / record['path']).resolve()
        if not target.is_relative_to(LOCAL.resolve()): raise ValueError('Asset path escapes pilot directory')
        verify(target.read_bytes(), record)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if args.verify:
        verify_assets()
        print('PASS all pinned pilot asset hashes')
        return
    manifest = json.loads(LOCK.read_text(encoding='utf-8'))
    for record in manifest['files']:
        name, url = record['path'], record['url']
        target = LOCAL / name
        if not target.resolve().is_relative_to(LOCAL.resolve()): raise ValueError('Asset path escapes pilot directory')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with urllib.request.urlopen(url, timeout=90) as response:
                content = response.read()
            verify(content, record)
            temporary = target.with_suffix(target.suffix + '.download')
            temporary.write_bytes(content)
            temporary.replace(target)
        content = target.read_bytes()
        verify(content, record)
        print(f'{name}: {len(content):,} bytes', flush=True)
    verify_assets()


if __name__ == '__main__':
    main()
