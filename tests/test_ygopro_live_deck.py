from copy import deepcopy
import struct
import unittest

from test_ygopro_capture import Memory as DeckMemory
from test_ygopro_order import Memory as OrderMemory, PROFILE
from ygopro_capture import read_initial_deck, CaptureError


class LiveMemory(DeckMemory):
    def __init__(self):
        super().__init__()
        self.data.update(OrderMemory(started=1, in_duel=1, lobby=0).memory)
        self.data[self.game+PROFILE['building']] = b'\x00\x00'
        header = list(struct.unpack('<9Q', self.data[self.base+PROFILE['deck']]))
        original = struct.unpack('<3Q', self.data[header[0]])
        self.data[header[0]] = struct.pack('<40Q', *(list(original)*13+[original[0]]))
        header[1] = header[0]+40*8
        self.data[self.base+PROFILE['deck']] = struct.pack('<9Q', *header)
        for zone, count in enumerate((35, 5, 0, 0, 0, 0, 1)):
            address = 0x5000000+zone*0x1000
            self.data[self.game+PROFILE['field_vectors']+48*zone] = struct.pack('<3Q', address, address+count*8, address+60*8)
            self.data[address] = struct.pack('<'+'Q'*count, *range(0x6000000, 0x6000000+count*8, 8))


class LiveDeckTests(unittest.TestCase):
    def test_complete_submitted_deck_is_separate_from_the_remaining_library(self):
        memory = LiveMemory(); value = read_initial_deck(memory, memory.base, PROFILE)
        self.assertEqual(len(value['deck']['main']), 40)
        self.assertEqual(len(value['deck']['extra']), 1)
        self.assertEqual(len(value['deck']['side']), 1)
        self.assertEqual(value['evidence']['own_counts'][:2], [35, 5])

    def test_lobby_late_start_editor_siding_and_server_count_mismatch_are_refused(self):
        for kind in ('lobby', 'late', 'editor', 'siding', 'count', 'played'):
            with self.subTest(kind=kind):
                memory = LiveMemory()
                if kind == 'lobby': memory.data.update(OrderMemory().memory)
                elif kind == 'late': struct.pack_into('<i', memory.data[memory.game+PROFILE['duel_info']], 28, 2)
                elif kind in ('editor', 'siding'):
                    memory.data[memory.game+PROFILE['building']] = b'\x01\x00' if kind == 'editor' else b'\x00\x01'
                else:
                    address = memory.game+PROFILE['field_vectors']+(0 if kind == 'count' else 48*2)
                    a, _, c = struct.unpack('<3Q', memory.data[address]); memory.data[address] = struct.pack('<3Q', a, a+8, c)
                    memory.data[a] = struct.pack('<Q', 0x6000000)
                with self.assertRaises(CaptureError): read_initial_deck(memory, memory.base, PROFILE)

    def test_changing_zone_snapshot_is_rejected(self):
        memory = LiveMemory(); read = memory.read; calls = 0
        target = memory.game+PROFILE['field_vectors']
        def racing(address, size):
            nonlocal calls
            value = read(address, size)
            if address == target:
                calls += 1
                if calls > 1: return b'\x00'*24
            return value
        memory.read = racing
        with self.assertRaisesRegex(CaptureError, '正在变化'): read_initial_deck(memory, memory.base, PROFILE)


if __name__ == '__main__': unittest.main()
