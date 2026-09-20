from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trainer'))

def fixture():
    source={'id':'source','title':'公开样本','url':'https://example.org/report','kind':'decklist'}
    route={'id':'route-a','title':'起手甲','opening':{'cards':[{'code':101,'quantity':1}],'other_cards':0,'conditions':'先攻空场，通常召唤未使用'},
           'steps':[{'id':'step-1','cards':[101],'action':'通常召唤','result':'得到身体'},{'id':'step-2','cards':[201],'action':'进入额外','result':'形成终场'}],
           'endboard':[{'code':201,'quantity':1,'note':'示例终场'}],'source_ids':['source'],'validation':'card_text_reviewed','notes':'条件推演'}
    second=deepcopy(route);second.update(id='route-b',title='起手乙');second['opening']['cards'][0]['code']=102;second['steps'][0]['cards']=[102]
    deck={'id':'deck-a','period_id':'new','archetype':'a','name':'公开构筑甲','tag_ids':['set:62'],'source_ids':['source'],'reported_date':'2026-09-10','date_note':'来源日期',
          'main':[{'code':i,'quantity':3 if i<114 else 1} for i in range(101,115)],'extra':[{'code':201,'quantity':1}],'side':None,'routes':[route,second]}
    return {'version':1,'revision':'2026-09-20','checked_at':'2026-09-20','sources':[source],'tags':[{'id':'set:62','name':'卡通'}],
            'card_names':{'101':'素材甲','201':'终场甲'},'periods':[
            {'id':'old','format':'OCG','label':'七月样本','start':'2026-07-01','end':'2026-07-31','sample_size':100,'metric':'公开样本占比','note':'非全体占有率','source_ids':['source'],'breakdown':[{'archetype':'a','name':'甲','count':30}]},
            {'id':'new','format':'Master Duel','label':'九月样本','start':'2026-09-01','end':'2026-09-20','sample_size':10,'metric':'公开样本占比','note':'非全体占有率','source_ids':['source'],'breakdown':[{'archetype':'a','name':'甲','count':2},{'archetype':'b','name':'乙','count':5}]}],
            'decks':[deck]}

class OpponentCatalogTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('intelligence_opponents'),'The read-only opponent catalog module exists')
        import intelligence_opponents
        return intelligence_opponents
    def store(self):
        return SimpleNamespace(catalog=SimpleNamespace(cards={101:{'id':101,'name':'当前卡名','desc':'当前文本'}}),
                               library=SimpleNamespace(all_tags=lambda:{'set:62':{'id':'set:62','name':'已有TAG名称'}}))
    def test_sorts_period_then_share_and_keeps_source_denominator(self):
        value=fixture();second=deepcopy(value['decks'][0]);second.update(id='deck-b',archetype='b');value['decks'].append(second)
        old=deepcopy(second);old.update(id='deck-old',period_id='old',archetype='a');value['decks'].append(old)
        before=deepcopy(value);result=self.module().snapshot(self.store(),value)
        self.assertEqual([p['id'] for p in result['periods']],['new','old'])
        self.assertEqual([d['id'] for d in result['decks']],['deck-b','deck-a','deck-old'])
        self.assertEqual(result['decks'][0]['share'],.5);self.assertEqual(result['decks'][0]['sample_count'],5)
        self.assertEqual(result['decks'][0]['sample_size'],10);self.assertEqual(value,before)
    def test_preview_retains_counts_unknown_side_and_stable_ids_without_writing(self):
        result=self.module().snapshot(self.store(),fixture());d=result['decks'][0]
        self.assertEqual(d['counts'],{'main':40,'extra':1,'side':None})
        self.assertTrue(result['readonly']);self.assertEqual(d['routes'][0]['id'],'route-a')
        self.assertEqual(result['tags'][0]['name'],'已有TAG名称');self.assertEqual(result['cards']['101']['name'],'当前卡名')
        self.assertTrue(result['cards']['201']['missing']);self.assertEqual(result['cards']['201']['name'],'终场甲')
    def test_rejects_incomplete_or_duplicate_routes_and_cards_outside_the_list(self):
        for change in (lambda d:d.update(routes=d['routes'][:1]),
                       lambda d:d['routes'][1].update(id=d['routes'][0]['id']),
                       lambda d:d['routes'][1]['steps'][0].update(cards=[999]),
                       lambda d:d['routes'][0]['opening']['cards'][0].update(quantity=4),
                       lambda d:d['routes'][0].update(validation='engine_verified')):
            value=fixture();change(value['decks'][0])
            with self.subTest(change=change),self.assertRaises(ValueError):self.module().snapshot(self.store(),value)
    def test_rejects_invented_share_invalid_counts_and_unsafe_source(self):
        for change in (lambda v:v['periods'][1].update(sample_size=0),
                       lambda v:v['periods'][1]['breakdown'][0].update(count=11),
                       lambda v:v['decks'][0].update(tag_ids=['missing']),
                       lambda v:v['sources'][0].update(url='file:///private'),
                       lambda v:v['decks'][0]['main'][0].update(quantity=True)):
            value=fixture();change(value)
            with self.subTest(change=change),self.assertRaises(ValueError):self.module().snapshot(self.store(),value)

    def test_terminal_resource_quantity_cannot_exceed_the_published_composition(self):
        value=fixture();value['decks'][0]['routes'][0]['endboard'][0]['quantity']=2
        with self.assertRaises(ValueError):self.module().snapshot(self.store(),value)

if __name__=='__main__':unittest.main()
