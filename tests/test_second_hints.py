"""Synthetic state/strategy contracts; native interactions have their own suite."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import Mock, patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
import test_store as fixtures
from second_rules import ASH, IMPERM, OGRE, ALUBER, MOYE, FUSION, RESPONDERS, EFFECTS, usage_status
from second_hint_proof import HintProof, PROOF_PATH

N = 1184620


class SecondHintTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store
        for code in (ASH, IMPERM, OGRE, ALUBER, MOYE, FUSION):
            self.store.catalog.cards[code] = {'id': code, 'name': 'TEST ONLY ' + str(code), 'desc': 'synthetic text',
                'type': 4 if code == IMPERM else 2 if code == FUSION else 33,
                'level': 3, 'atk': 0, 'def': 0, 'extra': False, 'script_available': True}
        self.deck = self.store.save_deck({'name': 'TEST ONLY second hints',
            'deck': {'main': [ASH, ASH, IMPERM, OGRE] + [N] * 36, 'extra': [], 'side': []}})
        self.api = self.store.second_duel
        self.proof = {'status': 'matched', 'stamp': 'synthetic-resource-version', 'reason': 'unit fixture only',
                      'cases': json.loads(PROOF_PATH.read_text(encoding='utf-8'))['cases']}
        self.api.hints.proof.check = Mock(side_effect=lambda **kwargs: deepcopy(self.proof))
        self.doc = self.api.start({'request_id': uuid.uuid4().hex, 'deck_id': self.deck['id'],
            'deck_revision': self.deck['revision'], 'opening': [ASH, ASH, IMPERM, OGRE, N]})
        for card in list(self.doc['current']['cards']):
            if card['controller'] == 0 and card['location'] == 2 and card['code'] in RESPONDERS:
                self.event('effect_count', card_id=card['id'], effect_id=RESPONDERS[card['code']], status='unused')
                self.event('resource_role', card_id=card['id'], role='free')

    def event(self, kind, **payload):
        self.doc = self.api.event({'id': self.doc['id'], 'round_id': self.doc['input']['round_id'],
            'revision': self.doc['revision'], 'event_id': uuid.uuid4().hex, 'kind': kind, 'payload': payload})
        return self.doc

    def actor(self, code):
        found = next((c for c in self.doc['current']['cards'] if c['controller'] == 1 and c.get('code') == code), None)
        if not found:
            self.event('opponent_card', location=8 if code == FUSION else 4, known=True, code=code, position=1)
            found = next(c for c in self.doc['current']['cards'] if c['controller'] == 1 and c['code'] == code)
        return found

    def window(self, effect='aluber.search', **changes):
        actor = self.actor(EFFECTS[effect]['code'])
        self.event('verify', turn=1, turn_player=1, phase='main1', lp=[8000, 8000], opponent_hand_count=None, confirmed=True)
        return self.event('hint_window', **({'card_id': actor['id'], 'effect_id': effect, 'link': 1, 'top': 1, 'speed': 1,
            'protections': [], 'protections_checked': True, 'other_rules': 'none', 'grave_rule': 'normal',
            'objective': 'balanced', 'environment': 'local', 'confirmed': True} | changes))

    def generate(self):
        self.doc = self.api.dispatch('advice', {'id': self.doc['id'], 'round_id': self.doc['input']['round_id'],
            'revision': self.doc['revision'], 'request_id': uuid.uuid4().hex})
        return self.doc['advice']

    def item(self, hint, code):
        return next(r for r in hint['items'] if r['code'] == code)

    def test_aluber_compares_answers_instead_of_always_ashing_a_search(self):
        self.window()
        before = deepcopy(self.doc['current'])
        hint = self.generate()
        self.assertEqual(self.item(hint, IMPERM)['recommendation'], 'use')
        self.assertEqual(self.item(hint, ASH)['recommendation'], 'hold')
        self.assertEqual(self.item(hint, OGRE)['recommendation'], 'hold')
        self.assertEqual(self.doc['current'], before)
        self.assertEqual(len(hint['opponent_candidates']), 2)
        self.assertIn('混合', hint['opponent_candidates'][1])

    def test_only_ash_against_aluber_leaves_the_unknown_followup_tradeoff_explicit(self):
        card = next(c for c in self.doc['current']['cards'] if c['location'] == 2 and c['code'] == IMPERM)
        self.event('move', card_id=card['id'], **{'from': 2, 'to': 16, 'reason': 'effect'})
        self.window()
        row = self.item(self.generate(), ASH)
        self.assertEqual(row['recommendation'], 'information')
        self.assertIn('不能固定', row['reason'])
        self.window(objective='stop_effect')
        self.assertEqual(self.item(self.generate(), ASH)['recommendation'], 'use')

    def test_moye_token_is_not_deck_summoning_and_ogre_does_not_negate(self):
        self.window('moye.token')
        hint = self.generate()
        ash, ogre = self.item(hint, ASH), self.item(hint, OGRE)
        self.assertEqual(ash['conditions'], 'blocked')
        self.assertEqual(ogre['attributes'], ['destroy'])
        self.assertIsNone(ogre['example_result']['negation'])
        self.assertEqual(ogre['example_result']['gained'], 1)
        self.assertFalse(ogre['example_result']['immediate_chixiao'])
        self.assertEqual(ogre['recommendation'], 'use')
        self.window('moye.token', objective='stop_effect')
        self.assertEqual(self.item(self.generate(), OGRE)['recommendation'], 'hold')

    def test_card_effect_two_never_inherits_effect_one_case(self):
        self.window('moye.draw')
        hint = self.generate()
        self.assertTrue(all(r['recommendation'] == 'information' for r in hint['items']))
        self.assertTrue(any('具体效果缺少' in s for s in hint['missing']))

    def test_fusion_negation_and_actual_exchange_are_separate_from_prevented_gain(self):
        self.window('fusion.activate')
        hint = self.generate()
        ash = self.item(hint, ASH)
        self.assertEqual(ash['recommendation'], 'use')
        self.assertEqual(ash['attributes'], ['negate_effect'])
        self.assertEqual(ash['exchange']['expected_opponent_removed'], 0)
        self.assertIsNone(ash['exchange']['prevented_deck_gain'])
        self.assertIn('尚未记录', ash['exchange']['actual'])
        self.assertEqual(self.item(hint, IMPERM)['conditions'], 'blocked')
        self.assertEqual(self.item(hint, OGRE)['conditions'], 'blocked')

    def test_spent_usage_and_shared_effect_groups_are_not_restored_by_negation(self):
        ash = next(c for c in self.doc['current']['cards'] if c['location'] == 2 and c['code'] == ASH)
        self.event('effect_observed', card_id=ash['id'], effect_id='ash.negate', outcome='activation_negated', confirmed=True)
        self.window('fusion.activate')
        row = self.item(self.generate(), ASH)
        self.assertEqual(row['copies'], 2)
        self.assertEqual(row['conditions'], 'blocked')
        actor = self.actor(ALUBER)
        self.event('effect_observed', card_id=actor['id'], effect_id='aluber.search', outcome='effect_negated', confirmed=True)
        self.assertEqual(usage_status(self.doc['current'], EFFECTS['aluber.revive'], 1, actor['id']), 'used')
        fusion = self.actor(FUSION)
        self.event('effect_observed', card_id=fusion['id'], effect_id='fusion.activate', outcome='activation_negated', confirmed=True)
        self.assertEqual(usage_status(self.doc['current'], EFFECTS['fusion.activate'], 1, fusion['id']), 'unused')
        self.event('effect_observed', card_id=fusion['id'], effect_id='fusion.activate', outcome='effect_negated', confirmed=True)
        self.assertEqual(usage_status(self.doc['current'], EFFECTS['fusion.activate'], 1, fusion['id']), 'used')

    def test_missing_cost_and_new_chain_or_protection_stop_determinate_advice(self):
        self.window('moye.token', grave_rule='monster_banish')
        ogre = self.item(self.generate(), OGRE)
        self.assertEqual(ogre['conditions'], 'blocked')
        self.assertTrue(any('费用' in s for s in ogre['blocked']))
        self.window('aluber.search', top=2, speed=3)
        hint = self.generate()
        self.assertTrue(all(r['recommendation'] == 'information' for r in hint['items']))
        self.assertTrue(any('直接连锁' in s for s in self.item(hint, ASH)['blocked']))
        self.window('moye.token', protections=['target', 'destroy'])
        hint = self.generate()
        self.assertEqual(self.item(hint, IMPERM)['conditions'], 'blocked')
        self.assertTrue(all(r['recommendation'] == 'information' for r in hint['items']))

    def test_key_starter_reservation_and_unknown_role_affect_recommendation(self):
        copies = [c for c in self.doc['current']['cards'] if c['code'] == ASH and c['location'] == 2]
        for card in copies:
            self.event('resource_role', card_id=card['id'], role='key', note='TEST ONLY required known material')
        self.window('fusion.activate')
        self.assertEqual(self.item(self.generate(), ASH)['recommendation'], 'hold')
        self.event('resource_role', card_id=copies[0]['id'], role='unknown')
        self.window('fusion.activate')
        self.assertEqual(self.item(self.generate(), ASH)['recommendation'], 'information')

    def test_hidden_identities_never_change_recommendation(self):
        self.window('fusion.activate')
        first = deepcopy(self.api.load(self.doc['id']))
        second = deepcopy(first)
        for doc, code in ((first, ASH), (second, MOYE)):
            doc['current']['cards'].append({'id': 'hidden', 'controller': 1, 'location': 2, 'code': code, 'position': 8})
        self.assertEqual(self.api.hints.evaluate(first, self.proof), self.api.hints.evaluate(second, self.proof))

    def test_expired_or_changed_resource_suggestions_cannot_be_chosen(self):
        self.window('fusion.activate')
        hint = self.generate()
        row = self.item(hint, ASH)
        request = {'id': self.doc['id'], 'round_id': self.doc['input']['round_id'], 'revision': self.doc['revision'],
                   'request_id': uuid.uuid4().hex, 'advice_id': hint['id'], 'card_id': row['instance_id'], 'choice': 'use'}
        before = deepcopy(self.doc['current'])
        result = self.api.dispatch('advice-choice', request)
        self.assertEqual(result['current'], before)
        self.assertEqual(len(result['advice']['decisions']), 1)
        self.assertEqual(len(self.api.dispatch('advice-choice', request)['advice']['decisions']), 1)
        with patch.object(self.api, 'now', return_value=hint['expires_ms']):
            with self.assertRaisesRegex(ValueError, '过期'):
                self.api.dispatch('advice-choice', {**request, 'request_id': uuid.uuid4().hex})
        self.proof['stamp'] = 'different rules'
        with self.assertRaises(ValueError):
            self.api.dispatch('advice-choice', {**request, 'request_id': uuid.uuid4().hex})

    def test_resource_change_failed_writes_and_actual_actions_preserve_separate_history(self):
        self.window('fusion.activate')
        hint = self.generate()
        before = self.api.state({'id': self.doc['id']})
        with patch.object(self.api, 'write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.generate()
        self.assertEqual(self.api.state({'id': self.doc['id']}), before)
        self.event('choice', note='玩家实际决定保留')
        self.assertFalse(self.doc['advice']['current'])
        raw = self.api.load(self.doc['id'])['advice_history'][0]
        self.assertIsNotNone(raw['known_state']['window'])
        self.assertEqual(raw['known_state']['hand'] if 'hand' in raw['known_state'] else len([c for c in raw['known_state']['cards'] if c['controller']==0 and c['location']==2]), 5)
        self.assertEqual(raw['id'], hint['id'])

    def test_external_platform_and_legacy_rule_notes_remain_explicitly_unverified(self):
        self.window('fusion.activate', environment='external')
        self.assertTrue(all(r['recommendation']=='information' for r in self.generate()['items']))
        self.event('rule', category='restrictions', label='unknown legacy condition', status='unknown')
        self.window('fusion.activate')
        self.assertTrue(any('未结构化' in s for s in self.generate()['missing']))

    def test_receipt_mismatch_is_not_a_claim_that_no_legal_response_exists(self):
        self.window('fusion.activate')
        self.proof.update(status='unverified', cases={}, reason='resource version differs')
        hint = self.generate()
        self.assertTrue(all(r['recommendation']=='information' for r in hint['items']))
        self.assertIn('resource version differs', hint['missing'])
        self.assertTrue(all(r['exchange']['expected_opponent_removed'] is None and r['exchange']['prevented_deck_gain'] is None for r in hint['items']))
        proof = HintProof(self.store).check()
        self.assertEqual(proof['status'], 'unverified')

    def test_late_effect_outcome_cannot_refund_a_newer_activation(self):
        card = self.actor(FUSION)
        self.event('effect_observed', card_id=card['id'], effect_id='fusion.activate', outcome='pending', confirmed=True)
        first = self.doc['current']['effect_actions'][-1]['id']
        self.event('effect_count', card_id=card['id'], effect_id='fusion.activate', status='unused', note='confirmed first activation was negated')
        self.event('effect_observed', card_id=card['id'], effect_id='fusion.activate', outcome='resolved', confirmed=True)
        self.event('effect_outcome', action_id=first, outcome='activation_negated')
        self.assertEqual(usage_status(self.doc['current'], EFFECTS['fusion.activate'], 1, card['id']), 'used')
        self.assertEqual(self.doc['current']['effect_actions'][0]['outcome'], 'activation_negated')
        with self.assertRaises(ValueError):
            self.event('effect_outcome', action_id=first, outcome='effect_negated')

    def test_unapplied_resolution_is_not_an_activation_negation(self):
        card = self.actor(FUSION)
        self.event('effect_observed', card_id=card['id'], effect_id='fusion.activate', outcome='pending', confirmed=True)
        action = self.doc['current']['effect_actions'][-1]['id']
        self.event('effect_outcome', action_id=action, outcome='not_applied')
        self.assertEqual(usage_status(self.doc['current'], EFFECTS['fusion.activate'], 1, card['id']), 'used')

    def test_malformed_proof_never_promotes_truthy_strings_to_verified_cases(self):
        checker = HintProof(self.store)
        old_stamp = checker.check()['stamp']
        target = self.fixture.root / 'malformed-hint-proof.json'
        target.write_text(json.dumps({'schema': 1, 'revision': 'bo1-second-hints-1', 'resources': {},
                                      'cases': {'bad': {'activated': 'yes'}}}), encoding='utf-8')
        with patch('second_hint_proof.PROOF_PATH', target):
            proof = checker.check()
        self.assertEqual(proof['status'], 'unverified')
        self.assertEqual(proof['cases'], {})
        self.assertNotEqual(proof['stamp'], old_stamp, 'Knowledge changes must invalidate already-issued advice even when engine files do not change')

    def test_a_negative_engine_case_cannot_be_overridden_by_positive_manual_checks(self):
        self.window('fusion.activate')
        self.proof['cases']['fusion_ash']['activated'] = False
        row = self.item(self.generate(), ASH)
        self.assertEqual(row['conditions'], 'blocked')
        self.assertNotEqual(row['recommendation'], 'use')

    def test_other_public_monsters_prevent_assuming_ogre_removes_all_synchro_options(self):
        self.actor(ALUBER)
        self.window('moye.token')
        row = self.item(self.generate(), OGRE)
        self.assertEqual(row['recommendation'], 'information')
        self.assertTrue(any('替代素材' in note for note in row['missing']))

    def test_rule_change_during_generation_does_not_publish_a_mixed_result(self):
        self.window('fusion.activate')
        before = deepcopy(self.api.load(self.doc['id']))
        self.api.hints.proof.check.side_effect = [deepcopy(self.proof), {**deepcopy(self.proof), 'stamp': 'new'}]
        with self.assertRaisesRegex(ValueError, '核对期间'):
            self.generate()
        self.assertEqual(self.api.load(self.doc['id']), before)


if __name__ == '__main__':
    unittest.main()
