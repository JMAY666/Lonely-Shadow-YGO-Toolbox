"""Versioned opening predicates and matching of physical main-deck copies.

Conditions describe the initial deal only. They never assert route equivalence.
No evaluator uses free text, card names, cached candidate lists or user labels.
"""
from collections import Counter
from copy import deepcopy
from plan_tags import matches_set


KINDS = {'normal': (0x10, '通常'), 'effect': (0x20, '效果'), 'ritual': (0x80, '仪式'),
         'fusion': (0x40, '融合'), 'synchro': (0x2000, '同调'), 'xyz': (0x800000, '超量'),
         'pendulum': (0x1000000, '灵摆'), 'link': (0x4000000, '连接'), 'tuner': (0x1000, '调整'),
         'non_tuner': (0, '非调整'), 'spirit': (0x200, '灵魂'), 'union': (0x400, '同盟'),
         'gemini': (0x800, '二重'), 'flip': (0x200000, '反转'), 'toon': (0x400000, '卡通')}
ATTRIBUTES = dict(zip([1, 2, 4, 8, 16, 32, 64], ['地', '水', '炎', '风', '光', '暗', '神']))
RACES = dict(zip([1 << i for i in range(26)], ['战士', '魔法师', '天使', '恶魔', '不死', '机械', '水',
    '炎', '岩石', '鸟兽', '植物', '昆虫', '雷', '龙', '兽', '兽战士', '恐龙', '鱼', '海龙',
    '爬虫类', '念动力', '幻神兽', '创造神', '幻龙', '电子界', '幻想魔']))
LABELS = {'category': '卡牌类别', 'monster_kind': '怪兽种类', 'level': '等级', 'rank': '阶级',
          'link': '连接值', 'attribute': '属性', 'race': '种族', 'code': '指定卡牌', 'setcode': '数据库系列编号'}
OPTIONS = {'category': {'monster': '怪兽', 'spell': '魔法', 'trap': '陷阱'},
           'monster_kind': {k: v[1] for k, v in KINDS.items()}, 'attribute': ATTRIBUTES, 'race': RACES}
NUMERIC = ('level', 'rank', 'link')


def schema():
    return {'version': 1, 'fields': {key: {'label': label, 'numeric': key in NUMERIC,
            'options': [{'value': value, 'label': text} for value, text in OPTIONS.get(key, {}).items()]}
            for key, label in LABELS.items()}}


def is_condition(value):
    return isinstance(value, dict) and value.get('kind') == 'condition'


def has_conditions(conditions):
    return isinstance(conditions, dict) and any(isinstance(v, dict)
        for key in ('slots', 'banned') for v in conditions.get(key, []) or [])


def normalize_card(value):
    if not is_condition(value) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('条件牌版本或格式不支持，请使用兼容版本；不能将文字备注当作可执行规则')
    if set(value) - {'kind', 'version', 'rule'}: raise ValueError('条件牌包含不支持的字段')
    budget = [0]

    def walk(node, depth=0):
        budget[0] += 1
        if depth > 6 or budget[0] > 80: raise ValueError('条件最多嵌套 6 层、合计 80 项')
        if not isinstance(node, dict): raise ValueError('条件组合格式无效')
        op = node.get('op')
        if op in ('all', 'any', 'not'):
            items = node.get('items')
            if set(node) != {'op', 'items'} or not isinstance(items, list) or not 1 <= len(items) <= 30 or (op == 'not' and len(items) != 1):
                raise ValueError('且／或组合需要 1–30 项；排除组合必须包含 1 项')
            return {'op': op, 'items': [walk(child, depth + 1) for child in items]}
        field = node.get('field')
        if field not in LABELS: raise ValueError('不支持此条件字段，文字、效果与费用不能自动作为起手属性判断')
        if field in NUMERIC:
            if op not in ('eq', 'gte', 'lte', 'between'): raise ValueError('数值条件仅支持等于、上下限和范围')
            keys = ('min', 'max') if op == 'between' else ('value',)
            if set(node) != {'field', 'op', *keys}: raise ValueError('数值条件格式无效')
            if any(type(node[k]) is not int or not 0 <= node[k] <= 255 for k in keys):
                raise ValueError('等级、阶级和连接值请输入 0–255 的整数')
            if op == 'between' and node['min'] > node['max']: raise ValueError('范围下限不能大于上限')
            return deepcopy(node)
        values = node.get('values')
        if op not in ('in', 'not_in') or set(node) != {'field', 'op', 'values'} or not isinstance(values, list) or not 1 <= len(values) <= 100:
            raise ValueError('多选条件需要包含或排除至少一个选项（最多 100 项）')
        for item in values:
            if field in ('category', 'monster_kind'):
                valid = isinstance(item, str) and item in OPTIONS[field]
            elif field in OPTIONS:
                valid = type(item) is int and item in OPTIONS[field]
            else:
                valid = type(item) is int and 0 < item < (65536 if field == 'setcode' else 2**32)
            if not valid: raise ValueError(f'{LABELS[field]}含有不支持的选项')
        return {'field': field, 'op': op, 'values': list(dict.fromkeys(values))}

    return {'kind': 'condition', 'version': 1, 'rule': walk(value.get('rule'))}


def evaluate(node, code, card):
    """Three-valued logic: a missing/inapplicable attribute stays unknown under NOT."""
    op = node['op']
    if op in ('all', 'any', 'not'):
        results = [evaluate(child, code, card) for child in node['items']]
        if op == 'not': return None if results[0] is None else not results[0]
        if op == 'all': return False if False in results else None if None in results else True
        return True if True in results else None if None in results else False
    field = node['field']
    flags = card.get('type')
    if field == 'code': value = code
    elif field == 'setcode':
        value = card.get('setcode')
        if not isinstance(value, (int, str)) or isinstance(value, bool): return None
        try: int(value)
        except ValueError: return None
    else:
        if type(flags) is not int: return None
        if field == 'category': value = [key for key, mask in [('monster', 1), ('spell', 2), ('trap', 4)] if flags & mask]
        else:
            if not flags & 1: return None
            if field in NUMERIC:
                if field == 'level' and flags & (0x800000 | 0x4000000): return None
                if field == 'rank' and not flags & 0x800000: return None
                if field == 'link' and not flags & 0x4000000: return None
                value = card.get('level')
                if type(value) is not int or value < 0: return None
                value &= 255
            elif field == 'monster_kind': value = [k for k, (mask, _) in KINDS.items() if flags & mask or k == 'non_tuner' and not flags & 0x1000]
            else:
                value = card.get(field)
                if type(value) is not int or value <= 0: return None
    if op == 'eq': return value == node['value']
    if op == 'gte': return value >= node['value']
    if op == 'lte': return value <= node['value']
    if op == 'between': return node['min'] <= value <= node['max']
    hit = (any(matches_set(value, target) for target in node['values']) if field == 'setcode' else
           any(v in value for v in node['values']) if isinstance(value, list) else value in node['values'])
    return hit if op == 'in' else not hit


def describe(value, catalog=None):
    catalog = catalog or {}
    if value is None: return '随机补齐'
    if type(value) is int: return catalog.get(value, catalog.get(str(value), {})).get('name', f'卡号 {value}')

    def text(node):
        op = node['op']
        if op == 'not': return '排除（' + text(node['items'][0]) + '）'
        if op in ('all', 'any'): return '（' + (' 且 ' if op == 'all' else ' 或 ').join(text(c) for c in node['items']) + '）'
        field = node['field']; label = LABELS[field]
        if op == 'between': return f"{label} {node['min']}–{node['max']}"
        if op in ('eq', 'gte', 'lte'): return f"{label} {dict(eq='=', gte='≥', lte='≤')[op]} {node['value']}"
        values = [describe(v, catalog) if field == 'code' else OPTIONS.get(field, {}).get(v, str(v)) for v in node['values']]
        return ('排除' if op == 'not_in' else '') + label + '：' + ' / '.join(values)

    rule = value['rule']
    # A common readable summary; arbitrary trees retain all parentheses.
    if rule.get('op') == 'all' and len(rule['items']) == 2:
        level = next((n for n in rule['items'] if n.get('field') == 'level' and n.get('op') == 'eq'), None)
        tuner = next((n for n in rule['items'] if n == {'field': 'monster_kind', 'op': 'in', 'values': ['tuner']}), None)
        if level and tuner: return f"任意等级 {level['value']} 调整"
    return '任意满足 ' + text(rule)


def missing_data(node, code, card):
    """Inapplicable (a spell has no level) is not missing catalog metadata."""
    if evaluate(node, code, card) is not None: return False
    if node['op'] in ('all', 'any', 'not'):
        return any(missing_data(child, code, card) for child in node['items'])
    field = node['field']
    if field == 'setcode': return True
    if type(card.get('type')) is not int: return True
    flags = card['type']
    if not flags & 1: return False
    if field == 'level' and flags & (0x800000 | 0x4000000): return False
    if field == 'rank' and not flags & 0x800000: return False
    if field == 'link' and not flags & 0x4000000: return False
    return field in (*NUMERIC, 'attribute', 'race')


def normalize(main, conditions):
    if not isinstance(conditions, dict): raise ValueError('起手条件无效')
    count = conditions.get('hand_count', 5)
    if type(count) is not int or not 1 <= count <= 60: raise ValueError('起手数量请输入 1–60 的整数')
    if count > len(main): raise ValueError(f'主卡组只有 {len(main)} 张，无法提供 {count} 张起手；额外和副卡组不参与抽取')
    slots, banned = conditions.get('slots'), conditions.get('banned')
    if not isinstance(slots, list) or len(slots) > 60: raise ValueError('起手槽位无效')
    if any(v is not None for v in slots[count:]): raise ValueError(f'起手数量已设为 {count} 张，但超出数量的槽位仍有指定卡牌，请移除或增加起手数量')
    if not isinstance(banned, list) or len(banned) > 60: raise ValueError('起手禁用列表无效')
    def entry(value, required):
        if value is None and required: return None
        if isinstance(value, dict): return normalize_card(value)
        if type(value) is not int or value not in main: raise ValueError('只能选择当前主卡组内的卡牌；原卡牌已不在当前主卡组')
        return value
    result = {'hand_count': count, 'slots': [entry(v, True) for v in slots[:count]] + [None] * max(0, count-len(slots)), 'banned': []}
    for value in banned:
        value = entry(value, False)
        # Keep condition positions stable for editing/preview, including equal
        # predicates. Concrete legacy bans retain their original deduplication.
        if isinstance(value, dict) or value not in result['banned']: result['banned'].append(value)
    return result


def assignment(candidates, rng=None, forced=None):
    """Augmenting paths, not greedy consumption. Nodes are physical copy indices."""
    owners, matched = {}, {}
    forced = forced or {}
    for slot, copy in forced.items():
        if copy not in candidates[slot] or copy in owners: return None
        owners[copy] = slot; matched[slot] = copy
    order = [i for i in range(len(candidates)) if i not in forced]
    if rng: rng.shuffle(order)
    order.sort(key=lambda i: len(candidates[i]))
    choices = [list(pool) for pool in candidates]
    if rng:
        for pool in choices: rng.shuffle(pool)
    def augment(slot, seen):
        for copy in choices[slot]:
            if copy in seen: continue
            seen.add(copy)
            previous = owners.get(copy)
            if previous is None or previous not in forced and augment(previous, seen):
                owners[copy] = slot; matched[slot] = copy
                return True
        return False
    for slot in order:
        if not augment(slot, set()): return None
    return [matched[i] for i in range(len(candidates))]


def prepare(main, conditions, catalog=None):
    conditions = normalize(main, conditions)
    catalog = catalog or {}
    counts = Counter(main)
    def matches(value):
        if value is None: return set(counts), []
        if type(value) is int: return {value}, []
        hits, unknown = set(), []
        for code in counts:
            card = catalog.get(code, catalog.get(str(code), {}))
            result = evaluate(value['rule'], code, card)
            if result is True: hits.add(code)
            # Missing metadata is different from a known card without a level.
            if result is None and missing_data(value['rule'], code, card): unknown.append(code)
        return hits, unknown
    banned, warnings, errors, bans = set(), [], [], []
    for value in conditions['banned']:
        hits, unknown = matches(value); banned.update(hits)
        label = describe(value, catalog)
        if not hits: warnings.append(f'禁止条件「{label}」未命中当前主卡组，当前没有实际影响')
        if unknown: errors.append(f'禁止条件「{label}」缺少卡牌资料，无法可靠判断：{unknown}')
        bans.append({'summary': label, 'codes': sorted(hits), 'types': len(hits), 'copies': sum(counts[c] for c in hits)})
    required = Counter(v for v in conditions['slots'] if type(v) is int)
    for code, copies in required.items():
        if copies > counts[code]: errors.append(f'卡牌 {code} 只含 {counts[code]} 张，不能指定 {copies} 张')
        if code in banned: errors.append(f'卡牌 {code} 同时被指定和禁用，请先取消其中一个条件')
    slots, candidates = [], []
    for i, value in enumerate(conditions['slots']):
        hits, unknown = matches(value); allowed = hits - banned
        candidates.append([j for j, code in enumerate(main) if code in allowed])
        label = describe(value, catalog)
        if unknown: errors.append(f'槽位 {i+1}「{label}」缺少卡牌资料，无法可靠判断：{unknown}')
        if value is not None and not allowed:
            errors.append(f'槽位 {i+1}「{label}」' + ('候选已被禁止规则全部排除' if hits else '在当前主卡组中没有候选'))
        slots.append({'summary': label, 'codes': sorted(hits), 'allowed_codes': sorted(allowed),
                      'types': len(hits), 'copies': sum(counts[c] for c in hits),
                      'allowed_copies': sum(counts[c] for c in allowed)})
    available = sum(n for c, n in counts.items() if c not in banned) - sum(required.values())
    missing = conditions['hand_count'] - sum(required.values())
    if available < missing and not errors: errors.append(f'扣除指定副本并排除禁用卡后，只剩 {max(0, available)} 张可抽取，还需要 {missing} 张，无法组成 {conditions["hand_count"]} 张起手')
    chosen = assignment(candidates)
    if chosen is None and not errors:
        conflict = [i for i, v in enumerate(conditions['slots']) if v is not None]
        for i in conflict[:]:
            trial = [j for j in conflict if j != i]
            if assignment([candidates[j] for j in trial]) is None: conflict = trial
        constrained = '、'.join(f'{i+1}「{slots[i]["summary"]}」' for i in conflict)
        copies = len({c for i in conflict for c in candidates[i]})
        errors.append(f'槽位 {constrained} 存在交叉冲突：合计仅 {copies} 张可用实体副本，却需要 {len(conflict)} 张；同一实体副本不能重复使用')
    return {'conditions': conditions, 'valid': not errors, 'errors': errors, 'warnings': warnings,
            'slots': slots, 'banned': bans, 'candidates': candidates, 'assignment': chosen}


def preview(main, conditions, catalog, focus=None):
    try: result = prepare(main, conditions, catalog)
    except ValueError as exc: return {'valid': False, 'errors': [str(exc)], 'warnings': [], 'slots': [], 'banned': []}
    if isinstance(focus, dict) and focus.get('kind') in ('slots', 'banned') and type(focus.get('index')) is int:
        kind, index = focus['kind'], focus['index']
        if 0 <= index < len(result[kind]):
            detail = deepcopy(result[kind][index]); rows = []
            counts = Counter(main)
            for code in detail['codes']:
                available = 0
                if kind == 'slots' and result['valid'] and code in detail['allowed_codes']:
                    copies = [j for j, c in enumerate(main) if c == code]
                    others = [pool for i, pool in enumerate(result['candidates']) if i != index and result['conditions']['slots'][i] is not None]
                    # Maximum copies left after satisfying the other required slots.
                    # Each card's maximum is independent; these maxima are not additive.
                    lo, hi = 0, len(copies)
                    while lo < hi:
                        mid = (lo + hi + 1) // 2; reserve = set(copies[:mid])
                        if assignment([[c for c in pool if c not in reserve] for pool in others]) is not None: lo = mid
                        else: hi = mid - 1
                    available = lo
                card = catalog.get(code, catalog.get(str(code), {}))
                reason = ('整副初始手牌禁止，后续仍可抽取' if kind == 'banned' else
                          '被禁止规则排除' if code not in detail['allowed_codes'] else
                          '整套规则有冲突，暂不可分配' if not result['valid'] else
                          '其他槽位占用必要副本' if not available else '可填入此槽位')
                rows.append({'code': code, 'name': card.get('name', str(code)), 'count': counts[code],
                             'available_count': available, 'reason': reason})
            detail.update(cards=rows, usable_types=sum(r['available_count'] > 0 for r in rows))
            result['focus'] = detail
    result.pop('candidates'); result.pop('assignment')
    return result


def match_hand(hand, conditions, catalog=None):
    """Match requirements against a concrete hand (never count a copy twice).

    The caller validates membership in its current deck. Training's random
    filler count is not an additional route requirement; recorded costs/resources
    are checked separately. Every actual card still obeys the opening bans.
    """
    if not isinstance(conditions, dict): return False, '缺少起手规则'
    normalized = deepcopy(conditions)
    count, slots = conditions.get('hand_count', 5), conditions.get('slots')
    if type(count) is not int or not 1 <= count <= 60: raise ValueError('起手数量请输入 1–60 的整数')
    if not isinstance(slots, list) or len(slots) > 60: raise ValueError('起手槽位无效')
    if any(v is not None for v in slots[count:]): raise ValueError('起手规则包含超出数量的指定槽位')
    normalized['slots'] = [v for v in slots[:count] if v is not None]
    if len(hand) < len(normalized['slots']): return False, f'需要 {len(normalized["slots"])} 张指定／条件牌，实际手牌只有 {len(hand)} 张'
    # A banned concrete card absent from the hand is normal, unlike a design
    # that refers to a card removed from its deck.
    banned = normalized.get('banned', [])
    if any(type(v) is int and v in hand for v in banned): return False, '起手包含手动设置的禁止上手卡牌'
    normalized['banned'] = [v for v in banned if type(v) is not int]
    normalized['hand_count'] = len(hand)
    result = prepare(hand, normalized, catalog)
    banned_codes = {c for row in result['banned'] for c in row['codes']}
    if banned_codes.intersection(hand): return False, '起手包含禁止条件命中的卡牌'
    return result['valid'], '；'.join(result['errors'])
