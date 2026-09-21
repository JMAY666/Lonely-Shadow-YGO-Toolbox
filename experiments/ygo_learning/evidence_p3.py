"""Lossless JSON evidence with content-addressed snapshots and gzip compression.

Archives never replace native evidence. A typed tree keeps ordinary user keys
distinct from reference markers; hashes validate both snapshots and restoration.
"""
import gzip
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def hash_value(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def json_value(value):
    """Apply JSON's integer-key conversion, rejecting ambiguous collisions."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, (str, int)) or isinstance(key, bool):
                raise ValueError('Evidence object keys must be strings or integer counters')
            name = str(key)
            if name in result:
                raise ValueError('Evidence keys collide after JSON normalization')
            result[name] = json_value(item)
        return result
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def write_archive(path, record, *, verify=True):
    record = json_value(record)
    snapshots = {}
    references = 0

    def encode(value):
        nonlocal references
        if isinstance(value, dict):
            if all(key in value for key in ('raw', 'state', 'learning')):
                key = hash_value(value)
                snapshots[key] = value
                references += 1
                return ['s', key]
            if any(not isinstance(key, str) for key in value):
                raise ValueError('JSON evidence keys must be strings')
            return ['d', [[key, encode(item)] for key, item in value.items()]]
        if isinstance(value, list):
            return ['l', [encode(item) for item in value]]
        if value is not None and not isinstance(value, (str, bool, int, float)):
            raise ValueError('Evidence must contain only JSON values')
        return ['v', value]

    tree = encode(record)
    archive = {'schema': 1, 'record_sha256': hash_value(record),
               'tree': tree, 'snapshots': snapshots}
    payload = canonical(archive)
    compressed = gzip.compress(payload, compresslevel=6, mtime=0)
    with Path(path).open('xb') as stream:
        stream.write(compressed)
    if verify and read_archive(path) != record:
        raise ValueError('Evidence restoration differs from source')
    return {'record_sha256': archive['record_sha256'],
            'archive_sha256': hashlib.sha256(compressed).hexdigest(),
            'original_json_bytes': len(canonical(record)),
            'referenced_json_bytes': len(payload), 'compressed_bytes': len(compressed),
            'unique_snapshots': len(snapshots), 'snapshot_references': references,
            'restoration_verified': verify}


def read_archive(path):
    with gzip.open(path, 'rb') as stream:
        payload = stream.read(256 * 1024**2 + 1)
    if len(payload) > 256 * 1024**2:
        raise ValueError('Evidence archive exceeds bounded restore size')
    archive = json.loads(payload)
    if archive.get('schema') != 1:
        raise ValueError('Unsupported evidence schema')
    snapshots = archive['snapshots']
    for key, value in snapshots.items():
        if hash_value(value) != key:
            raise ValueError('Snapshot hash mismatch')

    def decode(node):
        if not isinstance(node, list) or len(node) != 2:
            raise ValueError('Malformed evidence tree')
        kind, value = node
        if kind == 's':
            if value not in snapshots:
                raise ValueError('Missing snapshot reference')
            return deepcopy(snapshots[value])
        if kind == 'd':
            result = {}
            for key, item in value:
                if key in result:
                    raise ValueError('Duplicate evidence key')
                result[key] = decode(item)
            return result
        if kind == 'l':
            return [decode(item) for item in value]
        if kind == 'v':
            return value
        raise ValueError('Unknown evidence node')

    record = decode(archive['tree'])
    if hash_value(record) != archive['record_sha256']:
        raise ValueError('Restored record hash mismatch')
    return record
