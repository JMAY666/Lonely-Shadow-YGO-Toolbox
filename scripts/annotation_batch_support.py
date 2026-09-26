"""Shared, content-addressed I/O for annotation checkpoints (no rule inference)."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys
from concurrent.futures import ThreadPoolExecutor


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text('utf-8'), object_pairs_hook=_unique_object)


def content_hash(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def atomic_json(path, value):
    """Replace one file after a complete, flushed write in the same directory."""
    data = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    atomic_bytes(path, data)


def atomic_bytes(path, data):
    """Preserve original bytes when saving a recoverable baseline."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValueError('Refuse to replace a linked output file')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def contained_path(root, relative, *, must_exist=True):
    root = Path(root).resolve(strict=True)
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Source path must stay relative to its package')
    path = (root / relative).resolve(strict=must_exist)
    if not path.is_relative_to(root):
        raise ValueError('Source path escapes its package')
    return path


def snapshot_hashes(batch, document, source_pack, supplemental_root=None):
    """Always hash actual bytes, including on cache hits; never trust size/mtime."""
    pack = Path(source_pack).resolve(strict=True)
    raw = (pack / 'manifest.json').read_bytes()
    if content_hash(raw) != batch['source_manifest_sha256']:
        raise ValueError('Source manifest changed; re-audit the collected package')
    evidence = {row['code']: row for row in read_json(pack / 'manifest.json')['cards']}
    expected_hashes = {}
    for row in [*batch['cards'], *batch.get('updated_cards', [])]:
        code = row['code']
        for source in document['cards'][str(code)]['sources']:
            binding = batch.get('source_bindings', {}).get(f'{code}/{source["id"]}')
            if binding and binding['kind'] == 'supplement':
                if supplemental_root is None:
                    raise ValueError('This batch requires --supplemental-root')
                base, original = Path(supplemental_root).resolve(strict=True), binding
            else:
                source_code = binding.get('source_code', code) if binding else code
                originals = {s['id']: s for s in evidence[source_code]['sources']}
                original = originals[binding['source_id'] if binding else source['id']]
                base = pack
            for kind in ('raw', 'text'):
                path = contained_path(base, original[kind + '_path'])
                expected = original[kind + '_sha256']
                if path in expected_hashes and expected_hashes[path] != expected:
                    raise ValueError(f'{code}: conflicting hashes for one source file')
                expected_hashes[path] = expected
    def check_file(item):
        path, expected = item
        actual = content_hash(path.read_bytes())
        if actual != expected:
            raise ValueError('Source snapshot hash mismatch')
        return path, actual
    # Mechanical source checks are independent; never parallelize writes or approvals.
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = dict(pool.map(check_file, expected_hashes.items()))
    return hashes


def validation_fingerprint(root, batch, document, catalog, builtins, hashes):
    """Cover data, actual runtime, vocabulary, validator code and source bytes."""
    root = Path(root)
    dependencies = [*sorted((root / 'src/trainer').glob('*.py')),
                    *sorted((root / 'src/trainer').glob('*.json')),
                    *sorted((root / 'scripts').glob('*.py'))]
    return content_hash({'protocol': 1, 'python': sys.version, 'batch': batch, 'document': document,
                         'catalog': catalog.cards, 'builtins': builtins,
                         'sources': {str(p): h for p, h in sorted(hashes.items())},
                         'dependencies': {str(p.relative_to(root)): content_hash(p.read_bytes())
                                          for p in dependencies}})


def cached_result(path, fingerprint):
    try:
        record = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get('result'), dict):
        return None
    result = record['result']
    required = {'cards', 'updated_cards', 'search_cases', 'rule_cases', 'purpose_cases',
                'source_files', 'source_snapshots_verified'}
    if (record.get('fingerprint') == fingerprint and record.get('protocol') == 1
            and record.get('status') == 'passed' and required <= result.keys()):
        return result
    return None
