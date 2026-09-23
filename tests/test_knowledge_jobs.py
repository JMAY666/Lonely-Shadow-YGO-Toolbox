"""Durable queue races with synthetic callbacks; these are not engine acceptance."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from knowledge_jobs import KnowledgeJobs
from knowledge_schema import digest
from knowledge_store import KnowledgeStore


class Owner:
    def __init__(self, root):
        self.fail_write = False
        def read(path): return json.loads(path.read_text(encoding='utf-8'))
        def write(path, value):
            if self.fail_write: raise OSError('injected write failure')
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value),encoding='utf-8');tmp.replace(path)
        self.manager=KnowledgeStore(root,read,write)
        self.version=1;self.title='presentation only';self.shutdown=False
        self.calls=[];self.committed=[];self.gate=None;self.started=threading.Event();self.case_status='passed'

    def verification_snapshot(self, project_id, route_id, build_id, hand, scenario):
        identity=digest([route_id,build_id,hand,scenario,self.version])
        return {'identity':identity,'project_id':project_id,'route_id':route_id,'build_id':build_id,
                'hand':list(hand),'scenario':scenario,'inputs':{'source':str(self.version)},
                'environment':{'synthetic':True},'payload':{'synthetic':True}}

    def current_identity(self,s):
        return self.verification_snapshot(s['project_id'],s['route_id'],s['build_id'],s['hand'],s['scenario'])['identity']

    def verify_case(self,s,limits,cancelled,progress):
        self.calls.append(s['identity']);self.started.set()
        progress({'nodes':1,'phase':'synthetic callback'})
        if self.gate: self.gate.wait(3)  # Intentionally returns late to exercise cancellation guards.
        return {'status':self.case_status,'note':'限定预算内未找到' if self.case_status=='unknown' else 'synthetic result',
                'evidence':{'synthetic':True}}

    def store_verification(self,s,result):
        if self.current_identity(s)!=s['identity']: return False
        self.committed.append((s['project_id'],s['identity'],result['status']));return True

    def closing(self): return self.shutdown


class KnowledgeJobsTests(unittest.TestCase):
    def setUp(self):
        self.base=Path(__file__).resolve().parents[1]/'.local/test-runs'
        self.base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='knowledge-queue-',dir=self.base)
        self.owner=Owner(Path(self.temp.name));self.jobs=KnowledgeJobs(self.owner)
        self.body={'project_id':'project','route_id':'route','build_id':'build',
                   'cases':[{'hand':[100],'scenario':'none'}], 'limits':{'seconds':2,'nodes':10,'depth':8}}

    def tearDown(self):
        self.owner.shutdown=True
        if self.owner.gate:self.owner.gate.set()
        if self.jobs._worker:self.jobs._worker.join(4)
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(self.base.resolve()))
        self.temp.cleanup()

    def terminal(self,jid,service=None):
        service=service or self.jobs;deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            value=service.poll(jid)
            if value['status'] in ('completed','cancelled','stale','failed','paused'): return value
            time.sleep(.01)
        self.fail('job did not reach a terminal state')

    def test_all_scenes_finish_and_repeated_requests_reuse_without_regenerating(self):
        body={**self.body,'cases':[{'hand':[100]},{'hand':[200]}]}
        first=self.jobs.start(body);done=self.terminal(first['id'])
        self.assertEqual(done['status'],'completed');self.assertEqual(done['completed'],2)
        self.assertEqual(len(self.owner.calls),2)
        self.assertEqual(self.jobs.start(body)['id'],first['id']);self.assertEqual(len(self.owner.calls),2)

    def test_changed_dependency_cannot_reuse_a_completed_job_signature(self):
        first=self.jobs.start(self.body);self.terminal(first['id'])
        self.owner.version+=1
        second=self.jobs.start(self.body);self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.terminal(second['id'])['status'],'completed')
        self.assertEqual(len(self.owner.calls),2)
        self.assertEqual(self.jobs.poll(first['id'])['status'],'stale')

    def test_cancelled_late_callback_never_publishes_or_caches_a_pass(self):
        self.owner.gate=threading.Event();job=self.jobs.start(self.body)
        self.assertTrue(self.owner.started.wait(2))
        self.assertEqual(self.jobs.cancel(job['id'])['status'],'cancelled')
        self.owner.gate.set()
        if self.jobs._worker:self.jobs._worker.join(3)
        self.assertEqual(self.owner.committed,[])
        self.assertFalse(list(Path(self.temp.name).glob('validation-cache/*.json')))
        self.assertEqual(self.jobs.poll(job['id'])['status'],'cancelled')

    def test_resume_waits_for_old_epoch_then_restarts_interrupted_scene(self):
        self.owner.gate=threading.Event();job=self.jobs.start(self.body)
        self.assertTrue(self.owner.started.wait(2));self.jobs.cancel(job['id'])
        self.jobs.resume(job['id']);self.owner.gate.set()
        done=self.terminal(job['id']);self.assertEqual(done['status'],'completed')
        self.assertEqual(len(self.owner.calls),2);self.assertEqual(len(self.owner.committed),1)

    def test_cache_reuses_semantics_for_another_editable_project_and_refresh_rechecks(self):
        first=self.jobs.start(self.body);self.terminal(first['id'])
        second=self.jobs.start({**self.body,'project_id':'another-project'})
        done=self.terminal(second['id']);self.assertEqual(done['reused'],1);self.assertEqual(len(self.owner.calls),1)
        third=self.jobs.start({**self.body,'refresh':True});self.terminal(third['id'])
        self.assertEqual(len(self.owner.calls),2)

    def test_budget_unknown_is_preserved_and_not_cached_as_impossible(self):
        self.owner.case_status='unknown';job=self.jobs.start(self.body);done=self.terminal(job['id'])
        self.assertEqual(done['cases'][0]['note'],'限定预算内未找到')
        self.assertEqual(self.owner.committed[0][2],'unknown')
        self.assertFalse(list(Path(self.temp.name).glob('validation-cache/*.json')))

    def test_restart_pauses_unfinished_jobs_without_starting_the_engine(self):
        with patch.object(self.jobs,'_spawn'):
            job=self.jobs.start(self.body)
        restarted=KnowledgeJobs(self.owner)
        self.assertEqual(restarted.list()['jobs'][0]['status'],'paused');self.assertEqual(self.owner.calls,[])
        restarted.resume(job['id'])
        self.assertEqual(self.terminal(job['id'],restarted)['status'],'completed')
        if restarted._worker:restarted._worker.join(3)

    def test_disk_failure_before_queueing_runs_no_callback(self):
        self.owner.fail_write=True
        with self.assertRaises(OSError):self.jobs.start(self.body)
        self.assertEqual(self.owner.calls,[]);self.assertEqual(self.owner.committed,[])

    def test_corrupt_cache_is_not_reused_and_corrupt_jobs_are_reported(self):
        job=self.jobs.start(self.body);self.terminal(job['id'])
        path=next(Path(self.temp.name).glob('validation-cache/*.json'))
        value=json.loads(path.read_text());value['digest']='bad';path.write_text(json.dumps(value))
        newer=self.jobs.start({**self.body,'project_id':'different'});self.terminal(newer['id'])
        self.assertEqual(len(self.owner.calls),2)
        bad='a'*32;self.owner.manager._write_json('jobs/'+bad+'.json',{'id':bad,'cases':[]})
        restarted=KnowledgeJobs(self.owner)
        self.assertTrue(any(row['id']==bad for row in restarted.list()['errors']))

    def test_invalid_limits_and_unbounded_scenes_rejected(self):
        for limits in ({'nodes':True},{'seconds':float('nan')},{'depth':129},{'nodes':321},{'seconds':0}):
            with self.subTest(limits=limits),self.assertRaises(ValueError):self.jobs.start({**self.body,'limits':limits})
        with self.assertRaises(ValueError):self.jobs.start({**self.body,'cases':[{'hand':[100],'scenario':'all-game'}]})
        with self.assertRaises(ValueError):self.jobs.start({**self.body,'cases':[{'hand':[100]}]*9})

    def test_edit_during_verification_invalidates_only_dependent_jobs(self):
        self.owner.gate=threading.Event();job=self.jobs.start(self.body)
        self.assertTrue(self.owner.started.wait(2));self.owner.version+=1
        self.jobs.invalidate('project');self.owner.gate.set()
        if self.jobs._worker:self.jobs._worker.join(3)
        self.assertEqual(self.jobs.poll(job['id'])['status'],'stale');self.assertEqual(self.owner.committed,[])

    def test_progress_persistence_failure_stops_publication(self):
        entered=threading.Event()
        def verify(snapshot,limits,cancelled,progress):
            self.owner.fail_write=True;progress({'phase':'failure injection'});entered.set()
            return {'status':'passed','note':'must not publish','evidence':{}}
        self.owner.verify_case=verify
        job=self.jobs.start(self.body);self.assertTrue(entered.wait(2))
        if self.jobs._worker:self.jobs._worker.join(3)
        self.assertEqual(self.jobs.poll(job['id'])['status'],'failed');self.assertEqual(self.owner.committed,[])
        self.owner.fail_write=False


if __name__=='__main__':unittest.main()
