"""Cancellable, per-duel orchestration. Sampling never waits for TAG analysis."""
from collections import Counter
from copy import deepcopy
import re
import threading
import time
import uuid

import deck_tags
from automatic_duel import digest
from ygopro_capture import CaptureError
from ygopro_order import OrderMonitor, ACTIVE


TERMINAL = {'cancelled', 'invalidated', 'closed'}
STAGES = {'waiting': '等待对局开始', 'deck': '获取本局卡组', 'tags': '识别 TAG',
          'opening': '等待先后攻及起手就绪', 'audit': '自动校验', 'ready': '自动校验通过',
          'second': '已识别为后攻，后攻展开暂未支持', 'failed': '自动识别未完成',
          'cancelled': '已取消监测', 'invalidated': '监测连接已失效',
          'closed': '游戏客户端已关闭或连接已切换，智能识别已停止'}


class SmartRecognition:
    def __init__(self, store, write, now):
        self.store, self.write, self.now = store, write, now
        self.lock = threading.RLock()
        self.jobs = {}
        self.active = None

    def transition(self, job, stage, error='', failed_stage=None):
        if (job['stage'], job['error']) == (stage, error): return
        job.update(stage=stage, error=error, failed_stage=failed_stage)
        job['events'].append({'stage': stage, 'time_ms': self.now(), 'elapsed_ms': self.now()-job['started_ms']})
        self.persist(job)

    def persist(self, job):
        # Full snapshots are private runtime data, never deck-library entries.
        self.write(self.store.root/'smart-recognition'/(job['id']+'.json'), self.public(job))

    def public(self, job):
        return deepcopy({key: job.get(key) for key in
            ('id', 'capture_id', 'stage', 'error', 'failed_stage', 'started_ms', 'events', 'frame',
             'construction', 'tag_result', 'context', 'reading_error', 'cycle', 'note', 'previous_round', 'platform')}) | {
                 'message': '等待下一场对局开始' if job['stage']=='waiting' and job.get('previous_round') else STAGES[job['stage']]}

    def current(self, job):
        return self.active == job['id'] and not job['stop'].is_set() and job['stage'] not in TERMINAL

    def context_valid(self, identifier, round_id=None):
        job = self.jobs.get(identifier)
        return bool(job and self.current(job) and job['stage'] == 'ready'
                    and (round_id is None or round_id == job['round_id'])
                    and time.monotonic()-job['last_sample'] < 2 and time.monotonic()-job['touched'] < 20)

    def start(self, body):
        identifier, capture_id = body.get('request_id'), body.get('capture_id')
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
            raise ValueError('智能识别请求标识无效。')
        with self.lock:
            if identifier in self.jobs:
                job = self.jobs[identifier]
                if job.get('capture_id') not in (None, capture_id): raise ValueError('请求不属于当前连接。')
                return self.public(job)
            attached = self.store.ygopro_capture.attached
            if not attached or capture_id != attached['capture_id']: raise CaptureError('请先连接游戏平台。')
            self.cancel_active()
            job = {'id': identifier, 'capture_id': capture_id, 'platform': attached.get('platform', 'ygopro'), 'stage': 'waiting', 'error': '',
                   'failed_stage': None, 'started_ms': self.now(), 'events': [], 'frame': None,
                   'construction': None, 'tag_result': None, 'context': None, 'reading_error': '',
                   'stop': threading.Event(), 'touched': time.monotonic(), 'last_sample': time.monotonic(),
                   'round_id': None, 'game': None, 'tag_generation': 0, 'tag_pending': False,
                   'cycle': 0, 'note': '', 'previous_round': None, 'await_boundary': False,
                   'monitor': OrderMonitor(self.store, self.write, self.now)}
            job['events'].append({'stage': 'waiting', 'time_ms': job['started_ms'], 'elapsed_ms': 0})
            self.jobs[identifier] = job; self.active = identifier
            threading.Thread(target=self.run, args=(job,), daemon=True, name='ygopro-initial-sampler').start()
            return self.public(job)

    def poll(self, body):
        with self.lock:
            job = self.jobs.get(body.get('request_id'))
            if not job: raise ValueError('智能识别会话不存在，请重新监测。')
            job['touched'] = time.monotonic()
            return self.public(job)

    def stop(self, job, stage='cancelled', error=''):
        if job['stage'] in TERMINAL: return
        job['stop'].set(); job['tag_generation'] += 1
        self.transition(job, stage, error)
        if job.get('context'):
            identifier = job['context']['context_id']
            # The context guard rejects new actions immediately; engine cleanup
            # may need to wait for a running native search to yield.
            threading.Thread(target=self.close_context, args=(identifier,), daemon=True).start()

    def close_context(self, identifier):
        try: self.store.automatic_duel.close({'context_id': identifier})
        except (OSError, ValueError): pass  # Cancellation remains authoritative.

    def cancel_active(self):
        with self.lock:
            if self.active in self.jobs: self.stop(self.jobs[self.active])

    def reset_round(self, job, reason, await_boundary=False):
        """Retire only this round; keep the process subscription and sampler."""
        previous = self.public(job) if job['round_id'] else None
        context = job.get('context')
        job['tag_generation'] += 1
        if previous:
            job['cycle'] += 1
            job['previous_round'] = {'round_id': job['round_id'], 'ended_ms': self.now(), 'reason': reason}
        job.update(stage='waiting', error='', failed_stage=None, frame=None, construction=None,
                   tag_result=None, context=None, round_id=None, tag_pending=False, note=reason,
                   await_boundary=await_boundary, started_ms=self.now(), events=[])
        job['events'].append({'stage': 'waiting', 'time_ms': job['started_ms'], 'elapsed_ms': 0})
        job['monitor'] = OrderMonitor(self.store, self.write, self.now)
        # Per-round guards are invalid already, even while native cleanup waits.
        if context: threading.Thread(target=self.close_context, args=(context['context_id'],), daemon=True).start()
        if previous:
            self.write(self.store.root/'smart-recognition/rounds'/(previous['frame']['round_id']+'.json'),
                       {**previous, 'ended_ms': self.now(), 'end_reason': reason})
        self.persist(job)

    def cancel(self, body):
        identifier = body.get('request_id')
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
            raise ValueError('智能识别请求标识无效。')
        with self.lock:
            if identifier not in self.jobs:
                # A cancel can reach the service before its delayed start.
                self.jobs[identifier] = {'id': identifier, 'stage': 'cancelled', 'capture_id': None}
            else: self.stop(self.jobs[identifier])
            return {'id': identifier, 'stage': 'cancelled'}

    def retry(self, body):
        with self.lock:
            job = self.jobs.get(body.get('request_id'))
            if not job or not self.current(job): raise ValueError('本局已失效，请重新监测下一局。')
            if body.get('cycle') != job['cycle'] or body.get('round_id') != job['round_id']:
                raise ValueError('识别局次已变化，旧重试请求已忽略。')
            if job['stage'] != 'failed' or job['failed_stage'] not in ('tags', 'audit'):
                raise ValueError('当前错误需要重新监测下一局。')
            if job['tag_pending']: return self.public(job)
            job['tag_result'] = None
            self.transition(job, 'tags')
            self.start_tags(job)
            return self.public(job)

    def run(self, job):
        try:
            while not job['stop'].is_set():
                if time.monotonic()-job['touched'] > 20:
                    with self.lock: self.stop(job, 'invalidated', '监测页面已离开或连接中断，请重新监测。')
                    return
                try:
                    value = self.store.ygopro_capture.live_sample(job['capture_id'],
                        with_deck=job['construction'] is None,
                        with_opening=not job['frame'] or (job['frame'].get('opening') or {}).get('status') not in ('ready', 'missed'))
                except CaptureError as error:
                    alive = self.store.ygopro_capture.connection_alive(job['capture_id'])
                    with self.lock:
                        if not self.current(job): return
                        if alive is False:
                            self.stop(job, 'closed', '客户端已关闭、重新启动或连接被切换。'); return
                        if time.monotonic()-job['last_sample'] > 2 and not job['await_boundary']:
                            self.reset_round(job, '读取中断，本局无法继续确认；恢复后自动等待下一场。', await_boundary=True)
                        job['reading_error'] = str(error)
                else:
                    with self.lock:
                        if not self.current(job): return
                        if time.monotonic()-job['last_sample'] > 2:
                            self.reset_round(job, '采样中断，本局不能复用旧数据；自动等待下一场。', await_boundary=True)
                        job['last_sample'] = time.monotonic(); job['reading_error'] = ''
                        self.accept(job, value)
                job['stop'].wait(.025 if job['stage'] not in ('ready', 'second', 'failed') else .15)
        except Exception as error:
            with self.lock:
                if self.current(job):
                    # Never let an unexpected worker failure leave a ready UI.
                    job['stop'].set()
                    job.update(stage='invalidated', error='监测任务失败：'+str(error))
                    if job.get('context'): threading.Thread(target=self.close_context, args=(job['context']['context_id'],), daemon=True).start()

    def accept(self, job, sample):
        raw = sample['frame']
        if job['game'] is not None and sample['game'] != job['game']:
            self.reset_round(job, '游戏场景已切换，自动等待下一场。', await_boundary=raw['phase'] in ACTIVE)
        job['game'] = sample['game']
        if job['await_boundary']:
            if raw['phase'] in ACTIVE: return
            job['await_boundary'] = False
        if raw['phase'] in ('ended', 'waiting_start', 'unsupported'):
            if job['round_id']:
                self.reset_round(job, '本局已结束，已关闭本局工作区，自动等待下一场。')
            if raw['phase'] == 'unsupported': job['note'] = '当前模式不支持，保持连接并等待普通对局。'
        previous = job['monitor'].last_live
        if (job['round_id'] and previous and previous['evidence'].get('duel_token')
                and raw['evidence'].get('duel_token')
                and previous['evidence']['duel_token'] != raw['evidence']['duel_token']):
            self.reset_round(job, '检测到新的开局消息，旧构筑、起手和计算已关闭。')
        if (job['round_id'] and previous and previous['phase']=='detected' and raw['phase'] in ACTIVE
                and (raw['phase']!='detected' or raw['evidence']['turn'] < previous['evidence']['turn'])):
            self.reset_round(job, '检测到下一场，旧构筑、起手和计算已关闭。')
        monitor = job['monitor']
        if not monitor.monitor_id:
            monitor.monitor_id = uuid.uuid4().hex; monitor.capture_id = job['capture_id']
        frame = monitor.accept(raw)
        if frame['round_id']:
            if job['round_id'] and job['round_id'] != frame['round_id']:
                self.reset_round(job, '检测到下一场，旧构筑、起手和计算已关闭。')
                return self.accept(job, sample)
            if not job['round_id']: job['note'] = ''
            job['round_id'] = frame['round_id']
        job['frame'] = frame
        if job['stage'] in ('ready', 'second', 'failed'): return
        opening = frame.get('opening') or {}
        if opening.get('status') == 'missed':
            self.transition(job, 'failed', opening['error'], 'opening'); return
        if not job['round_id']: return
        if not job['construction']:
            self.transition(job, 'deck')
            if sample.get('construction'):
                construction = deepcopy(sample['construction'])
                try: self.validate_deck(construction['deck'])
                except ValueError as error: self.transition(job, 'failed', str(error), 'deck'); return
                construction.update(round_id=job['round_id'], capture_id=job['capture_id'], captured_ms=self.now())
                job['construction'] = construction
                self.transition(job, 'tags'); self.start_tags(job)
            elif frame['phase'] == 'detected':
                self.transition(job, 'failed', sample.get('deck_error') or '未捕捉到本局完整构筑，请重新监测下一局。', 'deck')
                return
        if job['construction'] and job['tag_result'] is not None:
            self.transition(job, 'opening')
            if frame['phase'] == 'detected' and opening.get('status') == 'ready': self.audit(job)

    def validate_deck(self, deck):
        self.store.validate(deck)
        if not 40 <= len(deck['main']) <= 60: raise ValueError('本局主卡组不完整，需要 40–60 张。')
        # Aliases share the same copy limit; preserve every actual card id.
        aliases = [self.store.catalog.cards[c].get('alias') or c for z in ('main', 'extra', 'side') for c in deck[z]]
        if any(count > 3 for count in Counter(aliases).values()): raise ValueError('本局构筑同名卡超过 3 张，当前自动识别不支持此构筑。')

    def recognize_tags(self, deck):
        vocabulary = self.store.library.all_tags()
        result = deck_tags.suggest(deck, vocabulary, self.store.catalog.cards)
        selected = deck_tags.selection(result, vocabulary)
        return {'selection': selected, 'method': 'local-series-statistics',
                'vocabulary_revision': digest(vocabulary),
                'tag_names': {key: vocabulary[key]['name'] for key in selected['tag_ids']},
                'outcome': 'recognized' if selected['tag_ids'] else 'no_applicable_tags'}

    def start_tags(self, job):
        if job['tag_pending']: return
        job['tag_pending'] = True; job['tag_generation'] += 1
        generation = job['tag_generation']; deck = deepcopy(job['construction']['deck'])
        def analyze():
            try:
                result = self.recognize_tags(deck)
                with self.lock:
                    if not self.current(job) or generation != job['tag_generation']: return
                    if not isinstance(result, dict) or 'selection' not in result: raise ValueError('TAG 识别返回格式无效。')
                    deck_tags.selection(result['selection'], self.store.library.all_tags())
                    job['tag_result'] = deepcopy(result)
            except Exception as error:
                with self.lock:
                    if self.current(job) and generation == job['tag_generation']:
                        self.transition(job, 'failed', 'TAG 识别失败：'+str(error), 'tags')
            finally:
                with self.lock:
                    if generation == job['tag_generation']: job['tag_pending'] = False
        threading.Thread(target=analyze, daemon=True, name='ygopro-tag-analysis').start()

    def audit(self, job):
        self.transition(job, 'audit')
        frame, construction, tags = job['frame'], job['construction'], job['tag_result']
        opening = frame['opening']
        try:
            if (construction['round_id'] != frame['round_id'] or construction['capture_id'] != job['capture_id']
                    or construction['evidence']['game'] != job['game']
                    or opening.get('detected_order') != frame['detected_order']):
                raise ValueError('构筑、先后攻与起手不属于同一局。')
            if tags.get('vocabulary_revision') != digest(self.store.library.all_tags()): raise ValueError('TAG 资料已变化，请重试识别。')
            submitted = self.store.ygopro_capture.submitted_deck(job['capture_id'])
            self.validate_deck(submitted)
            label = 'YGOPRO2' if job.get('platform') == 'ygopro2' else 'YGOPro'
            inputs = self.store.automatic_duel.checked_input({'name': label + ' 本局构筑', 'deck': construction['deck'],
                        'tag_selection': tags['selection']}, submitted, opening['cards'])
            confirmed = {'order': frame['detected_order'], 'source': 'software-audit', 'confirmed_ms': self.now()}
            monitor = job['monitor']; monitor.round['confirmed'] = confirmed
            monitor.round['opening']['confirmed'] = {'snapshot_id': opening['snapshot_id'], 'cards': list(opening['cards']),
                                                      'source': 'software-audit', 'confirmed_ms': self.now()}
            monitor.persist(); job['frame'] = monitor.public()
            if frame['detected_order'] == 'second': self.transition(job, 'second'); return
            if frame['detected_order'] != 'first': raise ValueError('先后攻尚未确定。')
            inputs.update(hand=list(opening['cards']), round_id=frame['round_id'], snapshot_id=opening['snapshot_id'],
                          turn_order='first', recognition_id=job['id'], capture_id=job['capture_id'])
            job['context'] = self.store.automatic_duel.create(inputs)
            self.transition(job, 'ready')
        except (ValueError, OSError) as error:
            self.transition(job, 'failed', '自动校验失败：'+str(error), 'audit')
