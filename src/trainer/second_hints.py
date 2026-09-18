"""Conditional, auditable use/hold comparisons over player-known observations."""
from copy import deepcopy
import uuid

from second_duel import identifier, number, words, WINDOW_MS
from second_hint_proof import HintProof, card_identity
from second_rules import (EFFECTS, RESPONDERS, ASH, IMPERM, OGRE, ROLE_LABELS, PROTECTIONS,
                          REVISION, options, effect_for, usage_status, usage_key, set_usage)


class SecondHints:
    def __init__(self, owner):
        self.owner = owner
        self.proof = HintProof(owner.store)

    def options(self):
        return options(self.owner.store.catalog.cards)

    def card(self, doc, key):
        card = next((c for c in doc['current']['cards'] if c['id'] == key and c.get('code')), None)
        if not card:
            raise ValueError('请选择当前已知的卡牌实例；未知牌不能被当作已知效果来源')
        return card

    def apply(self, doc, kind, payload):
        state = doc['current']
        if kind == 'effect_outcome':
            action = next((a for a in state.get('effect_actions', []) if a['id'] == payload.get('action_id')), None)
            outcome = payload.get('outcome')
            note = words(payload.get('note', ''), 500)
            if not action or outcome not in ('resolved', 'not_applied', 'activation_negated', 'effect_negated'):
                raise ValueError('请关联已经记录的具体发动，并填写其实际处理结果')
            if action['outcome'] not in ('pending', outcome) and not note:
                raise ValueError('更正已有处理结果需要说明依据')
            effect = EFFECTS.get(action['effect_id'])
            if not effect:
                raise ValueError('旧记录的效果定义已变化；原始记录保留，请先核对资料')
            key = usage_key(effect, action['player'], action['card_id'])
            counter = state.get('effect_counts', {}).get(key, {})
            action['outcome'] = outcome
            if counter.get('action_id') == action['id'] and action['turn'] == state['turn']:
                set_usage(state, effect, action['player'], action['card_id'], 'used', outcome, action['id'])
            state['stale_reason'] = '实际处理结果已补充；较早动作不会覆盖较新的次数记录，请核对当前窗口'
            return '补充具体发动结果：' + effect['label'] + '；' + {'resolved': '已结算', 'not_applied': '已结算但未适用', 'activation_negated': '发动被无效', 'effect_negated': '效果被无效'}[outcome] + ('；' + note if note else '')
        card = self.card(doc, payload.get('card_id'))
        if kind == 'resource_role':
            if card['controller'] != 0 or card['location'] != 2 or payload.get('role') not in ROLE_LABELS:
                raise ValueError('请为当前我方手牌填写保留用途')
            note = words(payload.get('note', ''), 500)
            if payload['role'] == 'key' and not note:
                raise ValueError('请说明需要保留的起动点、素材或费用用途')
            state.setdefault('resource_roles', {})[card['id']] = {'role': payload['role'], 'note': note, 'source': 'user_confirmed'}
            state['stale_reason'] = '手牌保留用途已更新，请核对当前局面'
            return '核对手牌用途：' + ROLE_LABELS[payload['role']] + ('；' + note if note else '')
        effect = effect_for(card['code'], payload.get('effect_id'))
        if kind in ('effect_count', 'effect_observed'):
            note = words(payload.get('note', ''), 500)
            status = payload.get('status', 'unknown')
            outcome = None
            if kind == 'effect_observed':
                outcome = payload.get('outcome')
                if outcome not in ('pending', 'resolved', 'not_applied', 'activation_negated', 'effect_negated'):
                    raise ValueError('请选择实际发动后的已知处理状态')
                if payload.get('confirmed') is not True:
                    raise ValueError('请确认此效果确实已经发动；选择建议不等于实际发动')
                status = 'used'
            elif status not in ('unused', 'used', 'unknown'):
                raise ValueError('请选择尚未使用、已经使用或未知')
            if (status == 'unused' and usage_status(state, effect, card['controller'], card['id']) == 'used'
                    and not note):
                raise ValueError('更正已记录的使用次数必须说明依据；原历史不会删除')
            if kind == 'effect_observed':
                actions = state.setdefault('effect_actions', [])
                if len(actions) >= 300:
                    raise ValueError('本局具体发动记录达到容量上限；原始记录保留')
                action = {'id': uuid.uuid4().hex, 'card_id': card['id'], 'effect_id': payload['effect_id'],
                          'player': card['controller'], 'turn': state['turn'], 'outcome': outcome, 'source': 'user_confirmed'}
                actions.append(action)
                # A new activation that was itself negated cannot refund another
                # copy's already-recorded activation. Corrections have their own
                # explicit path; later outcomes bind to this exact action ID.
                previous = state.get('effect_counts', {}).get(usage_key(effect, card['controller'], card['id']), {})
                refund_other = (effect['limit'] == 'activate_name_turn' and outcome == 'activation_negated'
                                and previous.get('turn') == state['turn'] and previous.get('status') == 'used')
                if not refund_other:
                    set_usage(state, effect, card['controller'], card['id'], status, outcome, action['id'])
            else:
                set_usage(state, effect, card['controller'], card['id'], status)
            state['stale_reason'] = '效果使用情况已变化，请核对资源、费用和当前窗口'
            status_text = {'unused': '尚未使用', 'used': '已经使用', 'unknown': '未知'}[usage_status(state, effect, card['controller'], card['id'])] if effect['limit'] != 'none' else '无同名每回合一次限制'
            return ('实际发动：' if kind == 'effect_observed' else '核对次数：') + effect['label'] + '；' + status_text + '；' + effect['limit_text'] + ('；' + note if note else '')
        if kind != 'hint_window':
            raise ValueError('结构化提示操作无效')
        if state.get('stale_reason'):
            raise ValueError('请先保存当前局面核对结果，再确认响应窗口')
        if card['controller'] != 1 or effect.get('responder'):
            raise ValueError('本期窗口仅选择对手已公开的指定效果')
        if payload.get('confirmed') is not True:
            raise ValueError('请确认对手已实际发动此效果，且当前正等待我方响应')
        link, top = payload.get('link'), payload.get('top')
        for value in (link, top):
            if value is not None:
                number(value, 1, 32, '连锁序号')
        if link is not None and top is not None and link > top:
            raise ValueError('所选效果的连锁序号不能大于当前最后连锁')
        speed = payload.get('speed')
        if speed is not None:
            number(speed, 1, 3, '最后连锁的咒文速度')
        protections = payload.get('protections', [])
        if (not isinstance(protections, list) or len(protections) > len(PROTECTIONS)
                or any(type(p) is not str or p not in PROTECTIONS for p in protections)):
            raise ValueError('保护属性无效')
        checked = payload.get('protections_checked', False)
        if type(checked) is not bool:
            raise ValueError('保护核对标记无效')
        for key, choices in {'other_rules': ('none', 'present', 'unknown'), 'grave_rule': ('normal', 'monster_banish', 'unknown'),
                             'objective': ('balanced', 'stop_effect', 'remove_body', 'preserve'),
                             'environment': ('local', 'external', 'unknown')}.items():
            if payload.get(key) not in choices:
                raise ValueError('请填写规则环境、附加影响和比较目标')
        if doc['input']['platform'] != 'manual' and payload['environment'] == 'local':
            raise ValueError('外部平台记录不能标为内置规则实战；请使用外部平台参考范围')
        native = state.get('native_window')
        if doc.get('native_link') and (not native or not native.get('recognized') or any(
                payload.get(key) != native.get(key) for key in ('card_id', 'effect_id', 'link', 'top', 'speed'))):
            raise ValueError('所选效果或连锁与当前原生响应窗口不符；未覆盖的效果不能套用已有案例')
        state['window'] = {'id': uuid.uuid4().hex, 'label': effect['label'], 'source': 'user_confirmed', 'response_player': 0,
                           'created_ms': self.owner.now(), 'expires_ms': self.owner.now() + WINDOW_MS,
                           'analysis': {'actor': card['id'], 'effect': payload['effect_id'], 'link': link, 'top': top,
                                        'speed': speed, 'protections': sorted(set(protections)), 'protections_checked': checked,
                                        **{k: payload[k] for k in ('other_rules', 'grave_rule', 'objective', 'environment')}}}
        return '确认结构化响应窗口：' + effect['label']

    def current(self, doc, hint, proof=None, force=False):
        window = doc['current'].get('window')
        return bool(not self.owner.status(doc) and window and window.get('analysis')
                    and hint.get('revision') == doc['revision'] and hint.get('window_id') == window['id']
                    and window['expires_ms'] > self.owner.now() and hint.get('registry') == REVISION
                    and hint.get('rules_stamp') == (proof or self.proof.check(force=force))['stamp'])

    def public(self, doc):
        history = doc.get('advice_history') or []
        if not history:
            return None
        hint = deepcopy(history[-1])
        hint.pop('known_state', None)
        hint['current'] = self.current(doc, hint)
        return hint

    def generate(self, body):
        owner = self.owner
        with owner.lock:
            doc = owner.load(body.get('id'))
            if body.get('round_id') != doc['input']['round_id'] or body.get('revision') != doc['revision']:
                raise ValueError('局次或局面已变化，请按当前版本重新生成提示')
            request = identifier(body.get('request_id'))
            old = next((h for h in doc.get('advice_history', []) if h['id'] == request), None)
            if old:
                if old['revision'] != body['revision']:
                    raise ValueError('此请求已用于另一局面版本')
                return owner.public(doc)
            if doc['closed']:
                raise ValueError('已结束记录只能回看已有提示')
            if len(doc.get('advice_history', [])) >= 150:
                raise ValueError('本局提示记录达到上限；实际记录保留，不覆盖旧提示')
            proof = self.proof.check(force=True)
            hint = self.evaluate(doc, proof)
            if self.proof.check(force=True)['stamp'] != proof['stamp']:
                raise ValueError('核对期间规则资料发生变化；提示未保存，请按当前资源重试')
            native_error = owner.routes.connection_error(doc, force=True)
            if native_error: raise ValueError(native_error)
            hint.update(id=request, revision=doc['revision'], round_id=doc['input']['round_id'], registry=REVISION,
                        rules_stamp=proof['stamp'], created_ms=owner.now(), known_state=deepcopy(doc['current']),
                        decisions=[])
            if doc.get('native_link'): hint['native_origin'] = deepcopy(doc['native_link'])
            updated = deepcopy(doc)
            updated.setdefault('advice_history', []).append(hint)
            # Advice is a separate journal: it neither changes resources nor
            # extends the response window or advances the observation revision.
            owner.save(updated)
            return owner.public(updated)

    def choose(self, body):
        owner = self.owner
        with owner.lock:
            doc = owner.load(body.get('id'))
            if body.get('round_id') != doc['input']['round_id'] or body.get('revision') != doc['revision']:
                raise ValueError('局面已变化，旧建议不能继续采用')
            hint = next((h for h in doc.get('advice_history', []) if h['id'] == body.get('advice_id')), None)
            if not hint or not self.current(doc, hint, force=True):
                raise ValueError('建议或响应窗口已过期，请重新核对')
            row = next((r for r in hint['items'] if r['instance_id'] == body.get('card_id')), None)
            if not row or row['recommendation'] == 'information':
                raise ValueError('信息不足的提示不能作为确定建议采用；仍可单独记录玩家实际选择')
            choice = body.get('choice')
            if choice not in ('use', 'hold') or choice == 'use' and row['conditions'] != 'met':
                raise ValueError('当前条件不支持此建议选择')
            event_id = identifier(body.get('request_id'))
            previous = next((d for d in hint['decisions'] if d['id'] == event_id), None)
            if previous:
                if previous['choice'] != choice or previous['card_id'] != row['instance_id']:
                    raise ValueError('同一选择请求的内容不一致')
                return owner.public(doc)
            if len(hint['decisions']) >= 50:
                raise ValueError('本条建议选择记录过多，请核对重复提交')
            updated = deepcopy(doc)
            target = next(h for h in updated['advice_history'] if h['id'] == hint['id'])
            target['decisions'].append({'id': event_id, 'choice': choice, 'card_id': row['instance_id'],
                                         'time_ms': owner.now(), 'basis': 'player_intention_not_execution'})
            owner.save(updated)
            return owner.public(updated)

    def evaluate(self, doc, proof):
        state, window = doc['current'], doc['current'].get('window') or {}
        analysis = window.get('analysis') or {}
        effect = EFFECTS.get(analysis.get('effect'))
        actor = next((c for c in state['cards'] if c['id'] == analysis.get('actor')), None)
        common = []
        if self.owner.status(doc):
            common.append(self.owner.status(doc))
        if not analysis:
            common.append('当前只有文字记录或没有窗口；请选定公开卡片的具体效果与连锁')
        if not window or window.get('expires_ms', 0) <= self.owner.now():
            common.append('响应窗口已关闭或过期')
        if (state['turn'], state['turn_player'], state['phase']) != (1, 1, 'main1'):
            common.append('本期案例只覆盖对手首回合主要阶段 1；其他时点尚未覆盖')
        if any(lp <= 0 for lp in state['lp']):
            common.append('LP 状态超出本期响应案例范围，请核对对局是否已经结束')
        if analysis.get('link') is None or analysis.get('top') is None:
            common.append('当前连锁资料不完整')
        elif (analysis['link'], analysis['top']) != (1, 1):
            common.append('当前多重连锁超出本期单一发动窗口；追加效果需要单独复验')
        elif effect and effect.get('case') and analysis.get('speed') not in (None, 1):
            common.append('所选基准效果为一速；填报的最后连锁速度与该单一窗口不一致')
        if analysis.get('environment') != 'local':
            common.append('外部平台或规则环境尚未验收；以下只作本地案例比较')
        if analysis.get('other_rules') != 'none':
            common.append('尚未排除影响响应的其他公开限制；附加规则不在本期完整验证范围')
        if not analysis.get('protections_checked'):
            common.append('尚未核对无效、取对象、破坏及效果抗性等保护')
        if any(r['status'] != 'expired' for r in state['usage'] + state['restrictions']):
            common.append('仍有未结构化的次数或限制备注，请核对并转换；不能从文字猜测规则')
        if not effect or not effect.get('case'):
            common.append('该具体效果缺少本期可比较的原生案例，不能据此声称无解')
        if not actor or actor.get('controller') != 1 or not actor.get('code'):
            common.append('缺少对手已公开的效果来源实例')
        elif effect and (actor['code'] != effect['code'] or actor['location'] != effect['location']):
            common.append('效果来源的当前区域或身份与所选效果不符')
        elif actor['location'] in (4, 8) and actor.get('position') not in (1, 4):
            common.append('效果来源的表侧表示尚未核对')
        if proof['status'] != 'matched':
            common.append(proof['reason'])
        protections = analysis.get('protections') or []
        if protections:
            common.append('存在额外保护或无效状态；本期未在这些附加状态下完整复验')
        if analysis.get('grave_rule') != 'normal':
            common.append('送墓替代状态未核对或超出当前原生案例范围')
        groups = {}
        for card in state['cards']:
            if card['controller'] == 0 and card['location'] == 2 and card.get('code') in RESPONDERS:
                groups.setdefault(card['code'], []).append(card)
        items = []
        roles = state.get('resource_roles') or {}
        for code, copies in groups.items():
            copies.sort(key=lambda c: {'free': 0, 'unknown': 1, 'key': 2}[roles.get(c['id'], {}).get('role', 'unknown')])
            card = copies[0]
            rule = EFFECTS[RESPONDERS[code]]
            unknown, blocked = list(common), []
            native = state.get('native_window') if doc.get('native_link') else None
            if native and not any(r['card_id'] == card['id'] and r['effect_id'] == RESPONDERS[code] for r in native['responders']):
                blocked.append('当前原生菜单没有开放此手牌效果；人工条件不能替代引擎权限')
            count = usage_status(state, rule, 0, card['id'])
            if count == 'unknown':
                unknown.append('尚未核对此卡名本回合的使用次数')
            elif count == 'used':
                blocked.append('此卡名效果本回合已使用；发动或效果无效不退还使用次数')
            if analysis.get('speed') is None:
                unknown.append('尚未核对最后连锁的咒文速度')
            elif analysis['speed'] == 3:
                blocked.append('这些响应不能连锁咒文速度 3 的效果')
            if code in (ASH, OGRE):
                if analysis.get('link') is None or analysis.get('top') is None:
                    unknown.append('尚未核对是否能直接连锁所选效果')
                elif analysis['link'] != analysis['top']:
                    blocked.append('需要直接连锁该效果，不能隔着新的连锁块响应较早效果')
            if effect and code == ASH and not set(effect['attributes']) & {'search', 'draw', 'deck_materials'}:
                blocked.append('所选效果不包含灰流丽能够响应的牌组处理；生成衍生物不等于从牌组特召')
            if code == IMPERM:
                if any(c['controller'] == 0 and c['location'] in (4, 8) for c in state['cards']):
                    blocked.append('我方场上已有卡，不能按本期手牌发动方式使用无限泡影')
                if actor and actor['location'] != 4:
                    blocked.append('所选来源不是场上表侧怪兽；不能以烙印融合这张魔法为对象')
                if 'target' in protections:
                    blocked.append('已确认对象不能成为效果对象')
            if code == OGRE:
                if actor and actor['location'] != 4:
                    blocked.append('本期所选魔法的卡片发动不满足幽鬼兔的响应条件')
                if analysis.get('grave_rule') == 'monster_banish':
                    blocked.append('必须送墓的费用不能在怪兽送墓改为除外时支付')
                if effect and effect.get('case') == 'moye' and actor and any(c['controller'] == 1 and c['location'] == 4 and c['id'] != actor['id'] for c in state['cards']):
                    unknown.append('对手还有其他怪兽；当前案例没有评估替代素材，不能据此认为破坏莫邪就阻断其同调展开')
            for relevant in (actor, card):
                if relevant and relevant.get('code'):
                    frozen = doc.get('catalog', {}).get(str(relevant['code']))
                    current = self.owner.store.catalog.cards.get(relevant['code'])
                    if not frozen or not current or card_identity(frozen) != card_identity(current):
                        unknown.append('本局冻结卡文与当前规则资料不同，请先核对适用版本')
            case_id = f'{effect["case"]}_{rule["responder"]}' if effect and effect.get('case') else None
            case = proof.get('cases', {}).get(case_id)
            if not case:
                unknown.append('缺少这一响应组合的原生案例')
            elif not case.get('activated'):
                blocked.append('对应原生案例没有此项合法响应；不能只凭条件清单把它升级为可用')
            role = roles.get(card['id'], {'role': 'unknown', 'note': ''})
            condition = 'blocked' if blocked else 'unknown' if unknown else 'met'
            preference = 'information'
            why = '信息不足，先查看交与不交的条件差异'
            if condition == 'blocked':
                preference, why = 'hold', '当前指定响应不满足已列规则条件；保留卡片，其他响应对象和后续窗口未穷举'
            elif condition == 'met':
                if role['role'] == 'unknown':
                    unknown.append('未核对此卡是否还是必须保留的起动点、素材或费用')
                elif role['role'] == 'key' or analysis['objective'] == 'preserve':
                    preference, why = 'hold', '按已确认的保留用途或保留资源目标，暂不投入这张卡'
                elif code == ASH and effect['case'] == 'aluber' and analysis['objective'] == 'balanced':
                    why = '现在交可阻止检索；保留可等待烙印融合等窗口。对手后续未知，不能固定为检索必交灰'
                elif code == OGRE and effect['case'] == 'aluber' and analysis['objective'] != 'remove_body':
                    preference, why = 'hold', '幽鬼兔能移除阿鲁伯本体，但本次检索仍会处理；当前目标不是单纯移除本体'
                elif analysis['objective'] == 'remove_body' and code != OGRE:
                    preference, why = 'hold', '这项响应无效效果但不移除本体，不符合当前移除目标'
                elif analysis['objective'] == 'stop_effect' and code == OGRE:
                    preference, why = 'hold', '破坏不会无效这里已经发动的效果，不符合当前阻止处理的目标'
                else:
                    preference = 'use'
                    why = '在已确认条件及无追加响应的案例中，可以阻止当前关键收益'
                    if code == OGRE:
                        why = '移除莫邪后，原生案例不能立即用莫邪＋衍生物同调召唤赤霄；衍生物仍会生成，补点未知'
            # Rule/platform/resource uncertainty always keeps the primary advice
            # informational, even if a local incompatibility was also identified.
            if common:
                preference = 'information'
            items.append({'instance_id': card['id'], 'code': code, 'copies': len(copies), 'effect_id': RESPONDERS[code],
                          'label': rule['label'], 'attributes': rule['attributes'], 'targeted': rule['targeted'],
                          'target_id': actor['id'] if actor else None, 'cost': rule['cost'], 'limit': rule['limit_text'],
                          'conditions': condition, 'blocked': blocked, 'missing': list(dict.fromkeys(unknown)),
                          'recommendation': preference, 'reason': why, 'role': deepcopy(role), 'case_id': case_id,
                          'example': 'passed' if case else 'unverified', 'example_result': deepcopy(case),
                          'if_use': self.use_text(effect, rule, case), 'if_hold': self.hold_text(effect, rule),
                          'exchange': {'actual': '尚未记录这次响应的实际消耗或移除', 'expected_hand_committed': case.get('responder_cards_committed') if case else None,
                                       'expected_opponent_removed': int(case['actor_removed']) if case else None,
                                       'prevented_deck_gain': (effect.get('deck_gain') if case.get('negation') and effect else 0) if case else None},
                          'sources': [rule['source'], *([effect['source']] if effect else [])]})
        # Prefer the equally applicable monster-targeted answer and preserve Ash
        # for a different effect class. This is conditional, not a deck lock-in.
        if effect and effect.get('case') == 'aluber' and analysis.get('objective') == 'balanced':
            imperm = next((r for r in items if r['code'] == IMPERM and r['recommendation'] == 'use'), None)
            ash = next((r for r in items if r['code'] == ASH and r['conditions'] == 'met' and r['role']['role'] == 'free'), None)
            if imperm and ash and not common:
                ash.update(recommendation='hold', reason='已有条件满足的无限泡影可处理当前怪兽；保留灰流丽应对不同类型的后续效果，后续是否出现仍未知')
        return {'window_id': window.get('id'), 'expires_ms': window.get('expires_ms', 0), 'items': items,
                'missing': list(dict.fromkeys(common)), 'effect': deepcopy(effect),
                'opponent_candidates': deepcopy(effect.get('candidates', [])) if effect else [],
                'candidate_basis': effect.get('candidate_basis', '对手卡组尚未确定') if effect else '对手卡组尚未确定',
                'scope': ('规则状态来自同一内置练习的完整重放；具体对象、处理与策略仍按已列条件和有限案例比较' if doc.get('native_link') else
                          '仅比较已列卡片、所选效果和有限本地案例；当前记录局面尚未完整重建为引擎状态'),
                'assumptions': ['案例中双方不追加其他响应，相关效果按记录处理', '对手未公开手牌、盖卡、牌序和后续补点保持未知'],
                'coverage': '仅覆盖手牌中的灰流丽、无限泡影、幽鬼兔；其他合法响应未穷举',
                'engine_proof': {'status': proof['status'], 'reason': proof['reason']}}

    @staticmethod
    def use_text(effect, rule, case):
        if not effect or not case:
            return '缺少可复核案例，尚不能预测处理结果'
        if not case.get('activated'):
            return '当前指定响应在基准案例中不能发动；不代表以后所有窗口都不能使用'
        if rule['responder'] == 'ogre':
            if effect['case'] == 'moye':
                return '投入一张手牌破坏莫邪，生成衍生物的处理仍继续；案例中不能立即用原本的莫邪＋衍生物同调召唤赤霄。这不是无效事件'
            return '投入一张手牌破坏阿鲁伯，检索仍会处理。这不是无效事件，不能算成阻止获得一张检索卡'
        return '投入一张手牌，在无追加响应的案例中无效效果，阻止' + effect['gain'] + '；不因此额外破坏来源卡'

    @staticmethod
    def hold_text(effect, rule):
        gain = effect.get('gain', '本次效果') if effect else '本次效果'
        return '保留这张手牌；在无其他响应的案例中，对手继续获得' + gain + '。保留后的下一次使用窗口并不保证出现'
