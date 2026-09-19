"""Safety/correctness contracts that do not load model dependencies."""
import hashlib
import io
import json
import struct
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from adapter import NativeInput
from bootstrap import verify
from policy import Policy
from run import validate_service
from experiments.ygo_agent import report

CATALOG = {code: {'name': str(code), 'type': 33, 'level': 4, 'atk': 1700,
                 'def': 1800, 'race': 0x800000, 'attribute': 2}
           for code in (20001443, 93490856, 23431858)}


def card(code, zone, seq=0, player=0):
    return {'code': code, 'controller': player, 'location': zone, 'sequence': seq,
            'position': 10 if zone in (1, 2, 64) else 1, 'counters': [], 'disabled': False}


def snapshot():
    raw = bytes([11, 0, 1]) + struct.pack('<IBBB', 20001443, 0, 2, 0) + bytes([0] * 6 + [1, 0])
    return {'version': 1, 'player': 0, 'answered': False, 'raw': raw.hex(), 'state': {
        'lp': [8000, 8000], 'turn': 1, 'turn_player': 0, 'phase': 4,
        'cards': [card(20001443, 2), card(93490856, 1), card(23431858, 1, 1), card(99999999, 2, player=1)]}}


class AdapterTests(unittest.TestCase):
    def test_report_preserves_a_blocked_attempt_with_no_predictions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / 'evidence/baseline-1'
            case.mkdir(parents=True)
            (case / 'result.json').write_text(json.dumps({'case': 'baseline', 'status': 'blocked', 'steps': []}), encoding='utf-8')
            with patch.object(report, 'LOCAL', root), redirect_stdout(io.StringIO()): report.main()
            summary = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
            self.assertIsNone(summary['median_ms'])
            self.assertEqual(summary['native_actions_confirmed'], 0)
            self.assertIn('试验停止：blocked', (root / 'report.md').read_text(encoding='utf-8'))

    def test_wrong_service_is_rejected_before_creating_decks(self):
        expected = Path('isolated-pilot').resolve()
        validate_service({'embedded': True, 'runtime': str(expected)}, expected)
        with self.assertRaisesRegex(ValueError, 'isolated'):
            validate_service({'embedded': True, 'runtime': str(Path('user-data').resolve())}, expected)
        with self.assertRaisesRegex(ValueError, 'isolated'):
            validate_service({'embedded': False, 'runtime': str(expected)}, expected)

    def test_opponent_hidden_identity_and_attributes_never_reach_model(self):
        first, second = snapshot(), snapshot()
        second['state']['cards'][-1].update(code=123, status_flags=0x4000000, disabled=True,
                                           counters=[{'count': 9}])
        a, b = NativeInput(first, CATALOG).input(), NativeInput(second, CATALOG).input()
        self.assertEqual(a, b)
        self.assertEqual(a['cards'][-1]['code'], 0)
        self.assertEqual(a['cards'][-1]['types'], [])

    def test_deck_shuffle_and_instance_insertion_order_do_not_change_observation(self):
        first, second = snapshot(), snapshot()
        second['state']['cards'][1]['sequence'], second['state']['cards'][2]['sequence'] = 1, 0
        second['state']['cards'].reverse()
        self.assertEqual(NativeInput(first, CATALOG).input(), NativeInput(second, CATALOG).input())

    def test_native_action_identity_is_preserved(self):
        native = NativeInput(snapshot(), CATALOG)
        self.assertEqual(native.input()['action_msg']['data']['idle_cmds'][0]['data']['response'], 0)
        self.assertEqual(native.response({'response': 0}, []), '00000000')
        self.assertEqual(native.response({'response': 7}, []), '07000000')

    def test_unrecognized_action_does_not_become_default(self):
        with self.assertRaises(StopIteration): NativeInput(snapshot(), CATALOG).response({'response': 99}, [])

    def test_missing_visible_card_data_stops_prediction(self):
        with self.assertRaises(KeyError): NativeInput(snapshot(), {})

    def test_unknown_window_stops_prediction(self):
        value = snapshot()
        value['raw'] = bytes([142, 0, 1]).hex() + struct.pack('<I', 1).hex()
        with self.assertRaisesRegex(ValueError, 'coverage'): NativeInput(value, CATALOG).input()

    def test_later_turn_is_not_silently_encoded_as_first_turn(self):
        value = snapshot()
        value['state']['turn'] = 3
        with self.assertRaisesRegex(ValueError, 'first player first turn'): NativeInput(value, CATALOG)

    def test_card_capacity_is_not_silently_truncated(self):
        value = snapshot()
        value['state']['cards'].extend(card(93490856, 1, i + 2) for i in range(160))
        with self.assertRaisesRegex(ValueError, 'capacity'): NativeInput(value, CATALOG)

    def test_action_capacity_is_not_silently_truncated(self):
        policy = Policy.__new__(Policy)
        policy.np = None
        policy.features = SimpleNamespace(MAX_ACTIONS=24,
            Input=SimpleNamespace(model_validate=lambda _: SimpleNamespace(action_msg=None)),
            get_legal_actions=lambda _: [None] * 25)
        with self.assertRaisesRegex(ValueError, 'capacity'): policy._step({})

    def test_history_only_commits_the_exact_acknowledged_action(self):
        policy = Policy.__new__(Policy)
        policy.rstate, policy.history = 'old recurrent state', 'old history'
        policy.pending = ({'version': 4, 'prompt': 'aa', 'response': 'bb'}, ('new recurrent state', 'new history'))
        with self.assertRaisesRegex(ValueError, 'differs'): policy.commit(3, 'aa', 'bb')
        self.assertEqual(policy.history, 'old history')
        with self.assertRaisesRegex(ValueError, 'differs'): policy.commit(4, 'aa', 'cc')
        policy.commit(4, 'aa', 'bb')
        self.assertEqual(policy.history, 'new history')
        self.assertIsNone(policy.pending)

    def test_modified_download_is_rejected(self):
        record = {'path': 'model', 'bytes': 3, 'sha256': hashlib.sha256(b'abc').hexdigest()}
        verify(b'abc', record)
        with self.assertRaisesRegex(ValueError, 'integrity'): verify(b'abd', record)


if __name__ == '__main__': unittest.main()
