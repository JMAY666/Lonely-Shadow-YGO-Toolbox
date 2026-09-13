"""Synthetic events and public card text; no user training/deck data."""
from copy import deepcopy
import json
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from card_semantics import clauses, effect_clause, summon_method, zone_name
from actions import project_actions
from report import build_report
from test_reports import card, event, move, report, POT, MONSTER

SAGE = 8240199
SAGE_TEXT = ('这个卡名的②的效果1回合只能使用1次。\n'
             '①：这张卡召唤时才能发动。从卡组把「青色眼睛的贤士」以外的1只光属性·1星调整加入手卡。\n'
             '②：把这张卡从手卡丢弃，以自己场上1只效果怪兽为对象才能发动。那只怪兽送去墓地，从卡组把1只「青眼」怪兽特殊召唤。')
STONE_TEXT = ('这个卡名的②的效果1回合只能使用1次。\n'
              '①：这张卡被送去墓地的回合的结束阶段才能发动。从卡组把1只「青眼」怪兽特殊召唤。\n'
              '②：把墓地的这张卡除外，以自己墓地1只「青眼」怪兽为对象才能发动。那只怪兽加入手卡。')


class TextTests(unittest.TestCase):
    def test_mikailis_search_description_maps_to_effect_three_not_two(self):
        code = 42741437
        text = ('4星怪兽×2\n这个卡名的①③的效果1回合各能使用1次。\n'
                '①：这张卡用「救祓少女」怪兽为素材作超量召唤的自己·对方回合，以对方的场上·墓地1张卡为对象才能发动。那张卡除外。\n'
                '②：这张卡不会被和从墓地特殊召唤的怪兽的战斗破坏。\n'
                '③：把这张卡1个超量素材取除才能发动。从卡组把1张「救祓少女」魔法·陷阱卡加入手卡。')
        catalog = {str(code): {'desc': text}}
        for index, expected in ((0, 1), (1, 3), (2, None)):
            e = event(1, 70, cards=[card(code, 1, 4, 5)], effect={'description_id': code * 16 + index})
            self.assertEqual(effect_clause(e, catalog)['number'], expected)

    def test_clause_headings_do_not_include_restriction_references(self):
        parts = clauses(SAGE_TEXT)
        self.assertEqual(set(parts), {1, 2})
        self.assertTrue(parts[1].startswith('①：这张卡召唤时'))
        self.assertNotIn('②', parts[1])

    def test_sage_effect_number_uses_audited_activation_not_zero_description(self):
        catalog = {str(SAGE): {'desc': SAGE_TEXT}}
        for location, number in ((4, 1), (2, 2)):
            e = event(1, 70, cards=[card(SAGE, 1, location)], effect={'description_id':0})
            answer = effect_clause(e, catalog)
            self.assertEqual(answer['number'], number)
            self.assertTrue(answer['text'].startswith('①' if number == 1 else '②'))

    def test_changed_text_or_copied_effect_fails_closed(self):
        e = event(1,70,cards=[card(SAGE,1,4)],effect={'description_id':0})
        self.assertIsNone(effect_clause(e,{str(SAGE):{'desc':SAGE_TEXT+'变化'}})['number'])
        e['effect']['description_id']=12345
        self.assertIsNone(effect_clause(e,{str(SAGE):{'desc':SAGE_TEXT}})['number'])
        e['effect']['description_id']=0
        e['engine_effect']={'owner_code':POT}
        self.assertIsNone(effect_clause(e,{str(SAGE):{'desc':SAGE_TEXT}})['number'])

    def test_description_index_zero_can_mean_effect_two(self):
        code=71039903
        e=event(1,70,cards=[card(code,1,16)],effect={'description_id':code*16})
        self.assertEqual(effect_clause(e,{str(code):{'desc':STONE_TEXT}})['number'],2)

    def test_unknown_multi_effect_index_is_not_ordinal(self):
        e=event(1,70,cards=[card(123,1,4)],effect={'description_id':123*16})
        self.assertIsNone(effect_clause(e,{'123':{'desc':'①：抽1张。\n②：回复1000。','str1':''}})['number'])

    def test_unnumbered_text_preserved_and_duplicate_numbers_unknown(self):
        e=event(1,70,cards=[card()])
        self.assertEqual(effect_clause(e,{str(POT):{'desc':'自己抽2张。'}})['text'],'自己抽2张。')
        self.assertEqual(clauses('①：第一块。\n①：第二块。'),{})


class ProcedureTests(unittest.TestCase):
    def test_native_summon_types_and_materials(self):
        types=[(0x4c000000,0x10000008,'连接召唤'),(0x46000000,0x80008,'同调召唤'),
               (0x49000000,0x200008,'超量召唤'),(0x43000000,0x40048,'融合召唤')]
        for info, reason, name in types:
            with self.subTest(name=name):
                material=card(MONSTER,1,4)
                summoned={**card(123,2,4,5),'name':'测试额外怪兽','summon_info':info|0x400000,'summon_method':summon_method(info),'material_instance_ids':[1]}
                m=move(1,material,4,128 if name=='超量召唤' else 16,reason);m['material_target']=2
                events=[m,move(2,summoned,64,4,0x800),event(3,62,cards=[summoned]),event(4,63,cards=[summoned])]
                a=project_actions(report(events))
                self.assertEqual(len(a),1)
                self.assertIn(name,a[0]['summary']);self.assertIn('额外怪兽区 1',a[0]['summary'])
                self.assertEqual(a[0]['cards'][0]['materials'][0]['instance_id'],1)
                self.assertIn('1:0',a[0]['evidence_refs'])

    def test_generic_revival_does_not_become_fusion_summon(self):
        c={**card(123,2,4,1),'summon_info':0x40100000,'summon_method':'特殊召唤','material_instance_ids':[1]}
        r=report([move(1,c,16,4,0x800),event(2,62,cards=[c]),event(3,63,cards=[c])])
        r['catalog']['123']={'type':0x41,'desc':'融合怪兽'}
        a=project_actions(r)[0]
        self.assertNotIn('融合召唤',a['summary']);self.assertIn('从我方墓地特殊召唤',a['summary'])

    def test_legacy_materials_require_explicit_target(self):
        c=card(123,2,4,5);m=move(1,card(MONSTER,1,4),4,16,0x10000008)
        ev=[m,move(2,c,64,4,0x800),event(3,62,cards=[c]),event(4,63,cards=[c])]
        self.assertEqual(len(project_actions(report(ev))),2)
        m['material_target']=2
        a=project_actions(report(ev));self.assertEqual(len(a),1);self.assertIn('连接召唤',a[0]['summary'])

    def test_main_extra_and_overlay_zones(self):
        self.assertEqual(zone_name(4,0),'主怪兽区 1')
        self.assertEqual(zone_name(4,5),'额外怪兽区 1')
        self.assertEqual(zone_name(4,6),'额外怪兽区 2')
        self.assertEqual(zone_name(0x84,5),'叠放素材')

    def test_effect_summon_does_not_duplicate_placement(self):
        source={'effect_id':1,'effect_handle':9,'handler_instance':8}
        c=card(MONSTER,2,4,2)
        e=move(3,c,2,4,0x800);e['cause']=source
        events=[event(1,70,cards=[card(instance=8)],chain=1,engine_effect=source),event(2,72,chain=1),
                e,event(4,62,cards=[c],cause=source),event(5,63,cards=[c],cause=source),event(6,73,chain=1)]
        a=project_actions(report(events))[0]
        self.assertEqual(len(a['execution']),1)
        self.assertIn('从我方手卡特殊召唤',a['observed_summary'])
        self.assertNotIn('移至',a['observed_summary'])


class OutcomeTests(unittest.TestCase):
    def test_cost_after_chaining_comes_before_draw_in_execution(self):
        source={'effect_id':10,'effect_handle':9,'handler_instance':1}
        cost=move(2,card(MONSTER,2,2),2,16,0x4080);cost['cause']=source
        events=[event(1,70,cards=[card()],chain=1,engine_effect=source),cost,event(3,71,chain=1),event(4,72,chain=1),
                event(5,90,cards=[card(MONSTER,3),card(MONSTER,4)],actor='self',draw_kind='effect'),event(6,73,chain=1)]
        a=project_actions(report(events))[0]
        self.assertEqual([s['role'] for s in a['execution']],['cost','result'])
        self.assertIn('丢弃',a['execution'][0]['text'])

    def test_six_facedown_banishes_are_one_cost_and_sort_is_one_result(self):
        source={'effect_id':10,'effect_handle':9,'handler_instance':1}
        events=[event(1,70,cards=[card()],chain=1,engine_effect=source)]
        for i in range(6):
            e=move(i+2,card(100+i,i+10,64),64,32,0x80);e['destination']['position']=10;e['cause']=source;events.append(e)
        events += [event(8,71,chain=1),event(9,72,chain=1),event(10,30,player=0,cards=[card(200+i,i+20,1) for i in range(6)])]
        events.append(move(11,card(200,20,1),1,2,0x40))
        for i in range(5):
            refresh=move(12+i,card(201+i,21+i,1),1,1,0x40);refresh['deck_operation']='position_refresh';events.append(refresh)
        for i in range(5):
            reorder=move(17+i,card(201+i,21+i,1),1,1,0);reorder['deck_operation']='move_to_bottom';events.append(reorder)
        events.append(event(22,73,chain=1))
        a=project_actions(report(events))[0]
        self.assertEqual(len(a['execution']),4)
        cost=a['execution'][0];self.assertEqual(len(cost['cards']),6);self.assertEqual(len(cost['event_refs']),6)
        self.assertIn('6 张卡里侧除外',cost['text'])
        self.assertIn('剩余 5 张卡',a['execution'][-1]['text']);self.assertIn('卡组底部',a['execution'][-1]['text'])
        self.assertNotIn('移至我方卡组',a['observed_summary'])

    def test_set_during_effect_resolution_does_not_duplicate_move(self):
        c=card(123,2,8,3)
        events=[event(1,70,cards=[card()],chain=1),event(2,72,chain=1),move(3,c,1,8,0),event(4,54,cards=[c]),event(5,73,chain=1)]
        a=project_actions(report(events))[0]
        self.assertEqual(len(a['execution']),1);self.assertIn('盖放',a['observed_summary'])

    def test_same_deck_reorder_preserves_instances_across_one_batch(self):
        cards=[{**card(100+i,i+1,1,i),'reason':0} for i in range(5)]
        state={'cards':cards,'turn':1,'turn_player':0,'phase':4,'lp':[8000,8000]}
        raw=b''
        for code in [104,103,102]:
            raw+=bytes([50])+struct.pack('<I',code)+bytes([0,1,4,8,0,1,0,8])+struct.pack('<I',0)
        end=deepcopy(state)
        # three top-to-bottom insertions: [2,3,4,0,1] from bottom to top.
        for sequence,index in enumerate([2,3,4,0,1]):end['cards'][index]['sequence']=sequence
        rows=[{'kind':'loaded','seq':1,'time_ms':1,'state':state},{'kind':'batch','seq':2,'time_ms':2,'raw':raw.hex(),'state':end}]
        meta={'deck':{'main':[100+i for i in range(5)],'extra':[],'side':[]},'catalog':{},'started_ms':0}
        r=build_report(meta,rows,[])
        self.assertEqual([e['cards'][0]['instance_id'] for e in r['events']],[5,4,3])
        self.assertTrue(all(e['deck_operation']=='move_to_bottom' for e in r['events']))


if __name__=='__main__': unittest.main()
