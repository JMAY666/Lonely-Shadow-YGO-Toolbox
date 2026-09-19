"""Public native window identity and hindsight-free second-player review."""
from copy import deepcopy

from modular_decisions import model, semantic_response
from module_graph import decision_boundaries
from second_rules import EFFECTS, RESPONDERS, ALUBER, MOYE, FUSION, set_usage, usage_key
from protocol import packets


# Exact descriptors observed in the pinned, separately fingerprinted scripts.
# Other effects on these cards do not inherit the first effect's case.
CHAIN_EFFECTS = {(ALUBER, ALUBER * 16, 137): 'aluber.search',
                 (MOYE, MOYE * 16, 137): 'moye.token',
                 (FUSION, 0, 26): 'fusion.activate'}
ANNOTATIONS = {'resource_role', 'hint_window', 'verify', 'window', 'choice', 'result', 'invalidate',
               'rule', 'rule_status', 'resume'}


def own_main(node):
    state = node['state']
    return (node.get('player') == 0 and bytes.fromhex(node['raw'])[0] == 11 and
            (state.get('turn'), state.get('turn_player'), state.get('phase'), state.get('chain_depth')) == (2, 0, 4, 0))


def supported_window(node):
    state = node['state']
    return stage_of(node) != 'opponent_turn' or (node.get('player') == 0 and bytes.fromhex(node['raw'])[0] in (12, 16) and
                              state.get('turn') == 1 and state.get('turn_player') == 1)


def stage_of(node):
    if own_main(node): return 'own_turn'
    state = node['state']; message = bytes.fromhex(node['raw'])[0]
    if state.get('turn') == 2 and state.get('turn_player') == 0 and node.get('player') == 0 and not state.get('chain_depth'):
        if message == 10 and state.get('phase') in (8,16,128): return 'battle'
        if message == 11 and state.get('phase') == 256: return 'after_battle'
    return 'opponent_turn'


def native_window(node, current):
    state = node['state']; chains = state.get('chains') or []
    result = {'basis': 'native_legal_menu', 'recognized': False, 'responders': [],
              'notice': '原生菜单仅证明当前开放的效果；具体对象、处理结果和策略仍需核对'}
    if stage_of(node) != 'opponent_turn': return result
    prompt = model(node['raw'], state, node.get('effects'))
    ids = {c.get('native_instance'): c['id'] for c in current['cards'] if c.get('native_instance') is not None}
    for choice in prompt['choices']:
        card, effect = choice.get('card') or {}, choice.get('effect') or {}
        code = card.get('code')
        if (choice['semantic']['kind'] not in ('yes', 'activate') or code not in RESPONDERS
                or card.get('controller') != 0 or card.get('location') != 2 or card.get('instance_id') not in ids):
            continue
        # Complete script identity is also checked before advice is generated.
        if effect.get('handler_code') != code or effect.get('operation_line') is None: continue
        result['responders'].append({'card_id': ids[card['instance_id']], 'effect_id': RESPONDERS[code],
                                     'basis': 'offered_by_current_native_menu'})
        rule = EFFECTS[RESPONDERS[code]]
        if rule['limit'] != 'none' and effect.get('count_remaining', 0) > 0:
            set_usage(current, rule, 0, ids[card['instance_id']], 'unused')
            current['effect_counts'][usage_key(rule, 0, ids[card['instance_id']])]['source'] = 'native_legal_menu'
    if len(chains) != 1: return result
    effect = chains[0].get('effect') or {}
    key = CHAIN_EFFECTS.get((effect.get('handler_code'), effect.get('description'), effect.get('effect_type')))
    card_id = ids.get(effect.get('handler_instance'))
    actor = next((c for c in current['cards'] if c['id'] == card_id and c.get('controller') == 1), None)
    if key and actor and actor.get('code') == EFFECTS[key]['code'] and actor['location'] == EFFECTS[key]['location']:
        result.update(recognized=True, card_id=card_id, effect_id=key, link=1, top=1, speed=1)
    return result


def carry_annotations(current, previous):
    hand = {c['id'] for c in current['cards'] if c['controller'] == 0 and c['location'] == 2}
    current['resource_roles'] = {key: deepcopy(value) for key, value in previous.get('resource_roles', {}).items() if key in hand}
    # These are human notes, never native restrictions or counter permissions.
    for key in ('usage', 'restrictions'):
        current[key] = deepcopy(previous.get(key, []))
    return current


def public_actions(rows, folder, through):
    result = []
    for boundary in decision_boundaries(rows, folder):
        node = boundary['node']
        responses = [r for r in boundary['responses'] if r['seq'] <= through]
        if node['seq'] > through or not responses: continue
        row = {'seq': responses[-1]['seq'], 'node': node['node'], 'player': node.get('player'),
               'turn': node['state']['turn'], 'selection': [], 'basis': 'native_response', 'ambiguous': len(responses) != 1}
        if node.get('player') == 0 and len(responses) == 1:
            try:
                decision = semantic_response(model(node['raw'], node['state'], node.get('effects')), responses[0]['raw'])
                row['selection'] = deepcopy(decision.get('selection', []))
            except (ValueError, KeyError, IndexError, TypeError):
                row['ambiguous'] = True
        # An opponent's private menu/effect identity is never decoded for review.
        result.append(row)
    return result


def public_outcomes(rows, through):
    result = []
    for row in rows:
        if row['seq'] > through or row.get('kind') != 'batch': continue
        try:
            for offset, message, data in packets(bytes.fromhex(row['raw'])):
                if message in (75, 76):
                    result.append({'seq': row['seq'], 'offset': offset, 'kind': 'activation_negated' if message == 75 else 'effect_negated', 'link': data[0]})
                elif message == 83:
                    result.append({'seq': row['seq'], 'offset': offset, 'kind': 'targets',
                        'places': [{'controller': data[1+i*4], 'location': data[2+i*4], 'sequence': data[3+i*4]} for i in range(data[0])]})
        except (ValueError, KeyError, IndexError):
            result.append({'seq': row['seq'], 'kind': 'undecoded', 'notice': '该批次有未解码事件，只列已确认的公开结果'})
    return result


def review(doc, hint):
    origin = hint.get('native_origin')
    result = {'id': hint['id'], 'known_state': deepcopy(hint['known_state']),
              'decisions': deepcopy(hint['decisions']), 'comparison': deepcopy(hint['items']),
              'actual': None, 'notes': [], 'notice': '比较依据仅为生成时已知信息；后续实际结果单列，其他选择只是假设'}
    if not origin:
        result['notice'] += '。此旧提示未绑定原生日志，实际情况见原观察记录'
        return result
    result['notes'] = [{'kind': e['kind'], 'note': e['payload'].get('note', ''), 'time_ms': e['time_ms'],
                        'basis': 'user_note_not_native_result'} for e in doc.get('events', [])
                       if e['kind'] in ('choice', 'result') and e.get('native_origin') and all(
                           e['native_origin'].get(k) == origin.get(k) for k in ('source', 'checkpoint', 'seq'))]
    history = doc.get('native_history', [])
    before = next((h for h in history if h['node'] == origin['checkpoint'] and h['seq'] == origin['seq']), None)
    after = next((h for h in history if h['seq'] > origin['seq'] and not h['state'].get('chain_depth')), None)
    if not before or not after: return result
    old = before['state']['cards']; new = after['state']['cards']
    remaining_hand = {c.get('instance_id') for c in new if c.get('controller') == 0 and c.get('location') == 2}
    remaining_field = {c.get('instance_id') for c in new if c.get('controller') == 1 and c.get('location') in (4, 8)}
    result['actual'] = {'from_node': before['node'], 'through_node': after['node'],
        'own_hand_departures': [c['code'] for c in old if c.get('controller') == 0 and c.get('location') == 2
                               and c.get('instance_id') not in remaining_hand],
        'opponent_field_departures': [c['code'] for c in old if c.get('controller') == 1 and c.get('location') in (4, 8)
                                     and c.get('code') and c.get('instance_id') not in remaining_field],
        'actions': deepcopy([a for a in doc.get('native_actions', []) if before['seq'] < a['seq'] <= after['seq']]),
        'outcomes': deepcopy([a for a in doc.get('native_outcomes', []) if before['seq'] < a['seq'] <= after['seq']]),
        'state': deepcopy(after['state']), 'basis': 'public_native_trace',
        'notice': '比较两端公开状态，列出结算后不在原区域的实例；不等同于费用、破坏或无效，也不与预计阻止的收益相加'}
    return result
