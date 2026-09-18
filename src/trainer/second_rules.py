"""Small, sourced effect catalogue for conditional hints, not a rule engine."""
from copy import deepcopy

ASH, IMPERM, OGRE = 14558127, 10045474, 59438930
ALUBER, MOYE, FUSION, FISSURE = 62962630, 20001443, 44362883, 81674782
REVISION = 'bo1-second-hints-1'
BASE = 'https://www.db.yugioh-card.com/yugiohdb/'


def source(cid):
    return BASE + f'faq_search.action?cid={cid}&ope=4&request_locale=ja'


EFFECTS = {
    'aluber.search': {'code': ALUBER, 'number': 1, 'label': '① 召唤／特殊召唤成功后检索烙印魔法／陷阱',
        'location': 4, 'attributes': ['search'], 'limit': 'use_name_turn', 'group': 'aluber.1or2',
        'limit_text': '①②每回合只能使用其中一个一次', 'source': source(16195), 'case': 'aluber',
        'gain': '一次烙印魔法／陷阱检索', 'deck_gain': 1,
        'candidates': ['烙印轴', '带烙印轴的混合构筑'], 'candidate_basis': '仅来自已公开阿鲁伯，尚未确认完整卡组'},
    'aluber.revive': {'code': ALUBER, 'number': 2, 'label': '② 墓地复活并无效怪兽',
        'location': 16, 'attributes': ['revive', 'negate_effect'], 'limit': 'use_name_turn', 'group': 'aluber.1or2',
        'limit_text': '与①共用每回合二选一的使用限制', 'source': source(16195), 'case': None},
    'moye.token': {'code': MOYE, 'number': 1, 'label': '① 展示手牌并生成相剑衍生物',
        'location': 4, 'attributes': ['create_token'], 'limit': 'use_name_turn', 'group': 'moye.1',
        'limit_text': '①每回合只能使用一次；与②分别计数', 'source': source(16489), 'case': 'moye',
        'gain': '一只相剑衍生物', 'deck_gain': 0,
        'candidates': ['相剑轴', '带相剑轴的混合构筑'], 'candidate_basis': '仅来自已公开莫邪，尚未确认完整卡组'},
    'moye.draw': {'code': MOYE, 'number': 2, 'label': '② 作为同调素材送墓后抽牌',
        'location': 16, 'attributes': ['draw'], 'limit': 'use_name_turn', 'group': 'moye.2',
        'limit_text': '②每回合只能使用一次；不是①生成衍生物', 'source': source(16489), 'case': None},
    'fusion.activate': {'code': FUSION, 'number': 1, 'label': '① 烙印融合的卡片发动',
        'location': 8, 'attributes': ['fusion_summon', 'deck_materials'], 'limit': 'activate_name_turn', 'group': 'fusion.card',
        'limit_text': '每回合只能发动一张；效果无效仍计发动，发动无效不计本次发动',
        'source': source(17066), 'case': 'fusion', 'gain': '本次融合及融合素材处理', 'deck_gain': None,
        'candidates': ['烙印轴', '带烙印融合的混合构筑'], 'candidate_basis': '公开烙印融合不等于已知所有后续资源'},
    'ash.negate': {'code': ASH, 'number': 1, 'label': '① 无效包含指定牌组处理的效果',
        'location': 2, 'attributes': ['negate_effect'], 'limit': 'use_name_turn', 'group': 'ash.1',
        'limit_text': '同名每回合只能使用一次，发动或效果被无效也已使用', 'source': source(12950),
        'case': None, 'responder': 'ash', 'cost': '丢弃这张手牌', 'targeted': False},
    'imperm.negate': {'code': IMPERM, 'number': 1, 'label': '① 无效对手表侧怪兽的效果',
        'location': 2, 'attributes': ['negate_effect'], 'limit': 'none', 'group': 'imperm.1',
        'limit_text': '卡文没有同名每回合一次；手牌发动需我方场上没有卡，且不适用盖放发动的列无效',
        'source': source(13631), 'case': None, 'responder': 'imperm', 'cost': '无额外费用；投入这张陷阱', 'targeted': True},
    'ogre.destroy': {'code': OGRE, 'number': 1, 'label': '① 破坏场上发动效果的卡',
        'location': 2, 'attributes': ['destroy'], 'limit': 'use_name_turn', 'group': 'ogre.1',
        'limit_text': '同名每回合只能使用一次；必须将自身送墓，不是单纯丢弃',
        'source': source(11708), 'case': None, 'responder': 'ogre', 'cost': '将这张手牌送去墓地', 'targeted': False},
}
RESPONDERS = {ASH: 'ash.negate', IMPERM: 'imperm.negate', OGRE: 'ogre.destroy'}
PROTECTIONS = {'target': '不能成为效果对象', 'destroy': '不会被效果破坏',
               'monster': '不受怪兽效果影响', 'trap': '不受陷阱效果影响',
               'activation': '发动不会被无效', 'effect': '效果不会被无效', 'already_negated': '已处于效果无效状态'}
ATTRIBUTES = {'search': '检索', 'create_token': '生成衍生物', 'draw': '抽牌', 'revive': '复活',
              'negate_effect': '效果无效', 'negate_activation': '发动无效', 'destroy': '破坏',
              'fusion_summon': '融合召唤', 'deck_materials': '使用牌组素材'}
ROLE_LABELS = {'free': '已核对无必须保留用途', 'key': '需要保留作起动／素材／费用', 'unknown': '起动点影响未核对'}


def options(catalog):
    return {'revision': REVISION, 'effects': [dict(id=key, **deepcopy(value),
                card_name=catalog.get(value['code'], {}).get('name', str(value['code']))) for key, value in EFFECTS.items()],
            'responders': list(RESPONDERS), 'protections': PROTECTIONS, 'attributes': ATTRIBUTES, 'roles': ROLE_LABELS}


def effect_for(code, key):
    value = EFFECTS.get(key)
    if not value or value['code'] != code:
        raise ValueError('卡片与具体效果不匹配；不能把同一卡的所有效果混在一起')
    return value


def usage_key(effect, player, instance):
    return f'{player}:{effect["group"]}'


def usage_status(state, effect, player, instance):
    if effect['limit'] == 'none':
        return 'not_limited'
    key = usage_key(effect, player, instance)
    value = (state.get('effect_counts') or {}).get(key)
    if not value:
        return 'unknown'
    if value.get('turn') != state['turn']:
        return 'unknown'  # A missed interval is not evidence of an unused effect.
    return value['status']


def set_usage(state, effect, player, instance, status, outcome=None, action_id=None):
    if effect['limit'] == 'none':
        return
    if outcome == 'activation_negated' and effect['limit'] == 'activate_name_turn':
        status = 'unused'
    row = {'turn': state['turn'], 'status': status, 'source': 'user_confirmed', 'outcome': outcome, 'action_id': action_id}
    state.setdefault('effect_counts', {})[usage_key(effect, player, instance)] = row
