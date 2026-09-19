"""Explicit preview/reconcile of external resources; no reconstructed rules."""
from copy import deepcopy
import threading
import uuid

from second_duel import identifier, digest, MAX_EVENTS


class SecondLive:
    def __init__(self, owner):
        self.owner = owner
        self.operations = threading.Lock()
        self.previews = {}
        self.latest = {}

    def request(self, body):
        doc = self.owner.load(body.get('id'))
        if (doc['closed'] or doc['epoch'] != self.owner.epoch or doc['revision'] != body.get('revision')
                or doc['input']['round_id'] != body.get('round_id')):
            raise ValueError('局次或观察版本已变化，不能采用旧读取结果')
        if (doc['input']['platform'] != 'ygopro' or not doc['input'].get('connection') or doc.get('native_link')):
            raise ValueError('仅支持从已核实 YGOPro 开局进入的本局后攻记录')
        error = self.owner.connection_error(doc)
        if error: raise ValueError(error)
        return doc

    def read(self, doc):
        source = doc['input']['connection']
        def anchor():
            if self.owner.connection_error(doc): raise ValueError('本局连接或局次已失效')
            if source.get('recognition_id'):
                smart = self.owner.store.ygopro_smart
                with smart.lock:
                    job = smart.jobs[source['recognition_id']]
                    return job['round_id'], job.get('game'), job['frame']['evidence']['turn']
            frame = self.owner.store.ygopro_order.public()
            return frame['round_id'], None, frame['evidence']['turn']
        before = anchor()
        sample = deepcopy(self.owner.store.ygopro_capture.resource_snapshot(source['capture_id']))
        if anchor() != before or sample['turn'] != before[2]:
            raise ValueError('读取期间局次或回合已变化，请重新核对')
        if before[1] is not None and int.from_bytes(bytes.fromhex(before[1]), 'little') != int(sample['game'], 16):
            raise ValueError('当前游戏场景与本局开局来源不同，不能合并')
        if sample['order'] != 'second':
            raise ValueError('实际客户端未确认后攻，不能套用这份后攻记录')
        # The scene address is a private continuity guard, not a player-known id.
        game = sample.pop('game')
        return sample, game

    def panel(self, doc):
        preview = self.previews.get(doc['id'])
        value = {'supported': doc['input']['platform'] == 'ygopro' and bool(doc['input'].get('connection')),
                 'missing': ['完整连锁、响应窗口、次数及持续限制尚未接入', '采样不能还原中间发生的所有动作'],
                 'history_count': len(doc.get('live_history', []))}
        if preview:
            value['preview'] = {k: deepcopy(preview[k]) for k in ('id', 'snapshot', 'created_ms', 'revision')}
            value['preview']['can_apply'] = (not doc['closed'] and doc['epoch'] == self.owner.epoch
                and preview['revision'] == doc['revision'] and not self.owner.connection_error(doc))
            value['preview']['current'] = value['preview']['can_apply'] and self.owner.now() - preview['created_ms'] <= 2000
        return value

    def status(self, doc):
        # A confirmed read is an observation at that time, never a continuously
        # current permission to use an old response window.
        link = doc.get('live_link')
        if link:
            latest = self.latest.get(doc['id'], {})
            if latest.get('error'): return latest['error']
            if self.owner.now() - latest.get('seen_ms', 0) > 2000:
                return '公开资源读取已过期；请重新读取并核对，不沿用旧建议'
            if latest.get('digest') != link['digest']:
                return '客户端资源已变化，当前记录尚未同步；请重新读取并核对'
        return ''

    def check_current(self, doc):
        if not doc.get('live_link') or doc['closed'] or doc['epoch'] != self.owner.epoch: return
        try:
            sample, _ = self.read(doc)
            self.latest[doc['id']] = {'digest': digest(sample), 'seen_ms': self.owner.now()}
        except (ValueError, OSError, KeyError) as error:
            self.latest[doc['id']] = {'error': '无法核对当前公开资源：' + str(error)}

    def preview(self, body):
        with self.operations:
            with self.owner.lock:
                doc = deepcopy(self.request(body))
            sample, game = self.read(doc)
            with self.owner.lock:
                self.request(body)
                value = {'id': uuid.uuid4().hex, 'revision': doc['revision'], 'snapshot': sample,
                         'game': game, 'created_ms': self.owner.now()}
                updated = deepcopy(self.owner.load(doc['id']))
                if len(updated.get('live_reads', [])) >= 200: raise ValueError('本局读取记录已满，历史保留')
                updated.setdefault('live_reads', []).append({k: deepcopy(value[k]) for k in ('id','revision','snapshot','created_ms')})
                for card in sample['cards']:
                    code = card.get('code')
                    if code in self.owner.store.catalog.cards:
                        updated['catalog'].setdefault(str(code), deepcopy(self.owner.store.catalog.cards[code]))
                self.owner.save(updated)
                self.previews[doc['id']] = value
                self.latest[doc['id']] = {'digest': digest(sample), 'seen_ms': self.owner.now()}
                return self.owner.public(updated)

    def apply(self, body):
        with self.operations:
            with self.owner.lock:
                key = identifier(body.get('event_id'))
                existing = self.owner.load(body.get('id'))
                repeated = next((e for e in existing['events'] if e['id'] == key), None)
                if repeated:
                    if repeated['kind'] != 'live_sync' or repeated['request_hash'] != digest(body):
                        raise ValueError('同一同步标识不能用于不同局面或内容')
                    return self.owner.public(existing)
                doc = deepcopy(self.request(body))
                preview = deepcopy(self.previews.get(doc['id']))
                if (not preview or body.get('preview_id') != preview['id'] or preview['revision'] != doc['revision']
                        or body.get('confirmed') is not True):
                    raise ValueError('请先读取本局公开资源，并核对本次将更新的字段')
                if len(doc['events']) >= MAX_EVENTS: raise ValueError('观察记录已满，原历史保留')
            sample, game = self.read(doc)
            if sample != preview['snapshot'] or game != preview['game']:
                raise ValueError('客户端已变化，本次未覆盖人工记录；请重新读取并核对')
            cards = []
            for row in sample['cards']:
                # Location snapshots do not establish a card's identity across
                # moves, reveals or allocator reuse. Do not carry instance uses.
                card = {**row, 'id': uuid.uuid4().hex, 'source': 'readonly_public_snapshot'}
                if card['position'] in (5, 10): card['position'] = 1 if card['position'] == 5 else 8
                cards.append(card)
                code = card.get('code')
                if code in self.owner.store.catalog.cards:
                    doc['catalog'].setdefault(str(code), deepcopy(self.owner.store.catalog.cards[code]))
            old = deepcopy(doc['current'])
            hosts = {(c['controller'], c['sequence']): c['id'] for c in cards if c['location'] == 4}
            for card in cards:
                if card['location'] == 128:
                    host = hosts.get(tuple(card.pop('material_host', [])))
                    if not host: raise ValueError('素材承载关系不完整，未采用此次快照')
                    card['host_id'] = host
            # Shared historical use records are retained conservatively; no used
            # effect is refunded by a resource snapshot. Unmapped instance scopes
            # and unobserved materials are not claimed to be restored.
            current = deepcopy(old)
            current.update(cards=cards, turn=sample['turn'], turn_player=sample.get('turn_player'),
                phase=sample.get('phase') or 'unknown', lp=sample['lp'], opponent_hand_count=sample['counts'][1]['2'],
                zone_counts=sample['counts'], window=None, resource_roles={},
                live_context={'phase': sample.get('phase'), 'turn_player': sample.get('turn_player'),
                              'turn_player_basis': sample.get('turn_player_basis', 'unknown')},
                stale_reason='已核对公开资源；未读取的时点、完整连锁、实例次数和持续限制仍待核对，不能据此重建规则')
            current.pop('hint_window', None)
            current.pop('native_rules', None)
            for row in current.get('effect_counts', {}).values():
                if row.get('status') != 'used': row['status'] = 'unknown'
            doc.update(current=current, revision=doc['revision'] + 1, updated_ms=self.owner.now())
            doc['live_link'] = {'snapshot_id': preview['id'], 'confirmed_ms': self.owner.now(), 'layout': sample['layout'], 'digest': digest(sample)}
            doc.setdefault('live_history', []).append({'id': preview['id'], 'snapshot': sample,
                'observed_ms': preview['created_ms'], 'confirmed_ms': self.owner.now(), 'revision': doc['revision']})
            doc['events'].append({'id': key, 'kind': 'live_sync', 'request_hash': digest(body),
                'source': 'readonly_public_snapshot', 'time_ms': self.owner.now(), 'revision': doc['revision'],
                'summary': '核对并采用 YGOPro 已覆盖的公开资源；未推断中间动作',
                'payload': {'snapshot_id': preview['id']}, 'before': old, 'after': deepcopy(current)})
            with self.owner.lock:
                self.request(body)
                self.owner.save(doc)
                self.latest[doc['id']] = {'digest': digest(sample), 'seen_ms': self.owner.now()}
                self.previews.pop(doc['id'], None)
                return self.owner.public(doc)

    def check_annotation(self, doc, kind, payload):
        if not doc.get('live_link'): return
        if kind in ('move', 'opponent_card', 'reveal'):
            raise ValueError('已接入公开资源读取；实际卡牌变化请重新读取并核对，避免重复扣牌或猜测中间动作')
        if kind == 'verify' and any(payload.get(k) != doc['current'][k] for k in ('turn','lp','opponent_hand_count')):
            raise ValueError('核对值与已读取资源不同；请重新读取，不能静默覆盖识别字段')
        context = doc['current'].get('live_context', {})
        if kind == 'verify' and any(context.get(k) is not None and payload.get(k) != context[k] for k in ('phase', 'turn_player')):
            raise ValueError('阶段或回合玩家与已读取依据不同，请重新读取，不能用人工选择覆盖')
        if kind in ('verify', 'window', 'hint_window'):
            self.check_current(doc)
            error = self.status(doc)
            if error: raise ValueError(error)

    def dispatch(self, action, body):
        return self.preview(body) if action == 'live-preview' else self.apply(body)
