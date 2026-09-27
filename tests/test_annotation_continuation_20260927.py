"""Independent rule regressions for the continued official OCG cohort.

The cited official card/FAQ sources are frozen in the public batch contract.
These expectations specifically guard the mistakes in the quarantined draft
and conditional rule boundaries; source/classification checks run separately.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from card_annotations import _processing_nodes


class ContinuationRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text(encoding='utf-8'))['cards']
        cls.batch = json.loads((ROOT / 'docs/card-annotation-batch-2026-09-27-continuation.json').read_text(encoding='utf-8'))

    def effect(self, code, key):
        return next(e for e in self.cards[str(code)]['effects'] if e['key'] == key)

    def test_dunk_guy_activates_in_monster_zone(self):
        structure = self.effect(93431862, 'm-all')['structure']
        self.assertEqual(structure['activation']['zones'], ['monster'])
        self.assertEqual(structure['cost'][0]['from_zones'], ['hand'])

    def test_photon_dragon_summon_is_an_effect_without_chain(self):
        for code in [93717133, 93717134, 93717135]:
            effect = self.effect(code, 'm1')
            self.assertEqual(effect['effect_type'], 'no_chain_effect')
            self.assertEqual(effect['structure']['processing'][0]['action'], 'special_summon')
            self.assertIs(effect['structure']['processing'][0]['creates_chain'], False)

    def test_multiply_guy_uses_trap_effect_in_main_phase(self):
        effect = self.effect(96693371, 'm2')
        self.assertEqual(effect['effect_type'], 'trap_effect')
        self.assertIn('仅双方主要阶段', effect['structure']['activation']['conditions'][0])

    def test_dragulas_resurrection_has_no_extra_deck_or_battle_trigger(self):
        structure = self.effect(93713837, 'm2')['structure']
        self.assertEqual(structure['activation']['zones'], ['grave', 'banished'])
        self.assertEqual(structure['processing'][0]['from_zones'], ['grave', 'banished'])
        self.assertNotIn('战斗', ''.join(structure['activation']['conditions']))

    def test_flame_shoot_ignores_conditions_without_invented_fusion_summon(self):
        processing = self.effect(93347961, 'm2')['structure']['processing'][0]
        self.assertIs(processing['ignore_summoning_conditions'], True)
        self.assertNotIn('summon_type', processing)

    def test_diva_destroy_requires_real_damage_faq_15094(self):
        effect = self.effect(84988419, 'm2')
        burn = effect['structure']['processing'][0]
        self.assertEqual(burn['action'], 'burn')
        self.assertEqual(burn['then'][0]['action'], 'destroy')
        self.assertIn('实际成功给予效果伤害', burn['then'][0]['condition'])
        self.assertIn('伤害被降为0时不破坏', burn['then'][0]['condition'])
        self.assertTrue(any('fid=15094' in s['url'] for s in self.cards['84988419']['sources']))

    def test_pendulum_and_monster_blocks_keep_separate_capabilities(self):
        self.assertEqual(self.effect(64881644, 'p1')['block'], 'p')
        self.assertEqual(self.effect(64881644, 'm1')['block'], 'm')
        self.assertNotIn('etag:send-grave', self.effect(64881644, 'm1')['tags'])
        self.assertNotIn('etag:special-summon', self.effect(90276649, 'p2')['tags'])

    def test_battle_damage_actions_have_their_common_tag(self):
        for row in self.batch['cards']:
            for effect in self.cards[str(row['code'])]['effects']:
                nodes = list(_processing_nodes(effect.get('structure', {}).get('processing', []), include_granted=False))
                if any(p['action'] in ('damage_modify', 'grant_piercing') for _, p in nodes):
                    self.assertIn('etag:damage-modify', effect.get('own_tags', effect['tags']))

    def test_pending_cards_require_an_explicit_later_review_before_admission(self):
        resolved = json.loads((ROOT / 'docs/card-annotation-batch-2026-09-27-model-expansion.json').read_text('utf-8'))
        accepted = {row['code'] for row in resolved['cards']}
        for row in self.batch['pending']:
            if row['code'] in accepted:
                self.assertEqual(self.cards[str(row['code'])]['review']['status'], 'reviewed')
                self.assertEqual(self.cards[str(row['code'])]['review']['origin'], 'manual')
            else:
                self.assertNotIn(str(row['code']), self.cards)


if __name__ == '__main__':
    unittest.main()
