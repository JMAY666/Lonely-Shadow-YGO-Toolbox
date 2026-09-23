"""Explicit adapters from immutable knowledge evidence to the existing rules core.

Publisher assertions never authorize execution. A local scene check is scoped to
its inputs, and every live action still goes through the normal disposable core.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import re
import threading
import time
import uuid

from knowledge_schema import digest, inputs_for, inspect_document
from modular_decisions import validate_source
from plan_sharing import FORMAT as PLAN_FORMAT, VERSION as PLAN_VERSION, validate as validate_plan


def native_binding(document, target):
    value = deepcopy(document)
    value['records'][target]['data'].pop('native_binding', None)
    return inputs_for(value, target)


def native_plan(document, target):
    record = document['records'].get(target, {})
    data = record.get('data', {})
    if record.get('deleted') or record.get('personal_orphan') or record.get('kind') != 'route':
        raise ValueError('该条目不是当前有效展开')
    if data.get('representation') != 'decisions' or not isinstance(data.get('plan'), dict):
        raise ValueError('仅有教程或结构化资料，缺少原始决策记录，不能进行引擎验证')
    if data.get('native_binding') != native_binding(document, target):
        raise ValueError('整理步骤或依赖已改变，原始决策对应关系待核对；请从重新录制的正式方案导入')
    identity = data.get('evidence_identity', {})
    if any(not re.fullmatch(r'[0-9a-f]{64}', str(identity.get(k, ''))) for k in ('engine_sha256', 'scripts_sha256')):
        raise ValueError('原始记录缺少引擎或脚本身份，保留浏览；需从有完整证据的本机正式方案导入')
    scope = inputs_for(document, target)
    if any(row['blocking'] for row in inspect_document(document)['issues'] if row['record'] in scope):
        raise ValueError('路线的依赖或步骤锚点不完整，请先修复结构问题')
    plan = validate_plan({'format': PLAN_FORMAT, 'version': PLAN_VERSION, 'plan': data['plan'], 'tags': []})['plan']
    evidence = plan.get('modular_source')
    validate_source(evidence)
    if not evidence.get('edges') or not any(edge.get('terminal') for edge in evidence['edges']):
        raise ValueError('原始决策未形成已记录终场，不能作为完整路线验证')
    plan.update(identity)
    return plan


class KnowledgeRuntime:
    def __init__(self, knowledge):
        self.knowledge, self.store, self.manager = knowledge, knowledge.store, knowledge.manager
        self._lock = threading.RLock()
        self._environment = None
        self._temporary = {}
        self._entries = {}
        self.errors = {}
        self.jobs = None

    def closing(self): return self.store.closing

    def environment(self, force=False):
        from modular import EXTRACTOR_VERSION
        signature = self.store.modular.precompute.rules(force=force)
        with self._lock:
            if not force and self._environment and self._environment[0] == signature:
                return deepcopy(self._environment[1])
        root = self.store.runtime
        files = [root / 'YGOPro.exe', root / 'cards.cdb']
        files += sorted((root / 'expansions').glob('*.cdb'))
        files += [root / source['path'] for source in self.store.catalog.sources if str(source.get('path', '')).endswith(('.cdb', '.ypk'))]
        hashes = {file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
                  for file in files if file.is_file()}
        if 'YGOPro.exe' not in hashes or 'cards.cdb' not in hashes: raise ValueError('缺少本机规则引擎或卡库')
        if any(source['path'] in hashes and hashes[source['path']] != source['sha256'] for source in self.store.catalog.sources):
            raise ValueError('卡库或补丁文件已改变，当前目录与已加载资料不一致；请刷新资源或重启后重新验证')
        result = {'files': hashes, 'scripts': self.store.compromise.script_identity(),
                  'catalog': deepcopy(self.store.catalog.sources), 'extractor': EXTRACTOR_VERSION,
                  'scope': '本机展开练习规则；不证明当前赛事禁限合法性', 'adapter': 1, 'semantic_version': 3}
        with self._lock: self._environment = (signature, result)
        return deepcopy(result)

    def verification_snapshot(self, project_id, route_id, build_id, hand, scenario, *, force=True):
        from duel import validate_hand
        with self.store.lock:
            document = self.manager.project(project_id)['document']
            plan = native_plan(document, route_id)
            build = document['records'].get(build_id)
            if not build or build['kind'] != 'build' or build.get('deleted') or build_id not in inputs_for(document, route_id):
                raise ValueError('请选择本路线明确关联的构筑')
            deck = {zone: deepcopy(build['data'].get(zone)) for zone in ('main', 'extra', 'side')}
            if any(not isinstance(value, list) for value in deck.values()): raise ValueError('构筑信息不完整，未知副卡不能当作已确认空副卡')
            if any(Counter(deck[zone]) != Counter(plan['deck'][zone]) for zone in deck):
                raise ValueError('构筑与原始记录不一致，请重新录制或补充独立的适用关系')
            validate_hand(deck, len(hand), hand)
            self.store.validate(deck, training=True)
            if scenario not in ('none', 'ash'): raise ValueError('暂仅支持无额外干扰和现有灰流丽场景')
            environment = self.environment(force=force)
            inputs = inputs_for(document, route_id)
            identity = digest([document['package']['id'], route_id, build_id, inputs, environment, hand, scenario])
            return {'identity': identity, 'project_id': project_id, 'route_id': route_id, 'build_id': build_id,
                    'hand': list(hand), 'scenario': scenario, 'inputs': inputs, 'environment': environment,
                    'payload': {'document': document, 'plan': plan, 'deck': deck}}

    def current_identity(self, snapshot):
        return self.verification_snapshot(snapshot['project_id'], snapshot['route_id'], snapshot['build_id'],
            snapshot['hand'], snapshot['scenario'], force=False)['identity']

    def _proof_key(self, document, target, environment):
        return digest([document['package']['id'], target, inputs_for(document, target), environment])

    def store_verification(self, snapshot, result):
        with self.store.lock:
            if self.verification_snapshot(snapshot['project_id'], snapshot['route_id'], snapshot['build_id'],
                    snapshot['hand'], snapshot['scenario'], force=True)['identity'] != snapshot['identity']:
                return False
            from datetime import datetime, timezone
            check = {'id': 'engine-' + snapshot['identity'], 'type': 'engine', 'target': snapshot['route_id'],
                'inputs': snapshot['inputs'], 'status': result['status'], 'note': result.get('note', ''),
                'at': datetime.now(timezone.utc).isoformat(), 'environment': snapshot['environment'],
                'scene': {'hand': snapshot['hand'], 'scenario': snapshot['scenario']},
                'evidence': deepcopy(result.get('evidence', {})), 'authority': 'local_rules_check'}
            if not self.manager.record_engine_check(snapshot['project_id'], snapshot['inputs'], check): return False
            if result['status'] == 'passed':
                key = self._proof_key(snapshot['payload']['document'], snapshot['route_id'], snapshot['environment'])
                self.manager._write_json('local-verifications/%s.json' % key,
                    {'key': key, 'identity': snapshot['identity'], 'check': check, 'digest': digest(check)})
            return True

    def _qualified(self, document, target, environment):
        native_plan(document, target)
        key = self._proof_key(document, target, environment)
        proof = self.manager._read_json('local-verifications/%s.json' % key)
        if not proof or proof.get('key') != key or proof.get('digest') != digest(proof.get('check')):
            return False
        return proof['check'].get('status') == 'passed' and proof['check'].get('environment') == environment

    def status_for(self, document):
        result, environment = {}, None
        for target, record in document['records'].items():
            if record['kind'] != 'route' or record.get('deleted'): continue
            value = {'native_ready': False, 'locally_verified': False, 'reason': ''}
            try:
                native_plan(document, target)
                value['native_ready'] = True
                environment = environment or self.environment()
                value['locally_verified'] = self._qualified(document, target, environment)
                if not value['locally_verified']:
                    old = [c for c in document['checks'] if c['type'] == 'engine' and c['target'] == target]
                    changed = bool(old and old[-1].get('environment') != environment)
                    value['reason'] = ('卡库、脚本、核心或适配版本与所附历史验证不同，需要在当前环境重新检查；共用资源变化按整条路线扩大重验。'
                                       if changed else '尚无当前依赖和规则环境下的本机通过记录')
                else: value['reason'] = '已有本机限定场景验证；当前对局仍逐步通过规则引擎，不代表最优'
            except (ValueError, OSError, KeyError, TypeError) as error:
                value['reason'] = str(error)
            result[target] = value
        return result

    def _projection(self, document, target, version):
        plan = native_plan(document, target)
        record = document['records'][target]
        origin = {'package_id': document['package']['id'], 'version': version, 'record_id': target,
                  'inputs': inputs_for(document, target)}
        identifier = 'kp-' + digest([origin, plan, record['tags'], record['title']])
        plan.update(id=identifier, name=record['title'] + ' · ' + document['package']['name'] + ' [' + version + ']', imported=True, readonly_knowledge=True,
            knowledge_origin=origin, edit_revision=record['revision'], plan_stage='saved',
            classification={'version': 1, 'mode': 'manual', 'tag_ids': list(record['tags']), 'primary_ids': record['tags'][:1]})
        path = 'projections/%s.json' % identifier
        if self.manager._read_json(path) is None:
            self.manager._write_json(path, {'plan': plan, 'digest': digest(plan)})
        return plan

    def read_plan(self, identifier):
        if not re.fullmatch(r'kp-[0-9a-f]{64}', str(identifier)): raise ValueError('知识包路线标识无效')
        value = self.manager._read_json('projections/%s.json' % identifier)
        if not value or value.get('digest') != digest(value.get('plan')) or value['plan'].get('id') != identifier:
            raise ValueError('知识包路线快照缺失或摘要不符')
        return deepcopy(value['plan'])

    def temporary_deck(self, identifier):
        with self._lock:
            value = self._temporary.get(identifier)
            if not value: raise ValueError('该验证场景已经结束')
            return deepcopy(value['deck'])

    def _entry(self, library, document, target, version, *, verification=False):
        from module_conditions import branch_condition
        plan = self._projection(document, target, version)
        identity = digest([plan, verification])
        if identity in self._entries: return deepcopy(self._entries[identity])
        routes = []
        for route_id, name, report, branch in [(plan['id'], plan['name'], plan, None),
                *((b['id'], b['name'], b['report'], b) for b in plan.get('branches', []) if b.get('report') and b.get('valid', True))]:
            evidence = library.capture(report)
            if branch:
                guard = branch_condition(plan, branch); evidence['if_condition'] = guard
                boundary = (guard.get('event') or {}).get('seq', branch['source']['seq'])
                snapshots = {node['id']: node for node in evidence['snapshots']}
                for edge in evidence['edges']:
                    if snapshots[edge['from']]['seq'] > boundary: edge['if_condition'] = deepcopy(guard)
                if guard['status'] != 'verified': evidence['unknown'].append({'reason': '妥协条件缺少实际事件确认'})
            routes.append({'id': route_id, 'name': name, **evidence})
        entry = {'id': plan['id'], 'name': plan['name'], 'version': identity, 'revision': plan['edit_revision'],
            'tag_ids': plan['classification']['tag_ids'], 'routes': routes,
            'opening_conditions': deepcopy(plan.get('expansion', {}).get('conditions')),
            'actual_opening': deepcopy(plan.get('expansion', {}).get('actual_opening')),
            'status': 'verification' if verification else 'ready', 'private': verification,
            'available_for_new': not verification, 'knowledge_package': document['package']['id'],
            'knowledge_version': version, 'knowledge_record': target,
            'opening_note': '已记录决策与本机验证场景；当前构筑、起手及每一步仍需规则校验'}
        if len(self._entries) >= 64: self._entries.clear()
        self._entries[identity] = deepcopy(entry)
        return entry

    def entries(self, library):
        registry = self.manager.registry(); result = {}
        enabled = {key: value for key, value in registry['packages'].items() if value.get('enabled') and value.get('compute_enabled')}
        environment = self.environment() if enabled else None
        for package_id, metadata in enabled.items():
            try:
                document = self.manager.document(package_id, metadata['active'])
                self.errors.pop(package_id, None)
            except (ValueError, OSError, KeyError) as error:
                self.errors[package_id] = str(error)
                continue
            for target, record in document['records'].items():
                if record['kind'] != 'route' or record.get('deleted'): continue
                try:
                    if not self._qualified(document, target, environment): continue
                    scope = inputs_for(document, target)
                    if any(row['code'] == 'card-missing' for row in inspect_document(document, self.store.catalog.cards)['issues'] if row['record'] in scope): continue
                    entry = self._entry(library, document, target, metadata['active'])
                    result[entry['id']] = entry
                except (ValueError, TypeError, KeyError): continue
        # Pinned sessions keep their old immutable steps after an update. They are not new candidates.
        selected = {sid for ctx in self.store.modular.sessions.values() for sid in ctx.get('selected', [])}
        for sid in selected - result.keys():
            old = library.entries.get(sid, {})
            if old.get('knowledge_package') in enabled and not old.get('private'):
                result[sid] = {**deepcopy(old), 'status': 'pinned', 'available_for_new': False}
        with self._lock:
            for value in self._temporary.values():
                entry = self._entry(library, value['document'], value['route'], value['version'], verification=True)
                result[entry['id']] = entry
        return result

    def plans(self):
        self.store.modular.library.sync()
        return [self.read_plan(key) for key, entry in self.store.modular.library.entries.items()
                if entry.get('knowledge_package') and entry.get('available_for_new') and entry['status'] == 'ready']

    def set_compute(self, package_id, revision, enabled):
        if type(enabled) is not bool: raise ValueError('请明确是否允许参与计算')
        with self.store.lock, self.manager._lock:
            registry = self.manager.registry()
            if type(revision) is not int or registry['revision'] != revision: raise ValueError('知识包状态已更新，请刷新')
            entry = registry['packages'].get(package_id)
            if not entry or not any(v.get('installed') for v in entry['versions'].values()): raise ValueError('知识包尚未安装')
            entry['compute_enabled'] = enabled
            if not enabled: self.knowledge._invalidate(package_id)
            self.manager._commit(registry, revision)
        return self.knowledge.snapshot()

    def verify_case(self, snapshot, limits, cancelled, progress):
        from duel_planner import generate, close
        document = snapshot['payload']['document']; target = snapshot['route_id']
        self_id = 'knowledge-job/' + uuid.uuid4().hex
        plan = self._projection(document, target, 'verification-' + snapshot['identity'][:12])
        saved = {'id': self_id, 'name': '知识包规则验证', 'revision': snapshot['identity'],
                 'deck': snapshot['payload']['deck'], 'tag_selection': {'tag_ids': document['records'][target]['tags']}}
        # A private scope is accepted only for this worker's exact source. It cannot execute.
        scope = {'id': snapshot['identity'], 'sources': [plan['id']], 'cancelled': cancelled, 'progress': progress}
        with self._lock: self._temporary[self_id] = {'deck': saved, 'document': document, 'route': target,
                                                    'version': 'verification-' + snapshot['identity'][:12]}
        sid = None
        def started(identifier, ctx):
            nonlocal sid
            sid = identifier
            ctx['knowledge_verification'] = scope
        try:
            if cancelled(): raise ValueError('已取消')
            progress({'phase': '启动隔离规则引擎', 'nodes': 0, 'seconds': 0})
            body = {'consumer': 'knowledge-verification', 'deck_id': self_id, 'revision': saved['revision'],
                'hand_count': len(snapshot['hand']), 'hand': snapshot['hand'], 'sources': [plan['id']],
                'preference': 'shortest', 'precise': False}
            result = generate(self.store.modular, body, on_started=started, verification=scope,
                search_options={'limits': {**limits, 'candidates': 8}, 'hard_limits': True,
                                'scenario': 1 if snapshot['scenario'] == 'ash' else 0})['result']
            candidates = [c for c in result.get('candidates', []) if c.get('validation') == 'engine_verified'
                          and (c.get('terminal_source') or {}).get('plan') == plan['id']
                          and (c.get('terminal_source') or {}).get('route') == plan['id']]
            passed = bool(candidates)
            return {'status': 'passed' if passed else 'unknown',
                'note': ('此起手与限定场景下，原始决策资料经当前规则引擎找到对应终场；不证明最优，也不替代文字内容的人工核对。'
                         if passed else '本次限定来源与预算内未确认对应终场，不能据此认为规则上不存在；原资料继续保留。'),
                'evidence': {'scene': snapshot['scenario'], 'hand': snapshot['hand'], 'limits': result.get('limits'), 'requested_limits': limits,
                    'nodes': result.get('nodes'), 'seconds': result.get('seconds'), 'limited': result.get('limited'),
                    'scope': '原始决策与来源终场', 'confirmed_candidates': len(candidates),
                    'terminal': candidates[0]['terminal'] if passed else None,
                    'steps': [{key: step[key] for key in ('source', 'operation_label', 'effect_label', 'decision', 'automatic') if key in step}
                              for step in candidates[0]['steps']] if passed else [], 'result_digest': digest(result)}}
        finally:
            if sid: close(self.store.modular, sid)
            with self._lock: self._temporary.pop(self_id, None)
