from copy import deepcopy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json
from intelligence import HANDTRAP_ID, BREAKER_ID
from intelligence_staples import load_catalog
from intelligence_marks import effect_parts
import deck_tags
from plan_tags import suggest
import test_store


class StapleCatalogTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def command(self, op, value=None):
        return self.store.intelligence.command({'op': op, 'value': value or {}, 'revision': self.store.library.document()['revision']})

    def install_catalog(self):
        catalog = load_catalog()
        for card in catalog['cards']:
            self.store.catalog.cards[card['code']] = {'id': card['code'], 'name': card['name'], 'desc': card['desc'], 'type': card['type']}
        return catalog

    def test_reviewed_catalog_imports_effects_categories_and_excludes_purpose_tags_from_series(self):
        catalog = self.install_catalog()
        self.assertEqual(len({c['code'] for c in catalog['cards']}), 64)
        result = self.command('staples.import')
        self.assertEqual(len(result['handtraps']), 28)
        self.assertEqual(len(result['breakers']), 39)
        self.assertEqual(len(result['folders']), 18)
        self.assertEqual(result['import_result']['missing'], [])
        self.assertEqual(result['import_result']['pending'], 0)
        for kind in ('handtraps', 'breakers'):
            for card in result[kind].values():
                self.assertEqual(result['folders'][card['folder_id']]['kind'], kind)
                self.assertTrue(card['effects'])
                self.assertTrue(card['note']); self.assertTrue(card['condition'])
                self.assertTrue(card['catalog_sources'][0]['official_url'].startswith('https://www.db.yugioh-card.com/'))
        self.assertEqual(len(result['handtraps']['34267821']['effects']), 1)
        key = next(iter(result['handtraps']['34267821']['effects']))
        self.assertTrue(effect_parts(result['handtraps']['34267821']['desc'])[int(key)].startswith('③：'))
        self.assertNotIn('98127546', result['handtraps'])
        self.assertIn('98127546', result['breakers'])
        tags = self.store.library.all_tags()
        purpose_ids = {key for key, tag in tags.items() if tag.get('kind') == 'purpose'}
        deck = {'main': [14558127, 10045474, 42141493], 'extra': [98127546], 'side': []}
        self.assertFalse(purpose_ids & set(deck_tags.suggest(deck, tags, self.store.catalog.cards)['tag_ids']))
        plan = {'actions': [{'id': '1', 'cards': [{'code': code, 'controller': 0} for code in deck['main']]}]}
        self.assertFalse(purpose_ids & set(suggest(plan, tags, self.store.catalog.cards)['tag_ids']))

    def test_import_preserves_user_notes_folder_endboard_and_backups(self):
        self.install_catalog()
        folder = self.command('folder.save', {'name': '无效'})['saved_id']
        self.command('handtrap.save', {'code': 14558127, 'folder_id': folder, 'note': '原用途', 'condition': '原条件',
                                       'effects': {'1': {'note': '原效果备注'}}})
        endboard = self.command('endboard.save', {'code': 14558127, 'note': '独立终场'})['endboards']
        before = read_json(self.store.library.path)
        result = self.command('staples.import')
        saved = result['handtraps']['14558127']
        self.assertEqual(saved['folder_id'], folder)
        self.assertEqual(saved['note'], '原用途'); self.assertEqual(saved['condition'], '原条件')
        self.assertEqual(saved['effects']['1']['notes'][0]['text'], '原效果备注')
        self.assertGreater(len(saved['effects']['1']['notes']), 1)
        self.assertEqual(result['endboards'], endboard)
        self.assertEqual(len(result['folders']), 18)
        self.assertEqual(read_json(self.store.root/'backups/tags'/f"{before['revision']}.json"), before)

    def test_same_version_does_not_rewrite_or_restore_manually_removed_notes(self):
        self.install_catalog()
        original = self.command('staples.import')
        before = self.store.library.path.read_bytes()
        repeated = self.command('staples.import')
        self.assertEqual(repeated['revision'], original['revision'])
        self.assertFalse(repeated['import_result']['changed'])
        self.assertEqual(self.store.library.path.read_bytes(), before)
        card = deepcopy(repeated['handtraps']['14558127']); card['effects'] = {}; card['note'] = '手动修订'
        saved = self.command('handtrap.save', card)
        again = self.command('staples.import')
        self.assertEqual(again['revision'], saved['revision'])
        self.assertEqual(again['handtraps']['14558127']['effects'], {})
        self.assertEqual(again['handtraps']['14558127']['note'], '手动修订')
        restarted = Store(self.root).intelligence.snapshot()
        self.assertEqual(restarted['handtraps'], again['handtraps'])
        self.assertEqual(restarted['breakers'], again['breakers'])

    def test_missing_and_changed_card_text_are_reported_without_guessing_effect_indexes(self):
        catalog = load_catalog()
        ash = next(c for c in catalog['cards'] if c['code'] == 14558127)
        self.store.catalog.cards[14558127] = {'id': 14558127, 'name': ash['name'], 'desc': '①：已变更的效果。', 'type': ash['type']}
        result = self.command('staples.import')
        self.assertEqual(len(result['handtraps']), 1)
        self.assertEqual(len(result['import_result']['missing']), 63)
        self.assertEqual(result['handtraps']['14558127']['effects'], {})
        self.assertEqual(len(result['handtraps']['14558127']['unmatched_effects']), 1)
        self.assertEqual(result['import_result']['pending'], 1)

    def test_failed_import_or_stale_revision_never_partially_writes(self):
        self.install_catalog()
        self.command('handtrap.save', {'code': 14558127, 'note': '保留'})
        before = self.store.library.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '其他入口'):
            self.store.intelligence.command({'revision': 0, 'op': 'staples.import'})
        with patch.object(self.store.library, 'write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.command('staples.import')
        self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_boardbreaker_membership_and_folders_remain_separate_from_handtraps(self):
        self.install_catalog()
        handfolder = self.command('folder.save', {'name': '同名分类'})['saved_id']
        breakerfolder = self.command('folder.save', {'name': '同名分类', 'kind': 'breakers'})['saved_id']
        self.command('handtrap.save', {'code': 10045474, 'folder_id': handfolder, 'note': '手坑用途'})
        self.command('breaker.save', {'code': 10045474, 'folder_id': breakerfolder, 'note': '解场用途'})
        with self.assertRaisesRegex(ValueError, '当前资料分类'):
            self.command('breaker.save', {'code': 10045474, 'folder_id': handfolder})
        self.command('breaker.save', {'code': 98127546, 'effects': {'1': {'note': '连接后无效'}}})
        with self.assertRaisesRegex(ValueError, '主卡组'):
            self.command('handtrap.save', {'code': 98127546})
        self.store.library.edit_tag({'id': BREAKER_ID, 'name': '解场', 'revision': self.store.library.document()['revision'],
                                    'card_ids': [10045474, 98127546, 90448279]})
        self.command('folder.remove', {'id': breakerfolder})
        result = self.store.intelligence.snapshot()
        self.assertIsNone(result['breakers']['10045474']['folder_id'])
        self.assertEqual(result['handtraps']['10045474']['folder_id'], handfolder)
        self.assertEqual(result['breakers']['10045474']['note'], '解场用途')
        self.command('breaker.remove', {'code': 10045474})
        self.assertIn(10045474, [c['id'] for c in self.store.library.members(HANDTRAP_ID)['cards']])
        self.assertNotIn(10045474, [c['id'] for c in self.store.library.members(BREAKER_ID)['cards']])

    def test_legacy_folder_cannot_be_retyped_with_members_still_inside(self):
        identifier = self.command('folder.save', {'name': '旧分类'})['saved_id']
        document = read_json(self.store.library.path)
        document['intelligence']['folders'][identifier].pop('kind')
        document['intelligence'].pop('breakers')
        document['intelligence'].pop('boardbreaker_tag_id')
        atomic_json(self.store.library.path, document)
        result = self.command('folder.save', {'id': identifier, 'name': '改名', 'kind': 'breakers'})
        self.assertEqual(result['folders'][identifier]['kind'], 'handtraps')
        self.assertEqual(result['breakers'], {})

    def test_reimporting_a_removed_card_reuses_renamed_catalog_folder(self):
        self.install_catalog()
        original = self.command('staples.import')
        folder = original['handtraps']['14558127']['folder_id']
        self.command('folder.save', {'id': folder, 'name': '自定义无效分类'})
        self.command('handtrap.remove', {'code': 14558127})
        result = self.command('staples.import')
        self.assertEqual(result['handtraps']['14558127']['folder_id'], folder)
        self.assertEqual(result['folders'][folder]['name'], '自定义无效分类')
        self.assertEqual(len(result['folders']), 18)

    def test_existing_boardbreaker_tag_members_survive_legacy_intelligence_upgrade(self):
        self.command('handtrap.save', {'code': 55144522})
        document = read_json(self.store.library.path)
        document['intelligence'].pop('breakers')
        document['intelligence'].pop('boardbreaker_tag_id')
        document['entries'].pop(BREAKER_ID)
        identifier = 'custom:' + 'c' * 32
        document['entries'][identifier] = {'id': identifier, 'name': '解场', 'aliases': [], 'setcode': None,
                                            'include_cards': [23995346], 'exclude_cards': []}
        atomic_json(self.store.library.path, document)
        before = self.store.library.path.read_bytes()
        snapshot = self.store.intelligence.snapshot()
        self.assertEqual(snapshot['boardbreaker_tag_id'], identifier)
        self.assertEqual(set(snapshot['breakers']), {'23995346'})
        self.assertEqual(self.store.library.path.read_bytes(), before)
        saved = self.command('handtrap.save', {'code': 55144522, 'note': '保留解场分类'})
        self.assertEqual(set(saved['breakers']), {'23995346'})
        self.assertEqual([c['id'] for c in self.store.library.members(identifier)['cards']], [23995346])


if __name__ == '__main__': unittest.main()
