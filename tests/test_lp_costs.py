"""LP fees carry no card id: verify attribution from protocol windows and snapshots."""
from copy import deepcopy
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from report import build_report

CODE = 77913594
SOURCE = {'effect_id': 10, 'effect_handle': 20, 'handler_instance': 1, 'handler_code': CODE}
CARD = {'code': CODE, 'name': '测试魔法', 'instance_id': 1, 'controller': 0, 'location': 8, 'sequence': 1, 'position': 1}
META = {'started_ms': 0, 'deck': {'main': [], 'extra': [], 'side': []},
        'catalog': {str(CODE): {'name': '测试魔法', 'desc': '①：支付800基本分才能发动。自己抽1张。', 'type': 2}}}


def chaining(link):
    return bytes([70]) + struct.pack('<I', CODE) + bytes([0, 8, 1, 1, 0, 8, 1]) + struct.pack('<I', 0) + bytes([link])


def payment(amount=800, player=0): return bytes([100, player]) + struct.pack('<I', amount)


def row(seq, payload=None, links=(1,), source=None):
    state = {'cards': [deepcopy(CARD)], 'turn': 1, 'phase': 4, 'turn_player': 0, 'lp': [8000, 8000],
             'chains': [{'link': link, 'effect': deepcopy(source or SOURCE)} for link in links]}
    return {'seq': seq, 'time_ms': seq, 'kind': 'loaded' if payload is None else 'batch',
            'state': state, 'raw': '' if payload is None else payload.hex()}


class LPCostTests(unittest.TestCase):
    def build(self, rows): return build_report(META, rows, [])

    def test_real_amount_attaches_first_and_raw_records_stay_unchanged(self):
        for amount in (800, 1200):
            rows = [row(1), row(2, chaining(1)), row(3, payment(amount)), row(4, bytes([71, 1]))]
            original = deepcopy(rows)
            r = self.build(rows)
            self.assertEqual(len(r['actions']), 1)
            a = r['actions'][0]
            self.assertEqual(a['execution'][0]['role'], 'cost')
            self.assertEqual(a['execution'][0]['text'], f'支付 {amount} LP 作为费用')
            self.assertIn('3:0', a['evidence_refs'])
            self.assertEqual(r['events'][1]['cost_activation_ref'], '2:0')
            self.assertEqual(rows, original)

    def test_second_link_does_not_pay_for_first_even_with_same_effect_identity(self):
        r = self.build([row(1), row(2, chaining(1)), row(3, bytes([71, 1])), row(4, chaining(2), (1, 2)),
                        row(5, payment(), (1, 2)), row(6, bytes([71, 2]), (1, 2))])
        self.assertEqual(len(r['actions']), 2)
        self.assertEqual(r['actions'][0]['costs'], [])
        self.assertEqual(len(r['actions'][1]['costs']), 1)
        self.assertEqual(r['events'][3]['cost_activation_ref'], '4:0')

    def test_closed_construction_window_does_not_absorb_unrelated_payment(self):
        r = self.build([row(1), row(2, chaining(1)), row(3, bytes([71, 1])), row(4, payment())])
        self.assertEqual(len(r['actions']), 2)
        self.assertEqual(r['actions'][0]['costs'], [])
        self.assertEqual(r['actions'][1]['kind'], 'cost')

    def test_mismatched_payer_or_snapshot_and_missing_snapshot_remain_independent(self):
        variants = [row(3, payment(player=1)), row(3, payment(), source={**SOURCE, 'handler_instance': 2}), row(3, payment(), ())]
        for fee in variants:
            with self.subTest(fee=fee['raw']):
                r = self.build([row(1), row(2, chaining(1)), fee])
                self.assertEqual(len(r['actions']), 2)
                self.assertNotIn('cost_activation_ref', r['events'][-1])

    def test_gap_and_overlapping_builds_fail_closed(self):
        gap = self.build([row(1), row(2, chaining(1)), row(4, payment())])
        self.assertEqual(gap['actions'][-1]['kind'], 'cost')
        overlap = self.build([row(1), row(2, chaining(1)), row(3, chaining(2), (1, 2)), row(4, payment(), (1, 2))])
        self.assertEqual(overlap['actions'][-1]['kind'], 'cost')

    def test_chain_end_and_phase_changes_invalidate_open_window(self):
        for boundary in (bytes([74]), bytes([40, 0]), bytes([41, 4, 0])):
            r = self.build([row(1), row(2, chaining(1)), row(3, boundary), row(4, payment())])
            self.assertEqual(r['actions'][-1]['kind'], 'cost')

    def test_effect_text_does_not_invent_payment(self):
        r = self.build([row(1), row(2, chaining(1)), row(3, bytes([71, 1]))])
        self.assertEqual(r['actions'][0]['costs'], [])
        self.assertEqual(r['actions'][0]['execution'], [])


if __name__ == '__main__': unittest.main()
