"""Import frozen public experiment conditions across instrumented test builds.

This does not resume an old engine or certify equivalence. It starts a new
record, preserving the original, for an explicit reference-trajectory check.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def start(store, body):
    from app import atomic_json, read_json
    allowed = {(ROOT / '.local/ygo-learning/p0b-p1' / name / 'runtime').resolve()
               for name in ('desktop-check-development-modular', 'desktop-check-development-modular-secondary')}
    if (not store.host or not store.host.test_control or os.environ.get('YGO_TRAIN_LEARNING') != '1'
            or store.runtime.resolve() not in allowed):
        raise ValueError('Frozen learning fixtures require the isolated test runtime')
    with store.lock:
        source_path = store.session_path(body['id']) / 'session.json'
        source = read_json(source_path)
        if (source.get('status') not in ('completed', 'stopping', 'interrupted') or store.alive(source) or
                not source.get('expansion') or source['expansion'].get('engine_seed') != 42):
            raise ValueError('Learning fixture source must be a closed seeded experiment')
        if source.get('engine_sha256') != body.get('source_engine_sha256'):
            raise ValueError('Learning fixture source engine identity changed')
        if (source.get('sources') != store.catalog.sources or
                source.get('scripts_sha256') != store.compromise.script_identity() or
                any(store.catalog.cards.get(int(code)) != card for code, card in source['catalog'].items())):
            raise ValueError('Learning fixture rule assets changed')
        current_engine = hashlib.sha256((store.runtime / 'YGOPro.exe').read_bytes()).hexdigest()
        fixture = deepcopy(source)
        fixture['engine_sha256'] = current_engine
        result = store.start(fixture['selected_deck'], retry_meta=fixture)
        target = store.session_path(result['id']) / 'session.json'
        meta = read_json(target)
        meta['learning_fixture'] = {'source_session': source['id'],
            'source_engine_sha256': source['engine_sha256'], 'target_engine_sha256': current_engine,
            'condition_sha256': hashlib.sha256(json.dumps(source['expansion'], sort_keys=True).encode()).hexdigest(),
            'equivalence': 'unverified_until_reference_trajectory_comparison',
            'source_status': source.get('status')}
        atomic_json(target, meta)
        return result
