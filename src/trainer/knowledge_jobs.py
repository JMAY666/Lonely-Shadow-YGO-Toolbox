# -*- coding: utf-8 -*-
"""knowledge_jobs.py —— 显式产品规则引擎校验的持久化作业队列。

只调度所有者注入的回调（快照/身份复核/校验/入库），自身不加载用户包代码、
不启用对局、不导入归档实验、不联网、不派生进程；仅 passed 的 scoped 证据
按语义身份缓存复用，引擎场景成功不代表最优性，unknown 备注原样保留。
"""
import copy
import hashlib
import json
import threading
import time
import uuid

_HEX = set('0123456789abcdef')
_ACTIVE = ('queued', 'running', 'paused')
_CASE_DONE = ('passed', 'unknown', 'failed')
_RESUMABLE = ('cancelled', 'paused', 'failed')


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(payload):
    return hashlib.sha256(_canon(payload).encode('utf-8')).hexdigest()


class KnowledgeJobs:
    """规则引擎校验队列：单守护工作线程 + 原子落盘 + 纪元令牌防串写。"""

    def __init__(self, owner):
        self.owner = owner
        self.manager = owner.manager
        self._lock = threading.RLock()
        self._result_lock = threading.RLock()
        self._worker = None
        self._jobs = {}
        self._loaded = False
        self._load_errors = []
        self._prog_ts = {}

    def _parse_body(self, body):
        if not isinstance(body, dict):
            raise ValueError('请求体必须是对象')
        for key in ('project_id', 'route_id', 'build_id'):
            if not isinstance(body.get(key), str) or not body[key]:
                raise ValueError('缺少或非法的字段：%s' % key)
        raw_cases = body.get('cases')
        if not isinstance(raw_cases, list) or not raw_cases:
            raise ValueError('cases 必须是非空列表')
        if len(raw_cases) > 8:
            raise ValueError('用例数量超过上限（最多 8 个）')
        cases = []
        for item in raw_cases:
            if not isinstance(item, dict):
                raise ValueError('每个用例必须是对象')
            hand = item.get('hand')
            if (not isinstance(hand, list) or not hand or
                    any(isinstance(h, bool) or not isinstance(h, int) for h in hand)):
                raise ValueError('用例 hand 必须是非空整数列表，且不含布尔值')
            scenario = item.get('scenario', 'none')
            if scenario not in ('none', 'ash'):
                raise ValueError('场景取值非法，仅支持 none 或 ash')
            cases.append({'hand': list(hand), 'scenario': scenario})
        raw = body.get('limits') or {}
        if not isinstance(raw, dict):
            raise ValueError('limits 必须是对象')
        refresh = body.get('refresh', False)
        if not isinstance(refresh, bool):
            raise ValueError('refresh 必须是布尔值')
        limits = {}
        for key, default, lo, hi, integral in (('seconds', 15, 0, 32, False),
                                               ('nodes', 160, 1, 320, True),
                                               ('depth', 48, 1, 128, True)):
            value = raw.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int if integral else (int, float)):
                raise ValueError('limits.%s 数值类型非法（不允许布尔值）' % key)
            if not lo <= value <= hi or (key == 'seconds' and value <= 0):
                raise ValueError('limits.%s 必须在 %s~%s 范围内的正取值' % (key, lo, hi))
            limits[key] = value
        signature = _digest({'project_id': body['project_id'], 'route_id': body['route_id'],
                             'build_id': body['build_id'], 'cases': cases, 'limits': limits})
        return body['project_id'], body['route_id'], body['build_id'], cases, limits, refresh, signature

    def start(self, body):
        """新建或复用作业；快照、身份复核、入库等所有者调用一律在队列锁外。"""
        project_id, route_id, build_id, cases, limits, refresh, signature = self._parse_body(body)
        self._ensure_loaded()
        prepared = []
        for case in cases:
            try:
                snap = self.owner.verification_snapshot(project_id, route_id, build_id,
                                                        case['hand'], case['scenario'])
            except ValueError as exc:
                raise ValueError('生成校验快照失败（hand=%s, scenario=%s）：%s'
                                 % (case['hand'], case['scenario'], exc))
            if (not isinstance(snap, dict) or not isinstance(snap.get('identity'), str)
                    or len(snap['identity']) != 64 or any(c not in _HEX for c in snap['identity'])):
                raise ValueError('校验快照数据非法，拒绝构造作业')  # 绝不伪造有效快照
            snap = copy.deepcopy(snap)
            entry = {'snapshot': snap, 'status': 'pending', 'result': None, 'reused': False}
            prepared.append(entry)
        signature = _digest([signature, [case['snapshot']['identity'] for case in prepared]])
        job = {'id': uuid.uuid4().hex, 'signature': signature, 'project_id': project_id,
               'route_id': route_id, 'build_id': build_id, 'status': 'queued', 'epoch': 1,
               'revision': 0, 'created': time.time(), 'updated': time.time(), 'limits': limits,
               'cases': prepared, 'current': -1, 'progress': {}, 'error': '',
               'cancel_requested': False, 'refresh': refresh}
        if all(c['status'] == 'passed' for c in prepared):
            job['status'] = 'completed'
        with self._lock:
            if not refresh:
                dup = self._find_signature(signature)
                if dup is not None:
                    return self._view(dup)  # 并发重复提交：复用既有作业，不追加重复检查
            try:
                self._persist(job)
            except OSError as exc:
                raise OSError('作业落盘失败，未创建作业：%s' % exc)
            self._jobs[job['id']] = job
            view = self._view(job)
            queued = job['status'] == 'queued'
        if queued:
            self._spawn()
        return view

    def poll(self, job_id):
        job = self._require(job_id)
        snaps = []
        with self._lock:
            if job['status'] in ('queued', 'running', 'completed', 'paused'):
                snaps = [(i, copy.deepcopy(c['snapshot'])) for i, c in enumerate(job['cases'])
                         ]
        for _index, snap in snaps:  # 所有者调用在锁外
            if self._identity_current(snap):
                continue
            with self._lock:  # 只单向判过期，绝不回退为有效
                fresh = self._jobs.get(job['id'])
                if fresh is not None and fresh['status'] in ('queued', 'running', 'completed', 'paused'):
                    fresh['epoch'] += 1
                    fresh['cancel_requested'] = True  # 运行中的校验谓词可观察到
                    self._retreat_current(fresh)
                    fresh['status'] = 'stale'
                    fresh['error'] = '轮询发现语义输入已变化，作业过期，请新建作业'
                    try:
                        self._persist(fresh)
                    except OSError:
                        pass
            break
        with self._lock:
            return self._view(self._jobs.get(job['id']) or job)

    def cancel(self, job_id):
        job = self._require(job_id)
        with self._result_lock, self._lock:  # Cancellation and result publication have one commit ordering.
            if job['status'] in _ACTIVE:
                job['cancel_requested'] = True
                job['epoch'] += 1  # 迟到的回调结果因纪元不符被丢弃
                self._retreat_current(job)  # 已完成用例结果保留，中断用例回退待处理
                job['status'] = 'cancelled'
                job['error'] = '作业已取消，可恢复继续'
                try:
                    self._persist(job)
                except OSError as exc:
                    job['error'] = '已取消，但状态落盘失败（%s）' % exc
            return self._view(job)

    def resume(self, job_id):
        job = self._require(job_id)
        with self._lock:
            if job['status'] not in _RESUMABLE:
                raise ValueError('仅已取消/暂停/失败的作业可恢复（当前：%s），过期作业需新建' % job['status'])
            snaps = [copy.deepcopy(c['snapshot']) for c in job['cases']]
        stale = next((i for i, snap in enumerate(snaps) if not self._identity_current(snap)), None)
        if stale is not None:  # 含已完成用例在内的全部快照都要复核
            with self._lock:
                fresh = self._jobs.get(job['id'])
                if fresh is not None and fresh['status'] not in ('stale', 'completed'):
                    fresh['status'] = 'stale'
                    fresh['cancel_requested'] = True
                    fresh['error'] = '恢复时发现第 %d 个用例语义输入已变化，请新建作业' % (stale + 1)
                    try:
                        self._persist(fresh)
                    except OSError:
                        pass
                    job = fresh
                return self._view(job)
        with self._lock:
            job = self._jobs.get(job['id'])
            if job is None or job['status'] not in _RESUMABLE:
                return self._view(job)  # 并发状态下已被修改，按当前状态返回
            job['epoch'] += 1  # 旧纪元工作现场就此退休
            job['cancel_requested'] = False
            job['status'] = 'queued'
            job['error'] = ''
            job['progress'] = {}
            self._retreat_current(job)  # 只重跑待处理/被中断的用例
            try:
                self._persist(job)
            except OSError as exc:
                job['status'] = 'failed'
                job['error'] = '恢复落盘失败，未重新排队（%s）' % exc
                return self._view(job)
            view = self._view(job)
        self._spawn()
        return view

    def list(self, project_id=None):
        self._ensure_loaded()
        with self._lock:
            jobs = [self._view(j) for j in sorted(self._jobs.values(),
                                                  key=lambda j: j.get('created', 0))
                    if project_id is None or j.get('project_id') == project_id]
            return {'jobs': jobs, 'errors': [dict(e) for e in self._load_errors]}

    def invalidate(self, project_id):
        """项目编辑后调用：仅使快照身份不再匹配的作业过期，无关作业保持原状。"""
        self._ensure_loaded()
        with self._lock:
            targets = {j['id']: [copy.deepcopy(c['snapshot']) for c in j['cases']]
                       for j in self._jobs.values()
                       if j.get('project_id') == project_id and j['status'] in _ACTIVE + ('completed',)}
        touched = []
        for jid, snaps in targets.items():  # 身份复核在锁外
            if all(self._identity_current(s) for s in snaps):
                continue
            with self._lock:
                job = self._jobs.get(jid)
                if job is None or job['status'] not in _ACTIVE + ('completed',):
                    continue
                job['epoch'] += 1
                job['cancel_requested'] = True
                self._retreat_current(job)
                job['status'] = 'stale'
                job['error'] = '项目编辑后语义输入不再匹配，作业过期，请新建作业'
                try:
                    self._persist(job)
                except OSError:
                    pass
                touched.append(jid)
        return {'invalidated': touched}

    # ---------- 工作线程：单实例、串行、锁外调用所有者 ----------

    def _spawn(self):
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._worker_loop,
                                            name='knowledge-jobs-worker', daemon=True)
            self._worker.start()

    def _worker_loop(self):
        while not self._closing():
            task = self._claim_task()
            if task is not None:
                try: self._run_case(task)
                except Exception as error:
                    self._mark(task['job_id'], task['epoch'], 'failed', '校验任务异常，未发布结果：' + str(error), task['index'])
                continue
            with self._lock:  # 退出判定与入队在同一把锁下，杜绝重启竞态
                if not any(j['status'] == 'queued' for j in self._jobs.values()):
                    self._worker = None
                    return
        with self._lock:  # 应用关闭：直接退出，不自动重启
            if self._worker is threading.current_thread():
                self._worker = None

    def _claim_task(self):
        with self._lock:
            for job in sorted((j for j in self._jobs.values() if j['status'] == 'queued'),
                              key=lambda j: j.get('created', 0)):
                for index, case in enumerate(job['cases']):
                    if case['status'] != 'pending':
                        continue
                    case['status'] = 'running'
                    job['current'] = index
                    job['status'] = 'running'
                    job['error'] = ''
                    try:
                        self._persist(job)
                    except OSError as exc:  # 落盘失败即拒绝执行该任务
                        case.update(status='pending', result=None)
                        job['current'] = -1
                        job['status'] = 'failed'
                        job['error'] = '领取任务时落盘失败，已拒绝执行（%s）' % exc
                        try:
                            self._persist(job)
                        except OSError:
                            pass
                        break
                    return {'job_id': job['id'], 'index': index, 'epoch': job['epoch'],
                            'snapshot': copy.deepcopy(case['snapshot']),
                            'limits': dict(job['limits']), 'refresh': job.get('refresh', False)}
            return None

    def _run_case(self, task):
        job_id, index, epoch = task['job_id'], task['index'], task['epoch']
        snapshot, limits = task['snapshot'], task['limits']
        if not self._identity_current(snapshot):  # 校验前复核
            self._mark(job_id, epoch, 'stale',
                       '校验前身份复核失败（输入变化或依赖被移除），作业过期，请新建作业', index)
            return
        try:
            cached = None if task.get('refresh') else self._cache_read(snapshot['identity'])
            if cached:
                result = cached['result']
            else:
                result = self.owner.verify_case(snapshot, limits,
                                            lambda: self._cancelled(job_id, epoch),
                                            lambda info: self._progress(job_id, epoch, index, info))
        except ValueError as exc:  # 回调以 ValueError 表示取消或过期
            with self._lock:
                job = self._jobs.get(job_id)
                flagged = job is None or job['epoch'] != epoch or job.get('cancel_requested')
            if flagged:
                return  # 已由取消/过期路径接管，绝不覆盖
            if self._closing():
                self._mark(job_id, epoch, 'paused', '应用正在关闭，作业已暂停，可稍后恢复', index)
            elif self._identity_current(snapshot):
                self._mark(job_id, epoch, 'failed', '规则校验中止，输入仍有效，可恢复当前场景（%s）' % exc, index)
            else:
                self._mark(job_id, epoch, 'stale',
                           '校验中止（%s），语义范围可能已变化，请新建作业' % exc, index)
            return
        except (RuntimeError, OSError) as exc:
            self._mark(job_id, epoch, 'failed', '引擎/传输故障，用例保持待处理（%s）' % exc, index)
            return
        except Exception as exc:  # 其余异常同样不得伪称通过
            self._mark(job_id, epoch, 'failed', '校验异常，用例保持待处理（%s）' % exc, index)
            return
        if not isinstance(result, dict) or result.get('status') not in _CASE_DONE:
            self._mark(job_id, epoch, 'failed', '校验回调返回非法结果，用例保持待处理', index)
            return
        if self._cancelled(job_id, epoch):
            if self._closing(): self._mark(job_id, epoch, 'paused', '应用关闭，保留已完成场景，可恢复当前场景', index)
            return
        if not self._identity_current(snapshot):  # 校验后、提交前复核
            self._mark(job_id, epoch, 'stale', '校验后身份复核失败，作业过期，请新建作业', index)
            return
        with self._result_lock:
            if self._cancelled(job_id, epoch): return
            try:
                committed = bool(self.owner.store_verification(snapshot, result))
            except (ValueError, RuntimeError, OSError) as exc:
                self._mark(job_id, epoch, 'failed', '结果入库失败，用例保持待处理（%s）' % exc, index)
                return
            if not committed:
                self._mark(job_id, epoch, 'stale', '入库时语义范围已变化，作业过期，请新建作业', index)
                return
            if result['status'] == 'passed': self._cache_write(snapshot, result)
            with self._lock:
                job = self._jobs.get(job_id)
                if job and job['epoch'] == epoch: job['cases'][index]['reused'] = bool(cached)
            self._commit_result(job_id, epoch, index, result)

    def _commit_result(self, job_id, epoch, index, result):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job['epoch'] != epoch or job['cases'][index]['status'] != 'running':
                return  # 取消/过期已接管，迟到的结果直接丢弃
            case = job['cases'][index]
            case.update(status=result['status'], result=result)  # note/evidence 原样保留
            job['current'] = -1
            job['progress'] = {}
            self._prog_ts.pop(job_id, None)
            if not any(c['status'] == 'pending' for c in job['cases']):
                job['status'] = 'completed'
                job['error'] = ''
            else:
                job['status'] = 'queued'
            try:
                self._persist(job)  # 每个用例完成后落盘检查点
            except OSError as exc:
                case.update(status='pending', result=None)  # 未落盘不得宣称已提交
                job['status'] = 'failed'
                job['error'] = '验证证据已提交，但任务检查点保存失败；已暂停，恢复时核对现有证据（%s）' % exc
                try:
                    self._persist(job)
                except OSError:
                    pass

    def _mark(self, job_id, epoch, status, message, index=None):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job['epoch'] != epoch or job['status'] in ('cancelled', 'stale', 'completed'):
                return
            if index is not None and job['cases'][index]['status'] == 'running':
                job['cases'][index].update(status='pending', result=None)
                job['current'] = -1
            job['status'] = status
            job['error'] = message
            if status == 'stale':
                job['cancel_requested'] = True
            self._prog_ts.pop(job_id, None)
            try:
                self._persist(job)
            except OSError:
                pass  # 内存状态一致，落盘失败不影响安全方向（用例仍为待处理）

    def _cancelled(self, job_id, epoch):
        with self._lock:
            job = self._jobs.get(job_id)
            if (job is None or job['epoch'] != epoch or job.get('cancel_requested')
                    or job['status'] not in ('queued', 'running')):
                return True
        return self._closing()

    def _progress(self, job_id, epoch, index, info):
        if not isinstance(info, dict):
            return
        now = time.time()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job['epoch'] != epoch or job['cases'][index]['status'] != 'running':
                return
            merged = dict(job.get('progress') or {})
            merged.update(info)
            job['progress'] = merged
            if now - self._prog_ts.get(job_id, 0.0) >= 0.25:  # 节流：约每秒 4 次落盘
                self._prog_ts[job_id] = now
                try:
                    self._persist(job)
                except OSError as error:
                    job['status'] = 'failed'; job['cancel_requested'] = True; job['epoch'] += 1
                    self._retreat_current(job)
                    job['error'] = '进度保存失败，已停止校验：' + str(error)

    # ---------- 缓存与工具 ----------

    def _identity_current(self, snapshot):
        try:  # 依赖被移除等异常一律视为不再匹配
            return self.owner.current_identity(snapshot) == snapshot.get('identity')
        except Exception:
            return False

    def _closing(self):
        try:
            return bool(self.owner.closing())
        except Exception:
            return True

    def _cache_read(self, identity):
        if (not isinstance(identity, str) or len(identity) != 64
                or any(c not in _HEX for c in identity)):
            return None
        try:
            data = self.manager._read_json('validation-cache/%s.json' % identity)
        except Exception:
            return None
        if not isinstance(data, dict) or data.get('identity') != identity:
            return None
        snap, result = data.get('snapshot'), data.get('result')
        if (not isinstance(snap, dict) or not isinstance(result, dict)
                or snap.get('identity') != identity
                or result.get('status') != 'passed'
                or data.get('digest') != _digest({'snapshot': snap, 'result': result})):
            return None  # 损坏缓存不作静默复用
        return {'snapshot': snap, 'result': result}

    def _cache_write(self, snapshot, result):  # 仅 passed 结果写入缓存
        payload = {'snapshot': snapshot, 'result': result}
        record = {'identity': snapshot['identity'], 'digest': _digest(payload)}
        record.update(payload)
        try:
            self.manager._write_json('validation-cache/%s.json' % record['identity'], record)
        except OSError:
            pass  # 缓存写失败不影响已提交的结果

    def _require(self, job_id):
        if (not isinstance(job_id, str) or len(job_id) != 32
                or any(c not in _HEX for c in job_id)):
            raise ValueError('作业 ID 非法（需要 32 位十六进制）')
        self._ensure_loaded()
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ValueError('作业不存在：%s' % job_id)
        return job

    def _find_signature(self, signature):
        for job in self._jobs.values():
            if job.get('signature') == signature and job.get('status') in _ACTIVE + ('completed',):
                return job
        return None

    @staticmethod
    def _retreat_current(job):
        if 0 <= job.get('current', -1) < len(job['cases']):
            case = job['cases'][job['current']]
            if case['status'] == 'running':
                case.update(status='pending', result=None)
        job['current'] = -1

    def _persist(self, job):
        job['revision'] = job.get('revision', 0) + 1
        job['updated'] = time.time()
        try:
            self.manager._write_json('jobs/%s.json' % job['id'], job)
        except Exception as exc:
            raise OSError('作业持久化失败：%s' % exc)

    def _ensure_loaded(self):
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                folder = self.manager._safe_path('jobs')
                names = sorted(p.name for p in folder.glob('*.json')) if folder.exists() else []
            except Exception as exc:
                self._load_errors.append({'id': '', 'error': '作业目录不可读：%s' % exc})
                names = []
            for name in names:
                key = name[:-5]
                try:
                    data = self.manager._read_json('jobs/%s' % name)
                    if (not isinstance(data, dict) or not isinstance(data.get('cases'), list)
                            or data.get('status') not in ('queued', 'running', 'paused', 'cancelled', 'completed', 'stale', 'failed')
                            or not isinstance(data.get('id'), str) or data['id'] != key
                            or len(key) != 32 or any(c not in _HEX for c in key)
                            or not all(isinstance(c, dict) and isinstance(c.get('snapshot'), dict)
                                       and c.get('status') in ('pending', 'running') + _CASE_DONE
                                       for c in data['cases'])):
                        raise ValueError('文件结构非法')
                except Exception as exc:  # 损坏文件显式上报，绝不静默重置
                    self._load_errors.append({'id': key, 'error': '作业文件损坏，已跳过（%s）' % exc})
                    continue
                for field, default in (('signature', ''), ('epoch', 1), ('revision', 0),
                                       ('limits', {}), ('current', -1), ('progress', {}),
                                       ('error', ''), ('cancel_requested', False),
                                       ('created', 0), ('updated', 0)):
                    data.setdefault(field, default)
                if data['status'] in ('queued', 'running'):  # 进程重启：中断转暂停，不自动恢复
                    if data['status'] == 'running':
                        data['progress'] = dict(data.get('progress') or {})
                        data['progress']['note'] = '恢复边界：进程重启，运行中用例回退为待处理'
                    data['status'] = 'paused'
                    data['error'] = '进程重启，作业已暂停，需手动恢复'
                    self._retreat_current(data)
                self._jobs[key] = data

    def _view(self, job):
        cases = []
        for c in job['cases']:
            result = c.get('result') or {}
            cases.append({'hand': list(c['snapshot'].get('hand') or []),
                          'scenario': c['snapshot'].get('scenario'),
                          'status': c['status'], 'note': result.get('note', ''),
                          'evidence': result.get('evidence') if isinstance(result.get('evidence'), dict) else {},
                          'reused': bool(c.get('reused'))})
        limits = dict(job.get('limits') or {})
        return {'id': job['id'], 'status': job['status'], 'epoch': job.get('epoch', 1),
                'revision': job.get('revision', 0), 'project_id': job.get('project_id'),
                'route_id': job.get('route_id'), 'build_id': job.get('build_id'),
                'case_count': len(cases),
                'completed': sum(1 for c in job['cases'] if c['status'] in _CASE_DONE),
                'reused': sum(1 for c in job['cases'] if c.get('reused')),
                'current': job.get('current', -1), 'progress': dict(job.get('progress') or {}),
                'limits': limits, 'total_max_seconds': limits.get('seconds', 15) * len(cases),
                'overhead_note': '另计每场启动上限 30 秒、单次原生调用上限 4 秒及关闭等待；搜索不运行额外的未请求场景。',
                'cases': cases, 'error': job.get('error', ''),
                'cancel_requested': bool(job.get('cancel_requested')),
                'created': job.get('created'), 'updated': job.get('updated')}
