"""Lossless archives of closed, newly created experiment sessions only.

Existing P0/P1/P3 evidence is never migrated by the batch runner. Each archive
contains every original file, a size/hash manifest, and an exclusive restoration
check. Compact mode removes only verified duplicate files from this new session;
metadata and application report caches stay available for same-condition retry.
"""
from contextlib import contextmanager
import hashlib
import json
import os
import sys
from pathlib import Path
import tempfile
import time
import uuid
import zipfile

from native_session import BASE
from provenance import ROOT, sha256
sys.path.insert(0, str(ROOT / 'src/trainer'))

SCHEMA = 'closed_native_session_v1'
MAX_BYTES = 512 * 1024**2
MANIFEST = '_archive_manifest.json'


def files(folder):
    folder = Path(folder)
    if folder.is_symlink() or os.path.isjunction(folder):
        raise ValueError('Session archive refuses directory links')
    result = {}
    for path in folder.iterdir():
        if path.is_symlink() or os.path.isjunction(path) or not path.is_file():
            raise ValueError('Session archive requires flat regular files')
        result[path.name] = {'size': path.stat().st_size, 'sha256': sha256(path)}
    if sum(item['size'] for item in result.values()) > MAX_BYTES:
        raise ValueError('Session exceeds bounded archive size')
    return result


def restore_archive(archive, destination, expected_hash):
    """Restore only into a fresh directory; reject traversal and extra members."""
    archive, destination = Path(archive), Path(destination)
    if sha256(archive) != expected_hash:
        raise ValueError('Native archive hash mismatch')
    if destination.exists():
        raise FileExistsError('Native restore destination must be new')
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        names = [item.filename for item in members]
        if len(names) != len(set(names)) or MANIFEST not in names:
            raise ValueError('Duplicate or missing archive members')
        if sum(item.file_size for item in members) > MAX_BYTES + 1024**2:
            raise ValueError('Native restore exceeds bounded size')
        manifest = json.loads(source.read(MANIFEST))
        if manifest.get('schema') != SCHEMA or not isinstance(manifest.get('files'), dict):
            raise ValueError('Unknown native archive schema')
        expected = manifest['files']
        if set(names) != {*expected, MANIFEST}:
            raise ValueError('Native archive file set mismatch')
        for name, item in expected.items():
            if (not name or name in ('.', '..') or Path(name).name != name or
                    any(c in name for c in '/\\:') or
                    type(item.get('size')) is not int or not 0 <= item['size'] <= MAX_BYTES):
                raise ValueError('Unsafe archive member')
        destination.mkdir()
        for name, item in expected.items():
            payload = source.read(name)
            if len(payload) != item['size'] or hashlib.sha256(payload).hexdigest() != item['sha256']:
                raise ValueError('Native archive member hash mismatch')
            with (destination / name).open('xb') as target:
                target.write(payload)
    if files(destination) != expected:
        raise ValueError('Native restoration differs from original files')
    return manifest


@contextmanager
def restored_session(archive, expected_hash):
    root = BASE / 'archive-restores'
    root.mkdir(exist_ok=True)
    # Only this newly allocated temporary tree is removed on exit. Never restore
    # over a live session or follow a directory link into another workspace.
    with tempfile.TemporaryDirectory(prefix='verified-', dir=root) as temporary:
        parent = Path(temporary).resolve()
        if parent.parent != root.resolve() or parent.is_symlink() or os.path.isjunction(parent):
            raise ValueError('Restore workspace escaped isolated root')
        folder = parent / 'session'
        restore_archive(archive, folder, expected_hash)
        yield folder


def pack_session(folder, archive, session_id, *, compact=False, audit_restored=None):
    from app import process_identity
    folder, archive = Path(folder), Path(archive)
    allowed = {(BASE / name / 'runtime/_trainer/sessions').resolve() for name in
               ('desktop-check-development-modular', 'desktop-check-development-modular-secondary')}
    if (folder.resolve().parent not in allowed or folder.name != str(uuid.UUID(session_id)) or
            not archive.resolve().is_relative_to((BASE.parent / 'p2-p3').resolve())):
        raise ValueError('Native archive path is outside the isolated experiment')
    original = files(folder)
    meta = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
    with (folder / 'native.jsonl').open(encoding='utf-8') as stream:
        header = json.loads(stream.readline())
    if (meta.get('id') != session_id or meta.get('status') != 'completed' or
            header.get('test_control') is not True or not meta.get('process_identity') or
            process_identity(meta.get('pid', 0)) == meta['process_identity']):
        raise ValueError('Cannot archive a live or unverified test session')
    manifest = {'schema': SCHEMA, 'session_id': session_id, 'files': original}
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for name in original:
            target.write(folder / name, name)
        target.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    fingerprint = sha256(archive)
    with restored_session(archive, fingerprint) as restored:
        if files(restored) != original:
            raise ValueError('Native archive restoration failed')
        if audit_restored is not None:
            audit_restored(restored)
    if files(folder) != original:
        raise ValueError('Native session changed while archiving; originals retained')
    retained = set(original)
    retained_duplicates = []
    if compact:
        # Preserve metadata/reports for the app's closed-session list and retry.
        # The full native log, replay calls, and checkpoints remain in the zip.
        retained = {name for name in original if name == 'session.json' or name.startswith('report-v')
                    or name.endswith('.ydk') or name == 'opening.cfg'}
        marker = {'schema': SCHEMA, 'archive': str(archive.resolve()), 'sha256': fingerprint,
                  'session_id': session_id, 'retained_files': sorted(retained),
                  'restore': 'session_archive.restore_archive into a fresh isolated directory'}
        with (folder / 'evidence-archive.json').open('x', encoding='utf-8') as stream:
            json.dump(marker, stream, ensure_ascii=False, indent=2)
        # All absolute paths were bounded above; delete only byte-verified
        # duplicate regular files from this closed session, never directories.
        for name in sorted(set(original) - retained):
            path = folder / name
            if path.is_symlink() or sha256(path) != original[name]['sha256']:
                raise ValueError('Session file changed before compaction')
            # The hidden renderer/service can still be finishing a read of a
            # closed session. Sharing violations must retain the verified
            # duplicate, not destroy an otherwise valid evidence batch.
            for attempt in range(4):
                try:
                    path.unlink()
                    break
                except PermissionError:
                    if attempt == 3:
                        retained_duplicates.append(name)
                    else:
                        time.sleep(.025)
    return {'schema': SCHEMA, 'path': str(archive.resolve()), 'sha256': fingerprint,
            'original_bytes': sum(item['size'] for item in original.values()),
            'compressed_bytes': archive.stat().st_size,
            'retained_bytes': sum(path.stat().st_size for path in folder.iterdir()),
            'files': len(original), 'restoration_verified': True, 'compact': compact,
            'retained_duplicate_files': retained_duplicates}
