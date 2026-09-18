from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trainer'))
from modular import Modular
from planning_preferences import advance_resources, resource_cost, cost_key, PREFERENCES, DEFAULT_PREFERENCE


def state(*locations):
    return {'cards': [{'instance_id': i+1, 'controller': 0, 'location': location} for i, location in enumerate(locations)]}


class ResourcePreferenceTests(unittest.TestCase):
    def test_actual_initial_resources_are_counted_once_without_draw_offsets_or_token_costs(self):
        initial = state(2, 1, 1, 64, 4)
        following = state(4, 2, 16, 4, 16, 4)  # The sixth physical card is a newly created token.
        ledger = advance_resources(initial, following)
        cost = resource_cost(ledger)
        self.assertEqual({key: cost[key] for key in ('hand', 'main', 'extra', 'other', 'total')},
                         {'hand': 1, 'main': 2, 'extra': 1, 'other': 1, 'total': 5})
        self.assertEqual(cost['status'], 'complete')
        recovered = state(2, 16, 16, 64, 16, 16)
        before = deepcopy(ledger)
        second = advance_resources(following, recovered, ledger)
        self.assertEqual(resource_cost(second), cost)
        self.assertEqual(ledger, before)
        third = advance_resources(recovered, following, second)
        self.assertEqual(resource_cost(third), cost)

    def test_continuation_only_counts_newly_used_resources(self):
        current = state(4, 2, 1, 64)
        following = state(4, 4, 1, 64)
        cost = resource_cost(advance_resources(current, following))
        self.assertEqual((cost['hand'], cost['main'], cost['extra'], cost['other']), (1, 0, 0, 0))

    def test_unknown_instances_are_not_presented_as_free_resources(self):
        unknown = {'cards': [{'controller': 0, 'location': 1}]}
        cost = resource_cost(advance_resources(unknown, state()))
        self.assertEqual(cost['status'], 'unassessed')
        self.assertGreater(cost_key({'resource_cost': cost}), cost_key({'resource_cost': {'status': 'complete', 'hand': 3}}))

    def test_four_preferences_and_three_equal_average_scores(self):
        def candidate(name, steps, terminal, hand, main=0, extra=0):
            return {'id': name, 'remaining': steps, 'goal_met': True, 'conditional': False,
                    'evaluation': {'marked_cards': terminal, 'marked_effects': 0},
                    'resource_cost': {'status': 'complete', 'hand': hand, 'main': main, 'extra': extra, 'other': 0}}
        candidates = [candidate('cheap', 10, 1, 0, 20), candidate('large', 9, 4, 3),
                      candidate('short', 1, 1, 2), candidate('average', 3, 3, 1)]
        for preference, expected in [('cheapest', 'cheap'), ('largest', 'large'), ('shortest', 'short'), ('balanced', 'average')]:
            ranked = deepcopy(candidates); Modular.rank(ranked, preference)
            self.assertEqual(ranked[0]['id'], expected)
            for c in ranked:
                scores = c['ranking']
                self.assertAlmostEqual(scores['average'], (scores['resources']+scores['steps']+scores['terminal'])/3, delta=.01)
        self.assertEqual(PREFERENCES, ('cheapest', 'largest', 'shortest', 'balanced'))
        self.assertEqual(DEFAULT_PREFERENCE, 'largest')

    def test_equal_hand_cost_uses_combined_main_and_extra_before_other_tiebreakers(self):
        a = {'resource_cost': {'status': 'complete', 'hand': 1, 'main': 2, 'extra': 2, 'other': 0}}
        b = {'resource_cost': {'status': 'complete', 'hand': 1, 'main': 0, 'extra': 5, 'other': 0}}
        self.assertLess(cost_key(a), cost_key(b))
        b['resource_cost'].update(main=4, extra=0)
        self.assertEqual(cost_key(a), cost_key(b))


if __name__ == '__main__': unittest.main()
