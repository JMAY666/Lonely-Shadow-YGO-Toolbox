import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import validation_p3 as validation
from provenance import sha256


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

    def test_registration_requires_budget_and_cannot_be_rewritten_after_outcomes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            base = root / '.local/ygo-learning/p2-p3'
            base.mkdir(parents=True)
            report_path = base / 'report/summary.json'
            report_path.parent.mkdir()
            addendum = root / 'protocol.md'
            addendum.write_text('pre-registered selection', encoding='utf-8')
            teacher = sha256(Path(validation.__file__).with_name('teacher_p3.py'))
            runtime = {'rules': 'fixed'}
            report = {'scope': 'training_calibration_only_no_independent_quality_claim',
                'protocol_fingerprint': 'protocol', 'families': 20,
                'budget': {'time_gate_passed': True, 'disk_gate_passed': True,
                           '200_family_p95_two_attempt_hours': 3.8,
                           '200_family_conservative_peak_additional_GiB': 4.5},
                'modes': {mode: {'all_full_replays_verified': True, 'native_archives_verified': 20}
                          for mode in ('B1', 'T0')},
                'sources': [{'code': {'teacher_p3.py': teacher}, 'runtime': runtime,
                             'fast_animation_requested': True}] * 4}
            report_path.write_text(json.dumps(report), encoding='utf-8')
            protocol = {'fingerprint': 'protocol', 'families': [
                {'id': str(i), 'split': 'validation'} for i in range(40)]}
            with patch.object(validation, 'ROOT', root), patch.object(validation, 'BASE', base), \
                    patch.object(validation, 'ADDENDUM', addendum), \
                    patch.object(validation, 'cumulative_seconds', return_value=7190) as compute:
                with self.assertRaisesRegex(ValueError, 'remaining'):
                    validation.authorize(protocol, report_path, runtime)
                with self.assertRaisesRegex(ValueError, 'no prior registration'):
                    validation.authorize(protocol, report_path, runtime, reporting=True)
                compute.return_value = 0
                saved = validation.authorize(protocol, report_path, runtime)
                self.assertEqual(saved, validation.authorize(protocol, report_path, runtime))
                addendum.write_text('changed after inspection', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'cannot be changed'):
                    validation.authorize(protocol, report_path, runtime)


if __name__ == '__main__':
    unittest.main()
