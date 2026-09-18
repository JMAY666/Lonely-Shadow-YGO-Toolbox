"""Synthetic protocol fixtures: no user decks, identities or training sessions."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from actions import project_actions
from protocol import packets
from report import build_report, read_journal

POT = 55144522
MONSTER = 1184620


def card(code=POT, instance=1, zone=8, sequence=0):
    return {'code': code, 'name': '强欲之壶' if code == POT else '魔物狩人', 'instance_id': instance,
            'controller': 0, 'location': zone, 'sequence': sequence, 'position': 1}


def event(seq, msg, **fields):
    return {'id': f'{seq}:0', 'native_seq': seq, 'time_ms': seq * 100, 'byte_offset': 0,
            'message': msg, 'type': f'事件{msg}', 'cards': [], 'cost': None, 'targets': None, **fields}


def move(seq, c, origin, destination, reason):
    return event(seq, 50, cards=[c], origin={**c, 'location': origin}, destination={**c, 'location': destination}, reason=reason,
                 cost={'reason_cost': True} if reason & 0x80 else None)


def report(events, initial=None):
    return {'events': events, 'initial_hand_ref': initial, 'status': 'completed',
            'catalog': {str(POT): {'name': '强欲之壶', 'type': 2, 'desc': '①：自己抽2张。'}}}


def pot_sequence(instance=1, start=10, draw_count=2):
    c = card(instance=instance)
    return [move(start, c, 2, 8, 0x2000400), event(start+1, 70, cards=[c], chain=1),
            event(start+2, 71, chain=1), event(start+3, '占位方自动跳过'),
            event(start+4, '玩家选择'), event(start+5, 72, chain=1),
            event(start+6, 90, actor='self', cards=[card(MONSTER, 10+i, 2) for i in range(draw_count)], draw_kind='effect'),
            event(start+7, 73, chain=1), move(start+8, c, 8, 16, 0x400), event(start+9, 74)]


class ActionTests(unittest.TestCase):
    def test_confirm_cards_is_a_recorded_reveal_inside_the_resolving_effect(self):
        shown=card(MONSTER, 20, 64)
        events=[event(1,70,cards=[card()],chain=1),event(2,72,chain=1),
                event(3,31,cards=[shown],player=1),event(4,73,chain=1),event(5,74)]
        frozen=json.dumps(events)
        action=project_actions(report(events))[0]
        self.assertEqual(action['results'][0]['message'],31)
        self.assertEqual(action['revealed_cards'],[shown])
        self.assertIn('展示卡牌',action['execution'][0]['text'])
        self.assertIn('3:0',action['evidence_refs'])
        self.assertEqual(json.dumps(events),frozen)

    def test_reveal_with_a_different_cause_is_not_attributed_to_the_resolving_effect(self):
        events=[event(1,70,cards=[card()],chain=1),event(2,72,chain=1),
                event(3,31,cards=[card(MONSTER,20,64)],cause={'handler_instance':999}),
                event(4,73,chain=1),event(5,74)]
        actions=project_actions(report(events))
        self.assertEqual(actions[0]['results'],[])
        self.assertEqual(actions[1]['kind'],'reveal')

    def test_pot_is_one_action_with_real_count_and_evidence(self):
        initial = event(1, 90, actor='self', cards=[card()]*5, draw_kind='rule')
        events = [initial, event(2, 40), event(3, 41), *pot_sequence()]
        actions = project_actions(report(events, initial['id']))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]['summary'], '在我方魔法陷阱区 1发动强欲之壶的效果：①：自己抽2张。')
        self.assertEqual(actions[0]['observed_summary'], '自己抽 2 张卡')
        self.assertTrue({'10:0', '11:0', '16:0', '17:0', '18:0'}.issubset(actions[0]['evidence_refs']))
        self.assertEqual(len(events), 13)  # Projection never removes raw evidence.

    def test_two_links_resolve_in_reverse_order_without_crossing_results(self):
        events = [event(1, 70, cards=[card(instance=1)], chain=1),
                  event(2, 70, cards=[card(instance=2, sequence=1)], chain=2), event(3, 72, chain=2),
                  event(4, 90, actor='self', cards=[card(MONSTER, 4)], draw_kind='effect'), event(5, 73, chain=2),
                  event(6, 72, chain=1), event(7, 90, actor='self', cards=[card(MONSTER, 5), card(MONSTER, 6)], draw_kind='effect'),
                  event(8, 73, chain=1), event(9, 74)]
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 2)
        self.assertEqual([a['resolution_order'] for a in actions], [2, 1])
        self.assertEqual([a['results'][0]['event_ref'] for a in actions], ['7:0', '4:0'])
        self.assertIn('抽 2 张卡', actions[0]['observed_summary'])
        self.assertIn('抽 1 张卡', actions[1]['observed_summary'])  # Never infer two from text.

    def test_chain_one_reuse_and_same_name_copies_remain_distinct(self):
        actions = project_actions(report(pot_sequence(1, 1) + pot_sequence(2, 20, 1)))
        self.assertEqual(len(actions), 2)
        self.assertEqual([a['chain_group'] for a in actions], [1, 2])
        self.assertNotEqual(actions[0]['cards'][0]['instance_id'], actions[1]['cards'][0]['instance_id'])
        self.assertIn('抽 1 张卡', actions[1]['observed_summary'])

    def test_rule_draw_hidden_but_draw_phase_effect_and_unknown_draw_preserved(self):
        events = [event(1, 41, value=1), event(2, 90, actor='self', cards=[card()], draw_kind='rule'),
                  event(3, 90, actor='self', cards=[card()], draw_kind='effect'),
                  event(4, 90, actor='self', cards=[card()], draw_kind='unknown')]
        actions = project_actions(report(events))
        self.assertEqual([a['id'] for a in actions], ['3:0','4:0'])
        self.assertIn('原因未知', actions[1]['summary'])

    def test_effect_movement_and_cost_are_not_mistaken_for_cleanup(self):
        c = card()
        events = [event(1, 70, cards=[c], chain=1), event(2, 72, chain=1),
                  move(3, c, 8, 16, 0x41), event(4, 73, chain=1), event(5, 74),
                  move(6, card(instance=8), 2, 16, 0x80)]
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 2)
        self.assertIn('破坏并将强欲之壶', actions[0]['observed_summary'])
        self.assertIn('费用', actions[1]['summary'])

    def test_unrelated_rule_movement_is_preserved(self):
        events = pot_sequence()
        events.insert(-1, move(19, card(instance=99), 8, 16, 0x400))
        self.assertEqual(len(project_actions(report(events))), 2)

    def test_negated_and_unfinished_effects_do_not_invent_draws(self):
        for state_msg, label in ((75, '发动被无效'), (76, '效果被无效')):
            events = [event(1, 70, cards=[card()], chain=1), event(2, state_msg, chain=1), event(3, 73, chain=1)]
            a = project_actions(report(events))[0]
            self.assertIn(label, a['status_label']); self.assertNotIn('抽', a['observed_summary'])
            self.assertEqual(a['selected_effect_text'], '①：自己抽2张。')
        a = project_actions(report([event(1, 70, cards=[card()], chain=1)]))[0]
        self.assertIn('尚未确认', a['status_label']); self.assertNotIn('抽', a['observed_summary'])

    def test_different_native_cause_vetoes_resolution_interval(self):
        source = {'effect_id': 1, 'handler_instance': 1}
        events = [event(1, 70, cards=[card()], chain=1, engine_effect=source), event(2, 72, chain=1),
                  event(3, 90, actor='self', cards=[card()], draw_kind='effect', cause={'effect_id': 2, 'handler_instance': 2}),
                  event(4, 73, chain=1)]
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]['results'], [])

    def test_effect_id_reordering_uses_stable_handle_or_resolution_snapshot(self):
        for with_handle in (True, False):
            started = {'effect_id':67,'handler_instance':1}
            resolved = {'effect_id':75,'handler_instance':1}
            if with_handle:
                started['effect_handle']=resolved['effect_handle']=81
            events=[event(1,70,cards=[card()],chain=1,engine_effect=started),
                    event(2,72,chain=1,engine_effect=resolved if not with_handle else None),
                    event(3,90,actor='self',cards=[card(MONSTER)],draw_kind='effect',cause=resolved),event(4,73,chain=1)]
            a=project_actions(report(events))
            self.assertEqual(len(a),1)
            self.assertIn('抽 1 张卡',a[0]['observed_summary'])

    def test_legacy_id_changes_during_operation_reconciled_at_solved(self):
        initial={'effect_id':67,'handler_instance':1}
        final={'effect_id':75,'handler_instance':1}
        events=[event(1,70,cards=[card()],chain=1,engine_effect=initial),event(2,72,chain=1,engine_effect=initial),
                event(3,90,actor='self',cards=[card(MONSTER)],draw_kind='effect',cause=final),
                event(4,73,chain=1,engine_effect=final)]
        a=project_actions(report(events))
        self.assertEqual(len(a),1); self.assertIn('抽 1 张卡',a[0]['observed_summary'])

    def test_no_instance_identity_does_not_merge_two_same_name_cards(self):
        events = pot_sequence(instance=None)
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 3)  # placement and cleanup cannot be identified reliably.

    def test_cost_with_native_source_attaches_to_correct_activation(self):
        source = {'effect_id': 5, 'handler_instance': 1}
        payment = event(1, 100, amount=1000, cost={'lp':1000}, cause=source)
        events = [payment, event(2, 70, cards=[card()], chain=1, engine_effect=source), event(3, 73, chain=1)]
        a = project_actions(report(events))
        self.assertEqual(len(a), 1); self.assertIn('支付 1000 LP', a[0]['observed_summary'])

    def test_normal_summon_combines_placement_start_and_success(self):
        c = card(MONSTER, 4, 4)
        actions = project_actions(report([move(1, c, 2, 4, 0x10), event(2, 60, cards=[c]), event(3, 61, cards=[c])]))
        self.assertEqual(len(actions), 1)
        self.assertTrue('通常召唤魔物狩人' in actions[0]['summary'])

    def test_targets_do_not_guess_between_multiple_links(self):
        events = [event(1, 70, cards=[card()], chain=1), event(2, 70, cards=[card(instance=2)], chain=2),
                  event(3, 83, targets=[card(MONSTER, 8)], cards=[card(MONSTER, 8)])]
        actions = project_actions(report(events))
        self.assertEqual(len(actions), 3); self.assertEqual(actions[-1]['kind'], 'target')


class JournalTests(unittest.TestCase):
    def test_duplicate_cross_session_gap_and_partial_tail(self):
        row = {'session':'test','seq':1,'time_ms':1,'kind':'begin'}
        lines = [row,row,{**row,'session':'other','seq':2},{**row,'seq':3}]
        test_root = Path(__file__).resolve().parents[1] / '.local/test-runs'
        test_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as directory:
            p = Path(directory)/'native.jsonl'
            p.write_text('\n'.join(json.dumps(r) for r in lines)+'\n{"seq":',encoding='utf8')
            rows, issues = read_journal(p,'test')
            self.assertEqual([r['seq'] for r in rows],[1,3]); self.assertEqual(len(issues),3)

    def test_unknown_and_truncated_packets_fail_closed(self):
        for raw in (b'\xff\x5a\x00', b'\x5a\x00\x02\x00'):
            with self.assertRaises(ValueError): list(packets(raw))

    def test_real_packet_draw_reason_does_not_hide_effect_draw_in_draw_phase(self):
        ids = [POT] * 6
        cards = [{**card(c, i+1, 1, i), 'reason':0} for i,c in enumerate(ids)]
        state = {'cards':cards,'turn':0,'turn_player':0,'phase':0,'lp':[8000,8000]}
        loaded = {'seq':1,'time_ms':0,'kind':'loaded','state':state}
        after = json.loads(json.dumps(state)); after['cards'][-1].update(location=2,sequence=0,reason=0x2000400)
        initial = {'seq':2,'time_ms':10,'kind':'batch','raw':(bytes([90,0,1])+struct.pack('<I',POT)).hex(),'state':after}
        after2 = json.loads(json.dumps(after)); after2['cards'][-2].update(location=2,sequence=1,reason=0x2000040)
        effect = {'seq':3,'time_ms':20,'kind':'batch','raw':(bytes([40,0,41,1,0,90,0,1])+struct.pack('<I',POT)).hex(),'state':after2}
        meta={'deck':{'main':ids,'extra':[],'side':[]},'catalog':{str(POT):{'name':'强欲之壶','type':2}},'started_ms':0}
        r=build_report(meta,[loaded,initial,effect],[])
        self.assertEqual(r['initial_hand_ref'],'2:0')
        self.assertEqual(len(r['actions']),1)
        self.assertEqual(r['statistics']['效果抽卡'],1)


if __name__ == '__main__': unittest.main()
