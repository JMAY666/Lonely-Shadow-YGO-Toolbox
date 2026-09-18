"""Comparable route preferences and private, physical-card resource accounting."""
from copy import deepcopy

PREFERENCES = ('cheapest', 'largest', 'shortest', 'balanced')
DEFAULT_PREFERENCE = 'largest'


def advance_resources(before, after, previous=None):
    """Count each starting resource once when it leaves its original zone.

    Native instance IDs remain internal. Draws cannot cancel a spent opening
    card, recovered cards are not charged twice, and new tokens are not costs.
    A new search starts a new ledger, so confirmed history is not charged again.
    """
    if previous is None:
        own = [card for card in before.get('cards', []) if card.get('controller') == 0]
        ledger = {'origins': {str(card['instance_id']): card['location'] for card in own if card.get('instance_id') is not None},
                  'used': [], 'complete': all(card.get('instance_id') is not None for card in own)}
    else:
        ledger = deepcopy(previous)
    current = {str(card['instance_id']): card for card in after.get('cards', []) if card.get('instance_id') is not None}
    used = set(ledger['used'])
    for identifier, origin in ledger['origins'].items():
        card = current.get(identifier)
        if not card or card.get('controller') != 0 or card.get('location') != origin:
            used.add(identifier)
    ledger['used'] = sorted(used)
    return ledger


def resource_cost(ledger):
    values = {'hand': 0, 'main': 0, 'extra': 0, 'other': 0}
    for identifier in ledger['used']:
        key = {2: 'hand', 1: 'main', 64: 'extra'}.get(ledger['origins'][identifier], 'other')
        values[key] += 1
    return {**values, 'total': sum(values.values()), 'status': 'complete' if ledger['complete'] else 'unassessed',
            'basis': '从当前计算起点按实体去重统计已投入卡牌；手牌优先，其次主卡组与额外卡组合计，再比较其他区域。回收不冲销已投入卡牌，跨区复用不重复计数；生命值与效果次数不折算成卡牌张数。'}


def cost_key(candidate):
    cost = candidate.get('resource_cost') or {}
    return (cost.get('status') != 'complete', cost.get('hand', 0),
            cost.get('main', 0) + cost.get('extra', 0), cost.get('other', 0))
