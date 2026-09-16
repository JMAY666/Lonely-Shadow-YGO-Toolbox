"""Isolated, pending-confirmation branches of one expansion plan.

Replay tapes stay beside local journals. Only frozen route data enters a plan.
The main report is never replaced by a branch report.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import uuid

from report import read_journal
from timeline import route_rows
from review import annotations_for, bounds, legacy_review, requirements
from module_graph import decision_boundaries, decision_id
from module_conditions import validate_if, branch_condition


def branch_points(report, rows):
    if report.get('compromise') or report.get('imported'): return []
    active = route_rows(rows)[0]
    actions = report.get('actions', [])
    nodes = legacy_review(report)['action_nodes']
    points = []
    for entry in decision_boundaries(active):
        row = entry['node']
        if not row.get('restorable'): continue
        state, seq = row['state'], row['seq']
        response = row.get('player') == 1 and row.get('prompt') in (12, 16) and state.get('chain_depth', 0) > 0
        idle = row.get('player') == 0 and row.get('prompt') in (10, 11) and not state.get('chain_depth', 0)
        if not (response or idle): continue
        if response:
            candidates = [a for a in actions if a.get('activation_ref') and bounds(a)[0] <= seq <= bounds(a)[1]
                          and any(c.get('controller') == 0 for c in a['cards'])]
        else:
            candidates = [a for a in actions if bounds(a)[1] <= seq]
        action = max(candidates, key=lambda a: bounds(a)[0], default=None)
        if response and not action: continue
        node_id = nodes.get(action['id']) if action else 'initial'
        points.append({'checkpoint': row['node'], 'module_id': decision_id(row), 'seq': seq, 'node_id': node_id,
            'action_id': action['id'] if action else None, 'cards': deepcopy(action['cards']) if action else [],
            'operation': action.get('heading') or action['summary'] if action else '初始手牌',
            'timing': '发动后的响应窗口' if response else '结算后' if action else '首次操作前',
            'prompt': row['prompt'], 'player': row['player'], 'chain_depth': state.get('chain_depth', 0),
            'opponent_hand': [c['code'] for c in sorted(state['cards'], key=lambda c: c['sequence'])
                              if c.get('controller') == 1 and c.get('location') == 2]})
    return points


def premises(report, start_seq, rows, associations=None):
    """Attribute only explicit core resolution/cause evidence, never adjacent card names."""
    actions = {a.get('activation_ref'): a for a in report.get('actions', []) if a.get('activation_ref')}
    associations = associations or {}
    result = []
    for event in report.get('events', []):
        if event.get('native_seq', 0) <= start_seq or event.get('message') not in (75, 76): continue
        source = actions.get(event.get('resolution_source_ref'))
        affected = actions.get(event.get('activation_ref'))
        if not source or not affected or not any(c.get('controller') == 1 for c in source['cards']): continue
        if not any(c.get('controller') == 0 for c in affected['cards']): continue
        result.append({'id': event['id'], 'source_action': source['id'], 'affected_action': affected['id'],
            'source_cards': deepcopy(source['cards']), 'affected_cards': deepcopy(affected['cards']),
            'chain_group': source.get('chain_group'), 'chain_link': source.get('chain_link'),
            'result': '发动被无效' if event['message'] == 75 else '效果被无效',
            'evidence_refs': [source['activation_ref'], event['id']], 'basis': '引擎连锁结算区间与无效事件', 'confirmed': True})
    covered = {item['source_action'] for item in result}
    for action in report.get('actions', []):
        if action.get('id') in covered or not action.get('activation_ref'): continue
        if int(action['activation_ref'].split(':')[0]) <= start_seq or not any(c.get('controller') == 1 for c in action['cards']): continue
        # An activation is an observed event even when its impact is not inferable.
        linked = associations.get(action['id'], {})
        target = next((a for a in report['actions'] if a['id'] == linked.get('action_id')), None)
        result.append({'id': action['id'], 'source_action': action['id'], 'source_cards': deepcopy(action['cards']),
            'affected_cards': deepcopy(target['cards']) if target else [], 'affected_action': target['id'] if target else None,
            'chain_group': action.get('chain_group'), 'chain_link': action.get('chain_link'),
            'result': '已发动，影响待核对' if action.get('status') == 'pending' else '对方发动了效果；具体影响未确认',
            'note': linked.get('note', ''), 'basis': '用户补充关联' if target else '保留原始事件，未推断受影响卡牌',
            'evidence_refs': action['evidence_refs'], 'confirmed': False})
    result.sort(key=lambda item: tuple(map(int, item['id'].split(':'))))
    return result


def resource_scope(main, branch=None):
    base = deepcopy(main.get('requirements') or requirements(main))
    extra, combined = {}, deepcopy(base)
    chosen = (branch or {}).get('report')
    if chosen:
        wanted = chosen.get('requirements') or requirements(chosen)
        for zone in ('main', 'extra', 'opening', 'random'):
            key = lambda item: (item.get('code'), item.get('constraint', ''))
            baseline = Counter()
            for item in base[zone]: baseline[key(item)] += item['count']
            needed, representatives = Counter(), {}
            for item in wanted[zone]: needed[key(item)] += item['count']; representatives[key(item)] = item
            extra[zone] = [{**deepcopy(representatives[k]), 'count': n - baseline[k]}
                           for k, n in needed.items() if n > baseline[k]]
            combined[zone] += extra[zone]
    return {'mainline': base, 'additional': extra, 'combined': combined,
            'branch_id': (branch or {}).get('id'), 'branch_name': (branch or {}).get('name'),
            'opponent_conditions': deepcopy((branch or {}).get('conditions', {}).get('hand', []))}


class Compromise:
    def __init__(self, store, read, write, write_bytes):
        self.store, self.read, self.write, self.write_bytes = store, read, write, write_bytes

    def path(self, identifier):
        self.store.session_path(identifier)
        return self.store.plans / 'branch-drafts' / (identifier + '.json')

    def script_identity(self):
        value = hashlib.sha256()
        for root in ('script', 'expansions/script'):
            for file in sorted((self.store.runtime / root).rglob('*.lua')):
                value.update(file.relative_to(self.store.runtime).as_posix().encode())
                value.update(hashlib.sha256(file.read_bytes()).digest())
        return value.hexdigest()

    def document(self, report):
        path = self.path(report['id'])
        if path.exists(): return self.read(path)
        return {'revision': report.get('branches_revision', 0), 'branches': deepcopy(report.get('branches', []))}

    def base(self, identifier):
        report = self.store._report(identifier)
        if report.get('compromise'): raise ValueError('本次只支持从主线创建妥协分支，不支持在分支内继续创建子分支')
        if report.get('plan_stage') not in ('draft', 'saved'): raise ValueError('请先完成主线，再创建妥协分支')
        return report

    def edit(self, report):
        if report.get('compromise'):
            return report
        result = deepcopy(report)
        doc = self.document(report)
        result['branches_revision'] = doc['revision']
        result['branches'] = self.snapshots(report, doc)
        if result['branches'] and result.get('review',{}).get('module_graph'):
            result['review']['module_graph']['branch_links']=[{'from_step':b['source']['node_id'],
                'from_module':b['source'].get('module_id',str(b['source']['checkpoint'])),
                'route':b['id'],'if_condition':deepcopy(b['if_condition'])} for b in result['branches']]
        elif result.get('review',{}).get('module_graph'):
            result['review']['module_graph'].pop('branch_links',None)
        if result['branches']:
            result['requirements'] = requirements(report)
        folder = self.store.session_path(report['id'])
        rows, issues = read_journal(folder / 'native.jsonl', report['id'])
        result['branch_points'] = branch_points(report, rows) if not issues else []
        result['branch_limit'] = '本次支持主线上的多个独立妥协分支，不支持嵌套。旧方案缺少重放记录时只能回看。'
        return result

    def snapshots(self, report, doc):
        result = deepcopy(doc['branches'])
        for branch in result:
            branch['valid'] = branch['source'].get('main_revision') == legacy_review(report)['revision']
            if not branch['valid']: branch['invalid_reason'] = '主线步骤已变化，原分支起点失效；请重新选择起点创建分支'
            sid = branch.get('session_id')
            if sid:
                frozen = next((b for b in report.get('branches', []) if b['id'] == branch['id'] and b.get('session_id') == sid and b.get('report')), None)
                # A formally saved route is self-contained, just like the mainline.
                # Its review must not depend on mutable or missing session files.
                if frozen:
                    current = deepcopy(frozen['report']); op = {'status': 'ready'}
                else:
                    current = self.store._report(sid)
                    operation = self.store.session_path(sid) / 'branch-operation.json'
                    op = self.read(operation) if operation.exists() else {'status': 'restoring'}
                branch['operation'] = op
                if op['status'] == 'ready':
                    current['annotations'] = annotations_for(current, branch.get('annotations'))
                    current['requirements'] = requirements(current)
                    if frozen:
                        rows = current.get('control_records', [])
                    else:
                        rows, _ = read_journal(self.store.session_path(sid) / 'native.jsonl', sid)
                        current['control_records'] = [deepcopy(r) for r in rows if r['seq'] > branch['source']['seq'] and
                            (r.get('kind') == 'opponent_control' or r.get('kind') == 'response' and r.get('actor') == 'opponent_manual')]
                    branch['premises'] = deepcopy(frozen.get('premises', [])) if frozen and branch.get('associations') == frozen.get('associations') else premises(current, branch['source']['seq'], rows, branch.get('associations'))
                    branch['report'] = current
            branch['if_condition'] = branch_condition(report,branch)
        return result

    def validate_save(self, report):
        for branch in report.get('branches', []):
            if not branch.get('session_id'): continue
            if branch.get('operation', {}).get('status') != 'ready' or not branch.get('report'):
                raise ValueError('存在未成功恢复的妥协分支，请重新构建或移除后再保存')
            self.store.validate_review_save(branch['report'])

    def mutate(self, identifier, expected, change):
        with self.store.lock:
            base = self.base(identifier)
            doc = self.document(base)
            if expected != doc['revision']: raise ValueError('分支已在其他页面修改，请重新载入后重试')
            change(base, doc)
            doc['revision'] += 1
            self.write(self.path(identifier), doc)
            return self.edit(base)

    def create(self, body):
        def change(base, doc):
            folder = self.store.session_path(base['id'])
            rows, issues = read_journal(folder / 'native.jsonl', base['id'])
            if issues: raise ValueError('原始记录不完整，无法准确恢复历史节点')
            point = next((p for p in branch_points(base, rows) if p['checkpoint'] == body.get('checkpoint') and p['node_id'] == body.get('node_id')), None)
            if not point: raise ValueError('此历史节点没有准确的可恢复时点，不能用场面快照继续对局')
            replay = folder / f"restore-{point['checkpoint']}.txt"
            if not replay.exists() or not (folder / 'core-calls.txt').exists(): raise ValueError('缺少完整引擎重放记录，此节点只能回看')
            source = {**point, 'main_revision': legacy_review(base)['revision'], 'replay_sha256': hashlib.sha256(replay.read_bytes()).hexdigest()}
            doc['branches'].append({'id': str(uuid.uuid4()), 'name': f"妥协分支 {len(doc['branches']) + 1}", 'source': source,
                'conditions': {'hand': point['opponent_hand'], 'expected_action': point['action_id'], 'note': '',
                               'if':{'kind':'recorded','required':[]}},
                'premises': [], 'annotations': None, 'associations': {}})
        return self.mutate(body['id'], body.get('revision'), change)

    def update(self, body):
        def retire(branch):
            sid = branch.pop('session_id')
            branch.setdefault('previous_sessions', []).append(sid)
            branch.setdefault('previous_annotations', {})[sid] = deepcopy(branch.get('annotations') or (branch.get('report') or {}).get('annotations'))
            for key in ('report', 'annotations', 'operation'): branch.pop(key, None)
            branch['premises'] = []
        def change(base, doc):
            branch = next((b for b in doc['branches'] if b['id'] == body.get('branch_id')), None)
            if branch is None: raise ValueError('妥协分支不存在')
            if branch.get('session_id'):
                metadata = self.store.session_path(branch['session_id']) / 'session.json'
                if metadata.exists() and self.store.alive(self.read(metadata)): raise ValueError('请先结束当前妥协展开，再修改条件或删除分支')
            if body.get('delete'):
                doc['branches'].remove(branch); return
            if body.get('reset') and branch.get('session_id'):
                retire(branch)
            name = body.get('name', branch['name'])
            if not isinstance(name, str) or not 0 < len(name.strip()) <= 80: raise ValueError('分支名称需为 1–80 个字符')
            branch['name'] = name.strip()
            if 'conditions' in body:
                value = body['conditions']; hand = value.get('hand')
                if not isinstance(hand, list) or len(hand) > 60: raise ValueError('对手场景手牌最多 60 张')
                for code in hand:
                    card = self.store.catalog.cards.get(code) if type(code) is int else None
                    if not card or card.get('extra') or card['type'] & 0x4000: raise ValueError('对手手牌只能配置有效的主卡组卡牌')
                action = value.get('expected_action')
                if action is not None and action not in [a['id'] for a in base['actions']]: raise ValueError('预期受干扰操作已失效')
                note = value.get('note', '')
                if not isinstance(note, str) or len(note) > 4000: raise ValueError('条件说明过长')
                conditions = {'hand': hand, 'expected_action': action, 'note': note,
                              'if':validate_if(value.get('if',branch['conditions'].get('if')),self.store.catalog.cards)}
                if Counter(hand) != Counter(branch['conditions']['hand']) and branch.get('session_id'):
                    retire(branch)
                branch['conditions'] = conditions
            if 'annotations' in body:
                saved = next((b.get('report') for b in base.get('branches', []) if b['id'] == branch['id'] and b.get('session_id') == branch.get('session_id')), None)
                route = saved or (self.store._report(branch['session_id']) if branch.get('session_id') else branch.get('report'))
                if not route: raise ValueError('请先完成妥协展开')
                branch['annotations'] = annotations_for(route, body['annotations'])
                if not branch.get('session_id'):
                    branch['report']['annotations'] = deepcopy(branch['annotations'])
                    branch['report']['requirements'] = requirements(branch['report'])
            if 'associations' in body:
                saved = next((b.get('report') for b in base.get('branches', []) if b['id'] == branch['id'] and b.get('session_id') == branch.get('session_id')), None)
                route = saved or branch.get('report') or (self.store._report(branch['session_id']) if branch.get('session_id') else base)
                actions = {a['id'] for a in route['actions']}
                associations = body['associations']
                if not isinstance(associations, dict) or len(associations) > 1000: raise ValueError('关联说明无效')
                for key, value in associations.items():
                    if key not in actions or value.get('action_id') not in actions or not isinstance(value.get('note', ''), str) or len(value.get('note', '')) > 4000:
                        raise ValueError('关联操作或说明无效')
                branch['associations'] = deepcopy(associations)
                if not branch.get('session_id') and branch.get('report'):
                    branch['premises'] = premises(branch['report'], branch['source']['seq'], [], branch['associations'])
        return self.mutate(body['id'], body.get('revision'), change)

    def enter(self, body):
        with self.store.lock:
            base = self.base(body['id']); doc = self.document(base)
            if body.get('revision') != doc['revision']: raise ValueError('分支条件已更新，请重新载入')
            branch = next((b for b in doc['branches'] if b['id'] == body.get('branch_id')), None)
            if not branch or branch['source']['main_revision'] != legacy_review(base)['revision']: raise ValueError('分支起点已失效')
            if branch.get('session_id'): raise ValueError('本分支已进入过场地；修改前置条件后可创建新的模拟尝试，原始记录保留')
            folder = self.store.session_path(base['id'])
            meta = self.read(folder / 'session.json')
            if not meta.get('scripts_sha256') or meta['scripts_sha256'] != self.script_identity():
                raise ValueError('效果脚本版本无法核对或已改变，不能准确恢复；请重新记录主线')
            if meta['engine_sha256'] != hashlib.sha256((self.store.runtime / 'YGOPro.exe').read_bytes()).hexdigest() or meta['sources'] != self.store.catalog.sources:
                raise ValueError('引擎或卡牌数据版本已改变，无法准确恢复；请在当前版本重新记录主线')
            replay = folder / f"restore-{branch['source']['checkpoint']}.txt"
            if hashlib.sha256(replay.read_bytes()).hexdigest() != branch['source']['replay_sha256']: raise ValueError('分支恢复记录已变化，拒绝近似恢复')
            setup = {'root_id': base['id'], 'branch_id': branch['id'], 'name': branch['name'], 'source': branch['source'], 'hand': branch['conditions']['hand']}
            result = self.store.start(meta['selected_deck'], retry_meta=meta, branch_setup=setup)
            branch['session_id'] = result['id']; doc['revision'] += 1; self.write(self.path(base['id']), doc)
            return {**result, 'root_id': base['id'], 'branch_id': branch['id'], 'branches_revision': doc['revision']}

    def prepare(self, path, meta, setup):
        original = self.store.session_path(setup['root_id'])
        for source, target in [('core-calls.txt', 'replay-calls.txt'), (f"restore-{setup['source']['checkpoint']}.txt", 'restore.txt'), ('opening.cfg', 'opening.cfg'), ('opponent.ydk', 'opponent.ydk')]:
            if (original / source).exists(): self.write_bytes(path / target, (original / source).read_bytes())
        rows, issues = read_journal(original / 'native.jsonl', setup['root_id'])
        if issues: raise ValueError('主线原始记录不完整')
        inherited = [r for r in rows if r['seq'] <= setup['source']['seq']]
        self.write_bytes(path / 'inherit.jsonl', ''.join(json.dumps({**r, 'session': meta['id']}, ensure_ascii=False) + '\n' for r in inherited).encode())
        maximum = max((r.get('node', 0) for r in inherited), default=0)
        self.write_bytes(path / 'branch.cfg', (' '.join(map(str, [maximum, len(setup['hand']), *setup['hand']])) + '\n').encode())

    def control(self, body):
        with self.store.lock:
            path = self.store.session_path(body['id']); meta = self.read(path / 'session.json')
            if not meta.get('compromise') or not self.store.alive(meta): raise ValueError('当前没有可接管的妥协对局')
            state = self.opponent(body['id'])
            command = body.get('command')
            if command not in ('take', 'release', 'answer'): raise ValueError('对手控制操作无效')
            if state.get('version') != body.get('version'): raise ValueError('对局已进入新的选择窗口，请刷新后重试')
            raw = '-'
            if command == 'answer':
                if not state.get('manual') or state.get('player') != 1 or state.get('answered'): raise ValueError('当前不是可提交的对手选择窗口')
                raw = body.get('raw', '')
                if not isinstance(raw, str) or not 0 < len(raw) <= 128 or len(raw) % 2 or any(c not in '0123456789abcdef' for c in raw): raise ValueError('选择数据无效')
            if (path / 'opponent.request').exists(): raise ValueError('上一项对手操作尚在处理，请稍候')
            token = uuid.uuid4().hex
            self.write_bytes(path / 'opponent.request', f"{command} {state['version']} {token} {raw}\n".encode())
            return {'token': token, 'status': 'queued'}

    def opponent(self, identifier):
        path = self.store.session_path(identifier); meta = self.read(path / 'session.json')
        if not meta.get('compromise'): raise ValueError('仅妥协分支提供对手操作窗口')
        result = self.read(path / 'opponent-state.json') if (path / 'opponent-state.json').exists() else {'version': 0, 'manual': True, 'player': -1}
        result.update(id=identifier, running=self.store.alive(meta), context=meta['compromise'])
        if (path / 'branch-operation.json').exists(): result['operation'] = self.read(path / 'branch-operation.json')
        return result
