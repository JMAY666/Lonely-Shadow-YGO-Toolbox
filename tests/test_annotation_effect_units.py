"""Semantic boundary regressions using reviewed model-gap cards and isolated data."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

import test_card_annotations as fixture
from card_annotations import digest, segments, validate_entry, effect_units
from card_capabilities import CardCapabilities, purpose_candidates

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
BATCH = json.loads((ROOT / 'docs/card-annotation-batch-2026-09-27-model-expansion.json').read_text('utf-8'))


class EffectUnitTests(unittest.TestCase):
    setUp = fixture.CardAnnotationTests.setUp
    tearDown = fixture.CardAnnotationTests.tearDown
    write_curated = fixture.CardAnnotationTests.write_curated

    def install(self, code):
        entry = deepcopy(DOCUMENT['cards'][str(code)])
        row = next(row for row in BATCH['cards'] if row['code'] == code)
        self.store.catalog.cards[code] = {'id': code, 'name': row['local_name'], 'type': row['local_type'],
                                         'desc': entry['frozen_text'], 'setcode': 0, 'extra': bool(row['local_type'] & 0x800040)}
        self.service.curated['cards'][code] = entry
        self.service._views = {}
        self.store.card_annotations = self.service
        return entry

    def test_real_queries_keep_units_branches_and_delays_separate(self):
        for row in BATCH['cards']: self.install(row['code'])
        for case in BATCH['query_cases']:
            with self.subTest(reason=case['reason']):
                result = self.service.search({'q': str(case['code']), **case['query']})
                self.assertEqual({hit['key'] for card in result['cards'] for hit in card['hits']}, set(case['expected_keys']))
                for card in result['cards']:
                    for hit in card['hits']:
                        if case['code'] == 89642993 and case['query'].get('action') == 'draw':
                            self.assertTrue(all('scheduled_effect' in item['effect_path'] for item in hit['evidence']))

    def test_personal_tags_do_not_create_cross_unit_facts_and_removal_masks_units(self):
        code = 88820235
        self.install(code)
        self.service.set_tags({'code': code, 'key': 'm-all', 'add': ['etag:draw']})
        self.assertEqual(self.service.search({'q': str(code), 'etags': ['etag:draw']})['total'], 1)
        self.assertEqual(self.service.search({'q': str(code), 'etags': ['etag:draw'], 'action': 'protect'})['total'], 0)
        self.service.set_tags({'code': code, 'key': 'm-all', 'remove': ['etag:protect']})
        self.assertEqual(self.service.search({'q': str(code), 'etags': ['etag:protect']})['total'], 0)
        self.assertEqual(self.service.search({'q': str(code), 'action': 'protect'})['total'], 1)

    def test_personal_notes_and_stale_history_stay_at_original_segment(self):
        code = 98263709
        self.install(code)
        self.service.add_note({'code': code, 'key': 'm-all', 'text': '我的原段备注'})
        self.assertEqual(self.service.view(code)['effects'][0]['notes'][-1]['text'], '我的原段备注')
        self.store.catalog.cards[code]['desc'] += '卡文修订'
        self.service._views = {}
        view = self.service.view(code)
        self.assertEqual(view['status'], 'stale')
        self.assertEqual(view['effects'][0]['notes'][-1]['text'], '我的原段备注')
        self.assertEqual(self.service.search({'q': str(code), 'action': 'heal'})['total'], 0)

    def test_new_unit_contract_rejects_incomplete_ambiguous_or_unanchored_payload(self):
        entry = self.install(88820235)
        mutations = [
            lambda e: e['effects'][0].update(structure={}),
            lambda e: e['effects'][0].update(tags=[]),
            lambda e: e['effects'][0].update(unit_mode='invented'),
            lambda e: e['effects'][0]['units'][1].update(id='fusion_rule'),
            lambda e: e['effects'][0]['units'][1].update(text='不在本段中的原文'),
            lambda e: e['effects'][0]['units'][1].update(effect_type='invented'),
            lambda e: e['effects'][0]['units'][1].update(notes=[]),
            lambda e: e['effects'][0]['units'][1]['notes'][0].update(source_refs=['missing']),
            lambda e: e['effects'][0]['units'][1]['structure'].pop('cost'),
            lambda e: e['effects'][0]['units'][1]['structure']['activation'].update(fast_effect=True),
        ]
        for mutate in mutations:
            invalid = deepcopy(entry); mutate(invalid)
            with self.subTest(value=invalid['effects'][0]), self.assertRaises(ValueError):
                validate_entry(invalid, self.service.registry, card_type=97)

    def test_delayed_processing_cannot_borrow_activation_cost_target_or_chain(self):
        entry = self.install(60461804)
        for field, value in [('cost', [{'kind': 'discard', 'text': '错误费用'}]),
                             ('targeting', [{'count': 1, 'filter': '错误发动对象'}]), ('usage', ['soft_opt'])]:
            invalid = deepcopy(entry)
            invalid['effects'][-1]['structure']['processing'][0]['scheduled_effect']['structure'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): validate_entry(invalid, self.service.registry)
        for changes in [{'creates_chain': True}, {'delay': ''}, {'then': [{'action': 'draw'}]},
                        {'action': 'grant_effect'}]:
            invalid = deepcopy(entry); invalid['effects'][-1]['structure']['processing'][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate_entry(invalid, self.service.registry)

    def test_attribute_set_damage_redirect_and_range_reject_lossy_shortcuts(self):
        for code, index, changes in [
            (92015800, 1, {'attribute': 'water'}), (92015800, 1, {'mode': 'replace'}),
            (92015800, 1, {'evaluated_at': 'resolution'}),
            (97403510, 1, {'recipient': 'self'}), (97403510, 1, {'is_effect_damage': True}),
            (46552140, 1, {'count': 5}), (46552140, 1, {'min_count': 6}),
            (46552140, 1, {'max_count': True}),
        ]:
            invalid = self.install(code)
            node = invalid['effects'][index]['structure']['processing'][1 if code == 97403510 else 0]
            node.update(changes)
            with self.subTest(code=code, changes=changes), self.assertRaises(ValueError):
                validate_entry(invalid, self.service.registry)

    def test_capability_facts_snapshots_and_role_filters_keep_unit_identity(self):
        self.install(88820235)
        capabilities = CardCapabilities(self.store)
        card = capabilities.card(88820235)
        self.assertEqual(len(card['effects'][0]['units']), 3)
        self.assertIn('融合素材与召唤限制', ' '.join(f['text'] for f in card['effects'][0]['facts']))
        self.assertIn(88820235, capabilities.matching_codes(tag='etag:protect', role='endboards'))
        self.assertNotIn(88820235, capabilities.matching_codes(tag='etag:stat-change', role='endboards'))
        report = {'catalog': {'88820235': {'desc': self.store.catalog.cards[88820235]['desc']}}}
        capabilities.freeze_report(report)
        before = deepcopy(report)
        self.service.curated['cards'][88820235]['effects'][0]['units'][1]['label'] = '新版说明'
        self.service._views = {}
        capabilities.freeze_report(report)
        self.assertEqual(report, before)
        self.assertFalse(self.service.path.exists())

    def test_scheduled_actions_are_described_but_never_instant_role_candidates(self):
        entry = self.install(60461804)
        delayed = entry['effects'][-1]
        self.assertEqual(purpose_candidates(delayed), [])
        facts = CardCapabilities(self.store).facts(delayed)
        self.assertTrue(any(f['label'] == '延迟处理' and '不另开连锁' in f['text'] for f in facts))
        self.assertEqual([u['structure']['cost'] for p,u in effect_units(delayed) if 'scheduled_effect' in p], [[]])


if __name__ == '__main__': unittest.main()
