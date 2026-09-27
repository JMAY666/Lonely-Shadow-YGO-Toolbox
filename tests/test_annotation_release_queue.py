import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from annotation_release_queue import ReleaseDates, build_queue, eligibility


class ReleaseQueueTests(unittest.TestCase):
    def setUp(self):
        self.dates = ReleaseDates({'retrieved_on': '2026-09-27', 'cards': {
            '1': ['2026-07-18', '2026-10-08'], '2': ['2026-10-01', '2026-01-01'],
            '3': ['', '2026-07-02'], '4': ['2020-01-01', ''],
        }, 'aliases': {'10': 1}})
        self.card = {'type': 0x21, 'desc': 'test', 'source': 'cards.cdb'}

    def test_future_tcg_does_not_exclude_released_ocg(self):
        self.assertIsNone(eligibility(1, self.card, self.dates, '2026-09-27'))
        self.assertIsNone(eligibility(10, self.card, self.dates, '2026-09-27'))

    def test_future_ocg_tcg_only_unknown_and_preview_are_separate(self):
        for code, expected in [(2, 'ocg_not_released'), (3, 'tcg_only_or_ocg_date_unknown'),
                               (5, 'release_date_unknown')]:
            self.assertEqual(eligibility(code, self.card, self.dates, '2026-09-27'), expected)
        self.assertEqual(eligibility(1, {**self.card, 'source': '_trainer/patches/superpre/resources/cards.cdb'},
                                     self.dates, '2026-09-27'), 'preview_source')

    def test_series_debut_not_latest_support_and_unknown_last(self):
        catalog = SimpleNamespace(cards={i: self.card for i in [1, 2, 3, 4, 5]})
        series = SimpleNamespace(members={'old': {1, 4}, 'new': {1}, 'unknown': {5}},
                                 releases={'old': {'date': '2020-01-01'}, 'new': {'date': '2026-07-18'}},
                                 definitions={k: {'name': k} for k in ['old', 'new', 'unknown']})
        result = build_queue(catalog, series, {}, self.dates, '2026-09-27')
        self.assertEqual([r['id'] for r in result['series']], ['new', 'old', 'unknown'])
        self.assertEqual(result['series'][-1]['remaining_codes'], [])


if __name__ == '__main__':
    unittest.main()
