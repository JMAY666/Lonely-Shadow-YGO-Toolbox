"""Reproduce a saved tutorial prefix using the current hand before planning."""
from copy import deepcopy

from card_semantics import effect_clause
from modular_decisions import bind_variants, model, public_state, response_bindings, semantic_response
from module_conditions import advance_facts


def anchor_source(modular, anchor):
    if not isinstance(anchor, dict): raise ValueError('请选择普通方案中的一个步骤')
    plan = modular.read(modular.store.plan_path(anchor.get('plan', '')))
    if plan.get('edit_revision', 0) != anchor.get('revision'):
        raise ValueError('普通方案已修改，请刷新后再从当前步骤生成后续')
    route_id = anchor.get('route', 'main')
    if route_id == 'main': report, source_id = plan, plan['id']
    else:
        branch = next((b for b in plan.get('branches', []) if b['id'] == route_id and b.get('valid', True)), None)
        if not branch or not branch.get('report'): raise ValueError('所选分支已失效，请刷新方案')
        report, source_id = branch['report'], branch['id']
    entry = modular.library.entries.get(plan['id'], {})
    route = next((r for r in entry.get('routes', []) if r['id'] == source_id), None)
    review = report.get('review') or {}; nodes = review.get('nodes', [])
    node = next((n for n in nodes if n['id'] == anchor.get('node') and n.get('kind') == 'step'), None)
    if not node or not route: raise ValueError('当前步骤缺少可重放的模块记录，请在新版中重新记录来源')
    snapshots = sorted(route['snapshots'], key=lambda s: s['position'])
    def boundary(n):
        seq = n.get('state_ref')
        if not isinstance(seq, (int, float)): return None
        return next((s for s in snapshots if s.get('seq', -1) >= seq and s.get('player') == 0 and s.get('raw')), None)
    target = boundary(node)
    if not target: raise ValueError('该步骤之后没有可确认的我方决策边界，原教程保留')
    edges = sorted((e for e in modular.library.edges([plan['id']])
                    if e['source']['route'] == source_id and e['position'] < target['position']), key=lambda e: e['position'])
    if not edges or any(u.get('position', 0) < target['position'] for u in route.get('unknown', [])):
        raise ValueError('前面步骤的决策记录不完整，不能可靠生成后续；原教程保留')
    layout, start = [], 0
    for step in nodes:
        if step.get('kind') != 'step': continue
        end_boundary = boundary(step)
        if not end_boundary or end_boundary['position'] > target['position']: break
        end = sum(e['position'] < end_boundary['position'] for e in edges) - 1
        if end >= start:
            edit = report.get('annotations', {}).get('nodes', {}).get(step['id'], {})
            layout.append({'start': start, 'end': end, 'number': step.get('number'),
                           'name': edit.get('name', ''), 'notes': edit.get('notes', '')})
            start = end + 1
        if step['id'] == node['id']: break
    return {'edges': edges, 'target': target, 'initial': snapshots[0]['state'], 'layout': layout,
            'version': entry['version'], 'anchor': {**anchor, 'name': plan['name'], 'number': node.get('number')}}


def replay_anchor(modular, sid, ctx, source):
    from duel_planner import projected, commit_projection
    from modular import terminal_key, board_pattern, observed_delta, satisfies_delta, hand_count, guide_block_reason
    base = modular.state(sid); current = base; path, steps = [], []
    memory = {'chains': {}, 'facts': []}
    for edge in source['edges']:
        prompt = model(current['raw'], current['state'], current.get('effects'))
        responses = bind_variants(edge['decision'], prompt, precise=True, limit=1)
        if not responses and not ctx['precise']:
            responses = bind_variants(edge['decision'], prompt, precise=False, limit=1)
        if not responses:
            raise ValueError('当前起手无法按普通方案重放到所选步骤：' +
                             guide_block_reason(edge, current, modular.store.catalog.cards) + '；原教程保留')
        response = responses[0]; before = current; bindings = response_bindings(prompt, response)
        path.append(current['raw'] + ':' + response)
        following = modular.bridge(sid, base, path)
        memory = advance_facts(memory, current['state'], following['state'], following['batches'],
                               next((b['effect'] for b in bindings if b.get('effect')), None))
        for _ in range(20):
            if following.get('private_cards') or following.get('uncertain'):
                raise ValueError('前面步骤含尚未填报的随机结果，不能把原方案的随机卡牌当成本局事实；请从起手生成临时方案并填写实际结果')
            if following['player'] != 1 or following.get('ended'): break
            opponent = model(following['raw'], following['state'], following.get('effects'))
            decline = next((c for c in opponent['choices'] if c['semantic']['kind'] in ('pass', 'no')), None)
            if not decline: raise ValueError('此前对手响应需要确认，当前不能可靠重放到此步骤')
            path.append(following['raw'] + ':' + decline['response'])
            previous = following; following = modular.bridge(sid, base, path)
            memory = advance_facts(memory, previous['state'], following['state'], following['batches'])
        else: raise ValueError('此前响应未能到达我方决策边界，原教程保留')
        step = {'edge': edge['id'], 'source': edge['source'], 'sources': [edge['source']],
                'decision': edge['decision'], 'bound_decision': semantic_response(prompt, response),
                'bindings': bindings, 'before': public_state(before['state']), 'state': public_state(following['state']),
                'automatic': edge.get('automatic', False), 'path_end': len(path), 'if_memory': deepcopy(memory)}
        selected = next((c for c in edge['decision'].get('selection', []) if c.get('effect')), None)
        if selected:
            step['effect_label'] = effect_clause({'cards': [selected.get('card', {})], 'engine_effect': selected['effect'],
                'effect': {'description_id': selected['effect'].get('description')}},
                {str(k): v for k, v in modular.store.catalog.cards.items()})
        steps.append(step); current = following
    target = source['target']['state']; actual = current['state']
    if (board_pattern(terminal_key(actual), ctx['precise']) != board_pattern(terminal_key(target), ctx['precise'])
            or not satisfies_delta({'delta': observed_delta(source['initial'], target)}, base['state'], actual)
            or hand_count(actual) < hand_count(base['state']) + hand_count(target) - hand_count(source['initial'])):
        raise ValueError('重放结果与所选步骤的已记录结果不一致，原教程保留；请核对实际局面')
    # Commit only after the whole prefix succeeds. Browsing a Step alone never
    # submits real inputs, nor does a failed replay change the current tutorial.
    modular.library.sync()
    if modular.library.entries.get(source['anchor']['plan'], {}).get('version') != source['version']:
        raise ValueError('来源方案在重放期间发生变化，请重新生成')
    commit_projection(ctx, projected(base, current, path, memory))
    ctx['forecast_steps'] = steps
    ctx['forecast_meta'].update(anchor=source['anchor'], prefix_layout=source['layout'])
