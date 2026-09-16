from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trainer'))
from module_conditions import branch_condition, condition_matches, facts_from_report, validate_if, advance_facts
from modular_decisions import effect_key


class IfConditionsTests(unittest.TestCase):
    def fixture(self,message=76):
        effect={'description':160,'handler_code':10,'handler_instance':1,'owner_code':10,'operation_line':70,'labels':[1]}
        action={'id':'2:0','cards':[{'code':10,'controller':0,'instance_id':1}],'engine_effect':effect}
        base={'actions':[action]}
        report={'events':[{'id':'2:0','message':70,'native_seq':2,**action},
                          {'id':'5:0','message':message,'native_seq':5,'activation_ref':'2:0','cards':action['cards']}]}
        branch={'source':{'seq':3,'action_id':'2:0'},'conditions':{'expected_action':'2:0','hand':[99],
            'if':{'kind':'effect_negated','required':[{'code':20,'location':2,'count':1}]}},'report':report}
        return base,branch,effect

    def test_preset_hand_is_not_an_if_fact(self):
        base,branch,_=self.fixture();branch.pop('report')
        guard=branch_condition(base,branch)
        self.assertEqual(guard['status'],'unverified')
        self.assertFalse(condition_matches(guard,[],{'cards':[]}))

    def test_exact_effect_and_available_extender_are_both_required(self):
        base,branch,effect=self.fixture();guard=branch_condition(base,branch)
        facts=facts_from_report(branch['report']);state={'cards':[{'code':20,'controller':0,'location':2}]}
        self.assertEqual(guard['status'],'verified');self.assertTrue(condition_matches(guard,facts,state))
        self.assertFalse(condition_matches(guard,facts,{'cards':[]}))
        wrong=deepcopy(facts);wrong[0]['effect']['labels']=[2]
        self.assertFalse(condition_matches(guard,wrong,state))
        wrong=deepcopy(facts);wrong[0]['kind']='activation_negated'
        self.assertFalse(condition_matches(guard,wrong,state))

    def test_activation_negation_and_effect_negation_are_distinct(self):
        base,branch,_=self.fixture(75)
        self.assertEqual(branch_condition(base,branch)['status'],'unverified')
        branch['conditions']['if']['kind']='activation_negated'
        self.assertEqual(branch_condition(base,branch)['status'],'verified')

    def test_extender_requirement_uses_confirmed_interruption_resources_after_the_cost_is_spent(self):
        base,branch,_=self.fixture();guard=branch_condition(base,branch)
        facts=facts_from_report(branch['report']);facts[0]['resources']=[[20,2,1]]
        self.assertTrue(condition_matches(guard,facts,{'cards':[]}))
        facts[0]['resources']=[]
        self.assertFalse(condition_matches(guard,facts,{'cards':[{'code':20,'controller':0,'location':2}]}))

    def test_opposing_effect_removal_is_distinct_from_paying_a_cost(self):
        opponent={'id':'1:0','native_seq':1,'message':70,'cards':[{'code':99,'instance_id':9,'controller':1}]}
        move={'id':'4:0','native_seq':4,'message':50,'cards':[{'code':10,'instance_id':1,'controller':0}],
              'origin':{'controller':0,'location':4},'destination':{'controller':0,'location':32},'reason':64,'cause':{'handler_instance':9}}
        self.assertEqual(facts_from_report({'events':[opponent,move]})[0]['kind'],'resource_moved')
        move['reason']=128
        self.assertEqual(facts_from_report({'events':[opponent,move]}),[])
        move['reason']=64;move['cause']={};opponent['cards'][0].pop('instance_id')
        self.assertEqual(facts_from_report({'events':[opponent,move]}),[])

    def test_disposable_chain_observations_match_recorded_guards(self):
        base,branch,effect=self.fixture(75);branch['conditions']['if']={'kind':'activation_negated','required':[]}
        guard=branch_condition(base,branch)
        before={'cards':[{'code':10,'instance_id':1,'controller':0}], 'chains':[{'link':1,'effect':effect}]}
        memory=advance_facts(None,before,{'cards':[],'chains':[]},['4b014a'])
        self.assertTrue(condition_matches(guard,memory['facts'],{'cards':[]}))
        self.assertEqual(memory['chains'],{})

    def test_declarative_resource_counts_validate_and_sum_without_reusing_one_card(self):
        with self.assertRaises(ValueError):validate_if('execute()',{})
        with self.assertRaises(ValueError):validate_if({'kind':'effect_negated','required':[{'code':1,'location':2,'count':0}]},{1:{}})
        guard={'kind':'unconditional','status':'verified','required':[{'code':1,'location':2,'count':1}]*2}
        self.assertFalse(condition_matches(guard,[],{'cards':[{'code':1,'controller':0,'location':2}]}))


class DataHubTests(unittest.TestCase):
    import test_store
    setUp=test_store.StoreTests.setUp
    tearDown=test_store.StoreTests.tearDown

    def test_provider_versions_follow_their_raw_owner_and_new_providers_need_registration(self):
        hub=self.store.modular
        before=hub.dispatch({'consumer':'duel','intent':'data'})
        self.store.save_deck({'name':'source deck','deck':self.deck})
        after=hub.dispatch({'consumer':'duel','intent':'data'})
        a=next(p for p in before['result']['providers'] if p['id']=='decks')
        b=next(p for p in after['result']['providers'] if p['id']=='decks')
        self.assertNotEqual(a['version'],b['version']);self.assertEqual(b['records'],1)
        hub.register_provider('future_fixture','test data owner',lambda:{'version':'v1','records':2})
        self.assertTrue(any(p['id']=='future_fixture' for p in hub.data()['providers']))
        with self.assertRaises(ValueError):hub.dispatch({'consumer':'unregistered','intent':'data'})

    def test_duel_dispatch_uses_the_same_core_and_frozen_duel_inputs(self):
        import uuid
        from app import atomic_json
        sid=str(uuid.uuid4());folder=self.store.session_path(sid);folder.mkdir()
        atomic_json(folder/'session.json',{'id':sid,'deck_sha256':'frozen-deck','engine_sha256':'engine','scripts_sha256':'scripts'})
        calls=[]
        self.store.modular.search=lambda ident:(calls.append(ident) or {'candidates':[],'status':'no_route'})
        result=self.store.modular.dispatch({'consumer':'duel','intent':'search','id':sid})
        self.assertEqual(calls,[sid]);self.assertEqual(result['inputs']['deck'],'frozen-deck')
        self.assertEqual(result['result']['status'],'no_route')
        self.assertEqual(result['consumer'],'duel')


if __name__=='__main__':unittest.main()
