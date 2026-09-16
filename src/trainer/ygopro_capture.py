"""Read-only, build-verified capture of YGOPro's live deck editor.

No input, code injection, file import, or writes to the game process. Addresses
are RVAs for explicitly verified images, not guesses for unknown client builds.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import struct
import threading
import time
import uuid


PROFILES = {
    '55dd3e8ea4e9a0f24bb2b038e4c95f6e266140469be3480924ff1e57dda1e629': {
        'version': 'YGOPro 1.036.2 (x64)', 'deck': 0x6b4330,
        'game': 0x693e20, 'building': 0x114b, 'dragging': 0x1894, 'card_type': 0x28,
        'duel_info': 0xe08, 'player_type': 0xf30, 'lobby_window': 0x3158,
        'rps_window': 0x32d8, 'order_window': 0x32f8, 'gui_visible': 0xa8,
    },
}
ZONES = ('main', 'extra', 'side')
EXTRA_TYPES = 0x4802040


class CaptureError(ValueError):
    pass


def read_deck(memory, base, profile):
    """Validate the editor flag, vector bounds and every card before returning."""
    def editor():
        game = struct.unpack('<Q', memory.read(base + profile['game'], 8))[0]
        if game < 0x10000 or memory.read(game + profile['building'], 2) != b'\x01\x00':
            raise CaptureError('请在 YGOPro 中打开「编辑卡组」，并停留在编辑页面后重新获取。')
        if memory.read(game + profile['dragging'], 2) != b'\x00\x00':
            raise CaptureError('正在拖动卡牌，请放下卡牌后重新获取。')
        return game

    game = editor()
    address = base + profile['deck']
    header = memory.read(address, 72)
    values = struct.unpack('<9Q', header)
    result, buffers = {}, []
    for index, (zone, limit) in enumerate(zip(ZONES, (60, 15, 15))):
        start, finish, capacity = values[index * 3:index * 3 + 3]
        if start == finish == capacity == 0:
            result[zone] = []
            continue
        if not (0x10000 <= start <= finish <= capacity < 0x7fffffffffff
                and start % 8 == finish % 8 == capacity % 8 == 0
                and (finish - start) // 8 <= limit and capacity - start <= 8192):
            raise CaptureError('当前卡组数据不完整或数量超限，请停止拖动卡牌后重新获取。')
        raw = memory.read(start, finish - start)
        buffers.append((start, raw))
        codes = []
        for (pointer,) in struct.iter_unpack('<Q', raw):
            if pointer < 0x10000 or pointer % 4:
                raise CaptureError('卡牌数据正在变化，请重新获取。')
            data = memory.read(pointer, profile['card_type'] + 4)
            code = struct.unpack_from('<I', data)[0]
            card_type = struct.unpack_from('<I', data, profile['card_type'])[0]
            if not 0 < code <= 0x0fffffff or not card_type & 7 or card_type & 0x4000:
                raise CaptureError('读取到无效卡牌，请重新获取。')
            if zone != 'side' and bool(card_type & EXTRA_TYPES) != (zone == 'extra'):
                raise CaptureError('卡牌分区正在变化，请重新获取。')
            codes.append(code)
        result[zone] = codes
    if not any(result.values()):
        raise CaptureError('当前编辑器卡组为空，请放入卡牌后重新获取。')
    if editor() != game or memory.read(address, 72) != header or any(memory.read(a, len(b)) != b for a, b in buffers):
        raise CaptureError('读取期间卡组发生变化，请停止操作后重新获取。')
    return result


class WindowsProcess:
    def __init__(self, pid):
        if os.name != 'nt':
            raise CaptureError('进程捕捉目前仅支持 Windows。')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        k = self.kernel
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k.ReadProcessMemory.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        k.GetProcessTimes.restype = wintypes.BOOL
        self.handle = k.OpenProcess(0x410, False, pid)  # QUERY_INFORMATION | VM_READ
        if not self.handle:
            raise CaptureError('无法读取 YGOPro 进程；请确认游戏仍在运行，且与工具箱使用相同权限。')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.kernel.CloseHandle(self.handle)

    def read(self, address, size):
        if not 0 <= size <= 8192 or address < 0x10000:
            raise CaptureError('读取范围无效，请重新捕捉。')
        if not size:
            return b''
        buffer = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, buffer, size, ctypes.byref(count)) or count.value != size:
            raise CaptureError('YGOPro 数据暂时无法读取，请确认进程仍在运行后重新捕捉。')
        return buffer.raw

    def identity(self):
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(length)) or not self.kernel.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)):
            raise CaptureError('无法核对 YGOPro 进程身份，请重新捕捉。')
        return path.value, (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def image_base(self, pid):
        class Module(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('id', wintypes.DWORD), ('pid', wintypes.DWORD),
                        ('global_count', wintypes.DWORD), ('process_count', wintypes.DWORD),
                        ('base', ctypes.c_void_p), ('length', wintypes.DWORD), ('module', wintypes.HMODULE),
                        ('name', wintypes.WCHAR * 256), ('path', wintypes.WCHAR * 260)]
        k = self.kernel
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Module)]
        k.Module32FirstW.restype = wintypes.BOOL
        snapshot = k.CreateToolhelp32Snapshot(0x18, pid)
        if snapshot == ctypes.c_void_p(-1).value:
            raise CaptureError('无法核对 YGOPro 模块，请重新捕捉。')
        try:
            module = Module(); module.size = ctypes.sizeof(module)
            if not k.Module32FirstW(snapshot, ctypes.byref(module)) or module.name.casefold() != 'ygopro.exe':
                raise CaptureError('目标不是 YGOPro.exe，请重新捕捉。')
            return module.base
        finally:
            k.CloseHandle(snapshot)


def processes():
    if os.name != 'nt':
        raise CaptureError('进程捕捉目前仅支持 Windows。')
    class ProcessEntry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                    ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                    ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
                    ('name', wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for name in ('Process32FirstW', 'Process32NextW'):
        function = getattr(kernel, name)
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        function.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise CaptureError('无法枚举游戏进程，请重试。')
    found = []
    try:
        entry = ProcessEntry(); entry.size = ctypes.sizeof(entry)
        available = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while available:
            if entry.name.casefold() == 'ygopro.exe':
                item = {'pid': entry.pid, 'name': entry.name, 'path': '', 'title': '', 'supported': False}
                try:
                    with WindowsProcess(entry.pid) as process:
                        item['path'], item['created'] = process.identity()
                    image = Path(item['path'])
                    if image.stat().st_size > 128 * 1024 * 1024:
                        raise CaptureError('此 YGOPro 构建尚未适配。')
                    digest = hashlib.sha256(image.read_bytes()).hexdigest()
                    item.update(image_hash=digest, supported=digest in PROFILES,
                                version=PROFILES.get(digest, {}).get('version', '未适配的 YGOPro 构建'))
                except (OSError, CaptureError) as error:
                    item['error'] = str(error)
                found.append(item)
            available = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    by_pid = {item['pid']: item for item in found}
    @callback_type
    def visit(hwnd, _):
        pid = wintypes.DWORD(); user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in by_pid and user.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            user.GetWindowTextW(hwnd, title, len(title))
            if title.value:
                by_pid[pid.value]['title'] = title.value
        return True
    user.EnumWindows(visit, 0)
    return found


class Capture:
    def __init__(self):
        self.lock = threading.Lock()
        self.attached = None

    def attach(self, pid=None):
        with self.lock:
            self.attached = None
            found = processes()
            choices = [item for item in found if pid is None or item['pid'] == pid]
            if len(choices) != 1:
                return {'connected': False, 'processes': found, 'error':
                        '检测到多个 YGOPro 进程，请选择要捕捉的进程。' if len(choices) > 1 else
                        '未找到 YGOPro.exe，请打开游戏后点击「重新捕捉」。'}
            process = choices[0]
            if not process['supported']:
                return {'connected': False, 'processes': found, 'process': process,
                        'error': process.get('error') or '已找到进程，但此 YGOPro 构建尚未适配；不会使用猜测的卡组。'}
            self.attached = {**process, 'capture_id': uuid.uuid4().hex}
            return {'connected': True, 'process': self.attached}

    def deck(self, capture_id):
        with self.lock:
            attached = self.attached
            if not attached or capture_id != attached['capture_id']:
                raise CaptureError('进程捕捉已失效，请重新捕捉。')
            with WindowsProcess(attached['pid']) as memory:
                if memory.identity() != (attached['path'], attached['created']):
                    self.attached = None
                    raise CaptureError('YGOPro 进程已重新启动，请重新捕捉。')
                base = memory.image_base(attached['pid'])
                profile = PROFILES[attached['image_hash']]
                previous = read_deck(memory, base, profile)
                for _ in range(3):
                    time.sleep(.025)
                    current = read_deck(memory, base, profile)
                    if current == previous:
                        return {'deck': current, 'process': attached, 'captured_ms': time.time_ns() // 1_000_000,
                                'method': 'process-memory'}
                    previous = current
                raise CaptureError('卡组持续变化，请停止操作后重新获取。')

    def order(self, capture_id):
        with self.lock:
            attached = self.attached
            if not attached or capture_id != attached['capture_id']:
                raise CaptureError('进程捕捉已失效，请重新捕捉。')
            with WindowsProcess(attached['pid']) as memory:
                if memory.identity() != (attached['path'], attached['created']):
                    self.attached = None
                    raise CaptureError('YGOPro 进程已重新启动，请重新捕捉。')
                base = memory.image_base(attached['pid'])
                return read_order(memory, base, PROFILES[attached['image_hash']])


def read_order(memory, base, profile):
    """Use MSG_START's isFirst, gated by a completed first-turn transition."""
    def sample():
        game = struct.unpack('<Q', memory.read(base + profile['game'], 8))[0]
        info = memory.read(game + profile['duel_info'], 34)
        player = memory.read(game + profile['player_type'], 1)[0]
        if any(value not in (0, 1) for value in info[:12]) or player > 7:
            raise CaptureError('游戏状态正在变化，等待下一次读取。')
        windows = []
        for key in ('lobby_window', 'rps_window', 'order_window'):
            pointer = struct.unpack('<Q', memory.read(game + profile[key], 8))[0]
            visible = memory.read(pointer + profile['gui_visible'], 1)[0]
            if visible not in (0, 1):raise CaptureError('游戏窗口状态无效，请重新捕捉。')
            windows.append(bool(visible))
        return (game, *info[:8], info[11], player, struct.unpack_from('<i', info, 28)[0], *windows)

    first = sample(); second = sample()
    if first != second:raise CaptureError('游戏状态正在变化，等待下一次读取。')
    _, started, in_duel, finished, replay, _, is_first, tag, single, swapped, player, turn, lobby, rps, choosing = second
    if not 0 <= turn <= 100000:raise CaptureError('回合数据无效，请重新捕捉。')
    evidence = {'started':bool(started), 'in_duel':bool(in_duel), 'finished':bool(finished),
                'is_first':bool(is_first), 'turn':turn, 'player_type':player,
                'lobby_visible':lobby, 'rps_visible':rps, 'order_visible':choosing}
    order = None
    if replay or tag or single or swapped or player >= 7:
        phase = 'unsupported'
    elif lobby:
        phase = 'waiting_start'
    elif started and in_duel and not finished and turn >= 1:
        phase = 'detected'; order = 'first' if is_first else 'second'
    elif started and not finished:
        phase = 'choose_order' if choosing else 'rps' if rps else 'waiting_choice'
    elif finished:
        phase = 'ended'
    else:
        phase = 'waiting_start'
    return {'phase':phase, 'detected_order':order, 'evidence':evidence}
