"""A user-confirmed duel forecast, isolated from actual expansion journals."""
from collections import Counter
from copy import deepcopy
import subprocess
import time
import uuid

from duel import validate_hand
from modular_decisions import model, public_state, bind_variants
from module_conditions import advance_facts
from planning_preferences import PREFERENCES, DEFAULT_PREFERENCE


def context(modular, body, *, allow_stale=False):
    sid = body.get('id'); ctx = modular.sessions.get(sid, {})
    if ctx.get('knowledge_verification'): raise ValueError('知识包验证实例不能作为对局教程采用或推进')
    if not ctx.get('forecast_meta') or sid not in modular.store.planning:
        raise ValueError('本局临时方案已结束，请重新生成')
    meta=ctx['forecast_meta']
    if meta.get('consumer','duel')!=body.get('consumer','duel') or meta.get('automatic_context')!=body.get('automatic_context'):
        raise ValueError('临时方案属于其他流程，不能跨工作区操作')
    if not allow_stale and meta.get('rules_version') and meta['rules_version'] != modular.precompute.rules():
        raise ValueError('规则资源已变化，原教程进度保留；当前引擎需重新建立，不能采用旧资源的候选或确认后续')
    ctx['forecast_touched'] = time.monotonic()
    return sid, ctx


def close(modular, sid):
    store = modular.store
    if sid not in store.planning: return
    store.stop(sid); proc = store.processes[sid]
    try: proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate(); proc.wait(timeout=5)
    store.refresh()
    with modular.lock: modular.sessions.pop(sid, None)
    modular.planning_cache.discard(sid)
    store.planning.discard(sid)


def public_steps(modular, steps):
    return modular.public_result({'candidates': [{'steps': steps}]})['candidates'][0]['steps']


def response(modular, sid, ctx, result=None):
    return {'id': sid, 'temporary': True, 'inputs': ctx['forecast_meta']['inputs'],
            'catalog': ctx['forecast_meta']['catalog'], 'result': modular.public_result(result) if result else None,
            'prefix': public_steps(modular, ctx.get('forecast_steps', [])),
            'anchor': ctx['forecast_meta'].get('anchor'), 'prefix_layout': ctx['forecast_meta'].get('prefix_layout', []),
            'initial': deepcopy(ctx['forecast_meta']['initial']),
            'confirmed': len(ctx.get('forecast_steps', [])), 'route': (ctx.get('forecast_route') or {}).get('id')}


def generate(modular, body, on_started=None, *, verification=None, search_options=None):
    store = modular.store; created = not body.get('id')
    refresh = body.get('refresh', False)
    if type(refresh) is not bool: raise ValueError('重新生成开关无效')
    if created:
        with store.lock:
            saved = store.get_deck(body.get('deck_id', ''))
            if saved['revision'] != body.get('revision'): raise ValueError('卡组已修改，请返回卡组选择重新确认')
            validate_hand(saved['deck'], body.get('hand_count'), body.get('hand')); store.validate(saved['deck'], training=True)
            selected = body.get('sources', []); modular.library.sync()
            if not verification and getattr(store, 'knowledge', None) and any(modular.library.entries.get(s, {}).get('knowledge_package') for s in selected):
                store.knowledge.runtime.environment(force=True)
                modular.library.sync()
            modular.library.validate_deck_sources(saved.get('tag_selection', {}), selected, verification=verification)
            from duel_continuation import anchor_source
            anchor = anchor_source(modular, body['anchor']) if body.get('anchor') else None
            session = store.start(saved['id'], design={
                'name': '决斗临时方案推演', 'notes': '后台计算用途，不是实际展开或正式保存方案',
                'revision': saved['revision'], 'deck': deepcopy(saved['deck']), 'deck_name': saved['name'],
                'conditions': {'hand_count': len(body['hand']), 'slots': list(body['hand']), 'banned': []},
                'opponent_ai': False, 'turn_order': 'first'}, planning=True)
        sid = session['id']; ctx = modular.context(sid)
    else: sid, ctx = context(modular, body)
    if on_started: on_started(sid, ctx)
    try:
        if created:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if store.closing or ctx.get('forecast_cancelled') or (verification and verification['cancelled']()): raise ValueError('预计算已取消')
                try: state = modular.state(sid)
                except ValueError: state = None
                if state and state['running'] and not state['answered'] and state.get('player') == 0 and state.get('raw'): break
                if store.processes[sid].poll() is not None: raise ValueError('后台规则引擎启动失败，请重试')
                time.sleep(.05)
            else: raise ValueError('后台规则引擎尚未就绪，请重试')
            meta = modular.read(store.session_path(sid) / 'session.json')
            ctx['forecast_meta'] = {'catalog': deepcopy(meta['catalog']), 'initial': public_state(state['state']),
                'tag_selection': deepcopy(saved.get('tag_selection', {})),
                'rules_version': modular.precompute.rules(),
                'consumer':body.get('consumer','duel'),'automatic_context':body.get('automatic_context'),
                'inputs': {'deck': saved['revision'], 'engine': meta['engine_sha256'], 'scripts': meta['scripts_sha256']}}
            ctx['forecast_steps'] = []
        modular.configure({'id': sid, 'sources': body.get('sources', ctx['selected']),
                           'preference': body.get('preference', ctx['preference']),
                           'precise': body.get('precise', ctx['precise']), 'goal': body.get('goal', ctx['goal'])})
        if created and anchor:
            from duel_continuation import replay_anchor
            replay_anchor(modular, sid, ctx, anchor)
        result = modular.search(sid, refresh=refresh, **({'all_preferences': True} if body.get('all_preferences') else {}), **(search_options or {}))
        if body.get('all_preferences'):
            bank = {}
            for preference in PREFERENCES:
                # The search and scores are preference-independent until here;
                # retain the complete discovered pool before each top-N cut.
                ranked = {**result, 'candidates': list(result['candidates'])}
                modular.rank(ranked['candidates'], preference)
                ranked['candidates'] = ranked['candidates'][:result['limits']['candidates']]
                ranked['preference'] = preference
                bank[preference] = ranked
            ctx['forecast_bank'] = bank
            import json
            if len(json.dumps(bank, ensure_ascii=False).encode('utf-8')) > 16 * 1024 * 1024:
                ctx.pop('forecast_bank', None)
                raise ValueError('本轮候选超过后台缓存容量，请减少来源后重试；未缩减搜索范围或冒充无路线')
            preference = body.get('preference', DEFAULT_PREFERENCE)
            result = ctx['result'] = bank[DEFAULT_PREFERENCE if preference == 'safest' else preference]
        ctx['forecast_meta']['inputs']['sources'] = result['token'][2]
        ctx.pop('forecast_partial', None)
        ctx['forecast_touched'] = time.monotonic()
        return response(modular, sid, ctx, result)
    except Exception:
        if created: close(modular, sid)
        raise


def adopt(modular, body):
    sid, ctx = context(modular, body); result = ctx.get('result') or {}
    if ctx.get('forecast_job') and body.get('job') != ctx['forecast_job']:
        raise ValueError('请使用当前预计算任务及状态版本采用候选')
    if body.get('preference') and ctx.get('forecast_bank'):
        result = ctx['forecast_bank'].get(DEFAULT_PREFERENCE if body['preference'] == 'safest' else body['preference']) or {}
        ctx['result'] = result
    candidate = next((c for c in result.get('candidates', []) if c['id'] == body.get('candidate')), None)
    if not candidate or not modular.valid_token(sid, candidate['token']): raise ValueError('候选来源或本局进度已变化，请重新生成')
    ctx['forecast_route'] = {'id': uuid.uuid4().hex, 'candidate': deepcopy(candidate),
        'base': modular.state(sid), 'prefix': deepcopy(ctx.get('forecast_steps', [])), 'confirmed': 0}
    if body.get('job'): modular.precompute.adopted(body['job'])
    return response(modular, sid, ctx, {'candidates': [candidate], 'status': result['status']})


def route_context(modular, body):
    sid, ctx = context(modular, body); route = ctx.get('forecast_route')
    if not route or route['id'] != body.get('route'): raise ValueError('临时路线已变化，请使用当前步骤')
    index = body.get('index')
    if type(index) is not int or not 0 <= index < len(route['candidate']['steps']): raise ValueError('步骤不存在')
    if index > route['confirmed']: raise ValueError('请先确认前面的步骤，不能跳过未完成步骤')
    return sid, ctx, route, index


def projected(base, following, path, memory=None, known=False):
    value = deepcopy(base)
    for key in ('running', 'answered'): value.pop(key, None)
    value.update(state=deepcopy(following['state']), raw=following['raw'], effects=following.get('effects', {}),
                 player=following['player'], revision=base['revision'] + 1,
                 _prefix=base.get('_prefix', []) + path,
                 _unknown_draws=[] if known else list(following.get('private_cards', [])))
    if memory is not None: value['_if_memory'] = deepcopy(memory)
    return value


def commit_projection(ctx, value):
    revision = max(ctx.get('forecast_revision', 0), value['revision']) + 1
    value['revision'] = revision
    ctx.update(forecast_revision=revision, forecast_state=value)
    ctx.pop('forecast_bank', None)
    ctx.pop('forecast_job', None)


def confirm(modular, body):
    sid, ctx, route, index = route_context(modular, body)
    candidate = route['candidate']; through = body.get('through', index)
    if type(through) is not int or not index <= through < len(candidate['steps']): raise ValueError('步骤确认范围无效')
    if through < route['confirmed']: return response(modular, sid, ctx)
    if index != route['confirmed']: raise ValueError('步骤进度已变化，请刷新本局状态')
    step = candidate['steps'][through]
    if candidate.get('observation_required') and through == len(candidate['steps']) - 1:
        raise ValueError('此步骤包含随机结果，请先填写实际获得或堆墓的卡牌')
    path = candidate['path'][:step['path_end']]; following = modular.bridge(sid, route['base'], path)
    commit_projection(ctx, projected(route['base'], following, path, step.get('if_memory')))
    ctx['forecast_steps'] = route['prefix'] + deepcopy(candidate['steps'][:through + 1]); route['confirmed'] = through + 1
    modular.audit(ctx, 'user_confirmed_step', step=index, through=through, route=route['id'])
    return response(modular, sid, ctx)


def observe(modular, body):
    sid, ctx, route, index = route_context(modular, body)
    kind = body.get('kind'); codes = body.get('cards')
    if kind not in ('draw', 'mill', 'interruption'): raise ValueError('请选择实际情况类型')
    if not isinstance(codes, list) or not 1 <= len(codes) <= 60 or any(type(c) is not int or c not in modular.store.catalog.cards for c in codes):
        raise ValueError('请填写实际卡牌，可重复；卡牌必须存在于本地卡库')
    if kind == 'interruption' and any(modular.store.catalog.cards[c].get('extra') for c in codes):
        raise ValueError('请填写从手牌发动的阻抗卡及其实际手牌费用')
    through = body.get('through', index)
    if type(through) is not int or not index <= through < len(route['candidate']['steps']): raise ValueError('步骤填报范围无效')
    if kind != 'interruption': index = through
    else:
        while index < through and route['candidate']['steps'][index].get('automatic'): index += 1
    candidate = route['candidate']; steps = candidate['steps']; step = steps[index]
    start = steps[index-1]['path_end'] if index else 0; prefix = candidate['path'][:start]
    before = modular.bridge(sid, route['base'], prefix)
    base = projected(route['base'], before, prefix, steps[index-1].get('if_memory') if index else route['base'].get('_if_memory'))
    base.setdefault('_observations', []).append({'index': len(base['_prefix']), 'kind': 1 if kind == 'interruption' else 0, 'codes': list(codes)})
    chunk = candidate['path'][start:step['path_end']]
    if kind in ('draw', 'mill'):
        following = modular.bridge(sid, base, chunk); zone = 2 if kind == 'draw' else 16
        deck_ids = {c['instance_id'] for c in before['state']['cards'] if c.get('controller') == 0 and c.get('location') == 1}
        actual = [c['code'] for c in following['state']['cards'] if c.get('instance_id') in deck_ids and c.get('location') == zone]
        if Counter(actual) != Counter(codes): raise ValueError('填报数量或发生步骤与引擎不符，原路线保留；请在实际抽牌／随机堆墓的步骤填写全部结果')
        memory = advance_facts(base.get('_if_memory'), before['state'], following['state'], following['batches'])
    else:
        chunk = [chunk[0]]; following = modular.bridge(sid, base, chunk)
        memory = advance_facts(base.get('_if_memory'), before['state'], following['state'], following['batches'],
                               next((b.get('effect') for b in step.get('bindings', []) if b.get('effect')), None))
        old_facts = len((base.get('_if_memory') or {}).get('facts', []))
        remaining = iter(steps[index+1:])
        for _ in range(24):
            facts = memory.get('facts', [])[old_facts:]
            if facts and following['player'] == 0 and bytes.fromhex(following['raw'])[0] in (10, 11) and not following['state'].get('chain_depth'): break
            prompt = model(following['raw'], following['state'], following.get('effects'))
            if following['player'] == 1: answer = 'ai'
            else:
                decline = next((c for c in prompt['choices'] if c['semantic']['kind'] in ('pass', 'no')), None)
                if decline: answer = decline['response']
                else:
                    planned = next(remaining, None)
                    options = bind_variants(planned['decision'], prompt, precise=ctx['precise']) if planned else []
                    if not options: raise ValueError('该阻抗还需要具体选择，无法从当前填报完整复核；原路线保留，请补充卡片及费用或选择正确步骤')
                    answer = options[0]
            chunk.append(following['raw'] + ':' + answer)
            previous = following; following = modular.bridge(sid, base, chunk)
            memory = advance_facts(memory, previous['state'], following['state'], following['batches'])
        else: raise ValueError('此阻抗未在当前步骤完成复核，原路线保留；请核对步骤与卡牌')
        affected = {s.get('card', {}).get('code') for s in step['decision'].get('selection', []) if s.get('card')}
        if not any(f.get('code') in affected for f in memory.get('facts', [])[old_facts:]):
            raise ValueError('未复核到针对当前操作的阻抗，原路线保留；请核对发生步骤与目标')
        existing = {c['instance_id'] for c in before['state']['cards']}
        paid = Counter(c['code'] for c in following['state']['cards'] if c.get('controller') == 1
                       and c.get('instance_id') not in existing and c.get('location') != 2)
        if paid != Counter(codes):
            raise ValueError('填报的阻抗卡或手牌费用与实际处理不符，原路线保留；请只填写确实发动或支付的卡牌')
    updated = projected(base, following, chunk, memory, known=True); observed = deepcopy(step)
    observed.update(state=public_state(following['state']), operation_label={'draw':'实际抽牌','mill':'实际随机堆墓','interruption':'实际受到阻抗'}[kind],
                    observation={'kind': kind, 'cards': list(codes), 'basis': 'user_reported'}, if_memory=memory)
    commit_projection(ctx, updated)
    ctx['forecast_steps'] = route['prefix'] + deepcopy(steps[:index]) + [observed]
    for code in codes:
        ctx['forecast_meta']['catalog'].setdefault(str(code), deepcopy(modular.store.catalog.cards[code]))
    ctx['forecast_route'] = None; ctx['result'] = None
    modular.audit(ctx, 'user_reported_outcome', kind_reported=kind, cards=codes, step=index)
    try: result = modular.search(sid)
    except ValueError as error:
        result = {'status': 'incomplete', 'candidates': [], 'reason': str(error)}
    return response(modular, sid, ctx, result)


def dispatch(modular, intent, body):
    if intent == 'plan': return generate(modular, body)
    if intent == 'plan-adopt': return adopt(modular, body)
    if intent == 'plan-confirm': return confirm(modular, body)
    if intent == 'plan-observe': return observe(modular, body)
    sid, ctx = context(modular, body, allow_stale=True); inputs = ctx['forecast_meta']['inputs']; close(modular, sid)
    return {'closed': True, 'inputs': inputs}
