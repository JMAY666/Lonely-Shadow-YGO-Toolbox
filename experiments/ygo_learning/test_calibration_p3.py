"""Calibration goals must be measured before the opponent or next own draw."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from calibration_p3 import TurnObserver, goal_view, latest_condition_session, CalibrationBudget


class TurnBoundaryTests(unittest.TestCase):
    def test_cumulative_deadline_stops_before_next_engine_node(self):
        with tempfile.TemporaryDirectory() as folder:
            budget = CalibrationBudget.__new__(CalibrationBudget)
            budget.progress_path = Path(folder) / 'compute-progress.json'
            budget.previous_compute = 7199
            budget.compute_started = time.monotonic() - 2
            budget.last_saved = 0
            with self.assertRaisesRegex(ValueError, 'two-hour'):
                budget.check()
            self.assertGreaterEqual(json.loads(budget.progress_path.read_text())['worker_seconds'], 2)

    def test_first_turn_two_snapshot_is_preserved(self):
        observer = TurnObserver()
        for turn, cards in [(1, [1]), (2, [1]), (3, [1, 2])]:
            observer.consume({'kind': 'batch', 'seq': turn,
                              'state': {'turn': turn, 'cards': cards}, 'raw': ''})
        self.assertEqual([1], observer.terminal['cards'])
        self.assertEqual(2, observer.terminal_seq)

    def test_only_actual_first_turn_self_draw_counts(self):
        observer = TurnObserver()
        for turn, raw in [(0, '5a000100000000'), (1, '5a000100000000'),
                          (1, '5a010100000000'), (3, '5a000100000000')]:
            observer.consume({'kind': 'batch', 'seq': 1, 'raw': raw,
                              'state': {'turn': turn, 'cards': []}})
        self.assertEqual(1, observer.draws)

    def test_goal_view_masks_unknown_identity(self):
        view = goal_view({'cards': [{'controller': 1, 'location': 2, 'sequence': 0,
                                    'position': 8, 'code': 123456, 'disabled': False}]})
        self.assertEqual(0, view['cards'][0]['code'])
        self.assertFalse(view['cards'][0]['identity_known'])

    def test_retry_follows_same_condition_and_rejects_changed_random_truth(self):
        from contract_v2 import digest
        original = '11111111-1111-4111-8111-111111111111'
        retry = '22222222-2222-4222-8222-222222222222'
        expansion = {'engine_seed': 42, 'draw_order': [3, 1, 2]}
        with tempfile.TemporaryDirectory() as folder:
            for sid, meta in [(original, {'expansion': expansion, 'retry_id': retry}),
                              (retry, {'expansion': expansion})]:
                path = Path(folder) / sid
                path.mkdir()
                (path / 'session.json').write_text(json.dumps(meta), encoding='utf-8')
            self.assertEqual(retry, latest_condition_session(Path(folder), original, digest(expansion)))
            (Path(folder) / retry / 'session.json').write_text(json.dumps({'expansion': {}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'condition'):
                latest_condition_session(Path(folder), original, digest(expansion))


if __name__ == '__main__':
    unittest.main()
