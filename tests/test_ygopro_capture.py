import copy
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from ygopro_capture import Capture, CaptureError, PROFILES, WindowsProcess, read_deck


class Memory:
    base = 0x1000000
    game = 0x2000000
    profile = next(iter(PROFILES.values()))

    def __init__(self):
        self.data = {}; self.changing = False
        self.data[self.base + self.profile['game']] = struct.pack('<Q', self.game)
        self.data[self.game + self.profile['building']] = b'\x01\x00'
        self.data[self.game + self.profile['dragging']] = b'\x00\x00'
        pointers = []
        for i, codes in enumerate(((123, 123, 456), (789,), (456,))):
            start = 0x3000000 + i * 0x1000
            pointers.extend((start, start + len(codes) * 8, start + 64 * 8))
            addresses = []
            for j, code in enumerate(codes):
                address = 0x4000000 + i * 0x1000 + j * 0x100
                addresses.append(address)
                raw = bytearray(self.profile['card_type'] + 4)
                struct.pack_into('<I', raw, 0, code)
                struct.pack_into('<I', raw, self.profile['card_type'], 0x41 if i == 1 else 2)
                self.data[address] = bytes(raw)
            self.data[start] = struct.pack('<' + 'Q' * len(addresses), *addresses)
        self.data[self.base + self.profile['deck']] = struct.pack('<9Q', *pointers)

    def read(self, address, size):
        if not size: return b''
        value = self.data[address]
        if self.changing and address == 0x3000000:
            self.data[address] = value[8:16] + value[16:24] + value[:8]
        return value[:size]


class CaptureTests(unittest.TestCase):
    def test_default_module_lookup_keeps_existing_ygopro_recognition_working(self):
        class Call:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*a):return self.fn(*a)
        closed=[]
        def first(_,ref):
            ref._obj.name='YGOPro.exe';ref._obj.base=0x140000000;return True
        reader=WindowsProcess.__new__(WindowsProcess)
        reader.kernel=SimpleNamespace(CreateToolhelp32Snapshot=Call(lambda *a:1),Module32FirstW=Call(first),
            Module32NextW=Call(lambda *a:False),CloseHandle=Call(lambda h:closed.append(h)))
        self.assertEqual(reader.image_base(123),0x140000000);self.assertEqual(closed,[1])

    def test_read_live_vectors_and_unsaved_changes(self):
        memory = Memory()
        self.assertEqual(read_deck(memory, memory.base, memory.profile), {'main':[123,123,456], 'extra':[789], 'side':[456]})
        address = 0x4000000
        memory.data[address] = struct.pack('<I', 999) + memory.data[address][4:]
        self.assertEqual(read_deck(memory, memory.base, memory.profile)['main'], [999,123,456])

    def test_reject_lobby_siding_overflow_invalid_type_and_races(self):
        for flags in (b'\0\0', b'\1\1'):
            memory = Memory(); memory.data[memory.game + memory.profile['building']] = flags
            with self.assertRaisesRegex(CaptureError, '编辑卡组'):read_deck(memory,memory.base,memory.profile)
        memory = Memory(); address = memory.base + memory.profile['deck']
        values = list(struct.unpack('<9Q',memory.data[address])); values[1] = values[0] + 61 * 8
        memory.data[address] = struct.pack('<9Q', *values)
        with self.assertRaisesRegex(CaptureError, '数量超限'):read_deck(memory,memory.base,memory.profile)
        memory = Memory(); memory.data[0x4000000] = memory.data[0x4001000]
        with self.assertRaisesRegex(CaptureError, '分区'):read_deck(memory,memory.base,memory.profile)
        memory = Memory(); memory.changing=True
        with self.assertRaisesRegex(CaptureError, '发生变化'):read_deck(memory,memory.base,memory.profile)
        memory = Memory(); memory.data[memory.game + memory.profile['dragging']] = b'\1\0'
        with self.assertRaisesRegex(CaptureError, '拖动'):read_deck(memory,memory.base,memory.profile)

    def test_attach_requires_one_supported_process_and_invalidates_old_capture(self):
        process = {'pid':123, 'supported':True, 'image_hash':next(iter(PROFILES)), 'path':'test', 'created':1}
        capture = Capture()
        with patch('ygopro_capture.processes',return_value=[process]):
            result = capture.attach(); self.assertTrue(result['connected'])
        with patch('ygopro_capture.processes',return_value=[]):
            self.assertFalse(capture.attach()['connected']);self.assertIsNone(capture.attached)
        with self.assertRaises(CaptureError):capture.deck(result['process']['capture_id'])
        with patch('ygopro_capture.processes',return_value=[process,{**process,'pid':124}]):
            self.assertFalse(capture.attach()['connected']);self.assertTrue(capture.attach(124)['connected'])
        with patch('ygopro_capture.processes',return_value=[{**process,'supported':False}]):
            self.assertIn('未适配',capture.attach()['error'])

    def test_restart_and_unstable_deck_never_return_a_stale_snapshot(self):
        attached={'pid':123,'path':'test','created':1,'image_hash':next(iter(PROFILES)),'capture_id':'test'}
        capture=Capture();capture.attached=copy.deepcopy(attached)
        with patch('ygopro_capture.WindowsProcess') as factory:
            memory=factory.return_value.__enter__.return_value;memory.identity.return_value=('test',2)
            with self.assertRaisesRegex(CaptureError,'重新启动'):capture.deck('test')
            self.assertIsNone(capture.attached)
        capture.attached=attached
        with patch('ygopro_capture.WindowsProcess') as factory, patch('ygopro_capture.read_deck',side_effect=[{'main':[i]} for i in range(4)]), patch('ygopro_capture.time.sleep'):
            factory.return_value.__enter__.return_value.identity.return_value=('test',1)
            with self.assertRaisesRegex(CaptureError,'持续变化'):capture.deck('test')

    def test_submitted_deck_requires_same_process_and_stable_started_duel(self):
        capture=Capture();capture.attached={'pid':123,'path':'test','created':1,'image_hash':next(iter(PROFILES)),'capture_id':'test'}
        memory=Memory();state={'phase':'detected','detected_order':'first','evidence':{'turn':1}}
        with patch('ygopro_capture.WindowsProcess') as factory,patch('ygopro_capture.read_order',return_value=state) as order:
            process=factory.return_value.__enter__.return_value;process.identity.return_value=('test',1)
            process.image_base.return_value=memory.base;process.read.side_effect=memory.read
            self.assertEqual(capture.submitted_deck('test'),{'main':[123,123,456],'extra':[789],'side':[456]})
            order.return_value={'phase':'waiting_start'}
            with self.assertRaisesRegex(CaptureError,'尚未进入'):capture.submitted_deck('test')
            order.side_effect=[state,{**state,'evidence':{'turn':2}}]
            with self.assertRaisesRegex(CaptureError,'状态正在变化'):capture.submitted_deck('test')
            process.identity.return_value=('test',2)
            with self.assertRaisesRegex(CaptureError,'进程已变化'):capture.submitted_deck('test')

    def test_connection_liveness_uses_exit_status_and_process_creation_identity(self):
        capture=Capture();capture.attached={'pid':123,'path':'test','created':1,'capture_id':'test'}
        with patch('ygopro_capture.WindowsProcess') as factory:
            process=factory.return_value.__enter__.return_value
            process.alive.return_value=True;process.identity.return_value=('test',1)
            self.assertTrue(capture.connection_alive('test'))
            process.identity.return_value=('test',2)
            self.assertFalse(capture.connection_alive('test'))
            process.identity.return_value=('test',1);process.alive.return_value=False
            self.assertFalse(capture.connection_alive('test'))
        self.assertFalse(capture.connection_alive('other-connection'))

    @unittest.skipUnless(os.name=='nt', 'Windows process identity API')
    def test_real_owned_process_exit_is_detected_without_writing_process_memory(self):
        child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with WindowsProcess(child.pid) as reader:path,created=reader.identity()
            capture=Capture();capture.attached={'pid':child.pid,'path':path,'created':created,'capture_id':'owned-test'}
            self.assertTrue(capture.connection_alive('owned-test'))
            child.terminate();child.wait(timeout=5)
            self.assertFalse(capture.connection_alive('owned-test'))
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=5)


if __name__ == '__main__':unittest.main()
