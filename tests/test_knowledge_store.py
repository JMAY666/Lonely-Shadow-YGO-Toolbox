"""Atomic publishing/updating and personal data preservation, without an engine."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from knowledge_store import KnowledgeStore
from knowledge_schema import digest
from test_knowledge_schema import fixture


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'knowledge'
        self.inject_failure = None
        def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
        def write(path, value):
            path = Path(path)
            if self.inject_failure and self.inject_failure(path): raise OSError('injected disk failure')
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp')
            tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            tmp.replace(path)
        self.read, self.write = read, write
        self.service = KnowledgeStore(self.root, read, write, cards=lambda: {100: {'id': 100}})

    def tearDown(self): self.temp.cleanup()

    def revision(self): return self.service.registry()['revision']

    def publish(self, doc=None, version='1.0.0'):
        project = self.service.create(document=doc or fixture())
        return self.service.bundle(project['id'], project['revision'], version)

    def install(self, bundle, enable=True):
        preview = self.service.preview(bundle)
        return self.service.install(bundle, preview['digest'], self.revision(), enable=enable)

    def updated(self, bundle, edit):
        doc = deepcopy(bundle['document']); edit(doc)
        return self.publish(doc, '1.1.0')

    def test_project_reopen_roundtrip_raw_source_preserved_and_revisions_server_owned(self):
        project = self.service.create(document=fixture()); original = deepcopy(project['document'])
        doc = deepcopy(original); doc['records']['step']['data']['costs'] = '新费用'
        doc['records']['step']['revision'] = 9999
        saved = self.service.save(project['id'], project['revision'], doc)
        self.assertEqual(saved['document']['records']['step']['revision'], 2)
        self.assertEqual(saved['document']['records']['raw'], original['records']['raw'])
        restarted = KnowledgeStore(self.root, self.read, self.write)
        self.assertEqual(restarted.project(project['id'])['document'], saved['document'])
        with self.assertRaises(ValueError): self.service.save(project['id'], project['revision'], doc)
        doc = deepcopy(saved['document']); del doc['records']['raw']
        deleted = self.service.save(project['id'], saved['revision'], doc)
        self.assertTrue(deleted['document']['records']['raw']['deleted'])

    def test_repeat_install_is_idempotent_and_same_version_other_bytes_rejected(self):
        bundle = self.publish(); self.install(bundle); registry = self.service.registry()
        self.install(bundle)
        self.assertEqual(self.service.registry(), registry)
        changed = deepcopy(bundle); changed['document']['package']['name'] = '异名同版'
        changed['digest'] = digest(changed['document'])
        with self.assertRaises(ValueError): self.service.preview(changed)
        self.assertEqual(self.service.registry(), registry)

    def test_preview_is_read_only_and_corrupted_digest_cannot_be_installed(self):
        bundle = self.publish(); before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.service.preview(bundle)
        self.assertEqual(before, {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        broken = deepcopy(bundle); broken['document']['package']['name'] = 'tampered'
        with self.assertRaises(ValueError): self.install(broken)
        self.assertEqual(self.service.registry()['packages'], {})

    def test_personal_overlay_survives_update_disable_uninstall_and_rollback(self):
        old = self.publish(); self.install(old); pid = old['document']['package']['id']
        personal = deepcopy(old['document']['records']['step']); personal['title'] = '我的标题'
        self.service.overlay(pid, '1.0.0', 'step', personal, '私人备注', self.revision())
        newer = self.updated(old, lambda d: d['records']['step']['data'].update(costs='新版费用'))
        self.install(newer)
        effective = self.service.document(pid)
        self.assertEqual(effective['records']['step']['title'], '我的标题')
        self.assertEqual(effective['records']['step']['data']['costs'], '新版费用')
        self.assertEqual(self.service.document(pid, '1.0.0', effective=False), old['document'])
        self.service.disable(pid, self.revision()); self.assertEqual(self.service.catalog(), [])
        self.service.activate(pid, '1.0.0', self.revision())
        self.assertEqual(self.service.document(pid)['records']['step']['title'], '我的标题')
        self.service.uninstall(pid, self.revision()); self.assertEqual(self.service.catalog(), [])
        self.assertTrue(self.service.registry()['overrides'])
        self.assertEqual(self.service.document(pid, '1.0.0')['records']['step']['title'], '我的标题')

    def test_conflict_never_silently_replaces_local_and_resolves_only_conflicting_fields(self):
        old = self.publish(); self.install(old); pid = old['document']['package']['id']
        local = deepcopy(old['document']['records']['step'])
        local['title'] = '本地标题'; local['data']['costs'] = '本地费用'
        self.service.overlay(pid, '1.0.0', 'step', local, '', self.revision())
        newer = self.updated(old, lambda d: d['records']['step']['data'].update(costs='远程费用'))
        before = self.service.registry()
        self.assertTrue(self.service.preview(newer)['conflicts'])
        with self.assertRaises(ValueError): self.install(newer)
        self.assertEqual(self.service.registry(), before)
        self.install(newer, enable=False)
        self.service.activate(pid, '1.1.0', self.revision(), resolutions={'step': 'incoming'})
        result = self.service.document(pid)['records']['step']
        self.assertEqual(result['title'], '本地标题')
        self.assertEqual(result['data']['costs'], '远程费用')

    def test_failed_install_at_each_write_retains_entire_old_registry(self):
        old = self.publish(); self.install(old)
        newer = self.updated(old, lambda d: d['records']['step']['data'].update(costs='changed'))
        baseline = self.service.registry()
        for needle in ('document.json', 'index.json', 'registry.json'):
            self.inject_failure = lambda path, needle=needle: needle in str(path)
            with self.subTest(needle=needle), self.assertRaises(OSError): self.install(newer)
            self.inject_failure = None
            self.assertEqual(self.service.registry(), baseline)
            pid = old['document']['package']['id']
            self.assertEqual(self.service.document(pid), old['document'])

    def test_checks_cannot_be_forged_in_project_save(self):
        p = self.service.create(document=fixture()); doc = deepcopy(p['document'])
        doc['checks'].append({'id': 'fake', 'target': 'route', 'type': 'engine', 'status': 'passed', 'inputs': {}, 'at': '', 'note': ''})
        with self.assertRaises(ValueError): self.service.save(p['id'], p['revision'], doc)
        with self.assertRaises(ValueError): self.service.review(p['id'], p['revision'], 'route', kind='engine')
        reviewed = self.service.review(p['id'], p['revision'], 'route', '人工核对')
        self.assertEqual(reviewed['inspection']['checks'][-1]['state'], 'passed')

    def test_unsupported_app_is_readable_but_cannot_activate(self):
        doc = fixture(); doc['package']['app_min'] = '999.0.0'; bundle = self.publish(doc)
        self.assertFalse(self.service.preview(bundle)['compatible'])
        self.install(bundle, enable=False)
        with self.assertRaises(ValueError): self.service.activate(doc['package']['id'], '1.0.0', self.revision())
        self.assertEqual(self.service.catalog(), [])

    def test_failed_project_save_never_moves_its_visible_revision(self):
        project = self.service.create(document=fixture())
        edited = deepcopy(project['document']); edited['records']['step']['data']['costs'] = 'changed'
        self.inject_failure = lambda path: path.name == 'registry.json'
        with self.assertRaises(OSError): self.service.save(project['id'], project['revision'], edited)
        self.inject_failure = None
        self.assertEqual(self.service.project(project['id'])['document'], project['document'])
        self.assertEqual(self.service.project(project['id'])['revision'], project['revision'])
        # A retry with different edits may reuse the revision number, not overwrite a referenced snapshot.
        edited['records']['step']['data']['costs'] = 'different retry'
        saved = self.service.save(project['id'], project['revision'], edited)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(saved['document']['records']['step']['data']['costs'], 'different retry')

    def test_failed_index_write_can_be_retried_then_reopened(self):
        bundle = self.publish()
        self.inject_failure = lambda path: path.name == 'index.json'
        with self.assertRaises(OSError): self.install(bundle)
        self.inject_failure = None
        self.install(bundle)
        self.assertTrue(list(self.root.glob('packages/*/index.json')))
        self.assertEqual(KnowledgeStore(self.root, self.read, self.write).catalog()[0]['origin'], 'knowledge')

    def test_incoming_conflict_resolution_can_delete_a_field_and_handles_dotted_keys(self):
        doc = fixture(); doc['records']['step']['data']['custom.field'] = 'original'
        old = self.publish(doc); self.install(old); pid = doc['package']['id']
        local = deepcopy(old['document']['records']['step'])
        local['data']['custom.field'] = 'local'; local['title'] = 'Personal title'
        self.service.overlay(pid, '1.0.0', 'step', local, 'retained note', self.revision())
        newer = self.updated(old, lambda d: d['records']['step']['data'].pop('custom.field'))
        self.install(newer, enable=False)
        self.service.activate(pid, '1.1.0', self.revision(), resolutions={'step': 'incoming'})
        item = self.service.document(pid)['records']['step']
        self.assertNotIn('custom.field', item['data']); self.assertEqual(item['title'], 'Personal title')

    def test_installed_registry_digest_is_the_expected_identity(self):
        bundle = self.publish(); self.install(bundle); pid = bundle['document']['package']['id']
        path = next(self.root.glob('packages/*/document.json'))
        altered = self.read(path); altered['document']['package']['name'] = 'tamper'
        altered['digest'] = digest(altered['document']); self.write(path, altered)
        with self.assertRaises(ValueError): self.service.document(pid)

    def test_publication_preserves_a_full_editable_release(self):
        bundle = self.publish()
        release = next(self.root.glob('projects/*/releases/*.json'))
        self.assertEqual(self.read(release), bundle)

    def test_new_release_reuses_unaffected_record_indexes(self):
        old = self.publish(); self.install(old)
        pid = old['document']['package']['id']
        before = self.service.index_info(pid, '1.0.0')
        newer = self.updated(old, lambda d: d['records']['step']['data'].update(costs='changed'))
        self.install(newer)
        after = self.service.index_info(pid, '1.1.0')
        self.assertEqual(after['statistics']['generated'], 1)
        self.assertEqual(after['statistics']['reused'], 4)
        self.assertEqual(after['records']['other'], before['records']['other'])
        self.assertIn('changed', next(row for row in self.service.catalog(['step']) if row['record']['id'] == 'step')['search_text'])


if __name__ == '__main__': unittest.main()
