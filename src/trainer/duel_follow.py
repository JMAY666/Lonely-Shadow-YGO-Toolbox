"""Selected-route following; adapters, evidence, matching and UI stay separate."""
from collections import Counter
from copy import deepcopy
import threading
import time
import uuid

from automatic_duel import digest
from duel_follow_events import EvidenceError, Journal, match_token, packet, signature
from protocol import packets


def expected_state(state):
    cards = deepcopy([c for c in (state or {}).get('cards', []) if c.get('controller') == 0 and c.get('location')])
    for card in cards:
        if card['location'] == 128:
            hosts = [c for c in cards if c.get('instance_id') == card.get('overlay_target') and c['location'] == 4]
            if len(hosts) != 1: raise EvidenceError('素材缺少唯一宿主实例')
            card.update(location=132, position=card['sequence'], sequence=hosts[0]['sequence'])
    return {'cards': cards, 'counts': dict(Counter(c['location'] for c in cards))}


def manual_expected(contract, state, inputs):
    """Preserve unused opening cards when checking a saved minimum-hand route."""
    result = expected_state(state)
    if contract['kind'] != 'formal': return result
    initial = {int(k): v for k, v in contract.get('initial_counts', {}).items()}
    if not initial: raise EvidenceError('方案缺少起点区域数量，不能人工核对结果')
    extra = Counter(inputs['hand']) - Counter(contract['hand'])
    counts = result['counts']
    counts[1] = counts.get(1, 0) + len(inputs['deck']['main']) - initial.get(1, 0) - initial.get(2, 0) - sum(extra.values())
    counts[2] = counts.get(2, 0) + sum(extra.values())
    counts[64] = counts.get(64, 0) + len(inputs['deck']['extra']) - initial.get(64, 0)
    for code, number in extra.items():
        result['cards'].extend({'code': code, 'controller': 0, 'location': 2, 'sequence': 0, 'position': 0}
                               for _ in range(number))
    return result


def own_initial(state):
    if not state or state.get('partial'): raise EvidenceError('方案缺少完整起手状态')
    cards = [c for c in state.get('cards', []) if c.get('controller') == 0]
    hand = sorted((c for c in cards if c['location'] == 2), key=lambda c: c['sequence'])
    if not hand or any(c['location'] not in (1, 2, 64) for c in cards):
        raise EvidenceError('首版只从本局初始起手路线建立跟随')
    journal = Journal([c['code'] for c in hand], sum(c['location'] in (1, 2) for c in cards),
                      sum(c['location'] == 64 for c in cards))
    journal.turn = state.get('turn', 1)
    return journal, [c['code'] for c in hand]


def check_step(tokens, journal, node):
    if not tokens: return '本步骤缺少可验证的操作事件，请人工核对'
    if not journal.settled: return '本步骤处于召唤或连锁内部，不能自动认定已完成'
    if not node.get('state') or node['state'].get('partial'): return '本步骤缺少完整结果快照'
    try:
        if signature(journal.state()) != signature(expected_state(node['state'])):
            return '原始操作事件与步骤结果快照不一致，不能自动跟随'
    except (ValueError, KeyError): return '结果快照缺少可验证的卡牌或素材身份'
    if any(t['message'] == 70 for t in tokens) and not any(t['message'] in (50, 53, 91, 92, 94, 100) for t in tokens):
        return '效果已处理的记录不足以证明本步骤结果，需人工核对'
    return ''


def formal_contract(plan):
    nodes = plan.get('review', {}).get('nodes', [])
    initial = next((n.get('state') for n in nodes if n.get('kind') == 'initial'), None)
    journal, hand = own_initial(initial)
    if not plan.get('review', {}).get('complete'): raise EvidenceError('旧方案的逐步记录不完整，保留手动教程')
    previous = next((n.get('state_ref') for n in nodes if n.get('kind') == 'initial'), None)
    steps = []; broken = False
    for node in nodes:
        if node.get('kind') != 'step': continue
        if broken:
            steps.append({'key': 'main/'+node['id'], 'tokens': [], 'reason': '前序证据不完整，此步骤需要人工核对或重新选择方案',
                          'expected': deepcopy(node.get('state')), 'instances': {'cards': []}})
            continue
        start = len(journal.tokens)
        reason = ''
        end = node.get('state_ref')
        if not isinstance(previous, int) or not isinstance(end, int) or end < previous:
            reason = '步骤缺少连续事件范围'
        else:
            records = [e for e in plan.get('events', []) if type(e.get('message')) is int and previous < e.get('native_seq', -1) <= end]
            try:
                for event in records:
                    if 'raw' not in event: raise EvidenceError('步骤缺少原始操作证据')
                    journal.apply(packet(event['message'], bytes.fromhex(event['raw'])))
            except (ValueError, KeyError, IndexError) as error: reason = str(error)
        tokens = deepcopy(journal.tokens[start:])
        reason = reason or check_step(tokens, journal, node)
        steps.append({'key': 'main/'+node['id'], 'tokens': tokens, 'reason': reason,
                      'expected': deepcopy(node.get('state')), 'instances': journal.state()})
        previous = end
        # Unread evidence after a broken step must not acquire guessed identities.
        if reason: broken = True
    if not steps: raise EvidenceError('方案没有可跟随的操作步骤')
    return {'kind': 'formal', 'hand': hand, 'steps': steps, 'revision': plan['automatic_revision'],
            'initial_counts': expected_state(initial)['counts']}


def starts_operation(step):
    return any(c.get('kind') in ('summon', 'special', 'activate', 'spell_set', 'monster_set') or
               c.get('kind') == 'yes' and c.get('effect')
               for c in (step.get('bound_decision') or step.get('decision') or {}).get('selection', []))


def temporary_contract(modular, sid, ctx):
    route = ctx['forecast_route']; candidate = route['candidate']
    if len(candidate.get('path', [])) > 256: raise EvidenceError('路线超过首版证据编译上限，请选择较短路线')
    if route.get('prefix') or route['base'].get('_prefix'):
        raise EvidenceError('续接临时方案带有既有前缀，首版需要从本局起手选择路线后跟随')
    journal, hand = own_initial(ctx['forecast_meta']['initial'])
    journal.turn = route['base'].get('state', {}).get('turn', 1)
    groups = []
    for i, step in enumerate(candidate['steps']):
        previous = groups[-1] if groups else None
        leading = previous and not any(starts_operation(s) for s in previous['steps'])
        if not groups or starts_operation(step) and not leading: groups.append({'start': i, 'steps': []})
        groups[-1]['steps'].append(step); groups[-1]['end'] = i
    result, path_index, broken = [], 0, False
    for i, group in enumerate(groups):
        start = len(journal.tokens); reason = ''
        last = group['steps'][-1]
        if broken:
            result.append({'key': f'main/forecast-{i}', 'tokens': [], 'reason': '前序证据不完整，此步骤需要人工核对或重新选择方案',
                           'index': group['start'], 'through': group['end'], 'expected': deepcopy(last.get('state')),
                           'instances': {'cards': []}})
            continue
        try:
            while path_index < last['path_end']:
                path_index += 1
                value = modular.bridge(sid, route['base'], candidate['path'][:path_index])
                for batch in value['batches']:
                    for _, kind, raw in packets(bytes.fromhex(batch)): journal.apply(packet(kind, raw))
        except (ValueError, KeyError, IndexError) as error: reason = str(error)
        tokens = deepcopy(journal.tokens[start:])
        reason = reason or check_step(tokens, journal, last)
        if candidate.get('observation_required') and group['end'] == len(candidate['steps'])-1:
            reason = '本步骤需要报告实际随机结果，不能自动确认'
        result.append({'key': f'main/forecast-{i}', 'tokens': tokens, 'reason': reason,
                       'index': group['start'], 'through': group['end'], 'expected': deepcopy(last.get('state')),
                       'instances': journal.state()})
        if reason: broken = True
    if not result: raise EvidenceError('临时路线没有可跟随的操作步骤')
    return {'kind': 'temporary', 'hand': hand, 'steps': result, 'planner_id': sid,
            'route': route['id'], 'revision': digest([route['id'], candidate, ctx['forecast_meta']['inputs']])}


class Follower:
    """Pure evidence matcher; completed prefix is independent of view position."""
    def __init__(self, contract, hand):
        self.contract = contract
        self.hand = hand
        self.journal = Journal()
        self.records = []
        self.identity = None
        self.bindings = {}
        self.completed = []
        self.token_index = 0
        self.status = 'syncing'
        self.reason = ''
        self.snapshot = None
        self.sampled_ms = None
        self.paused = False
        self.requires_sync = False
        self.seen = {}
        self.last_consistent_ms = None
        self.mismatch_samples = 0
        self.prompt = None

    def stop(self, reason, status='needs_confirmation'):
        self.status, self.reason, self.requires_sync = status, reason, True

    def ingest(self, sample):
        identity = (sample['capture_id'], sample['game'], sample['duel_token'])
        if self.identity and self.identity != identity: raise EvidenceError('进程或局次已变化，旧跟随已失效')
        if sample['turn'] != 1: raise EvidenceError('首版只跟随先攻第一回合')
        self.identity = identity
        # Validate a whole batch before mutating the reducer. Exact duplicates are
        # idempotent; conflicting duplicates, holes and old tails never advance.
        next_records = list(self.records)
        for record in sample['records']:
            seq = record['seq']
            if seq < len(next_records):
                if next_records[seq] != record: raise EvidenceError('重复消息内容冲突，不能继续匹配')
                continue
            if seq != len(next_records): raise EvidenceError('消息序号不连续，存在漏采或乱序')
            next_records.append(deepcopy(record))
        if len(next_records) != sample['processed']: raise EvidenceError('处理游标回退或消息缺失')
        if len(next_records) > 8192: raise EvidenceError('本局证据超过首版保留上限')
        trial = deepcopy(self.journal)
        for record in next_records[len(self.records):]: trial.apply(record)
        if trial.turn != 1: raise EvidenceError('缺少第一回合的连续消息')
        draws = [r for r in next_records if r['message'] == 90 and r.get('raw')]
        if len(draws) != 1:
            raise EvidenceError('不能确认唯一的初始起手证据')
        raw = bytes.fromhex(draws[0]['raw'])
        opening = [int.from_bytes(raw[i:i+4], 'little') & 0x7fffffff for i in range(2, len(raw), 4)]
        if Counter(opening) != Counter(self.hand): raise EvidenceError('实时消息与已冻结起手不属于同一局')
        if Counter(self.contract['hand']) - Counter(opening): raise EvidenceError('所选路线起手与本局不对应')
        for record in next_records[len(self.records):]:
            self.seen[record['seq']] = {'first_observed_ms': sample['sampled_ms'],
                                        'previous_sample_ms': self.last_consistent_ms}
        self.records, self.journal = next_records, trial
        self.snapshot = deepcopy(sample['state']); self.sampled_ms = sample['sampled_ms']
        self.prompt = sample.get('prompt')
        # Animations can update cards before their message is retired. A mismatch
        # is never treated as completion, even when the operation token matches.
        if signature(trial.state()) != signature(sample['state']):
            if not self.requires_sync and not self.paused:
                self.status, self.reason = 'executing', '等待动画与已处理消息的场面一致'
            self.mismatch_samples += 1
            if sample.get('prompt') == 11 and self.mismatch_samples >= 4 and not self.requires_sync:
                self.stop('稳定场面与消息推导持续不一致，可能漏采或状态变化，请重新核对')
            return False
        self.mismatch_samples = 0
        self.last_consistent_ms = sample['sampled_ms']
        return True

    def advance(self, confirm, now):
        if self.paused or self.requires_sync: return
        steps = self.contract['steps']; tokens = self.journal.tokens
        while len(self.completed) < len(steps):
            step = steps[len(self.completed)]
            if step['reason']:
                self.stop(step['reason']); return
            bindings = dict(self.bindings)
            expected = step['tokens']; actual = tokens[self.token_index:self.token_index+len(expected)]
            for a, b in zip(expected, actual):
                if not match_token(a, b, bindings):
                    self.stop('实际操作、卡牌实例、素材或对象与所选路线不符', 'blocked'); return
            if len(actual) < len(expected):
                selecting = self.prompt in (14, 15, 18, 19, 20, 22, 23, 24, 25, 26)
                self.status = 'executing' if actual or selecting else 'following'
                self.reason = '操作执行中，等待全部结果及连锁结束' if actual else '等待完成素材、对象或区域选择' if selecting else '等待执行下一步'
                return
            if not actual[-1]['settled']:
                self.status, self.reason = 'executing', '等待召唤成功或连锁结束'; return
            entry = {'key': step['key'], 'source': 'mdpro3-read-only', 'event_from': actual[0]['seq'],
                     'event_through': actual[-1]['seq'], 'confirmed_ms': now,
                     'sampled_ms': self.sampled_ms, 'delivery_ms': max(0, now-self.sampled_ms)}
            entry.update(self.seen.get(actual[-1]['seq'], {}))
            committed_ms = confirm(step, entry)
            if type(committed_ms) is int:
                entry.update(confirmed_ms=committed_ms, delivery_ms=max(0, committed_ms-self.sampled_ms))
            self.completed.append(entry); self.bindings = bindings; self.token_index += len(expected)
        self.status, self.reason = 'completed', '已核对所选路线的全部步骤'
        if self.token_index != len(tokens): self.stop('路线结束后出现其他操作，请核对当前局面', 'blocked')


class FollowService:
    def __init__(self, store, write, now):
        self.store, self.write, self.now = store, write, now
        self.lock = threading.RLock()
        self.jobs = {}; self.active = {}

    def retire_context(self, identifier):
        with self.lock:
            active = self.active.pop(identifier, None)
            job = self.jobs.get(active)
            if job:
                job['connected'] = False
                job['follower'].paused = True
                job['follower'].stop('本局工作区已结束，跟随已失效')
                self.persist(job)

    def validate(self, job):
        context = self.store.automatic_duel.context(job['context_id'])
        if self.active.get(context['id']) != job['id'] or context.get('selection_version', 0) != job['selection_version']:
            raise EvidenceError('所选方案已切换，旧跟随已失效')
        inputs = context['input']; recognition = self.store.ygopro_smart.jobs.get(inputs.get('recognition_id'))
        if not recognition or recognition.get('platform') != 'mdpro3' or recognition.get('round_id') != job['round_id']:
            raise EvidenceError('跟随局次已失效，请重新选择本局方案')
        if recognition.get('reading_error'): raise EvidenceError('智能识别读取暂时中断，请恢复后重新同步')
        if recognition.get('frame', {}).get('evidence', {}).get('duel_token') != job['duel_token']:
            raise EvidenceError('开局身份已变化')
        contract = job.get('follower') and job['follower'].contract
        if contract and contract['kind'] == 'temporary':
            ctx = self.store.modular.sessions.get(contract['planner_id'], {})
            route = ctx.get('forecast_route', {})
            if route.get('id') != contract['route']: raise EvidenceError('临时方案版本已变化')
            if ctx.get('forecast_meta', {}).get('rules_version') != self.store.modular.precompute.rules():
                raise EvidenceError('规则资源已变化，请重新选择路线')
        if job.get('source_stamp'):
            path = self.store.plan_path(context['selected_plan']['id'])
            if (path.stat().st_mtime_ns, path.stat().st_size) != job['source_stamp']:
                raise EvidenceError('正式方案来源已修改，请重新选择')
        return context

    def public(self, job):
        f = job['follower']; steps = f.contract['steps']; index = len(f.completed)
        return {'id': job['id'], 'context_id': job['context_id'], 'round_id': job['round_id'],
                'revision': f.contract['revision'], 'status': f.status, 'reason': f.reason,
                'connected': job.get('connected', False), 'sampled_ms': f.sampled_ms,
                'completed': deepcopy(f.completed), 'next_key': steps[index]['key'] if index < len(steps) else 'main/final',
                'steps': [{'key': s['key'], 'status': 'completed' if i < index else
                           ('executing' if f.status == 'executing' else 'needs_confirmation' if f.requires_sync else 'pending') if i == index else 'pending',
                           'reason': s['reason']} for i, s in enumerate(steps)],
                'live_state': deepcopy(f.snapshot), 'kind': f.contract['kind'],
                'temporary_confirmed': job.get('temporary_confirmed'), 'requires_sync': f.requires_sync}

    def persist(self, job):
        # Only private runtime data. Original opening, plan and journals stay intact.
        self.write(self.store.root/'live-follow'/(job['id']+'.json'), self.public(job))
        f = job['follower']; stamp = (len(f.records), len(f.completed))
        if job.get('evidence_stamp') != stamp:
            self.write(self.store.root/'live-follow'/(job['id']+'.evidence.json'),
                       {'identity': f.identity, 'contract': f.contract, 'records': f.records,
                        'completed': f.completed, 'sampled_ms': f.sampled_ms, 'snapshot': f.snapshot})
            job['evidence_stamp'] = stamp

    def start(self, body):
        with self.lock:
            context = self.store.automatic_duel.context(body.get('context_id'))
            identifier = uuid.UUID(body['request_id']).hex if body.get('request_id') else uuid.uuid4().hex
            if identifier in self.jobs:
                previous = self.jobs[identifier]
                if previous['context_id'] != context['id']: raise EvidenceError('跟随请求不属于当前工作区')
                self.validate(previous)
                return self.poll({'context_id': context['id'], 'id': identifier})
            inputs = context['input']; recognition = self.store.ygopro_smart.jobs.get(inputs.get('recognition_id'), {})
            if recognition.get('platform') != 'mdpro3': raise EvidenceError('首版仅支持 MDPRO3 智能识别后的先攻教程')
            job = {'id': identifier, 'context_id': context['id'], 'round_id': inputs['round_id'],
                   'capture_id': inputs['capture_id'], 'selection_version': context.get('selection_version', 0),
                   'duel_token': recognition['frame']['evidence']['duel_token'], 'connected': False}
            self.active[context['id']] = job['id']
            if body.get('planner_id'):
                sid = body['planner_id']
                selected = context.get('selected_temporary') or {}
                if selected != {'id': sid, 'route': body.get('route')}:
                    raise EvidenceError('临时方案不属于当前所选路线')
                with self.store.modular.planning_lock:
                    ctx = self.store.modular.sessions[sid]
                    contract = temporary_contract(self.store.modular, sid, ctx)
            else:
                plan = context.get('selected_plan')
                if not plan or body.get('revision') != plan['automatic_revision']: raise EvidenceError('正式方案版本已变化')
                path = self.store.plan_path(plan['id'])
                job['source_stamp'] = (path.stat().st_mtime_ns, path.stat().st_size)
                fresh = self.store.automatic_duel.match({'context_id': context['id']})
                current = next((p for p in fresh['matches'] if p['id'] == plan['id']), None)
                if not current or current['automatic_revision'] != plan['automatic_revision']:
                    raise EvidenceError('正式方案在进入教程前已经变化，请重新选择')
                contract = formal_contract(plan)
            job['follower'] = Follower(contract, list(inputs['hand']))
            self.validate(job); self.jobs[job['id']] = job
            for identifier in list(self.jobs)[:-16]:
                if identifier not in self.active.values(): self.jobs.pop(identifier, None)
            return self.poll({'context_id': context['id'], 'id': job['id']})

    def confirm(self, job, step, evidence):
        self.validate(job)
        contract = job['follower'].contract
        if contract['kind'] == 'temporary':
            from duel_planner import confirm
            context = self.store.automatic_duel.context(job['context_id'])
            body = self.store.automatic_duel.request(context, {'id': contract['planner_id'], 'route': contract['route'],
                       'index': step['index'], 'through': step['through']}, 'plan-confirm')
            with self.store.modular.planning_lock:
                value = confirm(self.store.modular, body, source=evidence['source'], evidence=evidence,
                                guard=lambda: self.validate(job))
            job['temporary_confirmed'] = value['confirmed']
        self.validate(job)
        return self.now()

    def poll(self, body):
        with self.lock:
            job = self.jobs.get(body.get('id'))
            if not job or job['context_id'] != body.get('context_id'): raise EvidenceError('跟随会话不存在')
            f = job['follower']; action = body.get('action', 'poll')
            if action not in ('poll', 'pause', 'resume', 'resync', 'manual', 'stop'): raise EvidenceError('跟随操作无效')
            if action == 'stop':
                f.paused = True; f.stop('跟随已停止', 'paused')
                if self.active.get(job['context_id']) == job['id']: self.active.pop(job['context_id'], None)
                self.persist(job); return self.public(job)
            try:
                self.validate(job)
                if time.monotonic()-job.get('last_poll', time.monotonic()) > 2:
                    f.stop('跟随采样曾中断，恢复前需要重新同步')
                job['last_poll'] = time.monotonic()
                if action == 'pause': f.paused = True; f.status = 'paused'; f.reason = '已暂停，仍保留已确认历史'
                sample = self.store.ygopro_capture.follow_sample(job['capture_id'],
                            0 if action in ('resume', 'resync') else len(f.records))
                job['connected'] = True
                if sample['duel_token'] != job['duel_token']: raise EvidenceError('本局身份发生变化')
                f.snapshot = deepcopy(sample['state']); f.sampled_ms = sample['sampled_ms']
                consistent = f.ingest(sample); job['connected'] = True
                if action in ('resume', 'resync'):
                    # Re-read the retained prefix and compare every old record,
                    # as well as the freshly measured scene. Never resume by UI index.
                    if not consistent: raise EvidenceError('当前场面尚未稳定，请稍后重新同步')
                    f.paused = False; f.requires_sync = False
                if action == 'manual':
                    if not consistent or not f.journal.settled: raise EvidenceError('当前操作仍在处理中，不能人工确认')
                    index = len(f.completed)
                    if index >= len(f.contract['steps']): raise EvidenceError('没有待确认的步骤')
                    step = f.contract['steps'][index]
                    if body.get('key') != step['key']: raise EvidenceError('只能确认实际下一步，不能跳步')
                    # Manual acknowledgement is explicit, but still cannot turn a
                    # mismatching board/random result into the expected projection.
                    expected = step.get('expected') or {}
                    context = self.validate(job)
                    normalized = manual_expected(f.contract, expected, context['input'])
                    if not normalized['cards'] or signature(normalized) != signature(sample['state']):
                        raise EvidenceError('实际场面与步骤结果不一致；请报告实际结果或重新选择方案')
                    bindings = dict(f.bindings)
                    for expected_card in step.get('instances', {}).get('cards', []):
                        from duel_follow_events import slot
                        matches = [c for c in f.journal.cards if c['code'] == expected_card['code'] and slot(c) == slot(expected_card)]
                        if len(matches) != 1: raise EvidenceError('人工确认后卡牌实例无法唯一重建，请重新选择方案')
                        bindings[expected_card['uid']] = matches[0]['uid']
                    entry = {'key': step['key'], 'source': 'manual', 'confirmed_ms': self.now(),
                             'event_through': len(f.records)-1, 'sampled_ms': f.sampled_ms}
                    entry['confirmed_ms'] = self.confirm(job, step, entry); f.completed.append(entry)
                    f.bindings = bindings
                    f.token_index = len(f.journal.tokens); f.paused = True
                    f.stop('已记录人工确认；恢复前请重新同步', 'paused')
                elif consistent:
                    f.advance(lambda step, evidence: self.confirm(job, step, evidence), self.now())
                if f.paused: f.status = 'paused'
            except (ValueError, OSError, KeyError, IndexError) as error:
                # A route mismatch is different from a disconnected reader.
                if 'sample' not in locals(): job['connected'] = False
                elif job.get('rejected_cursor') != sample['processed']:
                    self.write(self.store.root/'live-follow'/(job['id']+'.rejected-sample.json'),
                               {'reason': str(error), 'sample': sample})
                    job['rejected_cursor'] = sample['processed']
                f.stop(str(error))
            self.persist(job)
            return self.public(job)
