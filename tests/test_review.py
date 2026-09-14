from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from review import make_review, requirements, empty_annotations, annotations_for, legacy_review
from app import Store, read_json
import test_expansion


def card(i, code, location=2, sequence=0, **kw):
    return dict(instance_id=i, code=code, name=f'卡牌{code}', owner=0, controller=0, location=location,
                sequence=sequence, position=1, overlay_target=None, **kw)


def event(seq, msg, cards, offset=0, **kw):
    return dict(id=f'{seq}:{offset}', native_seq=seq, message=msg, type='合成验收事件', cards=deepcopy(cards), **kw)


def action(e, **kw):
    return dict(id=e['id'], kind='action', cards=e['cards'], evidence_refs=[e['id']], summary='合成验收动作', **kw)


def fixture():
    a, b, filler, xyz = card(1,101), card(2,101,sequence=1), card(3,102,sequence=2), card(4,201,64)
    start=[a,b,filler,xyz]
    first=[{**a,'location':4},b,filler,xyz]
    second=[first[0],{**b,'location':4,'sequence':1},filler,xyz]
    over=[{**a,'location':128,'overlay_target':4}, {**b,'location':128,'overlay_target':4,'sequence':1},filler,{**xyz,'location':4}]
    detached=[{**a,'location':16},over[1],filler,over[3]]
    state=lambda cs:dict(cards=deepcopy(cs),lp=[8000,8000],turn=1,phase=4,chain_depth=0)
    states=[dict(seq=1,kind='loaded',state=state([{**c,'location':1 if c['code']<200 else 64} for c in start])),
            dict(seq=2,kind='batch',state=state(start)),dict(seq=3,kind='checkpoint',state=state(start)),
            dict(seq=4,kind='batch',state=state(first)),dict(seq=5,kind='checkpoint',state=state(first)),
            dict(seq=6,kind='batch',state=state(second)),dict(seq=7,kind='checkpoint',state=state(second)),
            dict(seq=8,kind='batch',state=state(over)),dict(seq=9,kind='checkpoint',state=state(over)),
            dict(seq=10,kind='batch',state=state(detached)),dict(seq=11,kind='checkpoint',state=state(detached)),
            dict(seq=12,kind='end',state=state(detached))]
    e1=event(4,61,[{**first[0],'summon_method':'通常召唤','summon_origin':a}])
    e2=event(6,63,[{**second[1],'summon_method':'特殊召唤','summon_origin':b}])
    e3=event(8,63,[{**over[3],'summon_method':'超量召唤','materials':second[:2]}])
    e4=event(10,50,[over[0]],origin=over[0],destination=detached[0],cost={'reason_cost':True})
    report=dict(id='synthetic-review',name='节点验收',status='completed',initial_hand=deepcopy(start[:3]),initial_hand_ref='2:0',
                final_state=state(detached),final_state_ref=12,events=[e1,e2,e3,e4],actions=[action(e) for e in (e1,e2,e3,e4)],
                deck=dict(main=[101,101,102],extra=[201],side=[]),catalog={'101':{'name':'同名怪兽','desc':'测试'},'102':{'name':'无关牌'},'201':{'name':'超量怪兽','type':0x800001}})
    report['review']=make_review(report,states)
    return report,states


class ReviewProjectionTests(unittest.TestCase):
    def test_step_states_do_not_leak_later_hand_or_overlay_changes(self):
        report,rows=fixture();before=deepcopy(rows)
        nodes=report['review']['nodes']
        self.assertEqual([n['number'] for n in nodes],list(range(1,7)))
        self.assertEqual([sum(c['location']==2 for c in n['state']['cards']) for n in nodes],[3,2,1,1,1,1])
        self.assertEqual([sum(c.get('overlay_target')==4 for c in n['state']['cards']) for n in nodes],[0,0,0,2,1,1])
        self.assertEqual(nodes[3]['state']['cards'][0]['location'],128)
        self.assertEqual(nodes[4]['state']['cards'][0]['location'],16)
        self.assertEqual(rows,before)
        self.assertTrue(report['review']['complete'])

    def test_overlapping_chain_actions_share_one_end_boundary(self):
        report,rows=fixture()
        report['actions'][0]['evidence_refs'].append('8:0')
        projected=make_review(report,rows)
        self.assertEqual(projected['nodes'][1]['action_ids'],['4:0','6:0','8:0'])
        self.assertEqual(projected['nodes'][1]['state_ref'],9)
        self.assertEqual(len(projected['nodes']),4)

    def test_early_material_evidence_does_not_reorder_report_actions(self):
        report,rows=fixture()
        report['actions'][1]['evidence_refs'].insert(0,'2:1')
        view=make_review(report,rows)
        self.assertEqual(view['nodes'][1]['action_ids'],['4:0','6:0'])
        report['warnings']=['采集序号不连续：8']
        self.assertFalse(make_review(report,rows)['complete'])

    def test_duplicate_instances_count_once_across_reuse_and_unrelated_filler_is_excluded(self):
        report,_=fixture()
        summary=requirements(report)
        self.assertEqual([(c['code'],c['count']) for c in summary['main']],[(101,2)])
        self.assertEqual([(c['code'],c['count']) for c in summary['extra']],[(201,1)])
        self.assertEqual([(c['code'],c['count']) for c in summary['opening']],[(101,2)])

    def test_effect_and_rule_combined_move_still_counts_a_used_deck_resource(self):
        report,rows=fixture()
        deck_card=card(55,102,1)
        for row in rows: row['state']['cards'].append(deck_card.copy())
        moved=event(4,50,[deck_card],origin=deck_card,destination={**deck_card,'location':16},reason=0x440)
        report['events']=[moved];report['actions']=[action(moved)]
        report['review']=make_review(report,rows)
        summary=requirements(report)
        self.assertEqual([(x['code'],x['count']) for x in summary['main']],[(102,1)])
        self.assertEqual(summary['opening'],[])

    def test_opponent_condition_without_movement_and_hidden_information(self):
        report,rows=fixture()
        hidden=card(20,666);hidden.update(controller=1,owner=1)
        for row in rows: row['state']['cards'].append(deepcopy(hidden))
        report['actions'][0].update(kind='effect',selected_effect_text='对方场上有怪兽存在的场合才能发动。')
        review=make_review(report,rows)
        self.assertFalse(review['nodes'][0]['opponent']['visible'])
        self.assertTrue(review['nodes'][1]['opponent']['visible'])
        self.assertFalse(review['nodes'][2]['opponent']['visible'])
        concealed=review['nodes'][1]['state']['cards'][-1]
        self.assertIsNone(concealed['code']);self.assertEqual(concealed['name'],'未知卡牌')

    def test_missing_states_and_legacy_plan_do_not_fabricate_history(self):
        report,_=fixture();report.pop('review')
        before=deepcopy(report);view=legacy_review(report)
        self.assertFalse(view['complete']);self.assertTrue(view['nodes'][0]['state']['partial'])
        self.assertTrue(all(n['state'] is None for n in view['nodes'][1:-1]))
        self.assertEqual(report,before)

    def test_notes_are_checked_against_stable_node_and_instance_ids(self):
        report,_=fixture();edits=empty_annotations()
        edits['nodes']['step:8:0']={'name':'两体叠放','notes':'保留素材'}
        edits['cards']={'4':'本体作用','2':'第二张同名素材'}
        self.assertEqual(annotations_for(report,edits),edits)
        edits['cards']['999']='不属于此路线'
        with self.assertRaisesRegex(ValueError,'实例'):annotations_for(report,edits)

    def test_generic_cost_later_identity_use_and_random_hit_are_separate(self):
        report,rows=fixture()
        c=report['initial_hand'][2]
        cost=event(4,50,[c],origin=c,destination={**c,'location':16},cost={'reason_cost':True})
        starter=report['initial_hand'][0]
        activation=event(4,70,[starter],offset=1)
        a=action(activation,selected_effect_text='①：丢弃1张手卡才能发动。抽1张卡。')
        a['kind']='effect';a['evidence_refs']=[cost['id'],activation['id']]
        report['events']=[cost,activation];report['actions']=[a]
        report['review']=make_review(report,rows)
        summary=requirements(report)
        self.assertEqual({(x['code'],x['count']) for x in summary['opening']},{(101,1),(None,1)})
        self.assertEqual(summary['cost_candidates']['3']['constraint'],'任意手牌')
        later=event(6,70,[{**c,'location':16}]);report['events'].append(later);report['actions'].append(action(later))
        report['review']=make_review(report,rows)
        self.assertFalse(requirements(report)['cost_candidates']['3']['replaceable'])
        edits=empty_annotations();edits['costs']['3']={'mode':'any','constraint':'任意手牌'}
        with self.assertRaisesRegex(ValueError,'不能简化'):requirements(report,edits)
        random_card=card(50,102)
        for row in rows:
            row['state']['cards'].append({**random_card,'location':1 if row['seq']<5 else 2,'sequence':3})
        draw=event(5,90,[random_card],draw_kind='effect')
        played=event(6,70,[random_card],offset=1)
        report['events'] += [draw,played];report['actions'].append(action(played))
        report['review']=make_review(report,rows)
        summary=requirements(report)
        self.assertEqual(summary['random'][0]['instances'],['50'])
        self.assertFalse(any('50' in c['instances'] for c in summary['opening']))

    def test_procedure_conditions_and_opponent_lp_do_not_need_an_opponent_move(self):
        report,rows=fixture()
        report['actions'][0]['kind']='summon'
        report['actions'][0]['cards'][0]['summon_method']='特殊召唤'
        report['catalog']['101']['desc']='对方场上有怪兽而自己没有怪兽的场合，可以特殊召唤。①：其他效果。'
        view=make_review(report,rows)
        self.assertTrue(view['nodes'][1]['opponent']['visible'])
        e=event(4,91,[],player=1,amount=500)
        report['events']=[e];report['actions']=[action(e)]
        view=make_review(report,rows)
        self.assertTrue(view['nodes'][1]['opponent']['visible'])
        self.assertEqual(view['nodes'][1]['opponent']['zones'],[])

    def test_material_transfer_uses_recorded_host_and_missing_identity_stays_unknown(self):
        report,rows=fixture();other=card(5,201,4,1)
        for row in rows:
            row['state']['cards'].append({**other,'location':64 if row['seq']<10 else 4})
            if row['seq']>=10:
                next(c for c in row['state']['cards'] if c['instance_id']==2)['overlay_target']=5
        transfer=event(10,50,[card(2,101,128,1)],offset=1,origin=dict(controller=0,location=132,sequence=0),destination=dict(controller=0,location=132,sequence=1))
        report['events'].append(transfer);report['actions'].append(action(transfer));report['final_state']=deepcopy(rows[-1]['state'])
        view=make_review(report,rows)
        self.assertEqual([c['instance_id'] for c in view['nodes'][-1]['state']['cards'] if c.get('overlay_target')==5],[2])
        report['events'][-1]['cards'][0]['instance_id']=None
        report['review']=make_review(report,rows)
        self.assertTrue(requirements(report)['warnings'])


class ReviewSaveTests(unittest.TestCase):
    setUp=test_expansion.ExpansionStoreTests.setUp
    tearDown=test_expansion.ExpansionStoreTests.tearDown
    begin=test_expansion.ExpansionStoreTests.begin
    completed=test_expansion.ExpansionStoreTests.completed

    def report_ready(self):
        meta=self.completed();report,_=fixture()
        self.projection.update(review=report['review'],events=report['events'],actions=report['actions'],
                               final_state=report['final_state'],catalog=report['catalog'])
        return meta

    def test_preview_has_no_formal_write_and_atomic_save_preserves_every_annotation(self):
        meta=self.report_ready();edits=empty_annotations()
        edits['nodes']['final']={'name':'目标终场','notes':'终场说明'};edits['cards']['4']='本体保留效果'
        body=dict(id=meta['id'],name='二次确认',notes='方案说明',annotations=edits)
        with patch.object(self.store,'report',return_value=self.projection):
            preview=self.store.preview_plan(body)
            self.assertEqual(self.store.list_plans(),[])
            with self.assertRaisesRegex(ValueError,'先核对'):self.store.save_plan(body)
            with patch('app.atomic_json',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):self.store.save_plan({**body,'confirmation':preview['confirmation']})
            self.assertEqual(self.store.list_plans(),[])
            saved=self.store.save_plan({**body,'confirmation':preview['confirmation']})
        self.assertEqual(saved['annotations'],edits)
        self.assertEqual(self.store.save_plan(body),saved) # Lost acknowledgement retry.
        self.assertEqual(Store(self.root).report(meta['id'])['review'],self.projection['review'])
        self.assertEqual(len(self.store.list_plans()),1)
        changed={**body,'name':'响应丢失后返回修改'}
        preview=self.store.preview_plan(changed)
        self.assertTrue(preview['saved'])
        updated=self.store.update_plan({**changed,'original_name':preview['original_name'],'original_notes':preview['original_notes'],
                                       'original_revision':preview['edit_revision'],'confirmation':preview['confirmation']})
        self.assertEqual(updated['name'],'响应丢失后返回修改')
        self.assertEqual(len(self.store.list_plans()),1)

    def test_changed_preview_requires_reconfirmation_and_old_plan_has_recovery_copy(self):
        meta=self.report_ready();body=dict(id=meta['id'],name='确认',notes='',annotations=empty_annotations())
        with patch.object(self.store,'report',return_value=self.projection):
            preview=self.store.preview_plan(body)
            with self.assertRaisesRegex(ValueError,'先核对'):self.store.save_plan({**body,'name':'改变','confirmation':preview['confirmation']})
            saved=self.store.save_plan({**body,'confirmation':preview['confirmation']})
        edit={**body,'original_name':'确认','original_notes':'','original_revision':1}
        edit['annotations']['cards']['4']='新的卡片说明'
        preview=self.store.preview_plan(edit)
        updated=self.store.update_plan({**edit,'confirmation':preview['confirmation']})
        self.assertEqual(updated['edit_revision'],2)
        backup=self.store.plans/'revisions'/meta['id']/'1.json'
        self.assertEqual(read_json(backup),saved)
        self.assertEqual(updated['review'],saved['review'])
        edit['annotations']['cards']['4']='迟到覆盖'
        with self.assertRaisesRegex(ValueError,'其他页面'):self.store.update_plan(edit)

    def test_interruption_and_unfinished_chain_cannot_be_confirmed(self):
        meta=self.report_ready();body=dict(id=meta['id'],name='未完成')
        with patch.object(self.store,'report',return_value=self.projection):
            self.projection['status']='interrupted'
            with self.assertRaisesRegex(ValueError,'完整结束'):self.store.preview_plan(body)
            self.projection['status']='completed';self.projection['final_state']['chain_depth']=1
            with self.assertRaisesRegex(ValueError,'连锁'):self.store.preview_plan(body)


if __name__=='__main__': unittest.main()
