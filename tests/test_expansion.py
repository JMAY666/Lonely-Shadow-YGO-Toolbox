from collections import Counter
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json
from expansion import draw_opening, validate_conditions
import test_store


class OpeningTests(unittest.TestCase):
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

    def begin(self):
        (self.root/'YGOPro.exe').write_bytes(b'synthetic engine')
        self.selected = self.store.save_deck({'name':'源牌组', 'deck':self.deck})
        self.design = {'name':'测试方案','notes':'原备注','revision':self.selected['revision'],
                       'conditions':{'slots':[55144522,None,None,None,None],'banned':[]},'opponent_ai':False}
        self.proc = MagicMock(pid=123)
        self.proc.poll.return_value = None
        with patch('app.subprocess.Popen', return_value=self.proc), patch('app.process_identity', return_value=None):
            result = self.store.start(self.selected['id'], self.design)
        self.path = self.store.session_path(result['id'])
        return read_json(self.path/'session.json')

    def completed(self):
        meta = self.begin()
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
