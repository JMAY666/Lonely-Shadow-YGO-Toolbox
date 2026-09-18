from copy import deepcopy
import threading
import time
import unittest
import uuid

import test_store as fixtures
from ygopro_capture import CaptureError


class Source:
    def __init__(self, deck):
        self.attached = {'pid': 123, 'capture_id': 'capture'}
        self.deck = deepcopy(deck)
        self.alive = True
        self.sample = self.make('waiting_start')

    def make(self, phase, turn=0, order=None, hand=None, draw=None):
        frame = {'phase': phase, 'detected_order': order,
                 'evidence': {'turn': turn, 'is_first': order != 'second', 'in_duel': hand is not None}}
        if hand is not None: frame['opening_sample'] = {'turn': turn, 'hand': hand, 'draw': draw}
        value = {'frame': frame, 'game': 'stable-game', 'capture_id': 'capture'}
        if hand is not None:
            value['construction'] = {'deck': deepcopy(self.deck), 'method': 'submitted-current-deck-and-initial-zones',
                                     'evidence': {'game': 'stable-game', 'turn': turn}}
        return value

    def live_sample(self, *args, **kwargs):
        if isinstance(self.sample, Exception): raise self.sample
        return deepcopy(self.sample)

    def connection_alive(self, *_): return self.alive

    def submitted_deck(self, *_): return deepcopy(self.deck)


class SmartTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StoreTests(); self.fixture.setUp()
        self.store = self.fixture.store
        for code in range(100, 115):
            self.store.catalog.cards[code] = {**self.store.catalog.cards[1184620], 'id': code, 'name': '合成卡'+str(code)}
        self.deck = {'main': [c for c in range(100, 113) for _ in range(3)]+[113], 'extra': [], 'side': [114, 114]}
        self.hand = [100, 100, 101, 102, 103]
        self.store.library.builtins = {'test': {'id': 'test', 'name': '合成 TAG', 'include_cards': list(range(100, 114))}}
        self.source = Source(self.deck); self.store.ygopro_capture = self.source
        self.service = self.store.ygopro_smart
        self.body = {'request_id': uuid.uuid4().hex, 'capture_id': 'capture'}
        self.releases = []

    def tearDown(self):
        self.service.cancel_active()
        for release in self.releases: release.set()
        # Let private context cleanup finish before its isolated directory closes.
        time.sleep(.08)
        self.fixture.tearDown()

    def wait(self, predicate, timeout=3):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            value = self.service.poll(self.body)
            if predicate(value): return value
            time.sleep(.01)
        self.fail('Timed out: '+repr(value))

    def start(self): return self.service.start(self.body)

    def deal(self, order='first', cards=None):
        cards = self.hand if cards is None else cards
        self.source.sample = self.source.make('waiting_choice', order=order, hand=cards[:1], draw=cards)
        self.wait(lambda v: ((v.get('frame') or {}).get('opening') or {}).get('status') == 'dealing')
        self.source.sample = self.source.make('waiting_choice', order=order, hand=cards, draw=cards)
        self.wait(lambda v: ((v.get('frame') or {}).get('opening') or {}).get('status') == 'ready')
        self.source.sample = self.source.make('detected', turn=1, order=order, hand=cards)

    def test_first_flow_freezes_duplicates_is_idempotent_and_preserves_libraries(self):
        before = self.store.list_decks(); step = deepcopy(self.store.ygopro_order.public())
        self.start(); self.deal(); value = self.wait(lambda v: v['stage'] == 'ready')
        self.assertEqual(value['context']['hand'], self.hand)
        self.assertEqual(value['tag_result']['selection']['primary_ids'], ['test'])
        self.assertEqual(value['context']['deck']['deck'], self.deck)
        self.assertEqual(self.service.start(self.body)['context'], value['context'])
        self.source.sample = self.source.make('detected', 3, 'first', self.hand+[104])
        self.wait(lambda v: v['frame']['evidence']['turn'] == 3)
        self.assertEqual(self.service.poll(self.body)['context']['hand'], self.hand)
        self.assertEqual(len(self.store.automatic_duel.contexts), 1)
        self.assertEqual(self.store.list_decks(), before)
        self.assertEqual(self.store.ygopro_order.public(), step)

    def test_tag_latency_does_not_delay_sampling_and_cancel_discards_late_result(self):
        release = threading.Event(); self.releases.append(release)
        original = self.service.recognize_tags
        self.service.recognize_tags = lambda deck: (release.wait(3), original(deck))[1]
        self.start(); self.deal()
        value = self.wait(lambda v: v['frame']['phase'] == 'detected')
        self.assertEqual(value['frame']['opening']['cards'], self.hand)
        self.assertIsNone(value['context'])
        self.service.cancel(self.body); release.set(); time.sleep(.05)
        self.assertEqual(self.service.poll(self.body)['stage'], 'cancelled')
        self.assertEqual(self.store.automatic_duel.contexts, {})

    def test_cancel_before_delayed_start_cannot_replace_a_newer_task(self):
        old = dict(self.body); self.service.cancel(old)
        self.body['request_id'] = uuid.uuid4().hex; self.start()
        self.assertEqual(self.service.start(old)['stage'], 'cancelled')
        self.assertEqual(self.service.active, self.body['request_id'])

    def test_tag_failure_invalid_ids_and_retry_are_never_automatic_success(self):
        original = self.service.recognize_tags
        self.service.recognize_tags = lambda _: {'selection': {'tag_ids': ['missing'], 'primary_ids': []}}
        self.start(); self.deal(); value = self.wait(lambda v: v['stage'] == 'failed')
        self.assertEqual(value['failed_stage'], 'tags'); self.assertIsNone(value['context'])
        self.service.recognize_tags = original; self.service.retry({**self.body,'cycle':value['cycle'],'round_id':value['frame']['round_id']})
        self.assertEqual(self.wait(lambda v: v['stage'] == 'ready')['context']['hand'], self.hand)

    def test_no_applicable_tags_is_success_not_a_recognition_failure(self):
        self.store.library.builtins = {}
        self.start(); self.deal(); value = self.wait(lambda v: v['stage'] == 'ready')
        self.assertEqual(value['tag_result']['outcome'], 'no_applicable_tags')
        self.assertEqual(value['context']['deck']['tag_selection']['tag_ids'], [])

    def test_missing_initial_draw_or_late_start_never_uses_current_hand(self):
        self.source.sample = self.source.make('detected', 1, 'first', self.hand)
        self.start(); value = self.wait(lambda v: v['stage'] == 'failed')
        self.assertEqual(value['failed_stage'], 'opening'); self.assertIsNone(value['context'])
        self.assertEqual(value['frame']['opening']['cards'], [])

    def test_second_player_retains_opening_without_workspace_or_planner(self):
        self.start(); self.deal('second'); value = self.wait(lambda v: v['stage'] == 'second')
        self.assertEqual(value['frame']['opening']['cards'], self.hand)
        self.assertEqual(value['message'], '已识别为后攻，后攻展开暂未支持')
        self.assertIsNone(value['context']); self.assertEqual(self.store.automatic_duel.contexts, {})

    def test_hand_copy_mismatch_fails_software_audit(self):
        self.start(); self.deal(cards=[100]*4+[101])
        value = self.wait(lambda v: v['stage'] == 'failed')
        self.assertEqual(value['failed_stage'], 'audit'); self.assertIsNone(value['context'])

    def test_end_automatically_arms_next_round_on_the_same_subscription(self):
        self.start(); self.deal(); first = self.wait(lambda v: v['stage'] == 'ready')
        self.source.sample = self.source.make('ended')
        waiting = self.wait(lambda v: v['stage'] == 'waiting' and v['cycle'] == 1)
        self.assertIsNone(waiting['context']); self.assertIsNone(waiting['construction'])
        self.assertEqual(waiting['id'], first['id'])
        with self.assertRaises(ValueError): self.store.automatic_duel.context(first['context']['context_id'])
        self.source.sample = self.source.make('waiting_start')
        self.wait(lambda v: v['frame'] and v['frame']['phase'] == 'waiting_start')
        self.deal(); second = self.wait(lambda v: v['stage'] == 'ready')
        self.assertNotEqual(first['context']['context_id'], second['context']['context_id'])
        self.assertNotEqual(first['frame']['round_id'], second['frame']['round_id'])
        self.assertEqual(first['id'], second['id'])
        self.assertFalse(self.service.context_valid(second['id'], first['frame']['round_id']))
        self.assertTrue(self.service.context_valid(second['id'], second['frame']['round_id']))

    def test_new_round_without_an_end_sample_retires_old_results(self):
        self.start(); self.deal(); old = self.wait(lambda v: v['stage'] == 'ready')
        self.source.sample = self.source.make('rps')
        self.wait(lambda v: v['cycle'] == 1 and v['frame'] and v['frame']['phase'] == 'rps')
        self.deal(); current = self.wait(lambda v: v['stage'] == 'ready')
        self.assertNotEqual(old['frame']['round_id'], current['frame']['round_id'])
        self.assertEqual(len(self.store.automatic_duel.contexts), 2)

    def test_read_gap_retires_round_but_keeps_waiting_until_a_proven_new_boundary(self):
        self.start(); self.deal(); old = self.wait(lambda v: v['stage'] == 'ready')
        with self.service.lock: self.service.jobs[self.body['request_id']]['last_sample'] -= 3
        self.source.sample = CaptureError('temporary read failure')
        self.wait(lambda v: v['stage'] == 'waiting' and v['cycle'] == 1)
        self.source.sample = self.source.make('detected', 1, 'first', self.hand)
        time.sleep(.08)
        self.assertIsNone(self.service.poll(self.body)['context'])
        self.source.sample = self.source.make('waiting_start')
        self.wait(lambda v: v['frame'] and v['frame']['phase'] == 'waiting_start')
        self.deal(); self.wait(lambda v: v['stage'] == 'ready')
        with self.assertRaises(ValueError): self.store.automatic_duel.context(old['context']['context_id'])

    def test_only_a_confirmed_closed_process_stops_the_subscription(self):
        self.start(); self.deal(); self.wait(lambda v: v['stage'] == 'ready')
        self.source.alive = False; self.source.sample = CaptureError('process exited')
        value = self.wait(lambda v: v['stage'] == 'closed')
        self.assertIn('已关闭', value['message'])
        self.assertFalse(self.service.current(self.service.jobs[self.body['request_id']]))

    def test_old_tag_worker_cannot_fill_the_next_round_of_the_same_subscription(self):
        release = threading.Event(); self.releases.append(release)
        original = self.service.recognize_tags; calls = [0]
        def analyze(deck):
            calls[0] += 1
            if calls[0] == 1: release.wait(3)
            return original(deck)
        self.service.recognize_tags = analyze
        self.start(); self.deal(); self.wait(lambda v: v['frame']['phase']=='detected')
        self.source.sample = self.source.make('ended')
        self.wait(lambda v: v['cycle']==1 and v['stage']=='waiting')
        self.store.library.builtins = {}
        self.deal(); current = self.wait(lambda v: v['stage']=='ready')
        release.set(); time.sleep(.06)
        self.assertEqual(self.service.poll(self.body)['context'], current['context'])
        self.assertEqual(current['tag_result']['outcome'], 'no_applicable_tags')
        self.assertEqual(len(self.store.automatic_duel.contexts), 1)

    def test_second_player_round_automatically_returns_to_waiting_and_then_first_flow(self):
        self.start(); self.deal('second'); second = self.wait(lambda v: v['stage']=='second')
        self.assertIsNone(second['context'])
        self.source.sample=self.source.make('ended')
        self.wait(lambda v: v['stage']=='waiting' and v['cycle']==1)
        self.deal(); first=self.wait(lambda v: v['stage']=='ready')
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['frame']['detected_order'],'first')
        self.assertNotEqual(first['frame']['opening']['snapshot_id'],second['frame']['opening']['snapshot_id'])

    def test_retry_from_old_cycle_cannot_restart_a_new_rounds_tag_task(self):
        self.service.recognize_tags=lambda _: {'selection':{'tag_ids':['missing'],'primary_ids':[]}}
        self.start();self.deal();old=self.wait(lambda v:v['stage']=='failed')
        self.source.sample=self.source.make('ended');self.wait(lambda v:v['cycle']==1)
        self.deal();current=self.wait(lambda v:v['stage']=='failed')
        generation=self.service.jobs[self.body['request_id']]['tag_generation']
        with self.assertRaisesRegex(ValueError,'局次已变化'):
            self.service.retry({**self.body,'cycle':old['cycle'],'round_id':old['frame']['round_id']})
        self.assertEqual(self.service.jobs[self.body['request_id']]['tag_generation'],generation)
        self.assertEqual(self.service.poll(self.body)['error'],current['error'])

    def test_changed_deck_after_cancel_uses_new_tags_and_snapshot_only(self):
        self.start(); self.deal(); old = self.wait(lambda v: v['stage'] == 'ready')
        self.service.cancel(self.body)
        self.source.deck['main'] = [114 if c == 100 else c for c in self.deck['main']]
        self.source.deck['side'] = [100, 100]
        self.hand = [114, 114, 101, 102, 103]
        self.source.sample = self.source.make('waiting_start')
        self.body['request_id'] = uuid.uuid4().hex; self.start(); self.deal()
        new = self.wait(lambda v: v['stage'] == 'ready')
        self.assertNotEqual(old['context']['context_id'], new['context']['context_id'])
        self.assertNotEqual(old['frame']['round_id'], new['frame']['round_id'])
        self.assertEqual(new['context']['hand'], self.hand)
        self.assertEqual(new['context']['deck']['deck'], self.source.deck)


if __name__ == '__main__': unittest.main()
