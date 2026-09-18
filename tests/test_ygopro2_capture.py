"""Synthetic Mono memory fixtures; no personal decks or process addresses."""
import struct
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from ygopro_capture import Capture, CaptureError
from ygopro2_capture import Reader, verify_build, IMAGE_HASH, COMPONENTS
import ygopro_opening


class Memory:
    def __init__(self, first=True):
        self.data = bytearray(0x500000)
        self.next = 0x10000
        self.base = 0x100000
        self.domain = self.alloc(256)
        self.put(self.base + 0x2655e0, 'Q', self.domain)
        self.image = self.alloc(1100)
        assembly, node = self.alloc(128), self.alloc(16)
        self.put(assembly + 0x58, 'Q', self.image)
        self.put(node, 'Q', assembly)
        self.put(self.base + 0x265310, 'Q', node)
        self.put(self.image + 0x28, 'Q', self.raw(b'Assembly-CSharp\0' + b'\0' * 96))
        self.slots = self.alloc(17 * 8)
        self.put(self.image + 0x3d0 + 0x18, 'i', 17)
        self.put(self.image + 0x3d0 + 0x20, 'Q', self.slots)
        program_static = self.static(0x020001e9, 'Program')
        self.tcp = self.static(0x020001c5, 'TcpHelper')
        self.program, self.core, self.room = self.alloc(1200), self.alloc(640), self.alloc(224)
        self.put(program_static, 'Q', self.program)
        self.put(self.program + 1136, 'Q', self.core)
        self.put(self.program + 1112, 'Q', self.room)
        self.put(self.core + 128, 'Q', self.alloc(136))
        self.put(self.core + 104, 'B', 1)
        self.put(self.core + 456, 'i', 1)
        self.put(self.core + 582, 'B', int(first))
        self.hand = [1, 2, 2, 3, 4]
        self.deck = {'main': self.hand + list(range(10, 45)), 'extra': [100, 101], 'side': [102]}
        self.deck_obj = self.alloc(80)
        self.put(self.tcp + 40, 'Q', self.deck_obj)
        for offset, zone in ((16, 'main'), (24, 'extra'), (32, 'side')):
            self.put(self.deck_obj + offset, 'Q', self.sequence(self.deck[zone], 'I'))
        player = 0 if first else 1
        sizes = (40, 2, 42, 3) if first else (42, 3, 40, 2)
        start = self.packet(4, struct.pack('<Bii4H', player, 8000, 8000, *sizes))
        self.opposing_draw = self.packet(90, bytes([1 - player, 5]) + bytes(20))
        draw = self.packet(90, bytes([player, 5]) + struct.pack('<5I', *self.hand))
        self.packets = [start, draw, self.opposing_draw]
        self.put(self.core + 232, 'Q', self.sequence(self.packets))
        self.put(self.core + 472, 'i', 2)
        cards = []
        for location, codes in ((1, [0] * 35), (2, self.hand), (64, [0] * 2)):
            for sequence, code in enumerate(codes):
                c = self.alloc(552)
                self.put(c + 280, '4I', 0, location, sequence, 2)
                data = self.alloc(104)
                self.put(c + 40, 'Q', data)
                self.put(data + 72, 'i', code)
                cards.append(c)
        # Opponent ids deliberately point outside valid memory. They must not be read.
        opposing_card = self.alloc(552)
        self.put(opposing_card + 280, '4I', 1, 2, 0, 2)
        self.put(opposing_card + 40, 'Q', 0xffffffffffffffff)
        cards.append(opposing_card)
        self.card_list = self.sequence(cards)
        self.put(self.core + 144, 'Q', self.card_list)

    def alloc(self, size):
        address = self.next
        self.next += (size + 7) // 8 * 8
        return address

    def raw(self, data):
        address = self.alloc(len(data))
        self.data[address:address + len(data)] = data
        return address

    def put(self, address, fmt, *values):
        struct.pack_into('<' + fmt, self.data, address, *values)

    def read(self, address, size):
        if not 0x10000 <= address <= len(self.data) - size: raise CaptureError('invalid fixture address')
        return bytes(self.data[address:address + size])

    def static(self, token, name):
        klass = self.alloc(272)
        self.put(klass + 0x40, 'Q', self.image)
        self.put(klass + 0x48, 'Q', self.raw(name.encode() + bytes(96)))
        self.put(klass + 0x58, 'i', token)
        self.put(self.slots + 8 * (token % 17), 'Q', klass)
        runtime, vtable, data = self.alloc(24), self.alloc(40), self.alloc(96)
        self.put(klass + 0xf8, 'Q', runtime)
        self.put(runtime + 8, 'Q', vtable)
        self.put(vtable, 'Q', klass)
        self.put(vtable + 0x18, 'Q', data)
        return data

    def sequence(self, values, fmt='Q'):
        obj, array = self.alloc(32), self.alloc(32 + len(values) * struct.calcsize(fmt))
        self.put(obj + 16, 'Qii', array, len(values), 1)
        self.put(array + 24, 'Q', len(values))
        self.put(array + 32, fmt * len(values), *values)
        return obj

    def packet(self, kind, raw):
        package, master, stream, array = self.alloc(32), self.alloc(40), self.alloc(64), self.alloc(32 + len(raw))
        self.put(package + 16, 'Qi', master, kind)
        self.put(master + 16, 'Q', stream)
        self.put(stream + 32, 'i', len(raw))
        self.put(stream + 40, 'Q', array)
        self.put(array + 24, 'Q', len(raw))
        self.data[array + 32:array + 32 + len(raw)] = raw
        return package

    def sample(self, **kwargs):
        return Reader(self, self.base).sample(**kwargs)


class ReaderTests(unittest.TestCase):
    def test_real_structure_first_and_second_with_duplicates_and_no_opponent_ids(self):
        for first in (True, False):
            memory = Memory(first)
            value = memory.sample()
            self.assertEqual(value['construction']['deck'], memory.deck)
            self.assertEqual(value['construction']['evidence']['own_counts'], [35, 5, 0, 0, 0, 0, 2])
            self.assertEqual(value['frame']['opening_sample']['draw'], memory.hand)
            self.assertEqual(value['frame']['opening_sample']['hand'], memory.hand)
            opening = ygopro_opening.create(True)
            ygopro_opening.observe(opening, value['frame']['opening_sample'], value['frame'], lambda: 1)
            self.assertEqual(opening['cards'], memory.hand)
            memory.put(memory.core + 536, 'i', 1)
            frame = memory.sample(with_deck=False, with_opening=False)['frame']
            self.assertEqual(frame['detected_order'], 'first' if first else 'second')
            self.assertEqual(Reader(memory, memory.base).submitted_deck(), memory.deck)

    def test_lobby_and_unprocessed_start_never_use_stale_fields(self):
        memory = Memory()
        memory.put(memory.room + 104, 'B', 1)
        memory.put(memory.core + 536, 'i', 7)
        value = memory.sample()
        self.assertEqual(value['frame']['phase'], 'waiting_start')
        self.assertEqual(value['frame']['evidence']['turn'], 0)
        self.assertNotIn('construction', value)
        memory.put(memory.room + 104, 'B', 0)
        memory.put(memory.core + 472, 'i', -1)
        self.assertNotIn('construction', memory.sample())

    def test_watch_replay_tag_side_and_swapped_are_rejected(self):
        for target, offset, fmt, value in (('room', 197, 'B', 2), ('room', 190, 'B', 1),
                                          ('room', 212, 'i', 7), ('core', 456, 'i', 3), ('core', 583, 'B', 1)):
            memory = Memory()
            memory.put(getattr(memory, target) + offset, fmt, value)
            self.assertEqual(memory.sample()['frame']['phase'], 'unsupported')
        memory = Memory()
        info = struct.unpack('<Q', memory.read(memory.core + 128, 8))[0]
        memory.put(info + 128, 'B', 1)
        self.assertEqual(memory.sample()['frame']['phase'], 'unsupported')

    def test_server_counts_and_early_window_gate_construction(self):
        memory = Memory()
        memory.put(memory.deck_obj + 24, 'Q', memory.sequence([100], 'I'))
        self.assertIn('deck_error', memory.sample())
        memory = Memory()
        memory.put(memory.core + 536, 'i', 2)
        self.assertIn('deck_error', memory.sample())

    def test_mutated_snapshots_and_excess_counts_fail_closed(self):
        memory = Memory()
        memory.put(memory.card_list + 24, 'i', 513)
        with self.assertRaises(CaptureError): memory.sample()
        memory = Memory()
        reader = Reader(memory, memory.base)
        memory.put(memory.program + 1136, 'Q', memory.core + 8)
        with self.assertRaises(CaptureError): reader.sample()

    def test_missing_initial_draw_and_late_attach_do_not_guess_hand(self):
        memory = Memory()
        memory.put(memory.packets[1] + 24, 'i', 40)
        value = memory.sample()
        self.assertIsNone(value['frame']['opening_sample']['draw'])
        opening = ygopro_opening.create(False)
        ygopro_opening.observe(opening, value['frame']['opening_sample'], value['frame'], lambda: 1)
        self.assertEqual(opening['status'], 'missed')
        self.assertEqual(opening['cards'], [])

    def test_editor_is_not_exposed_and_process_restart_invalidates_capture(self):
        capture = Capture()
        with patch('ygopro_capture.processes', return_value=[{'pid': 123, 'supported': True, 'path': 'fixture', 'created': 1}]):
            attached = capture.attach(platform='ygopro2')['process']
        with self.assertRaisesRegex(CaptureError, '尚未开放'): capture.deck(attached['capture_id'])
        with patch('ygopro_capture.WindowsProcess') as factory:
            factory.return_value.__enter__.return_value.identity.return_value = ('fixture', 2)
            with self.assertRaisesRegex(CaptureError, '身份已变化'): capture.live_sample(attached['capture_id'])
        with self.assertRaises(CaptureError): capture.attach(platform='unknown')

    def test_all_managed_and_runtime_fingerprints_are_required(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'YGOPro2.exe'
            self.assertFalse(verify_build(image, IMAGE_HASH)['supported'])
            self.assertFalse(verify_build(image, 'other')['supported'])
            for relative in COMPONENTS:
                path = image.parent / 'YGOPro2_Data' / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'unknown build')
            self.assertFalse(verify_build(image, IMAGE_HASH)['supported'])


if __name__ == '__main__': unittest.main()
