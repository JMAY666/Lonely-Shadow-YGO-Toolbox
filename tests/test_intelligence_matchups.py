from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import runpy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json
from desktop_runtime import ServiceLock
from plan_tags import normalized
import test_store
from test_plan_library import sample


def fixture_catalog():
    """Synthetic references and cards keep importer tests independent of research."""
    source = {'id': 'fixture-report', 'title': '合成赛事资料', 'url': 'https://example.org/report',
              'published_at': '2026-09-01', 'period': '2026-08', 'kind': 'metagame', 'note': '隔离测试来源'}
    guide = {'id': 'ocg-fixture', 'topic': 'OCG · 合成主题', 'title': '合成主题应对', 'format': 'OCG',
             'period': '2026-07—2026-09', 'summary': '资料概述', 'recognition': '识别线索',
             'priorities': '优先应对', 'warnings': '例外情况', 'metagame': '赛事样本说明',
             'source_ids': ['fixture-report'],
             'steps': [{'opponent': 23995346, 'action': '发动效果', 'timing': '发动时',
                        'condition': '合成条件', 'responses': [{'cards': [55144522], 'mode': 'alternative',
                        'method': '', 'condition': '合成应对条件', 'expected': '合成预期', 'note': ''}], 'note': ''}]}
    return {'version': '2026-09-20', 'reviewed_at': '2026-09-20', 'window': '2026-07—2026-09',
            'sources': [source], 'guides': [guide]}


class MatchupCatalogTests(unittest.TestCase):
    setUp = test_store.StoreTests.setUp
    tearDown = test_store.StoreTests.tearDown

    def command(self, op, value=None):
        return self.store.intelligence.command({'op': op, 'value': value or {},
                                               'revision': self.store.library.document()['revision']})

    def import_catalog(self, catalog=None):
        with patch('intelligence_matchups.load_catalog', return_value=catalog or fixture_catalog()):
            return self.command('matchups.import')

    def run_cli(self, apply=False):
        script = Path(__file__).resolve().parents[1] / 'scripts/import_matchups.py'
        argv = [str(script), '--runtime', str(self.root)] + (['--apply'] if apply else [])
        output = io.StringIO()
        with patch.object(sys, 'argv', argv), patch('intelligence_matchups.load_catalog', return_value=fixture_catalog()), redirect_stdout(output):
            try: runpy.run_path(str(script), run_name='__main__')
            except FileNotFoundError as error: self.fail(f'Required import CLI is unavailable: {error}')
        return json.loads(output.getvalue())

    def stored_research_record(self):
        catalog = fixture_catalog(); guide = catalog['guides'][0]
        topic = self.command('topic.save', {'name': guide['topic']})['saved_id']
        saved = self.command('record.save', {'topic_id': topic, 'title': guide['title'], 'steps': guide['steps']})
        identifier = saved['saved_id']
        document = read_json(self.store.library.path)
        document['intelligence']['records'][identifier]['research'] = {
            'catalog_version': catalog['version'], 'reviewed_at': catalog['reviewed_at'],
            **{key: guide[key] for key in ('format', 'period', 'summary', 'recognition', 'priorities', 'warnings', 'metagame')},
            'sources': catalog['sources'], 'edited': False, 'steps_edited': False}
        atomic_json(self.store.library.path, document)
        return self.store.intelligence.snapshot()['records'][identifier]

    def test_record_editor_preserves_provenance_and_marks_actual_content_edits(self):
        record = self.stored_research_record()
        unchanged = self.command('record.save', record)['records'][record['id']]
        self.assertEqual(unchanged.get('research'), record['research'])
        value = deepcopy(unchanged); value.pop('research'); value['note'] = '个人补充'
        edited = self.command('record.save', value)['records'][record['id']]
        self.assertEqual(edited['research'], {**record['research'], 'edited': True})
        self.assertEqual(Store(self.root).intelligence.snapshot()['records'][record['id']], edited)

    def test_research_editor_updates_notes_without_forging_sources_or_version(self):
        record = self.stored_research_record()
        value = deepcopy(record)
        value['research'] = {'summary': '个人概述', 'recognition': '个人识别线索', 'priorities': '个人优先级',
                             'warnings': '', 'metagame': '个人样本说明', 'format': 'forged', 'period': 'forged',
                             'catalog_version': 'forged', 'reviewed_at': 'forged', 'edited': False,
                             'sources': [{'url': 'javascript:alert(1)'}]}
        saved = self.command('record.save', value)['records'][record['id']]
        expected = {**record['research'], **{key: value['research'][key]
                    for key in ('summary', 'recognition', 'priorities', 'warnings', 'metagame')}, 'edited': True}
        self.assertEqual(saved.get('research'), expected)
        saved['research']['edited'] = False
        self.assertTrue(self.command('record.save', saved)['records'][record['id']]['research']['edited'])

    def test_legacy_record_cannot_gain_forged_research_metadata(self):
        guide = fixture_catalog()['guides'][0]
        topic = self.command('topic.save', {'name': '个人主题'})['saved_id']
        value = {'topic_id': topic, 'title': guide['title'], 'steps': guide['steps']}
        saved = self.command('record.save', value)
        record = saved['records'][saved['saved_id']]
        self.assertNotIn('research', record)
        before = self.store.library.path.read_bytes()
        with self.assertRaises(ValueError):
            self.command('record.save', {**record, 'research': {'catalog_version': 'forged'}})
        self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_deleted_research_can_be_saved_as_personal_with_complete_reference_copy(self):
        record = self.stored_research_record()
        self.command('record.remove', {'id': record['id']})
        value = deepcopy(record)
        value.pop('id')
        value['reference_copy'] = '原始参考副本\n' + json.dumps(value.pop('research'), ensure_ascii=False) + '\n' + '保留来源' * 1200
        saved = self.command('record.save', value)
        personal = saved['records'][saved['saved_id']]
        self.assertNotIn('research', personal)
        self.assertEqual(personal.get('reference_copy'), value['reference_copy'])
        self.assertEqual(Store(self.root).intelligence.snapshot()['records'][personal['id']], personal)

    def test_invalid_research_edit_preserves_the_previous_document(self):
        record = self.stored_research_record()
        before = self.store.library.path.read_bytes()
        for index, research in enumerate((None, [], {'summary': 'x' * 4001}, {'recognition': 5})):
            with self.subTest(case=index):
                with self.assertRaises(ValueError): self.command('record.save', {**record, 'research': research})
                self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_import_separates_formats_and_preserves_existing_knowledge_tags_and_plans(self):
        catalog = fixture_catalog()
        catalog['guides'].append({**deepcopy(catalog['guides'][0]), 'id': 'md-fixture',
                                  'topic': 'Master Duel · 合成主题', 'format': 'Master Duel'})
        original_catalog = deepcopy(catalog)
        self.store.library.edit_tag({'revision': 0, 'name': '个人 TAG', 'card_ids': [1184620]})
        folder = self.command('folder.save', {'name': '个人文件夹'})['saved_id']
        self.command('handtrap.save', {'code': 55144522, 'folder_id': folder, 'note': '个人手坑备注'})
        self.command('breaker.save', {'code': 23995346, 'note': '个人解场备注'})
        self.command('endboard.save', {'code': 1184620, 'note': '个人终场备注'})
        topic = self.command('topic.save', {'name': catalog['guides'][0]['topic'], 'note': '个人主题'})['saved_id']
        personal = self.command('record.save', {'topic_id': topic, 'title': '个人断点',
                                               'steps': catalog['guides'][0]['steps']})['saved_id']
        plan = sample(); plan_path = self.store.plan_path(plan['id']); atomic_json(plan_path, plan)
        plan_before = plan_path.read_bytes()
        before = read_json(self.store.library.path)
        imported = self.import_catalog(catalog)
        self.assertEqual(imported['import_result'], {'added': 2, 'unchanged': 0, 'missing': [],
                                                    'changed': True, 'version': '2026-09-20'})
        self.assertEqual(imported['revision'], before['revision'] + 1)
        self.assertEqual(len(imported['topics']), 3)
        self.assertEqual(len(imported['records']), 3)
        self.assertEqual(imported['records'][personal], before['intelligence']['records'][personal])
        self.assertEqual(imported['topics'][topic], before['intelligence']['topics'][topic])
        for key in ('handtraps', 'breakers', 'endboards', 'folders'):
            self.assertEqual(imported[key], before['intelligence'][key])
        self.assertEqual(read_json(self.store.library.path)['entries'], before['entries'])
        self.assertEqual(read_json(self.store.root / 'backups/tags' / f"{before['revision']}.json"), before)
        self.assertEqual(plan_path.read_bytes(), plan_before)
        for guide_id, format_name in (('ocg-fixture', 'OCG'), ('md-fixture', 'Master Duel')):
            identifier = 'matchup:2026-09-20:' + guide_id
            record = imported['records'][identifier]
            self.assertEqual(record['topic_id'], 'topic:' + identifier)
            self.assertEqual(record['research']['format'], format_name)
            self.assertEqual(record['research']['sources'], catalog['sources'])
            self.assertFalse(record['research']['edited'])
            self.assertEqual(record['status'], '待核对')
        self.assertEqual(Store(self.root).intelligence.snapshot()['records'], imported['records'])
        self.assertEqual(catalog, original_catalog)

    def test_import_is_idempotent_and_does_not_restore_manually_edited_text(self):
        imported = self.import_catalog(); identifier = 'matchup:2026-09-20:ocg-fixture'
        before = self.store.library.path.read_bytes()
        repeated = self.import_catalog()
        self.assertEqual(repeated['import_result']['unchanged'], 1)
        self.assertFalse(repeated['import_result']['changed'])
        self.assertEqual(repeated['revision'], imported['revision'])
        self.assertEqual(self.store.library.path.read_bytes(), before)
        record = deepcopy(imported['records'][identifier]); record['title'] = '个人修订标题'
        record['steps'][0]['note'] = '个人步骤备注'; record['research']['summary'] = '个人修订概述'
        edited = self.command('record.save', record)
        again = self.import_catalog()
        self.assertEqual(again['records'][identifier], edited['records'][identifier])
        self.assertEqual(again['revision'], edited['revision'])

    def test_same_named_personal_topic_remains_editable_after_import(self):
        catalog = fixture_catalog(); name = catalog['guides'][0]['topic']
        personal = self.command('topic.save', {'name': name.lower(), 'note': '个人资料'})['saved_id']
        imported = self.import_catalog(catalog)
        topic_id = 'topic:matchup:2026-09-20:ocg-fixture'
        self.assertNotEqual(normalized(imported['topics'][topic_id]['name']), normalized(name))
        self.assertEqual(imported['topics'][topic_id]['name'], name + '（资料版 2026-09-20）')
        self.assertEqual(imported['topics'][personal]['note'], '个人资料')
        saved = self.command('topic.save', {**imported['topics'][personal], 'note': '导入后仍可修改'})
        self.assertEqual(saved['topics'][personal]['note'], '导入后仍可修改')
        self.assertEqual(saved['topics'][topic_id], imported['topics'][topic_id])

    def test_same_named_import_uses_unique_suffixes_without_renaming_existing_topics(self):
        catalog = fixture_catalog(); name = catalog['guides'][0]['topic']
        existing_names = [name, name + '（资料版 2026-09-20）', name + '（资料版 2026-09-20 · 2）']
        for previous in existing_names: self.command('topic.save', {'name': previous, 'note': '保留'})
        imported = self.import_catalog(catalog)
        topic_id = 'topic:matchup:2026-09-20:ocg-fixture'
        self.assertEqual(imported['topics'][topic_id]['name'], name + '（资料版 2026-09-20 · 3）')
        self.assertEqual([topic['name'] for key, topic in imported['topics'].items() if key != topic_id], existing_names)
        before = self.store.library.path.read_bytes()
        repeated = self.import_catalog(catalog)
        self.assertEqual(repeated['revision'], imported['revision'])
        self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_same_named_long_topic_gets_an_editable_length_limited_import_name(self):
        catalog = fixture_catalog(); name = 'OCG · ' + '长' * 74
        catalog['guides'][0]['topic'] = name
        personal = self.command('topic.save', {'name': name})['saved_id']
        imported = self.import_catalog(catalog)
        topic_id = 'topic:matchup:2026-09-20:ocg-fixture'
        topic = imported['topics'][topic_id]
        self.assertLessEqual(len(topic['name']), 80)
        self.assertTrue(topic['name'].endswith('（资料版 2026-09-20）'))
        saved = self.command('topic.save', {**topic, 'note': '可直接保存'})
        self.assertEqual(saved['topics'][topic_id]['note'], '可直接保存')
        self.assertEqual(saved['topics'][personal]['name'], name)

    def test_removed_record_can_be_reimported_without_replacing_renamed_topic(self):
        imported = self.import_catalog(); identifier = 'matchup:2026-09-20:ocg-fixture'
        topic = imported['records'][identifier]['topic_id']
        self.command('topic.save', {'id': topic, 'name': '我重命名的主题', 'note': '保留主题备注'})
        self.command('record.remove', {'id': identifier})
        restored = self.import_catalog()
        self.assertEqual(restored['import_result']['added'], 1)
        self.assertEqual(restored['topics'][topic]['name'], '我重命名的主题')
        self.assertEqual(restored['topics'][topic]['note'], '保留主题备注')
        self.assertEqual(len(restored['topics']), 1)
        self.assertIn(identifier, restored['records'])

    def test_missing_card_ids_are_imported_explicitly_and_remain_editable(self):
        catalog = fixture_catalog()
        catalog['guides'][0]['steps'][0]['opponent'] = 99900001
        imported = self.import_catalog(catalog); identifier = 'matchup:2026-09-20:ocg-fixture'
        self.assertEqual(imported['import_result']['missing'], [{'code': 99900001,
                         'guide_id': 'ocg-fixture', 'record_id': identifier}])
        self.assertEqual(imported['records'][identifier]['steps'][0]['opponent'], 99900001)
        self.assertTrue(imported['cards']['99900001']['missing'])
        record = imported['records'][identifier]; record['note'] = '缺卡时仍可补充'
        saved = self.command('record.save', record)
        self.assertEqual(saved['records'][identifier]['steps'][0]['opponent'], 99900001)
        record['steps'][0]['opponent'] = 99900002
        with self.assertRaisesRegex(ValueError, '卡库缺少'): self.command('record.save', record)

    def test_legacy_tag_entries_are_not_rewritten_by_matchup_import(self):
        original = {'version': 1, 'revision': 3, 'entries': {'custom:fixture': {
            'id': 'custom:fixture', 'name': '手坑', 'aliases': ['旧别名'], 'setcode': None,
            'include_cards': [55144522], 'exclude_cards': [], 'source': '个人来源'}}}
        atomic_json(self.store.library.path, original)
        imported = self.import_catalog()
        self.assertEqual(read_json(self.store.library.path)['entries'], original['entries'])
        self.assertEqual(set(imported['handtraps']), {'55144522'})
        self.assertEqual(read_json(self.store.root / 'backups/tags/3.json'), original)

    def test_stale_revision_and_failed_commit_leave_saved_data_intact(self):
        self.command('topic.save', {'name': '原主题'})
        before = self.store.library.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '其他入口'):
            self.store.intelligence.command({'revision': 0, 'op': 'matchups.import'})
        real_write = self.store.library.write
        def fail_commit(path, value):
            if path == self.store.library.path: raise OSError('isolated disk full')
            return real_write(path, value)
        with patch.object(self.store.library, 'write', side_effect=fail_commit):
            with self.assertRaises(OSError): self.import_catalog()
        self.assertEqual(self.store.library.path.read_bytes(), before)
        self.assertEqual(self.store.intelligence.snapshot()['records'], {})

    def test_invalid_later_step_cannot_partially_import_a_batch(self):
        self.command('topic.save', {'name': '原主题'})
        before = self.store.library.path.read_bytes()
        catalog = fixture_catalog()
        second = {**deepcopy(catalog['guides'][0]), 'id': 'bad-second'}
        second['steps'][0]['opponent'] = True
        catalog['guides'].append(second)
        with self.assertRaises(ValueError): self.import_catalog(catalog)
        self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_walkthrough_cards_have_previews_and_provenance_survives_manual_editing(self):
        catalog = fixture_catalog(); guide = catalog['guides'][0]
        guide['walkthrough'] = {'premise': '合成前提', 'sequence': [
            {'card': 99900002, 'action': '前置操作', 'result': '形成断点条件', 'step_index': None},
            {'card': 23995346, 'action': '到达测试断点', 'result': '应用该步条件', 'step_index': 0}],
            'branches': [{'label': '放行', 'body': '合成后续'}, {'label': '此处打断', 'body': '合成推演'}],
            'conclusion': '仅用于说明，非确定结果', 'source_ids': ['fixture-report']}
        imported = self.import_catalog(catalog); identifier = 'matchup:2026-09-20:ocg-fixture'
        record = imported['records'][identifier]
        self.assertEqual(record['research']['walkthrough'], guide['walkthrough'])
        self.assertTrue(imported['cards']['99900002']['missing'])
        self.assertEqual(imported['import_result']['missing'], [{'code': 99900002,
                         'guide_id': 'ocg-fixture', 'record_id': identifier}])
        record['research']['walkthrough'] = {'premise': '伪造来源流程'}
        record['note'] = '我的补充'
        saved = self.command('record.save', record)['records'][identifier]
        self.assertEqual(saved['research']['walkthrough'], guide['walkthrough'])
        self.assertTrue(saved['research']['edited'])
        self.assertIn('99900002', Store(self.root).intelligence.snapshot()['cards'])

    def test_invalid_catalog_metadata_is_rejected_without_writing(self):
        self.command('topic.save', {'name': '原主题'})
        before = self.store.library.path.read_bytes()
        changes = [
            ('bad version', lambda c: c.update(version='../version')),
            ('bad reviewed date', lambda c: c.update(reviewed_at=None)),
            ('unsafe url', lambda c: c['sources'][0].update(url='javascript:alert(1)')),
            ('relative url', lambda c: c['sources'][0].update(url='/local/report')),
            ('bad source kind', lambda c: c['sources'][0].update(kind='unknown')),
            ('duplicate source', lambda c: c['sources'].append(deepcopy(c['sources'][0]))),
            ('unknown source', lambda c: c['guides'][0].update(source_ids=['unknown'])),
            ('wrong source list', lambda c: c['guides'][0].update(source_ids='fixture-report')),
            ('duplicate guide', lambda c: c['guides'].append(deepcopy(c['guides'][0]))),
            ('bad format', lambda c: c['guides'][0].update(format='TCG')),
            ('long period', lambda c: c['guides'][0].update(period='x' * 201)),
            ('long summary', lambda c: c['guides'][0].update(summary='x' * 4001)),
            ('wrong recognition', lambda c: c['guides'][0].update(recognition=[])),
            ('long topic', lambda c: c['guides'][0].update(topic='x' * 81)),
        ]
        for name, change in changes:
            with self.subTest(case=name):
                catalog = fixture_catalog(); change(catalog)
                with self.assertRaises(ValueError): self.import_catalog(catalog)
                self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_walkthrough_requires_valid_cards_step_links_and_cited_sources(self):
        self.command('topic.save', {'name': '原主题'})
        before = self.store.library.path.read_bytes()
        walkthrough = {'premise': '前提', 'sequence': [{'card': 55144522, 'action': '操作', 'result': '结果', 'step_index': 0}],
                       'branches': [{'label': '放行', 'body': '后续'}], 'conclusion': '限制', 'source_ids': ['fixture-report']}
        changes = [
            ('boolean card', lambda w: w['sequence'][0].update(card=True)),
            ('negative card', lambda w: w['sequence'][0].update(card=-1)),
            ('unknown step', lambda w: w['sequence'][0].update(step_index=1)),
            ('boolean step', lambda w: w['sequence'][0].update(step_index=False)),
            ('unknown source', lambda w: w.update(source_ids=['unknown'])),
            ('wrong sequence', lambda w: w.update(sequence='not a list')),
            ('wrong branch', lambda w: w.update(branches=['not an object'])),
        ]
        for name, change in changes:
            with self.subTest(case=name):
                catalog = fixture_catalog(); candidate = deepcopy(walkthrough); change(candidate)
                catalog['guides'][0]['walkthrough'] = candidate
                with self.assertRaises(ValueError): self.import_catalog(catalog)
                self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_each_step_retains_validated_read_only_citations(self):
        catalog = fixture_catalog(); catalog['guides'][0]['step_sources'] = [['fixture-report']]
        result = self.import_catalog(catalog); identifier = 'matchup:2026-09-20:ocg-fixture'
        record = result['records'][identifier]
        self.assertEqual(record['research'].get('step_sources'), [['fixture-report']])
        record['research']['step_sources'] = [['forged']]
        saved = self.command('record.save', record)['records'][identifier]
        self.assertEqual(saved['research']['step_sources'], [['fixture-report']])

    def test_step_edits_mark_original_citations_as_detached_and_cannot_reset_the_flag(self):
        catalog = fixture_catalog(); catalog['guides'][0]['step_sources'] = [['fixture-report']]
        imported = self.import_catalog(catalog); identifier = 'matchup:2026-09-20:ocg-fixture'
        record = deepcopy(imported['records'][identifier])
        self.assertIs(record['research'].get('steps_edited'), False)
        record['note'] = '个人备注'
        annotated = self.command('record.save', record)['records'][identifier]
        self.assertFalse(annotated['research']['steps_edited'])
        annotated['steps'][0]['action'] = '手动改变断点操作'
        edited = self.command('record.save', annotated)['records'][identifier]
        self.assertTrue(edited['research']['steps_edited'])
        self.assertEqual(edited['research']['step_sources'], [['fixture-report']])
        edited['steps'] = imported['records'][identifier]['steps']
        edited['research']['steps_edited'] = False
        restored = self.command('record.save', edited)['records'][identifier]
        self.assertTrue(restored['research']['steps_edited'])

    def test_bad_step_citations_cannot_write_a_partial_import(self):
        self.command('topic.save', {'name': '原主题'})
        before = self.store.library.path.read_bytes()
        for citations in ([], [['unknown']], ['fixture-report'], [['fixture-report'], ['fixture-report']]):
            with self.subTest(citations=citations):
                catalog = fixture_catalog(); catalog['guides'][0]['step_sources'] = citations
                with self.assertRaises(ValueError): self.import_catalog(catalog)
                self.assertEqual(self.store.library.path.read_bytes(), before)

    def test_cli_preview_is_read_only_and_apply_uses_backup_and_idempotence(self):
        self.command('topic.save', {'name': '原主题'})
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        original = read_json(self.store.library.path)
        preview = self.run_cli()
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(after, before)
        self.assertFalse(preview['applied'])
        self.assertEqual(preview['result']['added'], 1)
        applied = self.run_cli(apply=True)
        self.assertTrue(applied['applied'])
        self.assertEqual(applied['revision_after'], original['revision'] + 1)
        self.assertEqual(read_json(Path(applied['backup'])), original)
        again = self.run_cli(apply=True)
        self.assertEqual(again['revision_after'], applied['revision_after'])
        self.assertFalse(again['result']['changed'])
        self.assertIsNone(again['backup'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows ServiceLock uses msvcrt')
    def test_cli_refuses_a_profile_locked_by_an_active_service(self):
        self.command('topic.save', {'name': '原主题'})
        before = self.store.library.path.read_bytes()
        with ServiceLock(self.store.root / 'service.lock'):
            with self.assertRaisesRegex(RuntimeError, '另一服务'): self.run_cli(apply=True)
        self.assertEqual(self.store.library.path.read_bytes(), before)


if __name__ == '__main__': unittest.main()
