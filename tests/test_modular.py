from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trainer'))
from modular_decisions import bind, digest, effect_key, integer, model, public_state, semantic_response, validate_source, bind_variants, snapshot_matches
from modular import Modular


def idle(cards, effects):
    # Six groups: five empty lists followed by all individually selectable effects.
    raw = bytes([11, 0, 0, 0, 0, 0, 0, len(effects)])
    for card, effect in zip(cards, effects):
        raw += card['code'].to_bytes(4,'little') + bytes([0, card['location'], card['sequence']]) + effect['description'].to_bytes(4,'little')
    return (raw+bytes([0,1,0])).hex()


class DecisionTests(unittest.TestCase):
    def test_different_values_of_one_shared_function_are_not_the_same_effect(self):
        card=dict(code=123,controller=0,location=4,sequence=0,position=1,instance_id=8)
        a=dict(handler_code=123,description=0,operation_line=20,labels=[],effect_value=1)
        b={**a,'effect_value':2}
        source=model(idle([card],[a]),{'cards':[card]},{'choices':[a]})
        current=model(idle([card],[b]),{'cards':[card]},{'choices':[b]})
        self.assertEqual(bind_variants(semantic_response(source,integer(5)),current,precise=False),[])
    def test_adaptive_positions_still_require_the_exact_effect_and_legal_zone(self):
        card=dict(code=123,controller=0,location=4,sequence=0,position=1,instance_id=8)
        effect=dict(handler_code=123,description=1968,operation_line=20,labels=[1])
        source=model(idle([card],[effect]),{'cards':[card]},{'choices':[effect]})
        decision=semantic_response(source,integer(5));moved={**card,'sequence':1}
        current=model(idle([moved],[effect]),{'cards':[moved]},{'choices':[effect]})
        self.assertEqual(bind_variants(decision,current,precise=True),[])
        self.assertEqual(bind_variants(decision,current,precise=False),[integer(5)])
        changed={**effect,'labels':[2]}
        self.assertEqual(bind_variants(decision,model(idle([moved],[changed]),{'cards':[moved]},{'choices':[changed]}),precise=False),[])
        raw=bytes([18,0,1])+((0xffffffff ^ (1<<3))).to_bytes(4,'little')
        p=model(raw.hex(),{'cards':[]})
        place={'message':18,'player':0,'context':None,'selection':[{'kind':'place','place':[0,4,1]}]}
        self.assertEqual(bind_variants(place,p,precise=True),[])
        self.assertEqual(bind_variants(place,p,precise=False),['000403'])
        place['selection'][0]['place'][0]=1
        self.assertEqual(bind_variants(place,p,precise=False),[])

    def test_precise_snapshot_compares_known_resources_but_not_private_ids_or_deck_order(self):
        first={'turn':1,'turn_player':0,'phase':4,'lp':[8000,8000],'chain_depth':0,'cards':[
            {'code':1,'controller':0,'location':4,'sequence':0,'position':1,'instance_id':1},
            {'code':2,'controller':0,'location':1,'sequence':0,'instance_id':2}]}
        second=deepcopy(first);second['cards'][0]['instance_id']=99;second['cards'][1]['sequence']=9
        self.assertTrue(snapshot_matches(first,second))
        second['cards'][0]['sequence']=1
        self.assertFalse(snapshot_matches(first,second))
        second=deepcopy(first);second['cards'].append({'code':3,'controller':0,'location':2})
        self.assertFalse(snapshot_matches(first,second))

    def test_three_effects_same_card_rebind_by_effect_not_menu_index(self):
        card=dict(code=123,controller=0,location=4,sequence=1,position=1,instance_id=99)
        effects=[dict(handler_code=123,description=1968+i,operation_line=20+i*10,count_code=123+i) for i in range(3)]
        source=model(idle([card]*3,effects),{'cards':[card]},{'choices':effects})
        decision=semantic_response(source,integer(5))
        reordered=[effects[2],effects[0],effects[1]]
        current=model(idle([card]*3,reordered),{'cards':[card]},{'choices':reordered})
        self.assertEqual(bind(decision,current),integer((1<<16)|5))
        self.assertEqual(decision['selection'][0]['effect']['operation_line'],20)
        changed=deepcopy(reordered);changed[1]['operation_line']=999
        self.assertIsNone(bind(decision,model(idle([card]*3,changed),{'cards':[card]},{'choices':changed})))

    def test_equal_description_different_script_functions_never_merge(self):
        card=dict(code=123,controller=0,location=4,sequence=1,position=1,instance_id=99)
        effects=[dict(handler_code=123,description=0,operation_line=n) for n in (20,30,40)]
        p=model(idle([card]*3,effects),{'cards':[card]},{'choices':effects})
        self.assertEqual(len({digest(semantic_response(p,integer((i<<16)|5))) for i in range(3)}),3)

    def test_shared_script_function_uses_effect_labels_to_distinguish_branches(self):
        card=dict(code=123,controller=0,location=4,sequence=1,position=1,instance_id=99)
        effects=[dict(handler_code=123,description=0,operation_line=20,labels=[n]) for n in (1,2,3)]
        source=model(idle([card]*3,effects),{'cards':[card]},{'choices':effects})
        decision=semantic_response(source,integer(5))
        reordered=[effects[2],effects[0],effects[1]]
        current=model(idle([card]*3,reordered),{'cards':[card]},{'choices':reordered})
        self.assertEqual(bind(decision,current),integer((1<<16)|5))

    def test_unknown_hand_and_facedowns_never_expose_effect_or_identity(self):
        state={'cards':[dict(code=123,controller=1,location=2,sequence=0,instance_id=8,reason_effect={'handler_code':123}),
                         dict(code=456,controller=1,location=8,sequence=0,position=8),
                         dict(code=789,controller=0,location=1,sequence=12)],'effect_usage':[{'player':1,'key':123}]}
        result=public_state(state)
        self.assertNotIn('123',str(result));self.assertNotIn('456',str(result))
        self.assertNotIn('sequence',result['cards'][2]);self.assertEqual(state['cards'][0]['code'],123)

    def test_consumed_effect_absent_from_prompt_cannot_be_reused(self):
        card=dict(code=123,controller=0,location=4,sequence=1,position=1,instance_id=99)
        effect=dict(handler_code=123,description=1968,operation_line=20)
        p=model(idle([card],[effect]),{'cards':[card]},{'choices':[effect]})
        action=semantic_response(p,integer(5))
        current=model(idle([],[]),{'cards':[card]},{'choices':[]})
        self.assertIsNone(bind(action,current))

    def test_field_position_and_unrelated_hand_are_distinct_conditions(self):
        card=dict(code=123,controller=0,location=4,sequence=1,position=1,instance_id=99)
        effect=dict(handler_code=123,description=1968,operation_line=20)
        source=model(idle([card],[effect]),{'cards':[card]},{'choices':[effect]})
        decision=semantic_response(source,integer(5))
        state={'cards':[card,dict(code=999,controller=0,location=2,sequence=0)]}
        self.assertEqual(bind(decision,model(idle([card],[effect]),state,{'choices':[effect]})),integer(5))
        moved={**card,'sequence':2}
        self.assertIsNone(bind(decision,model(idle([moved],[effect]),{'cards':[moved]},{'choices':[effect]})))

    def test_three_preferences_have_explainable_distinct_orders(self):
        def candidate(name,steps,board,hand,continued):
            return {'id':name,'remaining':steps,'goal_met':True,'conditional':False,
                'evaluation':{'board':board,'hand':hand,'extra':10,'lp':8000},
                'robustness':{'status':'evaluated','scenarios':[{'continued':v} for v in continued]}}
        candidates=[candidate('short',2,1,1,[False]),candidate('large',6,3,3,[False]),candidate('safe',4,2,2,[True])]
        for preference, expected in [('shortest','short'),('largest','large'),('safest','safe')]:
            actual=deepcopy(candidates);Modular.rank(actual,preference);self.assertEqual(actual[0]['id'],expected)

    def test_ambiguous_equal_effects_require_evidence_instead_of_first_index(self):
        card=dict(code=123,controller=0,location=4,sequence=1,position=1,instance_id=99)
        effect=dict(handler_code=123,description=0,operation_line=20)
        single=model(idle([card],[effect]),{'cards':[card]},{'choices':[effect]})
        decision=semantic_response(single,integer(5))
        ambiguous=model(idle([card,card],[effect,effect]),{'cards':[card]},{'choices':[effect,effect]})
        self.assertIsNone(bind(decision,ambiguous))

    def test_import_rejects_decision_tampering_before_storage(self):
        card=dict(code=123,controller=0,location=4,sequence=1,position=1,instance_id=99)
        effect=dict(handler_code=123,description=1968,operation_line=20)
        raw=idle([card],[effect]);state={'cards':[card]};effects={'choices':[effect]}
        decision=semantic_response(model(raw,state,effects),integer(5))
        source={'schema':1,'snapshots':[{'id':'a','raw':raw,'effects':effects,'state':state},{'id':'b','state':state}],
                'edges':[{'from':'a','to':'b','decision':decision,'response':integer(5),'delta':[]}]}
        validate_source(source)
        source['edges'][0]['decision']['selection'][0]['effect']['operation_line']=30
        with self.assertRaisesRegex(ValueError,'不一致'):validate_source(source)

    def test_overlay_selection_binds_carrier_and_material_instance(self):
        parent=dict(code=999,controller=0,location=4,sequence=1,position=1,instance_id=7)
        cards=[parent,*[dict(code=123,controller=0,location=128,sequence=i,position=0,instance_id=99+i,overlay_target=7) for i in range(2)]]
        raw=bytes([15,0,0,1,1,2])+b''.join((123).to_bytes(4,'little')+bytes([0,132,1,i]) for i in range(2))
        p=model(raw.hex(),{'cards':cards})
        decision=semantic_response(p,'0101')
        selected=decision['selection'][0]['card']
        self.assertEqual(selected['sequence'],1);self.assertEqual(selected['overlay']['code'],999)
        self.assertEqual(bind(decision,p),'0101')
        altered=deepcopy(cards);altered[0]['code']=998
        self.assertIsNone(bind(decision,model(raw.hex(),{'cards':altered})))


class LibraryVersionTests(unittest.TestCase):
    import test_store
    setUp=test_store.StoreTests.setUp
    tearDown=test_store.StoreTests.tearDown

    def test_edit_delete_restart_preserve_immutable_source_versions(self):
        from app import atomic_json, Store
        import uuid
        sid=str(uuid.uuid4())
        source={'schema':1,'snapshots':[],'edges':[],'unknown':[],'status':'incomplete'}
        plan={'id':sid,'name':'synthetic unit fixture','edit_revision':1,'modular_source':source}
        atomic_json(self.store.plan_path(sid),plan)
        first=self.store.modular.library.sync();version=first['sources'][0]['version']
        frozen=self.store.modular.library.root/'versions'/sid/(version+'.json')
        before=frozen.read_bytes()
        atomic_json(self.store.plan_path(sid),{**plan,'name':'edited','edit_revision':2})
        changed=self.store.modular.library.sync()
        self.assertNotEqual(changed['version'],first['version']);self.assertEqual(frozen.read_bytes(),before)
        reopened=Store(self.root).modular.library.sync()
        self.assertEqual(reopened,changed)
        self.store.plan_path(sid).unlink()
        self.assertEqual(self.store.modular.library.sync()['sources'],[])
        self.assertEqual(frozen.read_bytes(),before)


if __name__=='__main__':unittest.main()
