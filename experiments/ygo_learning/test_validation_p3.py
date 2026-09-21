import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import validation_p3 as validation
from provenance import sha256
from budget_policy import manifest as budget_manifest
from contract_v2 import digest


class ValidationTests(unittest.TestCase):
    def test_only_validation_split_is_selected_and_returned_by_copy(self):
        source = [{'id': f'v{i}', 'split': 'validation'} for i in range(40)]
        source += [{'id': 'sealed', 'split': 'holdout'}, {'id': 'used', 'split': 'train'}]
        selected = validation.families({'families': source})
        self.assertEqual(40, len(selected))
        selected[0]['id'] = 'changed'
        self.assertEqual('v0', source[0]['id'])
        with self.assertRaises(ValueError):
            validation.families({'families': source[:39]})

    def test_full_denominator_and_common_support_are_separate_requirements(self):
        pairs = [{'T0': False, 'B1': False, 'common_supported': True} for _ in range(40)]
        pairs[0]['T0'] = pairs[1]['T0'] = True
        a = validation.paired_selection(pairs, samples=200)
        self.assertEqual(.05, a['difference'])
        self.assertTrue(a['pilot_quality_gate_passed'])
        self.assertEqual(a, validation.paired_selection(pairs, samples=200))
        pairs[2]['T0'] = True
        pairs[3]['B1'] = True
        for row in pairs[:3]: row['common_supported'] = False
        b = validation.paired_selection(pairs, samples=200)
        self.assertEqual(.05, b['difference'])
        self.assertFalse(b['pilot_quality_gate_passed'])
        with self.assertRaises(ValueError): validation.paired_selection(pairs[:39])

    @contextmanager
    def registration_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = root / '.local/ygo-learning/p2-p3'
            base.mkdir(parents=True)
            report_path = base / 'report/summary.json'
            report_path.parent.mkdir()
            addendum = root / 'protocol.md'
            addendum.write_text('pre-registered selection', encoding='utf-8')
            legacy_addendum = root / 'legacy.md'
            legacy_addendum.write_text('original pre-registered selection', encoding='utf-8')
            teacher = sha256(Path(validation.__file__).with_name('teacher_p3.py'))
            runtime = {'rules': 'fixed'}
            report = {'scope': 'training_calibration_only_no_independent_quality_claim',
                'protocol_fingerprint': 'protocol', 'families': 20, 'executed_pairs': 20,
                'budget': {'time_gate_passed': True, 'disk_gate_passed': True,
                           '200_family_p95_two_attempt_hours': 4.8,
                           '200_family_conservative_peak_additional_GiB': 4.5},
                'budget_policy': budget_manifest(),
                'modes': {mode: {'all_full_replays_verified': True, 'native_archives_verified': 20}
                          for mode in ('B1', 'T0')},
                'sources': [{'code': {'teacher_p3.py': teacher}, 'runtime': runtime,
                             'fast_animation_requested': True}]}
            report_path.write_text(json.dumps(report), encoding='utf-8')
            protocol = {'fingerprint': 'protocol', 'families': [
                {'id': str(i), 'split': 'validation'} for i in range(40)]}
            with patch.object(validation, 'ROOT', root), patch.object(validation, 'BASE', base), \
                    patch.object(validation, 'ADDENDUM', addendum), \
                    patch.object(validation, 'LEGACY_ADDENDUM', legacy_addendum):
                yield base, report_path, report, protocol, runtime

    def test_registration_requires_budget_and_cannot_be_rewritten_after_outcomes(self):
        with self.registration_fixture() as (base, path, report, protocol, runtime), \
                patch.object(validation, 'cumulative_seconds', return_value=10790) as compute:
            with self.assertRaisesRegex(ValueError, 'remaining'):
                validation.authorize(protocol, path, runtime)
            with self.assertRaisesRegex(ValueError, 'no prior registration'):
                validation.authorize(protocol, path, runtime, reporting=True)
            compute.return_value = 0
            saved = validation.authorize(protocol, path, runtime)
            self.assertEqual(saved, validation.authorize(protocol, path, runtime))
            self.assertTrue((base / 'validation-registration-v8.json').is_file())
            self.assertFalse((base / 'validation-registration.json').exists())
            validation.ADDENDUM.write_text('changed after inspection', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'cannot be changed'):
                validation.authorize(protocol, path, runtime)

    def test_one_or_multiple_consistent_calibration_batches_are_supported(self):
        for count in (1, 4):
            with self.subTest(count=count), self.registration_fixture() as (_, path, report, protocol, runtime), \
                    patch.object(validation, 'cumulative_seconds', return_value=7300):
                report['sources'] *= count
                path.write_text(json.dumps(report), encoding='utf-8')
                saved = validation.authorize(protocol, path, runtime)
                self.assertEqual(7300, saved['previous_compute_seconds'])
                self.assertEqual(10800, saved['budget_policy']['worker_limit_seconds'])

    def test_cost_and_reliability_failures_cannot_be_overridden_by_budget_flags(self):
        changes = [
            lambda r: r['budget'].update({'200_family_p95_two_attempt_hours': 5.01}),
            lambda r: r['budget'].update({'200_family_p95_two_attempt_hours': float('nan')}),
            lambda r: r['budget'].update({'200_family_conservative_peak_additional_GiB': -1}),
            lambda r: r['budget_policy'].update({'worker_limit_seconds': 999999}),
            lambda r: r.update(executed_pairs=19),
            lambda r: r['modes']['T0'].update(native_archives_verified=19),
            lambda r: r.update(sources=[]),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index), self.registration_fixture() as (base, path, report, protocol, runtime):
                change(report)
                path.write_text(json.dumps(report), encoding='utf-8')
                with self.assertRaises(ValueError):
                    validation.authorize(protocol, path, runtime)
                self.assertFalse((base / 'validation-registration-v8.json').exists())

    def test_mixed_calibration_source_identity_is_rejected(self):
        with self.registration_fixture() as (_, path, report, protocol, runtime):
            report['sources'].append(deepcopy(report['sources'][0]))
            report['sources'][1]['code']['contract_v2.py'] = 'different'
            path.write_text(json.dumps(report), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'mixed identities'):
                validation.authorize(protocol, path, runtime)

    def test_original_registration_remains_readable_but_cannot_start_new_execution(self):
        with self.registration_fixture() as (base, path, report, protocol, runtime), \
                patch.object(validation, 'cumulative_seconds', return_value=0):
            current = validation.authorize(protocol, path, runtime)
            current_bytes = (base / 'validation-registration-v8.json').read_bytes()
            report.pop('budget_policy')
            report['budget']['200_family_p95_two_attempt_hours'] = 3.8
            path.write_text(json.dumps(report), encoding='utf-8')
            old = {k: v for k, v in current.items() if k not in ('budget_policy', 'fingerprint')}
            old.update(calibration_report_sha256=sha256(path),
                       addendum_sha256=sha256(validation.LEGACY_ADDENDUM))
            old['fingerprint'] = digest(old)
            old_path = base / 'validation-registration.json'
            old_path.write_text(json.dumps(old), encoding='utf-8')
            old_bytes = old_path.read_bytes()
            self.assertEqual(old, validation.authorize(protocol, path, runtime, reporting=True))
            with self.assertRaisesRegex(ValueError, 'budget policy'):
                validation.authorize(protocol, path, runtime)
            self.assertEqual(old_bytes, old_path.read_bytes())
            self.assertEqual(current_bytes, (base / 'validation-registration-v8.json').read_bytes())

    def test_cumulative_usage_keeps_failed_and_retried_batches_and_takes_larger_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            for name, summary, progress in [('teacher-old', 7190, 7200),
                                            ('teacher-validation-v8', 12, 10),
                                            ('teacher-failed', None, 20)]:
                batch = base / name
                batch.mkdir()
                if summary is not None:
                    (batch / 'summary.json').write_text(json.dumps({'worker_seconds': summary}), encoding='utf-8')
                (batch / 'compute-progress.json').write_text(json.dumps({'worker_seconds': progress}), encoding='utf-8')
            with patch.object(validation, 'BASE', base):
                self.assertEqual(7232, validation.cumulative_seconds())


if __name__ == '__main__':
    unittest.main()
