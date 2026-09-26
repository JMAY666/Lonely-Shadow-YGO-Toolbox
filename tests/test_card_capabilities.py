from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from card_capabilities import CardCapabilities, purpose_candidates, marked_capabilities
from card_annotations import digest
from plan_endboard import attach_terminal_marks, marked_terminal, marked_evaluation
import test_card_annotations as annotation_fixtures
from test_card_annotations import simple_effect, SEARCHER, PENDULUM, make_entry


class CapabilityTests(unittest.TestCase):
    write_curated = annotation_fixtures.CardAnnotationTests.write_curated

    def setUp(self):
        annotation_fixtures.CardAnnotationTests.setUp(self)
        self.store.card_annotations = self.service
        self.capabilities = self.store.card_capabilities

    def tearDown(self):
        annotation_fixtures.CardAnnotationTests.tearDown(self)

    def test_projection_is_read_only_and_copies_underlying_data(self):
        before = deepcopy(self.service.document)
        row = self.capabilities.card(20000001)
        self.assertTrue(row['trusted'])
        self.assertEqual(row['effects'][0]['ref']['effect_key'], 'm1')
        row['effects'][0]['structure']['activation']['zones'].clear()
        self.assertEqual(self.capabilities.card(20000001)['effects'][0]['structure']['activation']['zones'], ['hand'])
        self.assertEqual(before, self.service.document)
        self.assertFalse(self.service.path.exists())

    def test_target_facts_preserve_closed_open_and_fixed_quantities_in_snapshots(self):
        targets = [{'min_count': 1, 'max_count': 3, 'filter': '墓地火山怪兽'},
                   {'min_count': 2, 'max_count': None, 'filter': 'RR超量怪兽'},
                   {'count': 2, 'filter': '固定2张对象卡'}]
        def change(entries): entries['20000001']['effects'][0]['structure']['targeting'] = deepcopy(targets)
        self.write_curated(change)
        self.service.reload()
        projected = self.capabilities.card(20000001)
        effect = projected['effects'][0]
        target_fact = next(row['text'] for row in effect['facts'] if row['label'] == '对象')
        self.assertIn('1至3个 墓地火山怪兽', target_fact)
        self.assertIn('至少2个 RR超量怪兽', target_fact)
        self.assertIn('2 固定2张对象卡', target_fact)
        self.assertEqual(effect['structure']['targeting'], targets)
        report = {'catalog': {'20000001': {'desc': SEARCHER}}, 'branches': []}
        self.capabilities.freeze_report(report)
        frozen = deepcopy(report)
        self.assertEqual(report['annotation_snapshot']['20000001']['effects'][0]['structure']['targeting'], targets)
        effect['structure']['targeting'][0]['max_count'] = 99
        self.assertEqual(self.capabilities.card(20000001)['effects'][0]['structure']['targeting'], targets)
        self.capabilities.freeze_report(report)
        self.assertEqual(report, frozen)
        self.assertFalse(self.service.path.exists())

    def test_legacy_target_facts_do_not_silently_infer_an_open_upper_bound(self):
        legacy = simple_effect('m1', 1, [], [])
        legacy['structure']['targeting'] = [{'count': 2, 'min_count': 2, 'variable_count': True, 'filter': '原快照2只以上的文字'}]
        fact = next(row['text'] for row in self.capabilities.facts(legacy) if row['label'] == '对象')
        self.assertEqual(fact, '2 原快照2只以上的文字')

    def test_unknown_and_missing_do_not_mean_no_effect(self):
        unknown = self.capabilities.card(20000004)
        self.assertEqual(unknown['status'], 'none')
        self.assertFalse(unknown['trusted'])
        self.assertFalse(unknown['no_effect'])
        self.assertEqual(self.capabilities.card(9999)['status'], 'missing')
        self.assertTrue(self.capabilities.card(20000005)['no_effect'])

    def test_record_text_mismatch_never_attaches_current_effect(self):
        result = self.capabilities.card(20000001, SEARCHER + '新的文本')
        self.assertEqual(result['status'], 'mismatch')
        self.assertEqual(result['effects'], [])
        self.assertFalse(result['trusted'])

    def test_stale_and_pending_cannot_offer_candidates_or_match_filters(self):
        self.store.catalog.cards[20000001]['desc'] += '修改卡文'
        self.service._views.clear()
        self.assertEqual(self.capabilities.card(20000001)['status'], 'stale')
        self.assertEqual(self.capabilities.card(20000001)['effects'], [])
        self.assertNotIn(20000001, self.capabilities.matching_codes('etag:add-hand'))
        self.service.command({'op': 'set-review', 'code': 20000002, 'value': 'pending', 'revision': self.service.document['revision']})
        self.assertFalse(self.capabilities.card(20000002)['trusted'])
        self.assertNotIn(20000002, self.capabilities.matching_codes('etag:add-hand'))

    def test_personal_notes_refresh_content_version_and_frozen_report_stays_unchanged(self):
        report = {'catalog': {'20000001': {'desc': SEARCHER}}, 'branches': []}
        self.capabilities.freeze_report(report)
        original = deepcopy(report)
        old = self.capabilities.card(20000001)
        self.service.command({'op': 'add-note', 'code': 20000001, 'key': 'm1', 'text': '个人的新备注',
                              'revision': self.service.document['revision']})
        current = self.capabilities.card(20000001)
        self.assertNotEqual(old['version'], current['version'])
        self.assertTrue(any(row['text'] == '个人的新备注' for row in current['effects'][0]['notes']))
        self.capabilities.freeze_report(report)
        self.assertEqual(original, report)

    def test_legacy_effect_mapping_uses_unique_text_not_number(self):
        value = self.capabilities.card(20000003)
        self.assertEqual([row['legacy_key'] for row in value['effects']], ['0', '1', '2'])
        def add_pendulum(entries):
            entries['20000004'] = make_entry(20000004, PENDULUM, [
                simple_effect('p1', 1, ['etag:add-hand'], [{'action': 'add_hand', 'from_zones': ['deck']}]),
                simple_effect('m1', 1, ['etag:destroy','etag:special-summon'], [{'action': 'destroy'}, {'action': 'special_summon'}])])
        self.write_curated(add_pendulum); self.service.reload()
        value = self.capabilities.card(20000004)
        # The legacy split includes the monster delimiter with the pendulum text.
        p = next(row for row in value['effects'] if row['key'] == 'p1')
        self.assertIsNone(p['legacy_key'])

    def test_fixed_granted_facts_preserve_real_costs_timing_and_limits_across_modules(self):
        source = Path(__file__).resolve().parents[1] / 'src/trainer/card-annotations.json'
        document = json.loads(source.read_text('utf-8'))
        for code, key, timing in ((15092394, 'm1', '自己主要阶段'), (86221741, 'm3', '结束阶段')):
            effect = next(e for e in document['cards'][str(code)]['effects'] if e['key'] == key)
            facts = self.capabilities.facts(effect)
            own = [row for row in facts if not row['label'].startswith('固定获赋效果')]
            child = [row for row in facts if row['label'].startswith('固定获赋效果·')]
            self.assertTrue(any(row['label'] == '适用区域' for row in own))
            self.assertTrue(any(row['label'] == '固定获赋效果·时点' and timing in row['text'] for row in child))
            self.assertFalse(any(row['label'] == '后续处理' for row in own), 'compatibility then must not be flattened twice')
            if code == 15092394:
                self.assertTrue(any(row['label'] == '固定获赋效果·费用' and '取除' in row['text'] for row in child))
                self.assertTrue(any(row['label'] == '固定获赋效果·对象' for row in child))
                self.assertTrue(any(row['label'] == '固定获赋效果·次数' for row in child))
            else:
                self.assertTrue(any(row['label'] == '固定获赋效果·次数说明' and '结束阶段' in row['text'] for row in child))

    def test_equipped_continuous_protection_keeps_endboard_candidate(self):
        source = Path(__file__).resolve().parents[1] / 'src/trainer/card-annotations.json'
        document = json.loads(source.read_text('utf-8'))
        for code in (27756115, 95500396):
            effect = next(e for e in document['cards'][str(code)]['effects'] if e['key'] == 'm2')
            self.assertEqual(effect['effect_type'], 'spell_continuous')
            self.assertIn('endboards', {row['role'] for row in purpose_candidates(effect)})

    def test_role_candidates_exclude_self_destruction_and_ignition_hand_effect(self):
        effect = simple_effect('m1', 1, ['etag:destroy'], [{'action': 'destroy', 'selector': {'text': '把这张卡破坏'}}])
        self.assertEqual(purpose_candidates(effect), [])
        effect['structure']['processing'][0]['selector']['text'] = '对方场上1张卡'
        roles = {row['role'] for row in purpose_candidates(effect)}
        self.assertEqual(roles, {'breakers'})
        effect['structure']['activation']['fast_effect'] = True
        self.assertIn('handtraps', {row['role'] for row in purpose_candidates(effect)})

    def test_multiline_crlf_card_keeps_same_effect_reference(self):
        text = SEARCHER + '\n处理范围的补充说明。'
        self.store.catalog.cards[20000001]['desc'] = text.replace('\n', '\r\n')
        def change(entries):
            entries['20000001'].update(frozen_text=text, text_digest=digest(text))
        self.write_curated(change); self.service.reload()
        self.assertEqual(self.capabilities.card(20000001)['effects'][0]['legacy_key'], '0')

    def test_personal_tag_does_not_prove_purpose(self):
        effect = simple_effect('m1', 1, ['etag:negate-effect'], [{'action': 'draw'}])
        effect['structure']['activation']['fast_effect'] = True
        self.assertEqual(purpose_candidates(effect), [])

    def test_filters_require_same_effect_and_preserve_branch_limit(self):
        self.assertEqual(self.capabilities.matching_codes('etag:add-hand'), {20000001,20000002})
        self.assertEqual(self.capabilities.matching_codes('etag:special-summon', 'breakers'), set())
        effect = simple_effect('m2', 2, [], [{'action': 'choose_branch', 'branches': [
            {'condition': '选择此项', 'actions': [{'action': 'destroy', 'from_zones': ['opponent_monster']}]},
            {'condition': '或选择此项', 'actions': [{'action': 'draw'}]}]}])
        labels = [row['label'] for row in self.capabilities.facts(effect)]
        self.assertIn('分支 1', labels)
        self.assertIn('分支 2', labels)

    def test_marked_summary_only_uses_selected_instances_and_effects(self):
        snapshot = self.capabilities.card(20000003)
        card = {'code': 20000003, 'instance_id': 1, 'controller': 0, 'location': 4, 'position': 1}
        report = {'final_state': {'cards': [card]}, 'annotations': {'final_marks': {'1': {'marked': True, 'effects': {'2': {'note': '用途'}}}}},
                  'annotation_snapshot': {'20000003': snapshot}}
        source = attach_terminal_marks({'edges': [{'terminal': True}]}, report)
        terminal = marked_terminal(source['edges'][0], {'cards': [card]})
        result = marked_evaluation(terminal)
        self.assertEqual(result['marked_effects'], 1)
        self.assertEqual(result['capabilities']['tags'], ['破坏'])
        self.assertEqual(result['capabilities']['effects'][0]['key'], 'm2')
        from opening_analysis import terminal as opening_terminal
        reference = opening_terminal(report, self.store.catalog.cards)[0]
        self.assertEqual(reference['capability']['key'], 'm2')
        terminal['terminal_targets'][0]['card']['disabled'] = True
        self.assertEqual(marked_evaluation(terminal)['capabilities']['effects'], [])

    def test_legacy_plan_with_no_snapshot_is_unknown_and_not_backfilled(self):
        target = {'card': {'code': 20000001}, 'mark': {'effects': {'0': {'note': ''}}}}
        before = deepcopy(target)
        self.assertEqual(marked_capabilities([target])['unknown_cards'], 1)
        self.assertEqual(before, target)

    def test_batch_and_validation(self):
        result = self.capabilities.command({'cards': [{'code': 20000001}, {'code': 20000002}]})
        self.assertEqual(len(result['cards']), 2)
        for body in ({'cards': [{}]}, {'cards': [None]}, {'cards': [{'code': 20000001}]*121}, {'op': 'card', 'code': True}):
            with self.assertRaises(ValueError): self.capabilities.command(body)
        with self.assertRaises(ValueError): self.capabilities.matching_codes('made-up')

    def test_sharing_excludes_global_personal_annotation_notes(self):
        from plan_sharing import portable
        snapshot = self.capabilities.card(20000001)
        snapshot['effects'][0]['notes'] = [{'text': '全局私人备注不分享'}]
        plan = {'name': '测试', 'catalog': {}, 'expansion': {},
                'annotation_snapshot': {'20000001': snapshot},
                'modular_source': {'edges': [{'terminal_marks': [{'capabilities': snapshot, 'note': '明确选入方案的说明'}]}]}}
        before = deepcopy(plan)
        shared = portable(plan)
        self.assertNotIn('annotation_snapshot', shared)
        mark = shared['modular_source']['edges'][0]['terminal_marks'][0]
        self.assertNotIn('capabilities', mark)
        self.assertEqual(mark['note'], '明确选入方案的说明')
        self.assertEqual(plan, before)

    def test_live_and_opening_share_facts_without_promoting_them_to_roles(self):
        saved = self.store.save_deck({'name': '隔离能力样例', 'deck': {'main': [20000001]*40, 'extra': [], 'side': []}})
        body = {'deck_id': saved['id'], 'revision': saved['revision'], 'hand': [20000001]*5}
        opening = self.store.opening_workspace.analyze(body)
        self.assertTrue(opening['capabilities']['20000001']['trusted'])
        self.assertEqual(opening['handtrap_count'], 0)
        live = self.store.live_duel.command({'action': 'start', 'input': body})
        self.assertEqual(live['analysis']['capabilities']['20000001']['version'], opening['capabilities']['20000001']['version'])
        before = deepcopy(live['session'])
        self.service.command({'op': 'add-note', 'code': 20000001, 'key': 'm1', 'text': '新的能力备注',
                              'revision': self.service.document['revision']})
        updated = self.store.live_duel.command({'action': 'read', 'id': live['session']['id']})
        self.assertEqual(before, updated['session'])
        self.assertNotEqual(updated['analysis']['capabilities']['20000001']['version'], opening['capabilities']['20000001']['version'])

    def test_new_plan_freezes_branch_without_changing_an_existing_snapshot(self):
        branch = {'catalog': {'20000001': {'desc': SEARCHER}}}
        existing = {'catalog': {}, 'annotation_snapshot': {}}
        report = {'catalog': {}, 'branches': [{'report': branch}, {'report': existing}]}
        self.capabilities.freeze_report(report)
        self.assertTrue(branch['annotation_snapshot']['20000001']['trusted'])
        self.assertEqual(existing['annotation_snapshot'], {})


if __name__ == '__main__': unittest.main()
