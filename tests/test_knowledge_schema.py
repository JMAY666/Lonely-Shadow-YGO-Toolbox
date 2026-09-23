"""Knowledge data contracts: evidence scope, stable identities and lossless updates."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
import knowledge_schema as ks


def record(identifier, kind, data, refs=()):
    return {'id': identifier, 'kind': kind, 'revision': 1, 'title': identifier,
            'tags': [], 'refs': [{'id': ref, 'relation': 'uses'} for ref in refs], 'data': data}


def fixture():
    doc = ks.new_document('验收主题', '测试')
    doc['records'] = {
        'raw': record('raw', 'source', {'content': 'Synthetic evidence, not a real duel.'}),
        'build': record('build', 'build', {'main': [100] * 40, 'extra': [], 'side': None}),
        'step': record('step', 'step', {'cards': [100], 'action': '示例动作', 'result': '示例结果', 'costs': '一份资源'}, ['raw']),
        'route': record('route', 'route', {'steps': ['step'], 'representation': 'strategy', 'opening': {'cards': [100]}}, ['build']),
        'other': record('other', 'countermeasure', {'opponent': '未知', 'situation': '示例', 'responses': '待核对'}),
    }
    return doc


class KnowledgeSchemaTests(unittest.TestCase):
    def test_revision_title_and_tags_are_not_identity_or_rules(self):
        before = fixture(); after = deepcopy(before)
        after['records']['step'].update(title='改名', revision=2, tags=['custom:stable'])
        after['records']['step']['editor_note'] = '排版待调整'
        result = ks.impact(before, after)
        self.assertIn('step', result['changed'])
        self.assertEqual(result['semantic_changed'], [])
        self.assertEqual(result['affected'], [])
        self.assertEqual(set(ks.inputs_for(before, 'route')), {'route', 'step', 'raw', 'build', '$environment'})
        self.assertEqual(ks.inputs_for(before, 'route'), ks.inputs_for(after, 'route'))

    def test_cost_change_invalidates_transitive_result_but_not_other_content(self):
        before = fixture()
        check = {'id': 'check1', 'type': 'human', 'target': 'route', 'inputs': ks.inputs_for(before, 'route'),
                 'status': 'passed', 'note': '合成校验', 'at': '2026-09-23T00:00:00Z'}
        before['checks'] = [check]; after = deepcopy(before)
        after['records']['step']['data']['costs'] = '两份资源'
        self.assertEqual(ks.check_state(before, check), 'passed')
        self.assertEqual(ks.check_state(after, check), 'stale')
        result = ks.impact(before, after)
        self.assertEqual(set(result['affected']), {'step', 'route'})
        self.assertIn('other', result['reused'])
        self.assertEqual(result['checks_stale'], ['check1'])

    def test_deleting_evidence_never_erases_history_or_keeps_current_pass(self):
        doc = fixture(); check = {'id': 'e', 'type': 'engine', 'target': 'route',
                                 'inputs': ks.inputs_for(doc, 'route'), 'status': 'passed', 'at': '2026-09-23', 'note': ''}
        original = deepcopy(check)
        doc['records']['raw']['deleted'] = True
        self.assertEqual(ks.check_state(doc, check), 'stale')
        self.assertEqual(check, original)
        self.assertFalse(ks.inspect_document(doc)['capabilities']['execute'])
        with self.assertRaises(ValueError): ks.validate_document(doc, strict=True)

    def test_incomplete_or_cyclic_dependencies_cannot_be_published(self):
        doc = fixture(); doc['records']['step']['refs'].append({'id': 'route', 'relation': 'uses'})
        ks.validate_document(doc)
        with self.assertRaises(ValueError): ks.validate_document(doc, strict=True)
        self.assertTrue(any(i['blocking'] for i in ks.inspect_document(doc)['issues']))
        doc = fixture(); doc['records']['route']['data']['steps'] = ['absent']
        with self.assertRaises(ValueError): ks.validate_document(doc, strict=True)

    def test_provenance_claim_cannot_grant_execution_and_partial_inputs_are_stale(self):
        doc = fixture(); claim = {'id': 'claim', 'type': 'engine', 'target': 'route', 'status': 'passed',
                                 'inputs': {'route': ks.semantic(doc['records']['route'])}, 'at': '2026-09-23', 'note': ''}
        doc['checks'] = [claim]
        self.assertEqual(ks.check_state(doc, claim), 'stale')
        claim['inputs'] = ks.inputs_for(doc, 'route')
        self.assertFalse(ks.inspect_document(doc)['capabilities']['calculate'])
        self.assertFalse(ks.inspect_document(doc)['capabilities']['execute'])

    def test_unknown_side_stays_unknown_and_missing_card_still_browsable(self):
        doc = ks.validate_document(fixture(), strict=True)
        self.assertIsNone(doc['records']['build']['data']['side'])
        issues = ks.inspect_document(doc, cards={})['issues']
        self.assertTrue(any(not row['blocking'] and row['record'] == 'build' for row in issues))
        self.assertTrue(ks.inspect_document(doc, cards={})['capabilities']['browse'])

    def test_unsafe_shapes_paths_and_urls_are_rejected_without_mutation(self):
        for bad in ('../escape', '/absolute', 'a\\b', '..'):
            with self.subTest(bad=bad), self.assertRaises(ValueError): ks.identifier(bad)
        for update in ({'revision': True}, {'kind': 'executable'}, {'data': {'__proto__': {}}},
                       {'data': {'content': 'raw', 'url': 'javascript:alert(1)'}}):
            doc = fixture(); doc['records']['raw'].update(update); before = deepcopy(doc)
            with self.subTest(update=update), self.assertRaises(ValueError): ks.validate_document(doc)
            self.assertEqual(doc, before)

    def test_merge_retains_personal_edit_and_combines_independent_upstream_change(self):
        base = {'note': '原文', 'condition': '旧条件', 'items': [1, 2], 'optional': None}
        local = {**deepcopy(base), 'note': '个人备注'}
        remote = {**deepcopy(base), 'condition': '新条件'}
        merged, conflicts = ks.merge_value(base, local, remote)
        self.assertEqual(merged, {**remote, 'note': '个人备注'})
        self.assertEqual(conflicts, [])
        remote['note'] = '新版备注'
        merged, conflicts = ks.merge_value(base, local, remote)
        self.assertEqual(merged['note'], '个人备注')
        self.assertTrue(any('note' in p for p in conflicts))

    def test_merge_distinguishes_deleted_key_from_null_and_conflicts_on_arrays(self):
        merged, conflicts = ks.merge_value({'x': None, 'y': 1}, {'x': None, 'y': 1}, {'y': 1})
        self.assertNotIn('x', merged); self.assertEqual(conflicts, [])
        merged, conflicts = ks.merge_value({'x': 1}, {}, {'x': 2})
        self.assertNotIn('x', merged); self.assertTrue(conflicts)
        merged, conflicts = ks.merge_value([1, 2], [1, 3], [1, 4])
        self.assertEqual(merged, [1, 3]); self.assertTrue(conflicts)

    def test_oversized_nesting_and_global_prototype_keys_fail_before_copying(self):
        doc = fixture(); doc['package']['constructor'] = 'bad'
        with self.assertRaises(ValueError): ks.validate_document(doc)
        doc = fixture(); deep = {}; node = deep
        for _ in range(1100): node['child'] = {}; node = node['child']
        doc['records']['raw']['data']['content'] = deep
        with self.assertRaises(ValueError): ks.validate_document(doc)

    def test_deleted_unused_records_are_historical_not_publish_blockers(self):
        doc = fixture(); doc['records']['unused'] = record('unused', 'route', {'steps': []})
        doc['records']['unused']['deleted'] = True
        ks.validate_document(doc, strict=True)
        self.assertEqual(ks.inspect_document(doc)['counts']['route'], 1)

    def test_branch_requires_an_anchor_inside_its_route(self):
        doc = fixture(); doc['records']['branch'] = record('branch', 'branch', {'route': 'route'})
        with self.assertRaises(ValueError): ks.validate_document(doc, strict=True)
        doc['records']['other-step'] = record('other-step', 'step', {'action': '另一个动作', 'result': '另一个结果'})
        doc['records']['branch']['data']['anchor'] = 'other-step'
        with self.assertRaises(ValueError): ks.validate_document(doc, strict=True)

    def test_usage_notes_and_unknown_fields_are_not_mistaken_for_editorial_text(self):
        doc = fixture(); original = ks.inputs_for(doc, 'route')
        changed = deepcopy(doc); changed['records']['route']['data']['notes'] = '使用天底后不能照此同调'
        self.assertNotEqual(ks.inputs_for(changed, 'route'), original)
        changed = deepcopy(doc); changed['records']['step']['additional_constraint'] = 'new restriction'
        self.assertNotEqual(ks.inputs_for(changed, 'route'), original)

    def test_changing_declared_environment_invalidates_scope_without_renaming_entities(self):
        doc=fixture();check={'id':'checked','type':'human','target':'route','inputs':ks.inputs_for(doc,'route'),
                            'status':'passed','note':'','at':'2026-09-23'}
        doc['checks']=[check];changed=deepcopy(doc);changed['package']['environment']='different format or restriction period'
        self.assertEqual(ks.check_state(changed,check),'stale')
        result=ks.impact(doc,changed)
        self.assertTrue(result['environment_changed']);self.assertEqual(set(result['affected']),set(doc['records']))
        self.assertEqual(result['reused'],[])


if __name__ == '__main__': unittest.main()
