from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import tempfile
import threading
import time
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trainer'))
from module_graph import attach_modules, decision_boundaries
from modular import Modular, original_goal_met, terminal_matches
from modular_decisions import forecast_state, canonical_state
from review import legacy_review
from test_review import fixture
from app import Store, read_json, atomic_json
from card_semantics import effect_clause, card_activation


class ModuleGraphTests(unittest.TestCase):
    def test_transient_windows_sharing_conflict_retries_one_atomic_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'state.json';file.write_text('{"old":true}')
            import os
            replace=os.replace;calls=[]
            def blocked(source,target):
                calls.append((source,target))
                if len(calls)<3:raise PermissionError('temporary sharing conflict')
                replace(source,target)
            with patch('app.os.replace',blocked),patch('app.time.sleep'):
                atomic_json(file,{'new':True})
            self.assertEqual(read_json(file),{'new':True});self.assertEqual(len(calls),3)
            self.assertEqual(len({str(call[0]) for call in calls}),1)
            with patch('app.os.replace',side_effect=PermissionError('persistent denial')),patch('app.time.sleep'):
                with self.assertRaises(PermissionError):atomic_json(file,{'broken':True})
            self.assertEqual(read_json(file),{'new':True})
    def test_lua_reference_numbers_do_not_hide_actual_state_differences(self):
        first={'cards':[{'code':1,'reason_effect':{'effect_id':8,'effect_handle':201,'operation_line':40,'effect_value':2}}]}
        second=deepcopy(first);second['cards'][0]['reason_effect']['effect_handle']=202
        self.assertEqual(canonical_state(first),canonical_state(second))
        second['cards'][0]['reason_effect']['effect_value']=3
        self.assertNotEqual(canonical_state(first),canonical_state(second))
    def test_pendulum_placement_and_the_two_printed_effect_sections_are_distinct(self):
        catalog={'1':{'type':0x1000021,'desc':'←1 【灵摆】 1→\n①：灵摆区域的效果。\n【怪兽效果】\n①：怪兽区域的效果。'}}
        event={'cards':[{'code':1,'location':8}],'engine_effect':{'effect_type':0x10,'range':0x200}}
        self.assertIsNone(effect_clause(event,catalog)['number'])
        self.assertEqual(card_activation(event,catalog),'发动灵摆卡')
        event['engine_effect']['effect_type']=0x40
        self.assertEqual(effect_clause(event,catalog)['text'],'①：灵摆区域的效果。')
        event['cards'][0]['location']=4;event['engine_effect']['range']=4
        self.assertEqual(effect_clause(event,catalog)['text'],'①：怪兽区域的效果。')
    def test_steps_resolve_from_graph_and_keep_annotation_anchors(self):
        report, rows = fixture()
        review = report['review']; graph = review['module_graph']
        self.assertEqual(len([m for m in graph['modules'] if m['kind']=='decision']), 5)
        node = review['nodes'][2]
        expected = deepcopy(node['state'])
        node['state'] = {'cards': [{'code':999999}]}
        projected = legacy_review(report)
        self.assertEqual(projected['nodes'][2]['state'], expected)
        self.assertEqual(projected['nodes'][2]['id'], node['id'])
        self.assertEqual(projected['nodes'][2]['previous'], [review['nodes'][1]['id']])
        self.assertEqual(report['review']['nodes'][2]['state']['cards'][0]['code'],999999)

    def test_legacy_snapshot_is_readable_but_never_an_executable_connection(self):
        report,_ = fixture(); original=report['review']
        original.pop('module_graph')
        for n in original['nodes']: n.pop('module_id',None)
        before=deepcopy(report)
        view=legacy_review(report)
        self.assertEqual(view['revision'],original['revision'])
        self.assertTrue(view['nodes'][1]['state'])
        self.assertTrue(all(m['status']=='legacy' for m in view['module_graph']['modules']))
        self.assertEqual(view['module_graph']['connections'],[])
        self.assertEqual(report,before)

    def test_all_decision_windows_survive_grouping_and_retries_are_not_reusable(self):
        report,rows=fixture()
        nodes=deepcopy(report['review']['nodes']);view={'nodes':nodes}
        raw='0b00000000000000000101'
        rows[2].update(node=20,player=0,prompt=11,raw=raw)
        rows[4].update(node=21,player=0,prompt=11,raw=raw)
        rows[6].update(node=22,player=1,prompt=11,raw=raw)
        rows.insert(3,{'kind':'response','seq':31,'raw':'07000000'})
        rows.insert(4,{'kind':'response','seq':32,'raw':'07000000'})
        graph=attach_modules(view,report,rows)['module_graph']
        edge=next(e for e in graph['connections'] if e['from']=='20')
        self.assertFalse(edge['reusable']);self.assertEqual(edge['response_refs'],[31,32])
        self.assertIsNone(next(m for m in graph['modules'] if m['id']=='22')['raw'])
        self.assertEqual(len(decision_boundaries(rows)),5)

    def test_same_board_without_terminal_anchor_or_draw_gain_is_not_success(self):
        decision={'selection':[{'kind':'activate'}]}
        edge={'terminal_board':[], 'terminal_anchor':{'decision':decision,'delta':[], 'hand_delta':2,'lp_delta':0}}
        before={'cards':[],'lp':[8000,8000]}
        self.assertFalse(terminal_matches(edge,before,[],[]))
        self.assertFalse(terminal_matches(edge,before,[{'decision':decision,'before':before}],[]))
        after={'cards':[{'code':1,'controller':0,'location':2}]*2,'lp':[8000,8000]}
        self.assertTrue(terminal_matches(edge,after,[{'decision':decision,'before':before}],[]))

    def test_unknown_future_draw_cannot_be_deduced_from_remaining_deck(self):
        state={'cards':[{'code':1,'controller':0,'location':2,'instance_id':8},
                        {'code':2,'controller':0,'location':1,'instance_id':9,'sequence':0}]}
        shown=forecast_state(state,{8})
        self.assertTrue(all(c.get('unknown') for c in shown['cards']))
        self.assertTrue(all('code' not in c and 'instance_id' not in c for c in shown['cards']))
        self.assertEqual(state['cards'][0]['code'],1)

    def test_matching_board_must_not_skip_recorded_draw_or_damage(self):
        decision={'selection':[{'kind':'pass'}]}
        before={'cards':[],'lp':[8000,8000]}
        step={'decision':decision,'before':before,'source':{'route':'r','position':0}}
        edge={'terminal_board':[],'source':{'route':'r'},
              'terminal_profiles':[{'position':0,'hand_delta':1,'lp_delta':[0,-1200]}],
              'terminal_anchor':{'decision':decision,'delta':[],'hand_delta':0,'lp_delta':0}}
        after={'cards':[{'code':1,'controller':0,'location':2}],'lp':[8000,8000]}
        self.assertFalse(terminal_matches(edge,after,[step],[]))
        after['lp'][1]=6800
        self.assertTrue(terminal_matches(edge,after,[step],[]))
        after['cards']=[]
        self.assertFalse(terminal_matches(edge,after,[step],[]))

    def test_empty_selected_terminal_is_not_an_unspecified_goal(self):
        ctx={'original_goal':[],'original_goal_kind':'board'}
        self.assertTrue(original_goal_met(ctx,{'cards':[]}))
        self.assertFalse(original_goal_met(ctx,{'cards':[{'code':1,'controller':0,'location':4,'sequence':0,'position':1}]}))

    def test_successor_publication_before_answer_acknowledgement_is_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); bridge=object.__new__(Modular)
            bridge.bridge_lock=threading.Lock();bridge.store=SimpleNamespace(session_path=lambda _:folder)
            bridge.write_bytes=lambda path,data:path.write_bytes(data)
            bridge.state=lambda _: {'version':2}
            (folder/'modular-result.json').write_text('{}')
            reads=[]
            def read(_):
                reads.append(1)
                return {'token':'old'} if len(reads)==1 else {'token':'a'*32,'status':'submitted'}
            bridge.read=read
            self.assertEqual(bridge.bridge('s',{'version':1},['00'],command='answer',lease='a'*32)['status'],'submitted')
            self.assertEqual(len(reads),2)

    def test_concurrent_poll_and_worker_confirm_one_input_once(self):
        agent=object.__new__(Modular);agent.lock=threading.RLock()
        pending={'token':[1,1,'source',0], 'node':1,'lease':'same','step':{'response':'00','source':{},'automatic':False},
                 'remaining_decisions':2,'before':{'cards':[]},'expected':{'cards':[]}}
        ctx={'pending':pending,'completed':[]}
        agent.context=lambda _:ctx
        agent.state=lambda _: {'version':2,'answered':False,'player':0,'state':{'cards':[]}}
        agent.store=SimpleNamespace(session_path=lambda _:Path('unused'))
        agent.audit=lambda *a,**kw:None;agent.save=lambda _:None
        def journal(*a):
            time.sleep(.02)
            return [{'kind':'checkpoint','node':1,'seq':1},{'kind':'response','seq':2,'actor':'modular_ai','raw':'00'}],[]
        with patch('modular.read_journal',journal),ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(agent.reconcile,['s','s']))
        self.assertEqual(len(ctx['completed']),1)

    def test_history_caches_large_plan_names_and_refreshes_after_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=object.__new__(Store);store.sessions=Path(tmp)/'sessions';store.plans=Path(tmp)/'plans'
            (store.sessions/'s').mkdir(parents=True);store.plans.mkdir()
            meta=store.sessions/'s/session.json';plan=store.plans/'s.json'
            meta.write_text(json.dumps({'id':'s','name':'old','status':'completed','started_ms':1}),encoding='utf-8')
            plan.write_text(json.dumps({'name':'saved'}),encoding='utf-8')
            store.refresh=lambda:None;store.history_plan_names={}
            with patch('app.read_json',wraps=read_json) as reader:
                self.assertEqual(store.history()[0]['name'],'saved')
                self.assertEqual(store.history()[0]['name'],'saved')
                self.assertEqual(sum(call.args[0]==plan for call in reader.call_args_list),1)
                plan.write_text(json.dumps({'name':'saved revised'}),encoding='utf-8')
                self.assertEqual(store.history()[0]['name'],'saved revised')


if __name__=='__main__':unittest.main()
