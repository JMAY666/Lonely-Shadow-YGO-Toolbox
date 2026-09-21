"""Audit explicit calibration batches and compute conservative expansion gates."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import statistics

from calibration_p3 import CALIBRATION, ROOT
from protocol_p2 import load_protocol, calibration_families
from evidence_p3 import read_archive
from budget import folder_bytes
from provenance import sha256
from budget_policy import legacy_manifest, manifest as budget_manifest


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
    if 'timings' in row and row['timings'] != record.get('timings'):
        raise ValueError('Summary timing profile differs from restored record')
    return record


def verify_pair_conditions(conditions):
    for family in {key[0] for key in conditions}:
        if conditions.get((family, 'B1')) != conditions.get((family, 'T0')):
            raise ValueError('B1/T0 random condition differs for ' + family)


def summarize(batches, protocol, *, validation=False):
    from validation_p3 import families as validation_families
    families = {f['id']: f for f in (validation_families(protocol) if validation else calibration_families(protocol))}
    expected = set(families)
    count = len(expected)
    records = {}
    conditions = {}
    catalogs = {}
    worker_seconds = 0
    source_versions = []
    registered_versions = []
    for batch in batches:
        batch = Path(batch).resolve()
        if not batch.is_relative_to(CALIBRATION.resolve()):
            raise ValueError('Only local P3 calibration batches may be reported')
        summary = json.loads((batch / 'summary.json').read_text(encoding='utf-8'))
        manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
        expected_scope = ('40_validation_family_teacher_selection_no_holdout' if validation else
                          '20_training_family_cost_calibration_not_quality_validation')
        if summary.get('scope') != expected_scope or manifest.get('scope') != expected_scope:
            raise ValueError('Cannot mix calibration and validation evidence')
        if validation:
            from validation_p3 import authorize
            saved = manifest.get('validation_registration') or {}
            registered = authorize(protocol, saved.get('calibration_report', ''), manifest['runtime'], reporting=True)
            if saved != registered:
                raise ValueError('Validation batch registration changed')
            registered_versions.append(registered)
        if summary['protocol_fingerprint'] != protocol['fingerprint']:
            raise ValueError('Batch used another protocol')
        worker_seconds += summary['worker_seconds']
        for name, fingerprint in manifest['code'].items():
            if Path(name).name != name or sha256(batch / 'source' / name) != fingerprint:
                raise ValueError('Frozen source copy differs from its manifest')
        for name, fingerprint in manifest.get('implementation', {}).items():
            file = (batch / 'implementation' / name).resolve()
            if not file.is_relative_to((batch / 'implementation').resolve()) or sha256(file) != fingerprint:
                raise ValueError('Frozen implementation differs from its manifest')
        source_versions.append({'batch': batch.name, 'code': manifest['code'], 'runtime': manifest['runtime'],
                                'implementation': manifest.get('implementation'),
                                'fast_animation_requested': manifest.get('fast_animation_requested', False)})
        for row in summary['cases']:
            key = (row['family_id'], row['mode'])
            if key in records or key[0] not in expected or key[1] not in ('B1', 'T0'):
                raise ValueError('Duplicate or non-calibration result')
            name = row['archive']
            if Path(name).name != name or not name.endswith('.json.gz'):
                raise ValueError('Archive reference is not a local record filename')
            archive = batch / name
            restored = bind_summary(row, read_archive(archive))
            if 'fast_animation_requested' in manifest and restored.get('final_replay', {}).get(
                    'learning_profile', {}).get('fast_animation') != manifest['fast_animation_requested']:
                raise ValueError('Native animation mode differs from manifest')
            family = families[key[0]]
            if restored['scenario'] != family['scenario']:
                raise ValueError('Archive scenario differs from frozen family')
            from report_p3_evidence import verify
            checked = verify(restored, row, archive, family, protocol, catalogs)
            conditions[key] = checked.pop('expansion_hash')
            record = {key: restored[key] for key in row if key in restored}
            record.update(checked)
            records[key] = record
    if set(records) != {(f, mode) for f in expected for mode in ('B1', 'T0')}:
        raise ValueError('All frozen family pairs, including failures, are required')
    verify_pair_conditions(conditions)
    if any(any(s[key] != source_versions[0][key] for key in ('code', 'runtime', 'implementation',
                                                            'fast_animation_requested')) for s in source_versions):
        raise ValueError('Final calibration batches must use one frozen source/rule identity')
    policy = budget_manifest()
    if validation:
        if any(r != registered_versions[0] for r in registered_versions):
            raise ValueError('Validation batches must use one frozen registration')
        policy = registered_versions[0].get('budget_policy', legacy_manifest())
    modes = {}
    for mode in ('B1', 'T0'):
        rows = [records[f, mode] for f in sorted(expected)]
        windows = sum(r['multi_choice_windows'] + r['single_choice_windows'] for r in rows)
        modes[mode] = {
            'families': count, 'structural_goal_successes': sum(r['goal']['success'] for r in rows),
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
            'native_archives_verified': sum(r['native_archive_verified'] for r in rows),
            'reused_selected_probes': sum(r['reused_selected_probes'] for r in rows),
            'module_proposed_windows': sum(r['module_proposed_windows'] for r in rows),
            'opponent_search_decisions': sum(r['opponent_search_decisions'] for r in rows),
        }
    pairs = [records[f, 'B1']['seconds'] + records[f, 'T0']['seconds'] for f in sorted(expected)]
    overhead = max(0, worker_seconds - sum(pairs)) / count
    pair_bytes = []
    for family in sorted(expected):
        pair_bytes.append(sum(records[family, mode]['native_evidence_bytes'] +
                              records[family, mode]['storage']['retained_raw_collector_bytes'] +
                              records[family, mode]['storage']['compressed_bytes'] for mode in ('B1', 'T0')))
    current_bytes = folder_bytes(ROOT / '.local/ygo-learning')
    estimate = {
        'scope': 'B1_plus_T0_same_family_pairs_with_actual_retained_evidence_storage',
        'retry_planning_factor': 2, 'overhead_seconds_per_family': overhead,
        '200_family_mean_hours': (statistics.mean(pairs) + overhead) * 200 / 3600,
        '200_family_p95_two_attempt_hours': (percentile(pairs) + overhead) * 2 * 200 / 3600,
        '200_family_mean_additional_GiB': statistics.mean(pair_bytes) * 200 / 1024**3,
        '200_family_p95_two_attempt_additional_GiB': percentile(pair_bytes) * 2 * 200 / 1024**3,
        'current_directory_GiB': current_bytes / 1024**3,
        'remaining_directory_GiB': (policy['family_disk_limit_GiB'] * 1024**3 - current_bytes) / 1024**3,
        'compressed_collector_GiB_for_200_mean': sum(r['storage']['compressed_bytes'] for r in records.values()) * 200 / count / 1024**3,
        'compression_limit': 'uses actual native archives plus retained application caches; old evidence and runtimes remain',
    }
    estimate['time_gate_passed'] = estimate['200_family_p95_two_attempt_hours'] <= policy['family_time_limit_hours']
    reserve = max(2 * r['native_original_bytes'] + r['storage']['original_json_bytes'] for r in records.values())
    estimate['temporary_restore_reserve_GiB'] = reserve / 1024**3
    estimate['200_family_conservative_peak_additional_GiB'] = (
        estimate['200_family_p95_two_attempt_additional_GiB'] + reserve / 1024**3)
    estimate['disk_gate_passed'] = estimate['200_family_conservative_peak_additional_GiB'] <= estimate['remaining_directory_GiB']
    result = {'scope': 'validation_teacher_selection_no_holdout' if validation else 'training_calibration_only_no_independent_quality_claim',
            'protocol_fingerprint': protocol['fingerprint'], 'families': count, 'executed_pairs': count,
            'worker_seconds': worker_seconds, 'modes': modes,
            'budget_policy': policy,
            'B2': {'coverage': 0, 'denominator': count, 'scope': 'exact_public_P1_opening_sources_only'},
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
    if validation:
        from validation_p3 import paired_selection
        comparison = paired_selection([{'T0': records[f, 'T0']['goal']['success'],
            'B1': records[f, 'B1']['goal']['success'], 'common_supported': all(
                records[f, mode]['status'] != 'unsupported' for mode in ('B1', 'T0'))} for f in sorted(expected)])
        result['selection'] = comparison
        passed = comparison['pilot_quality_gate_passed'] and estimate['time_gate_passed'] and estimate['disk_gate_passed']
        result['next_sampling_authorized_by_gate'] = passed
        result['next_step'] = ('P4 pilot training-source collection may be prepared' if passed else
                               'stop expansion; validation quality or cost gate failed')
        result['unverified'][0] = 'formal teacher quality on sealed holdout'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('batches', nargs='+', type=Path)
    parser.add_argument('--validation', action='store_true')
    args = parser.parse_args()
    protocol = load_protocol(CALIBRATION / 'protocol.json')
    report = summarize(args.batches, protocol, validation=args.validation)
    output = CALIBRATION / ('report-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('families', 'modes', 'paired_outcomes', 'budget')}, indent=2))
    if args.validation:
        print(json.dumps(report['selection'], indent=2))
    print('Report:', output)


if __name__ == '__main__':
    main()
