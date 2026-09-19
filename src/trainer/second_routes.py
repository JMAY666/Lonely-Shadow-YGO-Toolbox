"""Read-only native checkpoints and isolated, sourced second-turn continuations.

Only the same local practice's complete replay tape supplies rules state. A
manually assembled board or an external game's opening cannot stand in for it.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import threading
import time
import uuid

from modular_decisions import canonical_state, digest, public_state
from planning_preferences import PREFERENCES
from report import read_journal
from timeline import route_rows
from second_native import ANNOTATIONS, stage_of, supported_window, native_window, carry_annotations, public_actions, public_outcomes


PHASES = {1: 'draw', 2: 'standby', 4: 'main1', 8: 'battle', 16: 'battle', 32: 'battle', 64: 'battle', 128: 'battle', 256: 'main2', 512: 'end'}


def same_deck(a, b):
    return all(Counter(a.get(k, [])) == Counter(b.get(k, [])) for k in ('main', 'extra', 'side'))


def observed_state(native, previous=None):
    """Project known information; never copy hidden identities or deck order."""
    state = public_state(native)
    previous = previous or {}
    mapped = {c.get('native_instance'): c['id'] for c in previous.get('cards', []) if c.get('native_instance') is not None}
    cards = []
    for c in state['cards']:
        if c['controller'] == 1 and c['location'] in (1, 2, 64):
            continue
        native_id = c.get('instance_id')
        identifier = mapped.get(native_id) if native_id is not None else None
        row = {'id': identifier or uuid.uuid4().hex, 'code': c.get('code'), 'owner': c.get('owner', c['controller']),
               'controller': c['controller'], 'location': c['location'], 'position': c.get('position', 0),
               'source': 'native_public_checkpoint'}
        if native_id is not None: row['native_instance'] = native_id
        for key in ('sequence', 'disabled', 'overlay_target', 'atk', 'def', 'level', 'type'):
            if key in c: row[key] = c[key]
        cards.append(row)
    ids = {c['native_instance']: c['id'] for c in cards if 'native_instance' in c}
    for c in cards:
        if c.get('overlay_target') is not None: c['parent_id'] = ids.get(c.pop('overlay_target'))
    return {'turn': state['turn'], 'turn_player': state['turn_player'], 'phase': PHASES.get(state['phase'], 'unknown'),
            'lp': state['lp'], 'cards': cards, 'opponent_hand_count': int(state['unknown'].get('2', 0)),
            'usage': [], 'restrictions': [], 'window': None, 'stale_reason': '',
            'native_rules': {'basis': 'exact_replay', 'normal_summons_used': state.get('normal_summons_used'),
                             'effect_usage': state.get('effect_usage', []),
                             'notice': '次数和持续限制由完整重放恢复；未公开的对手次数不展示'}}


def visible_candidate(candidate):
    # Do not publish native prompts, effects tables, raw responses or hidden
    # source catalogues through the observations workspace.
    keys = ('id', 'remaining', 'conditional', 'validation', 'reason', 'terminal', 'terminal_source',
            'resource_cost', 'evaluation', 'observation_required', 'adaptations')
    result = {k: deepcopy(candidate[k]) for k in keys if k in candidate}
    result['steps'] = [{k: deepcopy(step[k]) for k in ('source', 'bound_decision', 'automatic', 'effect_label',
                      'operation_label', 'before', 'state') if k in step} for step in candidate['steps']]
    result['assumption'] = '对手不追加响应；公开场面响应和实际偏差需同步真实练习后重算'
    result['battle'] = '本路线未验证战斗；请在实际场面同步后，单独验证指定攻击顺序'
    return result


class SecondRoutes:
    def __init__(self, owner):
        self.owner, self.store = owner, owner.store
        self.bindings = {}
        self.operations = threading.Lock()

    def request(self, body):
        doc = self.owner.load(body.get('id'))
        if body.get('round_id') != doc['input']['round_id'] or body.get('revision') != doc['revision']:
            raise ValueError('局次或观察版本已变化，请刷新后重试')
        if doc['closed'] or doc['epoch'] != self.owner.epoch:
            raise ValueError('此记录已结束或应用已重启，请新建记录或核对后恢复')
        if doc['input']['platform'] != 'manual' or doc['input'].get('connection'):
            raise ValueError('本期只接入有完整日志的本机内置后攻练习；外部平台缺少可重放历史')
        return doc

    def sample(self, sid, doc):
        folder = self.store.session_path(sid)
        meta = self.owner.read(folder / 'session.json')
        if (meta.get('purpose') == 'duel_planning' or meta.get('compromise')
                or meta.get('expansion', {}).get('turn_order') != 'second'):
            raise ValueError('请选择本机内置后攻主线练习；推演副本和妥协分支不能当作实战来源')
        if not same_deck(meta['deck'], doc['input']['deck']) or Counter(meta['expansion']['actual_opening']) != Counter(doc['input']['opening']['cards']):
            raise ValueError('练习构筑或原始起手与本局不同，不能仅凭当前手牌匹配')
        node = self.owner.read(folder / 'modular-state.json')
        if any(type(node.get(k)) is not int or not 0 <= node[k] <= 2**53 for k in ('node', 'version', 'revision')):
            raise ValueError('原生决策节点标识不完整或无效，拒绝恢复')
        state = node['state']
        if node.get('answered') or not node.get('raw') or not supported_window(node):
            raise ValueError('等待对手首回合的我方响应窗口，或我方首回合已结算的主要阶段／战斗操作点；其他选择需在原练习中完成')
        restore = folder / f"restore-{node['node']}.txt"
        tape = folder / 'core-calls.txt'
        if not restore.exists() or not tape.exists():
            raise ValueError('缺少完整重放记录，场面快照不能恢复次数与持续限制')
        return meta, node, digest([sid, node['version'], node['revision'], node['node'],
                                    hashlib.sha256(restore.read_bytes()).hexdigest()])

    def sources(self, body):
        with self.owner.lock:
            doc = self.request(body)
        records = []
        for row in self.store.history()[:100]:
            try:
                meta, node, stamp = self.sample(row['id'], doc)
                records.append({'id': row['id'], 'name': meta['name'], 'status': row['status'],
                                'checkpoint': node['node'], 'stamp': stamp,
                                'stage': stage_of(node),
                                'hand_count': sum(c['controller'] == 0 and c['location'] == 2 for c in node['state']['cards'])})
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return {'records': records, 'notice': '仅列出构筑、原始起手匹配且具备完整日志的内置后攻主线；最多检查最近 100 项。无记录不表示规则上无路线。'}

    def connection_error(self, doc, force=False):
        link = doc.get('native_link')
        if not link: return ''
        try:
            meta, node, stamp = self.sample(link['source'], doc)
            if stamp != link['stamp']: return '原练习已进入新窗口，请同步实际局面；旧提示和路线已停止采用'
            if link['rules'] != self.store.modular.precompute.rules(force=force):
                return '规则资源已变化，请重新同步核对，旧建议不能采用'
            if stage_of(node) == 'opponent_turn' and not self.store.alive(meta): return '原练习已结束，对手响应窗口仅供回看'
        except (OSError, ValueError, KeyError, TypeError):
            return '原练习当前窗口无法可靠读取，请完成原练习中的选择后重新同步'
        return ''

    def check_annotation(self, doc, kind, payload):
        if not doc.get('native_link') or kind == 'close': return
        if kind not in ANNOTATIONS:
            raise ValueError('本局已关联原生练习；卡牌、费用、抽牌、次数和处理结果请在原练习操作后同步，不能重复手填')
        if kind in ('choice', 'result', 'invalidate', 'resume'): return
        error = self.connection_error(doc, force=True)
        if error: raise ValueError(error)
        if kind == 'verify' and any(payload.get(key) != doc['current'][key] for key in ('turn', 'turn_player', 'phase', 'lp', 'opponent_hand_count')):
            raise ValueError('核对值与当前原生日志不同；请同步实际局面，不能用人工值覆盖')

    def annotated(self, doc, kind):
        binding = self.bindings.get(doc['id'])
        if not binding: return
        if kind == 'close': self.invalidate(doc['id']); return
        binding.update(revision=doc['revision'], result=None, status='ready', generation=uuid.uuid4().hex,
                       reason='人工条件或备注已记录；实际资源继续以原生日志同步')
        binding.pop('raw_result', None)
        ctx = self.store.modular.sessions.get(binding['sid'])
        if ctx:
            ctx['preference_version'] += 1
            ctx['result'] = None

    def valid(self, doc, binding, *, force=False):
        if not binding or binding.get('cancelled') or binding['revision'] != doc['revision'] or self.owner.status(doc):
            return False
        try:
            _, _, stamp = self.sample(binding['source'], doc)
            modular = self.store.modular
            ctx = modular.sessions.get(binding['sid'])
            if not ctx or ctx.get('forecast_cancelled') or not modular.state(binding['sid'])['running']:
                return False
            if binding.get('raw_result'):
                modular.library.sync()
                if binding['raw_result']['token'][2] != digest({sid: modular.library.entries.get(sid, {}).get('version') for sid in ctx['selected']}):
                    return False
            return (stamp == binding['stamp'] and binding['rules'] == self.store.modular.precompute.rules(force=force)
                    and binding['sid'] in self.store.planning)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def public(self, doc):
        binding = self.bindings.get(doc['id'])
        value = {'supported': doc['input']['platform'] == 'manual', 'linked': bool(doc.get('native_link')),
                 'current': self.valid(doc, binding), 'status': (binding or {}).get('status', 'unlinked'),
                 'route_ready': bool(binding and binding.get('stage', 'own_turn') == 'own_turn'),
                 'battle_ready': bool(binding and binding.get('stage', 'own_turn') in ('own_turn','battle')),
                 'reason': (binding or {}).get('reason', '仅有场面记录尚不能重建规则状态，请关联同一内置后攻练习'),
                 'history': deepcopy(doc.get('route_history', []))}
        if value['linked'] and not value['current']:
            value['reason'] = '原练习、观察或规则已变化，旧路线停止采用；请同步当前实际决策点'
        if binding:
            value.update(result=deepcopy(binding.get('result')), sources=deepcopy(binding.get('sources', [])),
                         preferences=list(PREFERENCES), selected=deepcopy(binding.get('selected', [])),
                         preference=binding.get('preference', 'largest'), goal=binding.get('goal', 'clear'))
            try:
                value['source_running'] = self.store.alive(self.owner.read(self.store.session_path(binding['source']) / 'session.json'))
            except (OSError, ValueError, KeyError):
                value['source_running'] = False
        return value

    def invalidate(self, key):
        binding = self.bindings.pop(key, None)
        if not binding: return
        binding['cancelled'] = True
        ctx = self.store.modular.sessions.get(binding['sid'])
        if ctx: ctx['forecast_cancelled'] = True
        def cleanup():
            from duel_planner import close
            with self.operations, self.store.modular.planning_lock:
                close(self.store.modular, binding['sid'])
        threading.Thread(target=cleanup, daemon=True).start()

    def library_sources(self, meta):
        modular = self.store.modular
        saved = self.store.get_deck(meta['selected_deck'])
        modular.library.sync()
        selection = saved.get('tag_selection', {})
        allowed = modular.library.deck_source_ids(selection)
        return selection, [s for s in modular.library.summary()['sources'] if s['id'] in allowed]

    def sync(self, body):
        from duel_planner import close
        from second_duel import MAX_EVENTS
        modular = self.store.modular
        with self.operations, modular.planning_lock:
            with self.owner.lock:
                doc = deepcopy(self.request(body))
            source_id = body.get('source_id')
            if body.get('confirmed') is not True:
                raise ValueError('请确认关联的是本局内置练习；该操作导入已发生的公开记录')
            if doc.get('native_link') and doc['native_link']['source'] != source_id:
                raise ValueError('本局已关联其他练习，不能换来源覆盖已执行历史；请另开记录')
            if not doc.get('native_link') and doc['events']:
                raise ValueError('已有人工观察不能被练习快照覆盖；请用相同起手另开空白后攻记录')
            if doc.get('native_link'):
                latest = max((i for i, event in enumerate(doc['events']) if event['kind'] == 'native_sync'), default=-1)
                if any(e['kind'] not in ANNOTATIONS for e in doc['events'][latest+1:]):
                    raise ValueError('同步后已有独立人工资源修改，不能静默覆盖；请另开记录核对当前练习')
            if len(doc['events']) >= MAX_EVENTS:
                raise ValueError('观察记录容量已满，原历史保留')
            meta, node, stamp = self.sample(source_id, doc)
            if body.get('stamp') and body['stamp'] != stamp:
                raise ValueError('所选练习决策点已变化，请刷新列表')
            rules = modular.precompute.rules(force=True)
            if (meta.get('engine_sha256') != hashlib.sha256((self.store.runtime / 'YGOPro.exe').read_bytes()).hexdigest()
                    or meta.get('scripts_sha256') != self.store.compromise.script_identity()
                    or meta.get('sources') != self.store.catalog.sources):
                raise ValueError('练习的引擎、卡库或脚本与当前资源不同，拒绝近似重建')
            folder = self.store.session_path(source_id)
            rows, issues = read_journal(folder / 'native.jsonl', source_id)
            if issues: raise ValueError('原始日志不完整，不能重建规则历史')
            active = route_rows(rows)[0]
            target = next((r for r in reversed(active) if r.get('kind') == 'checkpoint' and r.get('node') == node['node']), None)
            if not target: raise ValueError('当前引擎节点没有对应原始记录')
            history = [{'node': r['node'], 'seq': r['seq'], 'player': r.get('player'), 'state': public_state(r['state'])}
                       for r in active if r.get('kind') == 'checkpoint' and r['seq'] <= target['seq']]
            old_history = doc.get('native_history', [])
            if history[:len(old_history)] != old_history:
                raise ValueError('原练习已回退或改写此前路径；已执行历史保留，请另开记录')
            if old_history and len(history) == len(old_history):
                existing = self.bindings.get(doc['id'])
                if self.valid(doc, existing, force=True):
                    selection, sources = self.library_sources(meta)
                    modular.context(existing['sid'])['forecast_meta']['tag_selection'] = selection
                    existing['sources'] = sources
                    if not set(existing['selected']) <= {s['id'] for s in sources}:
                        existing.update(selected=[], result=None)
                        existing.pop('raw_result', None)
                    return self.owner.public(doc)
            setup = {'root_id': source_id, 'branch_id': str(uuid.uuid4()), 'name': '后攻规则重放副本',
                     'source': {'checkpoint': node['node'], 'seq': target['seq']},
                     'hand': [c['code'] for c in node['state']['cards'] if c['controller'] == 1 and c['location'] == 2]}
            sid = None
            try:
                sid = self.store.start(meta['selected_deck'], retry_meta=meta, branch_setup=setup, planning=True)['id']
                destination = self.store.session_path(sid)
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    operation = self.owner.read(destination / 'branch-operation.json') if (destination / 'branch-operation.json').exists() else {}
                    if operation.get('status') == 'error': raise ValueError('规则重放失败：' + operation.get('error', 'unknown'))
                    if operation.get('status') == 'ready' and (destination / 'modular-state.json').exists(): break
                    if self.store.closing or self.store.processes[sid].poll() is not None: raise ValueError('隔离引擎已结束，原练习保留')
                    time.sleep(.04)
                else: raise ValueError('规则重放超时，原练习与观察未变更')
                restored = modular.state(sid)
                common_keys = set(node['state']) & set(restored['state'])
                if canonical_state({k: node['state'][k] for k in common_keys}) != canonical_state({k: restored['state'][k] for k in common_keys}):
                    raise ValueError('重放结果与原练习的完整规则场面不一致')
                selection, sources = self.library_sources(meta)
                known = {c.get('code') for h in history for c in h['state']['cards'] if c.get('code')}
                catalogue = {str(code): deepcopy(self.store.catalog.cards[code]) for code in known if code in self.store.catalog.cards}
                ctx = modular.context(sid)
                ctx.update(forecast_meta={'consumer': 'second-duel', 'automatic_context': doc['id'],
                           'catalog': catalogue, 'initial': public_state(restored['state']), 'tag_selection': selection,
                           'rules_version': rules, 'inputs': {'engine': meta['engine_sha256'], 'scripts': meta['scripts_sha256'], 'checkpoint': stamp}},
                           forecast_steps=[])
                updated = deepcopy(doc)
                updated['current'] = carry_annotations(observed_state(restored['state'], doc['current']), doc['current'])
                updated['current']['native_window'] = native_window(restored, updated['current'])
                updated['catalog'].update(catalogue)
                updated.update(native_history=history, revision=doc['revision'] + 1, updated_ms=self.owner.now(),
                               native_actions=public_actions(active, folder, target['seq']),
                               native_outcomes=public_outcomes(active, target['seq']),
                               native_link={'source': source_id, 'checkpoint': node['node'], 'seq': target['seq'], 'stamp': stamp, 'rules': rules})
                updated['events'].append({'id': uuid.uuid4().hex, 'request_hash': digest(body), 'kind': 'native_sync',
                    'payload': {'source': source_id, 'checkpoint': node['node']}, 'source': 'native_public_checkpoint',
                    'time_ms': self.owner.now(), 'revision': updated['revision'], 'summary': '只读同步本机后攻练习；完整历史重放通过',
                    'before': doc['current'], 'after': deepcopy(updated['current'])})
                with self.owner.lock:
                    self.request(body)
                    if self.sample(source_id, doc)[2] != stamp or modular.precompute.rules(force=True) != rules:
                        raise ValueError('重建期间原练习或规则已变化，未发布旧局面')
                    self.owner.save(updated)
                    self.invalidate(doc['id'])
                    self.bindings[doc['id']] = {'sid': sid, 'source': source_id, 'stamp': stamp, 'rules': rules,
                        'stage': stage_of(node),
                        'revision': updated['revision'], 'status': 'ready', 'reason': {'own_turn':'完整历史重放通过；可以选择来源比较后续或验证攻击顺序',
                            'battle':'战斗操作点已重建；可以验证尚未执行的指定攻击顺序',
                            'after_battle':'已同步主要阶段 2；当前只供回看，未接入此阶段的展开续算',
                            'opponent_turn':'对手回合响应点已重建；请核对当前具体效果和干扰条件'}[stage_of(node)],
                        'sources': sources,
                        'selected': [], 'preference': 'largest'}
                    return self.owner.public(updated)
            except Exception:
                if sid: close(modular, sid)
                raise

    def generate(self, body):
        modular = self.store.modular
        with self.owner.lock:
            doc = self.request(body)
            binding = self.bindings.get(doc['id'])
            if not self.valid(doc, binding, force=True): raise ValueError('请先同步本局真实规则状态；仅凭手牌或场面不能续算')
            if binding.get('stage', 'own_turn') != 'own_turn': raise ValueError('路线续算只支持我方首回合主要阶段 1；请同步对应的实际操作点')
            if any(r['status'] != 'expired' for r in doc['current']['usage'] + doc['current']['restrictions']):
                raise ValueError('还有未结构化的人工次数或限制备注，请先核对；不能静默合并到原生规则权限')
            if binding['status'] == 'running': return self.owner.public(doc)
            selected, preference = body.get('sources'), body.get('preference', 'largest')
            goal = body.get('goal', 'clear')
            modular.library.sync()
            modular.library.validate_deck_sources(modular.context(binding['sid'])['forecast_meta']['tag_selection'], selected)
            if preference not in PREFERENCES: raise ValueError('请选择有效的路线偏好')
            if goal not in ('clear', 'develop'): raise ValueError('请选择已支持的解场或展开目标')
            binding.update(status='running', reason='在隔离引擎中核对后攻场面和来源操作', result=None,
                           selected=list(selected), preference=preference, goal=goal, generation=uuid.uuid4().hex)
            binding.pop('raw_result', None)
            generation, version = binding['generation'], doc['revision']
        def work():
            try:
                with self.operations, modular.planning_lock:
                    if binding.get('cancelled'): return
                    ctx = modular.context(binding['sid'])
                    ctx['forecast_meta']['second_constraints'] = {'turn': 2, 'phase': 4,
                        'clear_instances': [c['instance_id'] for c in modular.state(binding['sid'])['state']['cards']
                            if goal == 'clear' and c.get('controller') == 1 and c.get('location') == 4 and c.get('position', 0) & 5]}
                    modular.configure({'id': binding['sid'], 'sources': selected, 'preference': preference, 'precise': False, 'goal': []})
                    result = modular.search(binding['sid'], refresh=True, limits={'seconds': 24, 'nodes': 240})
                    # Sourced routes stay in Main Phase 1. Explicit attack-order
                    # validation has a separate, bounded entry point.
                    candidates = [c for c in result['candidates'] if all(s['state'].get('turn') == 2 and s['state'].get('phase') == 4 for s in c['steps'])]
                    with self.owner.lock:
                        current = self.owner.load(doc['id'])
                        if (binding.get('generation') != generation or current['revision'] != version
                                or not self.valid(current, binding, force=True)):
                            binding.update(status='stale', reason='计算期间实际局面或规则已变化，结果未发布'); return
                        view = {k: deepcopy(result[k]) for k in ('status', 'complete', 'limited', 'nodes', 'seconds', 'coverage', 'rejected', 'notice')}
                        view['candidates'] = [visible_candidate(c) for c in candidates[:3]]
                        if not candidates: view['status'] = 'limited' if result.get('limited') else 'incomplete'
                        saved = deepcopy(current)
                        saved.setdefault('route_history', []).append({'id': generation, 'revision': version,
                            'created_ms': self.owner.now(), 'source': deepcopy(current['native_link']),
                            'preference': preference, 'goal': goal, 'result': deepcopy(view), 'choices': []})
                        if len(saved['route_history']) > 80: raise ValueError('本局路线历史已满，原历史保留')
                        self.owner.save(saved)
                        binding.update(raw_result=result, result=view, status='ready',
                                       reason='候选仅覆盖所选来源与对手不追加响应分支；实际变化后重新同步')
            except Exception as error:
                if binding.get('generation') == generation and not binding.get('cancelled'):
                    binding.update(status='error', reason=str(error), result=None)
        threading.Thread(target=work, daemon=True).start()
        with self.owner.lock: return self.owner.public(self.owner.load(doc['id']))

    def choose(self, body):
        with self.owner.lock:
            doc = self.request(body)
            binding = self.bindings.get(doc['id'])
            if not self.valid(doc, binding, force=True) or binding.get('status') != 'ready':
                raise ValueError('实际局面或计算已变化，旧路线不能采用')
            candidate = next((c for c in (binding.get('result') or {}).get('candidates', []) if c['id'] == body.get('candidate')), None)
            if not candidate or not self.store.modular.valid_token(binding['sid'], binding['raw_result']['token']):
                raise ValueError('路线来源或候选已变化，请重新生成')
            updated = deepcopy(doc)
            history = next((h for h in updated.get('route_history', []) if h['id'] == binding['generation']), None)
            if not history: raise ValueError('路线历史缺失，请重新生成')
            if len(history['choices']) >= 30: raise ValueError('本次选择记录已达上限')
            history['choices'].append({'candidate': candidate['id'], 'time_ms': self.owner.now(), 'basis': 'intention_only'})
            self.owner.save(updated)
            return self.owner.public(updated)

    def dispatch(self, action, body):
        if action == 'route-battle':
            from second_battle import preview
            return preview(self, body)
        return {'route-sources': self.sources, 'route-sync': self.sync, 'route-generate': self.generate,
                'route-choose': self.choose}[action](body)
