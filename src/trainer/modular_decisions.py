"""Semantic decisions for the pinned core protocol, never a substitute rule engine.

Only responses observed in sources are reusable. Indexes are rebound to the new
legal prompt; effect identity and relevant position/instance attributes survive.
The disposable native core must still accept every rebound response.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import struct

from protocol import packets, PROMPTS, u32


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def canonical_state(value):
    if isinstance(value,dict):return {key:canonical_state(item) for key,item in value.items() if key!='effect_handle'}
    if isinstance(value,list):return [canonical_state(item) for item in value]
    return value


def integer(value):
    return struct.pack('<i', value).hex()


def public_state(state):
    result = deepcopy(state)
    hidden = Counter()
    for card in result.get('cards', []):
        if card.get('controller') == 1 and (card.get('location') in (1, 2, 64) or
                card.get('location') in (4, 8, 32) and card.get('position', 0) & 10):
            hidden[str(card['location'])] += 1
            for key in list(card):
                if key not in ('controller', 'location', 'sequence', 'position'): card.pop(key)
            card['unknown'] = True
        # The player knows their remaining deck multiset, not its shuffled order.
        if card.get('location') == 1:
            card.pop('sequence', None)
            if card.get('controller') == 0:
                for key in list(card):
                    if key not in ('controller','location','code','name'):card.pop(key)
    # Native card IDs and insertion order must not disclose the shuffled deck.
    own_deck=sorted((c for c in result.get('cards', []) if c.get('controller')==0 and c.get('location')==1),key=lambda c:c.get('code',0))
    result['cards']=[c for c in result.get('cards', []) if not (c.get('controller')==0 and c.get('location')==1)]+own_deck
    result['unknown'] = dict(hidden)
    # Shared/global counters can encode an unrevealed opponent card's identity.
    result['effect_usage'] = [row for row in result.get('effect_usage', []) if row.get('player') == 0]
    return result


def forecast_state(state, unknown_cards):
    result=public_state(state)
    for card in result['cards']:
        if card.get('controller')==0 and (card.get('instance_id') in unknown_cards or unknown_cards and card.get('location')==1):
            for key in list(card):
                if key not in ('controller','location','position'):card.pop(key)
            card.update(unknown=True,name='随机结果中的卡牌（待实际确认）')
    return result


EFFECT_KEYS = ('description', 'effect_type', 'event_code', 'range', 'owner_code', 'handler_code',
               'count_code', 'condition_line', 'cost_line', 'target_line', 'operation_line', 'labels',
               'category','property_flags','self_range','opponent_range','effect_value','value_line')


def effect_key(effect):
    return {key: effect.get(key) for key in EFFECT_KEYS} if effect else None


def card_key(card, state):
    key = {k: card.get(k) for k in ('code', 'controller', 'location')}
    if card.get('controller') == 1 and (card.get('location') in (1,2,64) or card.get('location') in (4,8,32) and card.get('position',0)&10):
        key.update(code=None, unknown=True)
    if card.get('location') in (4, 8, 128):
        key['sequence'] = card.get('sequence')
        key['position'] = card.get('position')
        parent = next((c for c in state.get('cards', []) if card.get('overlay_target') is not None and c.get('instance_id') == card['overlay_target']), None)
        if parent: key['overlay'] = {k: parent.get(k) for k in ('code', 'controller', 'location', 'sequence')}
    # Historical summon materials are evidence, not an unconditional prerequisite
    # for every later effect. Material selection binds its carrier explicitly;
    # other material-sensitive rules are re-evaluated by the disposable core.
    return key


def model(raw, state, effects=None):
    data = bytes.fromhex(raw)
    parsed = list(packets(data))
    if len(parsed) != 1 or parsed[0][1] not in PROMPTS: raise ValueError('缺少单次决策窗口')
    msg = data[0]
    player = data[2] if msg == 23 else data[1]
    effects = effects or {}
    context = effect_key(effects.get('context'))
    result = {'message': msg, 'player': player, 'context': context, 'choices': [], 'mode': 'single'}
    def card_at(p):
        code, controller, location, sequence = u32(data, p) & 0x7fffffff, *data[p+4:p+7]
        if location & 128:
            parent = next((c for c in state.get('cards', []) if c.get('controller') == controller and c.get('location') == (location & 127) and c.get('sequence') == sequence), None)
            materials = [c for c in state.get('cards', []) if parent and c.get('code') == code and c.get('location') == 128 and c.get('overlay_target') == parent.get('instance_id')]
            if msg in (15, 20, 26): materials = [c for c in materials if c.get('sequence') == data[p+7]]
            if len(materials) != 1: raise ValueError('无法唯一识别素材与承载怪兽实例')
            return materials[0]
        found = [c for c in state.get('cards', []) if c.get('code') == code and
                 (c.get('controller'), c.get('location'), c.get('sequence')) == (controller, location, sequence)]
        return found[0] if len(found) == 1 else dict(code=code, controller=controller, location=location, sequence=sequence)
    def add(kind, response, card=None, effect=None, **fields):
        semantic = {'kind': kind, **fields}
        if card: semantic['card'] = card_key(card, state)
        if effect: semantic['effect'] = effect_key(effect)
        result['choices'].append({'semantic': semantic, 'response': response, 'card': card, 'effect': effect})
    def chosen_effect(index, card, description):
        choices = effects.get('choices', [])
        if index < len(choices):
            effect = choices[index]
            if effect and effect.get('handler_code') == card.get('code') and effect.get('description') == description: return effect
        return {'handler_code': card.get('code'), 'description': description}
    if msg in (10, 11):
        p = 2
        groups = ('summon', 'special', 'position', 'monster_set', 'spell_set', 'activate') if msg == 11 else ('activate', 'attack')
        for group, kind in enumerate(groups):
            count = data[p]; p += 1
            width = 11 if kind == 'activate' else 8 if kind == 'attack' else 7
            for index in range(count):
                card = card_at(p)
                effect = chosen_effect(index, card, u32(data, p+7)) if kind == 'activate' else None
                add(kind, integer((index << 16) | group), card, effect); p += width
        if data[p]: add('battle' if msg == 11 else 'main2', integer(6 if msg == 11 else 2))
        if data[p+1]: add('end_turn', integer(7 if msg == 11 else 3))
    elif msg == 16:
        forced = False
        for i in range(data[2]):
            p = 12+i*14; forced |= bool(data[p+1]); card = card_at(p+2)
            add('activate', integer(i), card, chosen_effect(i, card, u32(data, p+10)))
        if not forced: add('pass', integer(-1))
    elif msg in (12, 13):
        card = card_at(2) if msg == 12 else None
        description = u32(data, 10) if msg == 12 else u32(data, 2)
        effect = chosen_effect(0, card, description) if card else effects.get('context')
        if card:
            actual = [e for e in effects.get('choices', []) if e and e.get('handler_code') == card['code'] and e.get('handler_instance') == card.get('instance_id')]
            if len(actual) == 1: effect = actual[0]
            elif (effects.get('context') or {}).get('handler_instance') == card.get('instance_id') and (effects.get('context') or {}).get('handler_code') == card.get('code'):
                effect = effects['context']
        for answer in (1, 0): add('yes' if answer else 'no', integer(answer), card, effect, description=description)
    elif msg in (14, 143):
        for i in range(data[2]): add('option', integer(i), value=u32(data, 3+i*4))
    elif msg == 19:
        for flag in (1, 2, 4, 8):
            if data[6] & flag: add('position_choice', integer(flag), value=flag, code=u32(data, 2))
    elif msg in (15, 20):
        result.update(mode='cards', minimum=data[3], maximum=data[4], cancel=bool(data[2]), tribute=msg == 20)
        for i in range(data[5]): add('card', i, card_at(6+i*8), **({'tribute_value': data[13+i*8]} if msg == 20 else {}))
    elif msg == 26:
        p = 7
        for i in range(data[6]): add('select', bytes([1, i]).hex(), card_at(p)); p += 8
        count = data[p]; p += 1
        for i in range(count): add('unselect', bytes([1, data[6]+i]).hex(), card_at(p)); p += 8
        if data[2] or data[3]: add('finish_selection' if data[2] else 'cancel_selection', integer(-1))
    elif msg in (18, 24):
        result.update(mode='places', minimum=data[2] or 1, maximum=data[2] or 1)
        mask = u32(data, 3)
        for i in range(32):
            if not mask & (1 << i):
                place = [player if i < 16 else 1-player, 8 if i % 16 >= 8 else 4, i % 8]
                add('place', bytes(place).hex(), place=place)
    elif msg == 23:
        result.update(mode='sum', minimum=data[7], maximum=data[8], mandatory=data[9], target=u32(data, 3), sum_mode=data[1])
        p = 10 + data[9]*11; count = data[p]; p += 1
        for i in range(count): add('material', i, card_at(p), value=u32(data, p+7)); p += 11
    elif msg == 25:
        result['mode'] = 'sort'
        for i in range(data[2]): add('sort_card', i, card_at(3+i*7))
    elif msg in (140, 141):
        result.update(mode='mask', minimum=data[2], maximum=data[2])
        for i in range(32):
            if u32(data, 3) & (1 << i): add('declare_mask', i, flag=1 << i)
    elif msg == 142:
        result.update(mode='declaration', rules=[u32(data, 3+i*4) for i in range(data[2])])
    elif msg == 22:
        result.update(mode='counters', amount=struct.unpack_from('<H',data,4)[0])
        for i in range(data[6]):
            add('counter', i, card_at(7+i*9))
            result['choices'][-1]['available'] = struct.unpack_from('<H',data,14+i*9)[0]
    elif msg == 132:
        for value in (1, 2, 3): add('rock_paper_scissors', integer(value), value=value)
    else:
        result['unsupported'] = True
    return result


def semantic_response(prompt, raw):
    """Extract the actual choice, excluding uninitialized response-buffer padding."""
    data = bytes.fromhex(raw)
    base = {key: prompt[key] for key in ('message', 'player', 'context')}
    choices, mode = prompt['choices'], prompt['mode']
    if mode == 'declaration': return {**base, 'declaration': u32(data), 'rules': prompt['rules']}
    if mode == 'counters':
        return {**base, 'selection': [{**c['semantic'], 'amount': struct.unpack_from('<H',data,i*2)[0]} for i,c in enumerate(choices) if struct.unpack_from('<H',data,i*2)[0]]}
    if mode == 'mask': return {**base, 'selection': [c['semantic'] for c in choices if u32(data) & c['semantic']['flag']]}
    if mode == 'single':
        matches = [c for c in choices if data.startswith(bytes.fromhex(c['response']))]
        if len(matches) != 1: raise ValueError('无法唯一识别本次效果或决策')
        return {**base, 'selection': [matches[0]['semantic']]}
    if mode in ('cards', 'sum'):
        if data[:4] == b'\xff'*4: return {**base, 'cancel': True}
        n = data[0]; indexes = list(data[1:1+n])
        if mode == 'sum': indexes = indexes[prompt['mandatory']:]
    elif mode == 'places':
        indexes = []
        for i in range(prompt['minimum']):
            place = data[i*3:i*3+3].hex()
            indexes.append(next(j for j, c in enumerate(choices) if c['response'] == place))
    elif mode == 'sort':
        if data[0] == 255: return {**base, 'cancel': True}
        indexes = sorted(range(len(choices)), key=lambda i: data[i])
    else: raise ValueError('此决策类型需要补充语义解码')
    if len(set(indexes)) != len(indexes) or any(i >= len(choices) for i in indexes): raise ValueError('来源选择无效')
    return {**base, 'selection': [choices[i]['semantic'] for i in indexes]}


def matching_key(value, precise=True):
    """Relax coordinates only; identity, posture, effects and resources survive."""
    if precise:return value
    if isinstance(value,list):return [matching_key(v,False) for v in value]
    if not isinstance(value,dict):return value
    result={k:matching_key(v,False) for k,v in value.items()}
    if result.get('location') in (4,8) and 'code' in result:result.pop('sequence',None)
    if result.get('kind')=='place' and 'place' in result:result['place']=result['place'][:2]
    return result


def semantic_equal(first, second, precise=True):
    return matching_key(first,precise)==matching_key(second,precise)


def context_equal(recorded, current):
    """Recognize the standard Link procedure across relocated Lua callbacks.

    This only adapts the already selected summon procedure, never an activatable
    card effect. Its carrier, summon type and all other effect fields must match;
    all three callbacks must move together. Materials still bind to the current
    legal prompt and every answer is checked by the disposable core.
    """
    if recorded == current: return True
    if not recorded or not current: return False
    standard = {'description': 1166, 'effect_type': 2, 'event_code': 34,
                'range': 64, 'effect_value': 0x4c000000, 'count_code': 0,
                'cost_line': 0, 'value_line': 0, 'labels': [], 'category': 0}
    if any(recorded.get(k) != v or current.get(k) != v for k, v in standard.items()): return False
    lines = ('condition_line', 'target_line', 'operation_line')
    if any(type(e.get(k)) is not int or e[k] <= 0 for e in (recorded, current) for k in lines): return False
    if any(recorded.get(k) is None or current.get(k) is None for k in EFFECT_KEYS): return False
    if {k:v for k,v in recorded.items() if k not in lines} != {k:v for k,v in current.items() if k not in lines}: return False
    return len({current[k] - recorded[k] for k in lines}) == 1


def script_binding_conflict(semantic, prompt):
    """Explain an unadaptable script signature without relaxing effect identity."""
    if any(semantic.get(k) != prompt.get(k) for k in ('message', 'player')): return False
    lines = ('condition_line', 'cost_line', 'target_line', 'operation_line', 'value_line')
    def relocated(a, b):
        return bool(a and b and a != b and
                    {k:v for k,v in a.items() if k not in lines} == {k:v for k,v in b.items() if k not in lines})
    a, b = semantic.get('context'), prompt.get('context')
    if relocated(a, b) and not context_equal(a, b): return True
    for selected in semantic.get('selection', []):
        if not selected.get('effect'): continue
        for choice in prompt.get('choices', []):
            actual = choice['semantic']
            if (relocated(actual.get('effect'), selected['effect'])
                    and semantic_equal({k:v for k,v in selected.items() if k != 'effect'},
                                       {k:v for k,v in actual.items() if k != 'effect'}, False)):
                return True
    return False


def snapshot_matches(first, second):
    def snapshot(state):
        shown=public_state(state)
        cards=[]
        for card in shown.get('cards',[]):
            value=card_key(card,shown)
            value['disabled']=card.get('disabled',False)
            value['counters']=card.get('counters',[])
            if card.get('location')==4:value['summon_method']=card.get('summon_info',0)&0xff000000
            cards.append(digest(value))
        return {**{k:state.get(k) for k in ('turn','turn_player','phase','lp','chain_depth')},'cards':sorted(cards)}
    return snapshot(first)==snapshot(second)


def activation_window_binding(semantic, prompt, excluded_instances=(), precise=True):
    if precise or {semantic.get('message'),prompt.get('message')} != {12,16}: return None
    if semantic.get('player') != prompt.get('player') or prompt.get('mode') != 'single': return None
    if not context_equal(semantic.get('context'),prompt.get('context')): return None
    selection=semantic.get('selection',[])
    if len(selection)!=1 or selection[0].get('kind') != ('yes' if semantic['message']==12 else 'activate'): return None
    selected=selection[0];effect=selected.get('effect') or {}
    # A card name/description alone cannot prove that two windows offer the
    # same effect. Require the complete recorded native effect signature.
    if any(effect.get(key) is None for key in EFFECT_KEYS) or not selected.get('card'): return None
    def normalized(value): return {k:v for k,v in value.items() if k not in ('kind','description')}
    matches=[c for c in prompt['choices'] if c['semantic'].get('kind') == ('yes' if prompt['message']==12 else 'activate')
             and (c.get('card') or {}).get('instance_id') not in excluded_instances
             and semantic_equal(normalized(selected),normalized(c['semantic']),False)]
    return matches[0]['response'] if len(matches)==1 else None


def bind(semantic, prompt, excluded_instances=(), precise=True):
    if semantic.get('message') != prompt.get('message'):
        return activation_window_binding(semantic,prompt,excluded_instances,precise)
    if any(semantic.get(k) != prompt.get(k) for k in ('message', 'player')) or not context_equal(semantic.get('context'), prompt.get('context')): return None
    if semantic.get('cancel'):
        return 'ff' if prompt['mode'] == 'sort' else integer(-1) if prompt.get('cancel') else None
    if prompt['mode'] == 'declaration':
        return struct.pack('<I',semantic['declaration']).hex() if semantic.get('rules') == prompt['rules'] else None
    if prompt['mode'] == 'counters':
        amounts = [0]*len(prompt['choices'])
        for selected in semantic.get('selection', []):
            wanted = {k:v for k,v in selected.items() if k != 'amount'}
            matches = [i for i,c in enumerate(prompt['choices']) if semantic_equal(c['semantic'],wanted,precise)]
            if len(matches) != 1 or selected['amount'] > prompt['choices'][matches[0]]['available']: return None
            amounts[matches[0]] = selected['amount']
        return b''.join(struct.pack('<H',n) for n in amounts).hex() if sum(amounts) == prompt['amount'] else None
    indexes = []
    for selected in semantic.get('selection', []):
        matches = [i for i, c in enumerate(prompt['choices']) if semantic_equal(c['semantic'],selected,precise) and i not in indexes
                   and (c.get('card') or {}).get('instance_id') not in excluded_instances]
        if not matches: return None
        if len(matches) > 1 and selected.get('effect'):
            # Equal labels/signatures must never arbitrarily choose a different
            # effect. Hand copies with distinct instances are also left explicit.
            physical=[(prompt['choices'][i].get('card') or {}).get('instance_id') for i in matches]
            if precise or len(physical)!=len(set(physical)):return None
        matches.sort(key=lambda i:prompt['choices'][i]['semantic']!=selected)
        indexes.append(matches[0])
    return encode_binding(semantic,prompt,indexes)


def encode_binding(semantic,prompt,indexes):
    if prompt['mode'] == 'single': return prompt['choices'][indexes[0]]['response'] if len(indexes) == 1 else None
    if prompt['mode'] in ('cards', 'sum'):
        if prompt['mode'] == 'cards':
            total = sum(prompt['choices'][i]['semantic'].get('tribute_value', 1) for i in indexes)
            if total < prompt['minimum'] or len(indexes) > prompt['maximum']: return None
        mandatory = prompt.get('mandatory', 0)
        return bytes([len(indexes)+mandatory, *range(mandatory), *indexes]).hex()
    if prompt['mode'] == 'places':
        return ''.join(prompt['choices'][i]['response'] for i in indexes) if len(indexes) == prompt['minimum'] else None
    if prompt['mode'] == 'sort':
        return bytes(indexes.index(i) for i in range(len(indexes))).hex() if len(indexes) == len(prompt['choices']) else None
    if prompt['mode'] == 'mask':
        return struct.pack('<I',sum(prompt['choices'][i]['semantic']['flag'] for i in indexes)).hex() if len(indexes) == prompt['minimum'] else None
    return None


def bind_variants(semantic,prompt,excluded_instances=(),precise=True,limit=3):
    first=bind(semantic,prompt,excluded_instances,precise)
    if semantic.get('message') != prompt.get('message'): return [first] if first is not None else []
    if precise or prompt['mode'] not in ('single','places','cards','sum') or semantic.get('cancel'):
        return [first] if first is not None else []
    if any(semantic.get(k)!=prompt.get(k) for k in ('message','player')) or not context_equal(semantic.get('context'),prompt.get('context')):return []
    options=[]
    for selected in semantic.get('selection',[]):
        choices=[i for i,c in enumerate(prompt['choices']) if semantic_equal(c['semantic'],selected,False)
                 and (c.get('card') or {}).get('instance_id') not in excluded_instances]
        if selected.get('effect'):
            counts=Counter((prompt['choices'][i].get('card') or {}).get('instance_id') for i in choices)
            choices=[i for i in choices if counts[(prompt['choices'][i].get('card') or {}).get('instance_id')]==1]
        choices.sort(key=lambda i:prompt['choices'][i]['semantic']!=selected)
        if not choices:return []
        options.append(choices)
    result=[first] if first is not None else []
    def visit(indexes):
        if len(result)>=limit:return
        if len(indexes)==len(options):
            raw=encode_binding(semantic,prompt,indexes)
            if raw is not None and raw not in result:result.append(raw)
            return
        for index in options[len(indexes)]:
            if index not in indexes:visit([*indexes,index])
            if len(result)>=limit:break
    visit([])
    return result


def forecast_reveals(batches, state, excluded_instances=()):
    """Expose only a confirmed reveal of an already-known own card."""
    result=[]
    for batch in batches:
        for _,msg,body in packets(bytes.fromhex(batch)):
            if msg != 31: continue
            for index in range(body[2]):
                offset=3+index*7
                code=int.from_bytes(body[offset:offset+4],'little')
                controller,location,sequence=body[offset+4:offset+7]
                if controller != 0 or location == 1: continue
                card=next((c for c in state.get('cards',[]) if c.get('controller')==controller and
                           c.get('location')==location and c.get('sequence')==sequence and c.get('code')==code and
                           not c.get('unknown') and c.get('instance_id') not in excluded_instances),None)
                if card: result.append(deepcopy(card))
    return result


def next_prompt(batches):
    last = None
    uncertain = False
    for batch in batches:
        data = bytes.fromhex(batch)
        for offset, msg, body in packets(data):
            if msg == 1: raise ValueError('规则引擎拒绝此决策')
            if msg in (30, 81, 90, 130, 131): uncertain = True
            if msg in PROMPTS: last = bytes([msg]) + body
    return last.hex() if last else None, uncertain


def response_bindings(prompt, raw):
    """Audit the actual indexes and physical instances selected in this duel."""
    data=bytes.fromhex(raw);choices=prompt['choices'];mode=prompt['mode'];indexes=[]
    if mode=='places':return [{'place':list(data[i*3:i*3+3])} for i in range(prompt['minimum'])]
    if mode=='single': indexes=[i for i,c in enumerate(choices) if data.startswith(bytes.fromhex(c['response']))]
    elif mode in ('cards','sum') and data[:4]!=b'\xff'*4:
        indexes=list(data[1:1+data[0]])[prompt.get('mandatory',0):]
    elif mode=='counters': indexes=[i for i in range(len(choices)) if struct.unpack_from('<H',data,i*2)[0]]
    return [{'index':i,'card':public_state({'cards':[choices[i]['card']]})['cards'][0] if choices[i].get('card') else None,'effect':deepcopy(choices[i].get('effect'))}
            for i in indexes if choices[i].get('card') or choices[i].get('effect')]


def terminal_key(state):
    """A terminal requires the recorded public board, including zones and materials.

    Hand/deck differences are resources to evaluate, not an exact-state join key.
    """
    return sorted([c.get('code'), c.get('location'), c.get('sequence'), c.get('position')]
                  for c in state.get('cards', []) if c.get('controller') == 0 and c.get('location') in (4, 8))


def evaluation(state, catalog):
    own = [c for c in state.get('cards', []) if c.get('controller') == 0]
    board = [c for c in own if c.get('location') in (4, 8)]
    hand = [c for c in own if c.get('location') == 2]
    # An explicit resource vector, not a win-rate or invented independent negates.
    return {'board': len(board), 'hand': len(hand),
            'field_monsters': sum(c.get('location') == 4 for c in board),
            'extra': sum(c.get('location') == 64 for c in own),
            'grave': sum(c.get('location') == 16 for c in own),
            'lp': state.get('lp', [0])[0],
            'normal_summons_used': state.get('normal_summons_used', [None])[0],
            'interruptions': None, 'followup_effects': None,
            'basis': '按场上与手牌可见资源合计、保留额外卡组、生命值依次比较；阻抗与墓地再利用效果未评估，不按卡数虚构次数'}


def resource_rank(value):
    if 'marked_cards' in value:
        return (value['marked_cards'], value.get('marked_effects', 0))
    return (value.get('confirmed_response', 0), value['board']+value['hand'], value.get('field_monsters', 0), value['extra'], value['lp'])


def validate_source(source):
    if not isinstance(source, dict) or source.get('schema') != 1: raise ValueError('模块来源版本无效')
    snapshots, edges = source.get('snapshots'), source.get('edges')
    if not isinstance(snapshots, list) or not isinstance(edges, list) or len(snapshots) > 10000 or len(edges) > 10000:
        raise ValueError('模块来源快照格式无效')
    nodes = {}
    for node in snapshots:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or node['id'] in nodes or not isinstance(node.get('state', {}).get('cards'), list):
            raise ValueError('模块快照标识或状态无效')
        nodes[node['id']] = node
    for edge in edges:
        if not isinstance(edge, dict) or edge.get('from') not in nodes or edge.get('to') not in nodes: raise ValueError('模块连接引用无效')
        node = nodes[edge['from']]
        try:
            if len(bytes.fromhex(edge['response'])) > 64: raise ValueError('决策响应超长')
            prompt = model(node['raw'], node['state'], node.get('effects'))
            if semantic_response(prompt, edge['response']) != edge['decision']: raise ValueError('模块决策与原始选择不一致')
            if edge.get('terminal') and not isinstance(edge.get('terminal_board'), list): raise ValueError('模块终场无效')
            if not isinstance(edge.get('delta'), list) or any(len(row) != 3 or any(type(n) is not int for n in row) for row in edge['delta']): raise ValueError('模块结果条件无效')
        except (KeyError, TypeError, IndexError, StopIteration) as error:
            raise ValueError('模块决策证据不完整') from error
