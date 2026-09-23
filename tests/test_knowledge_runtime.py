"""Capability boundaries for package declarations and private verification sessions."""
from copy import deepcopy
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trainer'))
from knowledge_runtime import native_plan, native_binding
from knowledge_sample import sample_document
from knowledge_schema import inputs_for
from modular import Modular
from planning_preferences import DEFAULT_PREFERENCE


class KnowledgeRuntimeTests(unittest.TestCase):
    def test_publisher_engine_claim_cannot_make_text_steps_executable(self):
        doc=sample_document()
        doc['checks']=[{'id':'publisher-claim','type':'engine','target':'route-1','inputs':inputs_for(doc,'route-1'),
                       'status':'passed','note':'claimed pass','at':'2026-09-23'}]
        with self.assertRaisesRegex(ValueError,'缺少原始决策'):native_plan(doc,'route-1')

    def test_modified_step_conditions_break_original_native_binding(self):
        doc=sample_document();route=doc['records']['route-1']
        route['data'].update(representation='decisions',plan={},evidence_identity={'engine_sha256':'0'*64,'scripts_sha256':'1'*64})
        route['data']['native_binding']=native_binding(doc,'route-1')
        modified=deepcopy(doc);modified['records']['route-1-s02']['data']['limits']='different once-per-turn restriction'
        with self.assertRaisesRegex(ValueError,'对应关系待核对'):native_plan(modified,'route-1')

    def test_verification_sessions_reject_live_execution_and_automatic_play(self):
        brain=object.__new__(Modular);brain.context=lambda _: {'knowledge_verification':{'sources':['private']}}
        with self.assertRaisesRegex(ValueError,'验证|校验'):brain.execute({'id':'private','candidate':'x'})
        with self.assertRaisesRegex(ValueError,'验证|校验'):brain.automatic({'id':'private','enabled':True})

    def test_new_live_context_cannot_select_another_contexts_pinned_old_package(self):
        brain=object.__new__(Modular)
        ctx={'id':'new','preference':DEFAULT_PREFERENCE,'precise':False,'selected':[]}
        brain.context=lambda _:ctx;brain.store=SimpleNamespace(lock=threading.RLock());brain.lock=threading.RLock()
        brain.library=SimpleNamespace(sync=lambda:None,entries={'old':{
            'knowledge_package':'pkg','available_for_new':False,'status':'pinned'}})
        with self.assertRaisesRegex(ValueError,'旧版本'):brain.configure({'id':'new','sources':['old']})


if __name__=='__main__':unittest.main()
