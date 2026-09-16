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
from unittest.mock import patch

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
        self.parent_style = u.GetWindowLongPtrW(self.parent, -16)
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

    def test_parent_paint_excludes_native_child_without_changing_window_geometry(self):
        style = self.user.GetWindowLongPtrW(self.parent, -16)
        self.assertTrue(style & 0x02000000, 'The parent must use WS_CLIPCHILDREN to prevent painting over OpenGL')
        self.assertEqual(style, self.parent_style | 0x02000000)
        state = self.host.status(self.store, 'test')
        self.assertTrue(state['parent_clips_children'])
        self.assertTrue(state['composition_compatible'])
        self.assertEqual(tuple(state['bounds'][key] for key in ('x','y','width','height')), self.host.rect)

    def test_shell_style_reset_is_repaired_without_repainting_native_window(self):
        style = self.user.GetWindowLongPtrW(self.parent, -16)
        self.user.SetWindowLongPtrW(self.parent, -16, style & ~0x02000000)
        self.assertFalse(self.host.status(self.store, 'test')['composition_compatible'])
        with patch.object(self.user, 'SetWindowPos', wraps=self.user.SetWindowPos) as move, \
                patch.object(self.user, 'SetWindowRgn', wraps=self.user.SetWindowRgn) as clip, \
                patch.object(self.user, 'ShowWindow', wraps=self.user.ShowWindow) as show:
            self.host.sync(self.store)
            self.assertTrue(self.host.status(self.store, 'test')['parent_clips_children'])
            self.assertTrue(self.host.status(self.store, 'test')['composition_compatible'])
            move.assert_called_once_with(self.parent, None, 0, 0, 0, 0, 0x003f)
            clip.assert_not_called()
            show.assert_not_called()

    def test_parent_from_a_different_process_is_not_modified(self):
        style = self.user.GetWindowLongPtrW(self.parent, -16)
        self.user.SetWindowLongPtrW(self.parent, -16, style & ~0x02000000)
        self.host.parent_pid += 1  # Simulate an HWND whose owning process changed.
        with patch.object(self.user, 'SetWindowLongPtrW', wraps=self.user.SetWindowLongPtrW) as change:
            self.host.protect_parent_paint()
            change.assert_not_called()

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

    def test_timeline_clips_only_native_card_info_and_preserves_field_hit(self):
        self.host.layout({'hwnd':str(self.parent), 'visible':True, 'timeline':True,
                          'x':18, 'y':132, 'width':1164, 'height':750,
                          'viewportWidth':1200, 'viewportHeight':900}, self.store)
        state = self.host.status(self.store, 'test')
        self.assertTrue(state['timeline_accessible'])
        self.assertTrue(state['owns_stage_hit_test'])
        self.assertTrue(state['composition_compatible'])

    def test_repeated_layer_repairs_do_not_reclip_resize_or_show_the_field(self):
        self.host.layout({'hwnd':str(self.parent), 'visible':True, 'timeline':True,
                          'x':18, 'y':132, 'width':1164, 'height':750,
                          'viewportWidth':1200, 'viewportHeight':900}, self.store)
        sibling = self.window(0, 0x56000000, 0, 0, 1200, 900, self.parent)
        position = self.user.SetWindowPos
        with patch.object(self.user, 'SetWindowPos', wraps=position) as move, \
                patch.object(self.user, 'SetWindowRgn', wraps=self.user.SetWindowRgn) as clip, \
                patch.object(self.user, 'ShowWindow', wraps=self.user.ShowWindow) as show:
            for _ in range(8):
                position(sibling, None, 0, 0, 1200, 900, 0x0010)
                self.host.sync(self.store)
                self.assertTrue(self.host.status(self.store, 'test')['owns_stage_hit_test'])
            self.assertEqual(move.call_count, 8)
            self.assertTrue(all(call.args[-1] & 0x000b == 0x000b for call in move.call_args_list),
                            'Z-order repair must not move, resize or invalidate the renderer')
            clip.assert_not_called()
            show.assert_not_called()

    def test_unchanged_hidden_and_visible_layouts_do_not_redraw(self):
        for visible in [False, True]:
            self.host.visible = visible
            self.host.sync(self.store)
            with patch.object(self.user, 'SetWindowPos', wraps=self.user.SetWindowPos) as move, \
                    patch.object(self.user, 'SetWindowRgn', wraps=self.user.SetWindowRgn) as clip, \
                    patch.object(self.user, 'ShowWindow', wraps=self.user.ShowWindow) as show:
                for _ in range(8):
                    self.host.sync(self.store)
                move.assert_not_called()
                clip.assert_not_called()
                show.assert_not_called()

    def test_background_planning_child_never_becomes_a_visible_stage(self):
        self.store.planning = {'test'}
        self.user.ShowWindow(self.native, 0)
        self.host.layout({'hwnd':str(self.parent), 'visible':True, 'timeline':True,
                          'x':24, 'y':140, 'width':1100, 'height':720,
                          'viewportWidth':1200, 'viewportHeight':900}, self.store)
        self.host.sync(self.store)
        self.assertFalse(self.host.status(self.store, 'test')['visible'])
