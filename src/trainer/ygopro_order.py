"""Per-round order monitoring and explicit, revision-checked confirmation."""
from copy import deepcopy
import threading
import time
import uuid

from ygopro_capture import CaptureError
import ygopro_opening


ACTIVE = {'rps', 'choose_order', 'waiting_choice', 'detected'}


class OrderMonitor:
    def __init__(self, store, write, now):
        self.store, self.write, self.now = store, write, now
        self.lock = threading.RLock()
        self.monitor_id = None
        self.capture_id = None
        self.round = None
        self.last = None
        self.last_live = None
        self.serial = 0
        self.last_success = None
        self.pending_persist = False

    def start(self, capture_id):
        with self.lock:
            raw = self.store.ygopro_capture.order(capture_id, with_opening=True)
            self.monitor_id = uuid.uuid4().hex
            self.capture_id = capture_id
            self.round = self.last = self.last_live = None
            self.serial = 0
            self.last_success = time.monotonic()
            self.pending_persist = False
            return self.accept(raw)

    def persist(self):
        if self.round:
            self.pending_persist = True
            self.write(self.store.root / 'automatic-duels' / (self.round['id'] + '.json'), self.round)
            self.pending_persist = False

    def accept(self, raw):
        raw = deepcopy(raw)
        opening_sample = raw.pop('opening_sample', None)
        phase = raw['phase']; previous = self.last_live
        reset = phase in ACTIVE and (not self.round or not previous or previous['phase'] not in ACTIVE or
                previous['phase'] == 'detected' and phase != 'detected' or
                phase == 'detected' and previous['phase'] == 'detected' and
                raw['evidence']['turn'] < previous['evidence']['turn'])
        if reset:
            self.round = {'id':uuid.uuid4().hex, 'started_ms':self.now(), 'process_pid':self.store.ygopro_capture.attached['pid'],
                          'detected_order':None, 'confirmed':None, 'confirmations':[], 'self_choice_seen':False, 'events':[],
                          'opening':ygopro_opening.create(raw['evidence']['turn'] == 0)}
        if self.round and phase == 'choose_order':self.round['self_choice_seen'] = True
        opening_changed = bool(self.round and phase in ACTIVE and ygopro_opening.observe(self.round['opening'], opening_sample, raw, self.now))
        if reset or raw != self.last or opening_changed or self.pending_persist:
            self.serial += 1
            if self.round:
                # A new round always gets a new id; old files retain their result.
                if raw['detected_order']:
                    if self.round['detected_order'] != raw['detected_order']:self.round['confirmed'] = None
                    self.round['detected_order'] = raw['detected_order']
                self.round['events'] = (self.round['events'] + [{'time_ms':self.now(), **deepcopy(raw)}])[-128:]
                self.persist()
        self.last = deepcopy(raw)
        if phase != 'disconnected':self.last_live = deepcopy(raw)
        return self.public()

    def public(self):
        return {'monitor_id':self.monitor_id, 'round_id':self.round['id'] if self.round else None,
                'revision':self.serial, **deepcopy(self.last or {}),
                'self_choice_seen':bool(self.round and self.round['self_choice_seen']),
                'confirmed':deepcopy(self.round['confirmed']) if self.round and self.last['phase'] == 'detected' else None,
                'opening':ygopro_opening.public(self.round['opening']) if self.round and self.last['phase'] in ACTIVE else None}

    def poll(self, monitor_id):
        with self.lock:
            if not self.monitor_id or monitor_id != self.monitor_id:
                raise CaptureError('监测会话已失效，请重新连接进程。')
            try:
                needs_opening = not self.round or self.round['opening']['status'] not in ('ready','missed')
                raw = self.store.ygopro_capture.order(self.capture_id, with_opening=needs_opening)
                current_time = time.monotonic()
                if (self.last_success is not None and current_time - self.last_success > 2
                        and self.last_live and self.last_live['phase'] in ACTIVE and raw['phase'] in ACTIVE):
                    # After a sampling gap, equal turn/order flags cannot prove
                    # this is the same duel. Retain the old file, never reuse its hand.
                    self.round = self.last_live = None
                self.last_success = current_time
            except CaptureError as error:
                raw = {'phase':'disconnected', 'detected_order':None, 'evidence':{}, 'error':str(error)}
            return self.accept(raw)

    def confirm(self, body):
        with self.lock:
            current = self.poll(body.get('monitor_id'))
            if current['phase'] != 'detected' or not current['detected_order']:
                raise CaptureError('本局先后攻尚未确定，请等待游戏正式开局。')
            if current['round_id'] != body.get('round_id') or current['revision'] != body.get('revision'):
                raise CaptureError('游戏状态已改变，请核对最新结果后再次确认。')
            selected = body.get('order')
            if selected not in ('first', 'second'):raise ValueError('请选择先攻或后攻。')
            result = {'order':selected, 'detected_order':current['detected_order'],
                      'source':'manual' if body.get('manual') is True else 'automatic', 'confirmed_ms':self.now()}
            if result['source'] == 'automatic' and selected != current['detected_order']:
                raise ValueError('更正识别结果时请使用手动选择。')
            previous = self.round['confirmed']
            history = self.round['confirmations']
            previous_opening_confirmation = self.round['opening']['confirmed']
            if not previous or previous['order'] != selected:self.round['opening']['confirmed'] = None
            self.round['confirmed'] = result
            self.round['confirmations'] = (history + [result])[-32:]
            try:self.persist()
            except OSError:
                self.round['confirmed'] = previous
                self.round['confirmations'] = history
                self.round['opening']['confirmed'] = previous_opening_confirmation
                raise
            return self.public()

    def confirm_opening(self, body):
        with self.lock:
            current = self.poll(body.get('monitor_id'))
            if current['round_id'] != body.get('round_id') or current['phase'] != 'detected':
                raise CaptureError('对局已变化，请核对本局起手后重试。')
            if not current['confirmed'] or current['confirmed']['order'] != 'first':
                raise CaptureError('当前仅先攻进入准备起手，后攻起手保留供后续开发。')
            opening = self.round['opening']
            if opening['status'] != 'ready' or opening['snapshot_id'] != body.get('snapshot_id'):
                raise CaptureError('起手快照已失效或尚未获取完整，请重新核对。')
            previous = opening['confirmed']
            opening['confirmed'] = {'snapshot_id':opening['snapshot_id'], 'cards':list(opening['cards']), 'confirmed_ms':self.now()}
            try:self.persist()
            except OSError:
                opening['confirmed'] = previous
                raise
            return self.public()
