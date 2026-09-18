"""Observation boundaries. These fixtures do not claim native rule validation."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from second_duel import SecondDuels
import test_store as fixtures


class SecondDuelsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store
        self.deck = self.store.save_deck({'name': 'TEST ONLY second observations',
                                          'deck': {'main': [55144522] * 2 + [1184620] * 38, 'extra': [23995346], 'side': []}})
        self.api = self.store.second_duel
        self.start_body = {'request_id': uuid.uuid4().hex, 'deck_id': self.deck['id'],
                           'deck_revision': self.deck['revision'], 'opening': [55144522, 1184620, 1184620, 1184620, 1184620]}
        self.doc = self.api.start(self.start_body)

    def body(self, kind, **payload):
        return {'id': self.doc['id'], 'round_id': self.doc['input']['round_id'], 'revision': self.doc['revision'],
                'event_id': uuid.uuid4().hex, 'kind': kind, 'payload': payload}

    def event(self, kind, **payload):
        self.doc = self.api.event(self.body(kind, **payload))
        return self.doc

    def verify(self, **changes):
        payload = {'turn': 1, 'turn_player': 1, 'phase': 'main1', 'lp': [8000, 8000],
                   'opponent_hand_count': 5, 'confirmed': True}
        return self.event('verify', **(payload | changes))

    def test_five_spend_one_draw_one_preserves_opening_and_instances(self):
        original = deepcopy(self.doc['input'])
        spent = next(c for c in self.doc['current']['cards'] if c['location'] == 2 and c['code'] == 55144522)
        body = self.body('move', card_id=spent['id'], **{'from': 2, 'to': 16, 'reason': 'cost'})
        self.doc = self.api.event(body)
        self.assertEqual(len(self.doc['current']['hand']), 4)
        self.assertEqual(self.api.event(body)['revision'], self.doc['revision'])
        drawn = next(c for c in self.doc['current']['cards'] if c['location'] == 1)
        self.event('move', card_id=drawn['id'], **{'from': 1, 'to': 2, 'reason': 'draw'})
        self.assertEqual(len(self.doc['current']['hand']), 5)
        self.assertEqual(self.doc['input'], original)
        self.assertEqual(len(self.doc['events']), 2)
        current_spent = next(c for c in self.doc['current']['cards'] if c['id'] == spent['id'])
        self.assertEqual(current_spent['location'], 16)
        self.assertEqual(self.store.get_deck(self.deck['id'])['deck'], self.deck['deck'])

    def test_stale_revisions_rounds_instances_and_reused_ids_do_not_spend_cards(self):
        self.verify()
        card = next(c for c in self.doc['current']['cards'] if c['location'] == 2)
        good = self.body('move', card_id=card['id'], **{'from': 2, 'to': 16, 'reason': 'cost'})
        for bad in ({**good, 'revision': 0}, {**good, 'round_id': 'old'},
                    {**good, 'payload': {**good['payload'], 'from': 1}}):
            with self.assertRaises(ValueError):
                self.api.event(bad)
            self.assertEqual(len(self.api.state({'id': self.doc['id']})['current']['hand']), 5)
        self.doc = self.api.event(good)
        with self.assertRaises(ValueError):
            self.api.event({**good, 'payload': {**good['payload'], 'to': 32}})
        self.assertEqual(len(self.doc['current']['hand']), 4)

    def test_failed_atomic_write_rolls_back_revision_and_resources(self):
        before = self.api.state({'id': self.doc['id']})
        card = next(c for c in self.doc['current']['cards'] if c['location'] == 2)
        with patch.object(self.api, 'write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.event('move', card_id=card['id'], **{'from': 2, 'to': 16, 'reason': 'cost'})
        self.assertEqual(self.api.state({'id': before['id']}), before)

    def test_windows_expire_and_any_observation_invalidates_previous_window(self):
        self.verify()
        self.event('window', label='公开效果发动，当前我方响应', confirmed=True)
        self.assertTrue(self.doc['window_valid'])
        expiry = self.doc['current']['window']['expires_ms']
        with patch.object(self.api, 'now', return_value=expiry):
            self.assertFalse(self.api.state({'id': self.doc['id']})['window_valid'])
        self.event('choice', note='实际选择暂不响应')
        self.assertIsNone(self.doc['current']['window'])
        self.assertIsNotNone(self.doc['events'][-1]['before']['window'])
        self.assertTrue(self.doc['status_reason'])

    def test_unknown_opponent_cards_cannot_store_secret_identity(self):
        with self.assertRaises(ValueError):
            self.event('opponent_card', location=8, known=False, code=55144522)
        self.event('opponent_card', location=8, known=False, code=None)
        opponent = next(c for c in self.doc['current']['cards'] if c['controller'] == 1)
        self.assertIsNone(opponent['code'])
        for zone in (1, 2, 64):
            with self.assertRaises(ValueError):
                self.event('opponent_card', location=zone, known=True, code=55144522)

    def test_private_record_and_deck_snapshot_do_not_mutate_saved_deck_or_plans(self):
        original = self.store.get_deck(self.deck['id'])
        plans = list(self.store.plans.glob('*.json'))
        self.verify(turn=2, turn_player=0)
        self.assertEqual(self.doc['input']['deck'], original['deck'])
        self.assertEqual(list(self.store.plans.glob('*.json')), plans)
        self.assertTrue((self.store.root / 'second-duels' / (self.doc['id'] + '.json')).exists())
        self.assertFalse(self.doc['capabilities']['engine_reconstruction'])
        self.assertFalse(self.doc['capabilities']['routes'])

    def test_reopening_requires_verification_and_never_restores_active_window(self):
        self.verify()
        self.event('window', label='待处理的公开效果', confirmed=True)
        restarted = SecondDuels(self.store, self.api.read, self.api.write, self.api.now)
        value = restarted.state({'id': self.doc['id']})
        self.assertTrue(value['status_reason'])
        self.assertFalse(value['window_valid'])
        with self.assertRaises(ValueError):
            restarted.event(self.body('choice', note='过期选择'))
        self.api = restarted
        self.verify()
        self.assertIsNone(self.doc['current']['window'])
        self.assertFalse(self.doc['status_reason'])

    def test_rule_notes_preserve_unknown_and_do_not_reset_faceup_uses(self):
        self.event('rule', category='usage', label='TEST ONLY 表侧存在期间已使用一次', status='confirmed')
        self.event('rule', category='restrictions', label='是否仍适用待确认', status='unknown')
        self.verify(turn=2, turn_player=0)
        self.assertEqual(self.doc['current']['usage'][0]['status'], 'confirmed')
        self.assertEqual(self.doc['current']['restrictions'][0]['status'], 'unknown')
        row = self.doc['current']['usage'][0]
        with self.assertRaises(ValueError):
            self.event('rule_status', category='usage', rule_id=row['id'], status='expired')
        self.event('rule_status', category='usage', rule_id=row['id'], status='expired', note='用户核对后更正')
        self.assertEqual(self.doc['events'][-1]['before']['usage'][0]['status'], 'confirmed')

    def test_close_rejects_late_mutations_but_keeps_full_history(self):
        old = self.body('result', note='迟到结果')
        value = self.api.dispatch('close', {'id': self.doc['id'], 'round_id': self.doc['input']['round_id']})
        self.assertTrue(value['closed'])
        with self.assertRaises(ValueError):
            self.api.event(old)
        self.assertEqual(len(self.api.history()), 1)
        self.assertEqual(self.api.state({'id': self.doc['id']})['input']['opening'], self.doc['input']['opening'])

    def test_concurrent_event_compare_and_swap_applies_only_once(self):
        requests = [self.body('choice', note='选择一'), self.body('choice', note='选择二')]
        accepted, rejected = [], []
        def submit(body):
            try: accepted.append(self.api.event(body))
            except ValueError as error: rejected.append(str(error))
        workers = [threading.Thread(target=submit, args=(body,)) for body in requests]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertEqual((len(accepted), len(rejected)), (1, 1))

    def test_smart_second_opening_is_bound_to_round_and_connection(self):
        rid, cid, sid = (uuid.uuid4().hex for _ in range(3))
        opening = {'status': 'ready', 'snapshot_id': sid, 'cards': self.start_body['opening'], 'captured_ms': 10}
        job = {'id': rid, 'stage': 'second', 'round_id': 'round', 'capture_id': cid, 'stop': threading.Event(),
               'frame': {'round_id': 'round', 'opening': opening, 'confirmed': {'order': 'second'}},
               'construction': {'deck': self.deck['deck']}, 'last_sample': time.monotonic(), 'touched': time.monotonic()}
        smart = self.store.ygopro_smart
        smart.jobs[rid] = job
        smart.active = rid
        body = {'request_id': uuid.uuid4().hex, 'recognition_id': rid, 'round_id': 'round', 'snapshot_id': sid}
        value = self.api.start(body)
        self.assertEqual(value['input']['opening']['source'], 'readonly_opening')
        self.assertEqual(value['input']['opening']['cards'], self.start_body['opening'])
        job['round_id'] = 'next'
        self.assertTrue(self.api.state({'id': value['id']})['status_reason'])
        with self.assertRaises(ValueError):
            self.api.event({'id': value['id'], 'round_id': 'round', 'revision': 0,
                            'event_id': uuid.uuid4().hex, 'kind': 'choice', 'payload': {'note': '旧局'}})

    def test_unrecognized_operations_and_identity_changes_are_rejected(self):
        with self.assertRaises(ValueError):
            self.event('execute', raw='native input')
        with self.assertRaises(ValueError):
            self.api.start({**self.start_body, 'opening': [1184620] * 5})
        self.assertEqual(self.api.state({'id': self.doc['id']})['revision'], 0)

    def test_positions_and_overlay_hosts_never_accept_conflicting_or_dangling_cards(self):
        hand = [c for c in self.doc['current']['cards'] if c['location'] == 2]
        self.event('move', card_id=hand[0]['id'], **{'from': 2, 'to': 4, 'position': 1, 'sequence': 0})
        with self.assertRaises(ValueError):
            self.event('move', card_id=hand[1]['id'], **{'from': 2, 'to': 4, 'position': 1, 'sequence': 0})
        self.event('move', card_id=hand[1]['id'], **{'from': 2, 'to': 128, 'host_id': hand[0]['id']})
        with self.assertRaisesRegex(ValueError, '素材实际去向'):
            self.event('move', card_id=hand[0]['id'], **{'from': 4, 'to': 16})
        self.event('move', card_id=hand[1]['id'], **{'from': 128, 'to': 16})
        self.event('move', card_id=hand[0]['id'], **{'from': 4, 'to': 16})
        self.assertTrue(all(not c.get('host_id') for c in self.doc['current']['cards']))

    def test_reveal_keeps_unknown_history_and_freezes_observed_card_text(self):
        self.event('opponent_card', location=8, known=False, code=None)
        row = next(c for c in self.doc['current']['cards'] if c['controller'] == 1)
        self.event('reveal', card_id=row['id'], code=55144522)
        self.assertIsNone(next(c for c in self.doc['events'][-1]['before']['cards'] if c['id'] == row['id'])['code'])
        original = self.doc['catalog']['55144522']['name']
        with patch.dict(self.store.catalog.cards[55144522], {'name': 'changed later'}):
            self.assertEqual(self.api.state({'id': self.doc['id']})['catalog']['55144522']['name'], original)

    def test_resume_requires_reconciliation_before_reopening_response_window(self):
        self.verify()
        self.event('window', label='旧窗口', confirmed=True)
        self.event('resume')
        self.assertTrue(self.doc['status_reason'])
        self.assertIsNone(self.doc['current']['window'])
        with self.assertRaises(ValueError):
            self.event('window', label='未经核对的新窗口', confirmed=True)
        self.verify()
        self.event('window', label='重新核对的窗口', confirmed=True)
        self.assertTrue(self.doc['window_valid'])


if __name__ == '__main__':
    unittest.main()
