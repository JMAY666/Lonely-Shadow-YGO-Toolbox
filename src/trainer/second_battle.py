"""Bounded validation of an explicit attack order, never an ATK-sum solver."""
from copy import deepcopy
import time

from modular_decisions import model
from protocol import packets, u32
from second_duel import identifier


ASSUMPTIONS = ['双方均不追加其他可选效果或响应；强制选择无法自动假定',
               '只验证指定攻击顺序和已公开目标，不搜索全部路线或宣称最优',
               '这是隔离演练，不扣实际资源，不代表实战必胜，也不认证 MD 规则']


def outcome_packets(batches):
    values = []
    for batch in batches:
        for _, message, data in packets(bytes.fromhex(batch)):
            if message == 110:
                values.append({'kind': 'attack', 'attacker': list(data[:3]), 'target': list(data[4:7])})
            elif message in (91, 92, 100):
                values.append({'kind': {91:'damage',92:'recovery',100:'lp_cost'}[message], 'player': data[0], 'amount': u32(data, 1)})
            elif message == 5:
                values.append({'kind': 'win', 'player': data[0], 'reason': data[1]})
    return values


def hidden_dependencies(initial, following):
    private = {c.get('instance_id') for c in initial['cards'] if c.get('controller') == 1 and
               (c.get('location') in (1,2,64) or c.get('location') in (4,8,32) and c.get('position',0)&10)}
    if following.get('private_cards') or following.get('uncertain'):
        return True
    if any(message == 36 for batch in following.get('batches', []) for _, message, _ in packets(bytes.fromhex(batch))):
        return True  # Shuffling set cards can erase previously known identity.
    return any(c.get('instance_id') in private and c.get('controller') == 1 and c.get('location') in (4,8,16,32)
               and c.get('position',0)&5 for c in following['state']['cards'])


def validate_order(doc, body):
    order = body.get('order')
    if not isinstance(order, list) or not 1 <= len(order) <= 12:
        raise ValueError('请指定 1–12 次攻击尝试；重复同一怪兽也必须通过原生次数检查')
    cards = {c['id']: c for c in doc['current']['cards']}
    result = []
    for row in order:
        if not isinstance(row, dict): raise ValueError('攻击顺序格式无效')
        if not isinstance(row.get('attacker'), str) or not isinstance(row.get('target'), str):
            raise ValueError('请使用当前卡片实例选择攻击者与目标')
        attacker = cards.get(row.get('attacker'))
        target = cards.get(row.get('target')) if row.get('target') != 'direct' else None
        if not attacker or attacker.get('controller') != 0 or attacker.get('location') != 4 or not attacker.get('native_instance'):
            raise ValueError('攻击者必须是当前我方怪兽区的已知原生实例')
        if row.get('target') != 'direct' and (not target or target.get('controller') != 1 or target.get('location') != 4
                or not target.get('code') or not target.get('native_instance') or target.get('position') not in (1,4)):
            raise ValueError('目标必须是对手当前已公开的表侧怪兽；不读取未知里侧身份来预测战斗')
        result.append({'attacker': attacker['native_instance'], 'attacker_code': attacker['code'],
                       'target': target['native_instance'] if target else None, 'target_code': target['code'] if target else None})
    return result


class BattleWalk:
    def __init__(self, modular, sid, base, valid):
        self.modular, self.sid, self.base, self.valid = modular, sid, base, valid
        self.current, self.path, self.events = base, [], []
        self.deadline = time.monotonic() + 22

    def answer(self, response):
        if len(self.path) >= 96 or time.monotonic() >= self.deadline:
            raise ValueError('演练达到决策或时间边界；未穷举，也不表示无解')
        if not self.valid(): raise ValueError('实际局面或规则已变化，旧演练未发布')
        path = self.path + [self.current['raw'] + ':' + response]
        following = self.modular.bridge(self.sid, self.base, path)
        if hidden_dependencies(self.base['state'], following):
            raise ValueError('后续依赖尚未公开的卡牌或随机结果；停止在此前已核对的部分')
        events = outcome_packets(following['batches'])
        # Native probe batches belong to the last submitted choice, not a
        # synthetic damage formula. Keep their original ordering.
        self.events.extend(events)
        self.path, self.current = path, following

    def settle(self, target=None):
        for _ in range(40):
            if self.current.get('ended'): return
            p = model(self.current['raw'], self.current['state'], self.current.get('effects'))
            if p['player'] == 0 and p['message'] in (10,11) and not self.current['state'].get('chain_depth'):
                return
            decline = next((c for c in p['choices'] if c['semantic']['kind'] in ('pass','no')), None) if p['message'] in (12,16) else None
            if decline:
                self.answer(decline['response']); continue
            if (target is not None and p['player'] == 0 and p['message'] == 15 and not p.get('context')
                    and not self.current['state'].get('chain_depth') and p.get('minimum') == p.get('maximum') == 1):
                choice = next((c for c in p['choices'] if (c.get('card') or {}).get('instance_id') == target), None)
                if not choice: raise ValueError('原生选择窗口未开放指定攻击目标，不能替换成另一个对象')
                self.answer(bytes([1,choice['response']]).hex()); continue
            raise ValueError('战斗中出现尚未覆盖的选择或强制效果；没有代替玩家猜测处理')
        raise ValueError('战斗未在有限步骤内结算，范围不足不表示无法斩杀')

    def run(self, order):
        completed = []
        reason, status = '', 'validated'
        try:
            p = model(self.current['raw'], self.current['state'], self.current.get('effects'))
            if p['message'] == 11:
                battle = next((c for c in p['choices'] if c['semantic']['kind'] == 'battle'), None)
                if not battle: raise ValueError('当前核心没有开放进入战斗阶段；不能用攻击力推断可攻击')
                self.answer(battle['response']); self.settle()
                if self.current.get('ended'): raise ValueError('进入战斗阶段时核心已结束对局，当前未完成指定攻击验证')
            for row in order:
                p = model(self.current['raw'], self.current['state'], self.current.get('effects'))
                if p['message'] != 10 or p['player'] != 0:
                    raise ValueError('当前不在我方可宣言攻击的原生窗口')
                choice = next((c for c in p['choices'] if c['semantic']['kind'] == 'attack' and
                               (c.get('card') or {}).get('instance_id') == row['attacker']), None)
                if not choice: raise ValueError('核心未开放这只怪兽的本次攻击：可能受表示、攻击次数或行动限制影响')
                attacker = choice['card']
                target = next((c for c in self.current['state']['cards'] if c.get('instance_id') == row['target']
                               and c.get('controller') == 1 and c.get('location') == 4), None) if row['target'] is not None else None
                if row['target'] is not None and not target: raise ValueError('指定目标已离开对手怪兽区，后续目标需要重新确认')
                start = len(self.events); before = list(self.current['state']['lp'])
                self.answer(choice['response']); self.settle(row['target'])
                events = self.events[start:]
                declarations = [e for e in events if e['kind'] == 'attack']
                expected = [1,4,target['sequence']] if target else None
                if not declarations or declarations[0]['attacker'] != [0,4,attacker['sequence']] or (
                        declarations[0]['target'] != expected if expected else declarations[0]['target'][1] != 0):
                    raise ValueError('核心攻击宣言与指定目标不一致，该段结果不作为已验证步骤')
                completed.append({**row, 'lp_before': before, 'lp_after': list(self.current['state']['lp']), 'events': deepcopy(events)})
                if self.current.get('ended'): break
        except (ValueError, TypeError, KeyError, IndexError) as error:
            reason, status = str(error), 'incomplete'
        final_lp = completed[-1]['lp_after'] if completed else list(self.base['state']['lp'])
        wins = [e for step in completed for e in step['events'] if e['kind'] == 'win']
        endings = {(e['player'],e['reason']) for e in wins}
        if len(endings) > 1: status,reason='incomplete','核心结束通知不一致，当前不作胜负判断'
        winner = wins[-1]['player'] if status == 'validated' and len(endings) == 1 else None
        won = bool(winner == 0 and final_lp[1] <= 0)
        conclusion = ('指定分支中核心记录我方获胜；不代表对手其他响应下仍然成立' if won else
                      '指定分支中核心记录我方败北' if winner == 1 else '指定分支中核心记录平局' if winner == 2 else
                      '已验证指定攻击顺序；本次未得到核心确认的斩杀结论')
        return {'status': status, 'reason': reason or conclusion,
                'conditional_lethal': won, 'steps': completed, 'requested': len(order), 'lp_before': list(self.base['state']['lp']),
                'lp_after': [max(0,v) for v in final_lp], 'core_lp_after': final_lp, 'winner': winner,
                'assumptions': ASSUMPTIONS, 'basis': 'isolated_native_replay',
                'notice': '伤害、攻击资格和次数来自当前核心实际处理；未执行其他展开，不使用攻击力相加估算'}


def preview(routes, body):
    owner, modular = routes.owner, routes.store.modular
    with routes.operations, modular.planning_lock:
        with owner.lock:
            doc = deepcopy(routes.request(body)); binding = routes.bindings.get(doc['id'])
            if not routes.valid(doc, binding, force=True) or binding.get('stage','own_turn') not in ('own_turn','battle'):
                raise ValueError('请先同步同一内置练习的我方主要阶段 1 或战斗操作点')
            if any(r['status'] != 'expired' for r in doc['current']['usage'] + doc['current']['restrictions']):
                raise ValueError('人工次数或限制备注尚未核对，暂不提供依赖这些条件的战斗演练')
            request = identifier(body.get('request_id')); order = validate_order(doc, body)
            old = next((h for h in doc.get('battle_history', []) if h['id'] == request), None)
            if old:
                if old['revision'] != doc['revision'] or old['origin']['stamp'] != doc['native_link']['stamp'] or old['order'] != body['order']:
                    raise ValueError('同一演练请求不能用于不同局面或攻击顺序')
                return owner.public(doc)
            if len(doc.get('battle_history', [])) >= 40: raise ValueError('本局战斗演练记录已满，原记录保留')
        valid = lambda: owner.load(doc['id'])['revision'] == doc['revision'] and routes.valid(owner.load(doc['id']), binding, force=True)
        walk = BattleWalk(modular, binding['sid'], modular.state(binding['sid']), valid)
        result = walk.run(order)
        with owner.lock:
            routes.request(body)
            if not valid(): raise ValueError('实际局面或规则已变化，演练结果未发布')
            updated = deepcopy(owner.load(doc['id']))
            updated.setdefault('battle_history', []).append({'id': request, 'revision': doc['revision'], 'created_ms': owner.now(),
                'origin': deepcopy(doc['native_link']), 'order': deepcopy(body['order']), 'result': result})
            owner.save(updated)
            return owner.public(updated)
