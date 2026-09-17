from collections import Counter
from copy import deepcopy
import itertools
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from opening_conditions import assignment, describe, evaluate, normalize_card, preview, match_hand
from expansion import draw_opening, validate_conditions
import test_expansion
import test_plan_library
import test_duel
import test_precompute
import test_automatic_duel
from app import Store, atomic_json, read_json
from plan_sharing import portable, validate
from modular_decisions import bind_variants, digest


def leaf(field, values, op='in'):
    return {'field': field, 'op': op, 'values': values}


def condition(*items, op='all'):
    return {'kind': 'condition', 'version': 1, 'rule': {'op': op, 'items': list(items)}}


def tuner(level):
    return condition({'field': 'level', 'op': 'eq', 'value': level}, leaf('monster_kind', ['tuner']))


def design(slots, banned=None):
    return {'hand_count': len(slots), 'slots': slots, 'banned': banned or []}


CATALOG = {i: {'id': i, 'name': f'卡{i}', 'type': 0x1021, 'level': i, 'race': 8192, 'attribute': 32, 'setcode': 0x1001} for i in (1, 2, 3)}
CATALOG.update({4: {'id': 4, 'name': '通常', 'type': 17, 'level': 4, 'race': 1, 'attribute': 1},
                5: {'id': 5, 'name': '魔法', 'type': 2, 'level': 0},
                6: {'id': 6, 'name': '超量', 'type': 0x800021, 'level': 3},
                7: {'id': 7, 'name': '连接', 'type': 0x4000021, 'level': 3}})


class ConditionTests(unittest.TestCase):
    def test_level_one_two_three_tuners_draw_real_copies_and_keep_definition(self):
        main = [1, 2, 3, 4, 4, 5]
        for level in (1, 2, 3):
            rules = design([4, tuner(level), None]); original = deepcopy(rules)
            hand, rest = draw_opening(main, rules, random.Random(7), CATALOG)
            self.assertEqual(hand[:2], [4, level]); self.assertEqual(Counter(hand + rest), Counter(main))
            self.assertEqual(rules, original); self.assertEqual(describe(tuner(level)), f'任意等级 {level} 调整')
            self.assertTrue(all(type(c) is int for c in hand))

    def test_overlap_requires_augmenting_paths_not_greedy(self):
        rules = design([condition(leaf('code', [1, 2])), condition(leaf('code', [1]))])
        for seed in range(30):
            self.assertEqual(draw_opening([1, 2], rules, random.Random(seed), CATALOG)[0], [2, 1])
        with self.assertRaisesRegex(ValueError, '交叉冲突'):
            validate_conditions([1, 4], design([condition(leaf('code', [1])), condition(leaf('code', [1]))]), CATALOG)
        for slots in ([1, tuner(1)], [tuner(1), tuner(1)]):
            with self.assertRaisesRegex(ValueError, '交叉冲突'): validate_conditions([1, 4], design(slots), CATALOG)
            self.assertEqual(draw_opening([1, 1], design(slots), catalog=CATALOG)[0], [1, 1])

    def test_solver_matches_exhaustive_oracle(self):
        pools = [[], [0], [1], [2], [0, 1], [1, 2], [0, 2], [0, 1, 2]]
        for candidates in itertools.product(pools, repeat=3):
            expected = any(all(copy in candidates[i] for i, copy in enumerate(p)) for p in itertools.permutations(range(3)))
            result = assignment(candidates)
            self.assertEqual(result is not None, expected, candidates)
            if result is not None: self.assertEqual(len(set(result)), 3)

    def test_and_or_not_inclusion_exclusion_and_missing_attributes(self):
        rule = condition(leaf('category', ['monster']), {'op': 'any', 'items': [leaf('code', [1]), leaf('code', [4])]},
                         {'op': 'not', 'items': [leaf('code', [1])]}, leaf('attribute', [1]), leaf('race', [1]))
        p = preview([1, 2, 3, 4, 5], design([rule]), CATALOG, {'kind': 'slots', 'index': 0})
        self.assertEqual([c['code'] for c in p['focus']['cards']], [4]); self.assertTrue(p['valid'])
        for field, expected in [('level', [3]), ('rank', [6]), ('link', [7])]:
            r = condition({'field': field, 'op': 'eq', 'value': 3})
            self.assertEqual(preview(list(CATALOG), design([r]), CATALOG)['slots'][0]['codes'], expected)
        not_level = condition({'op': 'not', 'items': [{'field': 'level', 'op': 'eq', 'value': 3}]})
        self.assertEqual(preview(list(CATALOG), design([not_level]), CATALOG)['slots'][0]['codes'], [1, 2, 4])
        non_tuner = condition(leaf('monster_kind', ['non_tuner']))
        self.assertEqual(preview([1, 4, 5], design([non_tuner]), CATALOG)['slots'][0]['codes'], [4])
        bounded = condition({'field': 'level', 'op': 'between', 'min': 1, 'max': 2}, leaf('code', [1], 'not_in'))
        self.assertEqual(draw_opening([1, 2, 3], design([bounded]), catalog=CATALOG)[0], [2])

    def test_bans_cover_full_opening_but_not_remaining_deck(self):
        any_tuner = condition(leaf('monster_kind', ['tuner']))
        rules = design([any_tuner, None], [tuner(1), tuner(2)])
        hand, rest = draw_opening([1, 2, 3, 4], rules, catalog=CATALOG)
        self.assertEqual(hand, [3, 4]); self.assertEqual(Counter(rest), Counter([1, 2]))
        for slots in ([1], [tuner(1)]):
            with self.assertRaises(ValueError): draw_opening([1, 4], design(slots, [any_tuner]), catalog=CATALOG)
        p = preview([4, 4], design([None], [tuner(1)]), CATALOG)
        self.assertTrue(p['valid']); self.assertIn('没有实际影响', p['warnings'][0])
        p = preview([1], design([1], [1]), CATALOG)
        self.assertFalse(p['valid']); self.assertIn('同时被指定和禁用', p['errors'][0])
        self.assertNotIn('还需要 0 张', '；'.join(p['errors']))

    def test_preview_distinguishes_raw_banned_and_other_required_occupancy(self):
        any_tuner = condition(leaf('monster_kind', ['tuner']))
        p = preview([1, 2, 3, 4], design([any_tuner, tuner(1)], [3]), CATALOG, {'kind': 'slots', 'index': 0})
        self.assertEqual((p['focus']['types'], p['focus']['copies'], p['focus']['usable_types']), (3, 3, 1))
        self.assertEqual([c['available_count'] for c in p['focus']['cards']], [0, 1, 0])
        self.assertIn('占用', p['focus']['cards'][0]['reason']); self.assertIn('禁止', p['focus']['cards'][2]['reason'])
        p = preview([1, 1, 4], design([any_tuner, tuner(1)]), CATALOG, {'kind': 'slots', 'index': 0})
        self.assertEqual(p['focus']['cards'][0]['available_count'], 1)
        duplicate_bans = preview([1, 4], design([None], [tuner(1), tuner(1)]), CATALOG, {'kind': 'banned', 'index': 1})
        self.assertEqual(duplicate_bans['focus']['cards'][0]['code'], 1)

    def test_conflict_reports_only_the_competing_subset_and_its_real_copy_count(self):
        a = condition(leaf('code', [1])); b = condition(leaf('code', [2]))
        p = preview([1, 2, 4], design([a, a, b]), CATALOG)
        message = p['errors'][0]
        self.assertIn('合计仅 1 张', message); self.assertIn('需要 2 张', message)
        self.assertIn('1「', message); self.assertIn('2「', message); self.assertNotIn('3「', message)

    def test_randomized_allocation_reaches_different_candidates_and_extra_copies(self):
        seen, copies = set(), set()
        for seed in range(150):
            hand, rest = draw_opening([1, 1, 1, 2, 3, 4], design([condition(leaf('monster_kind', ['tuner'])), None, None]), random.Random(seed), CATALOG)
            seen.add(hand[0]); copies.add(hand.count(1)); self.assertEqual(Counter(hand + rest), Counter([1, 1, 1, 2, 3, 4]))
        self.assertEqual(seen, {1, 2, 3}); self.assertIn(3, copies)

    def test_hand_matching_is_global_and_bans_apply_to_every_card(self):
        rules = design([condition(leaf('code', [1, 2])), tuner(1)])
        self.assertTrue(match_hand([1, 2], rules, CATALOG)[0])
        self.assertFalse(match_hand([1, 4], rules, CATALOG)[0])
        self.assertFalse(match_hand([1, 2, 3], {**rules, 'banned': [tuner(3)]}, CATALOG)[0])
        self.assertTrue(match_hand([1, 2], {**rules, 'banned': [4]}, CATALOG)[0])
        # Training filler slots are not route costs. Required slots at the end
        # remain requirements even when the current hand has fewer total cards.
        self.assertTrue(match_hand([1, 2], design([None, tuner(1), None, None, 2]), CATALOG)[0])
        self.assertFalse(match_hand([1], design([None, tuner(1), None, None, 2]), CATALOG)[0])

    def test_invalid_or_unreliable_rules_are_never_free_text(self):
        for value in ({'kind': 'condition', 'version': 2, 'rule': {}}, condition(leaf('effect_text', ['调整'])),
                      condition(leaf('race', [True])), condition(), condition({'field': 'level', 'op': 'eq', 'value': '3'})):
            with self.assertRaises(ValueError): normalize_card(value)
        p = preview([1, 2], design([tuner(1)]), {1: CATALOG[1]})
        self.assertFalse(p['valid']); self.assertIn('缺少卡牌资料', p['errors'][0])
        p = preview([1], design([tuner(1)]), {1: {'id': 1, 'type': 0x1021}})
        self.assertFalse(p['valid']); self.assertIn('缺少卡牌资料', p['errors'][0])

    def test_series_uses_packed_database_ids_and_not_display_names(self):
        r = condition(leaf('setcode', [1]))
        self.assertTrue(evaluate(r['rule'], 1, CATALOG[1]))
        self.assertTrue(evaluate(r['rule'], 1, {**CATALOG[1], 'setcode': str(0x1001 << 48)}))
        self.assertFalse(evaluate(r['rule'], 1, {**CATALOG[1], 'name': '系列1', 'setcode': 2}))


class ConditionIntegrationTests(unittest.TestCase):
    def test_conditional_design_persists_reopens_and_restarts_with_frozen_instance(self):
        f = test_expansion.ExpansionStoreTests(); f.setUp(); self.addCleanup(f.tearDown)
        rule = condition(leaf('category', ['spell']))
        settings = {'conditions': design([rule, None]), 'opponent_ai': True,
            'opponent_config': {'name': '条件对手', 'deck': f.deck,
                'conditions': design([condition(leaf('monster_kind', ['normal']))], [rule])}}
        meta = f.completed(settings)
        self.assertEqual(meta['expansion']['actual_opening'][0], 55144522)
        self.assertEqual(meta['expansion']['opponent_config']['actual_opening'], [1184620])
        self.assertEqual(meta['expansion']['conditions'], settings['conditions'])
        proc = MagicMock(pid=125); proc.poll.return_value = None
        with patch('app.subprocess.Popen', return_value=proc), patch('app.process_identity', return_value=None):
            result = f.store.restart(meta['id'])
        retry = read_json(f.store.session_path(result['id'])/'session.json')
        self.assertEqual(retry['expansion'], meta['expansion'])
        self.assertNotEqual(result['id'], meta['id'])
        # Saving is a separate completed attempt; restart intentionally abandons
        # its source draft, which must never be promoted back to a savable draft.
        f = test_expansion.ExpansionStoreTests(); f.setUp(); self.addCleanup(f.tearDown)
        meta = f.completed(settings)
        with patch.object(f.store, 'report', return_value=f.projection):
            saved = f.store.save_plan({'id': meta['id'], 'name': '条件保存', 'notes': ''})
        original = f.store.plan_path(meta['id']).read_bytes()
        reopened = Store(f.root).design_from(meta['id'])
        self.assertEqual(reopened['conditions'], saved['expansion']['conditions'])
        reopened['conditions']['slots'][0]['rule']['items'][0]['values'] = ['trap']
        self.assertFalse(preview(reopened['deck']['main'], reopened['conditions'], f.store.catalog.cards)['valid'])
        self.assertEqual(f.store.plan_path(meta['id']).read_bytes(), original)

    def test_sharing_preserves_editable_definition_and_rejects_forged_instance(self):
        p = test_plan_library.sample()
        p['expansion'].update(conditions=design([condition(leaf('code', [101, 102]))]), actual_opening=[101])
        document = {'format': 'ygo-trainer-plan', 'version': 1, 'plan': portable(p), 'tags': []}
        checked = validate(document)
        self.assertEqual(checked['plan']['expansion']['conditions'], p['expansion']['conditions'])
        for change in ('unknown', 'instance', 'record'):
            bad = deepcopy(document)
            if change == 'unknown': bad['plan']['expansion']['conditions']['slots'][0]['rule']['items'][0]['field'] = 'description'
            elif change == 'instance': bad['plan']['expansion']['actual_opening'] = [999]
            else: bad['plan']['initial_hand'][0]['code'] = 102
            with self.assertRaises(ValueError): validate(bad)

    def test_disabled_opponent_incomplete_settings_survive_sharing(self):
        p = test_plan_library.sample()
        p['expansion'].update(opponent_ai=False, opponent_config={'name': '保留设计', 'deck': p['deck'],
            'conditions': {'hand_count': 0, 'slots': [condition(leaf('code', [999]))], 'banned': []}})
        doc = {'format': 'ygo-trainer-plan', 'version': 1, 'plan': portable(p), 'tags': []}
        self.assertEqual(validate(doc)['plan']['expansion']['opponent_config']['conditions']['hand_count'], 0)
        doc['plan']['expansion']['opponent_ai'] = True
        with self.assertRaises(ValueError): validate(doc)

    def test_matching_collection_does_not_promote_unverified_route_substitution(self):
        p = test_duel.plan(); p['catalog'] = CATALOG
        p['requirements'].update(main=[test_duel.rows(1)], extra=[], opening=[test_duel.rows(1)])
        p['expansion'] = {'conditions': design([condition(leaf('monster_kind', ['tuner']))]), 'actual_opening': [1]}
        deck = {'main': [1, 2, 3, 4], 'extra': [], 'side': []}
        self.assertTrue(test_duel.project(p, deck, [1], CATALOG)[0])
        projected, stage, reason = test_duel.project(p, deck, [2], CATALOG)
        self.assertIsNone(projected); self.assertEqual(stage, 'incomplete'); self.assertIn('替换尚未验证', reason)
        self.assertEqual(test_duel.project(p, deck, [4], CATALOG)[1], 'opening')
        p['expansion']['conditions'] = design([1])
        self.assertEqual(test_duel.project(p, deck, [2], CATALOG)[1], 'opening')

    def test_legacy_training_filler_does_not_exclude_a_shorter_sufficient_hand(self):
        p = test_duel.plan()
        p['expansion'] = {'conditions': design([1, None, None, None, 1])}
        p['requirements'].update(extra=[], opening=[test_duel.rows(1, 2), test_duel.rows(None, 1, constraint='任意手牌')])
        deck = {'main': [1, 1, 2, 3, 4], 'extra': [], 'side': []}
        self.assertIsNotNone(test_duel.project(p, deck, [1, 1, 2])[0])
        self.assertEqual(test_duel.project(p, deck, [1, 1])[1], 'opening')
        self.assertEqual(test_duel.project(p, deck, [1, 2, 3])[1], 'opening')

    def test_modular_binding_does_not_alias_effects_for_same_tuner_properties(self):
        decision = {'message': 11, 'player': 0, 'selection': [{'kind': 'summon', 'card': {'code': 1, 'controller': 0, 'location': 2, 'sequence': 0}}]}
        prompt = {'message': 11, 'player': 0, 'mode': 'single', 'choices': [{'semantic': {'kind': 'summon', 'card': {'code': 2, 'controller': 0, 'location': 2, 'sequence': 0}}, 'response': '00000000'}]}
        self.assertTrue(evaluate(condition(leaf('monster_kind', ['tuner']))['rule'], 2, CATALOG[2]))
        self.assertEqual(bind_variants(decision, prompt, precise=False), [])

    def test_condition_source_change_invalidates_precomputed_candidates(self):
        f = test_precompute.PreparationTests(); f.setUp()
        source = {'conditions': design([tuner(1)])}
        f.modular.library.entries['p']['version'] = digest(source)
        value = f.prepare(); job = f.service.jobs[value['job']]
        job.update(status='ready', sid='sid', data={})
        source['conditions']['slots'][0] = tuner(2)
        f.modular.library.entries['p']['version'] = digest(source)
        self.assertEqual(f.poll(value)['status'], 'stale')

    def test_automatic_duel_matches_confirmed_real_hand_and_condition_bans(self):
        f = test_automatic_duel.AutomaticDuelsTests(); f.setUp(); self.addCleanup(f.doCleanups)
        context = f.prepare(); p = test_duel.plan()
        p['requirements'] = {'main': [test_duel.rows(55144522, 2)], 'extra': [],
                             'opening': [test_duel.rows(55144522, 2)], 'warnings': []}
        r = condition(leaf('category', ['spell']))
        p['expansion'] = {'conditions': design([r, r, None]), 'actual_opening': f.hand}
        file = f.store.plan_path(p['id']); atomic_json(file, p); original = file.read_bytes()
        result = f.store.automatic_duel.match({'context_id': context['context_id'], 'hand': [999]})
        self.assertEqual([v['id'] for v in result['matches']], [p['id']])
        self.assertEqual(result['matches'][0]['opening_match']['actual_hand'], f.hand)
        self.assertEqual(file.read_bytes(), original)
        p['expansion']['conditions']['banned'] = [condition(leaf('monster_kind', ['normal']))]
        atomic_json(file, p)
        result = f.store.automatic_duel.match({'context_id': context['context_id']})
        self.assertEqual(result['matches'], []); self.assertEqual(result['excluded'][0]['stage'], 'opening')


if __name__ == '__main__': unittest.main()
