"""Search correctness and hidden-future boundaries, independent of engine scores."""
import unittest
from teacher_p3 import bounded_search


def node(name, count=2, score=0):
    return {'observation': {'name': name, 'score': score},
            'candidates': [{'public': {'id': i}} for i in range(count)]}


class SearchTests(unittest.TestCase):
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
