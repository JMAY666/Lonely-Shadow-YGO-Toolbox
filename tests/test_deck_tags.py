from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
import deck_tags
import test_store
from app import Store


class DeckTagTests(unittest.TestCase):
    def setUp(self):
        self.cards = {i: {'id': i, 'name': name, 'setcode': series} for i, name, series in
                      [(1, '系列甲怪兽', 1), (2, '特殊名字', 0x1001), (3, '系列乙卡牌', 2),
                       (4, '副卡组专属', 3), (5, '通用卡', 0), (6, '卡库外部名称', 0)]}
        self.tags = {'a': {'name': '甲系列', 'aliases': ['Alias A'], 'setcode': 1},
                     'b': {'name': '子系列', 'setcode': 0x1001},
                     'c': {'name': '乙系列', 'include_cards': [3, 6]},
                     'side': {'name': '副卡组', 'setcode': 3}}
        self.deck = {'main': [1]*4 + [3]*2 + [5]*32, 'extra': [2]*2, 'side': [4]*15}

    def test_concentration_counts_copies_and_extra_but_excludes_side(self):
        result = deck_tags.suggest(self.deck, self.tags, self.cards)
        self.assertEqual(result['total'], 40)
        self.assertEqual(result['primary_ids'], ['a'])
        self.assertEqual(set(result['tag_ids']), {'a', 'b', 'c'})
        self.assertEqual(result['candidates'][0]['count'], 6)
        self.assertEqual(result['candidates'][0]['cards'][0]['count'], 4)
        self.assertNotIn('side', [c['id'] for c in result['candidates']])

    def test_secondary_threshold_and_no_evidence(self):
        self.deck['main'].remove(3)
        self.assertNotIn('c', deck_tags.suggest(self.deck, self.tags, self.cards)['tag_ids'])
        for deck in ({'main': [], 'extra': [], 'side': [4]}, {'main': [5], 'extra': [], 'side': []}):
            self.assertEqual(deck_tags.suggest(deck, self.tags, self.cards)['tag_ids'], [])
        self.assertEqual(deck_tags.suggest({'main':[3], 'extra':[], 'side':[]}, self.tags, self.cards)['primary_ids'], ['c'])

    def test_ties_prefer_specific_subseries_and_manual_exclusion(self):
        deck = {'main': [2]*3, 'extra': [], 'side': []}
        self.assertEqual(deck_tags.suggest(deck, self.tags, self.cards)['primary_ids'], ['b'])
        self.tags['a']['exclude_cards'] = [2]
        self.assertEqual(deck_tags.suggest(deck, self.tags, self.cards)['tag_ids'], ['b'])

    def test_search_alias_card_name_external_card_and_deck_card_filter(self):
        def ids(query='', cards=None):
            return [t['id'] for t in deck_tags.options(self.deck, self.tags, self.cards, query, cards)['tags']]
        self.assertEqual(ids('ＡＬＩＡＳ ａ'), ['a'])
        self.assertEqual(set(ids('特殊名字')), {'a', 'b'})
        self.assertEqual(ids('卡库外部名称'), ['c'])
        self.assertEqual(ids('', [4]), ['side'])
        self.assertEqual(ids('甲', [4]), [])
        self.assertEqual(set(ids('', [1, 3])), {'a', 'c'})
        with self.assertRaises(ValueError): ids('', [6])
        with self.assertRaises(ValueError): ids('', [True])


class DeckTagStoreTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def make_selection(self):
        first = self.store.library.edit_tag({'name': '测试卡组甲', 'card_ids': [55144522], 'revision': 0})['tag']['id']
        second = self.store.library.edit_tag({'name': '测试卡组乙', 'card_ids': [1184620], 'revision': 1})['tag']['id']
        return {'tag_ids': [first, second], 'primary_ids': [first, second]}

    def test_atomic_save_reopen_rename_legacy_client_and_clear(self):
        chosen = self.make_selection()
        saved = self.store.save_deck({'name': '卡组标签', 'deck': self.deck, 'tag_selection': chosen})
        original = (self.store.decks / '卡组标签.ydk').read_bytes()
        self.assertEqual(Store(self.root).get_deck(saved['id'])['tag_selection'], chosen)
        self.assertEqual(self.store.parse_deck(original), self.deck)
        renamed = self.store.rename_deck({**saved, 'name': '已改名'})
        self.assertEqual(renamed['tag_selection'], chosen)
        legacy = self.store.save_deck({'name': renamed['name'], 'id': renamed['id'], 'revision': renamed['revision'], 'deck': self.deck})
        self.assertEqual(legacy['tag_selection'], chosen)
        cleared = self.store.save_deck({**legacy, 'tag_selection': deck_tags.empty_selection()})
        self.assertEqual(Store(self.root).get_deck(saved['id'])['tag_selection'], deck_tags.empty_selection())
        with self.assertRaisesRegex(ValueError, '修改'): self.store.save_deck({**legacy, 'tag_selection': chosen})
        self.assertEqual(self.store.get_deck(saved['id']), cleared)
        self.assertTrue(any(p.read_bytes() == original for p in (self.store.root / 'backups').glob('*.ydk')))

    def test_invalid_selection_or_write_failure_preserves_deck_and_vocabulary(self):
        chosen = self.make_selection()
        saved = self.store.save_deck({'name': '保护测试', 'deck': self.deck, 'tag_selection': chosen})
        path = self.store.decks / '保护测试.ydk'
        before = path.read_bytes()
        vocabulary = self.store.library.path.read_bytes()
        for invalid in (None, {'tag_ids':['unknown'],'primary_ids':[]}, {'tag_ids':[], 'primary_ids':chosen['primary_ids']},
                        {'tag_ids':chosen['tag_ids']*16, 'primary_ids':[]}):
            with self.assertRaises(ValueError): self.store.save_deck({**saved, 'tag_selection': invalid})
            self.assertEqual(path.read_bytes(), before)
        with patch('app.atomic_bytes', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError): self.store.save_deck({**saved, 'tag_selection': deck_tags.empty_selection()})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.store.library.path.read_bytes(), vocabulary)

    def test_old_ydk_defaults_to_empty_and_reads_do_not_write(self):
        path = self.store.decks / '旧格式.ydk'
        path.write_bytes(self.store.ydk(self.deck))
        before = path.read_bytes()
        saved = self.store.get_deck('library/旧格式.ydk')
        self.assertEqual(saved['tag_selection'], deck_tags.empty_selection())
        self.store.deck_tag_options({'deck': self.deck})
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.store.library.path.exists())

    def test_saved_missing_reference_is_retained_but_new_unknown_is_rejected(self):
        path = self.store.decks / '缺少标签.ydk'
        chosen = {'tag_ids':['custom:missing'], 'primary_ids':['custom:missing']}
        path.write_bytes(self.store.ydk(self.deck, '缺少标签', chosen))
        saved = self.store.get_deck('library/缺少标签.ydk')
        self.assertEqual(self.store.save_deck(saved)['tag_selection'], chosen)
        with self.assertRaises(ValueError): self.store.save_deck({'name':'不能新增未知', 'deck':self.deck, 'tag_selection':chosen})

    def test_suggestions_use_shared_membership_without_changing_plan_rules(self):
        chosen = self.make_selection()
        before = deepcopy(self.deck)
        result = self.store.deck_tag_options({'deck': self.deck})
        self.assertEqual(set(result['suggestions']['tag_ids']), set(chosen['tag_ids']))
        self.assertEqual(len(result['suggestions']['primary_ids']), 1)
        self.assertEqual(self.deck, before)
        self.assertEqual(self.store.library.document()['revision'], 2)

    def test_malformed_metadata_is_reported_and_preserved(self):
        path = self.store.decks / '损坏标签.ydk'
        path.write_bytes(b'#trainer-tags: invalid\n' + self.store.ydk(self.deck))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'TAG 注释无效'): self.store.get_deck('library/损坏标签.ydk')
        self.assertEqual(path.read_bytes(), before)
