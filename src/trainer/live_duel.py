"""Private, revision-checked live-assistance workspaces; no game input APIs."""
from copy import deepcopy
import re
import threading
import time

from live_duel_state import initial, identity, apply_event, checked_cards, PHASES, ZONES, GOALS
from live_duel_analysis import Knowledge, analyze, name
from opening_analysis import digest, analyze_routes
from live_duel_state import active_locks
from live_synchro import options as synchro_options
import ygopro_live


class LiveDuel:
    def __init__(self, store, read, write, now):
        self.store, self.read, self.write, self.now = store, read, write, now
        self.lock = threading.RLock(); self.sessions = {}; self.run = identity()
        self._knowledge = None; self._catalog = None
        self._plans_key = None; self._plans = []

    def knowledge(self):
        if self._catalog is not self.store.catalog.cards:
            self._knowledge = Knowledge(self.store.catalog.cards); self._catalog = self.store.catalog.cards
        return self._knowledge

    def path(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier): raise ValueError('对局辅助会话无效')
        return self.store.root/'live-assistance'/f'{identifier}.json'

    def get(self, identifier):
        path = self.path(identifier)
        if identifier not in self.sessions:
            value = self.read(path)
            if not isinstance(value, dict) or value.get('schema') != 1 or value.get('id') != identifier:
                raise ValueError('对局辅助记录损坏或版本不支持；原文件保留')
            value = deepcopy(value); value['state']['window'] = None; value['needs_sync'] = True
            self.sessions[identifier] = value
        return self.sessions[identifier]

    def save(self, value):
        self.write(self.path(value['id']), value)
        self.sessions[value['id']] = value

    def start(self, body):
        deck, frozen, supplemental, source = self.store.opening_workspace.inputs(body.get('input', {}))
        if not frozen: raise ValueError('请先确认完整后攻起手')
        if supplemental: raise ValueError('请以原始起手建立本局，再在当前资源中核对补充牌')
        if body.get('format', 'OCG') != 'OCG': raise ValueError('实战规则首版仅覆盖 OCG，其他环境可继续查看起手资料')
        capture_id = None
        if source['kind'] == 'automatic':
            attached = self.store.ygopro_capture.attached
            if not attached or attached.get('platform', 'ygopro') != 'ygopro': raise ValueError('首版自动局面辅助仅支持 YGOPro')
            capture_id = attached['capture_id']
        value = {'schema': 1, 'id': identity(), 'run': self.run, 'revision': 1, 'created_at': self.now(),
                 'updated_at': self.now(), 'deck': deepcopy(deck), 'frozen': list(frozen), 'source': source,
                 'opening_input': deepcopy(body['input']), 'capture_id': capture_id, 'format': 'OCG',
                 'goal': 'steady', 'preserve': [], 'events': [], 'receipts': {}, 'closed': False,
                 'needs_sync': True, 'state': initial(deck, frozen), 'observation': None, 'observed_key': None}
        value['knowledge_version']=self.knowledge().version
        with self.lock:
            self.save(value)
            return self.public(value)

    def ensure_source(self, value):
        if value['source']['kind'] != 'automatic': return
        self.store.opening_workspace.automatic_input(value['opening_input'])
        if not self.store.ygopro_capture.attached or self.store.ygopro_capture.attached['capture_id'] != value['capture_id']:
            raise ValueError('连接已变化，请从本局起手重新进入辅助')

    def public(self, value):
        current = deepcopy(value)
        knowledge = self.knowledge()
        if current['state']['window'] and current['state']['window'].get('knowledge_version') != knowledge.version:
            current['state']['window'] = None
        result = analyze(current, knowledge, self.store.catalog.cards, self.now())
        result['references'] = self.plan_references(current, knowledge)
        # Mutation guards use monotonic revisions; wall-clock expiry is only an
        # additional presentation fence for manually confirmed response windows.
        cards = current['state']['cards']
        for card in cards: card['name'] = name(self.store.catalog.cards, card['code'])
        if current['observation']:
            for card in current['observation']['cards']: card['name'] = name(self.store.catalog.cards, card['code'])
        current.pop('receipts'); current.pop('opening_input'); current.pop('run')
        return {'session': current, 'analysis': result, 'options': {'phases': PHASES, 'zones': ZONES, 'goals': GOALS,
                'effects': [{'key': r['key'], 'code': r['code'], 'number': r['number'], 'name': r['name'],
                             'label': r['label'], 'locks': r.get('locks', []), 'cost':r.get('cost'), 'source': r['source']}
                            for r in knowledge.rules.values()]}}

    def plan_references(self, current, knowledge):
        """Reuse existing recordings without pretending to restore real history."""
        state = current['state']; root = getattr(self.store, 'plans', None)
        if state['player'] != 0 or not root: return []
        paths = sorted(root.glob('*.json'))
        stamp = [(p.name,p.stat().st_mtime_ns,p.stat().st_size) for p in paths]
        if stamp != self._plans_key:
            plans = []
            for path in paths:
                try:
                    plan = self.read(path)
                    if isinstance(plan,dict) and plan.get('id'): plans.append(plan)
                except (ValueError,OSError): continue
            self._plans, self._plans_key = plans, stamp
        hand = [c['code'] for c in state['cards'] if c['controller']==0 and c['zone']=='hand']
        records = analyze_routes(self._plans, current['deck'], hand, self.store.catalog.cards, 8)
        original_start = (state['normal_used']==0 and not active_locks(state,knowledge.rules)
                          and not any(c['controller']==0 and c['zone'] in ('monster','spell','grave','banished') for c in state['cards'])
                          and not any(u['player']==0 and u['turn']==state['turn'] for u in state['used']))
        return [{'key':r['key'],'title':r['sources'][0]['name'],'sources':r['sources'],
                 'condition':r['condition'],'steps':r['steps'][:3], 'required_hand':r['required_hand'],
                 'state_fit':'原起点资源可参考' if original_start else '当前已有消耗，不能从原起点重做',
                 'engine_verified_current':False,
                 'note':'录制方案的条件参考；对方场面及完整实战历史未复原，不作为当前确定操作。'}
                for r in records['routes'][:3]]

    def command(self, body):
        if body.get('action') == 'start': return self.start(body)
        with self.lock:
            value = self.get(body.get('id'))
            if value.get('knowledge_version') != self.knowledge().version:
                value = apply_event(value, {'operation':'gap'}, self.store.catalog.cards, self.knowledge().rules, self.now(), source='system')
                value['events'][-1]['note']='资料版本已变化，请重新核对次数与限制；原始事实保留'
                value['knowledge_version']=self.knowledge().version
                self.save(value)
            if body.get('action') == 'read':
                try: self.ensure_source(value)
                except ValueError as error:
                    if not value['needs_sync'] or value['state']['window']:
                        value = apply_event(value, {'operation': 'gap'}, self.store.catalog.cards, self.knowledge().rules, self.now(), source='system')
                        value['observation_error'] = str(error); self.save(value)
                    return self.public(value)
                return self.public(value)
            request = body.get('request_id')
            if not isinstance(request, str) or not re.fullmatch('[a-f0-9-]{16,64}', request): raise ValueError('请求标识无效')
            fingerprint = digest({k: v for k, v in body.items() if k != 'revision'})
            previous = value['receipts'].get(request)
            if previous:
                if previous != fingerprint: raise ValueError('同一请求标识不能用于另一项操作')
                return self.public(value)
            if value['closed']: raise ValueError('本局辅助已结束，历史记录保留')
            if type(body.get('revision')) is not int or body['revision'] != value['revision']: raise ValueError('局面已变化，请核对最新状态后再提交；输入保留')
            if body.get('operation') != 'close': self.ensure_source(value)
            if body.get('action') == 'observe':
                if not value['capture_id']: raise ValueError('请在自动模式连接 YGOPro 后使用实时公开局面读取')
                try:
                    observation = ygopro_live.capture(self.store.ygopro_capture, value['capture_id'])
                    if observation['turn'] < value['state']['turn'] or value['source']['kind']=='automatic' and observation.get('order')!='second':
                        raise ValueError('回合或先后攻与本局不一致，请从新局起手重新进入')
                except ValueError as error:
                    updated = apply_event(value, {'operation': 'gap'}, self.store.catalog.cards, self.knowledge().rules, self.now(), source='ygopro_public_snapshot')
                    updated['observation_error'] = str(error)
                else:
                    updated = deepcopy(value); key = digest(observation)
                    if key == value.get('observed_key'): return self.public(value)
                    if key != value.get('observed_key'):
                        updated['observation'] = observation; updated['observed_key'] = key
                        updated['needs_sync'] = True; updated['state']['window'] = None
                        updated['state'].update({k:deepcopy(observation[k]) for k in ('turn','player','lp','cards','opponent_hand')})
                        updated['state'].update(phase='unknown',normal_used=None,spell_trap_used=None)
                        updated['state']['known'].update(board=True, hand=all(c['code'] for c in observation['cards'] if c['controller']==0 and c['zone']=='hand'), usage=False, limits=False)
                        previous_visible={(c['id'],c['code']) for c in value['state']['cards'] if c['controller']==1 and c['code']}
                        for card in observation['cards']:
                            if card['controller']==1 and card['code'] and (card['id'],card['code']) not in previous_visible:
                                updated['events'].append({'id':identity(),'operation':'observation','kind':'reveal',
                                    'card':deepcopy(card),'effect':0,'outcome':'observed','at':self.now(),'turn':observation['turn'],
                                    'source':'ygopro_public_snapshot','note':'观察到公开卡；不据此推断召唤、发动或费用过程'})
                        updated['preserve']=[i for i in updated['preserve'] if any(c['id']==i for c in observation['cards'])]
                        if len(updated['events'])>5000: raise ValueError('本局记录已达上限；请结束本局，原记录保留')
                    updated['revision'] += 1; updated['updated_at'] = self.now(); updated['observation_error'] = ''
            elif body.get('action') == 'update':
                if value.get('run') != self.run and body.get('operation') not in ('snapshot', 'close'):
                    raise ValueError('应用已重启，请重新核对局面；不恢复旧响应窗口')
                if body.get('operation')=='synchro':
                    state=value['state'];knowledge=self.knowledge()
                    if any(e.get('kind')=='activate' and e.get('outcome')=='pending' and e['turn']==state['turn'] for e in value['events']):
                        raise ValueError('当前仍有待确认处理的发动，请先补记结果')
                    choices=synchro_options(state,knowledge.cards,self.store.catalog.cards,active_locks(state,knowledge.rules),value['preserve'])
                    chosen=next((c for c in choices if c['target_id']==body.get('target_id') and c['materials']==body.get('materials')),None)
                    if not chosen or body.get('confirmed') is not True: raise ValueError('素材或目标已变化，且需要确认游戏中已同调成功')
                    if not all(state['known'].values()) or value['needs_sync']: raise ValueError('先核对当前资源、次数和限制')
                    updated=deepcopy(value);new=updated['state'];target=next(c for c in new['cards'] if c['id']==chosen['target_id'])
                    for card in new['cards']:
                        if card['id'] in chosen['materials']:card.update(zone=chosen['destination'],controller=card['owner'],faceup=True)
                    # Successful summoning alone does not prove current effect
                    # status, modified level or attack eligibility.
                    target.update(zone='monster',faceup=True,disabled=None,attack_position=False,
                                  level=None,tuner=None,direct_attack_confirmed=False,attack=None,attacks_left=None)
                    new['window']=None
                    updated['events'].append({'id':identity(),'operation':'synchro','kind':'special','card':deepcopy(target),'effect':0,
                        'materials':chosen['materials'],'outcome':'resolved','turn':new['turn'],'at':self.now(),'source':'manual',
                        'note':'用户确认游戏中已完成同调；不自动发动素材与出场效果'})
                    updated['revision']+=1;updated['updated_at']=self.now()
                else: updated = apply_event(value, body, self.store.catalog.cards, self.knowledge().rules, self.now())
                updated['state']['cards'] = checked_cards(updated['state']['cards'], value['deck'], self.store.catalog.cards)
                if updated['state']['window']: updated['state']['window']['knowledge_version'] = self.knowledge().version
                updated['run'] = self.run
            else: raise ValueError('对局辅助操作无效')
            updated['receipts'][request] = fingerprint
            if len(updated['receipts']) > 5001: raise ValueError('本局请求达到上限，请结束；原记录保留')
            self.save(updated)
            return self.public(updated)
