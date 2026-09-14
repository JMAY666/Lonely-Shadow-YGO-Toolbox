"""Loopback-only deck library and training reports. Python 3.12+, standard library."""
import argparse
from collections import Counter
from copy import deepcopy
from contextlib import closing
import ctypes
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
import uuid
import webbrowser

from report import REPORT_VERSION, build_report, read_journal
from expansion import OPPONENT, draw_opening, plan_text, validate_conditions, training_settings
from timeline import route_rows, timeline_nodes
from review import annotations_for, confirmation_key, legacy_review, requirements
from plan_library import PlanLibrary
from plan_tags import tag_list
from plan_sharing import MAX_BYTES

WORKSPACE = Path(__file__).resolve().parents[2]
RUNTIME = WORKSPACE / '.local/YGOPro-Lite'
WEB = Path(__file__).parent / 'web'
EXTRA_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000


def now(): return time.time_ns() // 1_000_000


def atomic_json(path, data):
    atomic_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path): return json.loads(path.read_text(encoding='utf-8'))


def safe_child(root, relative):
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        raise ValueError('路径超出工作副本')
    return candidate


def process_identity(pid):
    """Creation time prevents attaching to a reused Windows PID. Never terminates it."""
    if os.name != 'nt': return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle: return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) or exit_code.value != 259: return None
        created, exited, cpu, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(cpu), ctypes.byref(user)): return None
        path, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)): return None
        return {'created': (created.dwHighDateTime << 32) | created.dwLowDateTime, 'path': str(Path(path.value).resolve())}
    finally: kernel.CloseHandle(handle)


class Catalog:
    def __init__(self, runtime):
        self.cards, self.sources = {}, []
        databases = [runtime / 'cards.cdb', *sorted((runtime / 'expansions').glob('*.cdb'))]
        for path in databases:
            if not path.exists(): raise ValueError(f'缺少卡牌数据库：{path.name}')
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                db.row_factory = sqlite3.Row
                sql = 'SELECT d.*,t.name,t.desc,' + ','.join(f't.str{i}' for i in range(1, 17)) + ' FROM datas d JOIN texts t ON d.id=t.id'
                for row in db.execute(sql):
                    card = dict(row)
                    card['source'] = path.relative_to(runtime).as_posix()
                    card['extra'] = bool(card['type'] & EXTRA_TYPES)
                    card['script_available'] = any((p / f"c{card['id']}.lua").exists() for p in (runtime / 'script', runtime / 'expansions/script'))
                    self.cards[card['id']] = card
            self.sources.append({'path': path.relative_to(runtime).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        self.archive_warning = [p.name for p in (runtime / 'expansions').glob('*') if p.suffix.lower() in ('.zip', '.ypk')]
        if self.archive_warning: raise ValueError('检测到尚未支持的扩展资源包；请先明确其与引擎的加载顺序，避免构筑资料不一致')

    def search(self, q, kind='', offset=0):
        q = q.strip().casefold()
        values = [c for c in self.cards.values() if (not q or q in c['name'].casefold() or q in c['desc'].casefold() or q == str(c['id']))
                  and (not kind or (kind == 'extra' and c['extra']) or (kind == 'monster' and c['type'] & 1)
                       or (kind == 'spell' and c['type'] & 2) or (kind == 'trap' and c['type'] & 4))]
        values.sort(key=lambda c: (c['name'], c['id']))
        return {'total': len(values), 'cards': values[offset:offset + 60]}


class Store:
    def __init__(self, runtime=RUNTIME, desktop=False, host=None):
        self.runtime = runtime.resolve()
        self.root = self.runtime / '_trainer'
        self.sessions = self.root / 'sessions'
        self.sessions.mkdir(parents=True, exist_ok=True)
        self.decks = self.root / 'decks'
        self.decks.mkdir(exist_ok=True)
        self.plans = self.root / 'plans'
        self.plans.mkdir(exist_ok=True)
        self.catalog = Catalog(self.runtime)
        self.lock = threading.RLock()
        self.library = PlanLibrary(self, read_json, atomic_json, now)
        self.processes = {}
        self.closing = False
        self.job = None
        self.host = host
        if desktop:
            from desktop_runtime import OwnedJob
            self.job = OwnedJob()
        self.refresh()

    def parse_deck(self, data):
        deck = {'main': [], 'extra': [], 'side': []}
        zone = 'main'
        for line in data.decode('utf-8-sig', errors='replace').splitlines():
            line = line.strip()
            if line in ('#main', '#extra', '!side'): zone = line.lstrip('#!'); continue
            if not line or line.startswith(('#', '!')): continue
            if not line.isdecimal() or not 0 < int(line) <= 0xffffffff: raise ValueError('YDK 包含无效卡牌编号')
            code = int(line)
            # Match the existing DeckManager: extra-deck types are classified by card type.
            card = self.catalog.cards.get(code)
            actual_zone = 'side' if zone == 'side' else ('extra' if card and card['extra'] else zone)
            deck[actual_zone].append(code)
        return deck

    def validate(self, deck, training=False):
        if not isinstance(deck, dict) or set(deck) != {'main', 'extra', 'side'}: raise ValueError('构筑分区无效')
        for zone, limit in (('main', 60), ('extra', 15), ('side', 15)):
            if not isinstance(deck[zone], list) or len(deck[zone]) > limit: raise ValueError(f'{zone} 数量超过 {limit}')
            for code in deck[zone]:
                if type(code) is not int or code not in self.catalog.cards: raise ValueError(f'数据库中找不到卡牌编号 {code}')
                card = self.catalog.cards[code]
                if card['type'] & 0x4000: raise ValueError('衍生物不能加入构筑')
                if zone != 'side' and card['extra'] != (zone == 'extra'): raise ValueError('卡牌类型与主卡组／额外卡组分区不一致')
        if training and not 40 <= len(deck['main']) <= 60: raise ValueError('开始训练需要 40–60 张主卡组')
        if training:
            missing = [str(c) for c in deck['main'] + deck['extra'] if not self.catalog.cards[c]['type'] & 0x10 and not self.catalog.cards[c]['script_available']]
            if missing: raise ValueError('缺少效果脚本，不能可靠训练：' + ', '.join(missing[:8]))

    @staticmethod
    def ydk(deck):
        return ('#created by YGO Trainer\n#main\n' + '\n'.join(map(str, deck['main'])) + '\n#extra\n' + '\n'.join(map(str, deck['extra'])) + '\n!side\n' + '\n'.join(map(str, deck['side'])) + '\n').encode('utf-8')

    def list_decks(self):
        result = []
        for source, root in (('library', self.decks), ('existing', self.runtime / 'deck')):
            for p in sorted(root.rglob('*.ydk')):
                if p.is_symlink(): continue
                identifier = source + '/' + p.relative_to(root).as_posix()
                result.append({'id': identifier, 'name': p.stem, 'source': source})
        return result

    def get_deck(self, identifier):
        source, sep, relative = identifier.partition('/')
        if not sep or source not in ('library', 'existing'): raise ValueError('构筑标识无效')
        p = safe_child(self.decks if source == 'library' else self.runtime / 'deck', relative)
        if p.suffix != '.ydk': raise ValueError('需要 YDK 文件')
        data = p.read_bytes()
        return {'id': identifier, 'name': p.stem, 'deck': self.parse_deck(data), 'revision': hashlib.sha256(data).hexdigest(), 'source': source}

    def save_deck(self, body):
        with self.lock:
            name = str(body.get('name', '')).strip()
            if not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]{1,80}', name) or name.endswith(('.', ' ')) or name.upper().split('.')[0] in {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}: raise ValueError('构筑名称含不可用字符')
            deck = body.get('deck'); self.validate(deck)
            p = safe_child(self.decks, name + '.ydk')
            if p.exists():
                old = p.read_bytes()
                if body.get('revision') != hashlib.sha256(old).hexdigest() or body.get('id') != 'library/' + p.name:
                    raise ValueError('同名构筑已存在或已被修改，请重新打开或使用新名称保存')
                backup = self.root / 'backups' / (uuid.uuid4().hex + '.ydk')
                atomic_bytes(backup, old)
            atomic_bytes(p, self.ydk(deck))
            return self.get_deck('library/' + p.name)

    def session_path(self, identifier):
        if str(uuid.UUID(identifier)) != identifier: raise ValueError('训练标识无效')
        return self.sessions / identifier

    def delete_deck(self, body):
        with self.lock:
            selected = self.get_deck(body.get('id', ''))
            if body.get('revision') != selected['revision']:
                raise ValueError('构筑已被修改，请重新选择后再删除')
            for meta_path in self.sessions.glob('*/session.json'):
                try: meta = read_json(meta_path)
                except (ValueError, OSError): continue
                if meta.get('selected_deck') == selected['id'] and meta.get('status') in ('starting', 'running', 'stopping') and self.alive(meta):
                    raise ValueError('此构筑正在训练，请先结束训练再删除')
            source, _, relative = selected['id'].partition('/')
            path = safe_child(self.decks if source == 'library' else self.runtime / 'deck', relative)
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != selected['revision']:
                raise ValueError('构筑已被修改，请重新选择后再删除')
            backup = self.root / 'backups/deleted' / uuid.uuid4().hex
            atomic_bytes(backup / 'deck.ydk', data)
            atomic_json(backup / 'metadata.json', {k: selected[k] for k in ('id', 'name', 'revision', 'source')} | {'deleted_ms': now()})
            if hashlib.sha256((backup / 'deck.ydk').read_bytes()).hexdigest() != selected['revision']:
                raise ValueError('删除备份校验失败，原构筑已保留')
            if hashlib.sha256(path.read_bytes()).hexdigest() != selected['revision']:
                raise ValueError('备份期间构筑已被修改，已保留原构筑，请重新选择')
            path.unlink()
            return {'id': selected['id'], 'backup': backup.relative_to(self.root).as_posix()}

    def alive(self, meta):
        proc = self.processes.get(meta['id'])
        if proc is not None: return proc.poll() is None
        return bool(meta.get('process_identity') and process_identity(meta.get('pid', 0)) == meta['process_identity'])

    def refresh(self):
        with self.lock:
            for p in self.sessions.glob('*/session.json'):
                try:
                    meta = read_json(p)
                    if meta['status'] not in ('running', 'starting', 'stopping'): continue
                    rows, issues = read_journal(p.parent / 'native.jsonl', meta['id'])
                    end = next((r for r in reversed(rows) if r.get('kind') == 'end'), None)
                    if end or not self.alive(meta):
                        meta['status'] = 'completed' if end and end.get('reason') == 'manual' else 'interrupted'
                        meta['end_reason'] = end.get('reason') if end else 'native_exit_without_end'
                        meta['ended_ms'] = end['time_ms'] if end else (rows[-1]['time_ms'] if rows else now())
                        if meta.get('plan_stage') == 'recording': meta['plan_stage'] = 'draft'
                        atomic_json(p, meta)
                        atomic_json(p.parent / 'report.json', build_report(meta, rows, issues))
                except (ValueError, KeyError, OSError):
                    # Retain damaged records. List endpoint exposes a recovery warning.
                    continue

    def history(self):
        self.refresh()
        result = []
        for p in self.sessions.glob('*/session.json'):
            try:
                meta = read_json(p)
                if meta.get('plan_stage') == 'discarded' and meta['status'] not in ('starting','running','stopping'): continue
                if (self.plans / 'deleted' / (meta['id'] + '.json')).exists(): meta['plan_stage'] = 'deleted'
                elif (self.plans / (meta['id'] + '.json')).exists():
                    meta['plan_stage'] = 'saved'
                    meta['name'] = read_json(self.plans / (meta['id'] + '.json'))['name']
                result.append({k: meta.get(k) for k in ('id', 'name', 'started_ms', 'ended_ms', 'status', 'end_reason', 'plan_stage', 'deck_name')})
            except (ValueError, OSError, KeyError, TypeError):
                result.append({'id': p.parent.name, 'name': '记录元数据损坏（原文件保留）', 'status': 'damaged', 'started_ms': 0})
        return sorted(result, key=lambda m: m['started_ms'], reverse=True)

    def start(self, identifier, design=None, retry_meta=None):
        with self.lock:
            if self.closing: raise ValueError('应用正在保存并退出，请稍候')
            self.refresh()
            if (any(proc.poll() is None for proc in self.processes.values()) or
                    any(r['status'] in ('running','starting','stopping') for r in self.history())):
                raise ValueError('请先结束当前展开，等待场地退出')
            if retry_meta:
                selected = {'id': identifier, 'name': retry_meta['deck_name'], 'deck': deepcopy(retry_meta['deck'])}
            elif design is not None and 'deck' in design:
                # A design owns a working snapshot; source changes/deletion cannot change it mid-attempt.
                deck_name, _ = plan_text({'name': design.get('deck_name')})
                selected = {'id': identifier, 'name': deck_name, 'deck': deepcopy(design['deck'])}
            else:
                selected = self.get_deck(identifier)
                if design and design.get('revision') != selected['revision']:
                    raise ValueError('源牌组已修改，请重新进入方案前置设计')
            deck = selected['deck']; self.validate(deck, training=True)
            expansion = None
            if retry_meta:
                expansion = deepcopy(retry_meta['expansion'])
            elif design is not None:
                name, notes = plan_text(design)
                conditions = validate_conditions(deck['main'], design.get('conditions'))
                settings = training_settings(design)
                opponent = deepcopy(design.get('opponent_config') or OPPONENT)
                if not isinstance(opponent, dict): raise ValueError('对手卡组配置无效')
                opponent['name'], _ = plan_text({'name': opponent.get('name')})
                # Disabled AI retains its settings; validate/draw the opponent only when enabled.
                if settings['opponent_ai']:
                    self.validate(opponent.get('deck'), training=True)
                    opponent['conditions'] = validate_conditions(opponent['deck']['main'], opponent.get('conditions',
                        {'slots': opponent.get('opening', [None]*5), 'banned': []}))
                    opponent_hand, opponent_rest = draw_opening(opponent['deck']['main'], opponent['conditions'])
                    opponent.update(actual_opening=opponent_hand, draw_order=opponent_hand + opponent_rest)
                hand, remaining = draw_opening(deck['main'], conditions)
                expansion = {'name': name, 'notes': notes, 'conditions': conditions, **settings,
                             'opponent_config': opponent,
                             'actual_opening': hand, 'draw_order': hand + remaining,
                             'engine_seed': 42 if self.host and self.host.test_control else secrets.randbits(32)}
            sid = str(uuid.uuid4()); path = self.session_path(sid); path.mkdir()
            data = self.ydk(deck)
            atomic_bytes(path / 'deck.ydk', data)
            meta = {'schema': 1, 'id': sid, 'name': selected['name'], 'selected_deck': identifier,
                    'started_ms': now(), 'ended_ms': None, 'status': 'starting', 'end_reason': None,
                    'deck': deck, 'deck_sha256': hashlib.sha256(data).hexdigest(),
                    'catalog': {str(c): self.catalog.cards[c] for c in set(sum(deck.values(), []))},
                    'sources': self.catalog.sources, 'engine_sha256': hashlib.sha256((self.runtime / 'YGOPro.exe').read_bytes()).hexdigest(),
                    'rule': 'Master Rule 2020 / core 8ff3583', 'opponent': 'empty; no AI; passes optional windows',
                    'legality': '构筑数量和类型校验；自由练习不执行禁限卡表及同名三张限制'}
            if expansion:
                if retry_meta:
                    for key in ('catalog', 'sources', 'engine_sha256', 'rule'):
                        meta[key] = deepcopy(retry_meta[key])
                meta.update(name=expansion['name'], deck_name=selected['name'], expansion=expansion, plan_stage='recording')
                ai = expansion['opponent_ai']
                opponent = expansion.get('opponent_config') or deepcopy(OPPONENT)
                if ai:
                    for code in set(sum(opponent['deck'].values(), [])):
                        meta['catalog'].setdefault(str(code), self.catalog.cards[code])
                    meta['opponent'] = opponent['name']
                # Native adapter reads a numeric config; original YDK and JSONL formats stay intact.
                settings = training_settings(expansion)
                opponent_order = opponent.get('draw_order')
                if ai and opponent_order is None:  # Old saved attempts used the fixed basic opponent.
                    opening = opponent.get('opening', OPPONENT['opening'])
                    opponent_order = draw_opening(opponent['deck']['main'], {'slots': opening, 'banned': []})
                    opponent_order = opponent_order[0] + opponent_order[1]
                opponent_order = opponent_order if ai else []
                opponent_hand = len(opponent.get('actual_opening', opponent.get('opening', OPPONENT['opening']))) if ai else 0
                extra = opponent['deck']['extra'] if ai else []
                if ai: atomic_bytes(path / 'opponent.ydk', self.ydk(opponent['deck']))
                values = [2, int(ai), expansion['engine_seed'], len(expansion['draw_order']), *expansion['draw_order'],
                          len(expansion['actual_opening']), int(settings['opponent_responses']),
                          int(settings['turn_order'] == 'second'), settings['player_lp'], settings['opponent_lp'],
                          opponent_hand, len(opponent_order), *opponent_order, len(extra), *extra]
                atomic_bytes(path / 'opening.cfg', (' '.join(map(str, values)) + '\n').encode('ascii'))
            atomic_json(path / 'session.json', meta)
            env = os.environ.copy(); env['YGO_TRAIN_SESSION'] = sid
            if self.host: env.update(self.host.environment())
            try:
                proc = subprocess.Popen([str(self.runtime / 'YGOPro.exe')], cwd=self.runtime, env=env)
                if self.job: self.job.assign(proc)
                self.processes[sid] = proc
                meta.update(pid=proc.pid, process_identity=process_identity(proc.pid), status='running')
            except OSError as exc:
                meta.update(status='interrupted', ended_ms=now(), end_reason='launch_failed')
                atomic_json(path / 'session.json', meta)
                raise ValueError(f'模拟器启动失败：{exc}') from exc
            atomic_json(path / 'session.json', meta)
            return {'id': sid, 'status': meta['status']}

    def design_from(self, identifier):
        report = self.report(identifier)
        if not report.get('expansion'): raise ValueError('此旧记录没有前置设计配置')
        expansion = deepcopy(report['expansion'])
        expansion.update(training_settings(expansion))
        expansion['conditions'] = validate_conditions(report['deck']['main'], expansion['conditions'])
        opponent = expansion.get('opponent_config') or deepcopy(OPPONENT)
        opponent.setdefault('conditions', {'hand_count': 5, 'slots': opponent.get('opening', [None]*5), 'banned': []})
        expansion['opponent_config'] = opponent
        return {**expansion, 'id': report['selected_deck'], 'deck_name': report.get('deck_name', report['name']),
                'deck': deepcopy(report['deck']), 'catalog': deepcopy(report['catalog'])}

    def return_to_design(self, identifier):
        with self.lock:
            design = self.design_from(identifier)  # Prepare recoverable configuration before stopping.
            path = self.session_path(identifier)
            meta = read_json(path / 'session.json')
            self.stop(identifier)
            deadline = time.monotonic() + 10
            while self.alive(meta) and time.monotonic() < deadline: time.sleep(0.05)
            if self.alive(meta): raise ValueError('场地仍在退出，配置与记录保留，请稍后重试')
            self.refresh()
            if not self.plan_path(identifier).exists(): self.discard_draft({'id': identifier})
            return design

    def discard_draft(self, body):
        with self.lock:
            identifier = body.get('id', '')
            if self.plan_path(identifier).exists(): raise ValueError('此内容已正式保存，请使用删除方案')
            self.refresh()
            path = self.session_path(identifier)
            meta = read_json(path / 'session.json')
            if self.alive(meta) or meta.get('plan_stage') not in ('draft', 'abandoned'):
                raise ValueError('请先结束展开，再放弃草稿')
            meta['plan_stage'] = 'abandoned'
            atomic_json(path / 'session.json', meta)
            return {'id': identifier, 'discarded': True}

    def restart(self, identifier):
        with self.lock:
            path = self.session_path(identifier)
            meta = read_json(path / 'session.json')
            if meta.get('retry_id'):
                return {'id': meta['retry_id'], 'status': read_json(self.session_path(meta['retry_id']) / 'session.json')['status']}
            if not meta.get('expansion') or meta.get('plan_stage') not in ('recording', 'draft', 'discarded'):
                raise ValueError('此记录不能重新展开')
            if meta['engine_sha256'] != hashlib.sha256((self.runtime / 'YGOPro.exe').read_bytes()).hexdigest():
                raise ValueError('引擎版本已改变，无法保证恢复相同初始状态，请创建新展开')
            meta['plan_stage'] = 'discarded'
            atomic_json(path / 'session.json', meta)
            self.stop(identifier)
            deadline = time.monotonic() + 10
            while self.alive(meta) and time.monotonic() < deadline: time.sleep(0.05)
            if self.alive(meta):
                current = read_json(path / 'session.json'); current['plan_stage'] = 'recording'
                atomic_json(path / 'session.json', current)
                raise ValueError('上一尝试仍在退出，请稍后重试；本次记录仍保留')
            self.refresh()
            result = self.start(meta['selected_deck'], retry_meta=meta)
            meta = read_json(path / 'session.json')
            meta['retry_id'] = result['id']
            atomic_json(path / 'session.json', meta)
            return result

    def plan_path(self, identifier):
        self.session_path(identifier)  # Validate UUID before forming a path.
        return self.plans / (identifier + '.json')

    def save_plan(self, body):
        with self.lock:
            identifier = body.get('id', '')
            target = self.plan_path(identifier)
            if (self.plans / 'deleted' / target.name).exists(): raise ValueError('此方案已删除，不能重复保存原草稿')
            # One session is one plan, including requests retried after a lost response.
            if target.exists(): return read_json(target)
            self.refresh()
            path = self.session_path(identifier)
            meta = read_json(path / 'session.json')
            if meta.get('plan_stage') != 'draft' or self.alive(meta): raise ValueError('请先结束展开，再保存待确认草稿')
            name, notes = plan_text(body)
            report = self.report(identifier)
            if not report['initial_hand'] or not report['final_state']:
                raise ValueError('未采集到完整起手和场面，请检查记录后重试')
            if [c['code'] for c in report['initial_hand']] != meta['expansion']['actual_opening'] or not report['loaded_verified']:
                raise ValueError('实际发牌与起手条件不一致，不能保存，请检查引擎版本')
            self.validate_review_save(report)
            annotations = annotations_for(report, body.get('annotations'))
            if report.get('review') and body.get('confirmation') != confirmation_key(report, name, notes, annotations):
                raise ValueError('请先核对最新保存摘要，再确认存入展开管理')
            snapshot = deepcopy(report)
            snapshot['name'] = name
            snapshot['expansion'].update(name=name, notes=notes)
            snapshot['plan_stage'] = 'saved'
            snapshot['saved_ms'] = now()
            snapshot['review'] = legacy_review(report)
            snapshot['annotations'] = annotations
            snapshot['requirements'] = requirements(report, annotations)
            snapshot['edit_revision'] = 1
            snapshot['classification'] = self.library.selection(snapshot)
            atomic_json(target, snapshot)
            # The immutable plan file is the commit point. Repairable display metadata comes second.
            meta.update(plan_stage='saved', name=name)
            meta['expansion'].update(name=name, notes=notes)
            try: atomic_json(path / 'session.json', meta)
            except OSError: pass
            return snapshot

    @staticmethod
    def validate_review_save(report):
        if report.get('plan_stage') == 'saved': return
        if report.get('status') != 'completed': raise ValueError('本次展开尚未完整结束，请完成展开后再保存')
        if not report.get('initial_hand') or not report.get('final_state') or not report.get('loaded_verified'):
            raise ValueError('起手、终场或构筑载入校验不完整，请核对原始记录')
        if (report.get('final_state') or {}).get('chain_depth', 0): raise ValueError('终场仍有未结束连锁，无法保存为完整方案')
        if report.get('review') and not report['review']['complete']:
            raise ValueError('缺少完整步骤快照，原始记录已保留，暂不能保存为完整方案')

    def preview_plan(self, body):
        with self.lock:
            report = self.report(body.get('id', ''))
            if report.get('plan_stage') not in ('draft', 'saved'): raise ValueError('没有有效待保存方案，请返回方案调整')
            self.validate_review_save(report)
            name, notes = plan_text(body)
            annotations = annotations_for(report, body.get('annotations'))
            return {'id': report['id'], 'name': name, 'notes': notes, 'annotations': annotations,
                    'saved': report.get('plan_stage') == 'saved', 'edit_revision': report.get('edit_revision', 0),
                    'original_name': report['name'], 'original_notes': report.get('expansion', {}).get('notes', ''),
                    'requirements': requirements(report, annotations),
                    'confirmation': confirmation_key(report, name, notes, annotations)}

    def list_plans(self):
        result = []
        vocabulary = self.library.all_tags()
        for path in self.plans.glob('*.json'):
            try:
                plan = read_json(path)
                selection = self.library.selection(plan, vocabulary)
                result.append({**{key: plan[key] for key in ('id', 'name', 'deck_name', 'saved_ms')},
                               'tags': tag_list(selection, vocabulary), 'tag_mode': selection.get('mode'), 'imported': plan.get('imported', False)})
            except (ValueError, OSError, KeyError):
                result.append({'id': path.stem, 'name': '方案文件损坏（原文件保留）', 'deck_name': '', 'saved_ms': 0})
        return sorted(result, key=lambda p: p['saved_ms'], reverse=True)

    def update_plan(self, body):
        with self.lock:
            target = self.plan_path(body.get('id', ''))
            plan = read_json(target)
            name, notes = plan_text(body)
            annotations = annotations_for(plan, body.get('annotations'))
            if (plan['name'], plan['expansion']['notes'], annotations_for(plan)) == (name, notes, annotations): return plan
            if (body.get('original_name'), body.get('original_notes')) != (plan['name'], plan['expansion']['notes']):
                raise ValueError('方案已在其他页面修改，请重新打开后再编辑；当前文字仍保留')
            if 'annotations' in body:
                if body.get('original_revision', 0) != plan.get('edit_revision', 0):
                    raise ValueError('方案说明已在其他页面修改，当前编辑已保留，请重新核对')
                if body.get('confirmation') != confirmation_key(plan, name, notes, annotations):
                    raise ValueError('保存摘要已过期，请返回修改后重新确认')
            backup = self.plans / 'revisions' / target.stem / f"{plan.get('edit_revision', 0)}.json"
            if not backup.exists(): atomic_json(backup, plan)
            plan['name'] = name
            plan['expansion'].update(name=name, notes=notes)
            plan['review'] = legacy_review(plan)
            plan['annotations'] = annotations
            plan['requirements'] = requirements(plan, annotations)
            plan['edit_revision'] = plan.get('edit_revision', 0) + 1
            atomic_json(target, plan)
            return plan

    def delete_plan(self, body):
        with self.lock:
            target = self.plan_path(body.get('id', ''))
            plan = read_json(target)
            if body.get('name') != plan['name']: raise ValueError('方案名称不匹配，请重新确认删除')
            # Atomic removal from the formal list, with a local recovery copy / late-save tombstone.
            deleted = self.plans / 'deleted' / target.name
            deleted.parent.mkdir(exist_ok=True)
            target.replace(deleted)
            return {'id': plan['id'], 'deleted': True}

    def stop(self, identifier):
        with self.lock:
            p = self.session_path(identifier); meta = read_json(p / 'session.json')
            if meta['status'] not in ('running', 'starting', 'stopping'): return {'id': identifier, 'status': meta['status']}
            atomic_bytes(p / 'stop.request', b'manual\n')
            meta['status'] = 'stopping'; atomic_json(p / 'session.json', meta)
            return {'id': identifier, 'status': 'stopping'}

    def timeline(self, identifier):
        folder = self.session_path(identifier)
        meta = read_json(folder / 'session.json')
        rows, issues = read_journal(folder / 'native.jsonl', identifier)
        active, full, valid = route_rows(rows)
        # Once input has branched, include the still-resolving portion of the current route.
        if valid and any(r.get('node') == valid[-1] for r in active): full = active
        report = build_report(meta, full, issues)
        nodes, pending = timeline_nodes(full, report['actions'])
        try: state = read_json(folder / 'timeline-state.json')
        except FileNotFoundError: state = {'revision': 0, 'cursor': None, 'at_node': False}
        try: operation = read_json(folder / 'rewind-operation.json')
        except FileNotFoundError: operation = None
        if operation and operation['status'] in ('queued', 'running'):
            committed = next((r for r in reversed(rows) if r.get('kind') == 'rewind' and r.get('token') == operation['token']), None)
            if committed and (state.get('cursor'), state.get('revision'), state.get('at_node')) == (committed['target'], committed.get('revision'), True):
                operation = {**operation, 'status': 'done', 'error': ''}
        alive = meta['status'] == 'running' and self.alive(meta)
        if operation and operation['status'] in ('queued', 'running') and not alive:
            operation = {**operation, 'status': 'error', 'error': 'engine_closed'}
        return {'id': identifier, **state, 'nodes': nodes, 'pending': pending,
                'available': alive and bool(nodes), 'operation': operation,
                'record_count': len(rows), 'warnings': issues}

    def rewind(self, body):
        with self.lock:
            identifier = body.get('id', '')
            timeline = self.timeline(identifier)
            if not timeline['available']: raise ValueError('此展开尚无可恢复节点，或场地已结束')
            if timeline['operation'] and timeline['operation']['status'] in ('queued', 'running'):
                raise ValueError('正在恢复场地，请等待本次回退完成')
            node, revision = body.get('node'), body.get('revision')
            if type(node) is not int or node not in [n['id'] for n in timeline['nodes']]:
                raise ValueError('此节点已退出当前路线，请刷新时间轴')
            if type(revision) is not int or revision != timeline['revision']:
                raise ValueError('场地已有新操作，请刷新时间轴后重试')
            token = uuid.uuid4().hex
            folder = self.session_path(identifier)
            operation = {'token': token, 'status': 'queued', 'node': node}
            atomic_json(folder / 'rewind-operation.json', operation)
            try: atomic_bytes(folder / 'rewind.request', f'{node} {revision} {token}\n'.encode('ascii'))
            except OSError:
                atomic_json(folder / 'rewind-operation.json', {**operation, 'status': 'error', 'error': 'write_failed'})
                raise
            return operation

    def shutdown(self, timeout=8):
        """Close only native processes launched here; preserve interrupted journals and reports."""
        with self.lock:
            self.closing = True
            owned = [p for p in self.processes.values() if p.poll() is None]
        if self.host: self.host.close_children(self)
        if os.name == 'nt':
            from ctypes import wintypes
            user = ctypes.WinDLL('user32', use_last_error=True)
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
            user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            pids = {p.pid for p in owned}
            def close_window(hwnd, _):
                pid = wintypes.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in pids: user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                return True
            user.EnumWindows(callback_type(close_window), 0)
        deadline = time.monotonic() + timeout
        for process in owned:
            try: process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.terminate()  # Popen retains the owned process handle, not an unverified PID.
                process.wait(timeout=5)
        if self.job: self.job.close()
        self.refresh()

    def report(self, identifier):
        self.refresh()
        plan = self.plan_path(identifier)
        if plan.exists(): return read_json(plan)
        deleted = self.plans / 'deleted' / plan.name
        if deleted.exists(): return read_json(deleted) | {'plan_stage': 'deleted'}
        p = self.session_path(identifier)
        meta = read_json(p / 'session.json')
        # Projection upgrades are separate files; never replace the old report, raw journal or deck snapshot.
        derived = p / f'report-v{REPORT_VERSION}.json'
        if derived.exists() and meta['status'] in ('completed', 'interrupted'):
            result = read_json(derived)
            if meta.get('plan_stage'): result['plan_stage'] = meta['plan_stage']
            return result
        rows, issues = read_journal(p / 'native.jsonl', identifier)
        report = build_report(meta, rows, issues)
        if meta['status'] in ('completed', 'interrupted'): atomic_json(derived, report)
        return report


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass

    def send(self, data, content_type='application/json; charset=utf-8', status=200):
        if not isinstance(data, bytes): data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(data)

    def dispatch(self, post=False):
        try:
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}': raise ValueError('仅接受本机工具箱请求')
            u = urlsplit(self.path); path = unquote(u.path); query = parse_qs(u.query)
            store = self.server.store
            if post:
                if self.headers.get('X-Trainer-Token') != self.server.token: raise ValueError('请求校验失败，请刷新页面')
                origin = self.headers.get('Origin')
                if origin and origin != f'http://127.0.0.1:{self.server.server_port}': raise ValueError('请求来源不匹配')
                length = int(self.headers.get('Content-Length', 0))
                maximum = MAX_BYTES if path in ('/api/plans/import', '/api/plans/import-preview') else 100_000
                if not 0 < length < maximum: raise ValueError('请求长度无效，分享文件上限为 20 MB')
                body = json.loads(self.rfile.read(length))
                if path == '/api/tags/save': return self.send(store.library.edit_tag(body))
                if path == '/api/plans/classify': return self.send(store.library.save_selection(body))
                if path == '/api/plans/import-preview': return self.send(store.library.import_document(body, preview=True))
                if path == '/api/plans/import': return self.send(store.library.import_document(body))
                if path == '/api/decks': return self.send(store.save_deck(body))
                if path == '/api/decks/delete': return self.send(store.delete_deck(body))
                if path == '/api/desktop/layout' and store.host: return self.send(store.host.layout(body, store))
                if path == '/api/native/test' and store.host: return self.send(store.host.test_event(store, body))
                if path == '/api/start': return self.send(store.start(body['deck_id'], body.get('design')))
                if path == '/api/stop': return self.send(store.stop(body['id']))
                if path == '/api/restart': return self.send(store.restart(body['id']))
                if path == '/api/rewind': return self.send(store.rewind(body))
                if path == '/api/return-to-design': return self.send(store.return_to_design(body['id']))
                if path == '/api/drafts/discard': return self.send(store.discard_draft(body))
                if path == '/api/plans/save': return self.send(store.save_plan(body))
                if path == '/api/plans/preview': return self.send(store.preview_plan(body))
                if path == '/api/plans/update': return self.send(store.update_plan(body))
                if path == '/api/plans/delete': return self.send(store.delete_plan(body))
                if path == '/api/shutdown':
                    self.send({'ok': True}); threading.Thread(target=self.server.shutdown, daemon=True).start(); return
            else:
                if path == '/api/bootstrap': return self.send({'token': self.server.token, 'cards': len(store.catalog.cards), 'sources': store.catalog.sources, 'runtime': str(store.runtime), 'embedded': bool(store.host)})
                if path == '/api/native/status' and store.host: return self.send(store.host.status(store, query['id'][0]))
                if path.startswith('/api/native/frame/') and store.host and store.host.test_control:
                    sid, frame = path.removeprefix('/api/native/frame/').split('/')
                    if not re.fullmatch(r'[0-9a-f]{32}\.png', frame): raise ValueError('场地截图标识无效')
                    return self.send((store.session_path(sid) / ('native-' + frame)).read_bytes(), 'image/png')
                if path == '/api/cards': return self.send(store.catalog.search(query.get('q', [''])[0], query.get('kind', [''])[0], max(0, int(query.get('offset', ['0'])[0]))))
                if path.startswith('/api/card/'):
                    code = int(path.rsplit('/', 1)[1]); return self.send(store.catalog.cards[code])
                if path == '/api/decks': return self.send(store.list_decks())
                if path == '/api/deck': return self.send(store.get_deck(query['id'][0]))
                if path == '/api/history': return self.send(store.history())
                if path == '/api/opponent': return self.send(OPPONENT)
                if path.startswith('/api/design/'): return self.send(store.design_from(path.rsplit('/', 1)[1]))
                if path.startswith('/api/ready/'):
                    return self.send({'ready': (store.session_path(path.rsplit('/', 1)[1]) / 'ready.json').exists()})
                if path == '/api/plans': return self.send(store.list_plans())
                if path.startswith('/api/plan-tags/'): return self.send(store.library.info(path.rsplit('/', 1)[1]))
                if path == '/api/tags': return self.send({'tags': list(store.library.all_tags().values()), 'revision': store.library.document()['revision']})
                if path.startswith('/api/plan-export/'): return self.send(store.library.export(path.rsplit('/', 1)[1]))
                if path.startswith('/api/plan/'): return self.send(read_json(store.plan_path(path.rsplit('/', 1)[1])))
                if path.startswith('/api/report/'): return self.send(store.report(path.rsplit('/', 1)[1]))
                if path.startswith('/api/timeline/'): return self.send(store.timeline(path.rsplit('/', 1)[1]))
                if path.startswith('/api/raw/'):
                    plan = store.plan_path(path.rsplit('/', 1)[1])
                    if plan.exists() and read_json(plan).get('imported'):
                        raise ValueError('此方案来自分享文件；可查看冻结事件，原生 JSONL 未随文件导入')
                    p = store.session_path(path.rsplit('/', 1)[1]) / 'native.jsonl'
                    return self.send(p.read_bytes(), 'text/plain; charset=utf-8')
                if path.startswith('/api/ydk/'):
                    plan = store.plan_path(path.rsplit('/', 1)[1])
                    if plan.exists(): return self.send(store.ydk(read_json(plan)['deck']), 'text/plain; charset=utf-8')
                    p = store.session_path(path.rsplit('/', 1)[1]) / 'deck.ydk'
                    return self.send(p.read_bytes(), 'text/plain; charset=utf-8')
                if path.startswith('/pics/'):
                    code = int(Path(path).stem)
                    for root in (store.runtime / 'expansions/pics', store.runtime / 'pics'):
                        for ext in ('.jpg', '.png'):
                            p = root / f'{code}{ext}'
                            if p.is_file(): return self.send(p.read_bytes(), mimetypes.guess_type(p.name)[0])
                    p = WEB / 'card-back.svg'; return self.send(p.read_bytes(), 'image/svg+xml')
                files = {'/': 'index.html', '/app.js': 'app.js', '/expansion.js': 'expansion.js', '/timeline.js': 'timeline.js', '/report-view.js': 'report-view.js', '/review.js': 'review.js', '/review.css': 'review.css', '/plan-tutorial.js': 'plan-tutorial.js', '/plan-tutorial.css': 'plan-tutorial.css', '/review-back.svg': 'review-back.svg', '/style.css': 'style.css', '/card-back.svg': 'card-back.svg'}
                if path in files:
                    p = WEB / files[path]; return self.send(p.read_bytes(), mimetypes.guess_type(p.name)[0] + '; charset=utf-8')
                if path in ('/activation.js', '/plan-library.js', '/plan-library.css'):
                    p = WEB / path[1:]; return self.send(p.read_bytes(), mimetypes.guess_type(p.name)[0] + '; charset=utf-8')
            self.send({'error': '内容不存在'}, status=404)
        except (ValueError, KeyError, FileNotFoundError, TypeError) as exc:
            self.send({'error': str(exc)}, status=400)
        except Exception:
            self.send({'error': '本地读写失败，原始数据已保留；请检查磁盘空间与日志'}, status=500)

    def do_GET(self): self.dispatch()
    def do_POST(self): self.dispatch(True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--runtime', type=Path, default=RUNTIME)
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--import-from', type=Path)
    parser.add_argument('--parent-pid', type=int)
    parser.add_argument('--embedded', action='store_true')
    parser.add_argument('--enable-native-test', action='store_true')
    args = parser.parse_args()
    from desktop_runtime import ServiceLock, migrate_data, prepare_resources
    runtime = args.runtime.resolve()
    # Acquire the target lock before migration or resource updates. No existing server is adopted.
    try: lock = ServiceLock(runtime / '_trainer/service.lock')
    except RuntimeError:
        if args.desktop or args.no_browser: raise
        webbrowser.open(f'http://127.0.0.1:{args.port}')
        return
    with lock:
        if args.import_from: migrate_data(args.import_from, runtime)
        if args.bundle: prepare_resources(args.bundle, runtime)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
        from desktop_host import NativeHost
        host = NativeHost(args.parent_pid, args.enable_native_test) if args.embedded else None
        try: server.store, server.token = Store(runtime, desktop=args.desktop, host=host), secrets.token_urlsafe(32)
        except Exception:
            server.server_close()
            raise
        url = f'http://127.0.0.1:{server.server_port}'
        atomic_json(server.store.root / 'service.json', {'pid': os.getpid(), 'url': url})
        parent = process_identity(args.parent_pid) if args.parent_pid else None
        stop_monitor = threading.Event()
        def monitor():
            while not stop_monitor.wait(0.5):
                server.store.refresh()
                if host:
                    try: host.sync(server.store)
                    except OSError: pass  # A native child can close between validation and placement.
                if args.desktop and args.parent_pid and (not parent or process_identity(args.parent_pid) != parent):
                    server.shutdown()
                    return
        threading.Thread(target=monitor, daemon=True).start()
        if args.desktop:
            # Pipe lifetime also covers an Electron crash before HTTP shutdown can be sent.
            def watch_parent_pipe():
                # A daemon blocked on BufferedReader.read can abort CPython during finalization.
                while os.read(sys.stdin.fileno(), 4096): pass
                server.shutdown()
            threading.Thread(target=watch_parent_pipe, daemon=True).start()
            print(json.dumps({'event': 'ready', 'pid': os.getpid(), 'url': url, 'token': server.token}), flush=True)
        elif not args.no_browser: webbrowser.open(url)
        try: server.serve_forever(poll_interval=0.3)
        finally:
            stop_monitor.set()
            server.server_close()
            if args.desktop: server.store.shutdown()
            (server.store.root / 'service.json').unlink(missing_ok=True)


if __name__ == '__main__': main()
