"""Synthetic IL2CPP structures; no personal client captures or card lists."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from mdpro3_capture import CLASSES, COMPONENTS, IMAGE_HASH, Reader, verify_build
from ygopro_capture import Capture, CaptureError
import ygopro_opening


class Memory:
    def __init__(self, first=True):
        self.data, self.next, self.base = {}, 0x10000, 0x100000
        self.payloads = {}
        self.statics, self.classes = {}, {}
        for name, (rva, namespace) in CLASSES.items():
            klass, static = self.alloc(0x140), self.alloc(0x300)
            self.put(self.base + rva, 'Q', klass)
            self.put(klass + 16, 'QQ', self.raw(name.encode() + bytes(96)), self.raw(namespace.encode() + bytes(96)))
            self.put(klass + 0xb8, 'Q', static)
            self.statics[name], self.classes[name] = static, klass
        self.core, self.room, program = self.alloc(0x100), self.alloc(0x60), self.alloc(0x128)
        self.cs, self.rs, self.tcp = (self.statics[n] for n in ('OcgCore', 'RoomServant', 'TcpHelper'))
        self.put(self.statics['Program'] + 8, 'Q', program)
        self.put(program + 0xc8, 'QQ', self.core, self.room)
        self.put(self.core + 0x30, 'B', 1)
        self.put(self.cs + 0x7c, 'i', 1)
        self.put(self.cs + 0x10, 'B', int(first))
        player = 0 if first else 1
        self.put(self.cs + 0xc, 'i', player)
        self.hand = [1, 2, 2, 3, 4]
        self.deck = {'main': self.hand + list(range(10, 45)), 'extra': [100, 101], 'side': [102]}
        self.deck_obj = self.alloc(0x60)
        self.put(self.tcp + 0x28, 'Q', self.deck_obj)
        for offset, zone in ((16, 'main'), (24, 'extra'), (32, 'side')):
            self.put(self.deck_obj + offset, 'Q', self.sequence(self.deck[zone], 'I'))
        sizes = (40, 2, 42, 3) if first else (42, 3, 40, 2)
        self.start = self.packet(4, struct.pack('<Bii4H', player, 8000, 8000, *sizes))
        draw = self.packet(90, bytes([player, 5]) + struct.pack('<5I', *self.hand))
        self.opponent_draw = self.packet(90, bytes([1-player, 5]) + bytes(20))
        self.packets = [self.start, draw, self.opponent_draw]
        self.set_packets(2)
        cards = []
        self.hand_objects = []
        for location, codes in ((1, [0]*35), (2, self.hand), (64, [0]*2)):
            for seq, code in enumerate(codes):
                card, gps, data = self.alloc(0x140), self.alloc(0x28), self.alloc(0x80)
                self.put(card + 0x30, 'Q', gps)
                self.put(gps + 16, '4I', 0, location, seq, 2)
                self.put(card + 0x20, 'Q', data)
                self.put(data + 16, 'i', code)
                cards.append(card)
                if location == 2: self.hand_objects.append(card)
        # The opponent's card data pointer cannot be dereferenced.
        card, gps = self.alloc(0x140), self.alloc(0x28)
        self.put(card + 0x30, 'Q', gps)
        self.put(gps + 16, '4I', 1, 2, 0, 2)
        self.put(card + 0x20, 'Q', 0xffffffffffffffff)
        self.card_list = self.sequence(cards + [card])
        self.put(self.cs + 0xe0, 'Q', self.card_list)
        self.reads = []

    def alloc(self, size):
        address = self.next
        self.next += (size + 7) // 8 * 8
        return address

    def raw(self, data):
        address = self.alloc(len(data))
        self.write(address, data)
        return address

    def write(self, address, data):
        self.data.update({address + i: b for i, b in enumerate(data)})

    def put(self, address, fmt, *values):
        self.write(address, struct.pack('<' + fmt, *values))

    def read(self, address, size):
        if not 0x10000 <= address < 0x10000000: raise CaptureError('invalid fixture address')
        self.reads.append((address, size))
        return bytes(self.data.get(address+i, 0) for i in range(size))

    def sequence(self, values, fmt='Q'):
        obj, array = self.alloc(32), self.alloc(32 + len(values) * struct.calcsize(fmt))
        self.put(obj + 16, 'Qii', array, len(values), 1)
        self.put(array + 24, 'Q', len(values))
        self.put(array + 32, fmt*len(values), *values)
        return obj

    def packet(self, kind, raw):
        package, master, stream, array = self.alloc(32), self.alloc(40), self.alloc(80), self.alloc(32 + len(raw))
        self.put(package + 16, 'Qi', master, kind)
        self.put(master + 16, 'Q', stream)
        self.put(stream + 0x28, 'Q', array)
        self.put(stream + 0x38, 'i', len(raw))
        self.put(array + 24, 'Q', len(raw))
        self.write(array + 32, raw)
        self.payloads[package] = array + 32
        return package

    def set_packets(self, processed):
        self.put(self.cs + 0x198, 'Q', self.sequence(self.packets))
        self.pending_list = self.sequence(self.packets[processed:])
        self.put(self.cs + 0x190, 'Q', self.pending_list)

    def sample(self, **kwargs):
        return Reader(self, self.base).sample(**kwargs)


class ReaderTests(unittest.TestCase):
    def test_first_and_second_order_duplicate_hand_and_no_opponent_ids(self):
        for first in (True, False):
            m = Memory(first)
            value = m.sample()
            self.assertEqual(value['construction']['deck'], m.deck)
            self.assertEqual(value['construction']['evidence']['own_counts'], [35,5,0,0,0,0,2])
            self.assertEqual(value['frame']['opening_sample']['draw'], m.hand)
            opening = ygopro_opening.create(True)
            ygopro_opening.observe(opening, value['frame']['opening_sample'], value['frame'], lambda: 1)
            self.assertEqual(opening['cards'], m.hand)
            opposing = m.payloads[m.opponent_draw]
            self.assertFalse(any(a < opposing + 22 and a + size > opposing + 2 for a, size in m.reads))
            m.put(m.cs + 0x28, 'i', 1)
            frame = m.sample(with_deck=False, with_opening=False)['frame']
            self.assertEqual(frame['detected_order'], 'first' if first else 'second')
            self.assertEqual(Reader(m, m.base).submitted_deck(), m.deck)

    def test_lobby_preloaded_start_and_reconnect_do_not_reuse_old_duel(self):
        for setup in ('lobby', 'preload', 'reconnect'):
            m = Memory()
            if setup == 'lobby': m.put(m.room + 0x30, 'B', 1)
            if setup == 'preload': m.set_packets(0)
            if setup == 'reconnect': m.put(m.rs + 0x1a, 'B', 1)
            value = m.sample()
            self.assertNotIn('construction', value)
            self.assertFalse(value['frame']['evidence']['in_duel'])
            self.assertIsNone(value['frame']['evidence']['duel_token'])

    def test_unsupported_modes_and_ended(self):
        for target, offset, fmt, value in (('rs', 5, 'B', 1), ('rs', 5, 'B', 2), ('rs', 0x14, 'i', 7),
                ('rs', 0x19, 'B', 1), ('rs', 0x1b, 'B', 1), ('cs', 0x7c, 'i', 3),
                ('cs', 0x11, 'B', 1), ('cs', 8, 'B', 1), ('cs', 9, 'B', 1)):
            m = Memory(); m.put(getattr(m, target) + offset, fmt, value)
            self.assertEqual(m.sample()['frame']['phase'], 'unsupported')
        m = Memory(); m.put(m.cs + 0x70, 'B', 1)
        self.assertEqual(m.sample()['frame']['phase'], 'ended')

    def test_partial_animation_waits_for_all_copies_and_late_attach_does_not_guess(self):
        m = Memory(); m.set_packets(1)
        card = m.hand_objects[-1]
        gps = struct.unpack('<Q', m.read(card + 0x30, 8))[0]
        m.put(gps + 20, 'I', 1)
        sample = m.sample(); opening = ygopro_opening.create(True)
        ygopro_opening.observe(opening, sample['frame']['opening_sample'], sample['frame'], lambda: 1)
        self.assertNotEqual(opening['status'], 'ready')
        m.put(gps + 20, 'I', 2)
        sample = m.sample()
        ygopro_opening.observe(opening, sample['frame']['opening_sample'], sample['frame'], lambda: 2)
        self.assertEqual(opening['cards'], m.hand)
        m.put(m.cs + 0x28, 'i', 1)
        sample = m.sample()
        self.assertIsNone(sample['frame']['opening_sample']['draw'])
        late = ygopro_opening.create(False)
        ygopro_opening.observe(late, sample['frame']['opening_sample'], sample['frame'], lambda: 3)
        self.assertEqual(late['status'], 'missed')

    def test_server_counts_and_window_must_match(self):
        m = Memory(); m.put(m.deck_obj + 24, 'Q', m.sequence([100], 'I'))
        self.assertIn('deck_error', m.sample())
        m = Memory(); m.put(m.cs + 0x28, 'i', 2)
        self.assertIn('deck_error', m.sample())

    def test_mutation_layout_queue_and_lengths_fail_closed(self):
        m = Memory(); r = Reader(m, m.base)
        m.put(m.classes['Program'] + 0xb8, 'Q', m.statics['Program'] + 8)
        with self.assertRaises(CaptureError): r.sample()
        m = Memory(); m.put(m.classes['Program'] + 16, 'Q', m.raw(b'Wrong' + bytes(96)))
        with self.assertRaises(CaptureError): m.sample()
        m = Memory(); m.put(m.cs + 0x190, 'Q', m.sequence([m.start]))
        with self.assertRaises(CaptureError): m.sample()
        m = Memory(); m.put(m.card_list + 24, 'i', 513)
        with self.assertRaises(CaptureError): m.sample()
        m = Memory(); m.put(m.cs + 0x10, 'B', 0)
        with self.assertRaises(CaptureError): m.sample()

    def test_attach_dispatch_editor_rejection_and_restart(self):
        c = Capture()
        with patch('ygopro_capture.processes', return_value=[{'pid':123,'supported':True,'path':'fixture','created':1}]):
            a = c.attach(platform='mdpro3')['process']
        with self.assertRaisesRegex(CaptureError, 'MDPRO3'): c.deck(a['capture_id'])
        with patch('ygopro_capture.WindowsProcess') as process, patch('mdpro3_capture.Reader') as reader:
            memory = process.return_value.__enter__.return_value
            memory.identity.return_value = ('fixture',1)
            reader.return_value.sample.return_value = {'frame':{}}
            self.assertEqual(c.live_sample(a['capture_id'])['capture_id'],a['capture_id'])
            memory.image_base.assert_called_with(123,'GameAssembly.dll')
            memory.identity.return_value = ('fixture',2)
            with self.assertRaises(CaptureError): c.live_sample(a['capture_id'])

    def test_fingerprint_requires_every_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary)/'MDPro3.exe'
            self.assertFalse(verify_build(image, 'bad')['supported'])
            self.assertFalse(verify_build(image, IMAGE_HASH)['supported'])
            hashes = {}
            for relative in COMPONENTS:
                p = image.parent/relative; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'fixture')
                hashes[relative] = hashlib.sha256(b'fixture').hexdigest()
            with patch('mdpro3_capture.COMPONENTS',hashes):
                self.assertTrue(verify_build(image, IMAGE_HASH)['supported'])
                p.write_bytes(b'changed')
                self.assertFalse(verify_build(image, IMAGE_HASH)['supported'])
