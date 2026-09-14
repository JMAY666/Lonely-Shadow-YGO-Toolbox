from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from compromise import branch_points, premises, resource_scope
from review import confirmation_key, empty_annotations
from app import atomic_json
from actions import project_actions
import test_store


def fixture():
    own = dict(code=55144522, name='我方抽牌效果', instance_id=41, controller=0, location=8, sequence=0)
    opponent = dict(code=1184620, name='对方测试卡', instance_id=42, controller=1, location=2, sequence=0)
    states = dict(turn=1, phase=4, lp=[8000, 8000], chain_depth=1, cards=[own, opponent])
    rows = [dict(seq=1, kind='begin', time_ms=1),
            dict(seq=2, kind='checkpoint', time_ms=2, node=1, player=0, prompt=11, restorable=True, state={**states, 'chain_depth': 0}),
            dict(seq=3, kind='batch', time_ms=3, state=states),
            dict(seq=4, kind='checkpoint', time_ms=4, node=2, player=1, prompt=16, restorable=True, state=states),
            dict(seq=5, kind='batch', time_ms=5, state={**states, 'chain_depth': 0}),
            dict(seq=6, kind='checkpoint', time_ms=6, node=3, player=0, prompt=11, restorable=True, state={**states, 'chain_depth': 0})]
    action = dict(id='3:0', kind='effect', cards=[own], activation_ref='3:0', chain_group=1, chain_link=1,
                  summary='发动我方抽牌效果', evidence_refs=['3:0', '5:0'], status='resolved')
    report = dict(id=str(uuid.uuid4()), name='分支隔离测试', plan_stage='draft', status='completed',
                  expansion=dict(name='分支隔离测试', notes=''), actions=[action], events=[],
                  initial_hand=[], final_state={**states, 'chain_depth': 0}, catalog={},
                  review={'revision': 'original-route', 'action_nodes': {'3:0': 'step:3:0'},
                          'nodes': [dict(id='initial', kind='initial', action_ids=[], state=states),
                                    dict(id='step:3:0', kind='step', action_ids=['3:0'], state=states),
                                    dict(id='final', kind='final', action_ids=[], state=states)]})
    return report, [{**row, 'session': report['id']} for row in rows]


class BranchProjectionTests(unittest.TestCase):
    def test_manual_choices_stay_in_evidence_and_confirmed_negation_is_the_opposing_effect_result(self):
        own={'code':55144522,'name':'我方效果','instance_id':1,'controller':0,'location':8}
        opposing={'code':14558127,'name':'灰流丽','instance_id':2,'controller':1,'location':2}
        def e(seq,msg,**kw): return {'id':f'{seq}:0','native_seq':seq,'time_ms':seq,'message':msg,'type':str(msg),'cards':[],**kw}
        events=[e(1,70,cards=[own],chain=1),e(2,71,chain=1),e(3,'对手手动选择'),e(4,1),
                e(5,70,cards=[opposing],chain=2),e(6,71,chain=2),e(7,72,chain=2),
                e(8,76,cards=[own],chain=1,resolution_source_ref='5:0'),e(9,73,chain=2),e(10,73,chain=1),e(11,74)]
        before=deepcopy(events)
        actions=project_actions({'events':events,'catalog':{}})
        self.assertEqual(len(actions),2)
        self.assertEqual(actions[0]['status'],'disabled')
        self.assertEqual(actions[1]['results'][0]['message'],76)
        self.assertEqual(actions[1]['results'][0]['cards'],[own])
        self.assertEqual(events,before)
        events[7].pop('resolution_source_ref')
        self.assertEqual(project_actions({'events':events,'catalog':{}})[1]['results'],[])

    def test_actual_response_and_settled_nodes_have_explicit_distinct_times(self):
        report, rows = fixture()
        points = branch_points(report, rows)
        self.assertEqual([p['timing'] for p in points], ['首次操作前', '发动后的响应窗口', '结算后'])
        self.assertEqual(points[1]['node_id'], 'step:3:0')
        self.assertEqual(points[1]['checkpoint'], 2)
        self.assertEqual(branch_points({**report, 'compromise': {'root_id': report['id']}}, rows), [])
        self.assertEqual(branch_points({**report, 'imported': True}, rows), [])
        for row in rows: row.pop('restorable', None)
        self.assertEqual(branch_points(report, rows), [], 'A snapshot without replay data is not a playable checkpoint')

    def test_negation_requires_explicit_resolution_source_and_affected_activation(self):
        report, _ = fixture(); own = report['actions'][0]
        opposing = {**deepcopy(own), 'id': '7:0', 'activation_ref': '7:0', 'chain_link': 2,
                    'cards': [dict(code=14558127, controller=1, name='灰流丽')], 'evidence_refs': ['7:0']}
        report['actions'].append(opposing)
        event = dict(id='9:0', native_seq=9, message=76, activation_ref=own['activation_ref'], resolution_source_ref='7:0')
        report['events'] = [event]
        result = premises(report, 4, [])
        self.assertTrue(result[0]['confirmed']); self.assertEqual(result[0]['result'], '效果被无效')
        self.assertEqual(result[0]['affected_cards'], own['cards'])
        report['events'][0].pop('resolution_source_ref')
        uncertain = premises(report, 4, [])
        self.assertFalse(uncertain[0]['confirmed']); self.assertEqual(uncertain[0]['affected_cards'], [])
        linked = premises(report, 4, [], {'7:0': {'action_id': own['id'], 'note': '仅为用户关联'}})
        self.assertFalse(linked[0]['confirmed']); self.assertEqual(linked[0]['basis'], '用户补充关联')
        self.assertEqual(linked[0]['note'], '仅为用户关联')
        report['actions'].pop(); self.assertEqual(premises(report, 4, []), [], 'Preset cards alone are not interference events')

    def test_resource_scope_maxima_exclude_other_alternatives_and_opponent(self):
        summary=lambda rows: dict(main=rows, extra=[], opening=[], random=[], final={'cards': []})
        a=dict(code=10, name='共用卡', count=1, constraint='')
        extra=dict(code=11, name='后续补点', count=1, constraint='')
        main={'requirements': summary([a])}
        chosen={'id':'branch-a','name':'第一分支','conditions':{'hand':[14558127]},'report':{'requirements':summary([{**a,'count':2},extra])}}
        before=deepcopy((main,chosen)); scope=resource_scope(main, chosen)
        self.assertEqual(scope['additional']['main'], [a,extra])
        self.assertEqual(sum(c['count'] for c in scope['combined']['main']),3)
        self.assertNotIn(14558127,[c['code'] for c in scope['combined']['main']])
        self.assertEqual(scope['opponent_conditions'],[14558127]); self.assertEqual((main,chosen),before)
        self.assertEqual(resource_scope(main)['combined'],main['requirements'])

    def test_save_confirmation_covers_branch_conditions_and_results(self):
        report, _ = fixture(); first=confirmation_key(report,'方案','',empty_annotations())
        changed={**report,'branches':[{'id':'b','conditions':{'hand':[14558127]}}]}
        self.assertNotEqual(first,confirmation_key(changed,'方案','',empty_annotations()))


class BranchStoreTests(unittest.TestCase):
    setUp=test_store.StoreTests.setUp
    tearDown=test_store.StoreTests.tearDown

    def prepare(self):
        report, rows=fixture(); folder=self.store.session_path(report['id']); folder.mkdir()
        atomic_json(folder/'session.json', report)
        (folder/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
        (folder/'restore-2.txt').write_text('immutable replay',encoding='utf-8')
        (folder/'core-calls.txt').write_text('immutable calls',encoding='utf-8')
        # Projection fixture deliberately supplies a frozen report. Engine reconstruction
        # is exercised separately by the real Avarice/Ash desktop acceptance.
        self.store._report=lambda identifier: deepcopy(report)
        return report,folder

    def test_multiple_branches_are_drafts_isolated_from_mainline_and_each_other(self):
        main,folder=self.prepare();before=(folder/'native.jsonl').read_bytes()
        first=self.store.compromise.create({'id':main['id'],'revision':0,'checkpoint':2,'node_id':'step:3:0'})
        first_id=first['branches'][0]['id']
        second=self.store.compromise.create({'id':main['id'],'revision':1,'checkpoint':2,'node_id':'step:3:0'})
        self.assertEqual(len(second['branches']),2)
        self.assertNotEqual(first_id,second['branches'][1]['id'])
        update=self.store.compromise.update({'id':main['id'],'branch_id':first_id,'revision':2,'conditions':{'hand':[55144522,55144522],'expected_action':'3:0','note':'预设'}})
        self.assertEqual(update['branches'][0]['conditions']['hand'],[55144522,55144522])
        self.assertEqual(update['branches'][1]['conditions']['hand'],[1184620])
        self.assertEqual(update['branches'][0]['premises'],[])
        self.assertEqual(update['actions'],main['actions']); self.assertEqual(update['final_state'],main['final_state'])
        self.assertEqual((folder/'native.jsonl').read_bytes(),before)
        self.assertFalse(self.store.plan_path(main['id']).exists())
        with self.assertRaisesRegex(ValueError,'其他页面'): self.store.compromise.update({'id':main['id'],'branch_id':first_id,'revision':2,'delete':True})
        deleted=self.store.compromise.update({'id':main['id'],'branch_id':first_id,'revision':3,'delete':True})
        self.assertEqual(len(deleted['branches']),1);self.assertEqual(deleted['actions'],main['actions'])
        self.assertTrue((folder/'core-calls.txt').exists())

    def test_changed_mainline_is_marked_invalid_and_never_rebound(self):
        main,folder=self.prepare()
        created=self.store.compromise.create({'id':main['id'],'revision':0,'checkpoint':2,'node_id':'step:3:0'})
        changed=deepcopy(main);changed['review']['revision']='different-route'
        result=self.store.compromise.edit(changed)
        self.assertFalse(result['branches'][0]['valid'])
        self.assertEqual(result['branches'][0]['source'],created['branches'][0]['source'])

    def test_missing_replay_and_nested_branch_fail_explicitly(self):
        main,folder=self.prepare();(folder/'restore-2.txt').unlink()
        with self.assertRaisesRegex(ValueError,'缺少完整'): self.store.compromise.create({'id':main['id'],'revision':0,'checkpoint':2,'node_id':'step:3:0'})
        main['compromise']={'root_id':main['id']}
        with self.assertRaisesRegex(ValueError,'子分支'): self.store.compromise.create({'id':main['id'],'revision':0,'checkpoint':2,'node_id':'step:3:0'})

    def test_saved_branch_review_uses_frozen_data_without_its_session_directory(self):
        main,folder=self.prepare()
        frozen=deepcopy(main)
        main['branches']=[{'id':str(uuid.uuid4()),'name':'已保存分支','session_id':str(uuid.uuid4()),
            'source':{'seq':4,'main_revision':main['review']['revision']},'conditions':{'hand':[]},'premises':[],
            'report':frozen,'associations':{}}]
        def forbid_session(identifier):
            if identifier!=main['id']: raise AssertionError('Saved branch must not reread its source session')
            return deepcopy(main)
        self.store._report=forbid_session
        opened=self.store.compromise.edit(main)
        self.assertEqual(opened['branches'][0]['report']['actions'],frozen['actions'])
        self.assertEqual(opened['branches'][0]['report']['final_state'],frozen['final_state'])
        self.assertTrue(opened['branches'][0]['valid'])
        sid=main['branches'][0]['session_id']
        updated=self.store.compromise.update({'id':main['id'],'branch_id':main['branches'][0]['id'],'revision':0,
            'conditions':{'hand':[],'expected_action':'3:0','note':'只补充场景说明'}})
        self.assertEqual(updated['branches'][0]['session_id'],sid)
        self.assertEqual(updated['branches'][0]['report']['actions'],frozen['actions'])


if __name__=='__main__': unittest.main()
