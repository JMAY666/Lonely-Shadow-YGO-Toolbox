"""Regression boundaries found in real correction diagnostics."""
import unittest
from unittest.mock import patch
from teacher_p3 import bounded_search, choose, microchoice, decision_key, board_score


def bundle(message=11, choices=2):
    return {'observation': {'cards': []}, 'candidates': [
        {'response': f'{index:02x}', 'public': {'message': message, 'cancel': False,
         'selection': [{'kind': 'pass' if message == 16 else 'activate'}]}}
        for index in range(choices)]}


class CorrectionTests(unittest.TestCase):
    def test_stop_alternative_does_not_displace_promising_third_branch(self):
        root = bundle(11, 4)
        visited = []
        def expand(path):
            visited.append(path[0])
            return {'bundle': {'observation': {'value': 10 if path[0] == 2 else 0}, 'candidates': []}}
        result = bounded_search(root, expand, lambda b: list(range(len(b['candidates']))),
                                lambda b: b['observation'].get('value', 0), max_depth=1,
                                max_nodes=4, branching=3, extra_candidate=lambda b: 3)
        self.assertEqual([0, 1, 2, 3], visited)
        self.assertEqual(2, result['index'])
        self.assertEqual(4, result['nodes'])

    def test_pending_starter_cost_and_chain_do_not_erase_its_potential(self):
        state = bundle(15, 1)
        state['observation']['cards'] = [{'controller': 0, 'location': 4,
            'position': 1, 'code': 20001443, 'disabled': False}]
        state['observation']['normal_used'] = 1
        empty = board_score(state)
        state['candidates'][0]['public']['context'] = {'handler_code': 20001443}
        self.assertGreater(board_score(state), empty)
        state['candidates'][0]['public'].pop('context')
        state['observation']['chains'] = [{'link': 1, 'effect': {'handler_code': 20001443}}]
        self.assertGreater(board_score(state), empty)
        state['observation']['chains'][0]['effect'] = {'identity_known': False}
        self.assertEqual(board_score(state), empty)

    def test_irrelevant_normal_summon_is_not_better_than_retaining_resources(self):
        from copy import deepcopy
        before = {'observation': {'cards': [{'controller': 0, 'location': 2,
                   'code': 14558127}] * 3, 'normal_used': 0}, 'candidates': []}
        after = deepcopy(before)
        after['observation']['cards'][0] = {'controller': 0, 'location': 4, 'code': 14558127,
                                           'position': 1, 'disabled': False}
        after['observation']['normal_used'] = 1
        self.assertLess(board_score(after), board_score(before))

    def test_spending_normal_summon_preserves_value_of_legal_starter_effect(self):
        hand = [{'controller': 0, 'location': 2, 'code': 55273560},
                {'controller': 0, 'location': 2, 'code': 14558127}]
        before = {'observation': {'cards': hand, 'normal_used': 0, 'normal_limit': 1}, 'candidates': []}
        after = {'observation': {'cards': [hand[1], {'controller': 0, 'location': 4,
                  'position': 1, 'code': 55273560, 'disabled': False}],
                  'normal_used': 1, 'normal_limit': 1}, 'candidates': [
                  {'public': {'selection': [{'kind': 'activate', 'card': {'code': 55273560}}]}}]}
        self.assertGreater(board_score(after), board_score(before))
        after['candidates'] = []
        self.assertLess(board_score(after), board_score(before))

    def test_interrupted_macro_preserves_all_already_attempted_microchoices(self):
        def expand(path, allowance, deadline):
            expand.attempted_nodes = 3
            raise ValueError('cumulative budget exhausted')
        expand.accepts_budget = True
        result = bounded_search(bundle(), expand, lambda b: [0, 1], lambda b: 0)
        self.assertEqual(3, result['nodes'])
        self.assertIsNone(result['index'])

    def test_empty_chain_repetitions_are_not_mistaken_for_strategy_cycles(self):
        root = bundle(11, 1)
        empty = bundle(16, 1)
        calls = []
        class Session:
            def probe(self, state, paths):
                calls.append(list(paths))
                return {'status': 'ok', 'batches': ['hidden' if len(paths) == 4 else 'empty'],
                        'boundary_raw': '1000', 'state': {'turn': 1}, 'private_cards': []}
        with patch('teacher_p3.build', side_effect=lambda s, _: root if s['raw'] == '0b00' else empty), \
                patch('teacher_p3.next_prompt', side_effect=lambda b: ('1000', b == ['hidden'])):
            result = choose(Session(), {'raw': '0b00'}, {}, avoid_state_keys=[decision_key(empty)])
        self.assertEqual(4, result['nodes'])
        self.assertEqual(1, result['uncertain_branches'])
        self.assertEqual([1, 2, 3, 4], [len(p) for p in calls])

    def test_cancel_back_to_executed_strategic_window_is_pruned(self):
        root, prior = bundle(15), bundle(11)
        root['candidates'] = root['candidates'][:1]
        class Session:
            def probe(self, state, paths):
                return {'status': 'ok', 'batches': ['idle'], 'boundary_raw': '0b00',
                        'state': {'turn': 1}, 'private_cards': []}
        with patch('teacher_p3.build', side_effect=lambda s, _: root if s['raw'] == '0f00' else prior), \
                patch('teacher_p3.next_prompt', return_value=('0b00', False)):
            result = choose(Session(), {'raw': '0f00'}, {}, avoid_state_keys=[decision_key(prior)])
        self.assertIsNone(result['index'])
        self.assertEqual('visible_decision_cycle', result['failures'][0]['error'])

    def test_only_unique_completion_can_bypass_material_search(self):
        value = bundle(15)
        value['candidates'][0]['public']['selection'] = [{'kind': 'card'}]
        value['candidates'][1]['public'].update(cancel=True, selection=[])
        self.assertEqual(0, microchoice(value)['index'])
        value['candidates'].append({'public': {'message': 15, 'cancel': False,
                                              'selection': [{'kind': 'card'}]}})
        self.assertIsNone(microchoice(value))


if __name__ == '__main__':
    unittest.main()
