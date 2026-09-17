"""Opening constraints and a versioned, local opponent configuration."""
import secrets
from opening_conditions import prepare, assignment


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


def validate_conditions(main, conditions, catalog=None):
    result = prepare(main, conditions, catalog)
    if not result['valid']: raise ValueError('；'.join(result['errors']))
    return result['conditions']


def draw_opening(main, conditions, rng=None, catalog=None):
    result = prepare(main, conditions, catalog)
    if not result['valid']: raise ValueError('；'.join(result['errors']))
    rng = rng or secrets.SystemRandom()
    indices = assignment(result['candidates'], rng=rng)
    hand = [main[i] for i in indices]
    remaining = main[:]
    for code in hand: remaining.remove(code)
    rng.shuffle(remaining)  # Banned cards remain here and work normally after the opening.
    return hand, remaining
