"""A valid archive cannot stand in for a different family or policy result."""
from copy import deepcopy
import unittest
from report_p3 import bind_summary, verify_pair_conditions


class ReportTests(unittest.TestCase):
    def record(self):
        return {'family_id': 'one', 'mode': 'T0', 'scenario': 'actual_draw', 'status': 'turn_completed',
                'replayed': True, 'model_calls': 3, 'nodes': 9, 'multi_choice_windows': 3,
                'single_choice_windows': 1, 'uncertain_branches': 2, 'seconds': 4.5,
                'goal': {'success': True}, 'native_evidence_bytes': 55, 'expansion_sha256': 'a'}

    def test_mislabelled_archive_and_changed_result_or_cost_are_rejected(self):
        record = self.record()
        self.assertEqual(record, bind_summary(record, record))
        for field, changed in [('family_id', 'two'), ('mode', 'B1'), ('scenario', 'one_ash'),
                               ('goal', {'success': False}), ('seconds', 0), ('nodes', 0)]:
            summary = deepcopy(record)
            summary[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                bind_summary(summary, record)

    def test_different_random_conditions_are_not_a_paired_comparison(self):
        with self.assertRaisesRegex(ValueError, 'condition'):
            verify_pair_conditions({('one', 'B1'): 'a', ('one', 'T0'): 'b'})
        verify_pair_conditions({('one', 'B1'): 'a', ('one', 'T0'): 'a'})


if __name__ == '__main__':
    unittest.main()
