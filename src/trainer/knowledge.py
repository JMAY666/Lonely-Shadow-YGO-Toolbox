"""App-facing knowledge workspace. Imports are explicit, private data remains owned."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from knowledge_schema import digest, inspect_document, validate_document, dependencies
from knowledge_store import KnowledgeStore


class Knowledge:
    def __init__(self, store, read, write):
        self.store = store
        self.manager = KnowledgeStore(store.root / 'knowledge', read, write, cards=lambda: store.catalog.cards)
        from knowledge_runtime import KnowledgeRuntime
        from knowledge_jobs import KnowledgeJobs
        self.runtime = KnowledgeRuntime(self)
        self.runtime.jobs = KnowledgeJobs(self.runtime)

    def snapshot(self):
        result = self.manager.snapshot()
        result['tags'] = list(self.store.library.all_tags().values())
        return result

    def provider_summary(self):
        registry = self.manager.registry()
        active = {key: value['active'] for key, value in registry['packages'].items() if value.get('enabled')}
        return {'version': digest([active, registry['overrides']]), 'records': len(active),
                'note': '提供资料与版本；安装不会自动授予计算或执行资格。'}

    def _invalidate(self, package_id):
        # Package modifications never auto-start a duel or enable an AI worker.
        affected = {sid for sid, entry in self.store.modular.library.entries.items()
                    if entry.get('knowledge_package') == package_id}
        self.store.modular.sources_changing(affected)
        precompute = self.store.modular.precompute
        with precompute.lock:
            for job in precompute.jobs.values():
                if affected.intersection(job.get('body', {}).get('sources', [])): precompute.cancel(job)

    def command(self, body):
        op = body.get('op')
        m = self.manager
        # Queue callbacks acquire the app lock themselves. Never invert it with cancellation's commit lock.
        jobs = self.runtime.jobs
        if op == 'job.start': return jobs.start(body)
        if op == 'job.poll': return jobs.poll(body['id'])
        if op == 'job.cancel': return jobs.cancel(body['id'])
        if op == 'job.resume': return jobs.resume(body['id'])
        if op == 'job.list': return jobs.list(body.get('project_id'))
        with self.store.lock:
            if op == 'project.create': return m.create(body.get('name', '新知识包'), body.get('theme', ''))
            if op == 'project.sample':
                from knowledge_sample import sample_document
                return m.create(document=sample_document())
            if op == 'project.get': return m.project(body['id'])
            if op == 'project.verification-status': return self.runtime.status_for(m.project(body['id'])['document'])
            if op == 'project.import':
                value = body['document']
                if value.get('format') == 'ygo-deck-knowledge-bundle':
                    m.preview(value); value = value['document']
                elif value.get('format') == 'ygo-deck-knowledge-project': value = value['document']
                return m.create(document=value)
            if op == 'project.save':
                value = m.save(body['id'], body['revision'], body['document'])
                jobs.invalidate(body['id'])
                return value
            if op == 'project.review':
                return m.review(body['id'], body['revision'], body['target'], body.get('note', ''), body.get('kind', 'human'))
            if op == 'project.publish': return m.bundle(body['id'], body['revision'], body['version'])
            if op == 'project.export':
                project = m.project(body['id'])
                return {'format': 'ygo-deck-knowledge-project', 'schema': 1, 'document': project['document']}
            if op == 'project.import-source': return self.import_source(body)
            if op == 'project.candidates': return self.candidates(body)
            if op == 'package.preview': return m.preview(body['bundle'])
            if op == 'package.get':
                doc = m.document(body['package_id'], body.get('version'))
                return {'document': doc, 'inspection': inspect_document(doc, self.store.catalog.cards),
                        'index': m.index_info(body['package_id'], doc['package']['version']),
                        'runtime': self.runtime.status_for(doc),
                        'personal_notes': {key: value.get('note', '') for key, value in m.registry()['overrides'].get(body['package_id'], {}).get(doc['package']['version'], {}).items()}}
            if op == 'package.activation-preview':
                doc = m.document(body['package_id'], body['version'], effective=False)
                return m.preview({'format': 'ygo-deck-knowledge-bundle', 'schema': 1, 'document': doc, 'digest': digest(doc)})
            if op == 'catalog':
                rows = m.catalog(body.get('kinds'))
                query, tag = str(body.get('query', '')).casefold().strip(), body.get('tag')
                return [row for row in rows if (not query or query in row['search_text'])
                        and (not tag or tag in row['record']['tags'])]
            if op == 'package.compute': return self.runtime.set_compute(body['package_id'], body['revision'], body['enabled'])
            if op == 'personal.copy-build': return self.copy_build(body)
            if op in ('package.install', 'package.activate', 'package.disable', 'package.uninstall', 'package.overlay'):
                # Updates retain pinned immutable versions; explicit disable revokes pending actions.
                if op in ('package.disable', 'package.uninstall'): self._invalidate(body['package_id'])
                if op == 'package.install':
                    return m.install(body['bundle'], body['digest'], body['revision'], body.get('enable', False), body.get('resolutions'))
                if op == 'package.activate':
                    return m.activate(body['package_id'], body['version'], body['revision'], body.get('resolutions'))
                if op == 'package.disable': return m.disable(body['package_id'], body['revision'])
                if op == 'package.uninstall': return m.uninstall(body['package_id'], body['revision'])
                return m.overlay(body['package_id'], body['version'], body['record_id'], body['local'], body.get('note', ''), body['revision'])
            raise ValueError('不支持的知识包操作')

    def import_source(self, body):
        """Take a frozen copy via existing owners; never move or rewrite their files."""
        m = self.manager
        project = m.project(body['id'])
        if project['revision'] != body['revision']: raise ValueError('制作项目已更新，请保留输入并刷新核对')
        doc = deepcopy(project['document']); records = doc['records']; suffix = uuid.uuid4().hex
        source_id = 'source-' + suffix
        kind = body.get('kind')

        def add(identifier, record_kind, title, data, refs=(), tags=()):
            records[identifier] = {'id': identifier, 'kind': record_kind, 'revision': 1, 'title': title,
                'tags': list(tags), 'refs': [{'id': r, 'relation': 'uses'} for r in refs], 'data': deepcopy(data)}
            return identifier

        if kind == 'deck':
            saved = self.store.get_deck(body['source_id'])
            if body.get('source_revision') != saved['revision']: raise ValueError('构筑已更新，请重新选择导入版本')
            source, _, relative = saved['id'].partition('/')
            if source not in ('library', 'existing'): raise ValueError('请先把当前构筑保存到个人卡组库再导入')
            base = self.store.decks if source == 'library' else self.store.runtime / 'deck'
            path = (base / relative).resolve()
            if not path.is_relative_to(base.resolve()) or path.is_symlink(): raise ValueError('构筑来源路径无效')
            original = path.read_bytes().decode('utf-8')
            add(source_id, 'source', saved['name'] + ' · 原始 YDK', {'content': original, 'source_revision': saved['revision']})
            add('build-' + suffix, 'build', saved['name'], {**saved['deck'], 'notes': '', 'conditions': ''},
                [source_id], saved['tag_selection']['tag_ids'])
        elif kind == 'plan':
            original = self.store.library.export(body['source_id'])
            plan = original['plan']
            full = self.store.report(body['source_id'])
            if body.get('source_revision') != full.get('edit_revision', 0): raise ValueError('正式方案已更新，请重新选择导入版本')
            add(source_id, 'source', plan['name'] + ' · 分享格式原始资料', {'content': original,
                'source_revision': full.get('edit_revision', 0), 'note': '按现有分享白名单复制，不携带本机路径或原生恢复文件。'})
            tag_ids = [tag['id'] for tag in original['tags']]
            build_id = add('build-' + suffix, 'build', plan.get('deck_name') or plan['name'], {**plan['deck'], 'notes': '', 'conditions': ''}, [source_id], tag_ids)
            steps = []
            for number, action in enumerate(plan.get('actions', []), 1):
                key = 'step-' + suffix + '-' + str(number)
                text = action.get('summary') or action.get('text') or action.get('kind') or f'原始步骤 {number}'
                steps.append(add(key, 'step', str(text)[:240], {
                    'cards': [c['code'] for c in action.get('cards', []) if c.get('code')], 'action': str(text),
                    'result': '详见原始报告的动作、快照与批注。', 'costs': '', 'targets': '', 'limits': '', 'source_action_id': action.get('id')}, [source_id]))
            route_id = add('route-' + suffix, 'route', plan['name'], {'steps': steps,
                'opening': plan.get('expansion', {}).get('conditions', {}), 'conditions': plan.get('expansion', {}).get('notes', ''),
                'notes': '正式记录导入候选；文字整理未覆盖原始决策证据。',
                'representation': 'decisions' if plan.get('modular_source', {}).get('edges') else 'strategy', 'plan': plan,
                'evidence_identity': {k: full.get(k) for k in ('engine_sha256', 'scripts_sha256') if full.get(k)}}, [source_id, build_id], tag_ids)
            for branch in plan.get('branches', []):
                add('branch-' + uuid.uuid4().hex, 'branch', branch['name'], {
                    'route': route_id, 'timing': str(branch.get('source', {}).get('timing', '')),
                    'interference': '详见冻结分支记录；源决策节点未自动映射到整理步骤。',
                    'resources': '', 'conditions': json.dumps(branch.get('conditions', {}), ensure_ascii=False),
                    'notes': '保留原始分支，人工确认锚点后再发布。', 'original_branch': branch}, [source_id])
            from knowledge_runtime import native_binding
            records[route_id]['data']['native_binding'] = native_binding(doc, route_id)
        elif kind == 'file':
            title = str(body.get('title', '原始资料')).strip()
            if not title or len(title) > 240: raise ValueError('资料名称请输入 1—240 字')
            content = body.get('content')
            if not isinstance(content, (str, dict, list)): raise ValueError('原始资料需要文本或结构化内容')
            add(source_id, 'source', title, {'content': content, 'url': body.get('url', ''), 'note': '用户主动导入的原始资料；发布前核对是否适合包含。'})
        else: raise ValueError('请选择构筑、正式方案或人工资料')
        return m.save(body['id'], body['revision'], doc)

    def candidates(self, body):
        project = self.manager.project(body['id'])
        if project['revision'] != body['revision']: raise ValueError('项目已改变，请重新检查')
        groups = {}
        for record in project['document']['records'].values():
            if record.get('deleted') or record['kind'] == 'source': continue
            key = digest([record['kind'], record['data'], sorted(dependencies(record))])
            groups.setdefault(key, []).append(record['id'])
        return {'revision': project['revision'], 'duplicates': [ids for ids in groups.values() if len(ids) > 1],
                'note': '候选不会直接改写项目；仅内容和依赖完全相同才列为重复候选，人工确认后可提取共用片段。'}

    def copy_build(self, body):
        document = self.manager.document(body['package_id'], body['version'])
        record = document['records'][body['record_id']]
        if record['kind'] != 'build' or record.get('deleted'): raise ValueError('请选择有效构筑')
        data = deepcopy(record['data'])
        if data.get('side') is None:
            if body.get('omit_unknown_side') is not True: raise ValueError('来源未披露副卡，请明确选择另存为不带副卡的个人构筑')
            data['side'] = []
        tags = [t for t in record['tags'] if t in self.store.library.all_tags()]
        return self.store.save_deck({'name': body.get('name') or record['title'] + ' · 个人副本',
            'deck': {z: data[z] for z in ('main', 'extra', 'side')},
            'tag_selection': {'version': 1, 'mode': 'manual', 'tag_ids': tags, 'primary_ids': tags[:1]}})
