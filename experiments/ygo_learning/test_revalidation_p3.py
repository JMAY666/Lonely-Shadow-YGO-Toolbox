"""Recovery must not hide a changed decision/state or reset cumulative limits."""
from copy import deepcopy
import unittest

from revalidation_p3 import budget_preflight, compare_record


class RevalidationTests(unittest.TestCase):
    def record(self):
        state = {'raw': '05', 'player': 0, 'state': {'lp': [8000, 8000], 'turn': 1},
                 'learning': {'cards': [{'attack': 1800}]}, 'effects': {'choices': [10]},
                 'version': 1, 'node': 5, 'learning_query_us': 25}
        return {'family_id': 'f', 'scenario': 'actual_draw', 'mode': 'B1', 'expansion_sha256': 'same',
                'steps': [{'before': deepcopy(state), 'after': deepcopy(state), 'response': '0100'}],
                'final': deepcopy(state), 'goal': {'success': True}, 'status': 'turn_completed',
                'actual_draw_count': 1, 'terminal_goal_view': {'cards': [10]},
                '_native_first_turn_terminal': {'turn': 2, 'lp': [8000, 8000], 'cards': [10]}}

    def test_timing_and_transport_ids_do_not_change_semantics(self):
        source = self.record()
        candidate = deepcopy(source)
        candidate['steps'][0]['before'].update(version=99, node=88, learning_query_us=500)
        result = compare_record(source, candidate)
        self.assertTrue(result['full_prefix_equal'])
        self.assertEqual(result['reference_prefix_sha256'], result['candidate_prefix_sha256'])

    def test_same_goal_cannot_hide_changed_response_dynamic_state_or_effect(self):
        source = self.record()
        for field in ('response', 'dynamic', 'effect', 'missing_step', 'following'):
            candidate = deepcopy(source)
            if field == 'response': candidate['steps'][0]['response'] = '0200'
            if field == 'dynamic': candidate['steps'][0]['before']['learning']['cards'][0]['attack'] = 0
            if field == 'effect': candidate['steps'][0]['before']['effects']['choices'] = [11]
            if field == 'missing_step': candidate['steps'] = []
            if field == 'following': candidate['steps'][0]['after']['state']['lp'][0] = 7000
            with self.subTest(field=field):
                self.assertFalse(compare_record(source, candidate)['full_prefix_equal'])

    def test_random_condition_and_policy_cannot_be_substituted(self):
        source = self.record()
        for field in ('expansion_sha256', 'family_id', 'mode', 'scenario'):
            candidate = deepcopy(source)
            candidate[field] = 'different'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'identity/condition'):
                compare_record(source, candidate)

    def test_final_state_and_actual_draws_are_checked_separately(self):
        source = self.record()
        candidate = deepcopy(source)
        candidate['final']['state']['lp'][0] = 0
        candidate['actual_draw_count'] = 2
        result = compare_record(source, candidate)
        self.assertTrue(result['full_prefix_equal'])
        self.assertFalse(result['final_checkpoint_equal'])
        self.assertFalse(result['outcome_equal'])

    def test_only_last_post_terminal_snapshot_uses_the_native_boundary(self):
        source = self.record()
        source['steps'][0]['after']['state']['turn'] = 2
        candidate = deepcopy(source)
        candidate['steps'][0]['after']['state'].update(turn=3, lp=[8000, 6000])
        result = compare_record(source, candidate)
        self.assertTrue(result['full_prefix_equal'])
        self.assertFalse(result['raw_successor_snapshots_equal'])
        candidate['_native_first_turn_terminal']['lp'][0] = 7000
        self.assertFalse(compare_record(source, candidate)['full_prefix_equal'])
        self.assertFalse(compare_record(source, candidate)['terminal_state_equal'])

    def test_missing_native_boundary_and_unsupported_result_never_hide_differences(self):
        source = self.record()
        source['steps'][0]['after']['state']['turn'] = 2
        missing = deepcopy(source)
        missing['_native_first_turn_terminal'] = None
        with self.assertRaisesRegex(ValueError, 'no native journal boundary'):
            compare_record(missing, deepcopy(missing))
        left = deepcopy(source)
        left['status'] = 'unsupported'
        left['_native_first_turn_terminal'] = None
        right = deepcopy(left)
        right['steps'][0]['after']['state']['turn'] = 3
        self.assertFalse(compare_record(left, right)['full_prefix_equal'])

    def test_post_terminal_action_cannot_be_normalized_away(self):
        source = self.record()
        source['steps'][0]['before']['state']['turn'] = 2
        with self.assertRaisesRegex(ValueError, 'beyond'):
            compare_record(source, deepcopy(source))

    def budget(self):
        return {'200_family_p95_two_attempt_hours': 5.5,
                '200_family_conservative_peak_additional_GiB': 4.4, 'remaining_directory_GiB': 7.2}

    def test_more_worker_time_does_not_waive_pilot_cost_gate(self):
        preflight = budget_preflight(self.budget(), 5800)
        self.assertEqual(5000, preflight['remaining_worker_seconds'])
        self.assertEqual(3960, preflight['full_validation_projected_seconds'])
        self.assertEqual(0, preflight['additional_worker_allowance_required_seconds'])
        self.assertEqual(9760, preflight['minimum_total_worker_limit_seconds'])
        self.assertFalse(preflight['budget_gates_passed'])
        self.assertFalse(budget_preflight(self.budget(), 0)['budget_gates_passed'])
        self.assertFalse(preflight['budget_limits_changed'])

    def test_zero_remaining_disk_overrun_and_nonfinite_cost_fail_closed(self):
        budget = self.budget()
        budget['200_family_p95_two_attempt_hours'] = 3.0
        self.assertTrue(budget_preflight(budget, 0)['budget_gates_passed'])
        self.assertEqual(3500, budget_preflight(budget, 7300)['remaining_worker_seconds'])
        self.assertEqual(0, budget_preflight(budget, 10900)['remaining_worker_seconds'])
        budget['remaining_directory_GiB'] = 2.0
        self.assertFalse(budget_preflight(budget, 0)['budget_gates_passed'])
        for invalid in (float('nan'), float('inf'), 0, -1, True):
            budget['200_family_p95_two_attempt_hours'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                budget_preflight(budget, 0)


if __name__ == '__main__':
    unittest.main()
