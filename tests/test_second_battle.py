"""Battle result provenance, bounded choices and non-disclosure contracts."""
from copy import deepcopy
from pathlib import Path
import struct
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trainer'))
from second_battle import BattleWalk,validate_order,preview

ATTACK=bytes([110,0,4,0,1,1,0,0,0]).hex()
DAMAGE=bytes([91,1]).hex()+struct.pack('<I',1500).hex()
WIN=bytes([5,0,1]).hex()


class BattleTests(unittest.TestCase):
    def base(self):
        return {'raw':'battle','player':0,'state':{'lp':[8000,3000],'cards':[{'instance_id':1,'code':1184620,'controller':0,'location':4,'sequence':0,'position':1}]}}

    def prompt(self,raw,*_):
        return {'message':10,'player':0,'choices':[{'semantic':{'kind':'attack'},'card':{'instance_id':1,'sequence':0},'response':'attack'}] if raw=='battle' else []}

    def walk(self,following,order=None):
        modular=SimpleNamespace(bridge=Mock(return_value=following))
        walk=BattleWalk(modular,'sid',self.base(),lambda:True)
        with patch('second_battle.model',side_effect=self.prompt):
            result=walk.run(order or [{'attacker':1,'attacker_code':1184620,'target':None,'target_code':None}])
        return result,modular

    def test_lp_zero_without_a_core_win_event_cannot_be_a_lethal_claim(self):
        following={'raw':None,'ended':True,'state':{'lp':[8000,0],'cards':[]},'batches':[ATTACK+DAMAGE]}
        result,_=self.walk(following)
        self.assertEqual(result['lp_after'],[8000,0]);self.assertFalse(result['conditional_lethal'])
        following['batches']=[ATTACK+DAMAGE+WIN]
        result,_=self.walk(following);self.assertTrue(result['conditional_lethal'])

    def test_spent_attack_is_rejected_and_damage_is_not_counted_twice(self):
        following={'raw':'spent','player':0,'ended':False,'state':{'lp':[8000,1500],'cards':[],'chain_depth':0},'batches':[ATTACK+DAMAGE]}
        order=[{'attacker':1,'attacker_code':1184620,'target':None,'target_code':None}]*2
        result,modular=self.walk(following,order)
        self.assertEqual(result['status'],'incomplete');self.assertEqual(len(result['steps']),1)
        self.assertEqual(result['lp_after'][1],1500);modular.bridge.assert_called_once()

    def test_incorrect_attack_target_does_not_publish_its_damage(self):
        following={'raw':None,'ended':True,'state':{'lp':[8000,0],'cards':[]},'batches':[bytes([110,0,4,0,1,1,4,1,1]).hex()+DAMAGE+WIN]}
        result,_=self.walk(following)
        self.assertFalse(result['conditional_lethal']);self.assertEqual(result['steps'],[])
        self.assertEqual(result['lp_after'],result['lp_before'])

    def test_unrevealed_opponent_card_cannot_contribute_to_a_published_result(self):
        initial=self.base();initial['state']['cards'].append({'instance_id':9,'code':999,'controller':1,'location':8,'position':8})
        following={'raw':None,'ended':True,'state':{'lp':[8000,0],'cards':[{'instance_id':9,'code':999,'controller':1,'location':16,'position':1}]},'batches':[ATTACK+DAMAGE+WIN]}
        walk=BattleWalk(SimpleNamespace(bridge=lambda *a:following),'sid',initial,lambda:True)
        with patch('second_battle.model',side_effect=self.prompt):result=walk.run([{'attacker':1,'attacker_code':1184620,'target':None,'target_code':None}])
        self.assertEqual(result['steps'],[]);self.assertEqual(result['lp_after'],[8000,3000]);self.assertFalse(result['conditional_lethal'])
        self.assertIn('未公开',result['reason'])

    def test_order_uses_current_instances_and_does_not_read_a_set_target(self):
        doc={'current':{'cards':[{'id':'own','native_instance':1,'code':1,'controller':0,'location':4},
                                {'id':'set','code':None,'controller':1,'location':4,'position':8}]}}
        for order in ([],[{'attacker':'old','target':'direct'}],[{'attacker':'own','target':'set'}]):
            with self.assertRaises(ValueError):validate_order(doc,{'order':order})
        self.assertEqual(validate_order(doc,{'order':[{'attacker':'own','target':'direct'}]})[0]['attacker'],1)

    def test_raw_negative_lp_is_retained_while_the_display_reaches_zero(self):
        following={'raw':None,'ended':True,'state':{'lp':[8000,-500],'cards':[]},'batches':[ATTACK+DAMAGE+WIN]}
        result,_=self.walk(following)
        self.assertEqual(result['core_lp_after'],[8000,-500]);self.assertEqual(result['lp_after'],[8000,0])
        self.assertTrue(result['conditional_lethal'])

    def test_shuffled_set_cards_or_conflicting_end_messages_do_not_create_certainty(self):
        following={'raw':None,'ended':True,'state':{'lp':[8000,0],'cards':[]},'batches':['240100'+ATTACK+DAMAGE+WIN]}
        result,_=self.walk(following);self.assertFalse(result['conditional_lethal']);self.assertEqual(result['steps'],[])
        following['batches']=[ATTACK+DAMAGE+WIN+bytes([5,1,1]).hex()]
        result,_=self.walk(following);self.assertFalse(result['conditional_lethal']);self.assertEqual(result['status'],'incomplete')

    def test_late_preview_is_not_saved_into_a_newer_observation(self):
        doc={'id':'doc','revision':0,'native_link':{'stamp':'s'},'current':{'usage':[],'restrictions':[],'cards':[{'id':'own','native_instance':1,'code':1,'controller':0,'location':4}]}}
        owner=SimpleNamespace(lock=threading.RLock(),load=lambda key:doc,save=Mock(),public=lambda d:d,now=lambda:1)
        modular=SimpleNamespace(planning_lock=threading.Lock(),state=lambda sid:self.base())
        routes=SimpleNamespace(owner=owner,store=SimpleNamespace(modular=modular),operations=threading.Lock(),
            request=lambda body:doc,bindings={'doc':{'sid':'sid','stage':'own_turn'}},valid=Mock(side_effect=[True,False]))
        before=deepcopy(doc)
        with patch.object(BattleWalk,'run',return_value={'status':'validated'}):
            with self.assertRaisesRegex(ValueError,'未发布'):
                preview(routes,{'request_id':'a'*32,'order':[{'attacker':'own','target':'direct'}]})
        owner.save.assert_not_called();self.assertEqual(doc,before)
