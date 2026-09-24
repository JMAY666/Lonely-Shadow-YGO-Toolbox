"""Synthetic evidence: not a claim of a real MDPRO3 game passing acceptance."""
from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from duel_follow import Follower, FollowService, formal_contract, temporary_contract, manual_expected
from duel_follow_events import EvidenceError, Journal, packet, read_packet, match_token, signature


HAND = [11, 11, 12, 13, 14]


def move(code, origin, dest):
    return (50, struct.pack('<I', code) + bytes(origin) + bytes(dest) + struct.pack('<I', 0))


SUMMON = [move(11, (0, 2, 0, 0), (0, 4, 0, 1)), (60, struct.pack('<I4B', 11, 0, 4, 0, 1)), (61, b'')]
ACTIVATE = [(70, struct.pack('<I4B3BIB', 11, 0, 4, 0, 1, 0, 4, 0, 176, 1)), (71, b'\x01'), (72, b'\x01')]
RESOLVE = [move(99, (0, 1, 3, 0), (0, 2, 4, 0)), (73, b'\x01'), (74, b'')]


def opening():
    return [(4, struct.pack('<Bii4H', 0, 8000, 8000, 40, 1, 40, 0)),
            (90, bytes([0, 5]) + struct.pack('<5I', *HAND)), (40, b'\0'), (41, b'\x04\0')]


def records(events):
    return [{'seq': i, 'ref': str(1000+i), **packet(kind, raw)} for i, (kind, raw) in enumerate(events)]


def state_from(events):
    journal = Journal()
    for record in records(events): journal.apply(record)
    return journal.state()


def complete_state(value):
    value=deepcopy(value)
    for zone in (1,64):
        value['cards'] += [{'code':0,'controller':0,'location':zone,'sequence':i,'position':0}
                           for i in range(value['counts'].get(zone,0))]
    return value


def sample(events, offset=0):
    rows = records(events)
    return {'capture_id': 'capture', 'game': 'game', 'duel_token': 'duel', 'turn': 1,
            'processed': len(rows), 'records': rows[max(0, offset-1):], 'state': state_from(events),
            'sampled_ms': 1000, 'prompt': 11}


def contract(groups=None):
    journal = Journal(HAND, 40, 1); journal.turn = 1
    steps = []
    for i, events in enumerate(groups or [SUMMON, ACTIVATE+RESOLVE]):
        start = len(journal.tokens)
        for record in records(events): journal.apply(record)
        steps.append({'key': 'main/s'+str(i+1), 'tokens': deepcopy(journal.tokens[start:]), 'reason': ''})
    return {'kind': 'formal', 'revision': 'revision', 'hand': HAND, 'steps': steps}


class FollowEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.follow = Follower(contract(), HAND); self.confirm = Mock()

    def feed(self, events):
        if self.follow.ingest(sample(events, len(self.follow.records))): self.follow.advance(self.confirm, 1250)

    def test_normal_steps_require_success_and_complete_chain_not_one_event_per_step(self):
        self.feed(opening()); self.assertEqual(self.follow.status, 'following')
        self.feed(opening()+SUMMON[:2]); self.assertEqual(self.follow.status, 'executing')
        self.confirm.assert_not_called()
        self.feed(opening()+SUMMON); self.assertEqual(len(self.follow.completed), 1)
        self.feed(opening()+SUMMON+ACTIVATE); self.assertEqual(len(self.follow.completed), 1)
        self.feed(opening()+SUMMON+ACTIVATE+RESOLVE[:-1]); self.assertEqual(len(self.follow.completed), 1)
        self.feed(opening()+SUMMON+ACTIVATE+RESOLVE); self.assertEqual(len(self.follow.completed), 2)
        self.assertEqual(self.follow.status, 'completed')

    def test_late_selection_and_fast_operations_replay_all_evidence_in_order(self):
        self.feed(opening()+SUMMON+ACTIVATE+RESOLVE)
        self.assertEqual([c['key'] for c in self.follow.completed], ['main/s1','main/s2'])
        self.assertEqual(self.confirm.call_count, 2)
        self.feed(opening()+SUMMON+ACTIVATE+RESOLVE)
        self.assertEqual(self.confirm.call_count, 2)

    def test_same_name_other_instance_cannot_activate_in_place_of_summoned_card(self):
        self.feed(opening()+SUMMON)
        # Same card code, but still in hand: never equivalent to the field copy.
        other = (70, struct.pack('<I4B3BIB', 11, 0, 2, 0, 0, 0, 2, 0, 176, 1))
        self.feed(opening()+SUMMON+[other])
        self.assertEqual(self.follow.status, 'blocked'); self.assertEqual(len(self.follow.completed), 1)

    def test_wrong_effect_id_does_not_match_same_card(self):
        wrong = (70, struct.pack('<I4B3BIB', 11, 0, 4, 0, 1, 0, 4, 0, 177, 1))
        self.feed(opening()+SUMMON+[wrong]); self.assertEqual(self.follow.status, 'blocked')
        reason=self.follow.reason;value=sample(opening()+SUMMON+[wrong],len(self.follow.records))
        value['state']['cards'][0]['code']=777
        self.assertFalse(self.follow.ingest(value))
        self.assertEqual((self.follow.status,self.follow.reason),('blocked',reason))

    def test_negation_and_random_results_stop_the_reducer(self):
        for record in (packet(75, b'\x01'), packet(76, b'\x01'), packet(90, b'\0\x01'+struct.pack('<I',99))):
            journal=Journal(HAND,40,1); journal.turn=1
            with self.assertRaises(EvidenceError): journal.apply(record)

    def test_holes_conflicting_duplicates_and_out_of_order_batches_are_rejected_atomically(self):
        self.feed(opening()); before=deepcopy(self.follow.records)
        for alteration in ('hole','conflict','reverse','old'):
            value=sample(opening()+SUMMON,len(before))
            if alteration=='hole': value['records'].pop(1)
            if alteration=='conflict': value['records'][0]['ref']='different-object'
            if alteration=='reverse': value['records'].reverse()
            if alteration=='old': value['processed']-=1
            with self.subTest(alteration=alteration),self.assertRaises(EvidenceError): self.follow.ingest(value)
            self.assertEqual(self.follow.records,before)

    def test_snapshot_ahead_of_processed_animation_never_advances(self):
        value=sample(opening()+SUMMON)
        value['state']['cards'][0]['code']=777
        self.assertFalse(self.follow.ingest(value)); self.confirm.assert_not_called()
        self.assertEqual(self.follow.status,'executing')
        self.feed(opening()+SUMMON);self.assertEqual(len(self.follow.completed),1)

    def test_pause_collects_without_advancing_and_disconnect_requires_explicit_resync(self):
        self.follow.paused=True;self.feed(opening()+SUMMON);self.confirm.assert_not_called()
        self.follow.paused=False;self.follow.stop('disconnected')
        self.feed(opening()+SUMMON);self.confirm.assert_not_called()
        self.follow.requires_sync=False;self.feed(opening()+SUMMON)
        self.assertEqual(len(self.follow.completed),1)

    def test_new_game_process_or_capture_never_reuses_old_progress(self):
        self.feed(opening()+SUMMON)
        for key in ('capture_id','game','duel_token'):
            value=sample(opening()+SUMMON,len(self.follow.records));value[key]='next'
            with self.assertRaises(EvidenceError):self.follow.ingest(value)
        self.assertEqual(len(self.follow.completed),1)

    def test_failed_confirmation_keeps_pending_step_retryable(self):
        self.follow.ingest(sample(opening()+SUMMON))
        self.confirm.side_effect=ValueError('engine not ready')
        with self.assertRaises(ValueError): self.follow.advance(self.confirm,1250)
        self.assertEqual(len(self.follow.completed),0);self.assertEqual(self.follow.token_index,0)
        self.confirm.side_effect=None;self.follow.advance(self.confirm,1251)
        self.assertEqual(len(self.follow.completed),1)

    def test_adapter_does_not_read_opponent_codes_or_choice_lists(self):
        raw=struct.pack('<I4B3BIB',999,1,2,0,0,1,2,0,1,1);reads=[]
        result=read_packet(70,len(raw),lambda at,n:(reads.append((at,n)) or raw[at:at+n]))
        self.assertTrue(result['opponent']);self.assertTrue(all(at>=4 for at,n in reads))
        raw=b'\x01\x05'+bytes(20);reads=[]
        result=read_packet(90,len(raw),lambda at,n:(reads.append((at,n)) or raw[at:at+n]))
        self.assertTrue(result['opponent_draw']);self.assertEqual(reads,[(0,2)])
        self.assertEqual(read_packet(15,999,lambda *_:self.fail('choice identities must not be read')), {})

    def test_formal_contract_retains_node_boundaries_and_rejects_missing_evidence(self):
        events=opening()+SUMMON+ACTIVATE+RESOLVE
        plan={'automatic_revision':'version','review':{'complete':True,'nodes':[
            {'id':'initial','kind':'initial','state_ref':3,'state':complete_state(state_from(opening()))},
            {'id':'s1','kind':'step','state_ref':6,'state':complete_state(state_from(opening()+SUMMON))},
            {'id':'s2','kind':'step','state_ref':12,'state':complete_state(state_from(events))}]},
            'events':[{'native_seq':i,'message':m,'raw':r.hex()} for i,(m,r) in enumerate(events)]}
        compiled=formal_contract(plan)
        self.assertEqual([len(s['tokens']) for s in compiled['steps']],[3,6])
        self.assertFalse(any(s['reason'] for s in compiled['steps']))
        del plan['events'][4]['raw']
        broken=formal_contract(plan)
        self.assertTrue(broken['steps'][0]['reason'])
        self.assertEqual(len(broken['steps']),2)
        self.assertTrue(broken['steps'][1]['reason'])

    def test_temporary_contract_groups_choices_and_uses_every_engine_response(self):
        states=[complete_state(state_from(opening()+events)) for events in (SUMMON,SUMMON+ACTIVATE,SUMMON+ACTIVATE+RESOLVE)]
        steps=[{'path_end':i+1,'decision':{'selection':[{'kind':kind}]},'state':states[i]}
               for i,kind in enumerate(('summon','activate','card'))]
        ctx={'forecast_meta':{'initial':complete_state(state_from(opening())),'inputs':{}},
             'forecast_route':{'id':'r','base':{},'prefix':[],
                               'candidate':{'steps':steps,'path':['a','b','c']}}}
        bridge=Mock(side_effect=[{'batches':[b''.join(bytes([m])+b for m,b in events).hex()]}
                                 for events in (SUMMON,ACTIVATE,RESOLVE)])
        value=temporary_contract(SimpleNamespace(bridge=bridge),'sid',ctx)
        self.assertEqual([s['through'] for s in value['steps']],[0,2])
        self.assertFalse(any(s['reason'] for s in value['steps']))
        self.assertEqual([c.args[2] for c in bridge.call_args_list],[['a'],['a','b'],['a','b','c']])
        ctx['forecast_route']['prefix']=[{}]
        with self.assertRaisesRegex(EvidenceError,'前缀'):temporary_contract(SimpleNamespace(bridge=bridge),'sid',ctx)

    def test_hand_shuffle_preserves_unique_instances_and_stops_on_ambiguous_duplicates(self):
        journal=Journal([11,12,13],40,1);journal.turn=1
        original={c['code']:c['uid'] for c in journal.cards}
        journal.apply(packet(33,b'\0\x03'+struct.pack('<3I',13,11,12)))
        self.assertEqual({c['code']:c['uid'] for c in journal.cards},original)
        self.assertEqual(journal.find({'location':2,'sequence':0,'position':0})['code'],13)
        duplicate=Journal(HAND,40,1)
        with self.assertRaisesRegex(EvidenceError,'同名'):
            duplicate.apply(packet(33,b'\0\x05'+struct.pack('<5I',*HAND)))

    def test_saved_route_subset_matches_shuffle_without_claiming_extra_hand_cards(self):
        expected=Journal([11],40,1);actual=Journal([12,11,13],40,1)
        a=expected.apply(packet(33,b'\0\x01'+struct.pack('<I',11)))
        b=actual.apply(packet(33,b'\0\x03'+struct.pack('<3I',13,12,11)))
        bindings={};self.assertTrue(match_token(a,b,bindings))
        self.assertEqual(len(bindings),1)

    def test_choice_prompt_is_executing_without_confirming_operation(self):
        value=sample(opening());value['prompt']=18
        self.assertTrue(self.follow.ingest(value));self.follow.advance(self.confirm,1250)
        self.assertEqual(self.follow.status,'executing');self.confirm.assert_not_called()

    def test_manual_saved_route_check_preserves_extra_opening_resources(self):
        expected=Journal([11],40,1)
        initial=dict(expected.counts)
        for record in records(SUMMON):expected.apply(record)
        plan={'kind':'formal','hand':[11],'initial_counts':initial}
        inputs={'hand':HAND,'deck':{'main':list(range(40)),'extra':[500]}}
        adjusted=manual_expected(plan,complete_state(expected.state()),inputs)
        actual=state_from(opening()+SUMMON)
        self.assertEqual(signature(adjusted),signature(actual))
        actual['cards'][0]['location']=16
        self.assertNotEqual(signature(adjusted),signature(actual),'A changed spare card is not silently accepted')

    def test_materials_travel_with_extra_deck_host_and_detach_by_instance(self):
        journal=Journal([11,12],40,1);journal.turn=1
        events=[move(11,(0,2,0,0),(0,4,0,1)),move(12,(0,2,0,0),(0,4,1,1)),
                move(11,(0,4,0,1),(0,192,0,0)),move(12,(0,4,1,1),(0,192,0,1)),
                move(500,(0,64,0,0),(0,4,0,1))]
        for record in records(events):journal.apply(record)
        materials=[c for c in journal.cards if c['location']==132]
        self.assertEqual([c['position'] for c in materials],[0,1]);self.assertEqual(journal.counts[132],2)
        journal.apply(packet(*move(11,(0,132,0,0),(0,16,0,1))))
        self.assertEqual(journal.find({'location':132,'sequence':0,'position':0})['code'],12)


class FollowServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.events=opening();self.disconnected=False
        self.context={'id':'ctx','selection_version':1,'selected_temporary':{'id':'planner','route':'route'},
                      'input':{'round_id':'round','recognition_id':'recognition','capture_id':'capture','hand':HAND}}
        self.native={'forecast_meta':{'consumer':'automatic-duel','automatic_context':'ctx','initial':{},'catalog':{},'inputs':{},'rules_version':'rules'},
                     'forecast_steps':[],'forecast_route':{'id':'route','confirmed':0,'prefix':[],
                        'base':{'revision':0},'candidate':{'steps':[{'path_end':1},{'path_end':2}],'path':['a','b']}}}
        modular=SimpleNamespace(sessions={'planner':self.native},planning_lock=threading.Lock(),
            precompute=SimpleNamespace(rules=lambda:'rules'),store=SimpleNamespace(planning={'planner'}),
            bridge=Mock(return_value={'state':{'cards':[]},'raw':'0b00','player':0}),audit=Mock(),public_result=lambda value:value)
        def read(capture,offset):
            if self.disconnected:raise EvidenceError('temporary disconnect')
            return sample(self.events,offset)
        self.store=SimpleNamespace(root=Path(self.directory.name),modular=modular,
            automatic_duel=SimpleNamespace(context=lambda *args,**kw:self.context,
                request=lambda ctx,body,intent:{**body,'consumer':'automatic-duel','automatic_context':'ctx'}),
            ygopro_capture=SimpleNamespace(follow_sample=read),
            ygopro_smart=SimpleNamespace(jobs={'recognition':{'platform':'mdpro3','round_id':'round',
                'frame':{'evidence':{'duel_token':'duel'}}}}))
        self.saved=[];self.service=FollowService(self.store,lambda path,value:self.saved.append((path,deepcopy(value))),lambda:1250)
        proof=contract();proof.update(kind='temporary',planner_id='planner',route='route')
        for i,step in enumerate(proof['steps']):step.update(index=i,through=i)
        with patch('duel_follow.temporary_contract',return_value=proof):
            self.value=self.service.start({'context_id':'ctx','planner_id':'planner','route':'route'})
        self.body={'context_id':'ctx','id':self.value['id']}

    def test_temporary_progress_writes_native_prefix_source_and_private_evidence(self):
        self.events+=SUMMON+ACTIVATE+RESOLVE
        result=self.service.poll(self.body)
        self.assertEqual(result['status'],'completed');self.assertEqual(result['temporary_confirmed'],2)
        self.assertEqual(self.native['forecast_route']['confirmed'],2)
        self.assertEqual(len(self.native['forecast_steps']),2)
        self.assertEqual(self.store.modular.audit.call_args.args[1],'live_confirmed_step')
        self.service.poll(self.body);self.assertEqual(self.store.modular.bridge.call_count,2)
        self.assertTrue(any(p.name.endswith('.evidence.json') for p,_ in self.saved))

    def test_transient_disconnect_restores_reading_but_waits_for_explicit_resync(self):
        self.disconnected=True;value=self.service.poll(self.body)
        self.assertFalse(value['connected']);self.assertTrue(value['requires_sync'])
        self.events+=SUMMON;self.disconnected=False
        self.assertEqual(len(self.service.poll(self.body)['completed']),0)
        value=self.service.poll({**self.body,'action':'resync'})
        self.assertEqual(len(value['completed']),1)

    def test_plan_switch_retires_old_responses_before_native_confirmation(self):
        self.events+=SUMMON;self.context['selection_version']+=1
        value=self.service.poll(self.body)
        self.assertTrue(value['requires_sync']);self.assertEqual(value['completed'],[])
        self.store.modular.bridge.assert_not_called()

    def test_closed_workspace_retires_subscription_even_without_client_stop(self):
        self.service.retire_context('ctx');self.events+=SUMMON
        self.assertNotIn('ctx',self.service.active)
        result=self.service.poll(self.body)
        self.assertEqual(result['completed'],[]);self.assertTrue(result['requires_sync'])
        self.store.modular.bridge.assert_not_called()

    def test_external_temporary_route_change_never_confirms_old_candidate(self):
        self.events+=SUMMON;self.native['forecast_route']['id']='new-route'
        value=self.service.poll(self.body)
        self.assertTrue(value['requires_sync']);self.store.modular.bridge.assert_not_called()

    def test_late_stop_cannot_invalidate_the_replacement_follow(self):
        proof=self.service.jobs[self.body['id']]['follower'].contract
        with patch('duel_follow.temporary_contract',return_value=proof):
            new=self.service.start({'context_id':'ctx','planner_id':'planner','route':'route'})
        self.service.poll({**self.body,'action':'stop'})
        self.assertEqual(self.service.active['ctx'],new['id'])
        self.events+=SUMMON
        self.assertEqual(len(self.service.poll({'context_id':'ctx','id':new['id']})['completed']),1)

    def test_formal_plan_changed_between_selection_and_follow_start_is_rejected(self):
        path=Path(self.directory.name)/'plan.json';path.write_text('{}',encoding='utf-8')
        self.store.plan_path=lambda _:path
        self.context['selected_plan']={'id':'saved','automatic_revision':'selected'}
        self.context['selection_version']+=1
        self.store.automatic_duel.match=Mock(return_value={'matches':[{'id':'saved','automatic_revision':'changed'}]})
        with self.assertRaisesRegex(EvidenceError,'进入教程前'):
            self.service.start({'context_id':'ctx','revision':'selected'})
        self.store.modular.bridge.assert_not_called()


if __name__=='__main__':unittest.main()
