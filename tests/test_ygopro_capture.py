import copy
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from ygopro_capture import Capture, CaptureError, PROFILES, read_deck


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


if __name__ == '__main__':unittest.main()
