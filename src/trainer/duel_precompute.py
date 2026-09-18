"""Bounded, single-worker preparation of four preferences for confirmed inputs."""
from copy import deepcopy
import os
import threading
import time
import uuid

from duel import validate_hand
from modular_decisions import digest
from planning_preferences import PREFERENCES, DEFAULT_PREFERENCE


class Precompute:
    def __init__(self, modular):
        self.modular = modular
        self.lock = threading.RLock()
        self.jobs = {}
        self.worker = None
        self.rule_cache = None

    def rules(self, force=False):
        now = time.monotonic()
        if not force and self.rule_cache and now-self.rule_cache[0] < 2: return self.rule_cache[1]
        root = self.modular.store.runtime
        stamps = []
        for name in ('YGOPro.exe', 'cards.cdb'):
            path = root/name
            if path.exists():
                st = path.stat(); stamps.append((name, st.st_size, st.st_mtime_ns))
        for name in ('script', 'expansions'):
            for folder, _, files in os.walk(root/name):
                for filename in sorted(files):
                    if not filename.endswith(('.lua', '.cdb', '.ypk')): continue
                    path = os.path.join(folder, filename); st = os.stat(path)
                    stamps.append((os.path.relpath(path, root), st.st_size, st.st_mtime_ns))
        value = digest([sorted(stamps), self.modular.store.catalog.sources])
        self.rule_cache = (now, value)
        return value

    def identity(self, body, force=False):
        store = self.modular.store
        saved = store.get_deck(body.get('deck_id', ''))
        if saved['revision'] != body.get('revision'): raise ValueError('卡组已修改，请重新确认构筑和起手')
        validate_hand(saved['deck'], body.get('hand_count'), body.get('hand'))
        self.modular.library.sync()
        selected = body.get('sources', [])
        self.modular.library.validate_deck_sources(saved.get('tag_selection', {}), selected)
        state = None
        if body.get('id'):
            from duel_planner import context
            sid, ctx = context(self.modular, body)
            state = self.modular.state(sid)
        inputs = {k: deepcopy(body.get(k)) for k in ('consumer', 'automatic_context', 'session', 'slot', 'deck_id', 'revision', 'hand', 'anchor', 'id', 'precise', 'goal')}
        inputs.update(sources={s: self.modular.library.entries[s]['version'] for s in sorted(set(selected))},
                      rules=self.rules(force), state=state)
        return digest(inputs)

    @staticmethod
    def owner(body):
        owner = body.get('automatic_context') if body.get('consumer') == 'automatic-duel' else body.get('session')
        if not isinstance(owner, str) or not 1 <= len(owner) <= 100: raise ValueError('缺少本局标识')
        return (body['consumer'], owner, body.get('slot', 'opening'))

    def cancel(self, job):
        job.update(cancelled=True, status='cancelled', data=None)
        ctx = self.modular.sessions.get(job.get('sid'))
        if ctx and not job.get('adopted'): ctx['forecast_cancelled'] = True

    def dispatch(self, intent, body):
        owner = self.owner(body)
        if intent == 'plan-prepare':
            version = self.identity(body)
            with self.lock:
                current = next((j for j in self.jobs.values() if j['owner'] == owner and not j['cancelled'] and not j.get('adopted')), None)
                if current and current['body'].get('request_generation', 0) > body.get('request_generation', 0):
                    raise ValueError('过期的预计算请求已忽略')
                if current and current['version'] == version and not body.get('refresh'):
                    current['touched'] = time.monotonic()
                    return self.view(current, body, reused=True)
                inherited = bool(current and body.get('id') and current.get('sid') == body['id'])
                if current:
                    if inherited: current['keep_session'] = True
                    self.cancel(current)
                active = [j for j in self.jobs.values() if not j['cancelled']]
                if len(active) >= 4: self.cancel(min(active, key=lambda j: j['touched']))
                identifier = uuid.uuid4().hex
                job = {'job': identifier, 'owner': owner, 'version': version, 'body': deepcopy(body),
                       'status': 'queued', 'created': time.monotonic(), 'touched': time.monotonic(),
                       'cancelled': False, 'sid': None, 'data': None,
                       'owns_session': current.get('owns_session', True) if inherited else not body.get('id')}
                self.jobs[identifier] = job
                self.ensure_worker()
                return self.view(job, body)
        with self.lock:
            job = self.jobs.get(body.get('job'))
            if not job or job['owner'] != owner: raise ValueError('预计算已释放，请重试')
            job['touched'] = time.monotonic()
        if intent == 'plan-cancel':
            with self.lock: self.cancel(job)
            return {'job': job['job'], 'status': 'cancelled', 'inputs': {}}
        if not job['cancelled']:
            try: valid = self.identity(job['body']) == job['version']
            except (ValueError, OSError): valid = False
            if not valid:
                with self.lock: self.cancel(job); job['status'] = 'stale'
        return self.view(job, body, reused=True)

    def view(self, job, body, reused=False):
        preference = body.get('preference', DEFAULT_PREFERENCE)
        if preference == 'safest': preference = DEFAULT_PREFERENCE
        if preference not in PREFERENCES: raise ValueError('路线偏好无效')
        ctx = self.modular.sessions.get(job.get('sid'), {})
        result = {'job': job['job'], 'version': job['version'], 'status': job['status'], 'id': job['sid'],
                  'inputs': {'version': job['version']}, 'reused': reused,
                  'progress': deepcopy(ctx.get('forecast_progress', {})), 'error': job.get('error'),
                  'background_seconds': round(time.monotonic()-job['created'], 3) if job['status'] in ('queued', 'running') else job.get('seconds'),
                  'preferences': {p: {'status': job['status'], 'complete': r.get('complete', False), 'candidates': len(r['candidates'])}
                                  for p, r in ctx.get('forecast_bank', {}).items()} if job.get('data') else {p: {'status': job['status']} for p in PREFERENCES}}
        if job.get('data') and not job['cancelled']:
            result['data'] = deepcopy(job['data'])
            result['data']['result'] = self.modular.public_result(ctx['forecast_bank'][preference])
            result['data']['result']['cache']['prepared_hit'] = reused
        elif job['status'] == 'running' and ctx.get('forecast_partial') and ctx.get('forecast_meta'):
            from duel_planner import response
            result['partial'] = response(self.modular, job['sid'], ctx, ctx['forecast_partial'])
        return result

    def validate_adoption(self, body):
        with self.lock:
            job = self.jobs.get(body.get('job'))
            if not job or job['owner'] != self.owner(body) or job['cancelled'] or job['status'] not in ('ready', 'partial'):
                raise ValueError('预计算未完成或已失效，请重试')
            if body.get('version') != job['version'] or body.get('id') != job['sid']:
                raise ValueError('候选状态版本已变化')
        if self.identity(job['body'], force=True) != job['version']:
            with self.lock: self.cancel(job)
            raise ValueError('构筑、起手、来源、规则或计算起点已变化，请采用重新计算的候选')

    def adopted(self, identifier):
        with self.lock:
            if identifier in self.jobs: self.jobs[identifier].update(adopted=True, cancelled=True, data=None, status='adopted')

    def ensure_worker(self):
        if self.worker and self.worker.is_alive(): return
        self.worker = threading.Thread(target=self.run, name='duel-precompute', daemon=True)
        self.worker.start()

    def close_owner(self, consumer, owner):
        with self.lock:
            for job in self.jobs.values():
                if job['owner'][:2] == (consumer, owner): self.cancel(job)

    def invalidate_all(self):
        with self.lock:
            for job in self.jobs.values(): self.cancel(job)
            self.rule_cache = None

    def run(self):
        from duel_planner import generate, close
        while not self.modular.store.closing:
            with self.lock:
                for job in self.jobs.values():
                    if time.monotonic()-job['touched'] > 900: self.cancel(job)
                removed = [j for j in self.jobs.values() if j['cancelled'] and j.get('finished', True)]
                for job in removed: self.jobs.pop(job['job'], None)
                job = next((j for j in self.jobs.values() if j['status'] == 'queued'), None)
                if job: job.update(status='running', finished=False)
            for old in removed:
                if old.get('sid') and old.get('owns_session') and not old.get('adopted') and not old.get('keep_session'):
                    with self.modular.planning_lock: close(self.modular, old['sid'])
            if not job:
                time.sleep(.25); continue
            def started(sid, ctx):
                with self.lock:
                    job['sid'] = sid
                    ctx['forecast_cancelled'] = job['cancelled']
                    ctx['forecast_job'] = job['job']
                    ctx.pop('forecast_partial', None)
            try:
                # Search has its own bounded worker and native bridge lock.
                # Do not hold the UI mutation lock while searching another
                # session: confirming an adopted tutorial must remain usable.
                if job['cancelled']: continue
                data = generate(self.modular, {**job['body'], 'all_preferences': True}, on_started=started)
                valid = self.identity(job['body']) == job['version']
                with self.lock:
                    if job['cancelled'] or not valid:
                        self.cancel(job)
                    else:
                        # Replaying a confirmed anchor advances its projection;
                        # publish the version guard again only after it succeeds.
                        self.modular.sessions[job['sid']]['forecast_job'] = job['job']
                        bank = self.modular.sessions[job['sid']]['forecast_bank']
                        job.update(data={k: v for k, v in data.items() if k != 'result'},
                                   status='ready' if all(r.get('complete') for r in bank.values()) else 'partial',
                                   seconds=round(time.monotonic()-job['created'], 3))
            except Exception as error:
                with self.lock:
                    if not job['cancelled']: job.update(status='failed', error=str(error), seconds=round(time.monotonic()-job['created'], 3))
            finally:
                with self.lock: job['finished'] = True
