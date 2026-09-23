from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from opening_analysis import concentration, DEFAULTS, analyze_routes, effect_statistics, terminal
from opening_workspace import OpeningWorkspace, reviewed_effects
from intelligence_staples import load_catalog
from app import atomic_json
from test_implicit_conditions import fixture
import test_store


def recorded():
    p = fixture([(1, 2, 4, True), (3, 1, 2, True)])
    p['catalog'] = {str(c): {'name': str(c), 'desc': ''} for c in (10, 20, 30)}
    for event in p['events']: event.update(time_ms=0, actor='self')
    return p


class AnalysisTests(unittest.TestCase):
    def test_parent_shared_and_purpose_exclusion(self):
        cards = {1: {'setcode': 0x1001}, 2: {'setcode': 2}, 3: {'setcode': 1}, 4: {}}
        tags = {'a': {'name': 'parent', 'setcode': 1}, 'b': {'name': 'child', 'setcode': 0x1001},
                'c': {'name': 'other', 'setcode': 2, 'include_cards': [1]},
                'p': {'name': 'purpose', 'kind': 'purpose', 'include_cards': [1, 2, 3, 4]}}
        before = deepcopy(tags)
        result = concentration({'main': [1]*4+[2]*3+[3]*2+[4], 'extra': [1], 'side': [3]*30}, tags, cards, DEFAULTS)
        self.assertEqual(tags, before)
        self.assertEqual(result['total'], 11)
        self.assertEqual(len(result['groups']), 2)
        self.assertEqual(result['status'], '双主系列')
        self.assertAlmostEqual(sum(g['weighted'] for g in result['groups']), 10)
        self.assertEqual(result['unclassified'], 1)

    def test_exact_dual_threshold_and_three_way_uncertainty(self):
        cards = {i: {} for i in range(4)}
        tags = {str(i): {'name': str(i), 'include_cards': [i]} for i in (1, 2, 3)}
        def check(a,b,c=0,n=0): return concentration({'main': [1]*a+[2]*b+[3]*c+[0]*n, 'extra': []}, tags, cards, DEFAULTS)
        self.assertEqual(check(20,16,n=19)['primary'], ['1','2'])
        self.assertEqual(check(20,15,n=20)['primary'], ['1'])
        self.assertEqual(check(2,2,n=51)['primary'], ['1'])
        self.assertEqual(check(10,10,10)['primary'], [])

    def test_deduplicate_copies_and_keep_region_order(self):
        p = recorded(); q = deepcopy(p); q.update(id='copy',name='renamed')
        for e in q['events']: e['time_ms'] += 77
        catalog = {int(c): v for c,v in p['catalog'].items()}
        before = deepcopy(p)
        result = analyze_routes([p,q], p['deck'], [10], catalog, 8)
        self.assertEqual(result['groups'], 1, result)
        self.assertEqual(len(result['routes'][0]['sources']), 2)
        self.assertTrue(result['routes'][0]['one_card'])
        self.assertEqual(p, before)
        q['events'][0]['destination']['location'] = 8
        self.assertEqual(analyze_routes([p,q],p['deck'],[10],catalog,8)['groups'], 2)

    def test_drawn_component_remaining_copies_and_costs(self):
        p = recorded(); cat = {int(c):v for c,v in p['catalog'].items()}
        result = lambda hand,deck=p['deck']: analyze_routes([p],deck,hand,cat,8)['routes'][0]
        self.assertEqual(result([10,30])['condition']['status'], 'unmet')
        self.assertEqual(result([10,30],{**p['deck'],'main':p['deck']['main']+[30]})['condition']['status'], 'satisfied')
        p['requirements']['opening'].append({'code':None,'constraint':'任意手牌','count':1})
        self.assertFalse(result([10,20])['one_card'])
        self.assertEqual(result([10])['condition']['status'], 'unmet')

    def test_branch_premises_stale_text_and_no_events_stay_pending(self):
        p=recorded(); cat={int(c):v for c,v in p['catalog'].items()}
        p['branches']=[{'id':'branch','name':'受阻','source':{'node_id':'s0','seq':10},'report':deepcopy(p),
                        'if_condition':{'kind':'negated','status':'verified'}}]
        result=analyze_routes([p],p['deck'],[10],cat,8)
        self.assertTrue(any(r['condition']['status']=='pending' for r in result['routes']))
        cat[10]={'name':'10','desc':'changed'}
        self.assertTrue(all(not r['verified_sample'] for r in analyze_routes([p],p['deck'],[10],cat,8)['routes']))
        p.pop('events');p['branches']=[]
        self.assertEqual(analyze_routes([p],p['deck'],[10],cat,8)['routes'][0]['condition']['status'],'pending')

    def test_effect_coverage_counts_success_not_materials_or_negations(self):
        def sample(i, applied):
            return {'key':str(i),'verified_sample':True,'participants':{'1':['发动'],'2':['素材']},'effects':[
                {'key':'1:1','code':1,'number':1,'text':'effect','attempts':4,'resolved':3,'negated':1,'applied':applied,'evidence':['e']}]}
        rows=effect_statistics([sample(1,3),sample(2,0)])
        self.assertEqual(rows[0]['coverage_count'],1);self.assertEqual(rows[0]['recommendation'],'候选')
        rows=effect_statistics([sample(1,3),sample(2,0),sample(3,1)])
        self.assertEqual(rows[0]['recommendation'],'主要效果');self.assertEqual(rows[0]['attempts'],12)
        self.assertEqual(len(rows),1)

    def test_recorded_effect_activation_and_result_are_not_material_votes(self):
        p=recorded();p['catalog']['10']['desc']='①：把卡加入手牌。'
        c={'code':10,'controller':0,'location':4,'sequence':0,'instance_id':1,'name':'10'}
        p['events']=[{'id':'2:0','native_seq':2,'time_ms':0,'message':70,'chain':1,'cards':[c]},
                     {'id':'3:0','native_seq':3,'time_ms':0,'message':72,'chain':1,'cards':[]},
                     *p['events'],{'id':'40:0','native_seq':40,'time_ms':0,'message':73,'chain':1,'cards':[]}]
        rows=analyze_routes([p],p['deck'],[10],{int(c):v for c,v in p['catalog'].items()},8)
        self.assertEqual(rows['groups'],1,rows)
        effects=rows['routes'][0]['effects'];self.assertEqual(len(effects),1)
        self.assertEqual(effects[0]['attempts'],1);self.assertEqual(effects[0]['resolved'],1)
        self.assertEqual(effects[0]['code'],10)

    def test_implicit_second_hand_cost_never_becomes_one_card_starter(self):
        p=fixture([(1,2,4,True),(2,2,16,True)],[(1,10,2),(2,20,2)])
        p['catalog']={'10':{'desc':''},'20':{'desc':''}}
        for e in p['events']:e.update(time_ms=0,actor='self')
        rows=analyze_routes([p],p['deck'],[10,20],{10:{'desc':''},20:{'desc':''}},8)
        self.assertEqual(rows['routes'][0]['condition']['status'],'satisfied')
        self.assertFalse(rows['routes'][0]['one_card'])

    def test_terminal_multiple_copies_and_unknown_counts(self):
        report={'final_state':{'cards':[{'code':1,'controller':0,'instance_id':i,'location':4,'disabled':True} for i in (1,2)]},
                'annotations':{'final_marks':{str(i):{'marked':True,'effects':{'0':{'note':'x'}}} for i in (1,2)}}}
        result=terminal(report,{1:{'name':'fixture'}})
        self.assertEqual(len(result),1);self.assertEqual(len(result[0]['copies']),2);self.assertEqual(result[0]['status'],'不可用')


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_store.StoreTests();self.fixture.setUp();self.store=self.fixture.store
        self.service=self.store.opening_workspace
        self.public=load_catalog()
        for c in self.public['cards']: self.store.catalog.cards[c['code']]={**c,'id':c['code'],'extra':False}
        self.deck=self.store.save_deck({'name':'opening test','deck':{'main':[23434538,94145021,91800273,54693926,14558127]+[1184620]*35,'extra':[],'side':[]}})
        self.body={'deck_id':self.deck['id'],'revision':self.deck['revision'],'hand':[23434538,94145021,91800273,54693926,14558127]}

    def tearDown(self): self.fixture.tearDown()

    def request(self, action, **values):
        snapshot=self.service.analyze(self.body);effect=snapshot['knowledge'][0]
        return {'action':action,'input':self.body,'revision':snapshot['revision'],'source_version':snapshot['source_version'],
                'key':effect['key'],'version':effect['version'],**values}

    def test_conflicts_unknown_cards_and_no_double_count(self):
        result=self.service.analyze(self.body)
        self.assertEqual(result['hand_count'],5)
        self.assertEqual(result['handtrap_count'],4)
        self.assertGreaterEqual(len(result['warnings']),5)
        self.assertEqual(result['analysis']['groups'],0)
        self.assertFalse(self.service.path.exists())
        result=self.service.analyze({**self.body,'hand':[1184620]})
        self.assertEqual(result['handtrap_count'],0);self.assertEqual(result['cards'][0]['roles'],[])

    def test_human_candidates_restart_and_restore(self):
        req=self.request('override',value={'roles':[],'priority':'secondary','note':'human <test>'})
        self.service.command(req)
        self.assertTrue((self.store.root/'backups/opening-analysis/0.json').exists())
        self.service.command(self.request('suggest'))
        reopened=OpeningWorkspace(self.store,self.service.read,self.service.write,self.service.now)
        entry=next(e for e in reopened.analyze(self.body)['knowledge'] if e['key']==req['key'])
        self.assertEqual(entry['roles'],[]);self.assertEqual(entry['note'],'human <test>');self.assertTrue(entry['candidate'])
        self.service.command(self.request('apply'))
        self.assertTrue(next(e for e in self.service.analyze(self.body)['knowledge'] if e['key']==req['key'])['roles'])
        self.service.command(self.request('restore'))
        self.assertFalse(self.service.document()['overrides'])

    def test_rule_writes_stale_revision_source_and_effect_rejected(self):
        request=self.request('override',value={'roles':[],'priority':'primary','note':''})
        for field in ('text','cost','verified','local_role','identity'):
            with self.subTest(field=field),self.assertRaises(ValueError): self.service.command({**request,'value':{**request['value'],field:'forged'}})
        with self.assertRaises(ValueError): self.service.command({**request,'source_version':'old'})
        with self.assertRaises(ValueError): self.service.command({**request,'version':'old'})
        with self.assertRaises(ValueError): self.service.command({**request,'key':{}})
        self.service.command(request)
        with self.assertRaises(ValueError): self.service.command(request)

    def test_old_text_preserves_override_but_does_not_apply_it(self):
        req=self.request('override',value={'roles':[],'priority':'primary','note':'keep'})
        self.service.command(req);code=int(req['key'].split(':')[0]);self.store.catalog.cards[code]['desc']+='changed'
        entry=next(e for e in self.service.analyze(self.body)['knowledge'] if e['key']==req['key'])
        self.assertTrue(entry['override_stale']);self.assertEqual(entry['override']['value']['note'],'keep')
        self.assertNotEqual(entry['roles'],[])

    def test_local_notes_do_not_change_analysis_and_corruption_is_not_overwritten(self):
        before=self.service.analyze(self.body)
        req=self.request('note',key='deck',value='这不是规则')
        self.service.command(req)
        self.assertEqual(self.service.analyze(self.body)['analysis'],before['analysis'])
        self.service.path.write_text('{broken','utf-8')
        with self.assertRaisesRegex(ValueError,'缺损'): self.service.command(req)
        self.assertEqual(self.service.path.read_text('utf-8'),'{broken')

    def test_failed_write_preserves_prior_revision(self):
        self.service.command(self.request('note',key='deck',value='old'))
        data=self.service.path.read_bytes()
        original=self.service.write
        def fail(path,value):
            if path==self.service.path: raise OSError('disk full')
            original(path,value)
        with patch.object(self.service,'write',side_effect=fail),self.assertRaises(OSError):
            self.service.command(self.request('note',key='deck',value='new'))
        self.assertEqual(self.service.path.read_bytes(),data)

    def test_supplemental_and_invalid_revision(self):
        result=self.service.analyze({**self.body,'supplemental':[1184620]})
        self.assertEqual(len(result['frozen']),5);self.assertEqual(result['hand_count'],6)
        with self.assertRaises(ValueError):self.service.analyze({**self.body,'supplemental':[23434538]})
        with self.assertRaises(ValueError):self.service.analyze({**self.body,'revision':'old'})

    def test_automatic_uses_server_frozen_hand_and_rejects_stale_round(self):
        frame={'round_id':'round','confirmed':{'order':'second'},'opening':{'status':'ready','snapshot_id':'frozen','cards':self.body['hand']}}
        job={'stage':'second','frame':frame,'construction':{'deck':self.deck['deck']}}
        smart=SimpleNamespace(lock=threading.RLock(),jobs={'recognition':job},current=lambda j:True)
        body={'source':'automatic','recognition_id':'recognition','round_id':'round','snapshot_id':'frozen','hand':[1184620]}
        with patch.object(self.store,'ygopro_smart',smart):
            result=self.service.analyze(body)
            self.assertEqual(result['frozen'],self.body['hand'])
            with self.assertRaises(ValueError):self.service.analyze({**body,'round_id':'old'})
            job['reading_error']='lost'
            with self.assertRaises(ValueError):self.service.analyze(body)


if __name__=='__main__': unittest.main()
