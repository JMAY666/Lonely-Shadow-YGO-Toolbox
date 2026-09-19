from copy import deepcopy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json
from intelligence import HANDTRAP_ID
from plan_tags import suggest, contains_card
import deck_tags
import test_store
from test_plan_library import sample


class IntelligenceTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def command(self, op, value):
        return self.store.intelligence.command({'op': op, 'value': value, 'revision': self.store.library.document()['revision']})

    def test_endboard_is_independent_from_historical_instances_and_persists(self):
        plan = sample()
        plan['annotations']['final_marks'] = {'1': {'marked': True, 'effects': {'0': {'note': '局部'}}}}
        plan['annotations']['cards'] = {'1': '实例说明'}
        path = self.store.plan_path(plan['id']); atomic_json(path, plan); before = path.read_bytes()
        value = {'code': 55144522, 'candidate': True, 'note': '通用用途', 'effects': {'0': {'note': '通用效果'}}}
        self.command('endboard.save', value)
        self.assertEqual(Store(self.root).intelligence.snapshot()['endboards']['55144522']['note'], '通用用途')
        self.command('endboard.save', {**value, 'note': '修订'})
        self.command('endboard.remove', {'code': 55144522})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.store.intelligence.snapshot()['endboards'], {})

    def test_handtrap_duplicates_tags_folder_move_and_removal_are_atomic(self):
        existing = self.store.library.edit_tag({'revision': 0, 'name': '保留系列', 'card_ids': [55144522]})
        other = existing['tag']['id']
        a = self.command('folder.save', {'name': '常用'})['saved_id']
        b = self.command('folder.save', {'name': '备选'})['saved_id']
        self.command('handtrap.save', {'code': 55144522, 'note': '用途', 'condition': '条件', 'folder_id': a})
        self.command('handtrap.save', {'code': 55144522})
        self.assertEqual(len(self.store.library.members(HANDTRAP_ID)['cards']), 1)
        self.assertEqual(self.store.intelligence.snapshot()['handtraps']['55144522']['note'], '用途')
        self.command('handtrap.save', {'code': 55144522, 'folder_id': b})
        self.command('folder.remove', {'id': b})
        item = self.store.intelligence.snapshot()['handtraps']['55144522']
        self.assertIsNone(item['folder_id']); self.assertEqual(item['note'], '用途')
        self.command('endboard.save', {'code': 55144522, 'note': '终场', 'effects': {}})
        self.command('handtrap.remove', {'code': 55144522})
        self.assertEqual(self.store.library.members(HANDTRAP_ID)['cards'], [])
        self.assertEqual([c['id'] for c in self.store.library.members(other)['cards']], [55144522])
        self.assertIn('55144522', self.store.intelligence.snapshot()['endboards'])

    def test_handtrap_accepts_user_chosen_spells_and_traps_rejects_extra_and_tokens(self):
        self.store.catalog.cards[77] = {'id': 77, 'type': 4, 'desc': '', 'name': '测试陷阱'}
        self.store.catalog.cards[78] = {'id': 78, 'type': 0x4001, 'desc': '', 'name': '测试衍生物'}
        for code in (55144522, 1184620, 77): self.command('handtrap.save', {'code': code})
        for code in (23995346, 78, 12345678, True):
            with self.assertRaises(ValueError): self.command('handtrap.save', {'code': code})
        tag = self.store.library.members(HANDTRAP_ID)
        with self.assertRaisesRegex(ValueError, '主卡组'):
            self.store.library.edit_tag({'id': HANDTRAP_ID, 'revision': tag['revision'], 'name': '手坑', 'card_ids': [23995346]})
        self.assertEqual(len(self.store.intelligence.snapshot()['handtraps']), 3)

    def test_other_tag_entry_point_shares_validation_notes_and_membership(self):
        self.command('handtrap.save', {'code': 55144522, 'note': '保留'})
        self.store.library.edit_tag({'id': HANDTRAP_ID, 'revision': self.store.library.document()['revision'], 'name': '手坑', 'card_ids': [55144522, 1184620, 1184620]})
        value = self.store.intelligence.snapshot()
        self.assertEqual(len(value['handtraps']), 2); self.assertEqual(value['handtraps']['55144522']['note'], '保留')
        self.store.library.edit_tag({'id': HANDTRAP_ID, 'revision': value['revision'], 'name': '手坑', 'card_ids': [1184620]})
        self.assertNotIn('55144522', self.store.intelligence.snapshot()['handtraps'])
        with self.assertRaises(ValueError): self.store.library.edit_tag({'revision': self.store.library.document()['revision'], 'name': '手坑'})

    def test_purpose_tag_does_not_enter_deck_or_plan_automatic_classification(self):
        for code in (55144522, 1184620): self.command('handtrap.save', {'code': code})
        vocabulary = self.store.library.all_tags()
        self.assertTrue(contains_card(vocabulary[HANDTRAP_ID], 55144522, self.store.catalog.cards[55144522]))
        self.assertNotIn(HANDTRAP_ID, deck_tags.suggest(self.deck, vocabulary, self.store.catalog.cards)['tag_ids'])
        plan = {'actions': [{'id': '1', 'cards': [{'code': c, 'controller': 0} for c in (55144522, 1184620)]}]}
        self.assertNotIn(HANDTRAP_ID, suggest(plan, vocabulary, self.store.catalog.cards)['tag_ids'])

    def test_stale_revision_and_disk_failures_keep_previous_document(self):
        self.command('handtrap.save', {'code': 55144522, 'note': '原文'})
        before = self.store.library.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '其他入口'):
            self.store.intelligence.command({'revision': 0, 'op': 'handtrap.save', 'value': {'code': 1184620}})
        real = self.store.library.write
        def fail(path, value):
            if path == self.store.library.path: raise OSError('isolated disk failure')
            return real(path, value)
        with patch.object(self.store.library, 'write', side_effect=fail):
            with self.assertRaises(OSError): self.command('handtrap.remove', {'code': 55144522})
        self.assertEqual(before, self.store.library.path.read_bytes())
        self.assertEqual(len(self.store.library.members(HANDTRAP_ID)['cards']), 1)

    def test_missing_cards_retain_identity_notes_and_effect_snapshot(self):
        self.command('endboard.save', {'code': 55144522, 'effects': {'0': {'note': '旧效果'}}})
        self.command('handtrap.save', {'code': 55144522, 'note': '资料'})
        del self.store.catalog.cards[55144522]
        value = self.store.intelligence.snapshot()
        self.assertTrue(value['cards']['55144522']['missing'])
        self.command('handtrap.save', {'code': 55144522, 'condition': '补充'})
        self.command('endboard.save', {**value['endboards']['55144522'], 'note': '补充'})
        self.assertEqual(self.store.intelligence.snapshot()['endboards']['55144522']['effects']['0']['note'], '旧效果')

    def test_sources_deduplicate_cards_but_keep_conflicts_and_branch_instances(self):
        plan = sample(); plan['annotations']['final_marks'] = {'1': {'marked': True, 'effects': {'0': {'note': '主线'}}}}
        branch = deepcopy(plan); branch['annotations']['cards'] = {'1': '不同用途'}
        plan['branches'] = [{'id': 'branch-a', 'report': branch}]
        path = self.store.plan_path(plan['id']); atomic_json(path, plan); before = path.read_bytes()
        sources = self.store.intelligence.sources()
        self.assertEqual(len(sources['groups']), 1); self.assertEqual(len(sources['groups'][0]['sources']), 2)
        first, second = sources['groups'][0]['sources']
        for source in (first, first, second):
            self.command('endboard.import', {'source_key': source['key'], 'fingerprint': source['fingerprint']})
        annotation = self.store.intelligence.snapshot()['endboards']['101']
        self.assertEqual(annotation['note'], '不同用途'); self.assertEqual(len(annotation['sources']), 2)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, '来源方案已改变'):
            self.command('endboard.import', {'source_key': first['key'], 'fingerprint': 'stale'})

    def record(self):
        topic = self.command('topic.save', {'name': '自定义主题', 'tag_ids': [HANDTRAP_ID]})['saved_id']
        return {'title': '测试断点', 'topic_id': topic, 'steps': [{'opponent': 23995346, 'action': '发动效果', 'timing': '发动时', 'condition': '满足条件', 'responses': [
            {'cards': [55144522], 'mode': 'alternative', 'condition': '说明 A', 'expected': '预期 A'},
            {'cards': [55144522, 1184620], 'mode': 'combination', 'condition': '说明 B', 'expected': '预期 B'}]}]}

    def test_breakpoint_options_combinations_order_missing_and_pending_status(self):
        record = self.record()
        record['steps'].append({'opponent': 1184620, 'action': '未补全操作', 'responses': []})
        result = self.command('record.save', record); identifier = result['saved_id']
        self.assertEqual(result['records'][identifier]['status'], '待补充')
        record = result['records'][identifier]; record['steps'].reverse()
        self.command('record.save', record)
        restart = Store(self.root).intelligence.snapshot()
        saved = restart['records'][identifier]
        self.assertEqual(saved['steps'][0]['opponent'], 1184620)
        self.assertEqual(saved['steps'][1]['responses'][1]['mode'], 'combination')
        self.assertEqual(restart['handtraps'], {})
        del self.store.catalog.cards[23995346]
        self.command('record.save', saved)
        self.assertIn('23995346', self.store.intelligence.snapshot()['cards'])
        saved['steps'] = saved['steps'][1:]
        self.assertEqual(self.command('record.save', saved)['records'][identifier]['status'], '待核对')

    def test_multiple_cards_require_explicit_combination_and_topics_preserve_records(self):
        record = self.record(); record['steps'][0]['responses'][1]['mode'] = 'alternative'
        with self.assertRaisesRegex(ValueError, '组合'): self.command('record.save', record)
        record['steps'][0]['responses'][1]['mode'] = 'combination'
        saved = self.command('record.save', record)
        with self.assertRaisesRegex(ValueError, '仍有断点'): self.command('topic.remove', {'id': record['topic_id']})
        self.command('record.remove', {'id': saved['saved_id']})
        self.command('topic.remove', {'id': record['topic_id']})

    def test_existing_handtrap_tag_identity_is_reused_and_first_write_is_backed_up(self):
        identifier = 'custom:' + 'a'*32
        original = {'version': 1, 'revision': 3, 'entries': {identifier: {'id': identifier, 'name': '手坑', 'aliases': [], 'setcode': None, 'include_cards': [55144522]}}}
        atomic_json(self.store.library.path, original)
        self.assertEqual(self.store.intelligence.snapshot()['handtrap_tag_id'], identifier)
        self.command('handtrap.save', {'code': 1184620})
        self.assertEqual(read_json(self.store.root/'backups/tags/3.json'), original)
        self.assertEqual(len([t for t in self.store.library.all_tags().values() if t['name'] == '手坑']), 1)
        atomic_json(self.store.library.path, read_json(self.store.root/'backups/tags/3.json'))
        self.assertEqual(set(Store(self.root).intelligence.snapshot()['handtraps']), {'55144522'})

    def test_catalog_filters_compose_before_pagination(self):
        result = self.store.catalog.search('', 'spell', card_ids={55144522, 23995346}, main_only=True, level='')
        self.assertEqual([c['id'] for c in result['cards']], [55144522])
        self.assertEqual(self.store.catalog.search('', 'extra', main_only=True)['total'], 0)


if __name__ == '__main__': unittest.main()
