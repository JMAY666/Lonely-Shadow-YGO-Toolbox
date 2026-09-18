from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
import threading
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trainer'))
from duel_precompute import Precompute
from modular import ModularLibrary


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.deck={'id':'d','revision':'v1','deck':{'main':[1,2],'extra':[],'side':[]},'tag_selection':{'tag_ids':['test']}}
        library=object.__new__(ModularLibrary)
        library.sync=lambda:None
        library.entries={'p':{'version':'p1','status':'ready','tag_ids':['test']}}
        self.modular=SimpleNamespace(store=SimpleNamespace(get_deck=lambda _:deepcopy(self.deck)),
            library=library,sessions={},public_result=deepcopy)
        self.service=Precompute(self.modular);self.service.rules=Mock(return_value='rules1');self.service.ensure_worker=Mock()
        self.body={'consumer':'duel','session':'round1','slot':'opening','deck_id':'d','revision':'v1','hand_count':1,'hand':[1],'sources':['p']}

    def prepare(self,**changes): return self.service.dispatch('plan-prepare',{**self.body,**changes})
    def poll(self,value,**changes): return self.service.dispatch('plan-poll',{**self.body,'job':value['job'],**changes})

    def test_preferences_and_repeated_clicks_join_one_job(self):
        first=self.prepare()
        for preference in ('shortest','largest','balanced','cheapest'):
            self.assertEqual(self.prepare(preference=preference)['job'],first['job'])
        self.assertEqual(len(self.service.jobs),1)
        self.assertEqual(set(first['preferences']),{'shortest','largest','balanced','cheapest'})
        self.service.ensure_worker.assert_called_once()

    def test_changes_cancel_old_tasks_and_prevent_adoption(self):
        for change in ({'hand':[2]},{'sources':['p'],'goal':[2]},{'precise':True}):
            first=self.prepare();second=self.prepare(**change)
            self.assertNotEqual(first['job'],second['job'])
            self.assertTrue(self.service.jobs[first['job']]['cancelled'])
            with self.assertRaises(ValueError): self.service.validate_adoption({**self.body,**first})

    def test_source_rule_and_deck_revisions_invalidate_ready_answers(self):
        for changed in ('source','rules','deck'):
            self.setUp();value=self.prepare();job=self.service.jobs[value['job']]
            job.update(status='ready',sid='sid',data={})
            if changed=='source':self.modular.library.entries['p']['version']='p2'
            elif changed=='rules':self.service.rules.return_value='rules2'
            else:self.deck['revision']='v2'
            self.assertEqual(self.poll(value)['status'],'stale')
            with self.assertRaises(ValueError):self.service.validate_adoption({**self.body,'job':value['job'],'id':'sid','version':value['version']})

    def test_retry_and_capacity_are_explicit_and_bounded(self):
        value=self.prepare();job=self.service.jobs[value['job']];job.update(status='failed',error='timeout')
        self.assertEqual(self.prepare()['status'],'failed')
        retry=self.prepare(refresh=True);self.assertNotEqual(retry['job'],value['job'])
        for n in range(7):self.prepare(session='round'+str(n))
        self.assertLessEqual(sum(not j['cancelled'] for j in self.service.jobs.values()),4)

    def test_adopted_tutorial_is_preserved_when_opening_is_prepared_again(self):
        value=self.prepare();job=self.service.jobs[value['job']];job.update(sid='tutorial',status='ready')
        self.modular.sessions['tutorial']={'forecast_cancelled':False,'confirmed':3}
        self.service.adopted(value['job']);second=self.prepare()
        self.assertNotEqual(second['job'],value['job'])
        self.service.cancel(job)
        self.assertFalse(self.modular.sessions['tutorial']['forecast_cancelled'])
        self.assertEqual(self.modular.sessions['tutorial']['confirmed'],3)

    def test_late_worker_cannot_publish_into_a_new_input_version(self):
        entered, release, replaced = threading.Event(), threading.Event(), threading.Event()
        self.modular.store.closing=False;self.modular.planning_lock=threading.Lock()
        self.service.ensure_worker=lambda:Precompute.ensure_worker(self.service)
        calls=[]
        def generate(modular,body,on_started):
            sid='sid'+str(len(calls));calls.append(sid)
            ctx={'forecast_bank':{p:{'candidates':[],'complete':True} for p in ('shortest','largest','balanced','cheapest')}}
            modular.sessions[sid]=ctx;on_started(sid,ctx)
            if len(calls)==1:entered.set();release.wait(3)
            else:replaced.set()
            return {'id':sid,'inputs':{},'result':{}}
        with patch('duel_planner.generate',side_effect=generate),patch('duel_planner.close') as close:
            try:
                first=self.prepare();self.assertTrue(entered.wait(2))
                second=self.prepare(hand=[2]);old=self.service.jobs[first['job']]
                release.set();self.assertTrue(replaced.wait(3))
                self.assertTrue(old['cancelled']);self.assertIsNone(old['data'])
                self.assertNotEqual(first['version'],second['version'])
                self.assertEqual(len(calls),2)
                self.assertTrue(any(c.args[1]=='sid0' for c in close.call_args_list))
            finally:
                release.set();self.modular.store.closing=True;self.service.worker.join(3)


if __name__=='__main__':unittest.main()
