"""Pre-registered selection of one fixed teacher on validation families only."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import random

from native_session import ROOT
from provenance import sha256
from contract_v2 import digest
from teacher_p3 import CONFIG
from budget import folder_bytes

BASE = ROOT / '.local/ygo-learning/p2-p3'
ADDENDUM = ROOT / 'docs/ai-learning-p3-validation-protocol.md'


def families(protocol):
    result = [deepcopy(f) for f in protocol['families'] if f['split'] == 'validation']
    if len(result) != 40 or len({f['id'] for f in result}) != 40:
        raise ValueError('All 40 frozen validation families are required')
    return result


def cumulative_seconds():
    total = 0
    for folder in BASE.glob('teacher-*'):
        values = [json.loads(p.read_text('utf-8')).get('worker_seconds', 0)
                  for p in (folder / 'summary.json', folder / 'compute-progress.json') if p.is_file()]
        total += max(values, default=0)
    return total


def authorize(protocol, report_path, runtime, *, reporting=False):
    """Freeze criteria before outcomes; never authorize a holdout or new teacher."""
    report_path = Path(report_path).resolve()
    if not report_path.is_relative_to(BASE.resolve()) or report_path.name != 'summary.json':
        raise ValueError('Validation requires a local audited calibration report')
    report = json.loads(report_path.read_text('utf-8'))
    if (report.get('scope') != 'training_calibration_only_no_independent_quality_claim' or
            report.get('protocol_fingerprint') != protocol['fingerprint'] or report.get('families') != 20):
        raise ValueError('Validation calibration report scope mismatch')
    budget = report['budget']
    if (not budget['time_gate_passed'] or not budget['disk_gate_passed'] or
            budget['200_family_p95_two_attempt_hours'] > 4 or (not reporting and
            budget['200_family_conservative_peak_additional_GiB'] >
            20 - folder_bytes(ROOT / '.local/ygo-learning') / 1024**3)):
        raise ValueError('Conservative calibration budget gate has not passed')
    teacher = sha256(Path(__file__).with_name('teacher_p3.py'))
    if (len(report.get('sources', [])) != 4 or any(s['code']['teacher_p3.py'] != teacher or
            s['runtime'] != runtime or s.get('fast_animation_requested') is not True for s in report['sources'])):
        raise ValueError('Validation teacher/runtime differs from calibrated version')
    for mode in ('B1', 'T0'):
        result = report['modes'][mode]
        if not result['all_full_replays_verified'] or result['native_archives_verified'] != 20:
            raise ValueError('Calibration reliability gate has not passed')
    expected = {'schema': 1, 'protocol_fingerprint': protocol['fingerprint'],
        'teacher_sha256': teacher, 'search': CONFIG, 'runtime': runtime,
        'calibration_report': str(report_path), 'calibration_report_sha256': sha256(report_path),
        'addendum_sha256': sha256(ADDENDUM), 'family_ids': [f['id'] for f in families(protocol)],
        'criteria': {'minimum_net_successes': 2, 'common_support_nonnegative': True,
                     'bootstrap_samples': 10000, 'bootstrap_seed': 20260921,
                     'formal_significance_required_for_pilot_selection': False},
        'holdout_opened': False, 'paid_calls': 0}
    path = BASE / 'validation-registration.json'
    if path.exists():
        saved = json.loads(path.read_text('utf-8'))
        if saved.get('fingerprint') != digest({k: v for k, v in saved.items() if k != 'fingerprint'}):
            raise ValueError('Validation registration fingerprint mismatch')
        if any(saved.get(k) != v for k, v in expected.items()):
            raise ValueError('Frozen validation registration cannot be changed')
    else:
        if reporting:
            raise ValueError('Validation evidence has no prior registration')
        previous = cumulative_seconds()
        projected = budget['200_family_p95_two_attempt_hours'] * 3600 * 40 / 200
        if previous + projected > 7200:
            raise ValueError('Conservative validation work exceeds remaining P2/P3 budget')
        saved = {**expected, 'registered_at_utc': datetime.now(timezone.utc).isoformat(),
                 'previous_compute_seconds': previous, 'validation_projected_seconds': projected}
        saved['fingerprint'] = digest(saved)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(saved, stream, ensure_ascii=False, indent=2)
    return saved


def paired_selection(pairs, *, samples=10000, seed=20260921):
    if len(pairs) != 40:
        raise ValueError('Selection requires all 40 validation families')
    difference = [int(row['T0']) - int(row['B1']) for row in pairs]
    common = [row for row in pairs if row['common_supported']]
    rng = random.Random(seed)
    distribution = sorted(sum(rng.choices(difference, k=40)) / 40 for _ in range(samples))
    def quantile(fraction):
        position = (len(distribution) - 1) * fraction
        low = int(position)
        return distribution[low] + (distribution[min(low + 1, len(distribution) - 1)] - distribution[low]) * (position - low)
    common_difference = sum(int(row['T0']) - int(row['B1']) for row in common)
    return {'families': 40, 'B1_successes': sum(row['B1'] for row in pairs),
            'T0_successes': sum(row['T0'] for row in pairs), 'difference': sum(difference) / 40,
            'paired_percentile_95_interval': [quantile(.025), quantile(.975)],
            'bootstrap_samples': samples, 'bootstrap_seed': seed,
            'common_supported_families': len(common), 'common_net_successes': common_difference,
            'pilot_quality_gate_passed': sum(difference) >= 2 and bool(common) and common_difference >= 0,
            'formal_quality_gate_evaluated': False}
