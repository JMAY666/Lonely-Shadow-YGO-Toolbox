from datetime import date
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
sys.path.insert(0, str(ROOT / 'scripts'))
from card_release_dates import ReleaseDates, load_release_dates, valid_date
from card_series import CardSeries
from build_card_release_dates import extract


def dates(cards, aliases=None):
    return ReleaseDates({'retrieved_on': '2026-09-24', 'cards': cards, 'aliases': aliases or {}})


class CardReleaseDateTests(unittest.TestCase):
    def test_physical_debut_uses_earliest_region_and_explicit_aliases(self):
        db = dates({'1': ['2024-09-28', '2023-07-27'], '2': ['2025-01-25', '']}, {'100001': 1})
        self.assertEqual(db.card(1)['date'], '2023-07-27')
        self.assertEqual(db.card(1)['region'], 'TCG')
        self.assertEqual(db.card(100001)['source_code'], 1)
        self.assertIsNone(db.card(3))
        self.assertEqual(db.first({1, 2, 3})['known_cards'], 2)

    def test_missing_and_future_dates_stay_explicit(self):
        db = dates({'1': ['2099-01-01', '']})
        self.assertTrue(db.first({1})['scheduled'])
        self.assertNotIn('date', db.first({2}))
        self.assertEqual(db.first({2})['known_cards'], 0)
        for value in ('2024-02-30', '2025-2-3', 'unknown'):
            with self.assertRaises(ValueError): valid_date(value)

    def test_series_date_uses_full_membership_even_when_only_a_newer_card_matches(self):
        catalog = SimpleNamespace(cards={1: {'type': 0x21, 'setcode': 0xaf}, 2: {'type': 0x21, 'setcode': 0xaf}})
        db = dates({'1': ['2004-04-01', ''], '2': ['2025-01-25', '']})
        series = CardSeries(catalog, {'set:af': {'id': 'set:af', 'setcode': 0xaf, 'name': '测试系列'}},
                            {'series': []}, releases=db)
        folder = series.folders([{'code': 2, 'status': 'reviewed'}])[0]
        self.assertEqual(folder['cover_code'], 2)
        self.assertEqual(folder['release']['date'], '2004-04-01')
        self.assertEqual(folder['release']['total_cards'], 2)

    def test_extraction_keeps_only_dates_and_unambiguous_provider_identity(self):
        raw = json.dumps({'data': [
            {'id': 1, 'name': '不要复制卡文', 'desc': 'not part of release data',
             'misc_info': [{'ocg_date': '2025-01-25', 'beta_id': 100001}], 'card_images': [{'id': 11}]},
            {'id': 2, 'misc_info': [{'tcg_date': '2024-01-25', 'beta_id': 100001}]},
        ]}).encode()
        result = extract(raw, '2026-09-24')
        self.assertEqual(result['cards'][1], ['2025-01-25', ''])
        self.assertNotIn(100001, result['aliases'], 'ambiguous provisional IDs never pick a card')
        self.assertEqual(result['aliases'][11], 1)
        self.assertNotIn('not part of release data', json.dumps(result))

    def test_empty_or_conflicting_snapshots_do_not_replace_good_data(self):
        with self.assertRaises(ValueError): extract(b'{"data": []}', '2026-09-24')
        raw = json.dumps({'data': [{'id': 1, 'misc_info': [
            {'ocg_date': '2025-01-25'}, {'ocg_date': '2024-01-25'}]}]}).encode()
        with self.assertRaises(ValueError): extract(raw, '2026-09-24')

    def test_bundled_offline_snapshot_matches_spot_checked_physical_dates(self):
        db = ReleaseDates(load_release_dates())
        self.assertEqual(db.card(16387555)['date'], '2025-08-23')
        self.assertEqual(db.card(42741437)['date'], '2021-08-28')
        self.assertEqual(db.card(94620082)['date'], '2018-07-14')
        self.assertLessEqual(date.fromisoformat(db.document['retrieved_on']), date.today())


if __name__ == '__main__':
    unittest.main()
