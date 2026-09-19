"""Private, observed BO1 second-player state; never a substitute rules engine.

The immutable opening and a revisioned observation journal have separate owners
from saved plans and native training sessions. No operation here sends game input.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import re
import threading
import time
import uuid

from duel import validate_hand


ZONES = {1: '牌组', 2: '手牌', 4: '怪兽区', 8: '魔陷区', 16: '墓地', 32: '除外', 64: '额外牌组', 128: '叠放素材'}
PHASES = ('unknown', 'draw', 'standby', 'main1', 'battle', 'main2', 'end')
PLATFORMS = ('manual', 'ygopro', 'ygopro2', 'mdpro3', 'masterduel')
WINDOW_MS = 30000
MAX_EVENTS = 2000


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
        raise ValueError('后攻记录标识无效')
    return value


def number(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(label + '无效')
    return value


def words(value, limit=1000):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('记录文字过长或格式无效')
    return value.strip()


class SecondDuels:
    def __init__(self, store, read, write, now):
        self.store, self.read, self.write, self.now = store, read, write, now
        self.root = store.root / 'second-duels'
        self.lock = threading.RLock()
        self.epoch = uuid.uuid4().hex
        self.cache = {}
        from second_hints import SecondHints
        self.hints = SecondHints(self)
        from second_routes import SecondRoutes
        self.routes = SecondRoutes(self)
        from second_live import SecondLive
        self.live = SecondLive(self)

    def load(self, key):
        key = identifier(key)
        if key not in self.cache:
            doc = self.read(self.root / (key + '.json'))
            if (not isinstance(doc, dict) or doc.get('schema') != 1 or doc.get('id') != key
                    or doc.get('input_digest') != digest(doc.get('input'))):
                raise ValueError('后攻记录格式或原始快照校验失败；原文件保留')
            if (not isinstance(doc.get('current'), dict) or not isinstance(doc['current'].get('cards'), list)
                    or not isinstance(doc.get('events'), list) or not isinstance(doc.get('catalog'), dict)
                    or type(doc.get('revision')) is not int or type(doc.get('closed')) is not bool):
                raise ValueError('后攻观察记录不完整；原文件保留')
            self.cache[key] = doc
        return self.cache[key]

    def save(self, doc):
        # The in-memory commit follows the atomic disk commit. Failed writes
        # never advance a revision, spend a card, or overwrite the old journal.
        if len(json.dumps(doc, ensure_ascii=False).encode('utf-8')) > (34 if doc['closed'] else 32) * 1024 * 1024:
            raise ValueError('本局观察记录超过容量上限；原记录保留，未应用本次变更')
        self.write(self.root / (doc['id'] + '.json'), doc)
        self.cache[doc['id']] = doc

    def connection_error(self, doc):
        source = doc['input'].get('connection')
        if not source:
            return ''
        smart = self.store.ygopro_smart
        if source.get('recognition_id'):
            job = smart.jobs.get(source['recognition_id'])
            if (not job or not smart.current(job) or job.get('stage') != 'second'
                    or job.get('round_id') != doc['input']['round_id']
                    or job.get('capture_id') != source['capture_id']
                    or time.monotonic() - job['last_sample'] >= 2
                    or time.monotonic() - job['touched'] >= 20 or job.get('reading_error')):
                return '本局连接中断或局次已变化；旧记录仅供回看'
        else:
            monitor = self.store.ygopro_order
            frame = monitor.public()
            if (monitor.monitor_id != source.get('monitor_id') or monitor.capture_id != source['capture_id']
                    or frame.get('round_id') != doc['input']['round_id'] or frame.get('phase') != 'detected'
                    or (frame.get('confirmed') or {}).get('order') != 'second'
                    or not monitor.last_live or monitor.last_success is None or time.monotonic() - monitor.last_success > 2):
                return '先后攻监测已中断或局次已变化；请重新核对当前对局'
        return ''

    def status(self, doc):
        if doc['closed']:
            return '本局记录已结束'
        if doc['epoch'] != self.epoch:
            return '应用已重启，请核对当前局面后恢复记录；旧响应窗口不会恢复'
        return self.connection_error(doc) or self.routes.connection_error(doc) or self.live.status(doc) or doc['current'].get('stale_reason', '')

    def public(self, doc):
        value = deepcopy(doc)
        value.pop('epoch', None)
        value.pop('input_digest', None)
        value['status_reason'] = self.status(doc)
        value['current']['hand'] = [c['code'] for c in doc['current']['cards'] if c['controller'] == 0 and c['location'] == 2]
        window = value['current'].get('window')
        value['window_valid'] = bool(window and not value['status_reason'] and window['expires_ms'] > self.now())
        value['capabilities'] = {'observations': True, 'automatic_live_state': False, 'engine_reconstruction': False,
                                 'advice': True, 'routes': False}
        value['catalog'] = deepcopy(doc.get('catalog', {}))
        value['hint_options'] = self.hints.options()
        value['advice'] = self.hints.public(doc)
        value['route_panel'] = self.routes.public(doc)
        value['live_panel'] = self.live.panel(doc)
        value['capabilities']['engine_reconstruction'] = value['route_panel']['current']
        value['capabilities']['routes'] = value['route_panel']['current'] and value['route_panel']['route_ready']
        for hint in value.get('advice_history', []):
            hint.pop('known_state', None)
        return value

    def start(self, body):
        with self.lock:
            key = identifier(body.get('request_id'))
            request_hash = digest(body)
            if key in self.cache or (self.root / (key + '.json')).exists():
                doc = self.load(key)
                if doc.get('start_request') != request_hash:
                    raise ValueError('重复创建请求与原始输入不一致')
                return self.public(doc)
            if body.get('recognition_id') or body.get('monitor_id'):
                inputs = self.automatic_input(body)
            else:
                saved = self.store.get_deck(body.get('deck_id', ''))
                if saved['revision'] != body.get('deck_revision'):
                    raise ValueError('卡组已变化，请重新选择并核对起手')
                self.store.validate(saved['deck'])
                hand = body.get('opening')
                validate_hand(saved['deck'], len(hand) if isinstance(hand, list) else 0, hand)
                platform = body.get('platform', 'manual')
                if platform not in PLATFORMS:
                    raise ValueError('请选择后攻记录的平台')
                inputs = {'deck': deepcopy(saved['deck']), 'deck_name': saved['name'], 'deck_revision': saved['revision'],
                          'round_id': uuid.uuid4().hex, 'platform': platform, 'connection': None,
                          'opening': {'snapshot_id': uuid.uuid4().hex, 'cards': list(hand), 'source': 'user_confirmed', 'captured_ms': self.now()}}
            cards, remaining = [], Counter(inputs['opening']['cards'])
            for zone in ('main', 'extra'):
                for code in sorted(inputs['deck'][zone]):
                    location = 64 if zone == 'extra' else 1
                    if zone == 'main' and remaining[code] > 0:
                        remaining[code] -= 1
                        location = 2
                    cards.append({'id': uuid.uuid4().hex, 'code': code, 'controller': 0, 'owner': 0,
                                  'location': location, 'position': 1, 'source': inputs['opening']['source']})
            doc = {'schema': 1, 'id': key, 'revision': 0, 'epoch': self.epoch, 'closed': False,
                   'created_ms': self.now(), 'updated_ms': self.now(), 'start_request': request_hash,
                   'input': inputs, 'input_digest': digest(inputs), 'events': [],
                   'catalog': {str(c): deepcopy(self.store.catalog.cards[c]) for c in set(sum(inputs['deck'].values(), []))},
                   'current': {'turn': 1, 'turn_player': 1, 'phase': 'unknown', 'lp': [8000, 8000],
                               'opponent_hand_count': None, 'cards': cards, 'usage': [], 'restrictions': [],
                               'window': None, 'stale_reason': '请核对当前手牌、公开局面和阶段；初始起手不等于当前手牌'}}
            error = self.connection_error(doc)
            if error:
                raise ValueError(error)
            self.save(doc)
            return self.public(doc)

    def automatic_input(self, body):
        if body.get('recognition_id'):
            smart = self.store.ygopro_smart
            with smart.lock:
                job = smart.jobs.get(body['recognition_id'])
                if not job or not smart.current(job) or job.get('stage') != 'second':
                    raise ValueError('请等待本局后攻及完整起手校验通过')
                frame, construction = deepcopy(job['frame']), deepcopy(job['construction'])
                deck, name = construction['deck'], '自动捕获的本局构筑'
                source = {'recognition_id': job['id'], 'capture_id': job['capture_id']}
                platform = job.get('platform', 'ygopro')
        else:
            monitor = self.store.ygopro_order
            with monitor.lock:
                frame = monitor.public()
                if body.get('monitor_id') != monitor.monitor_id:
                    raise ValueError('先后攻监测已经变化')
                deck = self.store.ygopro_capture.submitted_deck(monitor.capture_id)
                name = '自动捕获的本局构筑'
                source = {'monitor_id': monitor.monitor_id, 'capture_id': monitor.capture_id}
                platform = (self.store.ygopro_capture.attached or {}).get('platform', 'ygopro')
        opening = frame.get('opening') or {}
        if (frame.get('round_id') != body.get('round_id') or (frame.get('confirmed') or {}).get('order') != 'second'
                or opening.get('status') != 'ready' or opening.get('snapshot_id') != body.get('snapshot_id')):
            raise ValueError('后攻局次或初始起手已变化，请重新核对')
        self.store.validate(deck)
        validate_hand(deck, len(opening['cards']), opening['cards'])
        return {'deck': deepcopy(deck), 'deck_name': name, 'deck_revision': digest(deck), 'round_id': frame['round_id'],
                'platform': platform, 'connection': source,
                'opening': {'snapshot_id': opening['snapshot_id'], 'cards': list(opening['cards']),
                            'source': 'readonly_opening', 'captured_ms': opening.get('captured_ms')}}

    def state(self, body):
        with self.lock:
            current = deepcopy(self.load(body.get('id')))
        self.live.check_current(current)
        with self.lock:
            return self.public(self.load(body.get('id')))

    def history(self):
        rows = []
        with self.lock:
            for path in self.root.glob('*.json'):
                try:
                    doc = self.cache.get(path.stem) or self.read(path)
                    if not isinstance(doc, dict) or doc.get('schema') != 1 or doc.get('id') != path.stem:
                        raise ValueError('记录格式无效')
                    rows.append({'id': doc['id'], 'name': doc['input']['deck_name'], 'updated_ms': doc['updated_ms'],
                                 'closed': doc['closed'], 'events': len(doc['events']), 'platform': doc['input']['platform']})
                except (ValueError, OSError, KeyError, TypeError):
                    rows.append({'id': path.stem, 'name': '记录损坏，原文件保留', 'updated_ms': 0, 'closed': True, 'damaged': True})
        return sorted(rows, key=lambda item: item['updated_ms'], reverse=True)

    def event(self, body):
        with self.lock:
            doc = self.load(body.get('id'))
            if body.get('round_id') != doc['input']['round_id']:
                raise ValueError('填报不属于当前局次')
            event_id = identifier(body.get('event_id'))
            kind, payload = body.get('kind'), body.get('payload', {})
            request_hash = digest({'kind': kind, 'payload': payload})
            repeated = next((e for e in doc['events'] if e['id'] == event_id), None)
            if repeated:
                if repeated['request_hash'] != request_hash:
                    raise ValueError('同一事件标识不能提交不同内容')
                return self.public(doc)
            if body.get('revision') != doc['revision']:
                raise ValueError('局面已更新，原输入未应用；请刷新后核对')
            if doc['closed']:
                raise ValueError('本局记录已结束，仅可回看')
            if len(doc['events']) >= MAX_EVENTS and kind != 'close':
                raise ValueError('本局记录已达到容量上限；原始记录保留，请结束并另建记录')
            if kind != 'close' and self.connection_error(doc):
                raise ValueError(self.connection_error(doc))
            if doc['epoch'] != self.epoch and kind not in ('verify', 'resume', 'close'):
                raise ValueError('请先核对当前局面并恢复记录')
            if not isinstance(payload, dict):
                raise ValueError('实际情况格式无效')
            self.routes.check_annotation(doc, kind, payload)
            self.live.check_annotation(doc, kind, payload)
            updated = deepcopy(doc)
            before = deepcopy(updated['current'])
            updated['current']['window'] = None
            summary = self.apply(updated, kind, payload)
            updated.update(revision=doc['revision'] + 1, updated_ms=self.now(), epoch=self.epoch)
            updated['events'].append({'id': event_id, 'request_hash': request_hash, 'kind': kind, 'payload': deepcopy(payload),
                                      'source': 'user_confirmed', 'time_ms': self.now(), 'revision': updated['revision'],
                                      'summary': summary, 'before': before, 'after': deepcopy(updated['current'])})
            if doc.get('native_link'): updated['events'][-1]['native_origin'] = deepcopy(doc['native_link'])
            self.save(updated)
            if doc.get('native_link'): self.routes.annotated(updated, kind)
            else: self.routes.invalidate(doc['id'])
            return self.public(updated)

    def card(self, value):
        code = number(value, 1, 999999999, '卡号')
        if code not in self.store.catalog.cards:
            raise ValueError('卡号不存在于当前卡库，不能猜测身份')
        return code

    def placement(self, state, card, payload):
        zone = card['location']
        if zone in (4, 8):
            sequence = payload.get('sequence')
            if sequence is not None:
                number(sequence, 0, 6 if zone == 4 else 7, '场上位置')
                if any(c['id'] != card['id'] and c['controller'] == card['controller'] and c['location'] == zone
                       and c.get('sequence') == sequence for c in state['cards']):
                    raise ValueError('该场上位置已记录其他卡牌，请核对实际移动')
            card['sequence'] = sequence
        else:
            card.pop('sequence', None)
        position = payload.get('position')
        if position is not None and (type(position) is not int or position not in (1, 2, 4, 8)):
            raise ValueError('表示形式无效')
        card['position'] = position
        if card['controller'] == 1 and zone in (4, 8, 32) and position in (2, 8):
            card['code'] = None
        if zone == 128:
            host = next((c for c in state['cards'] if c['id'] == payload.get('host_id') and c['id'] != card['id']
                         and c['location'] == 4 and c['controller'] == card['controller']), None)
            if host is None:
                raise ValueError('请指定当前场上的素材承载怪兽')
            card['host_id'] = host['id']
        else:
            card.pop('host_id', None)

    def apply(self, doc, kind, payload):
        state = doc['current']
        note = words(payload.get('note', ''))
        if kind in ('hint_window', 'resource_role', 'effect_count', 'effect_observed', 'effect_outcome'):
            return self.hints.apply(doc, kind, payload)
        if kind == 'resume':
            if doc['input'].get('connection'):
                raise ValueError('自动对局历史不能恢复为当前连接；请重新识别本局')
            state['stale_reason'] = '已恢复人工记录，请先更正当前资源并核对局面；旧响应窗口已清除'
            return '恢复人工记录，等待核对当前实际状态'
        if kind == 'move':
            card = next((c for c in state['cards'] if c['id'] == payload.get('card_id')), None)
            if not card or card['location'] != payload.get('from'):
                raise ValueError('卡牌实例或原区域已变化')
            target = payload.get('to')
            if type(target) is not int or target not in ZONES or target == card['location']:
                raise ValueError('请选择不同的实际去向')
            reason = payload.get('reason', 'effect')
            if reason not in ('cost', 'effect', 'draw', 'summon', 'correction'):
                raise ValueError('请选择卡牌变化的原因')
            if reason == 'draw' and (card['controller'] != 0 or card['location'] != 1 or target != 2):
                raise ValueError('实际抽牌应从我方牌组进入手牌')
            if reason == 'correction' and not note:
                raise ValueError('请说明人工更正原因；原观察仍会保留')
            name = self.store.catalog.cards.get(card.get('code'), {}).get('name', '未知卡牌')
            origin = card['location']
            if origin == 4 and any(c.get('host_id') == card['id'] for c in state['cards']):
                raise ValueError('请先记录承载怪兽的素材实际去向，不能留下悬空素材')
            card.update(location=target, source='user_confirmed')
            self.placement(state, card, payload)
            if card['controller'] == 1 and target in (1, 2, 64):
                card['code'] = None
            state['stale_reason'] = '资源已变化，请核对当前局面和响应窗口'
            return f'{name}：{ZONES[origin]} → {ZONES[target]}（' + {'cost':'实际费用','draw':'实际抽牌','summon':'实际召唤','correction':'人工更正','effect':'实际结果'}[reason] + '）' + ('；' + note if note else '')
        if kind == 'opponent_card':
            zone = payload.get('location')
            if type(zone) is not int or zone not in (4, 8, 16, 32):
                raise ValueError('仅录入对手场上、墓地或除外的观察')
            known = payload.get('known')
            if type(known) is not bool:
                raise ValueError('请核对卡牌身份是否公开')
            if not known and payload.get('code') is not None:
                raise ValueError('隐藏卡不能携带已知卡号')
            if not known and zone == 16:
                raise ValueError('请核对墓地公开卡牌身份')
            if len([c for c in state['cards'] if c['controller'] == 1]) >= 120:
                raise ValueError('对手记录数量超过上限，请核对重复填报')
            code = self.card(payload.get('code')) if known else None
            if code:
                doc['catalog'].setdefault(str(code), deepcopy(self.store.catalog.cards[code]))
            card = {'id': uuid.uuid4().hex, 'code': code, 'controller': 1, 'owner': 1,
                    'location': zone, 'position': 1 if known else 8, 'source': 'user_confirmed'}
            self.placement(state, card, {**payload, 'position': payload.get('position', 1 if known else 8)})
            if known and card['code'] is None:
                raise ValueError('里侧对手卡片不能作为已知身份录入')
            state['cards'].append(card)
            state['stale_reason'] = '公开局面已变化，请重新核对'
            return '观察对手卡牌：' + (self.store.catalog.cards[code]['name'] if code else '未知卡牌') + ' · ' + ZONES[zone]
        if kind == 'reveal':
            card = next((c for c in state['cards'] if c['id'] == payload.get('card_id') and c['controller'] == 1), None)
            if not card or card['location'] not in (4, 8, 16, 32):
                raise ValueError('请选择当前对手区域的卡片实例')
            code = self.card(payload.get('code'))
            if card.get('code') and card['code'] != code:
                raise ValueError('此实例已有不同身份；请核对是否是新出现的卡片')
            card.update(code=code, position=1, source='user_confirmed')
            doc['catalog'].setdefault(str(code), deepcopy(self.store.catalog.cards[code]))
            state['stale_reason'] = '卡片身份已公开，请重新核对当前局面'
            return '实际公开卡片：' + self.store.catalog.cards[code]['name']
        if kind == 'verify':
            phase = payload.get('phase')
            if phase not in PHASES or phase == 'unknown':
                raise ValueError('请核对当前阶段')
            turn = number(payload.get('turn'), 1, 999, '回合')
            player = number(payload.get('turn_player'), 0, 1, '回合玩家')
            lp = payload.get('lp')
            if not isinstance(lp, list) or len(lp) != 2:
                raise ValueError('请核对双方 LP')
            lp = [number(v, 0, 2**31 - 1, 'LP') for v in lp]
            hand_count = payload.get('opponent_hand_count')
            if hand_count is not None:
                number(hand_count, 0, 120, '对手手牌张数')
            if payload.get('confirmed') is not True:
                raise ValueError('请确认已核对当前手牌、公开区域与规则记录')
            state.update(turn=turn, turn_player=player, phase=phase, lp=lp, opponent_hand_count=hand_count, stale_reason='')
            # Recorded usage is not automatically reset or inferred from a new
            # turn; its scope/expiry remains explicit until rules reconstruction.
            return '人工核对当前局面；未证明完整引擎规则状态' + ('；' + note if note else '')
        if kind == 'window':
            if doc['current']['stale_reason']:
                raise ValueError('请先核对当前局面')
            label = words(payload.get('label', ''), 500)
            if not label or payload.get('confirmed') is not True:
                raise ValueError('请描述公开动作，并确认当前是我方响应窗口')
            state['window'] = {'id': uuid.uuid4().hex, 'label': label, 'created_ms': self.now(),
                               'expires_ms': self.now() + WINDOW_MS, 'source': 'user_confirmed', 'response_player': 0}
            return '确认我方响应窗口：' + label
        if kind == 'rule':
            category = payload.get('category')
            if category not in ('usage', 'restrictions'):
                raise ValueError('请选择次数或持续限制')
            label = words(payload.get('label', ''), 500)
            if not label:
                raise ValueError('请填写具体效果、使用情况或限制及到期条件')
            row = {'id': uuid.uuid4().hex, 'label': label, 'status': payload.get('status'), 'source': 'user_confirmed'}
            if row['status'] not in ('confirmed', 'unknown', 'expired'):
                raise ValueError('规则记录状态无效')
            if len(state[category]) >= 200:
                raise ValueError('规则记录过多，请核对重复项目')
            state[category].append(row)
            state['stale_reason'] = '规则记录已变化，请核对当前局面'
            return ('效果次数：' if category == 'usage' else '持续限制：') + label
        if kind == 'rule_status':
            category = payload.get('category')
            if category not in ('usage', 'restrictions'):
                raise ValueError('规则记录分类无效')
            row = next((r for r in state[category] if r['id'] == payload.get('rule_id')), None)
            if not row or payload.get('status') not in ('confirmed', 'unknown', 'expired'):
                raise ValueError('规则记录不存在或状态无效')
            if not note:
                raise ValueError('请说明更正或到期依据')
            row['status'] = payload['status']
            state['stale_reason'] = '规则记录已变化，请重新核对'
            return '更新规则记录：' + row['label'] + '；' + note
        if kind in ('choice', 'result', 'invalidate'):
            if not note:
                raise ValueError('请填写实际选择、结果或缺失信息')
            state['stale_reason'] = note if kind == 'invalidate' else '实际进度已变化，请核对当前局面'
            return {'choice':'玩家实际选择：', 'result':'实际观察结果：', 'invalidate':'停止当前建议：'}[kind] + note
        if kind == 'close':
            doc['closed'] = True
            return '结束本局后攻记录；原始起手及观察历史保留'
        raise ValueError('尚未支持此类后攻填报，原状态保留')

    def dispatch(self, action, body):
        if action in ('live-preview', 'live-apply'):
            return self.live.dispatch(action, body)
        if action == 'review-window':
            from second_native import review
            with self.lock:
                doc = self.load(body.get('id'))
                hint = next((h for h in doc.get('advice_history', []) if h['id'] == body.get('advice_id')), None)
                if not hint: raise ValueError('该局没有此响应窗口记录')
                return review(doc, hint)
        if action in ('route-sources', 'route-sync', 'route-generate', 'route-choose', 'route-battle'):
            return self.routes.dispatch(action, body)
        if action == 'advice':
            return self.hints.generate(body)
        if action == 'advice-choice':
            return self.hints.choose(body)
        if action == 'start':
            return self.start(body)
        if action == 'state':
            return self.state(body)
        if action == 'event':
            return self.event(body)
        if action == 'history':
            return {'records': self.history()}
        if action == 'close':
            with self.lock:
                doc = self.load(body.get('id'))
                if body.get('round_id') != doc['input']['round_id']:
                    raise ValueError('关闭请求不属于此局')
                if doc['closed']:
                    return self.public(doc)
                return self.event({'id': doc['id'], 'round_id': doc['input']['round_id'], 'revision': doc['revision'],
                                   'event_id': uuid.uuid4().hex, 'kind': 'close', 'payload': {}})
        raise ValueError('后攻操作不存在')
