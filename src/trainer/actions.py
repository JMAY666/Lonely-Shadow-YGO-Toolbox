"""Project verified protocol events into readable actions without discarding evidence.

Chain link numbers are scoped to one chain group. Only effects observed inside the
matching resolution interval are attached; native cause metadata can veto that
association. Card text describes the effect, never supplies a missing result.
"""
from collections import Counter
from copy import deepcopy

REASON_EFFECT, REASON_COST, REASON_RULE = 0x40, 0x80, 0x400
ZONES = {1: '卡组', 2: '手牌', 4: '怪兽区', 8: '魔法陷阱区', 16: '墓地', 32: '除外区', 64: '额外卡组', 128: '叠放素材'}
NOISE = {2, *range(10, 27), 30, 31, 32, 33, 34, 36, 38, 39, 40, 41, 42,
         71, 72, 73, 74, 80, 81, 83, 94, 132, 133, 140, 141, 142, 143, 160, 161, 162, 163, 164, 165, 170,
         '玩家选择', '占位方自动跳过'}


def card_names(cards):
    counts = Counter(c.get('name') or f"卡牌 {c.get('code') or '未知'}" for c in cards)
    return '、'.join(f'{name} ×{count}' if count > 1 else name for name, count in counts.items())


def place(loc):
    if not loc: return '未知区域'
    side = '我方' if loc.get('controller') == 0 else '占位方' if loc.get('controller') == 1 else '未知方'
    zone = ZONES.get(loc.get('location'), '未知区域')
    number = f" {loc['sequence'] + 1}" if loc.get('location') in (4, 8) and loc.get('sequence', -1) >= 0 else ''
    return f'{side}{zone}{number}'


def same_card(a, b):
    # Never merge same-name copies when identity is unavailable.
    return a.get('instance_id') is not None and a.get('instance_id') == b.get('instance_id')


def semantic_result(e):
    msg, cards = e['message'], e.get('cards', [])
    if msg == 90:
        prefix = '' if e.get('actor') == 'self' else '占位方'
        return f'{prefix}抽 {len(cards)} 张卡'
    if msg == 50:
        dest, reason = e.get('destination', {}), e.get('reason') or 0
        verb = '作为费用，' if reason & REASON_COST else ''
        if reason & 1: verb += '破坏'
        elif reason & 2: verb += '解放'
        elif reason & 0x4000: verb += '丢弃'
        if verb and not verb.endswith('，'): verb += '并'
        return f"{verb}将{card_names(cards)}从{place(e.get('origin'))}移至{place(dest)}"
    if msg == 100: return f"支付 {e.get('amount', '未知')} LP 作为费用"
    if msg in (91, 92):
        who = '我方' if e.get('player') == 0 else '占位方'
        return f"{who}{'受到' if msg == 91 else '回复'} {e.get('amount', '未知')} {'伤害' if msg == 91 else 'LP'}"
    if msg in (61, 63, 65):
        verb = {61:'通常召唤',63:'特殊召唤',65:'反转召唤'}[msg]
        zones = '、'.join(dict.fromkeys(place(c) for c in cards))
        return f"{verb}{card_names(cards)}{('至' + zones) if zones else ''}"
    if msg == 54: return f"在{place(cards[0] if cards else None)}盖放{card_names(cards)}"
    if msg == 53: return f"{card_names(cards)}改为{ {1:'攻击表示',2:'里侧攻击表示',4:'守备表示',8:'里侧守备表示'}.get(e.get('position_to'), '未知表示')}"
    return f"{e['type']}{('：' + card_names(cards)) if cards else ''}"


def project_actions(report):
    events, catalog = report['events'], report.get('catalog', {})
    actions, links, resolving, suppressed = [], {}, None, {}
    event_by_id = {e['id']: e for e in events}
    preparation_start = 0
    deferred_results = {}
    chain_group, resolution_order = 1, 0
    pending_summons = {}

    def make(e, kind='action', text=None):
        a = {'id': e['id'], 'time_ms': e['time_ms'], 'kind': kind,
             'cards': deepcopy(e.get('cards', [])), 'summary': text or semantic_result(e),
             'evidence_refs': [e['id']], 'results': [], 'costs': [], 'targets': [],
             'status': 'observed', 'activation_ref': None, 'chain_group': None, 'chain_link': None,
             'resolution_order': None, 'effect_text': None}
        actions.append(a)
        return a

    def attach(a, e, role):
        if e['id'] not in a['evidence_refs']: a['evidence_refs'].append(e['id'])
        if role in ('results', 'costs'):
            a[role].append({'event_ref': e['id'], 'message': e['message'], 'text': semantic_result(e), 'cards': deepcopy(e.get('cards', []))})
        suppressed[e['id']] = role

    def cause_matches(a, e):
        source = e.get('cause')
        if source is None: return True  # Older journals have only the chain interval.
        effect = a.get('engine_effect')
        if effect and source.get('effect_id') is not None:
            key = 'effect_handle' if source.get('effect_handle') and effect.get('effect_handle') else 'effect_id'
            return source[key] == effect.get(key) and source.get('handler_instance') == effect.get('handler_instance')
        cards = a['cards']
        return bool(cards and source.get('handler_instance') == cards[0].get('instance_id'))

    def consume_preparation(a, e):
        if not a['cards']: return
        # Only the nearest meaningful action can be a normal placement before activation/summon.
        for prior in reversed(actions[:-1]):
            if prior['id'] in suppressed: continue
            candidate = event_by_id[prior['id']]
            if candidate['message'] == 50 and candidate.get('cards') and same_card(candidate['cards'][0], a['cards'][0]):
                dest = candidate.get('destination', {})
                if dest.get('location') in (4, 8) and dest.get('location') == a['cards'][0].get('location') and not candidate.get('cost'):
                    attach(a, candidate, 'placement')
            break

    for index, e in enumerate(events):
        msg = e['message']
        if msg in (11, 40, 41): preparation_start = index
        if msg == 70:
            c = e['cards'][0] if e.get('cards') else {}
            a = make(e, 'effect', f"在{place(c)}发动{card_names(e.get('cards', [])) or '未知卡牌'}的效果")
            a.update(activation_ref=e['id'], chain_group=chain_group, chain_link=e.get('chain'), status='pending',
                     engine_effect=deepcopy(e.get('engine_effect')))
            definition = catalog.get(str(c.get('code')), {})
            a['effect_text'] = definition.get('desc')
            descriptor = (e.get('effect') or {}).get('description_id')
            if descriptor and descriptor >> 4 == c.get('code'):
                a['effect_label'] = definition.get(f'str{(descriptor & 15) + 1}') or None
            links[e.get('chain')] = a
            consume_preparation(a, e)
            # A cost can precede MSG_CHAINING. Only explicit native attribution permits this merge.
            for prior in actions[:-1]:
                if prior['id'] in suppressed: continue
                cost_event = event_by_id[prior['id']]
                if cost_event in events[preparation_start:index] and cost_event.get('cost') and cost_event.get('cause') and cause_matches(a, cost_event): attach(a, cost_event, 'costs')
            preparation_start = index + 1
            continue
        if msg == 72:
            resolving = links.get(e.get('chain'))
            if resolving:
                resolution_order += 1; resolving['resolution_order'] = resolution_order
                # Core effect.id is reordered on activation. The live link's Lua handle is stable;
                # older native journals use the matching resolution-time id as a fallback.
                if e.get('engine_effect'): resolving['engine_effect'] = deepcopy(e['engine_effect'])
                attach(resolving, e, 'lifecycle')
            continue
        if msg in (71, 73, 75, 76):
            a = links.get(e.get('chain'))
            if a:
                attach(a, e, 'lifecycle')
                if msg in (75, 76): a['status'] = 'negated' if msg == 75 else 'disabled'
                if msg == 73:
                    if e.get('engine_effect'): a['engine_effect'] = deepcopy(e['engine_effect'])
                    for candidate in deferred_results.pop(a['id'], []):
                        if a['status'] == 'pending' and cause_matches(a, candidate):
                            attach(a, candidate, 'costs' if candidate.get('cost') else 'results')
                    if a['status'] == 'pending': a['status'] = 'resolved'
                    if resolving is a: resolving = None
            elif msg in (75, 76): make(e, 'exception')
            continue
        if msg == 74:
            chain_group += 1; links = {}; resolving = None
            preparation_start = index + 1
            continue
        if msg == 83:
            # Targets attach to the latest link only with a native effect match or a unique open link.
            choices = [a for a in links.values() if a['status'] == 'pending' and (not e.get('cause') or cause_matches(a, e))]
            if len(choices) == 1:
                a = choices[0]; a['targets'].extend(deepcopy(e.get('targets') or [])); attach(a, e, 'target')
            elif e.get('targets'):
                make(e, 'target', '选择对象：' + card_names(e['targets']))
            continue
        if msg in NOISE:
            suppressed[e['id']] = 'protocol'
            continue
        if msg == 90 and (e['id'] == report.get('initial_hand_ref') or e.get('draw_kind') == 'rule'):
            suppressed[e['id']] = 'initial_or_rule_draw'; continue
        if msg == 50:
            origin, dest, reason = e.get('origin', {}), e.get('destination', {}), e.get('reason')
            # The core explicitly sends resolved normal spells/traps with REASON_RULE (0x400).
            # Effect destruction, costs, redirects, unrelated cards and unknown reasons remain visible.
            if origin.get('location') == 8 and dest.get('location') == 16 and reason == REASON_RULE:
                c = e['cards'][0] if e.get('cards') else {}
                definition = catalog.get(str(c.get('code')), {})
                type_flags = definition.get('type', 0)
                candidates = [a for a in links.values() if a['status'] == 'resolved' and a['cards'] and same_card(c, a['cards'][0])]
                if candidates and type_flags & 6 and not type_flags & (0x20000 | 0x40000 | 0x80000 | 0x1000000):
                    attach(candidates[-1], e, 'rule_cleanup'); continue
        if msg in (60, 62, 64):
            pending_summons.setdefault(msg + 1, []).append(e)
            continue
        if msg in (61, 63, 65):
            candidates = pending_summons.pop(msg, [])
            a = make(e, 'summon')
            for started in candidates: attach(a, started, 'summon_begin')
            consume_preparation(a, e)
            if resolving and resolving['status'] == 'pending' and cause_matches(resolving, e):
                attach(resolving, e, 'results')
                for source in a['evidence_refs']:
                    if source not in resolving['evidence_refs']: resolving['evidence_refs'].append(source)
            continue
        if resolving and resolving['status'] == 'pending' and msg in (50, 90, 91, 92, 100, 53, 54, 93, 95, 101, 102):
            # Rule handling is not attributed to an effect just because it occurs in its resolution interval.
            if not (msg == 50 and (e.get('reason') or 0) & REASON_RULE and not (e.get('reason') or 0) & (REASON_EFFECT | REASON_COST)):
                if cause_matches(resolving, e):
                    attach(resolving, e, 'costs' if e.get('cost') else 'results'); continue
                deferred_results.setdefault(resolving['id'], []).append(e)
        a = make(e, 'cost' if e.get('cost') else 'action')
        if msg == 54: consume_preparation(a, e)
        if msg == 90 and e.get('draw_kind') == 'unknown': a['summary'] += '（原因未知）'

    for pending in pending_summons.values():
        for e in pending: make(e, 'summon', semantic_result(e) + '（尚未确认成功）')
    result = [a for a in actions if a['id'] not in suppressed]
    for a in result:
        if a['kind'] != 'effect': continue
        if a['costs']: a['summary'] += '；' + '；'.join(c['text'] for c in a['costs'])
        if a['targets']: a['summary'] += '，对象为' + card_names(a['targets'])
        if a['results']: a['summary'] += '，' + '，'.join(r['text'] for r in a['results'])
        if a['status'] in ('negated', 'disabled'):
            a['summary'] += '（发动被无效）' if a['status'] == 'negated' else '（效果被无效）'
        elif a['status'] == 'pending':
            a['summary'] += '（尚未确认结算完成）'
        elif not a['results']:
            a['summary'] += '（未识别出可描述的实际结果）'
        a['association'] = '核心原因效果与连锁结算区间' if a.get('engine_effect') else '连锁编号与结算区间（旧记录无原因效果标识）'
    order = {e['id']: i for i, e in enumerate(events)}
    for a in result: a['evidence_refs'].sort(key=order.get)
    result.sort(key=lambda a: order[a['id']])
    return result
