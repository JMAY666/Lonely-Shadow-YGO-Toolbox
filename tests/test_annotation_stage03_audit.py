"""Regressions for the OCG rule errors discovered in the 2026-09-27 audit.

Expected boundaries come from the cited KONAMI card texts and supplements,
not the batch author's generated query/semantic expectations.
"""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Stage03RuleAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text(encoding='utf-8'))['cards']

    def effect(self, code, key):
        return next(e for e in self.cards[str(code)]['effects'] if e['key'] == key)

    def test_big_eye_and_cook_require_one_material(self):
        for code, key in [(80117527, 'm1'), (82697249, 'm2')]:
            cost = self.effect(code, key)['structure']['cost']
            self.assertEqual(cost, [{'kind': 'detach_material', 'text': '取除本卡1个超量素材', 'count': 1}])

    def test_dragonic_ray_does_not_halve_attack(self):
        effect = self.effect(75402014, 'm2')
        self.assertEqual([p['action'] for p in effect['structure']['processing']], ['negate_effect'])
        self.assertNotIn('etag:stat-change', effect['tags'])

    def test_stealth_kragen_does_not_target(self):
        structure = self.effect(67557908, 'm2')['structure']
        self.assertEqual(structure['targeting'], [])
        self.assertEqual(structure['processing'][0]['selection_timing'], 'resolution')

    def test_bubbleman_special_summon_is_an_effect_without_chain(self):
        effect = self.effect(79979666, 'm1')
        self.assertEqual(effect['effect_type'], 'no_chain_effect')
        self.assertIn('etag:special-summon', effect['tags'])
        self.assertNotIn('etag:material-rule', effect['tags'])
        processing = effect['structure']['processing'][0]
        self.assertEqual(processing['action'], 'special_summon')
        self.assertIs(processing['creates_chain'], False)

    def test_dark_storm_keeps_own_damage_and_granted_quick_effect(self):
        damage = self.effect(77205367, 'm1')['structure']['processing'][1]
        self.assertEqual(damage['recipient'], 'both')
        granted = self.effect(77205367, 'm2')['structure']['processing'][0]['granted_effect']
        self.assertEqual(granted['effect_type'], 'quick')
        self.assertIs(granted['structure']['activation']['fast_effect'], True)

    def test_poisoner_uses_trap_effect_only_in_main_phase(self):
        effect = self.effect(83414006, 'm2')
        self.assertEqual(effect['effect_type'], 'trap_effect')
        self.assertTrue(any('主要阶段' in c for c in effect['structure']['activation']['conditions']))

    def test_temporary_banishment_returns_without_special_summon(self):
        for code in [62542673, 79625003, 80796456]:
            items = self.effect(code, 'm1')['structure']['processing'][0]['then']
            returned = next(item for item in items if item['action'] == 'return_to_field')
            self.assertEqual(returned['from_zones'], ['opponent_banished'])
            self.assertIs(returned['creates_chain'], False)
            self.assertIs(returned['counts_as_special_summon'], False)

    def test_material_grants_are_not_continuous_and_victory_does_not_target(self):
        for code in [85121942, 87911394]:
            self.assertEqual(self.effect(code, 'm2')['effect_type'], 'non_effect')
        granted = self.effect(87911394, 'm2')['structure']['processing'][0]['granted_effect']
        self.assertEqual(granted['structure']['targeting'], [])

    def test_bane_attack_gain_has_no_end_turn_limit(self):
        structure = self.effect(86165817, 'm2')['structure']
        gain = structure['processing'][0]['then'][0]
        self.assertNotIn('duration', gain)
        self.assertEqual(structure['processing'][1]['action'], 'lock')
        self.assertIs(structure['processing'][1]['self_only'], True)

    def test_leviathan_cannot_direct_attack_is_not_permission(self):
        effect = self.effect(69610924, 'm1')
        self.assertEqual(effect['structure']['processing'][0]['action'], 'lock')
        self.assertIn('etag:lock', effect['tags'])

    def test_dashers_activation_confirmation_is_not_hand_reveal_processing(self):
        effect = self.effect(81866673, 'm3')
        self.assertEqual([p['action'] for p in effect['structure']['processing']], ['special_summon'])
        self.assertNotIn('etag:hand-look', effect['tags'])
        self.assertEqual(effect['structure']['usage'], ['graveyard_once'])

    def test_galaxy_trance_records_negation_separately(self):
        effect = self.effect(63956833, 'm1')
        self.assertIn('negate_effect', [p['action'] for p in effect['structure']['processing']])
        self.assertIn('etag:negate-effect', effect['tags'])

    def test_battle_damage_actions_have_their_common_tag(self):
        for code in [75253697, 77205367]:
            self.assertIn('etag:damage-modify', self.effect(code, 'm1')['tags'])


if __name__ == '__main__':
    unittest.main()
