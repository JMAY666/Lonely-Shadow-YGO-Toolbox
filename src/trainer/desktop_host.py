"""Own-process native child-window hosting. Never sends global mouse or keyboard input."""
import ctypes
from ctypes import wintypes as w
import json
import math
import time
import uuid


class NativeHost:
    def __init__(self, parent_pid, test_control=False):
        from app import process_identity
        self.parent_pid = parent_pid
        self.parent_identity = process_identity(parent_pid)
        self.test_control = test_control
        self.hwnd = None
        self.rect = (0, 0, 1024, 640)
        self.visible = False
        self.user = u = ctypes.WinDLL('user32', use_last_error=True)
        u.IsWindow.argtypes = [w.HWND]
        u.GetParent.argtypes = [w.HWND]; u.GetParent.restype = w.HWND
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.MapWindowPoints.argtypes = [w.HWND, w.HWND, ctypes.POINTER(w.POINT), w.UINT]
        u.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]; u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
        u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        u.IsWindowVisible.argtypes = [w.HWND]
        u.ChildWindowFromPointEx.argtypes = [w.HWND, w.POINT, w.UINT]
        u.ChildWindowFromPointEx.restype = w.HWND
        self.last_placement = {}

    def pid(self, hwnd):
        result = w.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(result))
        return result.value

    def layout(self, body, store):
        from app import process_identity
        hwnd = int(body['hwnd'])
        if not self.parent_identity or process_identity(self.parent_pid) != self.parent_identity or self.pid(hwnd) != self.parent_pid or not self.user.IsWindow(hwnd):
            raise ValueError('桌面主窗口已失效，无法嵌入训练场地')
        visible = body.get('visible') is True
        if visible:
            values = [body.get(k) for k in ('x', 'y', 'width', 'height', 'viewportWidth', 'viewportHeight')]
            if not all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 32768 for v in values):
                raise ValueError('训练区域尺寸无效')
            x, y, width, height, vw, vh = values
            if width < 200 or height < 200 or vw < 200 or x + width > vw + 2 or y + height > vh + 2:
                raise ValueError('训练区域超出主窗口')
            client = w.RECT()
            if not self.user.GetClientRect(hwnd, ctypes.byref(client)):
                raise ValueError('无法读取主窗口尺寸')
            scale = (client.right - client.left) / vw
            self.rect = tuple(round(v * scale) for v in (x, y, width, height))
        self.hwnd, self.visible = hwnd, visible
        self.sync(store)
        return {'embedded': True}

    def environment(self):
        if not self.hwnd or not self.user.IsWindow(self.hwnd) or not self.visible:
            raise ValueError('训练区域尚未就绪，请重新点击开始训练')
        return {'YGO_EMBED_PARENT': str(self.hwnd), 'YGO_EMBED_PARENT_PID': str(self.parent_pid),
                'YGO_EMBED_RECT': ','.join(map(str, self.rect)),
                'YGO_TRAIN_TEST_CONTROL': '1' if self.test_control else '0'}

    def child(self, store, sid):
        proc = store.processes.get(sid)
        if proc is None or proc.poll() is not None:
            return None
        path = store.session_path(sid) / 'native-window.json'
        try:
            value = json.loads(path.read_text('utf8'))
            hwnd = int(value['hwnd'])
        except (OSError, ValueError, KeyError, TypeError): return None
        if self.user.IsWindow(hwnd) and self.pid(hwnd) == proc.pid and self.user.GetParent(hwnd) == self.hwnd:
            return hwnd
        return None

    def sync(self, store):
        for sid in list(store.processes):
            hwnd = self.child(store, sid)
            if not hwnd: continue
            placement = (hwnd, self.rect, self.visible)
            if self.last_placement.get(sid) == placement: continue
            x, y, width, height = self.rect
            if not self.user.SetWindowPos(hwnd, None, x, y, width, height, 0x0010):
                raise ctypes.WinError(ctypes.get_last_error())
            self.user.ShowWindow(hwnd, 4 if self.visible else 0)  # SW_SHOWNOACTIVATE / SW_HIDE
            self.last_placement[sid] = placement

    def status(self, store, sid):
        hwnd = self.child(store, sid)
        if not hwnd: return {'ready': False}
        rect = w.RECT(); self.user.GetWindowRect(hwnd, ctypes.byref(rect))
        origin = w.POINT(rect.left, rect.top)
        self.user.MapWindowPoints(None, self.hwnd, ctypes.byref(origin), 1)
        style = self.user.GetWindowLongPtrW(hwnd, -16)
        center = w.POINT(origin.x + (rect.right - rect.left) // 2, origin.y + (rect.bottom - rect.top) // 2)
        hit = self.user.ChildWindowFromPointEx(self.hwnd, center, 0)
        return {'ready': True, 'pid': self.pid(hwnd), 'hwnd': str(hwnd), 'parent': str(self.hwnd),
                'owns_stage_hit_test': hit == hwnd, 'stage_hit_hwnd': str(hit),
                'child_style': bool(style & 0x40000000), 'caption': bool(style & 0x00C00000),
                'visible': bool(style & 0x10000000), 'bounds': {'x': origin.x, 'y': origin.y,
                'width': rect.right - rect.left, 'height': rect.bottom - rect.top}}

    def close_children(self, store):
        for sid in list(store.processes):
            hwnd = self.child(store, sid)
            if hwnd: self.user.PostMessageW(hwnd, 0x0010, 0, 0)

    def test_event(self, store, body):
        from app import atomic_bytes
        if not self.test_control: raise ValueError('此运行未启用内部验收接口')
        sid, kind = body['id'], body['kind']
        if kind not in ('click', 'capture'): raise ValueError('不支持的内部测试动作')
        status = self.status(store, sid)
        if not status['ready']: raise ValueError('训练场地尚未就绪')
        x, y = body.get('x', 0), body.get('y', 0)
        if type(x) is not int or type(y) is not int or not (0 <= x < status['bounds']['width'] and 0 <= y < status['bounds']['height']):
            raise ValueError('内部测试坐标超出本应用的场地')
        token = uuid.uuid4().hex
        folder = store.session_path(sid)
        atomic_bytes(folder / 'test-command.txt', f'{kind} {token} {x} {y}\n'.encode('ascii'))
        response = folder / f'native-{token}.json'
        for _ in range(100):
            if response.exists():
                try: answer = json.loads(response.read_text('utf8'))
                except (OSError, ValueError):
                    time.sleep(0.05)
                    continue
                if answer.get('error'): raise ValueError(answer['error'])
                return {**answer, 'frame': f'/api/native/frame/{sid}/{token}.png'}
            time.sleep(0.05)
        raise ValueError('内部测试动作等待超时，已保留原始记录')
