"""Opening constraints and a versioned, local opponent configuration."""
from collections import Counter
import secrets


OPPONENT = {
    'id': 'basic-ash-v1', 'name': '基础干扰对手',
    'description': '40 张：3 张灰流丽、37 张魔物狩人。固定起手为 1 张灰流丽和 4 张魔物狩人；按内核合法时点响应，自己的回合优先通常召唤后结束。无复杂策略编辑。',
    'deck': {'main': [14558127] * 3 + [1184620] * 37, 'extra': [], 'side': []},
    'opening': [14558127] + [1184620] * 4,
}


def plan_text(body):
    name, notes = body.get('name', ''), body.get('notes', '')
    if not isinstance(name, str) or not name.strip():
        raise ValueError('请先填写方案名称，不能只有空格')
    if len(name.strip()) > 80: raise ValueError('方案名称最多 80 个字符')
    if not isinstance(notes, str) or len(notes) > 4000: raise ValueError('备注最多 4000 个字符')
    return name.strip(), notes


def validate_conditions(main, conditions):
    if not isinstance(conditions, dict): raise ValueError('起手条件无效')
    slots, banned = conditions.get('slots'), conditions.get('banned')
    if not isinstance(slots, list) or len(slots) != 5: raise ValueError('起手必须有 5 个槽位')
    if not isinstance(banned, list) or len(banned) > 60: raise ValueError('起手禁用列表无效')
    counts = Counter(main)
    for code in [c for c in slots if c is not None] + banned:
        if type(code) is not int or code not in counts: raise ValueError('只能选择当前主卡组内的卡牌')
    if any(type(code) is not int for code in banned): raise ValueError('起手禁用列表无效')
    required = Counter(c for c in slots if c is not None)
    for code, count in required.items():
        if count > counts[code]: raise ValueError(f'卡牌 {code} 只含 {counts[code]} 张，不能指定 {count} 张')
        if code in banned: raise ValueError(f'卡牌 {code} 同时被指定和禁用，请先取消其中一个条件')
    eligible = sum(count - required[code] for code, count in counts.items() if code not in banned)
    missing = 5 - sum(required.values())
    if eligible < missing:
        raise ValueError(f'扣除指定副本并排除禁用卡后，只剩 {eligible} 张可抽取，还需要 {missing} 张，无法组成 5 张起手')
    return {'slots': slots[:], 'banned': list(dict.fromkeys(banned))}


def draw_opening(main, conditions, rng=None):
    conditions = validate_conditions(main, conditions)
    rng = rng or secrets.SystemRandom()
    remaining = main[:]
    for code in conditions['slots']:
        if code is not None: remaining.remove(code)
    eligible = [c for c in remaining if c not in conditions['banned']]
    extra = iter(rng.sample(eligible, conditions['slots'].count(None)))
    hand = [code if code is not None else next(extra) for code in conditions['slots']]
    remaining = main[:]
    for code in hand: remaining.remove(code)
    rng.shuffle(remaining)  # Banned cards remain here and work normally after the opening.
    return hand, remaining
