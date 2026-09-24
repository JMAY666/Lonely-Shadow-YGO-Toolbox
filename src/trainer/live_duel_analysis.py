"""Local, evidence-bound opponent references and limited interaction guidance."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
import time

from live_duel_state import active_locks, uses
from opening_analysis import digest
from live_synchro import options as synchro_options

ROOT = Path(__file__).parent
THREATS = {'restriction': '限制关键行动', 'negate': '无效与阻断', 'protection': '保护其他威胁',
           'removal': '移除关键资源', 'interaction': '按墓地资源提供干扰', 'followup': '后续资源', 'damage': '攻击推进'}


def normalized(value): return re.sub(r'\s+', '', value or '')


class Knowledge:
    def __init__(self, catalog, data=None):
        data = data or json.loads((ROOT/'live-duel-rules.json').read_text('utf-8'))
        if data.get('schema') != 1: raise ValueError('实战资料版本不支持')
        self.cards, self.rules, self.stale = {}, {}, []
        original = {r['code']: r for r in data['cards']}
        for code, current in catalog.items():
            base = code
            if base not in original and type(current.get('alias')) is int and abs(code-current['alias']) < 20: base = current['alias']
            if base not in original: continue
            row = original[base]
            if (normalized(row['text']) != normalized(current.get('desc')) or row['type'] != current.get('type')
                    or row.get('level') is not None and row['level'] != current.get('level',0)&255):
                self.stale.append(code); continue
            self.cards[code] = {**row, 'code': code, 'base_code': base}
            for number, effect in row['effects'].items():
                key = f'{code}:{number}'
                self.rules[key] = {**effect, 'key': key, 'code': code, 'number': int(number),
                                   'shared': effect.get('shared', f'{base}:{number}'),
                                   'source': row['source'], 'name': current.get('name', row['name'])}
        self.version = digest([data, sorted((c, r.get('desc'), r.get('type'),r.get('level')) for c, r in catalog.items() if c in original or r.get('alias') in original)])
        self.guides = json.loads((ROOT/'matchups.json').read_text('utf-8'))

    def used(self, state, key, player):
        rule = self.rules[key]
        return sum(uses(state, k, player, rule) for k, r in self.rules.items() if r['shared'] == rule['shared'])


def name(catalog, code): return catalog.get(code, {}).get('name', str(code)) if code else '未知卡'


def opponent_routes(session, knowledge, catalog):
    evidence = [e for e in session['events'] if e.get('card', {}).get('controller') == 1 and e['card']['code']
                and e.get('kind') in ('normal', 'special', 'activate', 'reveal')]
    results = []
    for guide in knowledge.guides['guides']:
        if guide['format'] != session['format']: continue
        sequence = guide.get('walkthrough', {}).get('sequence', [])
        relevant = {row['card'] for row in sequence}
        hits = [e for e in evidence if e['card']['code'] in relevant]
        if not hits: continue
        distinct = list(dict.fromkeys(e['card']['code'] for e in hits))
        failed = [e for e in hits if e.get('outcome') in ('negated_activation', 'negated_effect', 'no_result')]
        # References are matched by observed cards, never asserted as actual steps.
        last_code = hits[-1]['card']['code']
        position = next((i for i, row in enumerate(sequence) if row['card'] == last_code), -1)
        next_rows = sequence[position+1:position+3] if position >= 0 and not failed else []
        results.append({'id': guide['id'], 'title': guide['topic'],
                        'status': '路线受阻，后续需重判' if failed else '依据较强' if len(distinct) >= 2 else '候选',
                        'evidence': [name(catalog, code) for code in distinct], 'evidence_count': len(distinct),
                        'summary': guide['summary'], 'next': deepcopy(next_rows),
                        'condition': '公开参考中的可能后续，未确认对方完整牌表或隐藏手牌',
                        'warnings': guide['warnings'], 'source_ids': guide['source_ids']})
    results.sort(key=lambda r: (-r['evidence_count'], r['id']))
    return results[:3]


def protected(target, state, catalog, knowledge):
    return bool(catalog.get(target['code'], {}).get('type', 0) & 0x1000 and any(
        c['id'] != target['id'] and c['controller'] == target['controller'] and c['zone'] == 'monster'
        and c['faceup'] and c['disabled'] is False and knowledge.cards.get(c['code'], {}).get('base_code') == 41069676
        for c in state['cards']))


def response_choices(session, knowledge, catalog, now):
    state = session['state']; window = state['window']; choices = []
    valid_window = bool(window and window['confirmed'] and window['expires_at'] > now)
    target_event = next((e for e in session['events'] if window and e['id'] == window.get('event_id')), None)
    target_rule = knowledge.rules.get(f"{target_event['card']['code']}:{target_event['effect']}", {}) if target_event and 'card' in target_event else {}
    flags = set(target_rule.get('flags', [])); locks = active_locks(state, knowledge.rules)
    enemy = [c for c in state['cards'] if c['controller'] == 1 and c['zone'] == 'monster' and c['faceup'] and c['code']]
    own_field = [c for c in state['cards'] if c['controller'] == 0 and c['zone'] in ('monster', 'spell')]
    for card in state['cards']:
        if card['controller'] != 0 or card['zone'] != 'hand': continue
        key = f"{card['code']}:1"; rule = knowledge.rules.get(key, {})
        kind = rule.get('response')
        if not kind: continue
        reasons, missing = [], []
        if not valid_window: missing.append('尚无有效的已确认响应窗口')
        if not all(state['known'].values()) or session.get('needs_sync'): missing.append('当前资源、次数或限制未核对完整')
        if state['phase'] in ('unknown', 'battle'): missing.append('当前阶段／战斗子时点未覆盖')
        if session['format'] != 'OCG': missing.append('本版规则核对范围为 OCG')
        if window and window['kind']=='chain' and not target_rule: missing.append('本次效果的连锁限制尚未覆盖')
        if window and window['kind']=='chain' and target_rule.get('no_monster_response') and catalog.get(card['code'],{}).get('type',0)&1:
            reasons.append('不能用怪兽效果连锁这次卡的发动')
        if any(c['controller']==1 and c['zone'] in ('monster','spell') and c['faceup'] and c['code'] not in knowledge.cards
               and (not c['code'] or catalog.get(c['code'],{}).get('type',0)&0x26) for c in state['cards']):
            missing.append('存在未覆盖的表侧效果卡，需要核对其发动限制和保护')
        if rule.get('limit') and knowledge.used(state, key, 0) >= rule['limit']: reasons.append('同名／共享效果次数已使用')
        canonical = catalog.get(card['code'], {}).get('alias') or card['code']
        for record in state['limits']:
            definition = knowledge.rules.get(record['key'], {})
            affected = record.get('affected_code')
            if ('named_negation' in definition.get('locks', []) and record['turn'] <= state['turn'] <= record['turn']+definition.get('duration',0)
                    and affected and canonical == (catalog.get(affected, {}).get('alias') or affected)):
                reasons.append('已记录对应原本卡名的效果无效限制')
        if rule.get('cost') == 'send_self' and 'banish_instead' in locks: reasons.append('送墓费用无法支付')
        selected = None
        if kind in ('ash', 'belle'):
            needed = {'deck_add', 'deck_special', 'deck_send'} if kind == 'ash' else {'grave_add', 'grave_special', 'grave_banish'}
            if not window or window['kind'] != 'chain': reasons.append('需要直接响应对应效果的发动')
            elif not target_rule or 'flags' not in target_rule: missing.append('紧邻发动的具体处理分支尚未覆盖')
            elif not flags & needed: reasons.append('紧邻效果不在已核对的适用范围')
            if kind=='belle' and target_rule.get('grave_target_scope'): missing.append('本次目标可能来自墓地或除外，需先核对所选目标区域')
            if target_event and target_event['card']['controller'] != 1: reasons.append('本辅助不建议无效自己的效果')
        elif kind in ('veiler', 'imperm'):
            if kind == 'veiler' and (state['player'] != 1 or state['phase'] not in ('main1', 'main2')): reasons.append('仅对方主要阶段')
            if kind == 'imperm' and own_field: reasons.append('从手牌发动要求自己场上没有卡')
            if kind == 'imperm' and any(knowledge.cards.get(c['code'],{}).get('base_code') == 61049315 and c['disabled'] is False for c in enemy):
                if state.get('spell_trap_used') is None: missing.append('蔷薇鞭适用，需要核对本回合魔陷卡发动次数')
                elif state['spell_trap_used'] >= 1: reasons.append('蔷薇鞭适用且本回合魔陷卡发动次数已用')
            options = [c for c in enemy if catalog.get(c['code'], {}).get('type', 0) & 0x20 and not protected(c, state, catalog, knowledge)]
            if target_event:
                options.sort(key=lambda c: c['id'] != target_event['card']['id'])
            if not options: reasons.append('没有已知可取对象的表侧效果怪兽')
            else:
                selected = options[0]
                if selected['disabled'] is True: reasons.append('目标已被无效，不重复投入')
                if selected['disabled'] is None: missing.append('目标当前效果状态未确认')
                if catalog.get(selected['code'],{}).get('type',0)&0x1000 and any(
                    c['id']!=selected['id'] and c['disabled'] is None and knowledge.cards.get(c['code'],{}).get('base_code')==41069676 for c in enemy):
                    missing.append('保护其他调整的效果状态未确认，不能确认该目标可被取对象')
                if window and window['kind']=='chain' and target_event and (target_event['card']['zone']!='monster' or selected['id']!=target_event['card']['id']):
                    missing.append('这个场上目标不能直接视为当前离场／其他来源效果的无效解法')
        elif kind == 'droll':
            if not window or window['kind'] != 'after_add' or state['phase'] == 'draw': reasons.append('需要抽牌阶段以外对方实际从卡组加手后的窗口')
            if 'draw_on_special' in locks: missing.append('与已适用的抽牌收益冲突，需要取舍')
        elif kind == 'maxx':
            if 'no_deck_add' in locks: reasons.append('卡组加手限制正在适用，不能获得抽牌收益')
        elif kind == 'shifter':
            if any(c['controller'] == 0 and c['zone'] == 'grave' for c in state['cards']): reasons.append('己方墓地并非空')
            if 'banish_instead' in locks: reasons.append('同类送墓改除外已适用')
            missing.append('需要权衡双方送墓改除外对我方后续的影响')
        if card['id'] in session['preserve']: missing.append('你已选择保留这份资源')
        status = 'unavailable' if reasons else 'conditional' if missing else 'available'
        cost = '把自身送墓' if rule.get('cost') == 'send_self' else '丢弃自身' if rule.get('cost') == 'discard_self' else '使用这张手牌'
        choices.append({'card_id': card['id'], 'code': card['code'], 'effect': 1, 'key': key, 'response_kind':kind, 'name': name(catalog, card['code']),
                        'label': rule['label'], 'status': status, 'reasons': reasons + missing,
                        'target': selected['id'] if selected else None, 'target_name': name(catalog, selected['code']) if selected else '',
                        'target_event': window.get('event_id') if window else None,
                        'responding_to': (name(catalog,target_event['card']['code'])+' · 效果 '+str(target_event['effect'])) if target_event and 'card' in target_event else '',
                        'cost': cost, 'consequence': '同一副本用作干扰后，不能再作为手牌素材或后续资源。',
                        'basis': '已覆盖卡文与当前人工确认窗口；未做完整引擎复原', 'source': rule['source']})
    narrow_first={'ash':0,'belle':1,'droll':1,'veiler':2,'imperm':3,'maxx':4,'shifter':5}
    choices.sort(key=lambda c: ({'available': 0, 'conditional': 1, 'unavailable': 2}[c['status']],
                                 narrow_first[c['response_kind']], c['code']))
    return choices


def threat_list(session, knowledge, catalog):
    state = session['state']; rows = []; locks = active_locks(state, knowledge.rules)
    breakers = [c for c in state['cards'] if c['controller'] == 0 and c['zone'] == 'hand'
                and c['id'] not in session['preserve'] and knowledge.rules.get(f"{c['code']}:1", {}).get('breaker') == 'dark_ruler']
    for card in state['cards']:
        if card['controller'] != 1 or card['zone'] not in ('monster', 'spell') or not card['faceup']: continue
        rules = [r for r in knowledge.rules.values() if r['code'] == card['code'] and r.get('threat')]
        if not rules:
            if not card['code'] or card['code'] not in knowledge.cards:
                rows.append({'card_id': card['id'], 'code': card['code'], 'name': name(catalog, card['code']), 'priority': 2,
                             'status': '资料不足', 'effects': [], 'reason': '未覆盖这张场上卡的具体威胁，不能据此判为可以放行', 'answers': []})
            continue
        if card['disabled'] is True: continue
        kinds = {r['threat'] for r in rules}
        priority = 0 if 'restriction' in kinds else 1 if kinds & {'protection', 'negate', 'removal', 'interaction'} else 2
        answers = []
        if breakers and card['zone'] == 'monster' and state['known']['hand'] and state['known']['limits']:
            answers.append('持有冥王结界波：可作为主要阶段处理候选；仍需核对其他限制及对方响应')
            priority += 1
        if 'restriction' in kinds:
            own_spells = [c for c in state['cards'] if c['controller'] == 0 and c['zone'] == 'hand' and catalog.get(c['code'], {}).get('type', 0) & 6]
            if len(own_spells) <= 1: priority = 2 + bool(answers)
            reason = '会影响当前魔陷资源的使用顺序' if own_spells else '持续限制需要结合接下来的启动与解场核对'
        elif 'protection' in kinds: reason = '先处理它可能恢复其他目标的取对象／破坏解法，不能将被保护的卡单独评价'
        elif 'followup' in kinds: reason = '可能补回手牌或场面；实际可用性取决于墓地、次数和后续窗口'
        else: reason = '可能阻断关键启动或移除资源；需结合费用、次数与目标条件'
        if card['disabled'] is None: reason += '；当前是否被无效尚未确认'
        rows.append({'card_id': card['id'], 'code': card['code'], 'name': name(catalog, card['code']), 'priority': priority,
                     'status': '优先处理' if priority == 0 else '条件性威胁',
                     'effects': [{'key': r['key'], 'label': r['label'], 'kind': THREATS[r['threat']]} for r in rules],
                     'reason': reason, 'answers': answers})
    rows.sort(key=lambda r: (r['priority'], r['code']))
    return rows


def own_turn(session, knowledge, catalog):
    state = session['state']; locks = active_locks(state, knowledge.rules); cards = state['cards']; candidates = []
    if state['player'] != 0: return {'candidates': [], 'damage': None, 'note': '进入我方回合后，按实际剩余资源重新规划'}
    if any(e.get('kind')=='activate' and e.get('outcome')=='pending' and e['turn']==state['turn'] for e in session['events']):
        return {'candidates':[],'damage':None,'note':'当前回合仍有待确认处理的发动；先记录实际结算，不跳到新的通常召唤、同调或战斗。'}
    ready = all(state['known'].values()) and not session.get('needs_sync')
    hand = [c for c in cards if c['controller'] == 0 and c['zone'] == 'hand']
    fields = [c for c in cards if c['controller'] == 0 and c['zone'] == 'monster']
    enemies = [c for c in cards if c['controller'] == 1 and c['zone'] == 'monster']
    unknown = any(c['controller'] == 1 and (not c['code'] or c['code'] not in knowledge.cards) for c in cards if c['zone'] in ('monster', 'spell'))
    def offer(card, label, steps, reason, blocked, allowed='conditional'):
        candidates.append({'card_id': card['id'], 'code': card['code'], 'label': label, 'steps': steps[:3], 'reason': reason,
                           'status': allowed if ready and not unknown else 'conditional',
                           'if_stopped': blocked, 'if_allowed': '确认实际结果后，从新资源继续计算；不要提前扣牌或跳过响应窗口。',
                           'basis': '已核对卡文下的短段参考；不是完整引擎验证路线'})
    if state['phase'] in ('main1', 'main2'):
        for option in synchro_options(state,knowledge.cards,catalog,locks,session['preserve'])[:3]:
            target=next(c for c in cards if c['id']==option['target_id'])
            material_names=' + '.join(name(catalog,c) for c in option['material_codes'])
            offer(target,'同调续接：'+name(catalog,option['code']),
                  ['确认已回到可进行通常同调的开放状态',material_names+' 作为素材',
                   '同调成功后，再核对出场与素材触发的连锁'],
                  '当前等级相加符合已覆盖素材；'+('包含手牌调整，会消耗原本保留的资源。' if option['uses_hand'] else '使用场上已知调整。'),
                  '若召唤被无效或素材去向不同，请直接核对实际局面，不按成功同调扣记。')
            candidates[-1]['synchro']=option
            if 'no_deck_add' in locks and 'deck_add' in knowledge.rules.get(f"{target['code']}:1",{}).get('flags',[]):
                candidates[-1]['reason']+=' 当前卡组加手受限，不能预期取得出场检索收益。'
        for card in hand:
            if card['id'] in session['preserve']: continue
            base = knowledge.cards.get(card['code'], {}).get('base_code')
            if base == 54693926 and enemies:
                offer(card, '先考虑结界波处理表侧怪兽', ['核对其他魔陷限制与响应', '主要阶段发动冥王结界波', '确认处理后再启动'],
                      '不取对象；效果适用后本回合对方受到的伤害为零', '若发动或效果被阻止，重新判断保留的启动和解场')
            if base == 16387555 and state['normal_used'] == 0:
                offer(card, '通常召唤提示员作为入口', ['通常召唤提示员', '在触发窗口核对①及本回合调整限制', '根据实际手牌／卡组／墓地选择另一只调整'],
                      '通常召唤尚未使用；完整后续还取决于对方响应和可取得的调整', '若①被阻止，提示员仍可能作素材；按剩余调整与召唤条件续接')
            if base in (16509007, 89392810) and state['normal_used'] == 0:
                offer(card, '通常召唤检索入口', ['通常召唤这张怪兽', '核对①的检索／回收目标', '处理后再选择手牌调整同调'],
                      '检索范围有等级排除，不能预先假定目标在卡组', '若检索受阻，检查手中已有调整，不重复消耗通常召唤')
            if base == 78058681 and 'no_deck_add' not in locks and knowledge.used(state, f"{card['code']}:1", 0) < 2:
                offer(card, '用本家检索补足入口', ['核对仍在卡组中的本家目标', '发动本家速攻魔法并等待处理', '核对调整限制后选择后续'],
                      '可补充启动，但不把检索等同于完成展开', '检索受阻后保留的通常召唤、补点与同名次数需要分别核对')
        for card in fields:
            base = knowledge.cards.get(card['code'], {}).get('base_code')
            if card['disabled'] is not False or base not in (16387555, 16509007, 89392810, 42781164): continue
            key = f"{card['code']}:1"
            if knowledge.used(state, key, 0): continue
            prior = next((e for e in reversed(session['events']) if e.get('card', {}).get('id') == card['id'] and e.get('kind') in ('normal', 'special')), None)
            if not prior or prior['turn'] != state['turn'] or base == 16387555 and prior['kind'] != 'normal': continue
            latest=next((e for e in reversed(session['events']) if e.get('kind') in ('normal','special','activate','attack')),None)
            if latest is not prior: continue
            flags=set(knowledge.rules[key].get('flags',[]))
            if 'no_deck_add' in locks and 'deck_add' in flags and 'grave_add' not in flags: continue
            offer(card, '核对刚召唤后的①触发', ['确认仍在本次召唤的触发窗口', knowledge.rules[key]['label'], '确认实际取得资源后续接'],
                  '当前已记录召唤与实体卡，触发时点及所需目标仍须核对'+('；卡组加手受限，只能在可合法墓地回收时考虑' if 'no_deck_add' in locks and 'grave_add' in flags else ''), '该效果被阻止后保留真实场面，不能重新当作空场起手')
    damage = None
    if state['phase'] == 'battle' and ready:
        attackers = [c for c in fields if c['faceup'] and c.get('attack_position') and c.get('direct_attack_confirmed') and c['attack'] is not None and c['attacks_left'] is not None]
        if 'no_damage' in locks:
            damage = {'amount': 0, 'condition': '已记录本回合对方受到伤害为零的效果，不安排伤害斩杀'}
        elif not enemies and len(attackers) == len(fields) and fields:
            total = sum(c['attack'] * c['attacks_left'] for c in attackers)
            damage = {'amount': total, 'condition': '仅按已确认攻击资格、攻击力与次数计算直攻上限；未覆盖的卡片效果及未知响应仍可能改变结果',
                      'reaches_lp': total >= state['lp'][1]}
    if session['goal'] == 'followup': candidates.sort(key=lambda r: r['code'] == 54693926)
    needs_stats=any(c['zone']=='monster' and c['controller']==0 and (c.get('level') is None or c.get('tuner') is None) for c in cards)
    return {'candidates': candidates[:3], 'damage': damage, 'needs_stats':needs_stats,
            'note': '请在当前资源中补充实际等级和调整身份，以核对同调续接' if needs_stats else '确认实际动作后，只更新未执行的后续；未找到候选不代表无解'}


def analyze(session, knowledge, catalog, now):
    start = time.perf_counter()
    routes = opponent_routes(session, knowledge, catalog)
    threats = threat_list(session, knowledge, catalog)
    choices = response_choices(session, knowledge, catalog, now)
    good = [c for c in choices if c['status'] == 'available']
    state = session['state']; window = state['window']
    fresh = bool(window and window['expires_at'] > now)
    if session.get('needs_sync') or not all(state['known'].values()):
        primary = {'kind': 'sync', 'text': '先核对当前局面', 'reason': '手牌、场面、次数或持续限制仍有缺失；已知资料继续保留'}
    elif not fresh:
        primary = {'kind': 'observe', 'text': '继续观察，等待确认响应窗口', 'reason': '当前没有可供立即使用的窗口；旧窗口的建议已失效'}
    elif good:
        chosen = good[0]
        explanation = chosen['label']
        if chosen['response_kind'] in ('ash','belle') and any(c['response_kind'] in ('veiler','imperm') for c in good):
            explanation += '；优先使用当前适用的直接响应，保留场上无效手段处理其他威胁'
        primary = {'kind': 'response', 'text': '可考虑：' + chosen['name'], 'reason': explanation, 'choice': chosen}
    else:
        primary = {'kind': 'hold', 'text': '暂不投入已列出的干扰', 'reason': '本次已覆盖条件下没有直接推荐；展开查看费用、时点或缺失条件。保留不代表放行一定安全。'}
    own = own_turn(session, knowledge, catalog)
    if state['player'] == 0 and own['candidates'] and primary['kind'] == 'observe':
        primary = {'kind': 'own', 'text': own['candidates'][0]['label'], 'reason': own['candidates'][0]['reason']}
    return {'revision': session['revision'], 'knowledge_version': knowledge.version, 'window_id': window['id'] if fresh else None,
            'expires_at': window['expires_at'] if fresh else None, 'primary': primary, 'routes': routes, 'threats': threats,
            'choices': choices, 'own': own, 'sources': [deepcopy(source) for source in knowledge.guides['sources'] if source['id'] in {key for route in routes for key in route['source_ids']}],
            'gaps': ['对手隐藏手牌与盖卡不补全；策略参考不等于必停或必胜', '完整实时连锁及历史效果恢复未自动验证，响应窗口由人工确认'],
            'elapsed_ms': round((time.perf_counter()-start)*1000, 3)}
