"""Focused privacy, masked-reference and feature-identity regressions."""
from copy import deepcopy
import struct
import unittest
from contract_v2 import build,feature_arrays,Unsupported

N,L=1184620,93490856
CAT={N:{'type':17,'attribute':1,'race':1,'level':4,'atk':1500,'def':1200},
     L:{'type':33,'attribute':2,'race':8192,'level':6,'atk':1200,'def':2300}}


def fixture():
    cards=[{'instance_id':10,'code':N,'owner':0,'controller':0,'location':1,'sequence':0,'position':8},
           {'instance_id':11,'code':L,'owner':0,'controller':0,'location':1,'sequence':15,'position':8},
           {'instance_id':12,'code':N,'owner':0,'controller':0,'location':2,'sequence':0,'position':10},
           {'instance_id':13,'code':N,'owner':1,'controller':1,'location':2,'sequence':0,'position':10}]
    dynamic=[{'instance_id':c['instance_id'],'type':CAT[c['code']]['type'],'attribute':1,'race':1,
              'level':4,'rank':0,'link':0,'link_marker':0,'attack':2500,'defense':1200,
              'base_attack':1500,'base_defense':1200} for c in cards]
    raw=bytes([15,0,0,1,1,1])+struct.pack('<I',L)+bytes([0,1,0,8])
    return {'player':0,'answered':False,'version':1,'raw':raw.hex(),'effects':{},
            'state':{'turn':1,'turn_player':0,'phase':4,'lp':[8000,8000],'cards':cards,
                     'chain_depth':0,'chains':[],'normal_summons_used':[0,0],'normal_summon_limit':[1,1],
                     'extra_normal_summon_used':[False,False],'effect_usage':[]},
            'learning':{'schema':2,'available':True,'cards':dynamic}}


class ContractTests(unittest.TestCase):
    def test_masked_deck_sequence_resolves_code(self):
        bundle=build(fixture(),CAT)
        selected=bundle['candidates'][0]['public']['selection'][0]['card']
        self.assertEqual(selected['code'],L)
        self.assertEqual(selected['sequence'],0)

    def test_private_order_and_identity_do_not_change_features(self):
        first=fixture();second=deepcopy(first)
        second['state']['cards'][0]['sequence']=15;second['state']['cards'][1]['sequence']=0
        second['state']['cards'][3]['code']=L
        a,b=build(first,CAT),build(second,CAT)
        self.assertEqual(a['observation'],b['observation'])
        x,y=feature_arrays(a),feature_arrays(b)
        self.assertTrue(all((x[k]==y[k]).all() for k in x))

    def test_dynamic_value_not_database_value(self):
        b=build(fixture(),CAT);f=feature_arrays(b)
        i=next(i for i,c in enumerate(b['observation']['cards']) if c['controller']==0 and c['location']==2)
        self.assertAlmostEqual(float(f['card_numeric'][i,0]),0.25)
        self.assertAlmostEqual(float(f['card_numeric'][i,2]),0.15)

    def test_missing_dynamic_value_rejected(self):
        s=fixture();s['learning']['cards']=[]
        with self.assertRaises(Unsupported):build(s,CAT)

    def test_attribute_choices_have_different_scalar_features(self):
        s=fixture();s['raw']=(bytes([141,0,1])+struct.pack('<I',3)).hex()
        b=build(s,CAT);f=feature_arrays(b)
        self.assertEqual(len(b['candidates']),2)
        self.assertFalse((f['actions'][0]==f['actions'][1]).all())

    def test_unknown_model_card_scope_rejected(self):
        b=build(fixture(),CAT)
        with self.assertRaises(Unsupported):feature_arrays(b,supported_codes={N})

    def test_chain_identity_is_encoded(self):
        a=build(fixture(),CAT);b=deepcopy(a)
        for bundle,code in ((a,N),(b,L)):
            bundle['observation']['chains']=[{'link':1,'effect':{'handler_code':code,'description':code*16}}]
        self.assertFalse((feature_arrays(a)['chains']==feature_arrays(b)['chains']).all())

    def test_capacity_rejects_without_truncating(self):
        b=build(fixture(),CAT)
        b['observation']['chains']=[{'link':i,'effect':None} for i in range(17)]
        with self.assertRaisesRegex(Unsupported,'chain_capacity'):feature_arrays(b)

    def test_counter_type_never_silently_collapses(self):
        b=build(fixture(),CAT);b['observation']['cards'][0]['counters']=[{'type':1,'count':2}]
        with self.assertRaisesRegex(Unsupported,'typed_counters'):feature_arrays(b)


if __name__=='__main__':unittest.main()
