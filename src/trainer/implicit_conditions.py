"""Step-local resource constraints derived from frozen decisions and movements.

This is a necessary-condition check, not a replacement for the rules engine.
Physical instances are bound once and follow their recorded zone changes. Random
identities are never borrowed from a recording to fill a live hand or graveyard.
"""
from collections import Counter
from copy import deepcopy

from modular_decisions import digest
from card_semantics import zone_name

VERSION = 1
RESOURCE_ZONES = (1, 16, 32, 64, 128)


def location(value):
    return 128 if isinstance(value, int) and value & 128 else value


def extract(report, generic_instances=()):
    review = report.get('review') or {}
    graph = review.get('module_graph') or {}
    frozen_source = report.get('modular_source') or {}
    if not graph.get('connections') and frozen_source.get('edges'):
        # Some older saved plans already have frozen modular decisions but no
        # shared review graph. Reuse those records, never a mutable live journal.
        graph = {'modules': frozen_source.get('snapshots', []), 'connections': frozen_source['edges']}
    modules = {m['id']: m for m in graph.get('modules', [])}
    nodes = review.get('nodes', [])
    events = sorted(report.get('events', []), key=lambda e: (e.get('native_seq', 0), e.get('byte_offset', 0)))
    initial = next((n for n in nodes if n.get('kind') == 'initial'), {})
    start = initial.get('state_ref') or 0
    pending, timeline, rows = [], [], []
    if not initial.get('state') or not review.get('complete'):
        pending.append('起点或步骤快照不完整，条件待核对')
    if not graph.get('connections'):
        pending.append('缺少冻结的操作选择记录，不能把缺少条件字段视为没有隐性条件')
    elif not any(modules.get(e.get('from'), {}).get('player') == 0 and e.get('decision') is not None for e in graph['connections']):
        pending.append('缺少可确认的我方选择依据，条件待核对')

    def step(seq):
        return next((n for n in nodes if n.get('kind') == 'step' and
                     n.get('range', [0, 0])[0] <= seq <= n.get('range', [0, 0])[1]), {})

    def card_fields(card):
        code = card.get('code')
        key = str(card.get('instance_id'))
        return {'instance': key, 'code': None if key in generic_instances else code,
                'name': '任意手牌' if key in generic_instances else report.get('catalog', {}).get(str(code), {}).get('name', card.get('name') or str(code))}

    selections = []
    for edge in graph.get('connections', []):
        module = modules.get(edge.get('from'), {})
        if module.get('player') != 0: continue
        if not edge.get('decision'):
            pending.append('部分我方操作缺少可核对的选择信息'); continue
        seq = min(edge.get('response_refs') or [module.get('seq', 0)+1])
        frozen = next((e for e in report.get('modular_source', {}).get('edges', []) if e.get('from') == edge.get('from')), {})
        bindings = edge.get('bindings', frozen.get('bindings', []))
        used = set()
        for selected in edge['decision'].get('selection', []):
            card = selected.get('card')
            if not card or card.get('controller') != 0 or selected.get('kind') in ('no', 'pass', 'finish_selection'): continue
            recorded = [b['card'] for b in bindings if b.get('card') and b['card'].get('instance_id') not in used and
                        all(b['card'].get(k) == card[k] for k in ('code', 'controller', 'location', 'sequence') if k in card)]
            actual = recorded[:1] or [c for c in (module.get('state') or {}).get('cards', [])
                      if c.get('instance_id') not in used and all(c.get(k) == card[k] for k in ('code', 'controller', 'location', 'sequence') if k in card)]
            # Public deck snapshots deliberately omit instance IDs and shuffle
            # order. Bind a selected identity to its observed outgoing movement
            # within this decision's resolution, never to a guessed deck index.
            if card['location'] == 1 and (len(actual) != 1 or actual[0].get('instance_id') is None):
                end = modules.get(edge.get('to'), {}).get('seq', seq)
                moved = [c for e in events if seq < e.get('native_seq', 0) <= end and e.get('message') == 50
                         and (e.get('origin') or {}).get('controller') == 0 and (e.get('origin') or {}).get('location') == 1
                         and (e.get('destination') or {}).get('location') != 1
                         for c in e.get('cards', []) if c.get('code') == card['code'] and c.get('instance_id') not in used]
                actual = moved[:1]
            if len(actual) != 1 or actual[0].get('instance_id') is None:
                pending.append('选择的卡牌实例无法唯一对应，份数待核对'); continue
            used.add(actual[0]['instance_id'])
            item = {'kind': 'need', 'seq': seq, 'order': -1, **card_fields(actual[0]),
                    'location': card['location'], 'node': step(seq).get('id'),
                    'step': step(seq).get('number'), 'evidence': [module['id'], *map(str, edge.get('response_refs', []))]}
            if not any(s['seq'] == seq and s['instance'] == item['instance'] for s in selections):
                selections.append(item)
    timeline.extend(selections)
    for event in events:
        seq = event.get('native_seq', 0)
        if seq <= start: continue
        msg = event.get('message')
        if msg == 90 and event.get('actor') == 'self':
            timeline.append({'kind': 'random', 'seq': seq, 'order': event.get('byte_offset', 0),
                             'random_instances': [str(c['instance_id']) for c in event.get('cards', []) if c.get('instance_id') is not None],
                             'node': step(seq).get('id'), 'step': step(seq).get('number'),
                             'evidence': [event['id']], 'reason': '随机抽牌，必须确认本局实际结果'})
        if msg != 50 or event.get('deck_operation'): continue
        origin, destination = event.get('origin') or {}, event.get('destination') or {}
        for card in event.get('cards', []):
            if origin.get('controller') != 0 and destination.get('controller') != 0: continue
            if card.get('instance_id') is None:
                pending.append('区域变化缺少卡牌实例，不能可靠跟踪资源流转'); continue
            item = {'kind': 'move', 'seq': seq, 'order': event.get('byte_offset', 0), **card_fields(card),
                    'location': location(origin.get('location')), 'to': location(destination.get('location')),
                    'position': destination.get('position', 0), 'reason': event.get('reason', 0),
                    'controller': origin.get('controller'), 'to_controller': destination.get('controller'),
                    'node': step(seq).get('id'), 'step': step(seq).get('number'), 'evidence': [event['id']]}
            timeline.append(item)
    timeline.sort(key=lambda item: (item['seq'], item['order']))
    produced, selected_at, seen_conditions, tainted = {}, {}, set(), set()
    for item in timeline:
        key = item.get('instance')
        if item['kind'] == 'random':
            tainted.update(item['random_instances'])
        elif item['kind'] == 'need':
            selected_at[key] = item['location']
            if item['location'] not in RESOURCE_ZONES or key in tainted: continue
            movement = next((e for e in timeline if e['kind'] == 'move' and e['instance'] == key and
                             e['seq'] >= item['seq']), None)
            destination = movement.get('to') if movement and movement['location'] == item['location'] else None
            purpose = ('检索' if item['location'] == 1 else '回收') if destination == 2 else '定向送墓' if destination == 16 else (
                '特殊召唤' if movement.get('reason', 0) & 0x800 else '移至怪兽区') if destination == 4 else (
                '盖放' if movement.get('position', 0) & 10 else '移至魔法与陷阱区') if destination == 8 else '取得或使用指定资源'
            ident = (key, item['location'], movement['evidence'][0] if movement else item['seq'])
            if ident in seen_conditions: continue
            seen_conditions.add(ident)
            provider = produced.get(key)
            row = {**deepcopy(item), 'id': digest(ident), 'count': 1, 'source_zone': item['location'],
                   'instances': [key],
                   'purpose': purpose, 'status': '已记录选择', 'nodes': [item['node']] if item['node'] else [],
                   'supplied_by': deepcopy(provider), 'uses': [f"第{item['step'] or '?'}步从{zone_name(item['location'])}{purpose}"]}
            if movement: row['evidence'] += movement['evidence']
            if provider:
                row['uses'].append(f"资源来自第{provider.get('step') or '?'}步的区域变化，不要求开局已有")
            row['uses'].append('操作选择及区域变化依据：' + '、'.join(row['evidence']))
            rows.append(row)
        elif item['kind'] == 'move':
            # An unselected card from an unordered deck is not an identity
            # predicate. This includes random mills and old, ambiguous records.
            if item['location'] == 1 and selected_at.get(key) != 1 and item['controller'] == 0:
                item.update(kind='unknown_result', reason='随机或未记录定向选择的卡组处理，需确认实际结果')
                tainted.add(key)
                pending.append(f"第{item.get('step') or '?'}步卡组处理缺少确定的选择依据，不能提取为指定卡牌条件")
            produced[key] = {'node': item['node'], 'step': item['step'], 'evidence': item['evidence']}
            selected_at.pop(key, None)
    grouped = {}
    for row in rows:
        provider = row.get('supplied_by') or {}
        key = (row['seq'], row['code'], row['source_zone'], row['purpose'], provider.get('node'))
        if key not in grouped: grouped[key] = row; continue
        target = grouped[key]
        target['count'] += row['count']
        for field in ('instances', 'evidence', 'uses'):
            target[field] = list(dict.fromkeys(target[field]+row[field]))
        target['id'] = digest([target['id'], row['id']])
    return {'schema': VERSION, 'revision': digest([review.get('revision'), graph, events, sorted(generic_instances), VERSION]),
            'status': 'pending' if pending else 'recorded', 'conditions': list(grouped.values()), 'timeline': timeline,
            'random_instances': sorted(tainted),
            'warnings': list(dict.fromkeys(pending)), 'basis': '由冻结的操作选择、实例与区域变化补算；按步骤检查，规则合法性仍由当前引擎判断。'}


def attach(report, branches=True):
    """Read-only upgrade, including each alternative branch independently."""
    value = deepcopy(report)
    summary = value.setdefault('requirements', {})
    generic = {str(i) for r in summary.get('opening', []) if r.get('code') is None and r.get('constraint') == '任意手牌' for i in r.get('instances', [])}
    summary['implicit'] = extract(value, generic)
    for branch in value.get('branches', []) if branches else []:
        if isinstance(branch, dict) and branch.get('report'): branch['report'] = attach(branch['report'])
    return value


def check(report, deck, hand):
    summary = report.get('requirements') or {}
    implicit = extract(report, {str(i) for r in summary.get('opening', []) if r.get('code') is None and r.get('constraint') == '任意手牌' for i in r.get('instances', [])})
    pool = Counter((c, 1) for c in deck['main']) + Counter((c, 64) for c in deck['extra'])
    for c in hand: pool[c, 1] -= 1; pool[c, 2] += 1
    bound, available = {}, {}
    # Instances already claimed by a different source instance cannot be reused
    # accidentally; returning one to the deck preserves that same binding.
    def bind(item):
        key, code, zone = item['instance'], item['code'], item['location']
        if key in bound:
            return bound[key][1] == zone and available[key]
        options = [c for c, loc in pool if loc == zone and pool[c, loc] > 0 and (code is None or c == code)]
        if not options: return False
        code = options[0]; pool[code, zone] -= 1; bound[key] = (code, zone); available[key] = True
        return True
    # Reserve exact opening identities before assigning generic costs, so an
    # arbitrary discard cannot consume a card needed by a later exact action.
    initial_ids = {str(c.get('instance_id')) for c in report.get('initial_hand') or []}
    for item in implicit['timeline']:
        if item.get('instance') in initial_ids and item.get('code') is not None and item.get('location') == 2:
            bind(item)
    for item in implicit['timeline']:
        if item['kind'] in ('random', 'unknown_result'):
            return {'status': 'random' if item['kind'] == 'random' else 'pending', 'reason': f"第{item.get('step') or '?'}步：{item['reason']}", 'implicit': implicit}
        if item['kind'] == 'move' and item['controller'] != 0:
            return {'status': 'pending', 'reason': '路线涉及对手区域资源，需要核对本局实际局面', 'implicit': implicit}
        if item['kind'] == 'move' and item['location'] == 0:
            bound[item['instance']] = (item['code'], item['to'])
            available[item['instance']] = item['to_controller'] == 0 and item['to'] != 0
            continue
        if not bind(item):
            count = pool[item['code'], item['location']] + sum(available[k] and v == (item['code'], item['location']) for k, v in bound.items())
            condition = next((c for c in implicit['conditions'] if item['instance'] in c['instances'] and c['location'] == item['location'] and c['seq'] <= item['seq']), {})
            reason = f"第{item.get('step') or '?'}步需要从{zone_name(item['location'])}{condition.get('purpose', '取得')}「{item['name']}」×{condition.get('count', 1)}，当前区域剩余{max(0, count)}张（缺少可用于本次操作的副本）"
            return {'status': 'unmet', 'reason': reason, 'implicit': implicit}
        if item['kind'] == 'move':
            bound[item['instance']] = (bound[item['instance']][0], item['to'])
            available[item['instance']] = item['to_controller'] == 0 and item['to'] != 0
    if implicit['warnings']:
        return {'status': 'pending', 'reason': '条件待核对：' + '；'.join(implicit['warnings']), 'implicit': implicit}
    if summary.get('random'):
        return {'status': 'random', 'reason': '依赖尚未确认的随机结果', 'implicit': implicit}
    return {'status': 'satisfied', 'reason': '已核对本局起手及逐步区域资源；仍须满足原路线其他规则条件', 'implicit': implicit}
