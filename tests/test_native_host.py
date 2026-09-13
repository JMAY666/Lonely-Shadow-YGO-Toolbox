"""Exercise HWND composition using only hidden, test-owned windows."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from desktop_host import NativeHost


@unittest.skipUnless(sys.platform == 'win32', 'Native hosting requires Windows')
class NativeCompositionTests(unittest.TestCase):
    def setUp(self):
        self.host = NativeHost(os.getpid())
        self.user = u = self.host.user
        u.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
        u.CreateWindowExW.restype = w.HWND
        u.DestroyWindow.argtypes = [w.HWND]
        # No WS_VISIBLE on the parent: no desktop window or global input.
        self.parent = self.window(0, 0, 0, 0, 1200, 900)
        self.addCleanup(u.DestroyWindow, self.parent)
        self.native = self.window(0, 0x56000000, 0, 0, 600, 500, self.parent)
        root = Path(__file__).resolve().parents[1] / '.local/test-runs'
        root.mkdir(parents=True, exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name)
        (folder / 'native-window.json').write_text(json.dumps({'hwnd': str(self.native)}), 'utf8')
        (folder / 'frame-ready.json').write_text('{"time_ms":1}', 'utf8')
        self.store = SimpleNamespace(
            processes={'test': SimpleNamespace(pid=os.getpid(), poll=lambda: None)},
            session_path=lambda sid: folder,
        )
        self.host.layout({'hwnd': str(self.parent), 'visible': True,
                          'x': 18, 'y': 132, 'width': 1164, 'height': 750,
                          'viewportWidth': 1200, 'viewportHeight': 900}, self.store)

    def window(self, extended, style, x, y, width, height, parent=None):
        hwnd = self.user.CreateWindowExW(extended, 'STATIC', '', style, x, y, width, height,
                                        parent, None, None, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        return hwnd

    def test_layered_surface_is_detected_even_when_native_owns_input(self):
        # Chromium's old Intermediate D3D Window is visible, disabled, layered,
        # and transparent to input. A successful hit test alone is insufficient.
        overlay = self.window(0x80020, 0x58000000, 0, 0, 1200, 900, self.parent)
        self.host.sync(self.store)
        state = self.host.status(self.store, 'test')
        self.assertTrue(state['frame_ready'])
        self.assertTrue(state['owns_stage_hit_test'])
        self.assertFalse(state['composition_compatible'])
        self.assertEqual(state['layered_overlaps'], [str(overlay)])
        self.user.ShowWindow(overlay, 0)
        self.assertTrue(self.host.status(self.store, 'test')['composition_compatible'])

    def test_layered_window_outside_stage_does_not_block_readiness(self):
        self.window(0x80020, 0x58000000, 0, 0, 1200, 100, self.parent)
        state = self.host.status(self.store, 'test')
        self.assertTrue(state['composition_compatible'])
        self.assertEqual(state['layered_overlaps'], [])

    def test_sync_repairs_sibling_order_without_a_layout_change(self):
        sibling = self.window(0, 0x56000000, 0, 0, 1200, 900, self.parent)
        self.user.SetWindowPos(sibling, None, 0, 0, 1200, 900, 0x0010)
        self.assertFalse(self.host.status(self.store, 'test')['owns_stage_hit_test'])
        self.host.sync(self.store)
        state = self.host.status(self.store, 'test')
        self.assertTrue(state['owns_stage_hit_test'])
        self.assertTrue(state['composition_compatible'])
        self.host.layout({'hwnd': str(self.parent), 'visible': False}, self.store)
        self.host.sync(self.store)
        self.assertFalse(self.host.status(self.store, 'test')['visible'])
