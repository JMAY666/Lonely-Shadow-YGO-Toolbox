"""Observation and publication boundaries; actual reconstruction has native tests."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
import test_store as fixtures
from second_routes import observed_state, same_deck, visible_candidate
from modular_decisions import public_state
import hashlib

N = 1184620


class SecondRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StoreTests(); self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.store = self.fixture.store
        self.deck = self.store.save_deck({'name': 'TEST ONLY second replay', 'deck': self.fixture.deck})
        self.owner = self.store.second_duel; self.routes = self.owner.routes
        self.doc = self.owner.start({'request_id': uuid.uuid4().hex, 'deck_id': self.deck['id'],
            'deck_revision': self.deck['revision'], 'opening': [N] * 5})

    def body(self, **fields):
        return {'id': self.doc['id'], 'round_id': self.doc['input']['round_id'], 'revision': self.doc['revision'], **fields}

    def test_public_projection_never_copies_hidden_ids_order_or_opponent_counters(self):
        state = {'turn': 2, 'turn_player': 0, 'phase': 4, 'lp': [8000, 8000], 'cards': [
            {'code': N, 'controller': 0, 'location': 1, 'sequence': 20, 'instance_id': 7},
            {'code': 55144522, 'controller': 1, 'location': 2, 'position': 8, 'sequence': 0, 'instance_id': 9},
            {'code': 55144522, 'controller': 1, 'location': 8, 'position': 8, 'sequence': 1, 'instance_id': 10},
            {'code': N, 'controller': 0, 'location': 4, 'position': 1, 'sequence': 2, 'instance_id': 11}],
            'normal_summons_used': [1, 1], 'effect_usage': [{'player': 1, 'key': 55144522}, {'player': 2, 'key': 55144522}, {'player': 0, 'key': 123}]}
        result = observed_state(state)
        self.assertEqual(result['opponent_hand_count'], 1)
        self.assertEqual(len(result['cards']), 3)
        own_deck = next(c for c in result['cards'] if c['location'] == 1)
        self.assertNotIn('sequence', own_deck); self.assertNotIn('native_instance', own_deck)
        hidden = next(c for c in result['cards'] if c['controller'] == 1)
        self.assertIsNone(hidden['code']); self.assertNotIn('native_instance', hidden)
        self.assertEqual(result['native_rules']['effect_usage'], [{'player': 0, 'key': 123}])
        newer = observed_state(state, result)
        self.assertEqual(next(c['id'] for c in result['cards'] if c.get('native_instance') == 11),
                         next(c['id'] for c in newer['cards'] if c.get('native_instance') == 11))

    def test_deck_matching_counts_duplicates_and_extra_not_only_hand(self):
        self.assertTrue(same_deck({'main': [1, 2, 1]}, {'main': [1, 1, 2]}))
        self.assertFalse(same_deck({'main': [1, 2]}, {'main': [1, 1, 2]}))
        self.assertFalse(same_deck({'main': [1], 'extra': [3]}, {'main': [1], 'extra': [4]}))

    def test_external_states_stale_revisions_and_closed_records_cannot_rebuild(self):
        before = deepcopy(self.owner.load(self.doc['id']))
        for changes in ({'revision': 999}, {'round_id': 'other'}):
            with self.assertRaises(ValueError): self.routes.sources(self.body(**changes))
        raw = self.owner.load(self.doc['id'])
        raw['input']['platform'] = 'masterduel'
        with self.assertRaisesRegex(ValueError, '外部平台'): self.routes.request(self.body())
        raw['input']['platform'] = 'manual'; raw['closed'] = True
        with self.assertRaises(ValueError): self.routes.request(self.body())
        raw.update(deepcopy(before))

    def test_manual_observations_cannot_be_silently_replaced(self):
        doc = self.owner.load(self.doc['id'])
        doc['events'] = [{'kind': 'move', 'id': 'original'}]
        before = deepcopy(doc)
        with self.assertRaisesRegex(ValueError, '人工观察'):
            self.routes.sync(self.body(source_id=str(uuid.uuid4()), confirmed=True))
        self.assertEqual(doc, before)
        with self.assertRaisesRegex(ValueError, '请确认'):
            self.routes.sync(self.body(source_id=str(uuid.uuid4())))

    def test_missing_replay_is_not_synthesized_from_the_board(self):
        sid = str(uuid.uuid4()); folder = self.store.session_path(sid); folder.mkdir()
        self.owner.write(folder/'session.json', {'id': sid, 'deck': self.deck['deck'],
            'expansion': {'turn_order': 'second', 'actual_opening': [N]*5}})
        self.owner.write(folder/'modular-state.json', {'answered': False, 'player': 0, 'raw': '0b00', 'node': 1, 'version': 1, 'revision': 1,
            'state': {'turn': 2, 'turn_player': 0, 'phase': 4, 'chain_depth': 0}})
        with self.assertRaisesRegex(ValueError, '完整重放'): self.routes.sample(sid, self.owner.load(self.doc['id']))

    def test_visible_routes_do_not_expose_native_prompts_or_claim_lethal(self):
        candidate = {'id': 'test', 'remaining': 1, 'path': ['private raw'], 'token': ['private'],
            'steps': [{'source': {'name': 'known source'}, 'next_raw': 'private', 'next_effects': {'secret': True},
                       'bound_decision': {'selection': [{'kind': 'pass'}]}, 'before': {'cards': []}, 'state': {'cards': []}}]}
        visible = visible_candidate(candidate)
        self.assertNotIn('path', visible); self.assertNotIn('token', visible)
        self.assertNotIn('next_raw', visible['steps'][0]); self.assertNotIn('next_effects', visible['steps'][0])
        self.assertIn('未验证战斗', visible['battle']); self.assertIn('对手不追加响应', visible['assumption'])

    def ready(self):
        binding = {'sid': 'mock', 'revision': self.doc['revision'], 'status': 'ready', 'source': 'native',
                   'stamp': 'sample', 'rules': 'rules', 'selected': ['source'], 'preference': 'shortest'}
        self.routes.bindings[self.doc['id']] = binding
        self.routes.valid = Mock(return_value=True)
        self.store.modular.context = Mock(return_value={'forecast_meta': {'tag_selection': {}}})
        self.store.modular.library.sync = Mock()
        self.store.modular.library.validate_deck_sources = Mock()
        self.store.modular.configure = Mock()
        self.store.modular.state = Mock(return_value={'state': {'cards': []}})
        return binding

    def test_failed_publication_does_not_publish_undurable_candidates(self):
        binding = self.ready()
        self.store.modular.search = Mock(return_value={'candidates': [], 'status': 'no_route', 'complete': True,
            'limited': False, 'nodes': 1, 'seconds': 0, 'coverage': {}, 'rejected': {}, 'notice': 'source scope only'})
        class Inline:
            def __init__(self, target, **_): self.target = target
            def start(self): self.target()
        original = deepcopy(self.owner.load(self.doc['id']))
        with patch('second_routes.threading.Thread', Inline), patch.object(self.owner, 'write', side_effect=OSError('disk full')):
            self.routes.generate(self.body(sources=['source']))
        self.assertEqual(binding['status'], 'error'); self.assertIsNone(binding['result'])
        self.assertEqual(self.owner.load(self.doc['id']), original)

    def test_late_result_cannot_replace_newer_observations(self):
        binding = self.ready()
        def changed(*args, **kwargs):
            self.owner.load(self.doc['id'])['revision'] += 1
            return {'candidates': []}
        self.store.modular.search = Mock(side_effect=changed)
        class Inline:
            def __init__(self, target, **_): self.target = target
            def start(self): self.target()
        with patch('second_routes.threading.Thread', Inline): self.routes.generate(self.body(sources=['source']))
        self.assertEqual(binding['status'], 'stale')
        self.assertNotIn('route_history', self.owner.load(self.doc['id']))

    def test_same_checkpoint_refreshes_new_sources_without_rewriting_observations(self):
        binding = self.ready()
        source = str(uuid.uuid4()); binding['source'] = source
        meta = {'selected_deck': self.deck['id'], 'sources': self.store.catalog.sources, 'engine_sha256': hashlib.sha256(b'test engine').hexdigest(),
                'scripts_sha256': self.store.compromise.script_identity()}
        (self.store.runtime/'YGOPro.exe').write_bytes(b'test engine')
        row = {'kind': 'checkpoint', 'node': 1, 'seq': 1, 'player': 0, 'state': {'cards': []}}
        raw = self.owner.load(self.doc['id'])
        raw['native_link'] = {'source': source}; raw['events'] = [{'kind': 'native_sync'}]
        raw['native_history'] = [{'node': 1, 'seq': 1, 'player': 0, 'state': public_state(row['state'])}]
        before = deepcopy(raw)
        self.routes.sample = Mock(return_value=(meta, {'node': 1}, 'sample'))
        self.routes.library_sources = Mock(return_value=({'tag_ids': ['tag']}, [{'id': 'new', 'name': 'new saved source'}]))
        self.store.start = Mock()
        with patch('second_routes.read_journal', return_value=([row], [])), patch('second_routes.route_rows', return_value=([row], [])):
            self.routes.sync(self.body(source_id=source, confirmed=True))
        self.assertEqual(binding['sources'][0]['id'], 'new')
        self.assertEqual(binding['selected'], [])
        self.assertEqual(self.owner.load(self.doc['id']), before)
        self.store.start.assert_not_called()


if __name__ == '__main__': unittest.main()
