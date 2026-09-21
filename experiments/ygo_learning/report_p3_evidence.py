"""Verify compact and original P3 evidence using the same native journal audit."""
from contextlib import contextmanager
import json
from pathlib import Path
import uuid
from budget import folder_bytes
from calibration_p3 import TurnObserver, goal_view
from contract_v2 import build, digest
from evidence_p3 import canonical, hash_value
from journal_audit import audit
from protocol_p2 import evaluate_goal
from provenance import sha256
from session_archive import restored_session, files
from native_session import BASE
from teacher_p3 import decision_key


@contextmanager
def native_folder(record, batch):
    packed = record.get('native_archive')
    if not packed:
        yield Path(record['session']['folder'])
        return
    archive = Path(packed['path']).resolve()
    expected = (batch / 'native' / (record['session']['id'] + '.zip')).resolve()
    if archive != expected or archive.stat().st_size != packed['compressed_bytes']:
        raise ValueError('Native archive reference/size differs from its batch')
    with restored_session(archive, packed['sha256']) as folder:
        entries = files(folder)
        if (len(entries) != packed['files'] or
                sum(item['size'] for item in entries.values()) != packed['original_bytes']):
            raise ValueError('Native archive restored file sizes differ')
        yield folder


def verify(record, row, archive, family, protocol, catalogs):
    batch = archive.parent
    raw_path = archive.with_suffix('')
    if (sha256(archive) != row['storage']['archive_sha256'] or
            hash_value(record) != row['storage']['record_sha256']):
        raise ValueError('Collector archive and summary hash differ')
    if raw_path.exists():
        if json.loads(raw_path.read_text(encoding='utf-8')) != record:
            raise ValueError('Collector archive differs from original record')
    elif row['storage'].get('raw_collector_retained') is not False or not record.get('native_archive'):
        raise ValueError('Missing original collector without verified compact storage')
    if record.get('native_archive') != row.get('native_archive'):
        raise ValueError('Native archive summary differs from collector')
    if not record['replayed'] or record['status'] in ('execution_error', 'journal_mismatch'):
        raise ValueError('Unresolved reliability failure cannot pass calibration')
    actual_folder = Path(record['session']['folder'])
    identifier = record['session']['id']
    allowed = {(BASE / name / 'runtime/_trainer/sessions' / identifier).resolve() for name in
               ('desktop-check-development-modular', 'desktop-check-development-modular-secondary')}
    if str(uuid.UUID(identifier)) != identifier or actual_folder.resolve() not in allowed:
        raise ValueError('Collector session path is outside isolated runtimes')
    with native_folder(record, batch) as folder:
        audit(record, folder=folder)
        meta = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
        if meta.get('id') != record['session']['id']:
            raise ValueError('Restored native session identity differs')
        expansion_hash = digest(meta['expansion'])
        if (expansion_hash != record['expansion_sha256'] or
                sorted(meta['expansion']['actual_opening']) != family['hand'] or
                meta['deck'] != protocol['deck'] or
                meta['expansion']['engine_seed'] != family['engine_seed'] or
                meta['expansion']['opponent_responses'] != (family['scenario'] == 'one_ash')):
            raise ValueError('Native experiment condition differs from frozen family')
        observer = TurnObserver()
        observer.update(folder / 'native.jsonl')
        actual_goal = evaluate_goal(goal_view(observer.terminal or {'cards': []}), family['goal'],
                                   completed=observer.terminal is not None, actual_draw_count=observer.draws)
        if (actual_goal != record['goal'] or observer.draws != record['actual_draw_count'] or
                observer.terminal_seq != record['goal_native_seq']):
            raise ValueError('Goal/count/boundary differs from original native journal')
    runtime = actual_folder.parents[2]
    if runtime not in catalogs:
        from app import Catalog
        catalogs[runtime] = Catalog(runtime).cards
    bundles = [build(s['before'], catalogs[runtime]) for s in record['steps']]
    multi = sum(len(bundle['candidates']) > 1 for bundle in bundles)
    packed = record.get('native_archive')
    physical_native_bytes = folder_bytes(actual_folder) + (packed['compressed_bytes'] if packed else 0)
    steps = record['steps']
    return {'expansion_hash': expansion_hash, 'native_evidence_bytes': physical_native_bytes,
            'native_original_bytes': record['native_evidence_bytes'],
            'executed_windows': len(steps), 'executed_multi_choice_windows': multi,
            'reused_selected_probes': sum(s.get('selected_replay_reused', False) for s in steps),
            'module_proposed_windows': sum(bool(s['decision'].get('proposals', {}).get(decision_key(bundle)))
                                           for s, bundle in zip(steps, bundles)),
            'opponent_search_decisions': sum(len(t.get('opponent_steps', []))
                for d in [s['decision'] for s in steps] + record.get('aborted_searches', [])
                for t in d.get('trace', []) + d.get('failures', [])),
            'native_archive_verified': bool(packed),
            'storage': {**row['storage'], 'compressed_bytes': archive.stat().st_size,
                        'retained_raw_collector_bytes': raw_path.stat().st_size if raw_path.exists() else 0,
                        'original_json_bytes': len(canonical(record))}}
