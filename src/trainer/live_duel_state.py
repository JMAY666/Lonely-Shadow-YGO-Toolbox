"""Versioned observed facts. Recommendations never mutate the physical ledger."""
from collections import Counter
from copy import deepcopy
import uuid

PHASES = {'draw': '抽牌阶段', 'standby': '准备阶段', 'main1': '主要阶段 1',
          'battle': '战斗阶段', 'main2': '主要阶段 2', 'end': '结束阶段', 'unknown': '阶段待确认'}
ZONES = {'hand': '手牌', 'monster': '怪兽区', 'spell': '魔陷区', 'grave': '墓地',
         'banished': '除外', 'extra': '额外卡组', 'deck': '卡组'}
GOALS = {'steady': '稳健突破', 'win': '争取本回合取胜', 'followup': '保留续航'}
OUTCOMES = {'resolved', 'negated_activation', 'negated_effect', 'no_result'}


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(label + '无效')
    return value


def text(value, maximum=400):
    if not isinstance(value, str) or len(value) > maximum: raise ValueError('文字格式或长度无效')
    return value


def identity(): return uuid.uuid4().hex


def initial(deck, hand):
    cards = [{'id': identity(), 'code': c, 'owner': 0, 'controller': 0, 'zone': z,
              'faceup': z == 'hand', 'disabled': None, 'attack': None, 'attacks_left': None}
             for z, codes in (('hand', hand), ('extra', deck['extra'])) for c in codes]
    return {'turn': 1, 'player': 1, 'phase': 'unknown', 'lp': [8000, 8000], 'cards': cards,
            'normal_used': None, 'spell_trap_used': None, 'known': {'board': False, 'hand': True, 'usage': False, 'limits': False},
            'used': [], 'limits': [], 'window': None, 'opponent_hand': None}


def checked_cards(rows, deck, catalog):
    if not isinstance(rows, list) or len(rows) > 180: raise ValueError('当前卡片列表无效')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict): raise ValueError('卡片格式无效')
        identifier = text(row.get('id') or identity(), 64)
        if identifier in seen: raise ValueError('同一实体卡重复出现')
        seen.add(identifier)
        code = integer(row.get('code'), 0, 0x0fffffff, '卡号')
        owner = integer(row.get('owner', row.get('controller')), 0, 1, '卡片持有者')
        player = integer(row.get('controller'), 0, 1, '控制者')
        zone = row.get('zone')
        if zone not in ZONES: raise ValueError('卡片区域无效')
        if code and code not in catalog: raise ValueError('当前卡库缺少卡号 ' + str(code))
        faceup = row.get('faceup', True)
        if type(faceup) is not bool: raise ValueError('表示形式无效')
        # Unknown opposing hands/deck/extra and facedown field cards stay unknown.
        if player == 1 and (zone in ('deck', 'extra') or zone == 'hand' and row.get('revealed') is not True
                            or zone in ('monster', 'spell', 'banished') and not faceup):
            code = 0
        if player == 0 and zone == 'hand' and not code: raise ValueError('我方手牌需填入实际卡片')
        disabled = row.get('disabled')
        if disabled is not None and type(disabled) is not bool: raise ValueError('效果状态无效')
        attack = row.get('attack')
        attacks = row.get('attacks_left')
        if attack is not None: integer(attack, 0, 999999, '实际攻击力')
        if attacks is not None: integer(attacks, 0, 20, '已确认剩余攻击次数')
        level = row.get('level'); tuner = row.get('tuner')
        if level is not None: integer(level, 0, 255, '当前等级')
        if tuner is not None and type(tuner) is not bool: raise ValueError('当前调整身份无效')
        result.append({'id': identifier, 'code': code, 'owner': owner, 'controller': player,
                       'zone': zone, 'faceup': faceup, 'disabled': disabled, 'attack': attack,
                       'attacks_left': attacks, 'revealed': bool(row.get('revealed')),
                       'direct_attack_confirmed': row.get('direct_attack_confirmed') is True,
                       'level':level, 'tuner':tuner,
                       'attack_position': row.get('attack_position') is True})
    available = Counter(deck['main'] + deck['extra'])
    present = Counter(r['code'] for r in result if r['owner'] == 0 and r['code'] and not catalog[r['code']].get('type', 0) & 0x4000)
    if any(n > available[c] for c, n in present.items()): raise ValueError('我方实体卡数量超过本局构筑；控制权变化请核对原持有者')
    for player in (0, 1):
        if sum(r['controller'] == player and r['zone'] == 'monster' for r in result) > 7: raise ValueError('怪兽区数量超限')
        if sum(r['controller'] == player and r['zone'] == 'spell' for r in result) > 8: raise ValueError('魔陷区数量超限')
    return result


def snapshot(old, data, deck, catalog, rules):
    if not isinstance(data, dict): raise ValueError('局面格式无效')
    allowed = {'turn', 'player', 'phase', 'lp', 'cards', 'normal_used', 'spell_trap_used', 'known', 'opponent_hand', 'used', 'limits'}
    if set(data) - allowed: raise ValueError('不允许直接改写推导或窗口字段')
    new = deepcopy(old)
    new['turn'] = integer(data.get('turn'), old['turn'], 100000, '回合')
    new['player'] = integer(data.get('player'), 0, 1, '回合玩家')
    if data.get('phase') not in PHASES: raise ValueError('阶段无效')
    new['phase'] = data['phase']
    lp = data.get('lp')
    if not isinstance(lp, list) or len(lp) != 2: raise ValueError('LP 格式无效')
    new['lp'] = [integer(n, 0, 99999999, 'LP') for n in lp]
    new['cards'] = checked_cards(data.get('cards'), deck, catalog)
    used = data.get('normal_used')
    if used is not None: integer(used, 0, 20, '已用通常召唤次数')
    new['normal_used'] = used
    spells = data.get('spell_trap_used')
    if spells is not None: integer(spells, 0, 200, '已发动魔陷卡次数')
    new['spell_trap_used'] = spells
    known = data.get('known', {})
    if set(known) != {'board', 'hand', 'usage', 'limits'} or any(type(v) is not bool for v in known.values()):
        raise ValueError('请分别确认当前场面、手牌、已用次数和持续限制')
    new['known'] = dict(known)
    count = data.get('opponent_hand')
    if count is not None: integer(count, 0, 80, '对手手牌张数')
    new['opponent_hand'] = count
    if 'used' in data:
        if not isinstance(data['used'], list) or len(data['used']) > 200: raise ValueError('次数记录无效')
        new['used'] = []
        for row in data['used']:
            key = text(row.get('key'), 60)
            if key not in rules and not any(u.get('event') == row.get('event') and u['key'] == key for u in old['used']):
                raise ValueError('未知效果次数只能保留实际动作记录，不能自由添加规则')
            usage = {'key': key, 'player': integer(row.get('player'), 0, 1, '玩家'),
                     'turn': integer(row.get('turn'), 1, new['turn'], '使用回合'),
                     'outcome': row.get('outcome') if row.get('outcome') in OUTCOMES else 'pending'}
            if row.get('event') and any(u.get('event') == row['event'] and all(u[k] == usage[k] for k in ('key','player','turn')) for u in old['used']):
                usage['event'] = row['event']
            new['used'].append(usage)
    if 'limits' in data:
        if not isinstance(data['limits'], list) or len(data['limits']) > 40: raise ValueError('限制记录无效')
        new['limits'] = []
        for row in data['limits']:
            key = row.get('key')
            if key not in rules or not rules[key].get('locks'): raise ValueError('尚未覆盖的持续限制')
            entry = {'key': key, 'player': integer(row.get('player'), 0, 1, '玩家'),
                     'turn': integer(row.get('turn'), 1, new['turn'], '适用回合')}
            if 'named_negation' in rules[key]['locks']:
                affected = integer(row.get('affected_code'), 1, 0x0fffffff, '对应原本卡名')
                if affected not in catalog: raise ValueError('对应卡名未在卡库中找到')
                entry['affected_code'] = affected
            if row.get('event') and any(r.get('event')==row['event'] and r['key']==key for r in old['limits']): entry['event']=row['event']
            new['limits'].append(entry)
    new['window'] = None
    return new


def active_locks(state, rules, player=0):
    result = []
    for record in state['limits']:
        definition = rules.get(record['key'], {})
        if not record['turn'] <= state['turn'] <= record['turn'] + definition.get('duration', 0): continue
        if definition.get('both') or record['player'] == player:
            result.extend(definition.get('locks', []))
    return set(result)


def uses(state, key, player, rule):
    return sum(r['key'] == key and r['player'] == player and r['turn'] == state['turn']
               and not (rule.get('count_mode') == 'activation' and r['outcome'] == 'negated_activation') for r in state['used'])


def apply_event(session, body, catalog, rules, now, source='manual'):
    """A user confirms a fact, not a predicted result. Return a new transaction."""
    result = deepcopy(session); state = result['state']; operation = body.get('operation')
    event = {'id': identity(), 'operation': operation, 'at': now, 'source': source, 'turn': state['turn']}
    state['window'] = None
    if operation == 'snapshot':
        result['state'] = snapshot(state, body.get('state'), result['deck'], catalog, rules)
        result['needs_sync'] = False
        event['note'] = '人工核对当前局面；保留原始起手与先前记录'
    elif operation == 'action':
        identifier = body.get('card_id')
        card = next((c for c in state['cards'] if c['id'] == identifier), None)
        if not card or not card['code']: raise ValueError('请先在当前局面中确认动作卡片')
        kind = body.get('kind')
        if kind not in ('normal', 'special', 'activate', 'reveal', 'attack'): raise ValueError('动作类型无效')
        number = integer(body.get('effect', 0), 0, 20, '效果编号')
        event.update(card=deepcopy(card), kind=kind, effect=number, outcome='pending' if kind == 'activate' else 'resolved')
        key = f"{card['code']}:{number}"
        if kind == 'activate':
            if rules.get(key,{}).get('continuous'): raise ValueError('永续适用不记录为一次发动，请在当前场面核对效果状态')
            activation = bool(catalog[card['code']].get('type', 0) & 6 and (card['zone'] == 'hand' or body.get('card_activation') is True or number == 0))
            event['card_activation'] = activation
            if activation and card['zone'] == 'hand': card.update(zone='spell', faceup=True)
            if activation and card['controller'] == 0 and state['spell_trap_used'] is not None: state['spell_trap_used'] += 1
            state['used'].append({'key': key, 'player': card['controller'], 'turn': state['turn'], 'outcome': 'pending', 'event': event['id']})
            if rules.get(key,{}).get('lock_mode')=='activation' and rules[key].get('locks'):
                state['limits'].append({'key':key,'player':card['controller'],'turn':state['turn'],'event':event['id']})
            # Explicitly observed costs, never estimated costs from a suggestion.
            payments = body.get('costs', [])
            if not isinstance(payments, list) or len(payments) > 20: raise ValueError('费用格式无效')
            required=rules.get(key,{}).get('cost')
            if required in ('send_self','discard_self'):
                allowed={'grave'} if required=='send_self' else {'grave','banished'}
                if not any(p.get('id')==card['id'] and p.get('zone') in allowed for p in payments):
                    raise ValueError('该效果必须以自身支付送墓或丢弃费用，请核对实际费用及去向')
            paid = set()
            for payment in payments:
                item = next((c for c in state['cards'] if c['id'] == payment.get('id')), None)
                if not item or item['id'] in paid or payment.get('zone') not in ('grave', 'banished', 'deck'):
                    raise ValueError('费用卡片或去向无效')
                if item['controller'] != card['controller']: raise ValueError('不能把对方卡片记录为自己的手牌费用')
                paid.add(item['id']); item.update(zone=payment['zone'], controller=item['owner'], faceup=payment['zone'] != 'deck')
            event['costs'] = deepcopy(payments)
        elif kind in ('normal', 'special'):
            if body.get('costs'): raise ValueError('召唤涉及的解放或素材请先在当前资源中核对；本入口不推断召唤手续')
            if kind == 'normal' and (card['controller'] == 0 and card['zone'] != 'hand' or not catalog[card['code']].get('type', 0) & 1):
                raise ValueError('通常召唤需从实际手牌选择怪兽')
            card.update(zone='monster', faceup=True, attack_position=True)
            if kind == 'normal' and card['controller'] == 0 and state['normal_used'] is not None: state['normal_used'] += 1
        elif kind == 'attack':
            if card['attacks_left'] is not None:
                if card['attacks_left'] < 1: raise ValueError('所记录剩余攻击次数已为零')
                card['attacks_left'] -= 1
        event['note'] = text(body.get('note', ''))
    elif operation == 'result':
        prior = next((e for e in result['events'] if e['id'] == body.get('event_id')), None)
        if not prior or prior.get('kind') != 'activate' or prior.get('outcome') != 'pending': raise ValueError('该发动不存在或已有处理结果')
        outcome = body.get('outcome')
        if outcome not in OUTCOMES: raise ValueError('处理结果无效')
        prior['outcome'] = outcome; event.update(target=prior['id'], outcome=outcome)
        if outcome == 'negated_activation' and prior.get('card_activation') and prior['card']['controller'] == 0 and state['spell_trap_used'] is not None:
            state['spell_trap_used'] = max(0, state['spell_trap_used']-1)
        for usage in state['used']:
            if usage.get('event') == prior['id']: usage['outcome'] = outcome
        key = f"{prior['card']['code']}:{prior['effect']}"
        rule = rules.get(key, {})
        if outcome == 'negated_activation': state['limits']=[r for r in state['limits'] if r.get('event')!=prior['id']]
        if rule.get('locks') and rule.get('lock_mode')!='activation' and (outcome == 'resolved' or outcome=='no_result' and rule.get('lock_on_no_result')):
            if 'named_negation' in rule['locks']:
                state['known']['limits'] = False
                event['note'] = '请在持续限制中补充实际对应的原本卡名'
            else: state['limits'].append({'key': key, 'player': prior['card']['controller'], 'turn': prior['turn']})
        # A result can contain a complete, explicitly confirmed physical snapshot.
        if body.get('state') is not None:
            result['state'] = snapshot(state, body['state'], result['deck'], catalog, rules)
        elif outcome in ('resolved','no_result') and (not rule or rule.get('resource_change')):
            state['known']['board'] = False; state['known']['hand'] = False
            event['note'] = '处理已确认；请核对实际取得的牌及区域变化'
    elif operation == 'window':
        kind = body.get('kind')
        if kind not in ('chain', 'after_add', 'open', 'none'): raise ValueError('响应窗口无效')
        if kind != 'none':
            target = next((e for e in result['events'] if e['id'] == body.get('event_id')), None)
            if kind == 'chain' and (not target or target.get('kind') != 'activate' or target.get('outcome') != 'pending'):
                raise ValueError('请选当前连锁最上方、尚未结算的发动')
            if kind == 'chain' and target['turn'] != state['turn']:
                raise ValueError('不能把先前回合的发动确认成当前响应窗口')
            pending = [e for e in result['events'] if e.get('kind') == 'activate' and e.get('outcome') == 'pending']
            if kind == 'chain' and pending and target['id'] != pending[-1]['id']:
                raise ValueError('较高连锁仍有待处理发动，不能越过它响应下方效果')
            if kind == 'after_add' and (not target or target.get('operation') != 'snapshot'):
                raise ValueError('请先核对实际加手后的局面')
            state['window'] = {'id': identity(), 'kind': kind, 'event_id': target['id'] if target else None,
                               'source': 'manual', 'expires_at': now + 15000,
                               'responder': 0, 'confirmed': body.get('confirmed') is True}
            if not state['window']['confirmed']: raise ValueError('请确认当前游戏确实轮到你响应')
    elif operation == 'gap':
        state['known'].update(board=False, hand=False, usage=False, limits=False)
        result['needs_sync'] = True; event['note'] = '记录中断；需要重新核对当前资源、次数与限制'
    elif operation == 'preference':
        if body.get('goal') not in GOALS: raise ValueError('目标无效')
        preserve = body.get('preserve', [])
        if not isinstance(preserve, list) or any(c not in {r['id'] for r in state['cards']} for c in preserve): raise ValueError('保留资源无效')
        result['goal'] = body['goal']; result['preserve'] = list(dict.fromkeys(preserve))
    elif operation == 'close': result['closed'] = True
    else: raise ValueError('不支持的对局操作')
    if len(result['events']) >= 5000: raise ValueError('本局记录已达上限，请结束本局；原记录保留')
    result['events'].append(event)
    result['revision'] += 1; result['updated_at'] = now
    return result
