"""Read-only review snapshots and evidence-based route requirements.

This projection never runs the engine. Native rows and the frozen report remain
facts; names, notes and manually checked requirements are a separate document.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import re
from module_graph import attach_modules

REVIEW_VERSION = 2


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def bounds(action):
    refs = [int(str(ref).split(':')[0]) for ref in action.get('evidence_refs', [action['id']])]
    return min(refs), max(refs)


def public_state(state):
    """The engine knows hidden opponent cards. The review must not disclose them."""
    if state is None: return None
    result = deepcopy(state)
    for card in result.get('cards', []):
        loc, pos = card.get('location'), card.get('position', 0)
        hidden = card.get('controller') == 1 and (loc in (1, 2) or
                 loc == 64 and not pos & 5 or loc in (4, 8, 32) and bool(pos & 10))
        if hidden:
            card.update(code=None, name='未知卡牌', identity_known=False)
        else:
            card['identity_known'] = bool(card.get('code'))
    return result


def make_review(report, rows):
    """Group complete actions at recorded boundaries, never inside a batch/chain.

    An action that straddles a boundary postpones that boundary. Thus a state
    cannot contain the result of an action assigned to a later node.
    """
    snapshots = {r['seq']: r['state'] for r in rows if 'state' in r}
    actions = report.get('actions', [])
    first = int(str(report.get('initial_hand_ref') or '0:0').split(':')[0])
    initial = snapshots.get(first)
    nodes = [{'id': 'initial', 'kind': 'initial', 'state': public_state(initial), 'state_ref': first or None,
              'range': [first, first], 'action_ids': []}]
    ordered = list(actions)  # Preserve the report's observed action order, including material cleanup.
    checkpoints = [r['seq'] for r in rows if r.get('kind') == 'checkpoint' and r['seq'] > first]
    # For older journals, whole batches provide equally explicit boundaries.
    boundaries = sorted(set(checkpoints + [bounds(a)[1] for a in actions if not checkpoints or bounds(a)[1] > checkpoints[-1]]))
    assigned, previous = set(), first
    for end in boundaries:
        active = [a for a in ordered if a['id'] not in assigned and bounds(a)[0] <= end]
        if not active or any(bounds(a)[1] > end for a in active): continue
        ids = [a['id'] for a in active]
        state = snapshots.get(end)
        nodes.append({'id': 'step:' + ids[0], 'kind': 'step', 'state': public_state(state), 'state_ref': end,
                      'range': [previous + 1, end], 'action_ids': ids})
        assigned.update(ids)
        previous = end
    # Missing evidence is represented explicitly, never filled with the final state.
    for action in ordered:
        if action['id'] not in assigned:
            start, end = bounds(action)
            nodes.append({'id': 'step:' + action['id'], 'kind': 'step', 'state': None, 'state_ref': None,
                          'range': [start, end], 'action_ids': [action['id']]})
    final_ref = report.get('final_state_ref', previous)
    nodes.append({'id': 'final', 'kind': 'final', 'state': public_state(report.get('final_state')),
                  'state_ref': final_ref, 'range': [min(previous + 1, final_ref or previous), final_ref], 'action_ids': []})
    action_nodes = {}
    for ordinal, node in enumerate(nodes, 1):
        node['number'] = ordinal
        for aid in node['action_ids']: action_nodes[aid] = node['id']
    action_by_id = {a['id']: a for a in actions}
    for node in nodes:
        selected = [action_by_id[aid] for aid in node['action_ids']]
        node['opponent'] = opponent_context(selected, report, nodes, node)
        if node['opponent']['visible'] and selected:
            start = min(bounds(a)[0] for a in selected)
            earlier = [seq for seq in snapshots if seq < start]
            if earlier:
                seq = max(earlier)
                before = public_state(snapshots[seq])
                node['opponent']['before'] = {'state_ref': seq, 'cards': [c for c in before.get('cards', [])
                    if c.get('controller') == 1 and c.get('location') in node['opponent']['zones']], 'lp': before.get('lp', [None, None])[1]}
    loaded = next((r.get('state') for r in rows if r.get('kind') == 'loaded'), None)
    initial_cards = loaded.get('cards', []) if loaded else []
    origins = {str(c['instance_id']): {'code': c.get('code'), 'owner': c.get('owner', c.get('controller')),
               'group': 'main' if c.get('location') == 1 else 'extra' if c.get('location') == 64 else None}
               for c in initial_cards if c.get('instance_id') is not None}
    value = {'version': REVIEW_VERSION, 'nodes': nodes, 'action_nodes': action_nodes, 'instance_origins': origins,
             'complete': bool(initial and report.get('initial_hand') and report.get('final_state') and
                              all(n['state'] is not None for n in nodes) and not any(
                                  any(word in warning for word in ('采集序号不连续', '冲突的重复序号', '未完成或损坏', '原始记录 '))
                                  for warning in report.get('warnings', []))),
             'boundary_note': '节点显示记录范围结束后的快照；同一批次及跨边界的连锁动作合并展示。'}
    attach_modules(value, report, rows)
    value['revision'] = digest(value)
    return value


def legacy_review(report):
    """Do not source a saved plan's missing states from a possibly changed session."""
    if report.get('review'):
        # Frozen revisions and annotation IDs stay stable when viewing old plans.
        return attach_modules(deepcopy(report['review']), report)
    review = make_review(report, [])
    # Only the hand is known at the initial boundary. Other regions remain unknown.
    if report.get('initial_hand'):
        review['nodes'][0]['state'] = {'cards': [{**c, 'location': 2, 'controller': 0,
                 'sequence': i} for i, c in enumerate(report['initial_hand'])], 'partial': True}
    review['complete'] = False
    review['boundary_note'] = '旧方案未保存逐步快照：初始仅显示已记录手牌，缺失的步骤状态标为未知；原文件保持不变。'
    review.pop('module_graph', None)
    attach_modules(review, report)
    review['revision'] = digest({k: v for k, v in review.items() if k != 'revision'})
    return review


def opponent_context(actions, report, nodes, node):
    zones, reasons = set(), []
    events = {e['id']: e for e in report.get('events', [])}
    for action in actions:
        for ref in action.get('evidence_refs', []):
            event = events.get(ref, {})
            if event.get('player') == 1 and event.get('message') in (91, 92, 94, 100):
                reasons.append('本步改变对方生命值或支付对方费用')
        cards = action.get('cards', []) + action.get('targets', [])
        cards += [c for group in ('costs', 'results') for item in action.get(group, []) for c in item.get('cards', [])]
        for card in cards:
            if card.get('controller') == 1:
                zones.add(card.get('location', 4)); reasons.append('本步涉及对方卡牌或响应')
        text = action.get('selected_effect_text') or action.get('effect_text') or ''
        if not text and action.get('kind') == 'summon':
            # A procedure summon (e.g. Cyber Dragon) may depend on the opponent
            # without creating an activated effect or moving an opposing card.
            text = ' '.join(re.split(r'[①②③④⑤⑥⑦⑧⑨⑩]', report.get('catalog', {}).get(str(c.get('code')), {}).get('desc', ''))[0]
                            for c in action.get('cards', []) if c.get('summon_method') == '特殊召唤')
        if re.search(r'对方|对手|對方|對手|opponent', text, re.I):
            zones.update((4, 8))
            reasons.append('本步效果文本涉及对方；发动条件与处理以实际记录为准')
            for word, location in [('手卡', 2), ('手牌', 2), ('墓地', 16), ('除外', 32), ('卡组', 1), ('额外', 64)]:
                if word in text: zones.add(location)
    # End-board relationships (including stolen cards/materials) are still relevant.
    if node['kind'] == 'final':
        related = [c for c in (node.get('state') or {}).get('cards', [])
                   if c.get('owner') != c.get('controller') and c.get('owner') in (0, 1)]
        if related: zones.add(4); reasons.append('终场存在双方控制权关联')
    return {'visible': bool(reasons), 'zones': sorted(zones), 'reasons': list(dict.fromkeys(reasons))}


def empty_annotations():
    return {'version': 1, 'nodes': {}, 'cards': {}, 'effects': {}, 'costs': {}, 'final_marks': {}, 'conditions_note': '', 'extra_conditions': []}


def annotations_for(report, value=None):
    value = deepcopy(report.get('annotations', empty_annotations()) if value is None else value)
    if not isinstance(value, dict): raise ValueError('方案说明格式无效')
    review = legacy_review(report)
    nodes = {n['id']: n for n in review['nodes']}
    actions = {a['id'] for a in report.get('actions', [])}
    result = empty_annotations()

    def text(value, limit=4000):
        if not isinstance(value, str) or len(value) > limit: raise ValueError(f'说明须为不超过 {limit} 字的文字')
        return value

    def mapping(key):
        data = value.get(key, {})
        if not isinstance(data, dict) or len(data) > 2000: raise ValueError('方案说明数量或格式无效')
        return data

    for key, edit in mapping('nodes').items():
        if key not in nodes or not isinstance(edit, dict): raise ValueError('步骤已改变，请重新打开核对')
        result['nodes'][key] = {'name': text(edit.get('name', ''), 80), 'notes': text(edit.get('notes', ''))}
    final_ids = {str(c['instance_id']) for c in (nodes['final'].get('state') or {}).get('cards', []) if c.get('instance_id') is not None}
    for key, edit in mapping('cards').items():
        if key not in final_ids: raise ValueError('终场卡牌实例不存在，不能关联说明')
        result['cards'][key] = text(edit)
    for key, edit in mapping('final_marks').items():
        if key not in final_ids or not isinstance(edit, dict) or type(edit.get('marked')) is not bool:
            raise ValueError('终场标记须关联有效卡牌实例')
        card = next(c for c in nodes['final']['state']['cards'] if str(c.get('instance_id')) == key)
        desc = report.get('catalog', {}).get(str(card.get('code')), {}).get('desc', '')
        parts = [p for p in re.split(r'(?=[①②③④⑤⑥⑦⑧⑨⑩][：:])', desc) if p]
        effects = edit.get('effects', {})
        if not isinstance(effects, dict) or len(effects) > len(parts): raise ValueError('效果标记无效')
        checked = {}
        for index, item in effects.items():
            if index not in {str(i) for i in range(len(parts))} or not isinstance(item, dict):
                raise ValueError('效果文本已改变，请重新核对')
            checked[index] = {'note': text(item.get('note', ''))}
        result['final_marks'][key] = {'marked': edit['marked'], 'effects': checked}
    for key, edit in mapping('effects').items():
        if key not in actions: raise ValueError('效果对应步骤不存在')
        result['effects'][key] = text(edit)
    candidates = cost_candidates(report)
    for key, edit in mapping('costs').items():
        if key not in candidates or not isinstance(edit, dict) or edit.get('mode') not in ('specific', 'any'):
            raise ValueError('费用核对项无效')
        constraint = text(edit.get('constraint', ''), 300).strip()
        if edit['mode'] == 'any' and (not candidates[key]['replaceable'] or not constraint):
            raise ValueError('此费用牌后续仍被使用，或缺少任意牌的真实限制，不能简化')
        result['costs'][key] = {'mode': edit['mode'], 'constraint': constraint}
    result['conditions_note'] = text(value.get('conditions_note', ''))
    extra = value.get('extra_conditions', [])
    if not isinstance(extra, list) or len(extra) > 60: raise ValueError('补充条件最多 60 项')
    for item in extra:
        if not isinstance(item, dict) or item.get('kind') not in ('opening', 'resource', 'random'):
            raise ValueError('补充条件类型无效')
        code, count, node = item.get('code'), item.get('count'), item.get('node')
        if code is not None and (type(code) is not int or str(code) not in report.get('catalog', {})): raise ValueError('补充卡牌不在本次冻结资料中')
        if type(count) is not int or not 1 <= count <= 60 or node not in nodes: raise ValueError('补充条件须有有效数量和关联步骤')
        constraint = text(item.get('constraint', ''), 300).strip()
        if not constraint: raise ValueError('请填写补充条件或用途')
        result['extra_conditions'].append({'kind': item['kind'], 'code': code, 'count': count, 'node': node, 'constraint': constraint})
    return result


def relevant_uses(report):
    """Ignore random reveals/draws until those physical cards participate later."""
    uses = defaultdict(list)
    events = {e['id']: e for e in report.get('events', [])}
    for action in report.get('actions', []):
        for ref in action.get('evidence_refs', []):
            event = events.get(ref, {})
            msg = event.get('message')
            if msg not in (50, 53, 54, 60, 61, 62, 63, 64, 65, 70, 83): continue
            if msg == 50:
                reason = event.get('reason') or 0
                if event.get('deck_operation') or (reason & 0x400 and not reason & (0x40 | 0x80)): continue
                if event.get('origin', {}).get('location') == event.get('destination', {}).get('location') == 1: continue
            for card in event.get('cards', []):
                if card.get('instance_id') is not None:
                    entry = {'action': action['id'], 'event': ref, 'card': card, 'cost': bool(event.get('cost')),
                             'seq': event.get('native_seq', 0), 'message': msg}
                    if not any(x['event'] == ref for x in uses[str(card['instance_id'])]): uses[str(card['instance_id'])].append(entry)
        for card in action.get('cards', []):
            for material in card.get('materials', []):
                key = material.get('instance_id')
                if key is not None and not uses[str(key)]:
                    uses[str(key)].append({'action': action['id'], 'event': action['id'], 'card': material,
                                          'cost': False, 'seq': bounds(action)[1], 'message': 63})
    return uses


def cost_candidates(report):
    uses = relevant_uses(report)
    events = {e['id']: e for e in report.get('events', [])}
    actions = {a['id']: a for a in report.get('actions', [])}
    result = {}
    for key, entries in uses.items():
        entries.sort(key=lambda e: (e['seq'], int(e['event'].split(':')[-1])))
        first = entries[0]
        source = events.get(first['event'], {})
        if not first['cost'] or source.get('origin', {}).get('location') != 2: continue
        action = actions[first['action']]
        text = action.get('selected_effect_text') or ''
        # Only unqualified, explicit hand costs from an identified clause are
        # automatically generalized. More restricted costs require a human check.
        generic = bool(re.search(r'(?:丢弃[1１一]张手[卡牌]|将[1１一]张手[卡牌](?:丢弃|送去墓地))'
                                 r'(?:[，,]以[^。；]*为对象)?(?:才?能|可以)发动', text))
        replaceable = all(entry['cost'] for entry in entries) and not any(
            e.get('cause', {}).get('handler_instance') == first['card'].get('instance_id')
            for e in report.get('events', []) if e.get('cause'))
        result[key] = {'card': deepcopy(first['card']), 'action': first['action'], 'event': first['event'],
                       'replaceable': replaceable, 'automatic': generic and replaceable,
                       'constraint': '任意手牌' if generic and replaceable else '任意符合实际费用条件的手牌',
                       'text': text or '具体效果待补充；请对照完整效果文本核对费用限制'}
    return result


def requirements(report, annotations=None):
    review = legacy_review(report)
    edits = annotations_for(report, annotations)
    uses, candidates = relevant_uses(report), cost_candidates(report)
    actions = {a['id']: a for a in report.get('actions', [])}
    nodes = {n['id']: n for n in review['nodes']}
    initial = {str(c['instance_id']) for c in report.get('initial_hand') or [] if c.get('instance_id') is not None}
    drawn = {}
    for event in report.get('events', []):
        if event.get('message') == 90 and event.get('id') != report.get('initial_hand_ref'):
            for card in event.get('cards', []):
                if card.get('instance_id') is not None: drawn.setdefault(str(card['instance_id']), event['id'])
    from implicit_conditions import extract
    evidence = extract({**report, 'review': review})
    for instance in evidence['random_instances']: drawn.setdefault(instance, 'uncertain-deck-result')
    buckets = {'main': {}, 'extra': {}, 'opening': {}, 'random': {}}
    unknown = []
    for key, entries in uses.items():
        card = entries[0]['card']
        origin = review.get('instance_origins', {}).get(key, {})
        owner = origin.get('owner', card.get('owner', card.get('controller')))
        if owner != 0: continue
        group = origin.get('group')
        code = origin.get('code') or card.get('code')
        if not group and not review.get('instance_origins'):
            in_main = code in report.get('deck', {}).get('main', [])
            in_extra = code in report.get('deck', {}).get('extra', [])
            if in_main != in_extra: group = 'main' if in_main else 'extra'
        if not group or not code:
            unknown.append('卡牌实例 ' + key + ' 的卡组来源未记录'); continue
        candidate, override = candidates.get(key), edits['costs'].get(key)
        any_card = bool(candidate and candidate['replaceable'] and
                        (override['mode'] == 'any' if override else candidate['automatic']))
        constraint = (override['constraint'] if override else candidate['constraint']) if any_card else ''
        effective_code = None if any_card else code
        label = constraint if any_card else report.get('catalog', {}).get(str(code), {}).get('name', card.get('name', str(code)))
        aid = list(dict.fromkeys(entry['action'] for entry in entries))
        step_ids = list(dict.fromkeys(review['action_nodes'].get(a) for a in aid if review['action_nodes'].get(a)))
        random = key not in initial and key in drawn
        def add(bucket):
            ident = (effective_code, constraint)
            row = buckets[bucket].setdefault(ident, {'code': effective_code, 'name': label, 'count': 0, 'instances': [],
                    'nodes': [], 'uses': [], 'status': '用户核对' if override and any_card else '已记录使用', 'constraint': constraint})
            row['count'] += 1; row['instances'].append(key)
            row['nodes'] = list(dict.fromkeys(row['nodes'] + step_ids))
            row['uses'] = list(dict.fromkeys(row['uses'] + [actions[a].get('observed_summary') or actions[a]['summary'] for a in aid]))
        # A random hit is a dependency, not a deterministic deck requirement.
        if random and not any_card: add('random')
        else: add(group)
        if key in initial: add('opening')
    for item in edits['extra_conditions']:
        group = item['kind']
        if group == 'resource':
            group = 'extra' if item['code'] in report.get('deck', {}).get('extra', []) else 'main'
        buckets[group][('manual', len(buckets[group]))] = {**item, 'name': report.get('catalog', {}).get(str(item['code']), {}).get('name', item['constraint']),
                   'nodes': [item['node']], 'uses': [item['constraint']], 'instances': [], 'status': '用户补充'}
    # Unknown physical identities cannot be reliably counted or deduplicated.
    used_refs = {ref for a in actions.values() for ref in a.get('evidence_refs', [])}
    if any(c.get('instance_id') is None for e in report.get('events', []) if e['id'] in used_refs for c in e.get('cards', [])):
        unknown.append('部分动作缺少卡牌实例，份数与起手条件需要人工核对')
    implicit = extract({**report, 'review': review}, {i for row in buckets['opening'].values() if row.get('code') is None and row.get('constraint') == '任意手牌' for i in row['instances']})
    return {**{k: list(v.values()) for k, v in buckets.items()}, 'cost_candidates': candidates, 'implicit': implicit,
            'warnings': list(dict.fromkeys(unknown)), 'note': edits['conditions_note'],
            'basis': '按本次路线中实际使用的卡牌实例统计；不是对所有替代路线的最小条件证明。',
            'final': {'cards': [c for c in (nodes['final'].get('state') or {}).get('cards', [])
                               if edits['final_marks'].get(str(c.get('instance_id')), {}).get('marked')],
                      'notes': edits['nodes'].get('final', {}).get('notes', '')}}


def confirmation_key(report, name, notes, annotations):
    return digest({'id': report['id'], 'review': legacy_review(report)['revision'], 'name': name, 'notes': notes,
                   'annotations': annotations, 'edit_revision': report.get('edit_revision', 0),
                   'branches': report.get('branches', []), 'branches_revision': report.get('branches_revision', 0)})
