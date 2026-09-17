from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import test_store as fixtures
import test_duel as plans
from app import atomic_json
from duel_planner import context as planner_context


class AutomaticDuelsTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.StoreTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.store=self.fixture.store;self.deck=deepcopy(self.fixture.deck)
        self.hand=[55144522,55144522,1184620]
        self.store.library.builtins={'custom:a':{'id':'custom:a','name':'自动验收','aliases':[],'setcode':None,'include_cards':[],'exclude_cards':[]}}
        self.inputs={'name':'自动本局卡组','deck':self.deck,'tag_selection':{'tag_ids':['custom:a'],'primary_ids':['custom:a']}}
        self.store.ygopro_capture=SimpleNamespace(attached={'pid':123},order=lambda *a,**k:deepcopy(self.raw),submitted_deck=lambda _:deepcopy(self.deck))
        self.raw={'phase':'rps','detected_order':None,'evidence':{'turn':0}}
        monitor=self.store.ygopro_order;state=monitor.start('capture')
        monitor.round['opening'].update(status='ready',cards=list(self.hand),snapshot_id=uuid.uuid4().hex,candidate=None)
        self.raw={'phase':'detected','detected_order':'first','evidence':{'turn':1}}
        state=monitor.poll(state['monitor_id']);monitor.confirm({**state,'order':'first'})
        self.body={**state,'snapshot_id':monitor.round['opening']['snapshot_id'],'deck_context':self.inputs}

    def prepare(self):
        self.store.ygopro_order.confirm_opening(self.body)
        return self.store.automatic_duel.prepare(self.body)

    def test_immutable_private_deck_does_not_enter_or_modify_manual_library(self):
        before=self.store.list_decks();value=self.prepare();identifier=value['deck']['id']
        self.assertTrue(identifier.startswith('automatic/'));self.assertEqual(self.store.list_decks(),before)
        saved=self.store.get_deck(identifier);self.assertEqual(saved['deck'],self.deck)
        for method in (self.store.save_deck,self.store.rename_deck,self.store.delete_deck):
            with self.assertRaisesRegex(ValueError,'只读'):method(saved)
        expected=deepcopy(self.deck);self.inputs['deck']['main'].clear();self.assertEqual(self.store.get_deck(identifier)['deck'],expected)
        self.assertEqual(self.store.automatic_duel.prepare(self.body)['context_id'],value['context_id'])

    def test_actual_submitted_deck_and_hand_must_match_the_captured_source(self):
        self.store.ygopro_capture.submitted_deck=lambda _:{**self.deck,'side':[]}
        with self.assertRaisesRegex(ValueError,'本局使用的卡组'):self.prepare()
        self.assertIsNone(self.store.ygopro_order.round['opening']['confirmed'])
        self.assertFalse(self.store.automatic_duel.root.exists())

    def test_unconfirmed_or_second_player_sources_cannot_prepare_plan_workspace(self):
        with self.assertRaisesRegex(ValueError,'尚未确认'):self.store.automatic_duel.prepare(self.body)
        self.store.ygopro_order.round['confirmed']['order']='second'
        with self.assertRaisesRegex(ValueError,'先攻'):self.store.automatic_duel.prepare(self.body)

    def test_matching_selection_refresh_and_original_plan_preservation(self):
        value=self.prepare();plan=plans.plan()
        plan['requirements']={'main':[plans.rows(55144522,2)],'extra':[],'opening':[plans.rows(55144522,2)],'warnings':[]}
        path=self.store.plan_path(plan['id']);atomic_json(path,plan);original=path.read_bytes()
        result=self.store.automatic_duel.match({'context_id':value['context_id'],'hand':[999]})
        self.assertEqual([p['id'] for p in result['matches']],[plan['id']])
        row=result['matches'][0];body={'context_id':value['context_id'],'plan_id':row['id'],'revision':row['automatic_revision']}
        selected=self.store.automatic_duel.select(body);self.assertEqual(selected['id'],row['id']);self.assertEqual(path.read_bytes(),original)
        plan['name']='已修改';atomic_json(path,plan)
        with self.assertRaisesRegex(ValueError,'已变化'):self.store.automatic_duel.select(body)
        self.assertEqual(self.store.automatic_duel.context(value['context_id'])['selected_plan']['name'],row['name'])

    def test_planner_requests_are_bound_to_automatic_context_and_canonical_inputs(self):
        value=self.prepare();calls=[]
        def dispatch(request):calls.append(request);return {'result':{'id':'owned-engine','inputs':{}}}
        self.store.modular.dispatch=dispatch
        self.store.automatic_duel.dispatch({'context_id':value['context_id'],'intent':'plan','deck_id':'library/forged.ydk','hand':[999]})
        self.assertEqual(calls[0]['consumer'],'automatic-duel');self.assertEqual(calls[0]['deck_id'],value['deck']['id'])
        self.assertEqual(calls[0]['hand'],self.hand)
        with self.assertRaisesRegex(ValueError,'不属于'):
            self.store.automatic_duel.dispatch({'context_id':value['context_id'],'intent':'plan-confirm','id':'manual-engine'})
        self.assertEqual(len(calls),1)
        context={'forecast_meta':{'consumer':'automatic-duel','automatic_context':value['context_id']}}
        modular=SimpleNamespace(sessions={'owned-engine':context},store=SimpleNamespace(planning={'owned-engine'}))
        with self.assertRaisesRegex(ValueError,'其他流程'):planner_context(modular,{'id':'owned-engine','consumer':'duel'})
        with self.assertRaisesRegex(ValueError,'其他流程'):planner_context(modular,{'id':'owned-engine','consumer':'automatic-duel','automatic_context':'another'})
        self.assertEqual(planner_context(modular,{'id':'owned-engine','consumer':'automatic-duel','automatic_context':value['context_id']})[0],'owned-engine')

    def test_closed_workspace_is_readable_but_cannot_match_or_start_new_work(self):
        value=self.prepare();self.store.automatic_duel.close({'context_id':value['context_id']})
        self.assertEqual(self.store.get_deck(value['deck']['id'])['deck'],self.deck)
        with self.assertRaisesRegex(ValueError,'已结束'):self.store.automatic_duel.match({'context_id':value['context_id']})

    def test_reloaded_private_snapshot_rejects_changed_content(self):
        value=self.prepare();service=self.store.automatic_duel;identifier=value['context_id']
        service.contexts.clear();self.assertEqual(service.deck(identifier)['deck'],self.deck)
        record=deepcopy(service.context(identifier));record['input']['hand'][0]=1184620;service.save(record);service.contexts.clear()
        with self.assertRaisesRegex(ValueError,'快照内容已变化'):service.deck(identifier)

    def test_opening_confirmation_write_failure_restores_previous_snapshot(self):
        monitor=self.store.ygopro_order;before=deepcopy(monitor.round)
        with patch.object(monitor,'persist',side_effect=OSError('test-only disk error')):
            with self.assertRaises(OSError):monitor.confirm_opening(self.body)
        self.assertEqual(monitor.round['opening']['confirmed'],before['opening']['confirmed'])
        self.assertNotIn('plan_input',monitor.round)

    def test_late_generation_after_context_close_releases_only_its_own_session(self):
        value=self.prepare();service=self.store.automatic_duel;calls=[]
        def dispatch(request):
            calls.append(request)
            if request['intent']=='plan':
                service.close({'context_id':value['context_id']})
                return {'result':{'id':'late-owned-engine','inputs':{}}}
            return {'result':{'closed':True,'inputs':{}}}
        self.store.modular.dispatch=dispatch
        with self.assertRaisesRegex(ValueError,'迟到的推演已关闭'):
            service.dispatch({'context_id':value['context_id'],'intent':'plan'})
        self.assertEqual([c['intent'] for c in calls],['plan','plan-close'])
        self.assertEqual(calls[-1]['id'],'late-owned-engine')
        self.assertEqual(calls[-1]['automatic_context'],value['context_id'])

    def test_late_queued_preparation_is_cancelled_even_without_an_engine_id(self):
        value=self.prepare();service=self.store.automatic_duel
        def dispatch(request):
            service.close({'context_id':value['context_id']})
            return {'result':{'id':None,'job':'late-job','inputs':{}}}
        self.store.modular.dispatch=dispatch
        with patch.object(self.store.modular.precompute,'close_owner') as close:
            with self.assertRaisesRegex(ValueError,'迟到'):
                service.dispatch({'context_id':value['context_id'],'intent':'plan-prepare','session':'round'})
            self.assertEqual(close.call_count,2)
            close.assert_called_with('automatic-duel',value['context_id'])


if __name__=='__main__':unittest.main()
