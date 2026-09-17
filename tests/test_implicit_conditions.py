"""Resource flow, alternative copies and incomplete evidence, without UI guesses."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trainer'))
from implicit_conditions import extract, check, attach
from duel import project


def fixture(operations, initial=None):
    initial = initial or [(1, 10, 2), (2, 20, 1), (3, 30, 1)]
    cards = {i: dict(instance_id=i, code=c, controller=0, location=z, sequence=i, name=str(c)) for i,c,z in initial}
    start = deepcopy(list(cards.values()))
    nodes = [{'id':'initial','kind':'initial','state_ref':1,'state':{'cards':start}}]
    modules, connections, events, actions = [], [], [], []
    for index,(instance,origin,destination,selected) in enumerate(operations):
        seq = 10+index*10; ident = str(seq); following = str(seq+10)
        card = deepcopy(cards[instance]); card['location'] = origin
        modules.append({'id':ident,'seq':seq,'player':0,'state':{'cards':deepcopy(list(cards.values()))}})
        connections.append({'from':ident,'to':following,'response_refs':[seq+1],
            'decision':{'selection':[{'kind':'card','card':{k:card[k] for k in ('code','controller','location')}}] if selected else []},
            'bindings':[{'card':card}] if selected else []})
        dest = {**card,'location':destination,'position':10 if destination==8 else 1}; eid = f'{seq+2}:0'
        events.append({'id':eid,'native_seq':seq+2,'byte_offset':0,'message':50,'cards':[card], 'origin':card,'destination':dest,'reason':0x40})
        actions.append({'id':eid,'evidence_refs':[eid],'summary':'recorded movement','cards':[card]})
        cards[instance] = dest
        nodes.append({'id':f's{index}','kind':'step','number':index+1,'range':[seq,seq+9],'state':{'cards':deepcopy(list(cards.values()))}})
    modules.append({'id':following,'seq':seq+10,'player':0,'state':{'cards':deepcopy(list(cards.values()))}})
    nodes.append({'id':'final','kind':'final','state':{'cards':deepcopy(list(cards.values()))}})
    deck = {'main':[c for i,c,z in initial if z != 64],'extra':[c for i,c,z in initial if z == 64],'side':[]}
    return {'id':'p','name':'route','deck':deck,'initial_hand':[c for c in start if c['location']==2],
        'events':events,'actions':actions,'review':{'complete':True,'revision':'fixture','nodes':nodes,
            'module_graph':{'modules':modules,'connections':connections}},
        'requirements':{'opening':[{'code':10,'count':1}],'main':[],'extra':[]}, 'branches':[]}


class ImplicitTests(unittest.TestCase):
    def test_deck_mill_search_and_grave_reuse_follow_each_step(self):
        p=fixture([(1,2,4,True),(2,1,16,True),(3,1,2,True),(2,16,8,True)])
        value=extract(p);self.assertFalse(value['warnings'])
        self.assertEqual([(c['code'],c['source_zone'],c['purpose']) for c in value['conditions']],[(20,1,'定向送墓'),(30,1,'检索'),(20,16,'盖放')])
        self.assertEqual(value['conditions'][-1]['supplied_by']['step'],2)
        self.assertEqual(check(p,p['deck'],[10])['status'],'satisfied')
        self.assertEqual(check(p,p['deck'],[10,30])['status'],'unmet')
        self.assertIn('剩余0张',check(p,p['deck'],[10,30])['reason'])
        deck=deepcopy(p['deck']);deck['main'] += [30,99]
        self.assertEqual(check(p,deck,[10,30,99])['status'],'satisfied')

    def test_return_and_reselect_same_instance_is_not_a_second_copy(self):
        p=fixture([(2,1,16,True),(2,16,1,True),(2,1,2,True)])
        self.assertEqual(check(p,p['deck'],[10])['status'],'satisfied')
        p['events'][-1]['cards'][0]['instance_id']=99
        self.assertEqual(check(p,p['deck'],[10])['status'],'unmet')

    def test_one_selection_needing_two_copies_reports_the_real_quantity(self):
        p=fixture([(2,1,16,True),(3,1,16,True)],[(1,10,2),(2,20,1),(3,20,1)])
        graph=p['review']['module_graph'];first,second=graph['connections']
        first['decision']['selection']+=second['decision']['selection'];first['bindings']+=second['bindings']
        graph['connections']=[first];graph['modules'][1]['state']=deepcopy(graph['modules'][-1]['state'])
        p['events'][1].update(id='12:1',native_seq=12,byte_offset=1)
        p['review']['nodes'][1]['state']=deepcopy(graph['modules'][-1]['state'])
        value=extract(p);self.assertEqual(value['conditions'][0]['count'],2)
        self.assertEqual(check(p,p['deck'],[10])['status'],'satisfied')
        self.assertEqual(check(p,p['deck'],[10,20])['status'],'unmet')

    def test_random_mill_then_revival_does_not_make_recorded_identity_deterministic(self):
        p=fixture([(2,1,16,False),(2,16,4,True)])
        value=extract(p)
        self.assertFalse(value['conditions']);self.assertIn('2',value['random_instances'])
        self.assertEqual(check(p,p['deck'],[10])['status'],'pending')
        p['events'].insert(0,{'id':'3:0','native_seq':3,'message':90,'actor':'self','cards':[{'instance_id':2,'code':20}]})
        self.assertEqual(check(p,p['deck'],[10])['status'],'random')

    def test_generic_cost_does_not_consume_reserved_exact_opening(self):
        p=fixture([(2,2,16,True),(1,2,4,True)],[(1,10,2),(2,20,2)])
        p['requirements']['opening'].append({'code':None,'count':1,'constraint':'任意手牌','instances':['2']})
        self.assertEqual(check(p,{'main':[10,99],'extra':[]},[10,99])['status'],'satisfied')

    def test_legacy_missing_evidence_is_pending_and_upgrades_never_write(self):
        p=fixture([(2,1,16,True)]);before=deepcopy(p)
        value=attach(p);self.assertEqual(p,before);self.assertTrue(value['requirements']['implicit']['conditions'])
        p['review'].pop('module_graph');self.assertEqual(check(p,p['deck'],[10])['status'],'pending')

    def test_branch_alternative_is_separate_from_unavailable_main(self):
        p=fixture([(3,1,2,True)]);branch=fixture([(2,1,16,True)])
        p['branches']=[{'id':'b','name':'recorded alternative','valid':True,'if_condition':{'kind':'unconditional','status':'verified'},'source':{'node_id':'s0','seq':10},'report':branch}]
        matched,_,_=project(p,p['deck'],[10,30])
        self.assertEqual(matched['duel_source_route'],'b')
        self.assertIn('剩余0张',matched['duel_original_reason'])
        self.assertNotIn(30,[c['code'] for c in attach(matched)['requirements']['implicit']['conditions']])
        p['branches'][0]['if_condition']['kind']='activation_negated'
        self.assertIsNone(project(p,p['deck'],[10,30])[0],'Unconfirmed interference cannot be promoted to an opening alternative')

    def test_manual_banned_cards_stay_independent(self):
        p=fixture([(2,1,16,True)]);p['expansion']={'conditions':{'banned':[30]}}
        self.assertEqual(project(p,p['deck'],[10,30])[1],'opening')


if __name__=='__main__': unittest.main()
