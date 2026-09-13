"""Project verified protocol events into readable actions without discarding evidence.

Chain link numbers are scoped to one chain group. Only effects observed inside the
matching resolution interval are attached; native cause metadata can veto that
association. Card text describes the effect, never supplies a missing result.
"""
from collections import Counter
from copy import deepcopy
import re
from card_semantics import CIRCLED, effect_clause, material_method, zone_name

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
    return side + zone_name(loc.get('location', 0), loc.get('sequence', -1))


def same_card(a, b):
    # Never merge same-name copies when identity is unavailable.
    return a.get('instance_id') is not None and a.get('instance_id') == b.get('instance_id')


def semantic_result(e):
    msg, cards = e['message'], e.get('cards', [])
    if msg == 90:
        prefix = '自己' if e.get('actor') == 'self' else '占位方'
        return f'{prefix}抽 {len(cards)} 张卡'
    if msg == 50:
        dest, reason = e.get('destination', {}), e.get('reason') or 0
        deck_op = e.get('deck_operation')
        if deck_op:
            return {'position_refresh':'刷新卡组内部位置', 'move_to_bottom':f'将{card_names(cards)}放回我方卡组底部',
                    'move_to_top':f'将{card_names(cards)}放回我方卡组顶部', 'reorder':f'调整{card_names(cards)}在卡组中的顺序'}.get(deck_op, '调整卡组内卡牌状态')
        if reason & REASON_COST and reason & 0x4000 and e.get('origin', {}).get('location') == 2:
            return '支付费用：从我方手卡丢弃' + card_names(cards)
        if dest.get('location') == 32:
            pos = dest.get('position', 0)
            facing = '里侧' if pos & 10 and not pos & 5 else '表侧' if pos & 5 and not pos & 10 else ''
            return f"{'支付费用：' if reason & REASON_COST else ''}从{place(e.get('origin'))}将{card_names(cards)}{facing}除外"
        if reason & REASON_COST and dest.get('location') == 16:
            return f"支付费用：将{place(e.get('origin'))}的{card_names(cards)}送去墓地"
        if reason & REASON_EFFECT and dest.get('location') == 2 and not reason & REASON_COST:
            return f"从{place(e.get('origin'))}将{card_names(cards)}加入手卡"
        if reason & 8:
            method = material_method(reason)
            return f"将{card_names(cards)}作为{method.removesuffix('召唤') if method else '召唤'}素材，从{place(e.get('origin'))}移至{place(dest)}"
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
    if msg in (30, 42): return f"翻开{'我方' if e.get('player') == 0 else '占位方'}{'额外卡组' if msg == 42 else '卡组'}顶的 {len(cards)} 张卡"
    if msg in (61, 63, 65):
        verb = {61:'通常召唤',63:'特殊召唤',65:'反转召唤'}[msg]
        descriptions = []
        for c in cards:
            method = c.get('summon_method') or verb
            materials = c.get('materials', [])
            lead = ''
            if materials and method in ('连接召唤','同调召唤','融合召唤','超量召唤','仪式召唤','上级召唤'):
                lead = f"以{card_names(materials)}作为{method.removesuffix('召唤')}素材，"
            origin = c.get('summon_origin')
            route = f"从{place(origin)}" if origin and method == '特殊召唤' else ''
            descriptions.append(f"{lead}{route}{method}{card_names([c])}至{place(c)}")
        return '；'.join(descriptions) or verb
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
             'resolution_order': None, 'effect_text': None, 'revealed_cards': []}
        actions.append(a)
        return a

    def attach(a, e, role, detail=None):
        if e['id'] not in a['evidence_refs']: a['evidence_refs'].append(e['id'])
        if role in ('results', 'costs'):
            a[role].append({'event_ref': e['id'], 'message': e['message'], 'text': detail['summary'] if detail else semantic_result(e),
                            'cards': deepcopy(detail['cards'] if detail else e.get('cards', []))})
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

    def consume_materials(a, e):
        for summoned in a['cards']:
            target_id = summoned.get('instance_id')
            if target_id is None: continue
            method = summoned.get('summon_method')
            native_ids = set(summoned.get('material_instance_ids', []))
            candidates = []
            for prior in actions[:-1]:
                if prior['id'] in suppressed or prior['kind'] != 'material': continue
                material_event = event_by_id[prior['id']]
                material_card = next(iter(material_event.get('cards', [])), {})
                target = material_event.get('material_target')
                identified = target == target_id or (material_card.get('instance_id') in native_ids and target in (None, target_id))
                if identified: candidates.append(material_event)
            # Legacy journals can identify a procedure from a material reason AND an explicit target.
            # Card type by itself is never used: reviving a Fusion monster is not a Fusion summon.
            if method is None and 'summon_info' not in summoned:
                methods = {m.get('material_method') or material_method(m.get('reason')) for m in candidates} - {None}
                if len(methods) == 1:
                    method = next(iter(methods)); summoned['summon_method'] = method
                    summoned['summon_method_source'] = 'material_reason_and_target'
            if method not in ('连接召唤','同调召唤','超量召唤','融合召唤','仪式召唤','上级召唤'): continue
            matched = [m for m in candidates if (m.get('material_method') or material_method(m.get('reason'))) in (None, method)]
            materials = []
            for material_event in matched:
                materials.extend(deepcopy(material_event['cards']))
                attach(a, material_event, 'summon_material')
            known_ids = {c.get('instance_id') for c in materials}
            # A native material list proves material membership, even if the move event was not captured.
            for material in summoned.get('native_material_cards', []):
                if material.get('instance_id') not in known_ids:
                    materials.append(deepcopy(material)); known_ids.add(material.get('instance_id'))
            summoned['materials'] = materials
        a['summary'] = semantic_result({**e, 'cards': a['cards']})

    def consume_field_placement(a, starts):
        for start in starts:
            for previous in reversed(events[:event_indexes[start['id']]]):
                if previous['message'] in (40, 74, 61, 63, 65): break
                if previous['message'] != 50 or previous.get('cost'): continue
                if not previous.get('cards') or not any(same_card(previous['cards'][0], c) for c in start['cards']): continue
                destination = previous.get('destination', {})
                if destination.get('location') not in (4, 8) or (previous.get('reason') or 0) & 8: break
                if not any(c.get('location') == destination['location'] and c.get('sequence') == destination.get('sequence') for c in start['cards']): break
                attach(a, previous, 'summon_placement')
                for c in a['cards']:
                    if same_card(c, previous['cards'][0]): c['summon_origin'] = deepcopy(previous['origin'])
                # A summon performed during effect resolution may have had its placement
                # attached to that effect already. Replace it with the confirmed summon.
                for parent in actions:
                    parent['results'] = [r for r in parent['results'] if r['event_ref'] != previous['id']]
                break

    event_indexes = {e['id']: i for i, e in enumerate(events)}

    for index, e in enumerate(events):
        msg = e['message']
        if msg in (11, 40, 41): preparation_start = index
        if msg == 70:
            c = e['cards'][0] if e.get('cards') else {}
            a = make(e, 'effect', f"在{place(c)}发动{card_names(e.get('cards', [])) or '未知卡牌'}的效果")
            a.update(activation_ref=e['id'], chain_group=chain_group, chain_link=e.get('chain'), status='pending',
                     engine_effect=deepcopy(e.get('engine_effect')))
            clause = effect_clause(e, catalog)
            a.update(effect_text=clause['full_text'], effect_number=clause['number'], effect_count=clause['count'],
                     selected_effect_text=clause['text'], effect_text_source=clause['source'],
                     effect_script_reference=clause.get('script_reference'))
            suffix = CIRCLED[clause['number'] - 1] if clause['number'] and clause['count'] > 1 else ''
            if clause['count'] > 1 and clause['number'] is None: suffix = '（编号未知）'
            a['heading'] = f"在{place(c)}发动{card_names(e.get('cards', [])) or '未知卡牌'}的效果{suffix}："
            a['effect_quote'] = clause['text']
            if suffix and clause['text']:
                a['effect_quote'] = re.sub(r'^[' + CIRCLED + r']\s*[:：]\s*', '', clause['text'])
            if clause.get('script_reference') == 'c8240199.thop':
                trigger = next((x for x in reversed(events[:index]) if x['message'] == 61 and any(same_card(c, target) for target in x.get('cards', []))), None)
                if trigger: a.update(trigger_ref=trigger['id'], trigger_summary='这张卡通常召唤成功后发动')
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
        if e.get('cost') and e.get('cause'):
            matches = [a for a in links.values() if a['status'] == 'pending' and cause_matches(a, e)]
            if len(matches) == 1:
                attach(matches[0], e, 'costs'); continue
        if msg in (30, 42) and resolving and resolving['status'] == 'pending':
            resolving['revealed_cards'].extend(deepcopy(e.get('cards', [])))
            attach(resolving, e, 'results'); continue
        if msg in NOISE:
            suppressed[e['id']] = 'protocol'
            continue
        if msg == 90 and (e['id'] == report.get('initial_hand_ref') or e.get('draw_kind') == 'rule'):
            suppressed[e['id']] = 'initial_or_rule_draw'; continue
        if msg == 50:
            origin, dest, reason = e.get('origin', {}), e.get('destination', {}), e.get('reason')
            if e.get('deck_operation') == 'position_refresh':
                if resolving: attach(resolving, e, 'deck_order_evidence')
                else: suppressed[e['id']] = 'deck_order_evidence'
                continue
            # The core explicitly sends resolved normal spells/traps with REASON_RULE (0x400).
            # Effect destruction, costs, redirects, unrelated cards and unknown reasons remain visible.
            if origin.get('location') == 8 and dest.get('location') == 16 and reason == REASON_RULE:
                c = e['cards'][0] if e.get('cards') else {}
                definition = catalog.get(str(c.get('code')), {})
                type_flags = definition.get('type', 0)
                candidates = [a for a in links.values() if a['status'] == 'resolved' and a['cards'] and same_card(c, a['cards'][0])]
                if candidates and type_flags & 6 and not type_flags & (0x20000 | 0x40000 | 0x80000 | 0x1000000):
                    attach(candidates[-1], e, 'rule_cleanup'); continue
            if (reason or 0) & 8 and not e.get('cost'):
                make(e, 'material'); continue
        if msg in (60, 62, 64):
            pending_summons.setdefault(msg + 1, []).append(e)
            continue
        if msg == 54:
            a = make(e, 'set')
            consume_preparation(a, e)
            consume_field_placement(a, [e])
            if resolving and resolving['status'] == 'pending' and cause_matches(resolving, e):
                attach(resolving, e, 'results', a)
                for source in a['evidence_refs']:
                    if source not in resolving['evidence_refs']: resolving['evidence_refs'].append(source)
            continue
        if msg in (61, 63, 65):
            candidates = pending_summons.pop(msg, [])
            a = make(e, 'summon')
            for started in candidates: attach(a, started, 'summon_begin')
            consume_preparation(a, e)
            consume_field_placement(a, candidates)
            consume_materials(a, e)
            if resolving and resolving['status'] == 'pending' and cause_matches(resolving, e):
                attach(resolving, e, 'results', a)
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
    def execution_steps(a):
        steps = []
        for role in ('costs', 'results'):
            group = None
            for item in sorted(a[role], key=lambda i: event_indexes[i['event_ref']]):
                source = event_by_id[item['event_ref']]
                origin, dest = source.get('origin', {}), source.get('destination', {})
                mode = source.get('deck_operation')
                key = None
                if source['message'] == 50 and dest.get('location') == 32:
                    key = (role, 'banish', origin.get('controller'), origin.get('location'), dest.get('controller'), dest.get('position'))
                elif source['message'] == 50 and mode in ('move_to_bottom', 'move_to_top', 'reorder'):
                    key = (role, mode, origin.get('controller'))
                if key is not None and group and group.get('_key') == key:
                    group['event_refs'].append(item['event_ref']); group['cards'].extend(deepcopy(item['cards']))
                else:
                    group = {**deepcopy(item), 'role': 'cost' if role == 'costs' else 'result', 'event_refs': [item['event_ref']], '_key': key}
                    steps.append(group)
        for step in steps:
            key = step.pop('_key')
            if not key: continue
            source = event_by_id[step['event_refs'][0]]
            count = len(step['cards'])
            if key[1] == 'banish':
                dest = source['destination']; pos = dest.get('position', 0)
                facing = '里侧' if pos & 10 and not pos & 5 else '表侧' if pos & 5 and not pos & 10 else ''
                step['text'] = f"从{place(source['origin'])}将 {count} 张卡{facing}除外：{card_names(step['cards'])}"
            else:
                # Repeated insertion at index 0 leaves the last moved card at the very bottom.
                # List the final group from its upper end towards the bottom.
                names = card_names(step['cards'])
                revealed = {c.get('instance_id') for c in a['revealed_cards']} - {None}
                selected = {c.get('instance_id') for r in a['results'] for c in r['cards']
                            if event_by_id[r['event_ref']].get('destination', {}).get('location') == 2} - {None}
                returned = {c.get('instance_id') for c in step['cards']} - {None}
                remaining = bool(revealed and selected and returned == revealed - selected and len(returned) == count)
                if key[1] == 'move_to_bottom':
                    step['text'] = f"将{'剩余 ' if remaining else ''}{count} 张卡按所选顺序放回我方卡组底部：{names}"
                elif key[1] == 'move_to_top': step['text'] = f"将 {count} 张卡按所选顺序放回我方卡组顶部：{names}"
                else: step['text'] = f"调整我方卡组中 {count} 张卡的顺序：{names}"
        return steps

    result = [a for a in actions if a['id'] not in suppressed]
    for a in result:
        if a['kind'] != 'effect': continue
        a['execution'] = execution_steps(a)
        a['observed_summary'] = ' → '.join(step['text'] for step in a['execution'])
        if a['targets']: a['observed_targets'] = '对象：' + card_names(a['targets'])
        a['summary'] = a['heading'] + (a['effect_quote'] or '效果编号或对应文本未确认，展开可查看完整卡片文本。')
        a['status_label'] = None
        if a['status'] in ('negated', 'disabled'):
            a['status_label'] = '发动被无效' if a['status'] == 'negated' else '效果被无效'
        elif a['status'] == 'pending':
            a['status_label'] = '尚未确认结算完成'
        elif not a['results']:
            a['status_label'] = '未识别出可描述的实际结果'
        a['association'] = '核心原因效果与连锁结算区间' if a.get('engine_effect') else '连锁编号与结算区间（旧记录无原因效果标识）'
    order = {e['id']: i for i, e in enumerate(events)}
    for a in result: a['evidence_refs'].sort(key=order.get)
    result.sort(key=lambda a: order[a['id']])
    return result
