"""Synthetic battle journals: omit routine combat without losing actual effects."""
from copy import deepcopy
import struct
import unittest

from test_reports import card, event, move, report
from actions import project_actions
from report import build_report


class BattleRecordTests(unittest.TestCase):
    def test_plain_battle_does_not_add_steps_or_mutate_evidence(self):
        events = [event(1, 110), event(2, 113), event(3, 111),
                  event(4, 2), event(5, 91, player=1, amount=1850),
                  event(6, 94, player=1, amount=6150), event(7, 91, player=0, amount=500),
                  event(8, 114), event(9, 41)]
        original = deepcopy(events)
        self.assertEqual(project_actions(report(events)), [])
        self.assertEqual(events, original)

    def test_zero_damage_and_repeated_attacks_are_hidden(self):
        events = [event(1, 110), event(2, 113), event(3, 111), event(4, 114),
                  event(5, 110), event(6, 113), event(7, 111),
                  event(8, 91, player=1, amount=1850), event(9, 114)]
        self.assertEqual(project_actions(report(events)), [])

    def test_battle_trigger_keeps_cost_damage_and_recovery_with_its_effect(self):
        source = {'effect_id': 10, 'handler_instance': 1}
        events = [event(1, 110), event(2, 113), event(3, 111),
                  event(4, 91, player=1, amount=1850),
                  event(5, 70, cards=[card()], chain=1, engine_effect=source),
                  event(6, 100, player=0, amount=800, cost={'lp': 800}, cause=source),
                  event(7, 71, chain=1), event(8, 72, chain=1),
                  event(9, 91, player=1, amount=500), event(10, 92, player=0, amount=300),
                  event(11, 73, chain=1), event(12, 74), event(13, 114)]
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['kind'], 'effect')
        self.assertEqual([s['text'] for s in actions[0]['execution']],
                         ['支付 800 LP 作为费用', '占位方受到 500 伤害', '我方回复 300 LP'])
        self.assertNotIn('4:0', actions[0]['evidence_refs'])

    def test_effect_before_damage_calculation_does_not_keep_later_battle_damage(self):
        events = [event(1, 110), event(2, 113), event(3, 70, cards=[card()], chain=1),
                  event(4, 72, chain=1), event(5, 91, player=1, amount=500),
                  event(6, 73, chain=1), event(7, 74), event(8, 111),
                  event(9, 91, player=1, amount=1850), event(10, 114)]
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['observed_summary'], '占位方受到 500 伤害')

    def test_unknown_damage_and_damage_with_a_native_cause_remain_visible(self):
        for boundary in (10, 11, 40, 41, 70, 73, 74, 110, 113, 114, '效果脚本错误'):
            with self.subTest(boundary=boundary):
                actions = project_actions(report([event(1, 111), event(2, boundary),
                                                  event(3, 91, player=1, amount=500)]))
                self.assertIn('3:0', [a['id'] for a in actions])
        for events in ([event(1, 111), event(3, 91, player=1, amount=500)],
                       [event(1, 111), event(2, 91, player=1, amount=500, cause={'handler_instance': 2})],
                       [event(1, 91, player=1, amount=500)]):
            self.assertEqual(project_actions(report(events))[-1]['summary'], '占位方受到 500 伤害')

    def test_only_plain_battle_destruction_is_hidden(self):
        for reason in (0x20, 0x21):
            self.assertEqual(project_actions(report([move(1, card(zone=4), 4, 16, reason)])), [])
        for reason in (0x41, 0x61, 0xa1, 0x4000021, 0):
            with self.subTest(reason=reason):
                self.assertEqual(len(project_actions(report([move(1, card(zone=4), 4, 16, reason)]))), 1)
        redirected = move(1, card(zone=4), 4, 32, 0x21)
        attributed = move(2, card(zone=4), 4, 16, 0x21)
        attributed['cause'] = {'handler_instance': 2}
        self.assertEqual(len(project_actions(report([redirected, attributed]))), 2)

    def test_attack_negation_is_kept_as_an_actual_effect_result(self):
        events = [event(1, 110), event(2, 70, cards=[card()], chain=1),
                  event(3, 72, chain=1), event(4, 112, type='攻击无效'),
                  event(5, 73, chain=1), event(6, 74)]
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['observed_summary'], '攻击无效')

    def test_battle_packets_keep_raw_events_final_lp_and_zero_step_count(self):
        payload = (bytes([110]) + bytes([0, 4, 0, 1]) + bytes(4) + bytes([113, 111]) + bytes(26)
                   + bytes([91, 1]) + struct.pack('<I', 1850) + bytes([114]))
        state = {'cards': [], 'turn': 3, 'turn_player': 0, 'phase': 8, 'lp': [8000, 6150]}
        rows = [{'seq': 1, 'time_ms': 1, 'kind': 'batch', 'raw': payload.hex(), 'state': state}]
        original = deepcopy(rows)
        meta = {'started_ms': 0, 'deck': {'main': [], 'extra': [], 'side': []}, 'catalog': {}}
        result = build_report(meta, rows, [])
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['actions'], [])
        self.assertEqual(result['statistics']['展开步骤'], 0)
        self.assertEqual([e['message'] for e in result['events']], [110, 113, 111, 91, 114])
        self.assertEqual(result['events'][3]['amount'], 1850)
        self.assertEqual(result['final_state']['lp'], [8000, 6150])
        self.assertEqual(rows, original)


if __name__ == '__main__':
    unittest.main()
