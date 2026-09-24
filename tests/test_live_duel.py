from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trainer'))
from app import atomic_json, read_json
from live_duel import LiveDuel
from live_duel_analysis import Knowledge, analyze
from live_duel_state import active_locks, checked_cards
from opening_workspace import OpeningWorkspace


class LiveTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]/'.local/test-runs'; root.mkdir(exist_ok=True, parents=True)
        self.temp = tempfile.TemporaryDirectory(dir=root); self.folder = Path(self.temp.name)
        self.clock = 100000
        data = json.loads((Path(__file__).resolve().parents[1]/'src/trainer/live-duel-rules.json').read_text('utf-8'))
        catalog = {r['code']: {'name': r['name'], 'desc': r['text'], 'type': r['type'], 'level':r.get('level',0)} for r in data['cards']}
        catalog[1184620] = {'name': '合成普通怪兽', 'desc': '', 'type': 17}
        self.hand = [14558127, 14558127, 97268402, 10045474, 16387555]
        self.deck = {'main': self.hand + [54693926, 23434538, 94145021, 91800273, 61049315, 78058681,73642296] + [1184620]*28,
                     'extra': [42781164, 15665977], 'side': []}
        self.saved = {'id': 'local', 'name': '隔离样例', 'revision': 'r1', 'deck': self.deck}
        self.store = SimpleNamespace(root=self.folder, lock=threading.RLock(), catalog=SimpleNamespace(cards=catalog),
                                     get_deck=lambda _: deepcopy(self.saved), ygopro_capture=SimpleNamespace(attached=None))
        self.store.opening_workspace = OpeningWorkspace(self.store, read_json, atomic_json, lambda: self.clock)
        self.service = LiveDuel(self.store, read_json, atomic_json, lambda: self.clock)
        self.value = self.service.command({'action': 'start', 'input': {'deck_id': 'local', 'revision': 'r1', 'hand': self.hand}})

    def tearDown(self):
        assert self.folder.resolve().is_relative_to(Path(__file__).resolve().parents[1]/'.local/test-runs')
        self.temp.cleanup()

    def body(self, operation, **fields):
        return {'action': 'update', 'id': self.value['session']['id'], 'revision': self.value['session']['revision'],
                'request_id': uuid.uuid4().hex, 'operation': operation, **fields}

    def update(self, operation, **fields):
        self.value = self.service.command(self.body(operation, **fields)); return self.value

    def snapshot(self, **fields):
        s = self.value['session']; state = deepcopy(s['state']); state.pop('window')
        state.update(phase='main1', normal_used=0, known=dict.fromkeys(state['known'], True)); state.update(fields)
        return self.update('snapshot', state=state)

    def card(self, code, controller=1, zone='monster', **fields):
        return {'id': uuid.uuid4().hex, 'code': code, 'controller': controller, 'owner': controller,
                'zone': zone, 'faceup': True, 'disabled': False, 'attack': None, 'attacks_left': None, **fields}

    def held(self, code): return next(c for c in self.value['session']['state']['cards'] if c['controller'] == 0 and c['zone'] == 'hand' and c['code'] == code)

    def chain(self, code=16387555, effect=1):
        cost=self.service.knowledge().rules.get(f'{code}:{effect}',{}).get('cost')
        c = self.card(code,zone='hand' if cost else 'monster',revealed=bool(cost)); self.snapshot(cards=self.value['session']['state']['cards']+[c])
        self.update('action', card_id=c['id'], kind='activate', effect=effect,costs=[{'id':c['id'],'zone':'grave'}] if cost else [])
        event = self.value['session']['events'][-1]['id']
        self.update('window', kind='chain', event_id=event, confirmed=True)
        return c, event

    def test_opening_immutable_costs_remain_spent_on_negation(self):
        self.chain(); ash = self.held(14558127)
        self.update('action', card_id=ash['id'], kind='activate', effect=1, costs=[{'id': ash['id'], 'zone': 'grave'}])
        event = self.value['session']['events'][-1]['id']
        self.update('result', event_id=event, outcome='negated_activation')
        s = self.value['session']
        self.assertEqual(s['frozen'], self.hand)
        self.assertEqual(next(c for c in s['state']['cards'] if c['id']==ash['id'])['zone'], 'grave')
        self.assertIn('次数已使用', next(c for c in self.value['analysis']['choices'] if c['code']==14558127)['reasons'][0])

    def test_idempotency_and_revision_reject_late_or_reused_updates(self):
        body = self.body('gap'); first = self.service.command(body); again = self.service.command(body)
        self.assertEqual(first['session'], again['session'])
        self.assertEqual(len(first['session']['events']), 1)
        with self.assertRaisesRegex(ValueError, '请求标识'): self.service.command({**body, 'operation': 'close'})
        with self.assertRaisesRegex(ValueError, '局面已变化'): self.service.command(self.body('gap'))

    def test_no_recommendation_mutates_resources_or_receipts(self):
        self.chain(); before = self.service.path(self.value['session']['id']).read_bytes()
        for _ in range(3): self.service.command({'action': 'read', 'id': self.value['session']['id']})
        self.assertEqual(before, self.service.path(self.value['session']['id']).read_bytes())
        self.assertEqual(sum(c['zone']=='hand' for c in self.value['session']['state']['cards']), 5)

    def test_hidden_cards_are_redacted_before_matching(self):
        cards = self.value['session']['state']['cards']+[self.card(16387555, zone='hand'), self.card(14442329, zone='spell', faceup=False)]
        self.snapshot(cards=cards)
        self.assertEqual([c['code'] for c in self.value['session']['state']['cards'] if c['controller']==1], [0,0])
        self.assertFalse(self.value['analysis']['routes'])

    def test_exposed_identity_lost_on_facedown_shuffle_correction(self):
        c = self.card(16387555, zone='hand', revealed=True)
        self.snapshot(cards=self.value['session']['state']['cards']+[c]); self.update('action', card_id=c['id'], kind='reveal', effect=0)
        self.assertTrue(self.value['analysis']['routes'])
        cards=deepcopy(self.value['session']['state']['cards']); next(r for r in cards if r['id']==c['id']).update(zone='deck', revealed=False)
        self.snapshot(cards=cards)
        self.assertEqual(next(r for r in self.value['session']['state']['cards'] if r['id']==c['id'])['code'],0)
        self.assertTrue(self.value['analysis']['routes'], 'Previously seen series remains historical evidence, not a current hand identity')

    def test_continuity_gap_disables_current_suggestions_and_preserves_prefix(self):
        self.chain(); self.assertEqual(self.value['analysis']['primary']['kind'],'response')
        prefix=deepcopy(self.value['session']['events']); self.update('gap')
        self.assertEqual(self.value['analysis']['primary']['kind'],'sync')
        self.assertEqual(self.value['session']['events'][:-1],prefix)

    def test_chain_target_must_be_highest_unresolved_activation(self):
        c, first = self.chain()
        self.update('action', card_id=c['id'], kind='activate', effect=2)
        last=self.value['session']['events'][-1]['id']
        with self.assertRaisesRegex(ValueError, '越过'): self.update('window',kind='chain',event_id=first,confirmed=True)
        self.update('window',kind='chain',event_id=last,confirmed=True)
        ash=next(c for c in self.value['analysis']['choices'] if c['code']==14558127)
        self.assertEqual(ash['status'],'unavailable')

    def test_cost_lock_stops_send_to_grave_but_not_discard(self):
        self.chain()
        self.snapshot(limits=[{'key':'91800273:1','turn':1,'player':1}])
        event=next(e for e in self.value['session']['events'] if e.get('kind')=='activate')
        self.update('window',kind='chain',event_id=event['id'],confirmed=True)
        choices=self.value['analysis']['choices']
        self.assertEqual(next(c for c in choices if c['code']==97268402)['status'],'unavailable')
        self.assertEqual(next(c for c in choices if c['code']==14558127)['status'],'available')
        self.snapshot(turn=3,player=1)
        self.assertNotIn('banish_instead',active_locks(self.value['session']['state'],self.service.knowledge().rules))

    def test_imperm_hand_condition_and_protected_tuner(self):
        own=self.card(16387555,0); cards=[c for c in self.value['session']['state']['cards'] if c['code']!=16387555]+[own,self.card(41069676),self.card(15665977)]
        self.snapshot(cards=cards); self.update('window',kind='open',confirmed=True)
        imperm=next(c for c in self.value['analysis']['choices'] if c['code']==10045474)
        self.assertEqual(imperm['status'],'unavailable')
        self.assertNotEqual(next(c for c in self.value['analysis']['choices'] if c['code']==97268402)['target'],cards[-1]['id'])

    def test_expired_window_and_restart_never_resurrect_advice(self):
        self.chain(); self.clock += 15001
        value=self.service.command({'action':'read','id':self.value['session']['id']})
        self.assertIsNone(value['analysis']['window_id']);self.assertNotEqual(value['analysis']['primary']['kind'],'response')
        restarted=LiveDuel(self.store,read_json,atomic_json,lambda:self.clock)
        value=restarted.command({'action':'read','id':self.value['session']['id']})
        self.assertTrue(value['session']['needs_sync']);self.assertIsNone(value['session']['state']['window'])
        with self.assertRaisesRegex(ValueError,'重启'):restarted.command(self.body('window',kind='open',confirmed=True))

    def test_card_text_change_removes_legality_mapping(self):
        self.chain(); self.store.catalog.cards=deepcopy(self.store.catalog.cards)
        self.store.catalog.cards[16387555]['desc']+=' changed'
        value=self.service.command({'action':'read','id':self.value['session']['id']})
        self.assertIsNone(value['analysis']['window_id'])
        self.assertTrue(value['session']['needs_sync'])
        self.assertEqual(value['session']['events'][-1]['source'],'system')
        self.assertNotEqual(next(c for c in value['analysis']['choices'] if c['code']==14558127)['status'],'available')

    def test_threat_answer_changes_ranking_without_duplicate_resources(self):
        cards=self.value['session']['state']['cards']+[self.card(61049315),self.card(41069676)]
        self.snapshot(cards=cards); original=deepcopy(self.value['analysis']['threats'])
        self.snapshot(cards=cards+[self.card(54693926,0,'hand')])
        revised=self.value['analysis']['threats']
        self.assertEqual(len(revised),2);self.assertTrue(all(t['answers'] for t in revised))
        self.assertNotEqual([r['code'] for r in original],[r['code'] for r in revised])

    def test_snapshot_keeps_pending_usage_identity_for_later_resolution(self):
        c=self.held(54693926) if any(r['code']==54693926 for r in self.value['session']['state']['cards']) else self.card(78058681,0,'hand')
        self.snapshot(cards=self.value['session']['state']['cards']+[c])
        self.update('action',card_id=c['id'],kind='activate',effect=1)
        event=self.value['session']['events'][-1]['id'];self.snapshot()
        self.update('result',event_id=event,outcome='negated_activation')
        self.assertEqual(next(u for u in self.value['session']['state']['used'] if u.get('event')==event)['outcome'],'negated_activation')

    def test_unknown_effect_history_survives_correction_without_inventing_rules(self):
        c=self.card(1184620);self.snapshot(cards=self.value['session']['state']['cards']+[c])
        self.update('action',card_id=c['id'],kind='activate',effect=1);event=self.value['session']['events'][-1]['id']
        self.snapshot();self.update('result',event_id=event,outcome='resolved')
        self.assertFalse(self.value['session']['state']['known']['board'])

    def test_named_negation_and_spent_spell_activation_are_respected(self):
        _,event=self.chain()
        self.snapshot(limits=[{'key':'24224830:1','player':1,'turn':1,'affected_code':14558127}])
        self.update('window',kind='chain',event_id=event,confirmed=True)
        self.assertEqual(next(c for c in self.value['analysis']['choices'] if c['code']==14558127)['status'],'unavailable')
        self.snapshot(cards=self.value['session']['state']['cards']+[self.card(61049315)],spell_trap_used=1)
        self.update('window',kind='open',confirmed=True)
        self.assertEqual(next(c for c in self.value['analysis']['choices'] if c['code']==10045474)['status'],'unavailable')

    def test_recorded_plan_is_read_only_and_cannot_restart_spent_resources(self):
        from test_opening_analysis import recorded
        plan=recorded();self.store.plans=self.folder/'plans';self.store.plans.mkdir()
        path=self.store.plans/'synthetic.json';atomic_json(path,plan);before=path.read_bytes()
        self.store.catalog.cards.update({int(c):v for c,v in plan['catalog'].items()})
        current=deepcopy(self.value['session']);current['deck']=plan['deck'];current['state'].update(player=0,normal_used=1)
        current['state']['cards']=[self.card(10,0,'hand')]
        refs=self.service.plan_references(current,self.service.knowledge())
        self.assertEqual(len(refs),1);self.assertFalse(refs[0]['engine_verified_current'])
        self.assertIn('不能从原起点重做',refs[0]['state_fit']);self.assertEqual(path.read_bytes(),before)

    def test_interrupted_cue_can_continue_with_one_hand_tuner_without_reusing_normal(self):
        cards=deepcopy(self.value['session']['state']['cards'])
        cue=next(c for c in cards if c['code']==16387555);cue.update(zone='monster',faceup=True,disabled=True,level=3,tuner=True)
        veiler=next(c for c in cards if c['code']==97268402);veiler.update(level=1,tuner=True)
        self.snapshot(turn=2,player=0,cards=cards,normal_used=1,used=[{'key':'16387555:1','player':0,'turn':2,'outcome':'negated_effect'}])
        route=next(c for c in self.value['analysis']['own']['candidates'] if c.get('synchro'))
        self.assertEqual(route['code'],42781164)
        before=deepcopy(self.value['session']['events'])
        self.update('synchro',target_id=route['synchro']['target_id'],materials=route['synchro']['materials'],confirmed=True)
        state=self.value['session']['state'];self.assertEqual(state['normal_used'],1)
        self.assertEqual([c['code'] for c in state['cards'] if c['zone']=='monster'],[42781164])
        self.assertTrue(all(next(c for c in state['cards'] if c['id']==identifier)['zone']=='grave' for identifier in (cue['id'],veiler['id'])))
        self.assertEqual(self.value['session']['events'][:-1],before)

    def test_synchro_rejects_changed_level_and_retains_hand_material_when_preserved(self):
        cards=deepcopy(self.value['session']['state']['cards'])
        cue=next(c for c in cards if c['code']==16387555);cue.update(zone='monster',faceup=True,level=3,tuner=True)
        veiler=next(c for c in cards if c['code']==97268402);veiler.update(level=2,tuner=True)
        self.snapshot(turn=2,player=0,cards=cards,normal_used=1)
        self.assertFalse(any(c.get('synchro') for c in self.value['analysis']['own']['candidates']))
        veiler['level']=1;self.snapshot(cards=cards);self.update('preference',goal='steady',preserve=[veiler['id']])
        self.assertFalse(any(c.get('synchro') for c in self.value['analysis']['own']['candidates']))

    def test_own_turn_uses_current_resources_and_normal_summon_count(self):
        self.snapshot(turn=2,player=0)
        self.assertTrue(any(c['code']==16387555 for c in self.value['analysis']['own']['candidates']))
        cue=self.held(16387555);self.update('action',card_id=cue['id'],kind='normal',effect=0)
        self.assertEqual(self.value['session']['state']['normal_used'],1)
        self.assertFalse(any(c['label']=='通常召唤提示员作为入口' for c in self.value['analysis']['own']['candidates']))
        prefix=deepcopy(self.value['session']['events']);self.snapshot(normal_used=1)
        self.assertEqual(self.value['session']['events'][:-1],prefix)

    def test_negated_cue_effect_does_not_impose_resolution_restriction(self):
        self.snapshot(turn=2,player=0);cue=self.held(16387555)
        self.update('action',card_id=cue['id'],kind='activate',effect=1)
        event=self.value['session']['events'][-1]['id'];self.update('result',event_id=event,outcome='negated_effect')
        self.assertNotIn('tuner_only',active_locks(self.value['session']['state'],self.service.knowledge().rules))

    def test_resolved_cue_without_resource_still_imposes_restriction(self):
        self.snapshot(turn=2,player=0);cue=self.held(16387555)
        self.update('action',card_id=cue['id'],kind='activate',effect=1)
        event=self.value['session']['events'][-1]['id'];self.update('result',event_id=event,outcome='no_result')
        self.assertIn('tuner_only',active_locks(self.value['session']['state'],self.service.knowledge().rules))

    def test_damage_limit_and_unknown_battle_state(self):
        cards=[c for c in self.value['session']['state']['cards'] if c['code']!=16387555]+[self.card(16387555,0,attack=4000,attacks_left=2,attack_position=True,direct_attack_confirmed=True)]
        self.snapshot(turn=2,player=0,phase='battle',cards=cards)
        self.assertEqual(self.value['analysis']['own']['damage']['amount'],8000)
        self.snapshot(phase='battle',limits=[{'key':'54693926:1','turn':2,'player':0}])
        self.assertEqual(self.value['analysis']['own']['damage']['amount'],0)
        self.snapshot(phase='battle',known={'hand':True,'board':False,'usage':True,'limits':True})
        self.assertIsNone(self.value['analysis']['own']['damage'])

    def test_reference_is_not_engine_validation_and_no_phantom_search_result(self):
        _,event=self.chain();before=len(self.value['session']['state']['cards'])
        self.update('result',event_id=event,outcome='resolved')
        self.assertEqual(len(self.value['session']['state']['cards']),before)
        self.assertFalse(self.value['session']['state']['known']['hand'])
        self.assertEqual(self.value['analysis']['primary']['kind'],'sync')

    def test_reject_direct_conclusion_edit_bad_copies_and_failed_save(self):
        state=deepcopy(self.value['session']['state']);state.pop('window');state['verdict']='win'
        with self.assertRaisesRegex(ValueError,'推导'):self.update('snapshot',state=state)
        cards=self.value['session']['state']['cards']+[self.card(16387555,0,'hand')]
        with self.assertRaisesRegex(ValueError,'超过'):self.snapshot(cards=cards)
        original=self.service.path(self.value['session']['id']).read_bytes(); revision=self.value['session']['revision']
        self.service.write=lambda *args:(_ for _ in ()).throw(OSError('synthetic save failure'))
        with self.assertRaises(OSError):self.update('gap')
        self.assertEqual(self.service.get(self.value['session']['id'])['revision'],revision)
        self.assertEqual(original,self.service.path(self.value['session']['id']).read_bytes())

    def test_closed_session_and_arbitrary_path_rejected(self):
        body=self.body('close');self.value=self.service.command(body)
        self.assertTrue(self.service.command(body)['session']['closed'])
        with self.assertRaisesRegex(ValueError,'已结束'):self.update('gap')
        with self.assertRaises(ValueError):self.service.command({'action':'read','id':'../opening-analysis-v1'})

    def test_snapshot_observation_is_partial_idempotent_and_invalidates_window(self):
        c,event=self.chain();context=self.service.get(self.value['session']['id']);context['capture_id']='isolated'
        self.service.save(context)
        observed={'turn':1,'player':1,'lp':[8000,8000],'cards':deepcopy(context['state']['cards']),
                  'opponent_hand':4,'source':'ygopro_public_snapshot','history_complete':False,'window_verified':False,'note':'isolated memory fixture'}
        def poll():
            body=self.body(None);body['action']='observe';self.value=self.service.command(body);return self.value
        with patch('live_duel.ygopro_live.capture',return_value=observed):
            first=poll();second=poll()
        self.assertEqual(first['session']['revision'],second['session']['revision'])
        self.assertIsNone(first['session']['state']['window']);self.assertTrue(first['session']['needs_sync'])
        self.assertFalse(first['session']['state']['known']['usage']);self.assertEqual(first['session']['state']['phase'],'unknown')
        with patch('live_duel.ygopro_live.capture',side_effect=ValueError('synthetic disconnect')):poll()
        self.assertEqual(self.value['session']['events'][-1]['operation'],'gap')
        self.assertIsNone(self.value['session']['state']['window'])

    def test_disconnected_source_does_not_reactivate_old_window_when_it_recovers(self):
        self.chain()
        with patch.object(self.service,'ensure_source',side_effect=ValueError('lost round')):
            first=self.service.command({'action':'read','id':self.value['session']['id']})
        recovered=self.service.command({'action':'read','id':self.value['session']['id']})
        self.assertTrue(first['session']['needs_sync']);self.assertTrue(recovered['session']['needs_sync'])
        self.assertIsNone(recovered['session']['state']['window'])

    def test_prior_turn_activation_is_not_a_current_response_window(self):
        _,event=self.chain();self.snapshot(turn=2,player=0)
        with self.assertRaisesRegex(ValueError,'先前回合'):self.update('window',kind='chain',event_id=event,confirmed=True)

    def test_own_actions_wait_for_current_chain_resolution(self):
        self.snapshot(turn=2,player=0);cue=self.held(16387555)
        self.update('action',card_id=cue['id'],kind='activate',effect=1)
        self.assertFalse(self.value['analysis']['own']['candidates'])
        self.assertIn('待确认处理',self.value['analysis']['own']['note'])

    def test_known_handtrap_cost_cannot_be_omitted_from_actual_ledger(self):
        self.snapshot();ash=self.held(14558127);revision=self.value['session']['revision']
        with self.assertRaisesRegex(ValueError,'必须'):self.update('action',card_id=ash['id'],kind='activate',effect=1)
        self.assertEqual(self.service.get(self.value['session']['id'])['revision'],revision)

    def test_maxx_draw_scope_and_unconfirmed_modal_scope_are_distinct(self):
        self.chain(23434538)
        self.assertEqual(next(c for c in self.value['analysis']['choices'] if c['code']==14558127)['status'],'available')
        self.chain(17209452,2)
        self.assertEqual(next(c for c in self.value['analysis']['choices'] if c['code']==14558127)['status'],'conditional')

    def test_belle_needs_b2b_target_region_and_dark_ruler_refuses_monster_chain(self):
        self.snapshot(cards=self.value['session']['state']['cards']+[self.card(73642296,0,'hand')])
        self.chain(65961304,3)
        self.assertEqual(next(c for c in self.value['analysis']['choices'] if c['code']==73642296)['status'],'conditional')
        self.chain(54693926,1)
        self.assertTrue(all(c['status']=='unavailable' for c in self.value['analysis']['choices'] if c['code'] in (14558127,73642296,97268402)))


if __name__=='__main__':unittest.main()
