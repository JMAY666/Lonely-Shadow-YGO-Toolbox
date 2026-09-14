"""Opening constraints and a versioned, local opponent configuration."""
from collections import Counter
import secrets


OPPONENT = {
    'id': 'basic-ash-v1', 'name': '基础干扰对手',
    'description': '基础配置：3 张灰流丽、37 张魔物狩人，可更换或编辑卡组及起手。AI 沿用内核简单策略，自己的回合优先通常召唤后结束。',
    'deck': {'main': [14558127] * 3 + [1184620] * 37, 'extra': [], 'side': []},
    'opening': [14558127] + [1184620] * 4,
}

MAX_HAND = 60  # Current free-practice main-deck limit.
MAX_LP = 2**31 - 1  # set_player_info accepts a positive int32_t.


def integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{label}请输入 {minimum}–{maximum} 的整数')
    return value


def training_settings(design):
    ai = design.get('opponent_ai', False)
    responses = design.get('opponent_responses', True)
    if type(ai) is not bool or type(responses) is not bool: raise ValueError('对手 AI 设置无效')
    order = design.get('turn_order', 'first')
    if order not in ('first', 'second'): raise ValueError('请选择玩家先手或后手')
    timer = design.get('timer', {'mode': 'off', 'seconds': 0})
    if not isinstance(timer, dict) or timer.get('mode') not in ('off', 'up', 'down'):
        raise ValueError('请选择关闭、正计时或倒计时')
    seconds = integer(timer.get('seconds', 0), '计时时长（秒）', 1 if timer['mode'] == 'down' else 0, MAX_LP)
    return {'opponent_ai': ai, 'opponent_responses': responses, 'turn_order': order,
            'player_lp': integer(design.get('player_lp', 8000), '玩家初始 LP', 1, MAX_LP),
            'opponent_lp': integer(design.get('opponent_lp', 8000), '对手初始 LP', 1, MAX_LP),
            'timer': {'mode': timer['mode'], 'seconds': seconds}}


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
    count = integer(conditions.get('hand_count', 5), '起手数量', 1, MAX_HAND)
    if count > len(main): raise ValueError(f'主卡组只有 {len(main)} 张，无法提供 {count} 张起手；额外和副卡组不参与抽取')
    if not isinstance(slots, list) or len(slots) > MAX_HAND: raise ValueError('起手槽位无效')
    if any(c is not None for c in slots[count:]):
        raise ValueError(f'起手数量已设为 {count} 张，但超出数量的槽位仍有指定卡牌，请移除或增加起手数量')
    slots = slots[:count] + [None] * max(0, count - len(slots))
    if not isinstance(banned, list) or len(banned) > 60: raise ValueError('起手禁用列表无效')
    counts = Counter(main)
    for code in [c for c in slots if c is not None] + banned:
        if type(code) is not int or code not in counts: raise ValueError('只能选择当前主卡组内的卡牌')
    if any(type(code) is not int for code in banned): raise ValueError('起手禁用列表无效')
    required = Counter(c for c in slots if c is not None)
    for code, copies in required.items():
        if copies > counts[code]: raise ValueError(f'卡牌 {code} 只含 {counts[code]} 张，不能指定 {copies} 张')
        if code in banned: raise ValueError(f'卡牌 {code} 同时被指定和禁用，请先取消其中一个条件')
    eligible = sum(count - required[code] for code, count in counts.items() if code not in banned)
    missing = count - sum(required.values())
    if eligible < missing:
        raise ValueError(f'扣除指定副本并排除禁用卡后，只剩 {eligible} 张可抽取，还需要 {missing} 张，无法组成 {count} 张起手')
    return {'hand_count': count, 'slots': slots[:], 'banned': list(dict.fromkeys(banned))}


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
