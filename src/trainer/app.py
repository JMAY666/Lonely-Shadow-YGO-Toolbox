"""Loopback-only deck library and training reports. Python 3.12+, standard library."""
import argparse
from collections import Counter
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
        self.catalog = Catalog(self.runtime)
        self.lock = threading.RLock()
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
                result.append({k: meta.get(k) for k in ('id', 'name', 'started_ms', 'ended_ms', 'status', 'end_reason')})
            except (ValueError, OSError):
                result.append({'id': p.parent.name, 'name': '记录元数据损坏（原文件保留）', 'status': 'damaged', 'started_ms': 0})
        return sorted(result, key=lambda m: m['started_ms'], reverse=True)

    def start(self, identifier):
        with self.lock:
            if self.closing: raise ValueError('应用正在保存并退出，请稍候')
            self.refresh()
            if any(r['status'] in ('running', 'starting', 'stopping') for r in self.history()): raise ValueError('请先结束当前训练')
            selected = self.get_deck(identifier)
            deck = selected['deck']; self.validate(deck, training=True)
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

    def stop(self, identifier):
        with self.lock:
            p = self.session_path(identifier); meta = read_json(p / 'session.json')
            if meta['status'] not in ('running', 'starting', 'stopping'): return {'id': identifier, 'status': meta['status']}
            atomic_bytes(p / 'stop.request', b'manual\n')
            meta['status'] = 'stopping'; atomic_json(p / 'session.json', meta)
            return {'id': identifier, 'status': 'stopping'}

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
        p = self.session_path(identifier)
        meta = read_json(p / 'session.json')
        # Projection upgrades are separate files; never replace the old report, raw journal or deck snapshot.
        derived = p / f'report-v{REPORT_VERSION}.json'
        if derived.exists() and meta['status'] in ('completed', 'interrupted'):
            return read_json(derived)
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
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
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
                if not 0 < length < 100_000: raise ValueError('请求长度无效')
                body = json.loads(self.rfile.read(length))
                if path == '/api/decks': return self.send(store.save_deck(body))
                if path == '/api/decks/delete': return self.send(store.delete_deck(body))
                if path == '/api/desktop/layout' and store.host: return self.send(store.host.layout(body, store))
                if path == '/api/native/test' and store.host: return self.send(store.host.test_event(store, body))
                if path == '/api/start': return self.send(store.start(body['deck_id']))
                if path == '/api/stop': return self.send(store.stop(body['id']))
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
                if path.startswith('/api/report/'): return self.send(store.report(path.rsplit('/', 1)[1]))
                if path.startswith('/api/raw/'):
                    p = store.session_path(path.rsplit('/', 1)[1]) / 'native.jsonl'
                    return self.send(p.read_bytes(), 'text/plain; charset=utf-8')
                if path.startswith('/api/ydk/'):
                    p = store.session_path(path.rsplit('/', 1)[1]) / 'deck.ydk'
                    return self.send(p.read_bytes(), 'text/plain; charset=utf-8')
                if path.startswith('/pics/'):
                    code = int(Path(path).stem)
                    for root in (store.runtime / 'expansions/pics', store.runtime / 'pics'):
                        for ext in ('.jpg', '.png'):
                            p = root / f'{code}{ext}'
                            if p.is_file(): return self.send(p.read_bytes(), mimetypes.guess_type(p.name)[0])
                    p = WEB / 'card-back.svg'; return self.send(p.read_bytes(), 'image/svg+xml')
                files = {'/': 'index.html', '/app.js': 'app.js', '/report-view.js': 'report-view.js', '/style.css': 'style.css', '/card-back.svg': 'card-back.svg'}
                if path in files:
                    p = WEB / files[path]; return self.send(p.read_bytes(), mimetypes.guess_type(p.name)[0] + '; charset=utf-8')
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
