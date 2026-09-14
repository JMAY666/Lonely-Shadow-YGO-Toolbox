from copy import deepcopy
import json
import sys
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json
from plan_tags import suggest, matches_set, used_codes, edit_tag, validate_selection, contains_card, edit_members, member_ids
from plan_sharing import portable, validate
from card_semantics import card_activation
from actions import project_actions
import test_store


def sample():
    first = dict(code=101, instance_id=1, controller=0, location=4, sequence=0, position=1, name='系列甲 A')
    second = {**first, 'code': 102, 'instance_id': 2, 'name': '系列甲 B'}
    events = [dict(id=f'{i}:0', native_seq=i, message=61, cards=[card], type='通常召唤', time_ms=i)
              for i, card in enumerate((first, second), 1)]
    actions = [dict(id=e['id'], kind='summon', cards=e['cards'], evidence_refs=[e['id']], summary='通常召唤') for e in events]
    return dict(id=str(uuid.uuid4()), name='分享验收', deck_name='测试构筑', saved_ms=1, edit_revision=1, plan_stage='saved',
                selected_deck='private/source.ydk', pid=123, process_identity={'path':'PRIVATE_PATH'}, sources=[{'path':'PRIVATE_SOURCE'}],
                deck=dict(main=[101]*20+[102]*20, extra=[], side=[]),
                catalog={str(c):dict(id=c, name=f'系列甲 {c}', desc='合成卡牌资料', type=1, setcode=0x119, source='PRIVATE_CDB') for c in (101, 102)},
                expansion=dict(name='分享验收', notes='备注', conditions=dict(hand_count=1, slots=[101], banned=[])),
                actions=actions, events=events, initial_hand=[first], final_state=dict(cards=[first, second], lp=[8000,8000]),
                started_ms=1, duration_ms=1, status='completed', end_reason='manual', loaded_verified=True,
                warnings=[], limitations=[], statistics={}, annotations=dict(nodes={}, cards={}, effects={}, final_marks={}))


class TagTests(unittest.TestCase):
    def tags(self):
        return {'set:119': {'id':'set:119','name':'转生炎兽','aliases':['Salamangreat'],'setcode':0x119},
                'set:120': {'id':'set:120','name':'其他系列','aliases':[],'setcode':0x120}}

    def test_concentration_counts_distinct_used_own_cards_and_one_primary(self):
        plan=sample();before=deepcopy(plan)
        repeated=deepcopy(plan['actions'][0]);repeated['id']='9:0';plan['actions'].append(repeated)
        opponent={'id':'10:0','kind':'effect','cards':[dict(code=202,controller=1)],'evidence_refs':[]}
        plan['actions'].append(opponent)
        draw={'id':'11:0','kind':'action','cards':[dict(code=203,controller=0)],'evidence_refs':['11:0']}
        plan['events'].append(dict(id='11:0',message=90,cards=draw['cards']));plan['actions'].append(draw)
        self.assertEqual(used_codes(plan),{101,102})
        result=suggest(plan,self.tags(),{})
        self.assertEqual(result['tag_ids'],['set:119']);self.assertEqual(result['primary_ids'],['set:119'])
        self.assertEqual(result['candidates'][0]['ratio'],1)
        self.assertEqual(plan['deck'],before['deck'])
        plan['catalog']['102']['setcode']=0x120
        self.assertEqual(suggest(plan,self.tags(),{})['tag_ids'],[])

    def test_low_concentration_and_ties_are_deterministic(self):
        plan=sample()
        for code in range(103,113):
            plan['actions'].append(dict(id=f'{code}:0',kind='summon',cards=[dict(code=code,controller=0)],evidence_refs=[]))
        self.assertEqual(suggest(plan,self.tags(),{})['tag_ids'],[])
        plan['actions']=plan['actions'][:4]
        for code in (103,104): plan['catalog'][str(code)]={'setcode':0x120}
        result=suggest(plan,self.tags(),{})
        self.assertEqual(set(result['tag_ids']),set(self.tags()));self.assertEqual(len(result['primary_ids']),1)
        self.assertEqual(result,suggest(plan,self.tags(),{}))

    def test_packed_signed_setcodes_and_subseries(self):
        self.assertTrue(matches_set(0x119 | (0x3008<<16),0x119))
        self.assertTrue(matches_set(0x3008,0x8))
        self.assertTrue(matches_set(0x3008,0x3008))
        self.assertFalse(matches_set(0x3008,0x5008))
        self.assertFalse(matches_set(0x119,0x19))
        self.assertTrue(matches_set((0xa008<<48)-(1<<64),0xa008))

    def test_aliases_are_normalized_and_manual_multiple_primary_is_valid(self):
        tags=self.tags()
        edited=edit_tag(dict(id='set:119',name='转生炎兽',aliases=['沙拉','SALAMANGREAT','ｓａｌａｍａｎｇｒｅａｔ']),tags)
        self.assertEqual(edited['aliases'],['沙拉','SALAMANGREAT'])
        with self.assertRaises(ValueError):edit_tag(dict(name='新标签',aliases=['salamangreat']),tags)
        chosen=validate_selection(dict(tag_ids=list(tags),primary_ids=list(tags)),tags)
        self.assertEqual(len(chosen['primary_ids']),2)
        with self.assertRaises(ValueError):validate_selection(dict(tag_ids=[],primary_ids=['set:119']),tags)

    def test_membership_overrides_include_remove_and_keep_future_base_cards(self):
        catalog={1:{'setcode':0x119},2:{'setcode':0x119},3:{'setcode':0}}
        tag=edit_members(self.tags()['set:119'],[1,3],catalog)
        self.assertEqual(tag['include_cards'],[3]);self.assertEqual(tag['exclude_cards'],[2])
        self.assertEqual(member_ids(tag,catalog),[1,3]);self.assertFalse(contains_card(tag,2,catalog[2]))
        catalog[4]={'setcode':0x119};self.assertEqual(member_ids(tag,catalog),[1,3,4])
        with self.assertRaises(ValueError):edit_members(tag,[999],catalog)

    def test_custom_membership_participates_in_concentration_and_manual_tags_stay(self):
        plan=sample();tag={'id':'custom:'+'a'*32,'name':'自定义系列','aliases':[],'setcode':None,'include_cards':[101,102]}
        result=suggest(plan,{tag['id']:tag},{})
        self.assertEqual(result['primary_ids'],[tag['id']]);tag['exclude_cards']=[102]
        self.assertEqual(suggest(plan,{tag['id']:tag},{})['tag_ids'],[])


class LibraryStoreTests(unittest.TestCase):
    setUp=test_store.StoreTests.setUp
    tearDown=test_store.StoreTests.tearDown

    def saved(self):
        plan=sample();atomic_json(self.store.plan_path(plan['id']),plan);return plan

    def test_old_plan_read_is_nonmutating_manual_removal_survives_reopen_and_backup(self):
        plan=self.saved();path=self.store.plan_path(plan['id']);before=path.read_bytes()
        self.assertEqual(self.store.list_plans()[0]['tags'][0]['name'],'转生炎兽')
        self.assertEqual(path.read_bytes(),before)
        result=self.store.library.save_selection(dict(id=plan['id'],revision=1,classification=dict(tag_ids=[],primary_ids=[])))
        self.assertEqual(result['classification']['tag_ids'],[])
        self.assertEqual(Store(self.root).list_plans()[0]['tags'],[])
        self.assertEqual((self.store.plans/'revisions'/plan['id']/'1.json').read_bytes(),before)
        with self.assertRaises(ValueError):self.store.library.save_selection(dict(id=plan['id'],revision=1,automatic=True))
        auto=self.store.library.save_selection(dict(id=plan['id'],revision=2,automatic=True))
        self.assertEqual(auto['classification']['primary_ids'],['set:119'])
        self.assertEqual(auto['events'],plan['events'])

    def test_definition_persists_aliases_and_preserves_official_metadata(self):
        tag=self.store.library.edit_tag(dict(id='set:119',name='转生炎兽',aliases=['沙拉','轉生炎獸'],revision=0))['tag']
        self.assertEqual(tag['official_name'],'转生炎兽')
        self.assertIn('沙拉',Store(self.root).library.all_tags()['set:119']['aliases'])
        with self.assertRaises(ValueError):self.store.library.edit_tag(dict(name='另一个',revision=0))

    def test_tag_card_editor_roundtrip_preserves_alias_only_edits_and_backups(self):
        created=self.store.library.edit_tag(dict(name='卡牌范围验收',aliases=['别称'],card_ids=[55144522,1184620],revision=0))
        key=created['tag']['id'];self.assertEqual(set(c['id'] for c in self.store.library.members(key)['cards']),{55144522,1184620})
        changed=self.store.library.edit_tag(dict(id=key,name='新名字',aliases=['别称'],card_ids=[1184620],revision=1))
        self.assertEqual(changed['tag']['include_cards'],[1184620])
        self.store.library.edit_tag(dict(id=key,name='新名字',aliases=['更多叫法'],revision=2))
        reopened=Store(self.root);self.assertEqual([c['id'] for c in reopened.library.members(key)['cards']],[1184620])
        self.assertTrue((self.store.root/'backups/tags/1.json').exists())
        with self.assertRaises(ValueError):reopened.library.edit_tag(dict(id=key,name='错误',card_ids=[999],revision=3))

    def test_new_shared_custom_tag_carries_membership_without_overwriting_local_members(self):
        plan=self.saved();created=self.store.library.edit_tag(dict(name='分享卡牌范围',card_ids=[55144522,1184620],revision=0))
        key=created['tag']['id'];self.store.library.save_selection(dict(id=plan['id'],revision=1,classification=dict(tag_ids=[key],primary_ids=[key])))
        document=self.store.library.export(plan['id']);self.assertEqual(document['tags'][0]['include_cards'],[1184620,55144522])
        document['tags'][0]['include_cards']=[23995346]
        preview=self.store.library.import_document({'document':document},preview=True)
        self.assertTrue(any('卡牌范围不同' in n for n in preview['notes']))
        self.store.library.import_document(dict(document=document,fingerprint=preview['fingerprint']))
        self.assertEqual(self.store.library.all_tags()[key]['include_cards'],[1184620,55144522])

    def test_export_import_roundtrip_omits_machine_data_and_preserves_frozen_facts(self):
        plan=self.saved();before=self.store.plan_path(plan['id']).read_bytes()
        exported=self.store.library.export(plan['id'])
        encoded=json.dumps(exported)
        self.assertNotIn('PRIVATE',encoded);self.assertNotIn('private/source.ydk',encoded);self.assertNotIn('process_identity',encoded)
        preview=self.store.library.import_document({'document':exported},preview=True)
        self.assertEqual(len(self.store.list_plans()),1)
        imported=self.store.library.import_document(dict(document=exported,fingerprint=preview['fingerprint']))
        self.assertNotEqual(imported['id'],plan['id'])
        result=read_json(self.store.plan_path(imported['id']))
        for field in ('deck','events','actions','final_state','annotations'): self.assertEqual(result[field],plan[field])
        self.assertEqual(self.store.plan_path(plan['id']).read_bytes(),before)
        repeat=self.store.library.import_document(dict(document=exported,fingerprint=preview['fingerprint']))
        self.assertTrue(repeat['duplicate']);self.assertEqual(repeat['id'],imported['id'])
        self.assertEqual(self.store.design_from(imported['id'])['deck'],plan['deck'])
        self.assertEqual(len(self.store.list_plans()),2)

    def test_import_validation_and_preview_fingerprint_prevent_partial_plans(self):
        exported=self.store.library.export(self.saved()['id'])
        for mutate in [lambda d:d.update(version=99),lambda d:d['plan']['deck']['main'].append('bad'),
                       lambda d:d['plan']['events'][0].update(id='"><script>'),
                       lambda d:d['plan'].update(annotations=[]),lambda d:d['plan'].update(__proto__={}),
                       lambda d:d['plan']['actions'][0].update(costs=[None]),
                       lambda d:d['plan']['final_state'].update(lp=['<img>',8000]),
                       lambda d:d['plan'].update(requirements={'extra':[{'count':'<img>'}]}),
                       lambda d:d['plan']['actions'][0].update(execution=[{}])]:
            invalid=deepcopy(exported);mutate(invalid)
            with self.assertRaises(ValueError):self.store.library.import_document({'document':invalid},preview=True)
        with self.assertRaises(ValueError):self.store.library.import_document(dict(document=exported,fingerprint='stale'))
        self.assertEqual(len(self.store.list_plans()),1)

    def test_alias_conflict_does_not_reassign_existing_tags(self):
        plan=self.saved();document=self.store.library.export(plan['id'])
        other=self.store.library.edit_tag(dict(name='别的系列',aliases=['冲突叫法'],revision=0))['tag']
        document['tags'][0]['aliases'].append('冲突叫法')
        preview=self.store.library.import_document({'document':document},preview=True)
        self.assertTrue(preview['notes'])
        self.store.library.import_document(dict(document=document,fingerprint=preview['fingerprint']))
        self.assertNotIn('冲突叫法',self.store.library.all_tags()['set:119']['aliases'])
        self.assertIn('冲突叫法',self.store.library.all_tags()[other['id']]['aliases'])

    def test_large_packed_series_identity_survives_browser_json_exchange(self):
        plan=self.saved();packed=(0xa008<<48)|0x119
        plan['catalog']['101']['setcode']=packed;atomic_json(self.store.plan_path(plan['id']),plan)
        exported=self.store.library.export(plan['id'])
        self.assertEqual(exported['plan']['catalog']['101']['setcode'],str(packed))
        parsed=json.loads(json.dumps(exported));preview=self.store.library.import_document({'document':parsed},preview=True)
        imported=self.store.library.import_document(dict(document=parsed,fingerprint=preview['fingerprint']))
        card=read_json(self.store.plan_path(imported['id']))['catalog']['101']
        self.assertEqual(int(card['setcode']),packed);self.assertTrue(matches_set(card['setcode'],0xa008))

    def test_scalar_opponent_context_lp_and_player_pair_lp_both_roundtrip(self):
        plan=self.saved();plan['review']={'nodes':[
            {'id':'initial','kind':'initial','number':1,'action_ids':[],'state':plan['final_state']},
            {'id':'final','kind':'final','number':2,'action_ids':[], 'state':plan['final_state'],
             'opponent':{'before':{'lp':8000,'cards':[]}}}]}
        atomic_json(self.store.plan_path(plan['id']),plan)
        exported=self.store.library.export(plan['id'])
        self.assertEqual(exported['plan']['review']['nodes'][1]['opponent']['before']['lp'],8000)

    def test_disk_failure_keeps_saved_plan_and_manual_classification(self):
        plan=self.saved();target=self.store.plan_path(plan['id']);before=target.read_bytes()
        with patch.object(self.store.library,'write',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):self.store.library.save_selection(dict(id=plan['id'],revision=1,automatic=True))
        self.assertEqual(target.read_bytes(),before)


class ActivationTests(unittest.TestCase):
    def test_card_activation_is_distinct_from_a_field_cards_triggered_effect(self):
        plan=sample();card=dict(code=1295111,name='转生炎兽的圣域',controller=0,location=8,sequence=5)
        plan['catalog']['1295111']={'type':0x80002,'desc':'①：持续适用。②：可以发动。'}
        for native,label in ((0x1a,'发动场地魔法卡'),(0x82,None)):
            action=dict(cards=[card],engine_effect={'effect_type':native})
            self.assertEqual(card_activation(action,plan['catalog']),label)
        plan['events']=[dict(id='1:0',native_seq=1,time_ms=1,message=70,cards=[card],chain=1,engine_effect={'effect_type':0x1a}),
                        dict(id='2:0',native_seq=2,time_ms=2,message=73,cards=[],chain=1)]
        action=project_actions(plan)[0]
        self.assertEqual(action['summary'],'发动场地魔法卡－转生炎兽的圣域')
        self.assertIsNone(action['status_label'])
