"""Native/manual ownership and review snapshots, separate from engine cases."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
import test_second_hints as fixtures
from second_native import native_window, own_main, supported_window, carry_annotations, public_outcomes, review
from second_rules import ALUBER, MOYE, ASH


class NativeBoundaryTests(unittest.TestCase):
    def test_opponent_response_and_own_main_are_distinct_supported_stages(self):
        node={'player':0,'raw':'1000','state':{'turn':1,'turn_player':1,'phase':4,'chain_depth':1}}
        self.assertTrue(supported_window(node));self.assertFalse(own_main(node))
        node['state'].update(turn=2,turn_player=0,chain_depth=0);node['raw']='0b00'
        self.assertTrue(own_main(node))
        node['state']['phase']=8;self.assertFalse(supported_window(node))
        node['state'].update(turn=1,turn_player=1);node['player']=1;self.assertFalse(supported_window(node))

    def test_exact_effect_identity_and_native_menu_are_not_card_name_guesses(self):
        current={'cards':[{'id':'aluber','native_instance':1,'code':ALUBER,'controller':1,'location':4},
                          {'id':'ash','native_instance':2,'code':ASH,'controller':0,'location':2}],'turn':1}
        effect={'handler_code':ALUBER,'handler_instance':1,'description':ALUBER*16,'effect_type':137}
        node={'player':0,'raw':'1000','state':{'turn':1,'turn_player':1,'chains':[{'link':1,'effect':effect}]}}
        choices=[{'semantic':{'kind':'activate'},'card':{'code':ASH,'instance_id':2,'controller':0,'location':2},
                  'effect':{'handler_code':ASH,'operation_line':35,'count_remaining':1}}]
        with patch('second_native.model',return_value={'choices':choices}):
            result=native_window(node,current)
            self.assertEqual(result['effect_id'],'aluber.search');self.assertEqual(result['responders'][0]['card_id'],'ash')
            self.assertEqual(current['effect_counts']['0:ash.1']['status'],'unused')
            self.assertEqual(current['effect_counts']['0:ash.1']['source'],'native_legal_menu')
            effect['description']+=1
            self.assertFalse(native_window(node,current)['recognized'])
            effect['description']-=1;effect['effect_type']=999
            self.assertFalse(native_window(node,current)['recognized'])

    def test_notes_carry_without_becoming_engine_counters_or_spending_again(self):
        previous={'resource_roles':{'held':{'role':'free'},'spent':{'role':'key'}},'usage':[{'label':'old note','status':'unknown'}],
                  'restrictions':[],'effect_counts':{'guess':{'status':'unused'}}}
        current={'cards':[{'id':'held','controller':0,'location':2},{'id':'spent','controller':0,'location':16}]}
        carry_annotations(current,previous)
        self.assertEqual(set(current['resource_roles']),{'held'});self.assertNotIn('effect_counts',current)
        self.assertEqual(current['usage'],previous['usage']);current['usage'][0]['label']='edited'
        self.assertEqual(previous['usage'][0]['label'],'old note')

    def test_native_outcomes_distinguish_negation_and_public_target_places(self):
        rows=[{'seq':5,'kind':'batch','raw':'4b014c02530100040100'},{'seq':6,'kind':'batch','raw':'4b03'}]
        result=public_outcomes(rows,5)
        self.assertEqual([r['kind'] for r in result],['activation_negated','effect_negated','targets'])
        self.assertEqual(result[2]['places'],[{'controller':0,'location':4,'sequence':1}])
        self.assertTrue(all('raw' not in r for r in result))

    def test_review_keeps_original_unknown_information_and_separates_actual_from_prediction(self):
        known={'cards':[{'code':ASH,'controller':0,'location':2},{'code':None,'controller':1,'location':8}]}
        before={'node':1,'seq':10,'state':{'chain_depth':1,'cards':[{'code':ASH,'instance_id':7,'controller':0,'location':2},
            {'controller':1,'location':8,'position':8,'unknown':True}]}}
        after={'node':2,'seq':20,'state':{'chain_depth':0,'cards':[{'code':ASH,'instance_id':7,'controller':0,'location':16},
            {'code':777,'instance_id':9,'controller':1,'location':16}]}}
        hint={'id':'h','known_state':deepcopy(known),'decisions':[{'choice':'use'}],'items':[{'if_hold':'hypothetical only'}],
              'native_origin':{'checkpoint':1,'seq':10}}
        doc={'native_history':[before,after],'native_actions':[{'seq':12,'player':0,'selection':[]}],
             'native_outcomes':[{'seq':18,'kind':'effect_negated','link':1}]}
        result=review(doc,hint)
        self.assertEqual(result['known_state'],known);self.assertEqual(result['actual']['own_hand_departures'],[ASH])
        self.assertEqual(result['actual']['opponent_field_departures'],[])
        doc['native_history'].append({'node':3,'seq':30,'state':{'chain_depth':0,'cards':[{'code':999,'location':2,'controller':1}]}})
        self.assertEqual(review(doc,hint),result)
        doc['native_history']=[before];self.assertIsNone(review(doc,hint)['actual'])

    def test_player_notes_are_bound_to_the_window_and_never_added_to_old_knowledge(self):
        origin={'source':'native','checkpoint':1,'seq':10}
        hint={'id':'h','known_state':{'cards':[]},'decisions':[],'items':[],'native_origin':origin}
        doc={'events':[{'kind':'choice','native_origin':origin,'payload':{'note':'intent only'},'time_ms':20},
                       {'kind':'result','native_origin':{**origin,'checkpoint':2},'payload':{'note':'later other window'},'time_ms':30}]}
        result=review(doc,hint)
        self.assertEqual([n['note'] for n in result['notes']],['intent only'])
        self.assertEqual(result['known_state'],{'cards':[]});self.assertIsNone(result['actual'])


class LinkedAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SecondHintTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.owner=self.fixture.api;self.routes=self.owner.routes;self.fixture.window()
        self.doc=self.owner.load(self.fixture.doc['id'])
        self.doc['native_link']={'source':'synthetic','stamp':'old','rules':'rules','checkpoint':1,'seq':1}
        self.connection=patch.object(self.routes,'connection_error',return_value='');self.connection.start();self.addCleanup(self.connection.stop)

    def test_linked_physical_changes_and_manual_counter_edits_are_rejected_without_writes(self):
        before=deepcopy(self.doc)
        for kind in ('move','opponent_card','reveal','effect_count','effect_observed','effect_outcome'):
            with self.assertRaisesRegex(ValueError,'重复手填'):self.fixture.event(kind)
        self.assertEqual(self.owner.load(self.doc['id']),before)

    def test_verification_cannot_overwrite_native_phase_or_lp_but_notes_remain_recordable(self):
        state=self.doc['current']
        with self.assertRaisesRegex(ValueError,'核对值'):
            self.fixture.event('verify',turn=2,turn_player=0,phase='main1',lp=state['lp'],opponent_hand_count=None,confirmed=True)
        self.fixture.event('choice',note='original intent, no resource movement')
        self.assertEqual(self.fixture.doc['input'],self.doc['input'])
        self.assertEqual(self.fixture.doc['current']['cards'],self.doc['current']['cards'])

    def test_manual_window_cannot_change_the_actual_source_effect(self):
        self.doc['current']['native_window']={'recognized':True,'effect_id':'moye.token','card_id':'different','link':1,'top':1,'speed':1,'responders':[]}
        actor=next(c for c in self.doc['current']['cards'] if c['controller']==1)
        with self.assertRaisesRegex(ValueError,'原生响应窗口'):
            self.fixture.event('hint_window',card_id=actor['id'],effect_id='aluber.search',link=1,top=1,speed=1,
                protections=[],protections_checked=True,other_rules='none',grave_rule='normal',objective='balanced',environment='local',confirmed=True)

    def test_positive_manual_checks_cannot_override_an_absent_native_response(self):
        self.doc['current']['native_window']={'recognized':True,'responders':[]}
        hint=self.owner.hints.evaluate(self.doc,self.fixture.proof)
        self.assertTrue(all(r['conditions']=='blocked' for r in hint['items']))
        self.assertTrue(all(any('原生菜单' in b for b in r['blocked']) for r in hint['items']))
