from copy import deepcopy
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import atomic_json
from duel import match, project, validate_hand
import test_store


def rows(code, count=1, **extra):
    return {'code': code, 'count': count, 'constraint': '', **extra}


def plan():
    return {'id': str(uuid.uuid4()), 'name': '合成主线', 'classification': {'mode': 'manual', 'tag_ids': ['custom:a'], 'primary_ids': []},
            'requirements': {'main': [rows(1, 2)], 'extra': [rows(9)], 'opening': [rows(1, 2)], 'warnings': []},
            'review': {'complete': True, 'nodes': [{'id': 'initial', 'kind': 'initial', 'state': {'cards': []}}, {'id': 's1', 'kind': 'step'}], 'module_graph': {'modules': [{'id': 'a', 'player': 0}], 'connections': [{'from': 'a', 'decision': {'selection': []}}]}}, 'branches': []}


class DuelRulesTests(unittest.TestCase):
    def setUp(self):
        self.deck = {'main': [1, 1, 2, 2, 3], 'extra': [9], 'side': [1, 9, 9]}
        self.plan = plan()

    def test_hand_exact_counts_and_main_only(self):
        validate_hand(self.deck, 5, self.deck['main'])
        validate_hand(self.deck, 2, [1, 1])
        for count, hand in [(0, []), (True, [1]), ('2', [1, 1]), (1.5, [1]), (6, [1]*6),
                            (2, [1]), (2, [1, 2, 3]), (3, [1, 1, 1]), (2, [1, 9]), (2, [1, True])]:
            with self.subTest(count=count, hand=hand), self.assertRaises(ValueError): validate_hand(self.deck, count, hand)

    def test_minimum_opening_does_not_deduct_configuration_resources(self):
        output, stage, _ = project(self.plan, self.deck, [1, 1, 2, 2, 3])
        self.assertIsNotNone(output)
        self.assertEqual(stage, '')
        self.assertEqual(project(self.plan, self.deck, [1, 2, 2, 3])[1], 'opening')
        self.plan['requirements']['main'][0]['count'] = 3
        self.assertEqual(project(self.plan, self.deck, [1, 1, 2])[1], 'resources')

    def test_explicit_second_turn_routes_are_not_first_turn_tutorials(self):
        self.plan['expansion'] = {'turn_order': 'second'}
        self.assertEqual(project(self.plan, self.deck, [1, 1, 2])[1], 'turn_order')
        self.plan['expansion']['turn_order'] = 'first'
        self.assertIsNotNone(project(self.plan, self.deck, [1, 1, 2])[0])

    def test_regions_and_mutually_exclusive_branches_keep_source_immutable(self):
        for key, count in [('a', 1), ('b', 2), ('c', 1)]:
            report = deepcopy(self.plan)
            report['requirements']['extra'] = [rows(9, count)]
            # Branches inherit the main opening; independent branch opening is ignored.
            report['requirements']['opening'] = [rows(999, 50)]
            self.plan['branches'].append({'id': key, 'name': key, 'valid': True,
                'source': {'node_id': 's1', 'seq': 10}, 'report': report})
        self.plan['branches'].append({'id': 'orphan', 'source': {'node_id': 'missing', 'seq': 10}, 'report': deepcopy(self.plan)})
        before = deepcopy(self.plan)
        result, _, _ = project(self.plan, self.deck, [1, 1, 2])
        self.assertEqual([b['id'] for b in result['branches']], ['a', 'c'])
        self.assertEqual(len(result['duel_excluded_branches']), 2)
        self.assertEqual(self.plan, before)
        self.deck['extra'] = []
        self.assertEqual(project(self.plan, self.deck, [1, 1, 2])[1], 'resources')

    def test_generic_cost_uses_distinct_remaining_cards_and_unknowns_fail_closed(self):
        self.plan['requirements']['opening'].append(rows(None, 2, constraint='任意手牌'))
        self.assertEqual(project(self.plan, self.deck, [1, 1, 2])[1], 'opening')
        self.assertIsNotNone(project(self.plan, self.deck, [1, 1, 2, 3])[0])
        self.plan['requirements']['opening'][-1]['constraint'] = '任意符合实际费用条件的手牌'
        self.assertEqual(project(self.plan, self.deck, [1, 1, 2, 3])[1], 'incomplete')
        for changes in ({'opening': None}, {'warnings': ['缺少实例']}, {'main': [rows(True)]}, {'opening': [rows(1, 0)]}):
            route = plan(); route['requirements'].update(changes)
            self.assertEqual(project(route, self.deck, [1, 1, 2])[1], 'incomplete')
        self.plan.pop('requirements')
        self.assertEqual(project(self.plan, self.deck, [1, 1, 2])[1], 'incomplete')


class DuelStoreTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def test_stable_tag_union_matching_metadata_refresh_and_read_only_files(self):
        self.store.library.builtins = {key: {'id': key, 'name': '同一显示名称', 'aliases': [], 'setcode': None,
                                            'include_cards': [], 'exclude_cards': []} for key in ['custom:a', 'custom:b', 'custom:c']}
        selected = {'tag_ids': ['custom:a', 'custom:b'], 'primary_ids': ['custom:a']}
        saved = self.store.save_deck({'name': '决斗合成构筑', 'deck': self.deck, 'tag_selection': selected})
        p = plan()
        p['requirements'] = {'main': [rows(55144522, 2)], 'extra': [], 'opening': [rows(55144522, 2)], 'warnings': []}
        path = self.store.plan_path(p['id']); atomic_json(path, p)
        other = deepcopy(p); other['id'] = str(uuid.uuid4()); other['classification']['tag_ids'] = ['custom:c']
        atomic_json(self.store.plan_path(other['id']), other)
        files = {f: f.read_bytes() for f in [path, *self.store.decks.glob('*.ydk')]}
        body = {'deck_id': saved['id'], 'revision': saved['revision'], 'hand_count': 3, 'hand': [55144522, 55144522, 1184620]}
        result = match(self.store, body)
        self.assertEqual([v['id'] for v in result['matches']], [p['id']])
        self.assertEqual(result['counts']['tags'], 1)
        for f, content in files.items(): self.assertEqual(f.read_bytes(), content)
        self.assertEqual(self.store.list_decks()[0]['tag_selection'], selected)
        self.store.library.builtins['custom:a']['name'] = '更新标签名'
        self.assertEqual(self.store.list_decks()[0]['tag_names']['custom:a'], '更新标签名')
        self.assertEqual(self.store.get_deck(saved['id'])['tag_names']['custom:a'], '更新标签名')
        with self.assertRaisesRegex(ValueError, '修改'): match(self.store, {**body, 'revision': 'old'})
        saved = self.store.save_deck({**saved, 'tag_selection': {'tag_ids': [], 'primary_ids': []}})
        result = match(self.store, {**body, 'revision': saved['revision']})
        self.assertIn('没有可用 Tag', result['reason'])
        self.assertEqual(result['matches'], [])


if __name__ == '__main__': unittest.main()
