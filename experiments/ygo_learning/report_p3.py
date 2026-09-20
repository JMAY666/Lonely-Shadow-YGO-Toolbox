"""Audit explicit calibration batches and compute conservative expansion gates."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import statistics

from calibration_p3 import CALIBRATION, ROOT, TurnObserver, goal_view
from protocol_p2 import load_protocol, calibration_families, evaluate_goal
from evidence_p3 import read_archive, hash_value
from budget import folder_bytes
from journal_audit import audit
from provenance import sha256
from contract_v2 import digest, build


def percentile(values, fraction=.95):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low = int(position)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (position - low)


def bind_summary(row, record):
    for key in ('family_id', 'mode', 'scenario', 'status', 'replayed', 'model_calls', 'nodes',
                'multi_choice_windows', 'single_choice_windows', 'uncertain_branches',
                'seconds', 'goal', 'native_evidence_bytes'):
        if key not in record or row.get(key) != record[key]:
            raise ValueError('Summary does not match restored archive: ' + key)
    return record


def verify_pair_conditions(conditions):
    for family in {key[0] for key in conditions}:
        if conditions.get((family, 'B1')) != conditions.get((family, 'T0')):
            raise ValueError('B1/T0 random condition differs for ' + family)


def summarize(batches, protocol):
    families = {f['id']: f for f in calibration_families(protocol)}
    expected = set(families)
    records = {}
    conditions = {}
    catalogs = {}
    worker_seconds = 0
    source_versions = []
    for batch in batches:
        batch = Path(batch).resolve()
        if not batch.is_relative_to(CALIBRATION.resolve()):
            raise ValueError('Only local P3 calibration batches may be reported')
        summary = json.loads((batch / 'summary.json').read_text(encoding='utf-8'))
        manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
        if summary['protocol_fingerprint'] != protocol['fingerprint']:
            raise ValueError('Batch used another protocol')
        worker_seconds += summary['worker_seconds']
        for name, fingerprint in manifest['code'].items():
            if Path(name).name != name or sha256(batch / 'source' / name) != fingerprint:
                raise ValueError('Frozen source copy differs from its manifest')
        source_versions.append({'batch': batch.name, 'code': manifest['code'], 'runtime': manifest['runtime']})
        for row in summary['cases']:
            key = (row['family_id'], row['mode'])
            if key in records or key[0] not in expected or key[1] not in ('B1', 'T0'):
                raise ValueError('Duplicate or non-calibration result')
            name = row['archive']
            if Path(name).name != name or not name.endswith('.json.gz'):
                raise ValueError('Archive reference is not a local record filename')
            archive = batch / name
            restored = bind_summary(row, read_archive(archive))
            family = families[key[0]]
            if restored['scenario'] != family['scenario']:
                raise ValueError('Archive scenario differs from frozen family')
            raw_path = archive.with_suffix('')
            if (sha256(archive) != row['storage']['archive_sha256'] or
                    hash_value(restored) != row['storage']['record_sha256'] or
                    json.loads(raw_path.read_text(encoding='utf-8')) != restored):
                raise ValueError('Archive, summary hash and original collector record differ')
            audit(restored)
            if not restored['replayed'] or restored['status'] in ('execution_error', 'journal_mismatch'):
                raise ValueError('Unresolved reliability failure cannot pass the calibration gate')
            folder = Path(restored['session']['folder'])  # audit() already checks the isolated root.
            meta = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
            expansion_hash = digest(meta['expansion'])
            if (expansion_hash != restored['expansion_sha256'] or
                    sorted(meta['expansion']['actual_opening']) != family['hand'] or
                    meta['deck'] != protocol['deck'] or
                    meta['expansion']['engine_seed'] != family['engine_seed'] or
                    meta['expansion']['opponent_responses'] != (family['scenario'] == 'one_ash')):
                raise ValueError('Native experiment condition differs from frozen family')
            conditions[key] = expansion_hash
            observer = TurnObserver()
            observer.update(folder / 'native.jsonl')
            actual_goal = evaluate_goal(goal_view(observer.terminal or {'cards': []}), family['goal'],
                                        completed=observer.terminal is not None, actual_draw_count=observer.draws)
            if (actual_goal != restored['goal'] or observer.draws != restored['actual_draw_count'] or
                    observer.terminal_seq != restored['goal_native_seq']):
                raise ValueError('Goal/count/boundary differs from original native journal')
            runtime = folder.parents[2]
            if runtime not in catalogs:
                from app import Catalog
                catalogs[runtime] = Catalog(runtime).cards
            executed_multiple = sum(len(build(s['before'], catalogs[runtime])['candidates']) > 1
                                    for s in restored['steps'])
            record = {key: restored[key] for key in row if key in restored}
            record['storage'] = {**row['storage'], 'compressed_bytes': archive.stat().st_size,
                                 'original_json_bytes': raw_path.stat().st_size}
            record['native_evidence_bytes'] = folder_bytes(folder)
            record['executed_windows'] = len(restored['steps'])
            record['executed_multi_choice_windows'] = executed_multiple
            records[key] = record
    if set(records) != {(f, mode) for f in expected for mode in ('B1', 'T0')}:
        raise ValueError('All frozen 20 family pairs, including failures, are required')
    verify_pair_conditions(conditions)
    if any(s['code'] != source_versions[0]['code'] or s['runtime'] != source_versions[0]['runtime'] for s in source_versions):
        raise ValueError('Final calibration batches must use one frozen source/rule identity')
    modes = {}
    for mode in ('B1', 'T0'):
        rows = [records[f, mode] for f in sorted(expected)]
        windows = sum(r['multi_choice_windows'] + r['single_choice_windows'] for r in rows)
        modes[mode] = {
            'families': 20, 'structural_goal_successes': sum(r['goal']['success'] for r in rows),
            'statuses': dict(Counter(r['status'] for r in rows)),
            'family_seconds_mean': statistics.mean(r['seconds'] for r in rows),
            'family_seconds_p95': percentile([r['seconds'] for r in rows]),
            'engine_search_nodes': sum(r['nodes'] for r in rows),
            'legacy_recommendation_calls': sum(r['model_calls'] for r in rows),
            'multi_choice_windows': sum(r['multi_choice_windows'] for r in rows),
            'executed_windows': sum(r['executed_windows'] for r in rows),
            'executed_multi_choice_windows': sum(r['executed_multi_choice_windows'] for r in rows),
            'executed_multi_choice_fraction': sum(r['executed_multi_choice_windows'] for r in rows) /
                                              sum(r['executed_windows'] for r in rows),
            'goal_success_family_multi_choice_windows': sum(r['executed_multi_choice_windows'] for r in rows if r['goal']['success']),
            'all_observed_windows': windows,
            'multi_choice_window_fraction': sum(r['multi_choice_windows'] for r in rows) / windows if windows else 0,
            'conditional_random_branches': sum(r['uncertain_branches'] for r in rows),
            'all_full_replays_verified': all(r['replayed'] for r in rows),
        }
    pairs = [records[f, 'B1']['seconds'] + records[f, 'T0']['seconds'] for f in sorted(expected)]
    overhead = max(0, worker_seconds - sum(pairs)) / 20
    pair_bytes = []
    for family in sorted(expected):
        pair_bytes.append(sum(records[family, mode]['native_evidence_bytes'] +
                              records[family, mode]['storage']['original_json_bytes'] +
                              records[family, mode]['storage']['compressed_bytes'] for mode in ('B1', 'T0')))
    current_bytes = folder_bytes(ROOT / '.local/ygo-learning')
    estimate = {
        'scope': 'B1_plus_T0_same_family_pairs_with_native_raw_and_compressed_records_retained',
        'retry_planning_factor': 2, 'overhead_seconds_per_family': overhead,
        '200_family_mean_hours': (statistics.mean(pairs) + overhead) * 200 / 3600,
        '200_family_p95_two_attempt_hours': (percentile(pairs) + overhead) * 2 * 200 / 3600,
        '200_family_mean_additional_GiB': statistics.mean(pair_bytes) * 200 / 1024**3,
        '200_family_p95_two_attempt_additional_GiB': percentile(pair_bytes) * 2 * 200 / 1024**3,
        'current_directory_GiB': current_bytes / 1024**3,
        'remaining_directory_GiB': (20 * 1024**3 - current_bytes) / 1024**3,
        'compressed_collector_GiB_for_200_mean': sum(r['storage']['compressed_bytes'] for r in records.values()) * 10 / 1024**3,
        'compression_limit': 'collector archives do not yet replace native JSONL, raw records, or runtime resources',
    }
    estimate['time_gate_passed'] = estimate['200_family_p95_two_attempt_hours'] <= 4
    estimate['disk_gate_passed'] = estimate['200_family_p95_two_attempt_additional_GiB'] <= estimate['remaining_directory_GiB']
    return {'scope': 'training_calibration_only_no_independent_quality_claim',
            'protocol_fingerprint': protocol['fingerprint'], 'families': 20, 'executed_pairs': 20,
            'worker_seconds': worker_seconds, 'modes': modes,
            'B2': {'coverage': 0, 'denominator': 20, 'scope': 'exact_public_P1_opening_sources_only'},
            'paired_outcomes': dict(Counter(
                'both' if records[f, 'T0']['goal']['success'] and records[f, 'B1']['goal']['success'] else
                'T0_only' if records[f, 'T0']['goal']['success'] else
                'B1_only' if records[f, 'B1']['goal']['success'] else 'neither' for f in expected)),
            'scenario_counts': {scenario: {mode: sum(r['goal']['success'] for r in records.values()
                               if r['scenario'] == scenario and r['mode'] == mode) for mode in ('B1', 'T0')}
                                for scenario in sorted({r['scenario'] for r in records.values()})},
            'budget': estimate, 'sources': source_versions,
            'next_sampling_authorized_by_gate': False,
            'next_step': 'fix teacher limitations and meet conservative budget before validation/sampling',
            'unverified': ['independent teacher quality', 'LLM gain', 'student transfer', 'P7 updates', 'product integration']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('batches', nargs='+', type=Path)
    args = parser.parse_args()
    protocol = load_protocol(CALIBRATION / 'protocol.json')
    report = summarize(args.batches, protocol)
    output = CALIBRATION / ('report-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('families', 'modes', 'paired_outcomes', 'budget')}, indent=2))
    print('Report:', output)


if __name__ == '__main__':
    main()
