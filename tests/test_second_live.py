from copy import deepcopy
import struct
import threading
import time
import unittest
from unittest.mock import Mock,patch
import uuid

import test_second_duel as fixtures
from ygopro_live import LAYOUT,MISSING


class SecondLiveTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.SecondDuelsTests();f.setUp();self.addCleanup(f.doCleanups)
        self.store,self.api=f.store,f.api
        self.rid,self.cid,self.sid=(uuid.uuid4().hex for _ in range(3))
        self.job={'id':self.rid,'stage':'second','round_id':'round','capture_id':self.cid,'platform':'ygopro',
            'stop':threading.Event(),'game':struct.pack('<Q',0x2000000).hex(),'frame':{'round_id':'round','confirmed':{'order':'second'},'evidence':{'turn':2},
            'opening':{'status':'ready','snapshot_id':self.sid,'cards':f.start_body['opening'],'captured_ms':10}},
            'construction':{'deck':f.deck['deck']},'last_sample':time.monotonic(),'touched':time.monotonic()}
        smart=self.store.ygopro_smart;smart.jobs[self.rid]=self.job;smart.active=self.rid
        self.doc=self.api.start({'request_id':uuid.uuid4().hex,'recognition_id':self.rid,'round_id':'round','snapshot_id':self.sid})
        self.sample={'layout':LAYOUT,'game':'2000000','order':'second','turn':2,'lp':[6000,8000],
            'cards':[{'code':1184620,'controller':0,'owner':0,'location':2,'sequence':i,'position':10} for i in range(4)],
            'counts':[{'1':35,'2':4,'4':0,'8':0,'16':1,'32':0,'64':1},{'1':35,'2':5,'4':0,'8':0,'16':0,'32':0,'64':0}],
            'missing':MISSING,'rules_complete':False,'phase':None,'capture_id':self.cid,'image_hash':'fixture'}
        self.capture=Mock(side_effect=lambda _:deepcopy(self.sample));self.store.ygopro_capture.resource_snapshot=self.capture

    def body(self,**extra):return {'id':self.doc['id'],'round_id':'round','revision':self.doc['revision'],**extra}
    def preview(self):self.doc=self.api.dispatch('live-preview',self.body());return self.doc
    def apply_body(self):return self.body(preview_id=self.doc['live_panel']['preview']['id'],event_id=uuid.uuid4().hex,confirmed=True)

    def test_preview_preserves_actual_state_and_confirmed_import_keeps_opening_history(self):
        original=deepcopy(self.doc);self.preview()
        self.assertEqual(self.doc['current'],original['current']);self.assertEqual(self.doc['revision'],0)
        self.assertEqual(len(self.doc['live_reads']),1);self.assertNotIn('game',self.doc['live_reads'][0]['snapshot'])
        body=self.apply_body();self.doc=self.api.dispatch('live-apply',body)
        self.assertEqual(len(self.doc['current']['hand']),4);self.assertEqual(self.doc['input'],original['input'])
        self.assertEqual(self.doc['events'][0]['before'],{k:v for k,v in original['current'].items() if k!='hand'})
        self.assertEqual(self.doc['current']['phase'],'unknown');self.assertFalse(self.doc['capabilities']['engine_reconstruction'])
        self.assertIsNone(self.doc['current']['turn_player'])
        self.assertEqual(self.api.dispatch('live-apply',body)['revision'],1)

    def test_changed_snapshot_late_round_and_failed_save_cannot_overwrite_resources(self):
        self.preview();body=self.apply_body();before=deepcopy(self.api.load(self.doc['id']))
        self.sample['lp'][0]=5000
        with self.assertRaisesRegex(ValueError,'客户端已变化'):self.api.dispatch('live-apply',body)
        self.assertEqual(self.api.load(self.doc['id']),before)
        self.sample['lp'][0]=6000
        with patch.object(self.api,'write',side_effect=OSError('fixture failed write')):
            with self.assertRaises(OSError):self.api.dispatch('live-apply',body)
        self.assertEqual(self.api.load(self.doc['id']),before)
        self.job['round_id']='new'
        with self.assertRaises(ValueError):self.api.dispatch('live-apply',body)

    def test_polling_detects_changes_and_read_failures_without_silently_importing(self):
        self.preview();self.doc=self.api.dispatch('live-apply',self.apply_body());before=deepcopy(self.doc['current'])
        self.sample['lp'][0]=4000
        value=self.api.state({'id':self.doc['id']});self.assertIn('客户端资源已变化',value['status_reason'])
        self.assertEqual(value['current'],before)
        self.capture.side_effect=ValueError('read interrupted')
        self.assertIn('无法核对',self.api.state({'id':self.doc['id']})['status_reason'])

    def test_source_scene_change_and_manual_physical_edit_are_rejected(self):
        self.sample['game']='3000000'
        with self.assertRaisesRegex(ValueError,'游戏场景'):self.preview()
        self.sample['game']='2000000';self.preview();self.doc=self.api.dispatch('live-apply',self.apply_body())
        card=self.doc['current']['cards'][0]
        with self.assertRaisesRegex(ValueError,'重复扣牌'):
            self.api.event({**self.body(), 'event_id':uuid.uuid4().hex,'kind':'move','payload':{'card_id':card['id'],'from':2,'to':16}})
        with self.assertRaisesRegex(ValueError,'核对值'):
            self.api.event({**self.body(),'event_id':uuid.uuid4().hex,'kind':'verify','payload':{'lp':[8000,8000]}})

    def test_closed_or_expired_preview_never_grants_an_old_window(self):
        self.preview();p=self.doc['live_panel']['preview'];now=self.api.now()
        with patch.object(self.api,'now',return_value=now+3000):
            value=self.api.state({'id':self.doc['id']});self.assertFalse(value['live_panel']['preview']['current'])
            self.assertTrue(value['live_panel']['preview']['can_apply']) # The button re-reads before applying.
        self.api.dispatch('close',self.body())
        with self.assertRaises(ValueError):self.api.dispatch('live-apply',self.apply_body())

    def test_a_late_read_cannot_overwrite_a_newer_manual_event(self):
        self.preview();body=self.apply_body();old=deepcopy(self.doc['input'])
        def late(_):
            current=self.api.load(self.doc['id']);current['revision']+=1
            current['current']['stale_reason']='newer observation'
            return deepcopy(self.sample)
        self.capture.side_effect=late
        with self.assertRaises(ValueError):self.api.dispatch('live-apply',body)
        current=self.api.load(self.doc['id'])
        self.assertEqual(current['current']['stale_reason'],'newer observation');self.assertEqual(current['input'],old)
        self.assertNotIn('live_history',current)

    def test_import_does_not_refund_spent_uses_or_infer_unread_turn_player(self):
        current=self.api.load(self.doc['id'])['current']
        current['effect_counts']={'shared':{'status':'used','turn':2},'instance':{'status':'unused','turn':2}}
        self.preview();self.doc=self.api.dispatch('live-apply',self.apply_body())
        self.assertEqual(self.doc['current']['effect_counts']['shared']['status'],'used')
        self.assertEqual(self.doc['current']['effect_counts']['instance']['status'],'unknown')
        value=self.api.event({**self.body(),'event_id':uuid.uuid4().hex,'kind':'verify','payload':{
            'turn':2,'turn_player':1,'phase':'main1','lp':[6000,8000],'opponent_hand_count':5,'confirmed':True}})
        self.assertEqual(value['current']['turn_player'],1) # Explicit human confirmation, not parity inference.
