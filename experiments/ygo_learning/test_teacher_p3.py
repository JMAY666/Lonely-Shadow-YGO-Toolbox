"""Search correctness and hidden-future boundaries, independent of engine scores."""
import unittest
from unittest.mock import patch
from teacher_p3 import bounded_search, opponent_response, board_score, choose


def node(name, count=2, score=0):
    return {'observation': {'name': name, 'score': score},
            'candidates': [{'public': {'id': i}} for i in range(count)]}


class SearchTests(unittest.TestCase):
    def test_opponent_microchoices_consume_node_and_depth_budgets(self):
        allowances = []
        def expand(path, allowance, deadline):
            allowances.append(allowance)
            return {'bundle': node(str(path), score=1), 'decision_nodes': min(3, allowance)}
        expand.accepts_budget = True
        result = bounded_search(node('root'), expand, lambda b: [0, 1],
                                lambda b: b['observation']['score'], max_nodes=5, max_depth=3)
        self.assertEqual([3, 2], allowances)
        self.assertEqual(5, result['nodes'])
        self.assertTrue(all(row['native_depth'] <= 3 for row in result['trace']))

    def test_all_failed_branches_do_not_return_an_untested_action(self):
        result = bounded_search(node('root'), lambda path: {'error': 'unsupported'},
                                lambda b: [0, 1], lambda b: 0)
        self.assertIsNone(result['index'])
        self.assertEqual('no_evaluable_search_branch', result['stopped'])

    def test_declared_opponent_pass_and_ash_have_explicit_boundaries(self):
        raw = '100100000000000000000000'
        self.assertEqual('ffffffff', opponent_response(raw, 'no_extra_response')['response'])
        self.assertEqual('ai', opponent_response(raw, 'one_ash')['response'])
        with self.assertRaisesRegex(ValueError, 'unknown_opponent'):
            opponent_response(raw, 'unknown')
        with self.assertRaisesRegex(ValueError, 'not_an_opponent'):
            opponent_response('100000000000000000000000', 'one_ash')

    def test_retaining_required_hand_matters_after_synchro_goal(self):
        def board(hand):
            return {'observation': {'cards': [{'controller': 0, 'location': 4, 'position': 1,
                    'code': 69248256, 'disabled': False}] +
                    [{'controller': 0, 'location': 2, 'code': 14558127}] * hand}}
        goal = {'minimum_retained_hand_cards': 2}
        self.assertGreater(board_score(board(2), goal), board_score(board(0), goal))

    def test_opponent_settlement_preserves_each_guard_and_stops_before_hidden_score(self):
        root = {'observation': {'cards': []}, 'candidates': [
            {'public': {'message': 11, 'selection': [{'kind': 'activate'}]}, 'response': '01'}]}
        raw = '100100000000000000000000'
        class Session:
            def __init__(self): self.paths = []
            def probe(self, state, paths):
                self.paths.append(list(paths))
                return {'status': 'ok', 'batches': [raw] if len(paths) == 1 else ['hidden'],
                        'boundary_raw': raw, 'state': {'turn': 1}, 'private_cards': []}
        session = Session()
        with patch('teacher_p3.build', return_value=root), patch('teacher_p3.next_prompt',
                side_effect=lambda batches: (raw, batches == ['hidden'])):
            result = choose(session, {'raw': '0b00'}, {}, scenario='no_extra_response')
        self.assertEqual(2, result['nodes'])
        self.assertEqual(1, result['uncertain_branches'])
        self.assertEqual([1, 2], [len(p['guards']) for p in result['probes']])
        self.assertEqual('ffffffff', session.paths[1][-1].split(':')[1])

    def test_mid_search_stop_preserves_nodes_and_never_returns_an_action(self):
        def expand(path):
            if path == (1,):
                raise ValueError('two-hour budget exhausted')
            return {'bundle': node('child', 0, 1)}
        result = bounded_search(node('root'), expand, lambda b: list(range(len(b['candidates']))),
                                lambda b: b['observation']['score'])
        self.assertIsNone(result['index'])
        self.assertEqual(2, result['nodes'])
        self.assertEqual(1, len(result['trace']))
        self.assertIn('two-hour', result['stopped'])

    def test_uses_each_branch_prefix_and_finds_two_step_improvement(self):
        visited = []
        def expand(path):
            visited.append(path)
            return {'bundle': node(str(path), score=10 if path == (1, 0) else 0)}
        result = bounded_search(node('root'), expand, lambda b: list(range(len(b['candidates']))),
                                lambda b: b['observation']['score'], max_depth=2, max_nodes=6)
        self.assertEqual(1, result['index'])
        self.assertIn((1, 0), visited)
        self.assertNotIn((1, 0, 0), visited)
        self.assertLessEqual(result['nodes'], 6)

    def test_hidden_future_does_not_enter_scoring_or_change_choice(self):
        choices = []
        for hidden_score in (100, -100):
            scored = []
            def expand(path):
                return {'uncertain': path[0] == 1,
                        'bundle': node('secret' if path[0] == 1 else 'safe', 0, hidden_score)}
            def score(bundle):
                self.assertNotEqual('secret', bundle['observation']['name'])
                scored.append(bundle['observation']['name'])
                return 0
            result = bounded_search(node('root'), expand, lambda b: list(range(len(b['candidates']))), score)
            choices.append(result['index'])
            self.assertEqual(1, result['uncertain_branches'])
        self.assertEqual(choices[0], choices[1])

    def test_failure_is_preserved_and_budget_counts_all_microchoices(self):
        result = bounded_search(node('root'), lambda p: {'error': 'search_limit'},
                                lambda b: [0, 1], lambda b: 0, max_nodes=1)
        self.assertEqual(1, result['nodes'])
        self.assertEqual(1, len(result['failures']))
        self.assertEqual('search_limit', result['failures'][0]['error'])


if __name__ == '__main__':
    unittest.main()
