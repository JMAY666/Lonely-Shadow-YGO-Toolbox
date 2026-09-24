from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from card_series import CardSeries, load_presentation


def card(setcode, card_type=0x21, text=''):
    return {'name': '测试卡', 'setcode': setcode, 'type': card_type, 'desc': text}


def tag(value, name='测试系列'):
    return {'id': f'set:{value:x}', 'setcode': value, 'name': name, 'aliases': []}


class CardSeriesTests(unittest.TestCase):
    def series(self, cards, tags=()):
        return CardSeries(SimpleNamespace(cards=cards), {t['id']: t for t in tags}, {'series': []})

    def test_parent_subtype_multiple_series_and_signed_64_bit(self):
        packed = (0x8001 << 48) | (0xaf << 16) | 0x2016
        s = self.series({1: card(packed - (1 << 64)), 2: card(0x1016)},
                        [tag(0x16), tag(0x1016), tag(0x2016), tag(0xaf), tag(0x8001)])
        self.assertEqual(set(s.memberships[1]), {'set:16', 'set:2016', 'set:af', 'set:8001'})
        self.assertNotIn('set:1016', s.memberships[1], 'sibling subtypes never match')
        self.assertEqual(set(s.memberships[2]), {'set:16', 'set:1016'})

    def test_support_text_never_becomes_series_membership_and_tokens_are_excluded(self):
        s = self.series({1: card(0, text='从卡组将1张「青眼」卡加入手卡'), 2: card(0xdd, 0x4011)}, [tag(0xdd, '青眼')])
        self.assertEqual(s.memberships[1], ['unassigned'])
        self.assertNotIn(2, s.memberships)

    def test_unknown_subtype_and_parent_retain_folders_regardless_of_card_order(self):
        s = self.series({1: card(0x1234), 2: card(0x234)})
        self.assertEqual(set(s.memberships[1]), {'set:234', 'set:1234'})
        self.assertIn('未命名系列', s.definitions['set:1234']['name'])
        self.assertNotIn('unassigned', s.memberships[1])

    def test_known_parent_does_not_hide_unknown_subtype(self):
        s = self.series({1: card(0x1234)}, [tag(0x234)])
        self.assertEqual(set(s.memberships[1]), {'set:234', 'set:1234'})

    def test_official_chinese_aliases_and_sample_review_are_separate_from_membership(self):
        s = CardSeries(SimpleNamespace(cards={42741437: card(0x172, 0x800021), 2: card(0x172)}),
                       {'set:172': tag(0x172, '救祓少女')})
        self.assertEqual(s.definitions['set:172']['name'], '驱魔姐妹')
        self.assertTrue(s.matches_query(2, '救祓少女'))
        self.assertTrue(s.matches_query(2, 'exosister'))
        self.assertEqual(s.card_series(42741437)[0]['sample_review'], 'checked')
        self.assertEqual(s.card_series(2)[0]['sample_review'], 'database')
        s.cards[42741437]['type'] = 0x21
        self.assertEqual(s.card_series(42741437)[0]['sample_review'], 'changed')

    def test_folder_counts_match_filtered_cards_and_cover_belongs_to_result(self):
        s = self.series({1: card(0xaf), 2: card((0xaf << 16) | 0x2016), 3: card(0)}, [tag(0xaf), tag(0x2016)])
        results = [{'code': 1, 'status': 'none'}, {'code': 2, 'status': 'reviewed'}]
        folders = {f['id']: f for f in s.folders(results)}
        self.assertEqual(folders['set:af']['count'], 2)
        self.assertEqual(folders['set:af']['annotated'], 1)
        self.assertEqual(folders['set:af']['cover_code'], 2)
        self.assertNotIn('unassigned', folders)
        self.assertEqual(s.folders([results[0]])[0]['cover_code'], 1)

    def test_curated_sources_cover_samples_and_renderable_emblems(self):
        document = load_presentation()
        self.assertTrue(document['series'])
        js = (Path(__file__).resolve().parents[1] / 'src/trainer/web/card-annotations.js').read_text('utf-8')
        for s in document['series']:
            self.assertIn(s['emblem'], js)
            self.assertIn(s['cover_code'], [c['code'] for c in s['samples']])


if __name__ == '__main__':
    unittest.main()
