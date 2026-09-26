"""Exercise review boundaries, exact-content caches and recoverable batch publication."""
from contextlib import closing, redirect_stdout
import io
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from annotation_batch_support import atomic_json, cached_result, contained_path, content_hash, read_json
from annotation_pipeline import Pipeline
import check_annotation_source_batch as checker


class AnnotationPipelineTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / '.local/test-runs'
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='annotation-pipeline-', dir=temporary_root)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        (self.runtime / 'script').mkdir()
        self.pack = self.root / 'pack'
        self.pack.mkdir()
        trainer = self.root / 'src/trainer'
        trainer.mkdir(parents=True)
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/validator.py').write_text('VERSION = 1\n', encoding='utf-8')
        (trainer / 'annotation-tags.json').write_bytes((ROOT / 'src/trainer/annotation-tags.json').read_bytes())
        (self.root / 'docs').mkdir()
        self.desc = '①：从卡组把1只「测试」怪兽加入手卡。'
        self.flavor = '测试用通常怪兽描述。'
        with closing(sqlite3.connect(self.runtime / 'cards.cdb')) as db:
            db.execute('CREATE TABLE datas(id INTEGER PRIMARY KEY, ot INTEGER, alias INTEGER, setcode INTEGER, type INTEGER, atk INTEGER, def INTEGER, level INTEGER, race INTEGER, attribute INTEGER, category INTEGER)')
            db.execute('CREATE TABLE texts(id INTEGER PRIMARY KEY, name TEXT, desc TEXT, str1 TEXT, str2 TEXT, str3 TEXT, str4 TEXT, str5 TEXT, str6 TEXT, str7 TEXT, str8 TEXT, str9 TEXT, str10 TEXT, str11 TEXT, str12 TEXT, str13 TEXT, str14 TEXT, str15 TEXT, str16 TEXT)')
            for code in range(20000001, 20000006):
                db.execute('INSERT INTO datas VALUES(?,?,?,?,?,0,0,1,1,1,0)',
                           (code, 0, 0, 0x1d5 if code != 20000005 else 0,
                            0x4001 if code == 20000003 else 0x11 if code == 20000005 else 2))
                db.execute('INSERT INTO texts(id,name,desc) VALUES(?,?,?)',
                           (code, f'测试卡{code}', self.flavor if code == 20000005 else self.desc))
            db.commit()
        records = []
        for code in range(20000001, 20000006):
            sources = []
            for kind in ('raw', 'text'):
                path = self.pack / (f'{code}.' + ('html' if kind == 'raw' else 'txt'))
                path.write_text(f'fixture OCG source {code}', encoding='utf-8')
            source = {'id': f'card-{code}', 'kind': 'card', 'status': 'saved',
                      'final_url': f'https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid={code}&ope=2&request_locale=ja',
                      'page_title': f'测试官方页{code}'}
            for kind in ('raw', 'text'):
                source[kind + '_path'] = f'{code}.' + ('html' if kind == 'raw' else 'txt')
                source[kind + '_sha256'] = content_hash((self.pack / source[kind + '_path']).read_bytes())
            sources.append(source)
            records.append({'code': code, 'official_cid': code, 'identity_status': 'candidate', 'sources': sources})
        atomic_json(self.pack / 'manifest.json', {'version': 1, 'cards': records})
        self.pipeline = Pipeline(self.root)
        self.existing = {'version': 1, 'id': 'fixture', 'cards': {}}
        # A reviewed card outside the selected cohort must survive unchanged.
        self.existing['cards']['20000004'] = self.entry(20000004)
        atomic_json(self.pipeline.formal, self.existing)
        self.baseline = self.pipeline.formal.read_bytes()
        self.checker_root = patch.object(checker, 'ROOT', self.root)
        self.checker_root.start()
        self.addCleanup(self.checker_root.stop)

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(ROOT / '.local/test-runs'))
        self.temporary.cleanup()

    def entry(self, code):
        from card_annotations import digest
        source = read_json(self.pack / 'manifest.json')['cards'][code - 20000001]['sources'][0]
        return {'code': code, 'frozen_text': self.desc, 'text_digest': digest(self.desc),
                'review': {'status': 'reviewed', 'origin': 'manual', 'checked_on': '2026-09-26', 'basis': 'Explicit fixture review'},
                'sources': [{'id': source['id'], 'title': source['page_title'], 'url': source['final_url'],
                             'format': 'OCG', 'checked_on': '2026-09-26'}],
                'effects': [{'key': 'm1', 'kind': 'numbered', 'number': 1, 'block': 'm',
                             'effect_type': 'spell_activation', 'tags': ['etag:add-hand'],
                             'structure': {'activation': {'timing': 'main_phase_self', 'zones': ['spell'],
                                                          'conditions': [], 'fast_effect': False},
                                           'cost': [], 'targeting': [], 'usage': [],
                                           'processing': [{'action': 'add_hand', 'count': 1, 'from_zones': ['deck'],
                                                           'to_zones': ['hand'], 'selector': {'text': '1只测试怪兽'}}]},
                             'notes': [{'text': 'Fixture evidence, not a real card rule', 'source_refs': [source['id']]}]}],
                'relations': [], 'notes': []}

    def prepare(self, **kwargs):
        return self.pipeline.prepare('trial', self.runtime, self.pack, codes=[20000001, 20000002], **kwargs)

    def decisions(self, pending=False):
        document = {'version': 1, 'cards': {'20000001': self.entry(20000001)}, 'pending': [],
                    'query_cases': [], 'semantic_cases': [], 'purpose_cases': [], 'source_bindings': {}}
        if pending:
            document['pending'] = [{'code': 20000002, 'status': 'requires_schema', 'reason': 'Fixture needs a separate effect model'}]
        else:
            document['cards']['20000002'] = self.entry(20000002)
        for code in map(int, document['cards']):
            for zone, expected in [('deck', ['m1']), ('grave', [])]:
                document['query_cases'].append({'code': code, 'query': {'from_zone': zone, 'etags': ['etag:add-hand']},
                                                'expected_keys': expected, 'reason': 'Distinct processing source'})
            document['semantic_cases'].append({'code': code, 'path': ['effects', 0, 'structure', 'processing', 0, 'from_zones'],
                                               'expected': ['deck'], 'reason': 'Do not confuse cost and resolution'})
        path = self.root / 'decisions.json'
        atomic_json(path, document)
        return path

    def assemble(self, pending=False):
        self.prepare()
        return self.pipeline.assemble('trial', self.decisions(pending))

    def verify(self, full=False):
        with redirect_stdout(io.StringIO()):
            return self.pipeline.verify('trial', full=full)

    def test_prepare_complete_series_and_resume_without_auto_review(self):
        result = self.pipeline.prepare('series', self.runtime, self.pack, series_ids=['set:1d5'])
        self.assertEqual((result['prepared'], result['skipped'], result['reviewed']), (2, 1, 0))
        folder, task, ledger = self.pipeline.task('series')
        self.assertTrue(task['selection']['complete_series'])
        templates = read_json(folder / 'templates.json')
        self.assertTrue(all(d['review'] == {'status': 'draft', 'origin': 'auto', 'checked_on': '', 'basis': ''}
                            for d in templates['cards'].values()))
        self.assertEqual(self.pipeline.status('series')['integrated_count'], 0)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.pipeline.prepare('series', self.runtime, self.pack, series_ids=['set:1d5'])
        self.assertEqual(self.pipeline.formal.read_bytes(), self.baseline)

    def test_draft_templates_remain_pending_and_cannot_be_auto_approved(self):
        self.prepare()
        folder = self.pipeline.folder('trial')
        ledger = self.pipeline.assemble('trial', folder / 'templates.json')
        self.assertEqual((ledger['reviewed_count'], ledger['pending_count']), (0, 2))
        draft = read_json(folder / 'templates.json')
        draft['cards']['20000001']['review']['status'] = 'reviewed'
        atomic_json(folder / 'templates.json', draft)
        with self.assertRaisesRegex(ValueError, 'manual review'):
            self.pipeline.assemble('trial', folder / 'templates.json')

    def test_compact_decisions_fill_only_frozen_fields_and_selected_sources(self):
        self.prepare()
        path = self.decisions()
        document = read_json(path)
        for code, entry in document['cards'].items():
            for key in ('code', 'frozen_text', 'text_digest'):
                entry.pop(key)
            entry.pop('sources')
            entry['source_ids'] = ['card-' + code]
            entry['effects'] = {e['key']: {k: v for k, v in e.items() if k not in ('key', 'kind', 'number', 'block')}
                                for e in entry['effects']}
        atomic_json(path, document)
        self.pipeline.assemble('trial', path)
        self.assertEqual(self.verify()['cards'], 2)
        self.assertEqual(read_json(self.pipeline.folder('trial') / 'candidate-document.json')['cards']['20000001'],
                         {**self.entry(20000001), 'sources': [{**self.entry(20000001)['sources'][0], 'region': 'Japan'}]})

    def test_pending_partition_and_previous_entries_preserved(self):
        ledger = self.assemble(pending=True)
        candidate = read_json(self.pipeline.folder('trial') / 'candidate-document.json')
        self.assertEqual(candidate['cards']['20000004'], self.existing['cards']['20000004'])
        self.assertNotIn('20000002', candidate['cards'])
        self.assertEqual((ledger['reviewed_count'], ledger['pending_count']), (1, 1))
        self.assertEqual(self.verify()['cards'], 1)
        self.assertEqual(self.pipeline.formal.read_bytes(), self.baseline)

    def test_cache_hit_rehashes_sources_and_full_check_bypasses_cache(self):
        self.assemble()
        first, second, full = self.verify(), self.verify(), self.verify(full=True)
        self.assertEqual((first['cache_hit'], second['cache_hit'], full['cache_hit']), (False, True, False))
        self.assertEqual(second['source_files'], 4)
        self.assertEqual(full['search_cases'], 4)

    def test_same_size_same_mtime_changed_source_cannot_hit_cache(self):
        self.assemble()
        self.verify()
        path = self.pack / '20000001.html'
        stat = path.stat()
        data = path.read_bytes()
        path.write_bytes(b'X' + data[1:])
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, 'snapshot hash mismatch'):
            self.verify()
        self.assertEqual(self.pipeline.status('trial')['verification']['status'], 'failed')
        self.assertEqual(self.pipeline.formal.read_bytes(), self.baseline)

    def test_vocabulary_and_validator_changes_invalidate_success_cache(self):
        self.assemble()
        self.verify()
        vocabulary = read_json(self.pipeline.tags)
        vocabulary['version_note'] = 'Changed fixture vocabulary version'
        atomic_json(self.pipeline.tags, vocabulary)
        self.assertFalse(self.verify()['cache_hit'])
        self.assertTrue(self.verify()['cache_hit'])
        (self.root / 'scripts/validator.py').write_text('VERSION = 2\n', encoding='utf-8')
        self.assertFalse(self.verify()['cache_hit'])

    def test_runtime_text_change_fails_even_after_success_cache(self):
        self.assemble()
        self.verify()
        with closing(sqlite3.connect(self.runtime / 'cards.cdb')) as db:
            db.execute('UPDATE texts SET desc=? WHERE id=20000001', (self.desc + '改版',))
            db.commit()
        with self.assertRaises((AssertionError, ValueError)):
            self.verify()

    def test_frozen_task_and_assembled_document_cannot_be_mutated_silently(self):
        self.assemble()
        folder = self.pipeline.folder('trial')
        candidate = read_json(folder / 'candidate-document.json')
        candidate['cards']['20000001']['effects'][0]['structure']['cost'] = [{'kind': 'discard', 'text': 'invented'}]
        atomic_json(folder / 'candidate-document.json', candidate)
        with self.assertRaisesRegex(ValueError, 'output changed'):
            self.verify()
        task = read_json(folder / 'task.json')
        task['cards'][0]['desc'] += '改版'
        atomic_json(folder / 'task.json', task)
        with self.assertRaisesRegex(ValueError, 'Frozen task changed'):
            self.pipeline.status('trial')

    def test_apply_revalidates_backups_preserves_and_is_idempotent(self):
        self.assemble(pending=True)
        self.verify()
        with redirect_stdout(io.StringIO()):
            first = self.pipeline.apply('trial', 'docs/batch.json')
            second = self.pipeline.apply('trial', 'docs/batch.json')
        self.assertEqual((first['new'], second['new'], second['idempotent']), (1, 0, True))
        candidate = read_json(self.pipeline.formal)
        self.assertEqual(candidate['cards']['20000004'], self.existing['cards']['20000004'])
        self.assertNotIn('20000002', candidate['cards'])
        backups = list(self.pipeline.folder('trial').glob('baseline-*.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), self.baseline)
        self.assertTrue(self.pipeline.status('trial')['verification']['full'])
        self.assertEqual(self.pipeline.status('trial')['phase'], 'integrated')

    def test_apply_blocks_concurrent_edit_and_keeps_lock_owned_by_other_writer(self):
        self.assemble()
        current = read_json(self.pipeline.formal)
        current['unrelated_change'] = 'Preserve this change'
        atomic_json(self.pipeline.formal, current)
        changed = self.pipeline.formal.read_bytes()
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'document changed'):
            self.pipeline.apply('trial', 'docs/batch.json')
        self.assertEqual(self.pipeline.formal.read_bytes(), changed)
        lock = self.pipeline.private / 'publication.lock'
        lock.write_text('another writer', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'publication is active'):
            self.pipeline.apply('trial', 'docs/batch.json')
        self.assertEqual(lock.read_text('utf-8'), 'another writer')

    def test_apply_failure_preserves_original_and_saved_backup(self):
        self.assemble()
        from annotation_batch_support import atomic_json as real_write
        def fail_document(path, value):
            if Path(path) == self.pipeline.formal:
                raise OSError('fixture failed publication')
            return real_write(path, value)
        with patch('annotation_pipeline.atomic_json', side_effect=fail_document), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError, 'failed publication'):
                self.pipeline.apply('trial', 'docs/batch.json')
        self.assertEqual(self.pipeline.formal.read_bytes(), self.baseline)
        self.assertEqual(next(self.pipeline.folder('trial').glob('baseline-*.json')).read_bytes(), self.baseline)
        with redirect_stdout(io.StringIO()):
            result = self.pipeline.apply('trial', 'docs/batch.json')
        self.assertEqual(result['new'], 2)

    def test_publication_cannot_leave_docs_or_overwrite_different_manifest(self):
        self.assemble()
        with self.assertRaisesRegex(ValueError, 'workspace docs'):
            self.pipeline.apply('trial', '../outside.json')
        atomic_json(self.root / 'docs/batch.json', {'unrelated': 'keep'})
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'different public manifest'):
            self.pipeline.apply('trial', 'docs/batch.json')
        self.assertEqual(read_json(self.root / 'docs/batch.json'), {'unrelated': 'keep'})
        self.assertEqual(self.pipeline.formal.read_bytes(), self.baseline)

    def test_duplicates_and_source_escape_are_rejected_and_broken_cache_is_miss(self):
        path = self.root / 'duplicate.json'
        path.write_text('{"cards":{},"cards":{}}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            read_json(path)
        with self.assertRaisesRegex(ValueError, 'relative'):
            contained_path(self.pack, '../decisions.json')
        for value in ([], {'protocol': 1, 'result': []}):
            atomic_json(path, value)
            self.assertIsNone(cached_result(path, 'fixture'))

    def test_assemble_rejects_incomplete_segments_and_existing_conflicts(self):
        self.prepare()
        path = self.decisions()
        data = read_json(path)
        data['cards']['20000001']['effects'] = []
        atomic_json(path, data)
        with self.assertRaisesRegex(ValueError, 'segments'):
            self.pipeline.assemble('trial', path)
        atomic_json(path, {'version': 1, 'cards': {'20000004': self.entry(20000004)}})
        with self.assertRaisesRegex(ValueError, 'outside the frozen task'):
            self.pipeline.assemble('trial', path)

    def test_readable_sources_never_count_as_reviewed_and_missing_inputs_are_pending(self):
        self.prepare()
        path = self.root / 'empty-decisions.json'
        atomic_json(path, {'version': 1, 'cards': {}, 'pending': []})
        ledger = self.pipeline.assemble('trial', path)
        self.assertEqual((ledger['reviewed_count'], ledger['pending_count'], ledger['integrated_count']), (0, 2, 0))
        self.assertEqual(self.pipeline.status('trial')['source_candidates'], 2)
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'cohort review'):
            self.pipeline.apply('trial', 'docs/batch.json')

    def test_parallel_packets_preserve_text_and_never_change_review_status(self):
        self.prepare()
        result = self.pipeline.packet('trial', [20000001, 20000002])
        self.assertEqual((result['packets'], result['reviewed']), (2, 0))
        packet = read_json(self.pipeline.folder('trial') / 'evidence/20000001.json')
        self.assertEqual(packet['sources'][0]['text'], (self.pack / '20000001.txt').read_text('utf-8'))
        self.assertEqual(packet['status'], 'prepared_only')
        self.assertEqual(packet['identity_status'], 'candidate')
        (self.pack / '20000002.txt').write_text('corrupted source', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'snapshot hash mismatch'):
            self.pipeline.packet('trial', [20000002])

    def test_normal_monster_flavor_preserved_without_fabricated_effects(self):
        from card_annotations import digest
        self.pipeline.prepare('normal', self.runtime, self.pack, codes=[20000005])
        entry = self.entry(20000005)
        entry.update({'no_effect': True, 'effects': [], 'frozen_text': self.flavor,
                      'text_digest': digest(self.flavor)})
        entry['notes'] = [{'text': 'Fixture normal monster identity manually reviewed', 'source_refs': ['card-20000005']}]
        path = self.root / 'normal-decisions.json'
        atomic_json(path, {'version': 1, 'cards': {'20000005': entry},
                           'query_cases': [{'code': 20000005, 'query': {'etags': ['etag:add-hand']},
                                            'expected_keys': [], 'reason': 'Flavor has no card effect'}]})
        self.pipeline.assemble('normal', path)
        with redirect_stdout(io.StringIO()):
            result = self.pipeline.verify('normal', full=True)
        self.assertEqual(result['cards'], 1)
        self.assertEqual(read_json(self.pipeline.folder('normal') / 'candidate-document.json')['cards']['20000005'], entry)

    def test_no_effect_marker_cannot_skip_spell_segments(self):
        self.prepare()
        path = self.decisions()
        data = read_json(path)
        data['cards']['20000001'].update({'no_effect': True, 'effects': []})
        atomic_json(path, data)
        with self.assertRaisesRegex(ValueError, 'segments'):
            self.pipeline.assemble('trial', path)

    def test_same_batch_operation_lock_blocks_assembly_without_touching_inputs(self):
        self.prepare()
        path = self.decisions()
        lock = self.pipeline.folder('trial') / 'operation.lock'
        lock.write_text('another operation', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Batch is busy'):
            self.pipeline.assemble('trial', path)
        self.assertEqual(lock.read_text('utf-8'), 'another operation')
        self.assertEqual(self.pipeline.formal.read_bytes(), self.baseline)

    def test_apply_detects_manually_changed_candidate_after_verification(self):
        self.assemble()
        original_verify = self.pipeline.verify
        def altered_candidate(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            path = self.pipeline.folder('trial') / 'candidate-document.json'
            candidate = read_json(path)
            candidate['unreviewed_edit'] = True
            atomic_json(path, candidate)
            return result
        with patch.object(self.pipeline, 'verify', side_effect=altered_candidate), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'changed after verification'):
                self.pipeline.apply('trial', 'docs/batch.json')
        self.assertEqual(self.pipeline.formal.read_bytes(), self.baseline)

    def test_normal_pendulum_cannot_drop_pendulum_effect_with_no_effect_marker(self):
        from card_annotations import digest
        with closing(sqlite3.connect(self.runtime / 'cards.cdb')) as db:
            db.execute('UPDATE datas SET type=? WHERE id=20000005', (0x1000011,))
            db.commit()
        self.pipeline.prepare('pendulum', self.runtime, self.pack, codes=[20000005])
        entry = self.entry(20000005)
        entry.update({'no_effect': True, 'effects': [], 'frozen_text': self.flavor, 'text_digest': digest(self.flavor)})
        path = self.root / 'pendulum-decisions.json'
        atomic_json(path, {'version': 1, 'cards': {'20000005': entry}})
        with self.assertRaisesRegex(ValueError, 'segments'):
            self.pipeline.assemble('pendulum', path)

    def test_compact_sources_cannot_relabel_another_locale_as_japanese(self):
        from annotation_pipeline import compile_entry
        self.prepare()
        _, task, _ = self.pipeline.task('trial')
        row = task['cards'][0]
        row['source_record']['sources'][0]['final_url'] = row['source_record']['sources'][0]['final_url'].replace('locale=ja', 'locale=en')
        entry = self.entry(20000001)
        entry.pop('sources')
        entry['source_ids'] = ['card-20000001']
        with self.assertRaisesRegex(ValueError, 'Japanese KONAMI OCG'):
            compile_entry(row, entry)


if __name__ == '__main__':
    unittest.main()
