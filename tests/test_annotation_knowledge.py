from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
import test_card_annotations as fixtures
from app import read_json, atomic_json
from annotation_knowledge import MANAGER


class AnnotationKnowledgeTests(unittest.TestCase):
    write_curated = fixtures.CardAnnotationTests.write_curated

    def setUp(self):
        fixtures.CardAnnotationTests.setUp(self)
        self.store.card_annotations = self.service
        self.sync = self.store.annotation_knowledge

    def tearDown(self):
        fixtures.CardAnnotationTests.tearDown(self)

    def legacy(self):
        # The synthetic dual-effect card has a reviewed opponent-removal effect.
        self.store.intelligence.command({'revision': 0, 'op': 'breaker.save', 'value': {
            'code': 20000003, 'note': '升级前自定义用途', 'condition': '旧条件', 'effects': {'1': {'note': '旧效果说明'}}}})
        return self.store.library.document()

    def test_upgrade_replaces_covered_personal_content_and_backs_up_original(self):
        previous = self.legacy()
        self.assertTrue(self.sync.upgrade())
        document = self.store.library.document()
        row = document['intelligence']['breakers']['20000003']
        self.assertEqual(row['managed_by'], MANAGER)
        self.assertEqual(row['effect_keys'], ['m2'])
        self.assertNotIn('旧', row['condition'])
        self.assertNotEqual(row['note'], '升级前自定义用途')
        backup = self.store.root / 'backups/tags' / f"{previous['revision']}.json"
        self.assertEqual(read_json(backup), previous)
        tag = self.store.library.all_tags()['purpose:boardbreaker']
        self.assertIn(20000003, tag['include_cards'])
        self.assertEqual(tag['managed_by'], MANAGER)
        before = self.store.library.path.read_bytes()
        self.assertFalse(self.sync.upgrade())
        self.assertEqual(before, self.store.library.path.read_bytes())

    def test_annotation_change_replaces_generated_notes_and_membership(self):
        self.sync.upgrade()
        self.service.command({'op': 'add-note', 'code': 20000003, 'key': 'm2', 'text': '统一标注的新说明',
                              'revision': self.service.document['revision']})
        result = self.store.intelligence.snapshot()
        self.assertIn('统一标注的新说明', result['breakers']['20000003']['effects']['2']['note'])
        self.service.command({'op': 'set-review', 'code': 20000003, 'value': 'pending',
                              'revision': self.service.document['revision']})
        result = self.store.intelligence.snapshot()
        self.assertNotIn('20000003', result['breakers'])
        self.assertNotIn(20000003, self.store.library.all_tags()['purpose:boardbreaker']['include_cards'])
        self.assertIn(20000003, result['annotation_sync']['unavailable_codes'])

    def test_old_opening_overrides_are_archived_and_actual_analysis_uses_annotations(self):
        workspace = self.store.opening_workspace
        old = {'schema': 1, 'revision': 5, 'settings': deepcopy(workspace.document()['settings']),
               'overrides': {'20000003:②': {'version': 'old', 'value': {'roles': [], 'priority': 'secondary', 'note': '旧角色'}}},
               'candidates': {}, 'notes': {'deck': {'text': '局部构筑备注', 'version': 'old'}}}
        atomic_json(workspace.path, old)
        self.sync.upgrade()
        self.assertEqual(read_json(self.store.root / 'backups/opening-analysis/5.json'), old)
        current = workspace.document()
        self.assertEqual(current['overrides'], {})
        self.assertEqual(current['notes'], old['notes'])
        effects = workspace.knowledge(current)
        self.assertIn('breaker', effects['20000003:m2']['roles'])
        self.assertEqual(effects['20000003:m2']['managed_by'], MANAGER)
        saved = self.store.save_deck({'name': '标注驱动统计', 'deck': {'main': [20000003]*40, 'extra': [], 'side': []}})
        result = workspace.analyze({'deck_id': saved['id'], 'revision': saved['revision'], 'hand': [20000003]*5})
        self.assertIn('breaker', result['cards'][0]['roles'])
        self.assertEqual(result['handtrap_count'], 0)

    def test_failed_sync_preserves_original_file_and_can_retry(self):
        previous = self.legacy()
        original = self.store.library.path.read_bytes()
        write = self.store.library.write
        def fail(path, value):
            if path == self.store.library.path: raise OSError('test disk full')
            write(path, value)
        with patch.object(self.store.library, 'write', side_effect=fail), self.assertRaises(OSError): self.sync.upgrade()
        self.assertEqual(self.store.library.path.read_bytes(), original)
        self.assertEqual(read_json(self.store.root / 'backups/tags' / f"{previous['revision']}.json"), previous)
        self.sync.upgrade()
        self.assertEqual(self.store.library.document()['intelligence']['breakers']['20000003']['managed_by'], MANAGER)

    def test_covered_no_longer_qualifying_mark_is_removed_and_uncovered_is_explicit_fallback(self):
        self.store.intelligence.command({'revision': 0, 'op': 'handtrap.save', 'value': {'code': 20000001, 'note': '错误用途'}})
        self.store.intelligence.command({'revision': 1, 'op': 'handtrap.save', 'value': {'code': 20000004, 'note': '尚未标注'}})
        self.sync.upgrade()
        result = self.store.intelligence.snapshot()
        self.assertNotIn('20000001', result['handtraps'])
        self.assertIn('20000004', result['handtraps'])
        self.assertFalse(result['capabilities']['20000004']['trusted'])

    def test_legacy_editor_cannot_override_managed_facts_or_purpose_tag(self):
        self.sync.upgrade()
        revision = self.store.library.document()['revision']
        with self.assertRaisesRegex(ValueError, '统一标注'):
            self.store.intelligence.command({'revision': revision, 'op': 'breaker.save', 'value': {'code': 20000003, 'note': '不能分叉资料'}})
        tag = self.store.library.all_tags()['purpose:boardbreaker']
        with self.assertRaisesRegex(ValueError, '统一标注'):
            self.store.library.edit_tag({'revision': revision, 'id': tag['id'], 'name': tag['name'], 'card_ids': []})

    def test_stale_card_drops_generated_role_without_inventing_replacement(self):
        self.sync.upgrade()
        self.store.catalog.cards[20000003]['desc'] += '新版卡文'
        self.service.reload()
        self.sync.synchronize()
        self.assertNotIn('20000003', self.store.intelligence.snapshot()['breakers'])
        self.assertNotIn('20000003:m2', self.store.opening_workspace.knowledge(self.store.opening_workspace.document()))

    def test_card_level_handtrap_role_does_not_leak_onto_field_followup(self):
        self.sync.public = {'cards': [{'code': 20000003, 'desc': fixtures.DUAL, 'groups': {'handtraps': 'test'},
                                      'effects': {'①': [], '②': []}}]}
        def change(entries):
            entries['20000003']['effects'][2]['structure']['activation']['zones'] = ['monster']
        self.write_curated(change); self.service.reload()
        compiled = self.sync.build()
        self.assertEqual(compiled['libraries']['handtraps']['20000003']['effect_keys'], ['m1'])
        self.assertNotIn('handtrap', compiled['opening']['20000003:m2']['roles'])

    def test_older_client_edits_cannot_silently_override_canonical_content(self):
        self.sync.upgrade()
        document = self.store.library.document()
        document['intelligence']['breakers']['20000003']['note'] = '旧客户端改写'
        atomic_json(self.store.library.path, document)
        self.assertTrue(self.sync.synchronize())
        self.assertNotEqual(self.store.intelligence.snapshot()['breakers']['20000003']['note'], '旧客户端改写')
        revision = self.store.library.document()['revision']
        self.store.intelligence.command({'revision': revision, 'op': 'topic.save', 'value': {'name': '独立断点主题'}})
        self.assertFalse(self.sync.synchronize(), 'Unrelated edits must not repeatedly rewrite the derived libraries')

    def test_details_filters_and_primary_library_share_effect_level_classification(self):
        self.sync.upgrade()
        capability = self.store.card_capabilities.card(20000003)
        role = next(row for row in capability['roles'] if row['role'] == 'breakers')
        self.assertEqual(role['effects'], ['m2'])
        role['effects'].clear()
        self.assertEqual(self.sync.build()['libraries']['breakers']['20000003']['effect_keys'], ['m2'])
        self.assertIn(20000003, self.store.card_capabilities.matching_codes('etag:destroy', 'breakers'))
        self.assertNotIn(20000003, self.store.card_capabilities.matching_codes('etag:special-summon', 'breakers'))

    def test_auto_draft_does_not_claim_authority_over_unannotated_manual_content(self):
        self.store.intelligence.command({'revision': 0, 'op': 'handtrap.save', 'value': {'code': 20000004, 'note': '未覆盖卡的补充'}})
        self.sync.upgrade()
        self.service.command({'op': 'draft', 'code': 20000004})
        self.sync.synchronize()
        self.assertNotIn(20000004, self.sync.build()['covered'])
        self.assertEqual(self.store.intelligence.snapshot()['handtraps']['20000004']['note'], '未覆盖卡的补充')


if __name__ == '__main__': unittest.main()
