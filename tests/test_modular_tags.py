"""Deck-scoped source eligibility at the library and computation boundaries."""
from copy import deepcopy
from unittest.mock import Mock, patch
import unittest
import uuid

import test_store
from app import atomic_json
from duel_planner import generate


class ModularTagTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def prepare(self):
        tags = []
        for index, name in enumerate(('TEST ONLY 主系列', 'TEST ONLY 副系列', 'TEST ONLY 无关系列')):
            tags.append(self.store.library.edit_tag({'name': name, 'revision': index})['tag']['id'])
        self.tags = tags
        self.saved = self.store.save_deck({'name': 'TEST ONLY source filter', 'deck': self.deck,
            'tag_selection': {'tag_ids': tags[:2], 'primary_ids': tags[:1]}})
        # Only extraction is stubbed here; saved classifications, indexing,
        # cache identity and API dispatch use the real services.
        capture = patch.object(self.store.modular.library, 'capture', side_effect=lambda plan, *_:
            {'snapshots': [], 'edges': [{}] if plan.get('usable', True) else [], 'unknown': []})
        capture.start(); self.addCleanup(capture.stop)
        self.plans = {}
        for name, selected in [('primary', tags[:1]), ('secondary', tags[1:2]),
                               ('mixed', tags[1:]), ('unrelated', tags[2:]), ('untagged', [])]:
            plan = {'id': str(uuid.uuid4()), 'name': 'TEST ONLY '+name, 'edit_revision': 0,
                    'classification': {'mode': 'manual', 'tag_ids': selected, 'primary_ids': []}}
            atomic_json(self.store.plan_path(plan['id']), plan)
            self.plans[name] = plan
        self.body = {'consumer': 'duel', 'session': 'test-round', 'slot': 'opening',
                     'deck_id': self.saved['id'], 'revision': self.saved['revision'],
                     'hand_count': 1, 'hand': [55144522], 'sources': [self.plans['primary']['id']]}
        self.store.modular.precompute.rules = Mock(return_value='test-rules')
        self.store.modular.precompute.ensure_worker = Mock()

    def test_primary_secondary_and_mixed_sources_match_by_id_without_mutating_plans(self):
        self.prepare()
        before = {path: path.read_bytes() for path in self.store.plans.glob('*.json')}
        result = self.store.modular.library.for_deck(self.saved)
        self.assertEqual({p['id'] for p in result['sources']},
                         {self.plans[name]['id'] for name in ('primary', 'secondary', 'mixed')})
        self.assertEqual(result['reason'], '')
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertEqual(len(self.store.modular.library.summary()['sources']), 5)

    def test_no_tags_unknown_tags_and_incomplete_sources_never_fall_back_to_all(self):
        self.prepare()
        for tags in ([], ['custom:missing']):
            result = self.store.modular.library.for_deck({**self.saved, 'tag_selection': {'tag_ids': tags}})
            self.assertEqual(result['sources'], [])
            self.assertIn('没有可用 Tag', result['reason'])
        for plan in self.plans.values():
            atomic_json(self.store.plan_path(plan['id']), {**plan, 'usable': False})
        result = self.store.modular.library.for_deck(self.saved)
        self.assertEqual(result['sources'], [])
        self.assertIn('没有与当前卡组', result['reason'])

    def test_direct_and_prepared_requests_reject_unrelated_sources_before_starting_an_engine(self):
        self.prepare()
        with patch.object(self.store, 'start') as start:
            for sources in ([], [self.plans['unrelated']['id']],
                            [self.plans['primary']['id'], self.plans['untagged']['id']]):
                with self.subTest(sources=sources):
                    body = {**self.body, 'sources': sources}
                    with self.assertRaisesRegex(ValueError, 'Tag'): generate(self.store.modular, body)
                    with self.assertRaisesRegex(ValueError, 'Tag'):
                        self.store.modular.precompute.dispatch('plan-prepare', body)
            start.assert_not_called()
        self.assertEqual(self.store.modular.precompute.jobs, {})

    def test_automatic_workspace_uses_its_frozen_deck_tags(self):
        self.prepare()
        context = self.store.automatic_duel.create({'name': 'TEST ONLY captured deck', 'deck': self.deck,
            'tag_selection': self.saved['tag_selection'], 'hand': [55144522],
            'round_id': 'test-round', 'snapshot_id': 'test-opening', 'turn_order': 'first'})
        result = self.store.modular.library.for_deck(context['deck'])
        self.assertEqual(len(result['sources']), 3)
        with self.assertRaisesRegex(ValueError, 'Tag'):
            self.store.automatic_duel.dispatch({'context_id': context['context_id'], 'intent': 'plan-prepare',
                'sources': [self.plans['unrelated']['id']]})
        job = self.store.automatic_duel.dispatch({'context_id': context['context_id'], 'intent': 'plan-prepare',
            'sources': [self.plans['secondary']['id']]})
        self.assertEqual(job['status'], 'queued')

    def test_classification_changes_invalidate_cached_jobs_and_keep_old_source_versions(self):
        self.prepare()
        service = self.store.modular.precompute
        prepared = service.dispatch('plan-prepare', self.body)
        plan = self.plans['primary']
        entry = self.store.modular.library.entries[plan['id']]
        frozen = self.store.modular.library.root/'versions'/plan['id']/(entry['version']+'.json')
        before = frozen.read_bytes()
        self.store.library.save_selection({'id': plan['id'], 'revision': 0,
            'classification': {'tag_ids': self.tags[2:], 'primary_ids': []}})
        result = service.dispatch('plan-poll', {**self.body, 'job': prepared['job']})
        self.assertEqual(result['status'], 'stale')
        self.assertNotIn(plan['id'], {p['id'] for p in self.store.modular.library.for_deck(self.saved)['sources']})
        self.assertEqual(frozen.read_bytes(), before)

    def test_automatic_classification_rechecks_tag_membership_without_source_file_edits(self):
        self.prepare()
        plan = deepcopy(self.plans['primary'])
        plan.pop('classification')
        plan['actions'] = [{'id': 1, 'cards': [{'code': code, 'controller': 0} for code in (55144522, 1184620)]}]
        atomic_json(self.store.plan_path(plan['id']), plan)
        self.assertNotIn(plan['id'], {p['id'] for p in self.store.modular.library.for_deck(self.saved)['sources']})
        before = self.store.plan_path(plan['id']).read_bytes()
        self.store.library.edit_tag({'id': self.tags[0], 'name': 'TEST ONLY 主系列', 'revision': 3,
                                     'card_ids': [55144522, 1184620]})
        self.assertIn(plan['id'], {p['id'] for p in self.store.modular.library.for_deck(self.saved)['sources']})
        self.assertEqual(self.store.plan_path(plan['id']).read_bytes(), before)


if __name__ == '__main__': unittest.main()
