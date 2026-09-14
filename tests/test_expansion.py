from collections import Counter
import json
from pathlib import Path
import random
import sys
import unittest
import uuid
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json
from expansion import draw_opening, validate_conditions, training_settings, MAX_LP
import test_store


class OpeningTests(unittest.TestCase):
    def test_actual_counts_partial_full_and_bans_apply_to_single_card(self):
        main = [1]*3 + [2]*32 + [3]*5
        for count in (1, 2, 3, 5, 40):
            for assigned in (0, min(count, 2)):
                conditions = {'hand_count': count, 'slots': [1]*assigned+[None]*(count-assigned), 'banned': []}
                hand, rest = draw_opening(main, conditions, random.Random(6))
                self.assertEqual(len(hand), count)
                self.assertEqual(Counter(hand+rest), Counter(main))
                self.assertGreaterEqual(hand.count(1), assigned)
        hand, rest = draw_opening(main, {'hand_count': 1, 'slots': [None], 'banned': [1, 2]})
        self.assertEqual(hand, [3])
        self.assertEqual(Counter(rest)[1], 3)
        with self.assertRaisesRegex(ValueError, '同时被指定和禁用'):
            draw_opening(main, {'hand_count':1, 'slots':[1], 'banned':[1]})

    def test_invalid_count_overflow_removed_card_and_insufficient_pool_are_rejected(self):
        for count in (0, -1, 1.5, None, True, '2', 61):
            with self.assertRaisesRegex(ValueError, '起手数量'):
                validate_conditions([1]*40, {'hand_count': count, 'slots': [None], 'banned': []})
        for conditions, message in [
            ({'hand_count':41,'slots':[],'banned':[]}, '主卡组只有 40 张'),
            ({'hand_count':1,'slots':[None,1],'banned':[]}, '超出数量'),
            ({'hand_count':1,'slots':[2],'banned':[]}, '当前主卡组'),
            ({'hand_count':1,'slots':[None],'banned':[1]}, '只剩 0 张.*需要 1 张'),
        ]:
            with self.assertRaisesRegex(ValueError, message): validate_conditions([1]*40, conditions)

    def test_settings_defaults_and_engine_limits(self):
        self.assertEqual(training_settings({}), {'opponent_ai':False,'opponent_responses':True,
            'turn_order':'first','player_lp':8000,'opponent_lp':8000,'timer':{'mode':'off','seconds':0}})
        for field in ('player_lp', 'opponent_lp'):
            for value in (0, MAX_LP+1, None, True, 0.5, '8000'):
                with self.assertRaises(ValueError): training_settings({field:value})
        self.assertEqual(training_settings({'player_lp':MAX_LP,'opponent_lp':1})['player_lp'], MAX_LP)
        for config in ({'opponent_responses':1},{'turn_order':'random'},{'timer':{'mode':'both'}},
                       {'timer':{'mode':'down','seconds':0}}, {'timer':{'mode':'up','seconds':-1}}):
            with self.assertRaises(ValueError): training_settings(config)

    def test_copy_limits_conflict_and_only_main_deck(self):
        for conditions in (
            {'slots': [1, 1, 1, None, None], 'banned': []},
            {'slots': [1, None, None, None, None], 'banned': [1]},
            {'slots': [None] * 5, 'banned': [3]},
            {'slots': [True, None, None, None, None], 'banned': []},
            {'slots': [None] * 5, 'banned': [None]},
        ):
            with self.assertRaises(ValueError): validate_conditions([1]*2+[2]*38, conditions)

    def test_specified_means_at_least_and_sampling_keeps_every_copy(self):
        main = [1]*3+[2]*37
        observed = set()
        for seed in range(500):
            hand, rest = draw_opening(main, {'slots': [1,None,None,None,None], 'banned': []}, random.Random(seed))
            observed.add(hand.count(1))
            self.assertEqual(Counter(hand+rest), Counter(main))
            self.assertEqual(len(hand), 5)
        self.assertEqual(observed, {1,2,3})
        for seed in range(100):
            hand, _ = draw_opening([1]*2+[2]*38, {'slots':[None]*5,'banned':[]}, random.Random(seed))
            self.assertLessEqual(hand.count(1), 2)

    def test_bans_only_affect_opening_and_insufficient_pool_is_explained(self):
        main = [1]*3+[2]*37
        hand, rest = draw_opening(main, {'slots':[None]*5, 'banned':[1]})
        self.assertNotIn(1, hand)
        self.assertEqual(rest.count(1), 3)
        self.assertEqual(Counter(hand+rest), Counter(main))
        with self.assertRaisesRegex(ValueError, '只剩 3 张.*需要 5 张'):
            draw_opening(main, {'slots':[None]*5, 'banned':[2]})


class ExpansionStoreTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def begin(self, changes=None):
        (self.root/'YGOPro.exe').write_bytes(b'synthetic engine')
        self.selected = self.store.save_deck({'name':'源牌组', 'deck':self.deck})
        self.design = {'name':'测试方案','notes':'原备注','revision':self.selected['revision'],
                       'conditions':{'slots':[55144522,None,None,None,None],'banned':[]},'opponent_ai':False}
        self.design.update(changes or {})
        self.proc = MagicMock(pid=123)
        self.proc.poll.return_value = None
        with patch('app.subprocess.Popen', return_value=self.proc), patch('app.process_identity', return_value=None):
            result = self.store.start(self.selected['id'], self.design)
        self.path = self.store.session_path(result['id'])
        return read_json(self.path/'session.json')

    def completed(self, changes=None):
        meta = self.begin(changes)
        self.proc.poll.return_value = 0
        meta.update(status='completed',plan_stage='draft',ended_ms=2)
        atomic_json(self.path/'session.json',meta)
        self.projection = {**meta,'initial_hand':[{'code':code} for code in meta['expansion']['actual_opening']],
                           'final_state':{'lp':[8000,8000],'cards':[]},'loaded_verified':True,'events':[],'actions':[]}
        return meta

    def test_blank_and_stale_design_cannot_launch_or_create_a_record(self):
        self.selected = self.store.save_deck({'name':'起手校验','deck':self.deck})
        for name, revision in [('  ',self.selected['revision']),('有名','stale')]:
            with self.assertRaises(ValueError): self.store.start(self.selected['id'], {'name':name,'revision':revision})
        self.assertEqual(list(self.store.sessions.iterdir()), [])

    def test_custom_opponent_config_roundtrip_and_native_opening_count(self):
        config={'id':'custom','name':'自定义对手','deck':self.deck,
                'conditions':{'hand_count':2,'slots':[1184620,None],'banned':[]}}
        meta=self.begin({'conditions':{'hand_count':1,'slots':[55144522],'banned':[1184620]},
                         'opponent_ai':True,'opponent_responses':False,'opponent_config':config,
                         'turn_order':'second','player_lp':1234,'opponent_lp':MAX_LP,'timer':{'mode':'down','seconds':60}})
        self.assertEqual(meta['expansion']['actual_opening'],[55144522])
        opponent=meta['expansion']['opponent_config']
        self.assertEqual(len(opponent['actual_opening']),2)
        self.assertEqual(Counter(opponent['draw_order']),Counter(self.deck['main']))
        values=list(map(int,(self.path/'opening.cfg').read_text().split()))
        self.assertEqual(values[:2],[2,1])
        self.assertEqual(values[44:51],[1,0,1,1234,MAX_LP,2,40])
        self.assertEqual(self.store.parse_deck((self.path/'opponent.ydk').read_bytes()),self.deck)
        self.proc.poll.return_value=0
        with patch.object(self.store, 'report', return_value=meta): restored=self.store.return_to_design(meta['id'])
        self.assertEqual(restored['opponent_config'],opponent)
        self.assertEqual(restored['timer'],{'mode':'down','seconds':60})
        self.assertEqual(read_json(self.path/'session.json')['plan_stage'],'abandoned')
        # A saved source may have changed or been removed; the returned design owns its snapshot.
        self.store.delete_deck(self.store.get_deck(self.selected['id']))
        replacement=MagicMock(pid=124);replacement.poll.return_value=None
        restored['conditions']={'hand_count':3,'slots':[1184620,None,None],'banned':[]}
        with patch('app.subprocess.Popen',return_value=replacement),patch('app.process_identity',return_value=None):
            new=self.store.start(restored['id'],restored)
        fresh=read_json(self.store.session_path(new['id'])/'session.json')
        self.assertNotEqual(new['id'],meta['id'])
        self.assertEqual(len(fresh['expansion']['actual_opening']),3)

    def test_discard_keeps_journal_and_source_and_cannot_save_again(self):
        meta=self.completed()
        (self.path/'native.jsonl').write_text('immutable evidence')
        self.store.discard_draft({'id':meta['id']})
        self.assertEqual((self.path/'native.jsonl').read_text(),'immutable evidence')
        self.assertEqual(self.store.get_deck(self.selected['id'])['deck'],self.deck)
        self.assertEqual(self.store.history()[0]['plan_stage'],'abandoned')
        with self.assertRaises(ValueError):self.store.save_plan({'id':meta['id'],'name':'late'})

    def test_saved_edit_failure_and_scoped_delete_keep_independent_records(self):
        meta=self.completed()
        with patch.object(self.store,'report',return_value=self.projection):
            saved=self.store.save_plan({'id':meta['id'],'name':'正式','notes':'原文'})
        raw=(self.path/'session.json').read_bytes()
        body={'id':meta['id'],'original_name':'正式','original_notes':'原文','name':'修改','notes':'新文'}
        with patch('app.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.store.update_plan(body)
        self.assertEqual(read_json(self.store.plan_path(meta['id'])),saved)
        changed=self.store.update_plan(body)
        self.assertEqual(changed['name'],'修改')
        self.assertEqual(changed['deck'],saved['deck'])
        self.assertEqual(changed['expansion']['conditions'],saved['expansion']['conditions'])
        self.assertEqual((self.path/'session.json').read_bytes(),raw)
        with self.assertRaises(ValueError):self.store.update_plan({**body,'name':'stale'})
        with patch('pathlib.Path.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):self.store.delete_plan({'id':meta['id'],'name':'修改'})
        self.assertEqual(read_json(self.store.plan_path(meta['id'])),changed)
        other_id=str(uuid.uuid4())
        other_path=self.store.plan_path(other_id)
        atomic_json(other_path,{**saved,'id':other_id,'name':'其他方案'})
        other=other_path.read_bytes()
        self.store.delete_plan({'id':meta['id'],'name':'修改'})
        self.assertEqual(other_path.read_bytes(),other)
        self.assertEqual((self.path/'session.json').read_bytes(),raw)

    def test_saved_settings_reopen_and_legacy_defaults_need_no_migration(self):
        changes={'conditions':{'hand_count':3,'slots':[1184620,None,None],'banned':[55144522]},
                 'opponent_ai':True,'opponent_responses':False,'turn_order':'second','player_lp':2500,'opponent_lp':9000,
                 'timer':{'mode':'up','seconds':31},'opponent_config':{'name':'自定义','deck':self.deck,
                     'conditions':{'hand_count':1,'slots':[1184620],'banned':[]}}}
        meta=self.completed(changes)
        with patch.object(self.store,'report',return_value=self.projection):
            saved=self.store.save_plan({'id':meta['id'],'name':'持久化设置','notes':'新文字'})
        reopened=Store(self.root)
        restored=reopened.design_from(meta['id'])
        for key in changes:
            self.assertEqual(restored[key],saved['expansion'][key])
        legacy_id=str(uuid.uuid4())
        legacy=json.loads(json.dumps(saved))
        legacy['id']=legacy_id
        for key in ('opponent_responses','turn_order','player_lp','opponent_lp','timer'):
            legacy['expansion'].pop(key)
        legacy['expansion'].update(opponent_ai=False,opponent_config=None,conditions={'slots':[None]*5,'banned':[]})
        atomic_json(reopened.plan_path(legacy_id),legacy)
        before=reopened.plan_path(legacy_id).read_bytes()
        restored=reopened.design_from(legacy_id)
        self.assertEqual(restored['conditions']['hand_count'],5)
        self.assertEqual(restored['player_lp'],8000)
        self.assertEqual(restored['turn_order'],'first')
        self.assertEqual(restored['timer'],{'mode':'off','seconds':0})
        self.assertEqual(reopened.plan_path(legacy_id).read_bytes(),before)

    def test_restart_uses_frozen_source_seed_opening_and_new_journal(self):
        meta = self.begin()
        (self.path/'native.jsonl').write_text('old attempt', encoding='utf8')
        self.store.save_deck({**self.selected, 'deck':{'main':[1184620]*40,'extra':[],'side':[]}})
        self.proc.poll.return_value = 0
        replacement = MagicMock(pid=124); replacement.poll.return_value = None
        with patch('app.subprocess.Popen',return_value=replacement), patch('app.process_identity',return_value=None):
            result = self.store.restart(meta['id'])
        retry = read_json(self.store.session_path(result['id'])/'session.json')
        self.assertEqual(retry['deck'], meta['deck'])
        self.assertEqual(retry['expansion'], meta['expansion'])
        self.assertEqual(retry['catalog'],meta['catalog'])
        self.assertNotEqual(retry['id'],meta['id'])
        self.assertFalse((self.store.session_path(result['id'])/'native.jsonl').exists())
        self.assertEqual((self.path/'native.jsonl').read_text(), 'old attempt')
        self.assertEqual(read_json(self.path/'session.json')['plan_stage'],'discarded')
        self.assertEqual(self.store.restart(meta['id'])['id'],result['id'])
        self.assertEqual(self.store.list_plans(),[])

    def test_save_is_idempotent_failure_retains_draft_and_restart_keeps_snapshot(self):
        meta = self.completed()
        body={'id':meta['id'],'name':'正式方案','notes':'新备注'}
        with patch.object(self.store,'report',return_value=self.projection), patch('app.atomic_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.save_plan(body)
        self.assertEqual(read_json(self.path/'session.json')['plan_stage'],'draft')
        self.assertEqual(self.store.list_plans(),[])
        with patch.object(self.store,'report',return_value=self.projection):
            saved=self.store.save_plan(body)
            self.assertEqual(saved,self.store.save_plan({**body,'name':'duplicate click'}))
        self.store.save_deck({**self.selected, 'deck':{'main':[1184620]*40,'extra':[],'side':[]}})
        reopened=Store(self.root)
        self.assertEqual(read_json(reopened.plan_path(meta['id'])),saved)
        self.assertEqual(saved['deck'],self.deck)
        self.assertEqual(saved['expansion']['notes'],'新备注')
        self.assertEqual(len(reopened.list_plans()),1)

    def test_delete_is_scoped_and_late_save_cannot_recreate_plan(self):
        meta=self.completed()
        with patch.object(self.store,'report',return_value=self.projection):
            saved=self.store.save_plan({'id':meta['id'],'name':'可删除','notes':''})
        before=(self.path/'session.json').read_bytes()
        with self.assertRaises(ValueError): self.store.delete_plan({'id':meta['id'],'name':'另一个方案'})
        self.store.delete_plan({'id':meta['id'],'name':saved['name']})
        self.assertEqual(self.store.list_plans(),[])
        self.assertEqual((self.path/'session.json').read_bytes(),before)
        self.assertEqual(self.store.get_deck(self.selected['id'])['deck'],self.deck)
        with self.assertRaisesRegex(ValueError,'已删除'): self.store.save_plan({'id':meta['id'],'name':'late','notes':''})

    def test_recording_or_incorrect_real_opening_cannot_be_saved(self):
        meta=self.begin()
        with self.assertRaisesRegex(ValueError,'先结束'): self.store.save_plan({'id':meta['id'],'name':'early'})
        self.proc.poll.return_value=0
        meta.update(status='completed',plan_stage='draft');atomic_json(self.path/'session.json',meta)
        with patch.object(self.store,'report',return_value={'initial_hand':[{'code':0}]*5,'final_state':{'cards':[]},'loaded_verified':True}):
            with self.assertRaisesRegex(ValueError,'实际发牌'): self.store.save_plan({'id':meta['id'],'name':'wrong'})


if __name__=='__main__': unittest.main()
