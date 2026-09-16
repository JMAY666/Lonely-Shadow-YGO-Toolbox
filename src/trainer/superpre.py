"""Managed MyCard YPK lifecycle. The native engine and web catalog share one package.

Only the named archive belongs to this manager. Immutable generations and a durable
journal allow recovery without replacing base resources or touching player data.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import zipfile

from desktop_runtime import digest, local_child, replace_file, write_json

SOURCE_URL = 'https://mycard.world/ygopro/arena/#/superpre'
CDN = 'https://cdntx.moecube.com/ygopro-super-pre/'
ARCHIVE_NAME = 'ygopro-super-pre.ypk'
MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024
BUSY_REASON = '请先结束当前展开和决斗后台推演，等待场地退出后再管理补丁。'


def managed_root(runtime):
    return local_child(runtime, '_trainer/patches/superpre')


def archive_path(runtime):
    return local_child(runtime, 'expansions/' + ARCHIVE_NAME)


def validate_url(url, *, archive=False):
    value = urlsplit(url)
    if (value.scheme != 'https' or value.netloc not in ('cdntx.moecube.com', 'cdncf.moecube.com') or
            value.query or value.fragment or not value.path.startswith('/ygopro-super-pre/')):
        raise ValueError('官方补丁地址已变化，暂不支持此下载来源。')
    if archive and not re.fullmatch(r'/ygopro-super-pre/archive/ygopro-super-pre(?:-[\w.-]+)?\.ypk', value.path):
        raise ValueError('官方补丁下载地址格式无法识别。')
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, archive='/archive/' in req.full_url)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def remote_open(url):
    validate_url(url)
    return build_opener(SafeRedirect).open(Request(url, headers={
        'User-Agent': 'Lonely-Shadow-Yu-Gi-Oh-Toolbox', 'Cache-Control': 'no-cache'}), timeout=30)


def remote_text(url):
    with remote_open(url) as response:
        payload = response.read(4097)
    if len(payload) > 4096: raise ValueError('官方版本信息过长，已停止读取。')
    return payload.decode('utf-8-sig').strip()


def fetch_release():
    # These are the same two metadata endpoints used by the supplied official page.
    stamp = remote_text(CDN + 'data/version.txt')
    if not re.fullmatch(r'\d{10}', stamp): raise ValueError('官方更新时间格式无法识别。')
    url = remote_text(CDN + 'data/latest-tag.txt') or CDN + 'archive/' + ARCHIVE_NAME
    validate_url(url, archive=True)
    name = PurePosixPath(urlsplit(url).path).name
    return {'version': name.removeprefix('ygopro-super-pre-').removesuffix('.ypk')
            if name != ARCHIVE_NAME else stamp, 'updated_ms': int(stamp) * 1000,
            'download_url': url, 'checked_ms': int(time.time() * 1000)}


def download_release(url, target, progress):
    validate_url(url, archive=True)
    with remote_open(url) as response, target.open('xb') as output:
        total = int(response.headers.get('Content-Length', 0))
        if not 0 <= total <= MAX_DOWNLOAD: raise ValueError('补丁下载大小超过允许范围。')
        loaded, started = 0, time.monotonic()
        while chunk := response.read(256 * 1024):
            loaded += len(chunk)
            if loaded > MAX_DOWNLOAD or time.monotonic() - started > 300:
                raise ValueError('补丁下载超出大小或时间限制，请稍后重试。')
            output.write(chunk)
            progress('downloading', '正在下载官方补丁', loaded, total)
        output.flush(); os.fsync(output.fileno())
    if not loaded or total and loaded != total: raise ValueError('补丁下载不完整，请重试。')


def validate_metadata(value):
    if (not isinstance(value, dict) or value.get('schema') != 1 or
            not re.fullmatch(r'[0-9a-f]{64}', str(value.get('sha256', ''))) or
            not isinstance(value.get('files'), list) or not 0 < len(value['files']) <= 20000 or
            not isinstance(value.get('file_hashes'), dict)):
        raise ValueError('补丁安装记录无法读取，原文件已保留。')
    for name in value['files']:
        validate_member(name)
        if not re.fullmatch(r'[0-9a-f]{64}', str(value['file_hashes'].get(name, ''))):
            raise ValueError('补丁资源校验记录不完整。')
    if set(value['file_hashes']) != set(value['files']): raise ValueError('补丁资源校验记录不匹配。')
    if (not isinstance(value.get('version'), str) or not value['version'] or
            any(type(value.get(k)) is not int or value[k] <= 0 for k in ('updated_ms', 'installed_ms', 'card_count'))):
        raise ValueError('补丁版本记录无效。')
    validate_url(value.get('download_url', ''), archive=True)
    return value


def installed_metadata(runtime):
    path = managed_root(runtime) / 'installed.json'
    return validate_metadata(json.loads(path.read_text('utf-8'))) if path.exists() else None


def generation_root(runtime, metadata):
    validate_metadata(metadata)
    return local_child(managed_root(runtime), 'generations/' + metadata['sha256'])


def resource_files(runtime, suffix):
    """Irrlicht sorts archive members case-insensitively; archive DBs load last."""
    metadata = installed_metadata(runtime)
    if not metadata: return []
    root = generation_root(runtime, metadata) / 'files'
    return [local_child(root, name) for name in sorted(metadata['files'], key=str.casefold)
            if name.endswith(suffix)]


def resource_root(runtime):
    metadata = installed_metadata(runtime)
    return generation_root(runtime, metadata) / 'files' if metadata else None


def verify_projection(runtime, metadata):
    root = generation_root(runtime, metadata) / 'files'
    for name, expected in metadata['file_hashes'].items():
        if digest(local_child(root, name)) != expected: raise ValueError('补丁资源副本校验失败：' + name)


def validate_member(name):
    if not isinstance(name, str): raise ValueError('补丁资源路径无效。')
    parts = PurePosixPath(name)
    if (not name or name.startswith('/') or '\\' in name or ':' in name or
            any(p in ('', '.', '..') or p.rstrip(' .') != p for p in name.split('/')) or
            any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in parts.parts) or
            any(ord(c) < 32 for c in name)):
        raise ValueError('补丁含不安全的资源路径。')
    allowed = (len(parts.parts) == 1 and parts.suffix in ('.cdb', '.conf') or name == 'corres_srv.ini' or
               parts.parts[0] == 'script' and parts.suffix == '.lua' or
               parts.parts[0] == 'pics' and parts.suffix in ('.jpg', '.png') or
               parts.parts[0] == 'pack' and parts.suffix == '.ydk')
    if not allowed: raise ValueError('补丁含不支持的资源类型：' + name)


def inspect_archive(archive, destination):
    """Extract only known data types; verify CRC, SQLite integrity and native schema."""
    names, seen, expanded = [], set(), 0
    with zipfile.ZipFile(archive) as package:
        if len(package.infolist()) > 20000: raise ValueError('补丁资源数量超出允许范围。')
        for member in package.infolist():
            name = member.filename
            if member.is_dir():
                # Directory entries are never extracted. Still reject traversal and links.
                local_child(destination, name.rstrip('/'))
            else: validate_member(name)
            key = name.rstrip('/').casefold()
            if key in seen or stat.S_ISLNK(member.external_attr >> 16) or member.flag_bits & 1:
                raise ValueError('补丁包含重复、加密或链接资源。')
            seen.add(key)
            expanded += member.file_size
            if (expanded > MAX_EXPANDED or member.file_size > 64 * 1024 * 1024 or
                    member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValueError('补丁压缩格式或资源大小不兼容。')
            if name.endswith('.lua') and member.file_size >= 0x100000:
                raise ValueError('补丁脚本超过当前引擎的读取上限。')
            if member.is_dir(): continue
            target = local_child(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            names.append(name)
    databases = [name for name in names if name.endswith('.cdb')]
    if not databases: raise ValueError('补丁中没有卡牌数据库。')
    codes = set()
    for name in databases:
        with closing(sqlite3.connect(local_child(destination, name).as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok': raise ValueError('补丁卡库完整性检查失败。')
            expected = {'datas': {'id', 'ot', 'alias', 'setcode', 'type', 'atk', 'def', 'level', 'race', 'attribute', 'category'},
                        'texts': {'id', 'name', 'desc', *(f'str{i}' for i in range(1, 17))}}
            for table, columns in expected.items():
                schema = db.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
                if not schema or schema[0] != 'table' or not columns <= {r[1] for r in db.execute(f'PRAGMA table_info({table})')}:
                    raise ValueError('补丁卡库结构与当前规则引擎不兼容。')
            ids = {r[0] for r in db.execute('SELECT id FROM datas')}
            if ids != {r[0] for r in db.execute('SELECT id FROM texts')} or any(type(c) is not int or not 0 < c <= 0xffffffff for c in ids):
                raise ValueError('补丁卡牌编号或文本不完整。')
            codes.update(ids)
    if not codes: raise ValueError('补丁卡库为空。')
    return {'files': sorted(names, key=str.casefold), 'file_hashes': {name: digest(local_child(destination, name)) for name in names},
            'card_count': len(codes), 'file_count': len(names)}


class Superpre:
    def __init__(self, store):
        self.store = store
        self.root = managed_root(store.runtime)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.thread = None
        self.job = {'busy': False, 'action': '', 'phase': 'idle', 'message': '', 'error': '', 'loaded': 0, 'total': 0}
        self.latest = None
        self.recover()
        self.installed = installed_metadata(store.runtime)
        try:
            cached = json.loads((self.root / 'latest.json').read_text('utf-8'))
            validate_url(cached['download_url'], archive=True)
            if all(type(cached[k]) is int and cached[k] > 0 for k in ('updated_ms', 'checked_ms')) and isinstance(cached['version'], str): self.latest = cached
        except (OSError, ValueError, KeyError, TypeError): pass

    @property
    def mutating(self):
        return (self.job['busy'] and self.job['action'] != 'check') or (self.root / 'transaction.json').exists()

    def blocked_reason(self):
        if self.store.closing: return '应用正在退出，请重新启动后再操作。'
        if any(proc.poll() is None for proc in self.store.processes.values()): return BUSY_REASON
        for path in self.store.sessions.glob('*/session.json'):
            try:
                if self.store.alive(json.loads(path.read_text('utf-8'))): return BUSY_REASON
            except (OSError, ValueError, KeyError, TypeError): continue  # Damaged history is preserved, not executed.
        return ''

    def status(self):
        with self.lock:
            installed = {k: v for k, v in self.installed.items() if k not in ('files', 'file_hashes')} if self.installed else None
            return deepcopy({'source_url': SOURCE_URL, 'installed': installed, 'latest': self.latest,
                             'update_available': bool(self.installed and self.latest and
                                 any(self.installed.get(k) != self.latest[k] for k in ('updated_ms', 'download_url'))),
                             'job': self.job})

    def progress(self, phase, message, loaded=0, total=0):
        with self.lock: self.job.update(phase=phase, message=message, loaded=loaded, total=total)

    def start(self, action):
        if action not in ('check', 'install', 'update', 'uninstall'): raise ValueError('补丁操作无效。')
        acquired = False
        with self.store.lock, self.lock:
            if self.job['busy']: raise ValueError('补丁操作正在进行，请等待完成。')
            if action != 'check':
                if (self.root / 'transaction.json').exists():
                    raise ValueError('补丁恢复尚未完成，请检查磁盘空间并重新启动应用后再操作。')
                reason = self.blocked_reason()
                if reason: raise ValueError(reason)
                acquired = self.store.modular.planning_lock.acquire(blocking=False)
                if not acquired: raise ValueError(BUSY_REASON)
            try:
                if action == 'install' and self.installed: raise ValueError('补丁已经安装，请使用检查更新或更新。')
                if action in ('update', 'uninstall') and not self.installed: raise ValueError('请先安装超先行补丁。')
                self.job = {'busy': True, 'action': action, 'phase': 'checking', 'message': '正在准备',
                            'error': '', 'loaded': 0, 'total': 0}
                self.thread = threading.Thread(target=self.run, args=(action, acquired), daemon=True)
                self.thread.start()
            except Exception:
                if acquired: self.store.modular.planning_lock.release()
                self.job['busy'] = False
                raise
        return self.status()

    def run(self, action, acquired):
        try:
            if action == 'uninstall':
                self.progress('applying', '正在卸载超先行补丁')
                self.commit(None)
                self.progress('done', '补丁已卸载；卡组、方案和历史记录已保留。')
            else:
                self.progress('checking', '正在读取官方更新时间和下载地址')
                latest = fetch_release()
                write_json(self.root / 'latest.json', latest)
                with self.lock: self.latest = latest
                if action == 'check':
                    self.progress('done', '已读取官方最新版本。')
                else:
                    with tempfile.TemporaryDirectory(prefix='staging-', dir=self.root) as temporary:
                        stage = Path(temporary)
                        archive = stage / 'package.ypk'
                        download_release(latest['download_url'], archive, self.progress)
                        self.progress('validating', '正在检查卡库、脚本、卡图与资源格式')
                        details = inspect_archive(archive, stage / 'files')
                        candidate = {**latest, **details, 'schema': 1, 'sha256': digest(archive),
                                     'installed_ms': int(time.time() * 1000)}
                        destination = generation_root(self.store.runtime, candidate)
                        if destination.exists():
                            # Previously verified rollback generation: never overwrite its contents.
                            if digest(destination / 'package.ypk') != candidate['sha256']:
                                raise ValueError('本地补丁备份校验失败，原文件已保留。')
                            verify_projection(self.store.runtime, candidate)
                        else:
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            stage.rename(destination)
                        self.progress('applying', '正在启用补丁并刷新卡牌资源')
                        self.commit(candidate)
                    self.progress('done', '补丁已启用，卡库、效果脚本和卡图已同步。')
        except Exception as error:
            with self.lock:
                self.job.update(phase='error', error=f'操作未完成：{error}', message='请检查网络或本地文件后重试。')
        finally:
            # Release before publishing idle so another request cannot observe an idle but locked manager.
            if acquired: self.store.modular.planning_lock.release()
            with self.lock: self.job['busy'] = False

    def assert_owned(self, previous):
        path = archive_path(self.store.runtime)
        others = [p.name for p in (self.store.runtime / 'expansions').glob('*')
                  if p.suffix.lower() in ('.zip', '.ypk') and p != path]
        if others: raise ValueError('检测到其他扩展资源包，请先处理资源加载冲突：' + '、'.join(others))
        if path.exists() and (not previous or digest(path) != previous['sha256']):
            raise ValueError('安装位置存在非本应用管理或被外部修改的补丁，已保留该文件。')

    def project(self, metadata):
        target = archive_path(self.store.runtime)
        if metadata:
            source = generation_root(self.store.runtime, metadata) / 'package.ypk'
            if digest(source) != metadata['sha256']: raise ValueError('补丁备份校验失败，无法恢复。')
            replace_file(target, source.read_bytes())
            write_json(self.root / 'installed.json', metadata)
        else:
            target.unlink(missing_ok=True)
            (self.root / 'installed.json').unlink(missing_ok=True)

    def recover(self):
        journal = self.root / 'transaction.json'
        if not journal.exists(): return
        value = json.loads(journal.read_text('utf-8'))
        previous, candidate = value['previous'], value['next']
        for metadata in (previous, candidate):
            if metadata: validate_metadata(metadata)
        target = archive_path(self.store.runtime)
        if target.exists() and digest(target) not in {m['sha256'] for m in (previous, candidate) if m}:
            raise ValueError('补丁恢复时发现外部修改，已保留文件，请检查补丁目录。')
        self.project(previous)
        journal.unlink()

    def commit(self, candidate):
        with self.store.lock:
            if self.store.closing: raise ValueError('应用正在退出，本次补丁未启用。')
            previous = self.installed
            self.assert_owned(previous)
            journal = self.root / 'transaction.json'
            write_json(journal, {'previous': previous, 'next': candidate})
            try:
                self.project(candidate)
                self.store.reload_resources()
                journal.unlink()
            except Exception:
                self.recover()
                self.store.reload_resources()
                raise
            with self.lock: self.installed = candidate
