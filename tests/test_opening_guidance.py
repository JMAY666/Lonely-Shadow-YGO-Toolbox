from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trainer'))
from opening_guidance import describe, load_guide
from opening_analysis import concentration, DEFAULTS
from opening_analysis import analyze_routes
from test_opening_analysis import recorded


class GuidanceTests(unittest.TestCase):
    def setUp(self):
        self.data=load_guide()
        self.catalog={r['code']:{'name':r['name'],'desc':r['text'],'type':r['type'],'setcode':469 if r['code'] not in (61049315,99243014) else 0} for r in self.data['cards']}
        self.catalog[14558127]={'name':'灰流丽','desc':'合成调整手坑','type':0x1021}
        self.catalog[73642296]={'name':'屋敷童','desc':'合成调整手坑','type':0x1021}
        self.catalog[99]={'name':'非调整额外样例','desc':'合成','type':0x41}
        self.deck={'main':[16387555,61049315,16509007,14558127,73642296],'extra':[42781164,99],'side':[]}

    def test_opening_explains_cue_rosewhip_and_handtrap_material_tradeoff(self):
        before=deepcopy(self.catalog)
        result=describe(self.deck,[16387555,61049315,14558127,73642296],self.catalog)
        self.assertTrue(result['active'])
        self.assertEqual({r['code'] for r in result['hand_cards']},{16387555,61049315})
        interaction=next(r for r in result['highlights'] if r['kind']=='interaction')
        self.assertIn('上手不等于废件',interaction['text'])
        material=next(r for r in result['highlights'] if r['kind']=='material')
        self.assertIn('灰流丽、屋敷童',material['text'])
        self.assertIn('选择带',result['warnings'][0]['text'])
        self.assertIn('非调整额外样例',result['warnings'][0]['text'])
        self.assertEqual(self.catalog,before)

    def test_changed_text_or_type_disables_specific_claim_and_changes_version(self):
        original=describe(self.deck,[16387555,61049315],self.catalog)
        self.catalog[61049315]['desc']+=' 新版差异'
        changed=describe(self.deck,[16387555,61049315],self.catalog)
        self.assertFalse(any(r['kind']=='interaction' for r in changed['highlights']))
        self.assertIn(61049315,[r['code'] for r in changed['stale']])
        self.assertNotEqual(changed['version'],original['version'])
        self.catalog[16387555]['type']=1
        self.assertNotIn(16387555,[r['code'] for r in describe(self.deck,[16387555],self.catalog)['hand_cards']])

    def test_no_claims_about_unheld_starter_or_unrelated_deck(self):
        result=describe(self.deck,[14558127],self.catalog)
        self.assertFalse(result['highlights']);self.assertFalse(result['warnings'])
        empty=describe({'main':[14558127],'extra':[]},[14558127],self.catalog)
        self.assertFalse(empty['active']);self.assertFalse(empty['hand_cards'])

    def test_whitespace_and_verified_art_alias_keep_evidence_but_not_new_semantics(self):
        alternate=16387556
        self.catalog[alternate]={**self.catalog[16387555],'alias':16387555,'desc':self.catalog[16387555]['desc'].replace('\r\n','\n')}
        deck={**self.deck,'main':[alternate,*self.deck['main'][1:]]}
        result=describe(deck,[alternate,61049315],self.catalog)
        self.assertIn(alternate,[r['code'] for r in result['hand_cards']])
        self.assertTrue(any(r['kind']=='interaction' for r in result['highlights']))

    def test_broad_support_labels_do_not_dilute_main_series_or_change_members(self):
        tags={'set:1d5':{'name':'本家','setcode':469},'set:17':{'name':'同调','setcode':23},'set:46':{'name':'融合','setcode':70}}
        cats={1:{'setcode':469|(23<<16)},2:{'setcode':70}}
        before=deepcopy(tags)
        result=concentration({'main':[1]*20+[2]*3,'extra':[]},tags,cats,DEFAULTS)
        self.assertEqual([g['id'] for g in result['groups']],['set:1d5'])
        self.assertEqual(result['groups'][0]['exclusive'],20)
        self.assertEqual({r['id'] for r in result['support_tags']},{'set:17','set:46'})
        self.assertEqual(tags,before)

    def test_card_activation_keeps_existing_note_key(self):
        plan=recorded()
        plan['catalog']['10'].update(desc='①：合成场地适用效果。②：合成另一个效果。',type=0x80002)
        c={'code':10,'controller':0,'location':8,'sequence':5,'instance_id':1,'name':'10'}
        plan['events']=[{'id':'2:0','native_seq':2,'time_ms':0,'message':70,'chain':1,'cards':[c],'engine_effect':{'effect_type':0x10}},
                        {'id':'3:0','native_seq':3,'time_ms':0,'message':72,'chain':1,'cards':[]},
                        {'id':'4:0','native_seq':4,'time_ms':0,'message':73,'chain':1,'cards':[]}]
        rows=analyze_routes([plan],plan['deck'],[10],{int(c):v for c,v in plan['catalog'].items()},8)
        effect=rows['routes'][0]['effects'][0]
        self.assertEqual(effect['key'],'10:unknown')
        self.assertEqual(effect['kind'],'card_activation')
        self.assertEqual(effect['text'],'发动场地魔法卡')

    def test_missing_extra_card_is_unknown_not_a_non_tuner_or_a_crash(self):
        deck={**self.deck,'extra':self.deck['extra']+[999999]}
        result=describe(deck,[16387555],self.catalog)
        self.assertIn(999999,[row['code'] for row in result['stale']])
        self.assertTrue(all('999999' not in row['text'] for row in result['warnings']))


if __name__=='__main__':unittest.main()
