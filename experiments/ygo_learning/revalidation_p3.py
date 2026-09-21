"""Audit a repaired runtime against full training evidence without opening validation.

This is an offline recovery check, not a teacher-selection authorization. Both
reports are independently re-audited; all 20 training families remain required.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import zipfile

from calibration_p3 import CALIBRATION, ROOT, TurnObserver
from contract_v2 import digest
from evidence_p3 import read_archive
from protocol_p2 import load_protocol
from provenance import runtime_identity, sha256
from report_p3 import summarize
from validation_p3 import cumulative_seconds


def semantic_checkpoint(state):
    # Exclude transport revision, session node and measured query duration only.
    return {key: state[key] for key in ('raw', 'player', 'state', 'learning', 'effects')}


def compare_record(reference, candidate):
    for key in ('family_id', 'scenario', 'mode', 'expansion_sha256'):
        if reference[key] != candidate[key]:
            raise ValueError('Recovery comparison identity/condition differs: ' + key)
    for record in (reference, candidate):
        if record['status'] == 'turn_completed' and record['_native_first_turn_terminal'] is None:
            raise ValueError('Completed first turn has no native journal boundary')
    def trace(record):
        result = []
        for index, step in enumerate(record['steps']):
            if step['before']['state']['turn'] > 1:
                raise ValueError('An actual decision occurred beyond the first-turn boundary')
            following = semantic_checkpoint(step['after'])
            # The native opponent can advance while the controller polls after
            # our final answer. Compare the same first-turn journal boundary,
            # never an arbitrarily timed turn-two/turn-three observation.
            if (index == len(record['steps']) - 1 and record['status'] == 'turn_completed'
                    and following['state']['turn'] > 1 and record['_native_first_turn_terminal'] is not None):
                following = {'native_first_turn_terminal': record['_native_first_turn_terminal']}
            result.append({'before': semantic_checkpoint(step['before']),
                           'response': step['response'], 'after': following})
        return result
    before, after = trace(reference), trace(candidate)
    outcomes = ('status', 'goal', 'actual_draw_count', 'terminal_goal_view')
    return {'family_id': reference['family_id'], 'mode': reference['mode'],
            'reference_windows': len(before), 'candidate_windows': len(after),
            'full_prefix_equal': before == after,
            'reference_prefix_sha256': digest(before), 'candidate_prefix_sha256': digest(after),
            'raw_successor_snapshots_equal': [semantic_checkpoint(s['after']) for s in reference['steps']] ==
                                             [semantic_checkpoint(s['after']) for s in candidate['steps']],
            'terminal_state_equal': reference['_native_first_turn_terminal'] == candidate['_native_first_turn_terminal'],
            'final_checkpoint_equal': semantic_checkpoint(reference['final']) == semantic_checkpoint(candidate['final']),
            'outcome_equal': all(reference[key] == candidate[key] for key in outcomes)}


def budget_preflight(budget, used_seconds):
    projected_hours = budget['200_family_p95_two_attempt_hours']
    additional_gib = budget['200_family_conservative_peak_additional_GiB']
    remaining_gib = budget['remaining_directory_GiB']
    values = (projected_hours, additional_gib, remaining_gib, used_seconds)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('Recovery budget requires finite measured values')
    if min(projected_hours, additional_gib) <= 0 or used_seconds < 0:
        raise ValueError('Recovery budget requires positive estimates and nonnegative usage')
    projection = projected_hours * 3600 * 40 / 200
    remaining = max(0, 7200 - used_seconds)
    gates = {'pilot_four_hour_cost': projected_hours <= 4,
             'pilot_twenty_GiB_storage': additional_gib <= remaining_gib,
             'remaining_two_hour_worker_budget': projection <= remaining}
    return {'worker_limit_seconds': 7200, 'used_worker_seconds': used_seconds,
            'remaining_worker_seconds': remaining, 'full_validation_projected_seconds': projection,
            'additional_worker_allowance_required_seconds': max(0, projection - remaining),
            'minimum_total_worker_limit_seconds': used_seconds + projection,
            'projected_200_family_hours': projected_hours,
            'required_cost_reduction_fraction': max(0, 1 - 4 / projected_hours),
            'gates': gates, 'budget_gates_passed': all(gates.values()),
            'budget_limits_changed': False}


def audited_report(path, protocol):
    path = Path(path).resolve()
    if not path.is_relative_to(CALIBRATION.resolve()) or path.name != 'summary.json':
        raise ValueError('Only explicit local calibration summaries may be compared')
    saved = json.loads(path.read_text('utf-8'))
    sources = saved['sources']
    if not sources or any(Path(s['batch']).name != s['batch'] for s in sources):
        raise ValueError('Invalid calibration batch references')
    batches = [CALIBRATION / s['batch'] for s in sources]
    audited = summarize(batches, protocol)
    for key in ('scope', 'protocol_fingerprint', 'families', 'executed_pairs', 'worker_seconds',
                'modes', 'paired_outcomes', 'scenario_counts', 'sources'):
        if saved[key] != audited[key]:
            raise ValueError('Calibration summary differs from independently audited evidence: ' + key)
    records, metadata = {}, []
    for batch in batches:
        summary = json.loads((batch / 'summary.json').read_text('utf-8'))
        for row in summary['cases']:
            record = read_archive(batch / row['archive'])
            key = (record['family_id'], record['mode'])
            records[key] = record
            # summarize() has just restored and hashed every file in this ZIP.
            with zipfile.ZipFile(record['native_archive']['path']) as archive:
                metadata.append(json.loads(archive.read('session.json')))
                observer = TurnObserver()
                with archive.open('native.jsonl') as journal:
                    for line in journal:
                        if line.strip(): observer.consume(json.loads(line))
                        if observer.terminal is not None: break
                record['_native_first_turn_terminal'] = observer.terminal
    engines = {m['engine_sha256'] for m in metadata}
    if len(engines) != 1:
        raise ValueError('Calibration sessions use mixed native binaries')
    assets = {digest({key: m[key] for key in ('catalog', 'scripts_sha256', 'deck_sha256', 'rule')})
              for m in metadata}
    if len(assets) != 1:
        raise ValueError('Calibration sessions use mixed cards/scripts/deck/rules')
    return audited, records, {'engine_sha256': engines.pop(), 'assets_sha256': assets.pop(),
                             'report': str(path), 'report_sha256': sha256(path)}


def revalidate(reference_path, candidate_path, protocol, runtime):
    began = time.perf_counter()
    registration = CALIBRATION / 'validation-registration.json'
    original_registration_hash = sha256(registration)
    reference, old, old_identity = audited_report(reference_path, protocol)
    candidate, new, new_identity = audited_report(candidate_path, protocol)
    if set(old) != set(new) or old_identity['engine_sha256'] == new_identity['engine_sha256']:
        raise ValueError('Recovery requires the same full training pairs and a different binary')
    if old_identity['assets_sha256'] != new_identity['assets_sha256']:
        raise ValueError('Cards/scripts/deck/rules changed beyond the native repair')
    for name in ('teacher_p3.py', 'contract_v2.py', 'module_proposals.py', 'protocol_p2.py'):
        if reference['sources'][0]['code'][name] != candidate['sources'][0]['code'][name]:
            raise ValueError('Recovery must retain the frozen policy/protocol: ' + name)
    runtime = Path(runtime).resolve()
    from native_session import BASE
    if runtime != (BASE / 'desktop-check-development-modular/runtime').resolve():
        raise ValueError('Recovery may only bind the primary isolated learning runtime')
    if (runtime_identity(runtime) != candidate['sources'][0]['runtime'] or
            sha256(runtime / 'YGOPro.exe') != new_identity['engine_sha256']):
        raise ValueError('Candidate evidence does not match the current isolated runtime')
    comparisons = [compare_record(old[key], new[key]) for key in sorted(old)]
    modes = {}
    for mode in ('B1', 'T0'):
        rows = [r for r in comparisons if r['mode'] == mode]
        modes[mode] = {'families': len(rows), 'windows': sum(r['candidate_windows'] for r in rows),
            **{key: sum(r[key] for r in rows) for key in
               ('full_prefix_equal', 'terminal_state_equal', 'final_checkpoint_equal', 'outcome_equal',
                'raw_successor_snapshots_equal')}}
    passed = all(row[key] for row in comparisons for key in
                 ('full_prefix_equal', 'terminal_state_equal', 'final_checkpoint_equal', 'outcome_equal'))
    if sha256(registration) != original_registration_hash:
        raise ValueError('Historical validation registration changed during recovery audit')
    preflight = budget_preflight(candidate['budget'], cumulative_seconds())
    return {'schema': 1, 'scope': 'repaired_runtime_training_revalidation_no_independent_quality_claim',
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'protocol_fingerprint': protocol['fingerprint'], 'reference': old_identity, 'candidate': new_identity,
            'runtime': candidate['sources'][0]['runtime'], 'comparisons': comparisons, 'modes': modes,
            'training_recovery_gate_passed': passed, 'budget': preflight,
            'candidate_calibration_budget': candidate['budget'],
            'historical_registration_sha256': original_registration_hash,
            'historical_registration_preserved': True,
            'new_validation_registration_created': False, 'next_sampling_authorized_by_gate': False,
            'next_step': ('resolve recovery differences before any further validation' if not passed else
                          'resolve failed budget gates, then pre-register a new complete validation run'
                          if not preflight['budget_gates_passed'] else
                          'pre-register a new complete validation run; this audit grants no execution authority'),
            'validation_families_executed': 0, 'holdout_opened': False, 'paid_calls': 0,
            'offline_audit_seconds': time.perf_counter() - began,
            'unverified': ['repaired-runtime 40-family validation', 'formal teacher quality',
                           'student transfer', 'LLM gain', 'updates and product integration']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-report', required=True, type=Path)
    parser.add_argument('--candidate-report', required=True, type=Path)
    parser.add_argument('--runtime', type=Path, default=ROOT / '.local/ygo-learning/p0b-p1/desktop-check-development-modular/runtime')
    args = parser.parse_args()
    source = Path(__file__).read_bytes()
    result = revalidate(args.reference_report, args.candidate_report,
                        load_protocol(CALIBRATION / 'protocol.json'), args.runtime)
    if Path(__file__).read_bytes() != source:
        raise ValueError('Recovery auditor changed during execution')
    output = CALIBRATION / ('revalidation-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(exist_ok=False)
    (output / 'source.py').write_bytes(source)
    result['auditor_sha256'] = sha256(output / 'source.py')
    with (output / 'summary.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: result[k] for k in ('training_recovery_gate_passed', 'modes', 'budget')}, indent=2))
    print('Report:', output)


if __name__ == '__main__':
    main()
