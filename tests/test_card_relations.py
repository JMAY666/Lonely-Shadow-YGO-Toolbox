from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from card_relations import CardRelations, script_references
from plan_tags import contains_card
import test_store
from app import Catalog, Store


def card(code, name, series=0, desc='', **fields):
    return dict(id=code, name=name, setcode=series, desc=desc, type=1, **fields)


class RelationTests(unittest.TestCase):
    def setUp(self):
        self.tags = {'set:1': {'id': 'set:1', 'name': '星辰', 'aliases': ['Starlight'], 'setcode': 1},
                     'set:1001': {'id': 'set:1001', 'name': '星辰子系', 'aliases': [], 'setcode': 0x1001},
                     'set:2': {'id': 'set:2', 'name': '月影', 'aliases': [], 'setcode': 2}}
        self.cards = {
            1: card(1, '星辰骑士', 0x1001), 2: card(2, '陌生名字', 1),
            3: card(3, '支援魔法', 0, '将「星辰」怪兽加入手卡。'),
            4: card(4, '点名支援', 0, '将「星辰骑士」加入手卡。'),
            5: card(5, '星辰骑士的仿造品'),
            6: card(6, '二跳支援', 0, '将「点名支援」加入手卡。'),
            7: card(7, '泛用卡', 0, '战士族怪兽1只。'),
            8: card(8, '多系列成员', 1 | (2 << 16)), 9: card(9, '月影成员', 2),
            10: card(10, '同名卡', 0, alias=1),
            11: {**card(11, '衍生物', 1, '「星辰骑士」'), 'type': 0x4001},
        }

    def ids(self, result): return {c['id'] for c in result['cards']}

    def test_exact_bidirectional_references_not_prefixes_or_transitive(self):
        index = CardRelations(self.cards, self.tags)
        result = index.search([1])
        self.assertTrue({2, 3, 4, 8, 10} <= self.ids(result))
        self.assertFalse({1, 5, 6, 7, 11} & self.ids(result))
        self.assertIn(1, self.ids(index.search([4])))
        self.assertFalse(contains_card(self.tags['set:1'], 3, self.cards[3]))

    def test_series_tag_does_not_merge_other_archetypes_or_excluded_members(self):
        index = CardRelations(self.cards, self.tags)
        result = index.search([1, 2, 8], series=1, excluded=[4])
        self.assertIn(3, self.ids(result))
        self.assertFalse({4, 9} & self.ids(result))
        self.assertEqual(self.ids(index.search([3])), {1, 2, 8})

    def test_normalization_filtering_and_ambiguous_aliases(self):
        self.cards[12] = card(12, '异名支援', 0, 'Add a “ＳＴＡＲＬＩＧＨＴ” monster.')
        index = CardRelations(self.cards, self.tags)
        self.assertEqual(self.ids(index.search([1], kind='text_series', query='12')), {12})
        self.tags['set:2']['aliases'] = ['Starlight']
        index = CardRelations(self.cards, self.tags)
        self.assertNotIn(12, self.ids(index.search([1])))

    def test_signed_packed_sets_and_sibling_subtypes(self):
        self.cards[20] = card(20, '多字段', ((0xa002 << 48) | 0x1001) - (1 << 64))
        self.cards[21] = card(21, '兄弟字段', 0x2001)
        index = CardRelations(self.cards, self.tags)
        self.assertIn(20, index.members[0x1001])
        self.assertNotIn(21, index.members[0x1001])
        self.assertIn(21, index.members[1])

    def test_stable_pagination_deduplicates_multiple_reasons(self):
        for code in range(100, 180): self.cards[code] = card(code, f'支援 {code}', 0, '「星辰」和「星辰骑士」')
        index = CardRelations(self.cards, self.tags)
        first, second = index.search([1]), index.search([1], offset=60)
        self.assertEqual(len(first['cards']), 60)
        self.assertFalse(self.ids(first) & self.ids(second))
        self.assertEqual(len(self.ids(first) | self.ids(second)), first['total'])
        self.assertGreater(next(c for c in first['cards'] if c['id'] == 100)['relation_count'], 1)

    def test_script_literals_ignore_comments_strings_expressions_and_invalid_ids(self):
        names, series = script_references('''
            -- c:IsCode(901)
            --[=[ c:IsCode(902) ]=]
            local fake = "c:IsCode(903)"
            local long = [==[ c:IsSetCard(0x999) ]==]
            s.listed_names={1, 0x2, 0}
            c100.listed_series={0x1001}
            aux.AddCodeList(c,3)
            Auxiliary.IsCodeListed(c,4)
            c:IsFusionCode(5)
            c:IsCode(id+1)
            c:IsSetCard(0x2)
            not c:IsSetCard(0x3)
            c:IsSetCard(dynamic,0x4)
            c:IsCode(4294967296)
        ''')
        self.assertEqual(names, {1, 2, 3, 4, 5})
        self.assertEqual(series, {0x1001, 2, 3})  # Even negative tests are only references.


class RelationStoreTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def test_draft_discovery_is_read_only_adoption_is_shared_and_persistent(self):
        created = self.store.library.edit_tag({'name': '种子 TAG', 'card_ids': [55144522], 'revision': 0})
        key = created['tag']['id']
        (self.root / 'script/c1184620.lua').write_text('aux.AddCodeList(c,55144522)', encoding='utf-8')
        before = self.store.library.path.read_bytes()
        result = self.store.library.related({'id': key})
        self.assertEqual([c['id'] for c in result['cards']], [1184620])
        self.assertEqual(result['cards'][0]['relation_reasons'][0]['kind'], 'script_card')
        self.assertEqual(self.store.library.path.read_bytes(), before)
        self.assertNotIn(1184620, self.store.library.all_tags()[key]['include_cards'])
        saved = self.store.library.edit_tag({'id': key, 'name': '种子 TAG', 'card_ids': [55144522, 1184620], 'revision': 1})
        self.assertEqual({c['tag_basis'] for c in saved['cards']}, {'手动加入'})
        reopened = Store(self.root)
        self.assertTrue(contains_card(reopened.library.all_tags()[key], 1184620, reopened.catalog.cards[1184620]))
        self.assertEqual(reopened.library.related({'id': key})['cards'], [])
        self.assertEqual((self.store.root / 'backups/tags/1.json').read_bytes(), before)

    def test_resource_replacement_invalidates_index_and_overlay_script_wins(self):
        (self.root / 'script/c1184620.lua').write_text('c:IsCode(55144522)', encoding='utf-8')
        result = self.store.library.related({'seed_id': 55144522})
        self.assertEqual([c['id'] for c in result['cards']], [1184620])
        overlay = self.root / 'expansions/script'
        overlay.mkdir(parents=True)
        (overlay / 'c1184620.lua').write_text('-- overridden; no relationship', encoding='utf-8')
        self.store.catalog = Catalog(self.root)
        self.assertEqual(self.store.library.related({'seed_id': 55144522})['cards'], [])

    def test_draft_exclusion_is_hidden_and_restore_roundtrip(self):
        tag = self.store.library.builtins['set:119']
        self.store.catalog.cards[55144522]['setcode'] = 0x119
        current = self.store.library.members(tag['id'])
        self.assertEqual(current['cards'][0]['tag_basis'], '卡库系列')
        self.assertEqual(self.store.library.related({'id': tag['id'], 'card_ids': []})['cards'], [])
        saved = self.store.library.edit_tag({'id': tag['id'], 'name': tag['name'], 'card_ids': [], 'revision': 0})
        self.assertEqual(saved['excluded_cards'][0]['id'], 55144522)
        restored = self.store.library.edit_tag({'id': tag['id'], 'name': tag['name'], 'card_ids': [55144522], 'revision': 1})
        self.assertEqual(restored['excluded_cards'], [])
        self.assertEqual(restored['cards'][0]['tag_basis'], '卡库系列')

    def test_invalid_queries_and_failed_save_preserve_original(self):
        created = self.store.library.edit_tag({'name': '原始', 'card_ids': [55144522], 'revision': 0})
        key = created['tag']['id']
        before = self.store.library.path.read_bytes()
        for body in ({'seed_id': True}, {'seed_id': 999}, {'card_ids': [True]}, {'card_ids': [999]},
                     {'kind': 'unknown'}, {'offset': -1}, {'offset': True}, {'query': 'a' * 121}, {'id': 'missing'}):
            with self.subTest(body=body), self.assertRaises(ValueError): self.store.library.related(body)
        with patch.object(self.store.library, 'write', side_effect=OSError('isolated failure')):
            with self.assertRaises(OSError):
                self.store.library.edit_tag({'id': key, 'name': '原始', 'card_ids': [55144522, 1184620], 'revision': 1})
        self.assertEqual(self.store.library.path.read_bytes(), before)


if __name__ == '__main__': unittest.main()
