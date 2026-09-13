"""Desktop-only resource projection, verified migration and owned-process lifetime."""
from contextlib import AbstractContextManager, nullcontext
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import uuid
import zipfile


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    replace_file(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def replace_file(path, data, durable=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('xb') as stream:
        stream.write(data)
        stream.flush()
        if durable: os.fsync(stream.fileno())
    os.replace(temporary, path)


class ServiceLock(AbstractContextManager):
    def __init__(self, path, create=True):
        if create: path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b' if create else 'r+b')
        if os.name == 'nt':
            import msvcrt
            try:
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.file.close()
                raise RuntimeError('该数据目录正在被另一服务使用，请先退出使用它的旧版练习室。') from None

    def __exit__(self, *_):
        self.file.close()


def local_child(root, relative):
    parts = PurePosixPath(relative)
    if parts.is_absolute() or '..' in parts.parts or '\\' in relative or ':' in relative or not parts.parts:
        raise ValueError('资源路径无效')
    path = root.joinpath(*parts.parts)
    if path.resolve() == root.resolve() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('资源路径超出数据目录')
    return path


def resource_allowed(name):
    path = PurePosixPath(name)
    if name in ('YGOPro.exe', 'cards.cdb', 'strings.conf', 'lflist.conf', 'system.conf', 'LICENSE'):
        return True
    return len(path.parts) > 1 and path.parts[0] in {'pics', 'script', 'textures', 'expansions'} and path.suffix.lower() in {'.jpg', '.png', '.lua', '.cdb', '.txt', '.conf'}


def prepare_resources(bundle, runtime):
    """Only package-owned resources are replaced; all user files stay outside the manifest."""
    runtime = runtime.resolve()
    marker = runtime / '.desktop-resources.json'
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('bundle-manifest.json'))
        files = manifest['files']
        for name in files:
            relative = PurePosixPath(name)
            if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name or not resource_allowed(name):
                raise ValueError(f'资源包含用户数据或未获准的文件：{name}')
        encoded = json.dumps(files, sort_keys=True).encode()
        if hashlib.sha256(encoded).hexdigest() != manifest['version']:
            raise ValueError('资源清单校验失败')
        previous = json.loads(marker.read_text('utf-8')) if marker.exists() else {}
        same_version = previous.get('version') == manifest['version']
        checked_directories = set()
        for name, expected in files.items():
            target = runtime / name
            if target.parent not in checked_directories:
                if not target.parent.resolve().is_relative_to(runtime):
                    raise ValueError('资源目录链接超出用户数据目录')
                checked_directories.add(target.parent)
            try: attributes = target.stat(follow_symlinks=False)
            except FileNotFoundError: attributes = None
            if attributes and getattr(attributes, 'st_file_attributes', 0) & 0x400:
                raise ValueError('资源文件不允许使用重新解析点')
            if name == 'system.conf' and attributes:
                continue
            if same_version and attributes and attributes.st_size == expected['size']:
                continue
            if attributes and digest(target) == expected['sha256']:
                continue
            data = archive.read(name)
            if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                raise ValueError(f'资源校验失败：{name}')
            # These bytes remain in the immutable package and can be repaired on the next launch.
            # Decks, reports and migration backups still use durable writes.
            replace_file(target, data, durable=False)
        write_json(marker, manifest)


def migration_inventory(source):
    result = {}
    for relative in ('_trainer/decks', '_trainer/backups', '_trainer/sessions', 'deck'):
        folder = source / relative
        if not folder.exists():
            continue
        if folder.is_symlink() or folder.is_junction():
            raise ValueError('迁移源中含目录联接或符号链接，拒绝越界复制')
        for path in sorted(folder.rglob('*')):
            if path.is_symlink() or path.is_junction():
                raise ValueError('迁移源中含目录联接或符号链接，拒绝越界复制')
            if not path.is_file() or path.suffix == '.tmp':
                continue
            result[path.relative_to(source).as_posix()] = {'size': path.stat().st_size, 'sha256': digest(path)}
    config = source / 'system.conf'
    if config.is_symlink(): raise ValueError('迁移配置不能是符号链接')
    if config.is_file():
        result['system.conf'] = {'size': config.stat().st_size, 'sha256': digest(config)}
    return result


def migrate_data(source, runtime):
    """First-use migration. Back up and verify before copying; resume a partial copy safely."""
    state_file = runtime.parent / 'migration.json'
    state = json.loads(state_file.read_text('utf-8')) if state_file.exists() else None
    if state and state['status'] == 'complete':
        return state
    if state is None:
        source = source.resolve(strict=True)
        if runtime.resolve().is_relative_to(source) or source.is_relative_to(runtime.resolve()):
            raise ValueError('迁移源和目标必须相互独立')
        if (runtime / '.desktop-resources.json').exists() or any((runtime / p).exists() for p in ('_trainer/decks', '_trainer/sessions', 'deck')):
            raise ValueError('目标已有桌面数据。请保留现有目录，改用一个空的 --data-dir 迁移，避免覆盖。')
        source_lock = source / '_trainer/service.lock'
        with ServiceLock(source_lock, create=False) if source_lock.exists() else nullcontext():
            # A legacy server can leave a native training window alive after it exits.
            from app import process_identity
            for path in (source / '_trainer/sessions').glob('*/session.json'):
                meta = json.loads(path.read_text('utf-8'))
                if meta.get('status') in ('starting', 'running', 'stopping') and meta.get('process_identity') and process_identity(meta.get('pid', 0)) == meta['process_identity']:
                    raise ValueError('迁移源仍有训练窗口，请先结束训练。')
            files = migration_inventory(source)
            backup = runtime.parent / 'migration-backups' / uuid.uuid4().hex
            backup.mkdir(parents=True)
            for name, expected in files.items():
                target = local_child(backup / 'files', name)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_child(source, name), target)
                if digest(target) != expected['sha256']:
                    raise ValueError('迁移备份校验失败，未迁移到运行目录')
            if migration_inventory(source) != files:
                raise ValueError('迁移过程中源数据发生变化，已保留备份，未迁移到运行目录')
            state = {'schema': 1, 'status': 'copying', 'source': str(source), 'backup': str(backup), 'files': files}
            write_json(backup / 'manifest.json', state)
            write_json(state_file, state)
    backup_root = Path(state['backup']) / 'files'
    for name, expected in state['files'].items():
        target = local_child(runtime, name)
        if target.exists() and digest(target) != expected['sha256']:
            raise ValueError(f'目标文件已改变，停止迁移并保留备份：{name}')
        if digest(local_child(backup_root, name)) != expected['sha256']:
            raise ValueError('迁移备份损坏，停止迁移')
    for name, expected in state['files'].items():
        target = local_child(runtime, name)
        if not target.exists():
            replace_file(target, local_child(backup_root, name).read_bytes())
        if digest(target) != expected['sha256']:
            raise ValueError('迁移结果校验失败，备份仍保留')
    state['status'] = 'complete'
    write_json(state_file, state)
    return state


class OwnedJob:
    """Windows job only contains engines created by this service; OS closes it on a crash."""
    def __init__(self):
        self.handle = None
        if os.name != 'nt':
            return
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', w.DWORD),
                        ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('reads', 'writes', 'other', 'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        kernel.CreateJobObjectW.restype = w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            error = ctypes.WinError(ctypes.get_last_error())
            process.terminate()
            process.wait(timeout=5)
            raise error

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
