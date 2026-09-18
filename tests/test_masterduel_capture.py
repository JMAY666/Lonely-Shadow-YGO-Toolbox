"""Synthetic IL2CPP data only; real solo rounds are documented separately."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from masterduel_capture import CLASSES, COMPONENTS, IMAGE_HASH, Reader, card_ids, verify_build
from ygopro_capture import Capture, CaptureError
import ygopro_opening


class Memory:
    def __init__(self, *, mine=0, first=0, online=False):
        self.data, self.next, self.base, self.reads = {}, 0x10000, 0x100000, []
        self.statics, self.classes = {}, {}
        for name, rva in CLASSES.items():
            klass = self.klass(name, 'YgomGame.Duel'); static = self.alloc(0x80)
            self.put(self.base + rva, 'Q', klass); self.put(klass + 0xb8, 'Q', static)
            self.statics[name], self.classes[name] = static, klass
        self.client, self.engine = self.alloc(0x240), self.alloc(0x140)
        self.put(self.statics['DuelClient'], 'Q', self.client)
        self.put(self.statics['Engine'] + 8, 'Q', self.engine)
        self.put(self.client + 0x1c4, 'i', 16); self.put(self.client + 0x1f8, 'B', 1)
        self.init = self.alloc(0x40); self.put(self.init, 'Q', self.klass('EngineInitializerByServer'))
        self.put(self.client + 0xc0, 'Q', self.init)
        settings = {'MyID':mine, 'MyType':0, 'FirstPlayer':first, 'GameMode':3 if online else 9,
                    'Type':0, 'tag':False, 'is_pvp':online}
        self.settings = {}
        values = []
        for key, value in settings.items():
            boxed = self.alloc(24); self.settings[key] = boxed
            self.put(boxed, 'Q', self.klass('Boolean' if isinstance(value, bool) else 'Int64'))
            self.put(boxed + 16, 'q', value)
            values.append((self.string(key), boxed))
        values.append((self.string('unrelated_account_value'), 0xfffffffffffffff0))
        entries = self.alloc(32 + 24 * len(values)); self.put(entries + 24, 'Q', len(values))
        for i, (key, value) in enumerate(values): self.put(entries + 32 + 24*i, 'iiQQ', i, -1, key, value)
        dictionary = self.alloc(64); self.put(dictionary, 'Q', self.klass('Dictionary`2'))
        self.put(dictionary + 24, 'Qii', entries, len(values), 1); self.put(self.init + 0x28, 'Q', dictionary)
        cached = self.alloc(40); self.put(self.engine + 16, 'Q', cached); self.put(cached + 16, 'i', mine)
        self.put(self.engine + 0xc9, 'B', online); self.put(self.engine + 0xcc, 'i', settings['GameMode'])
        self.hand_codes = [1, 2, 2, 3, 4]
        self.deck = {'main': self.hand_codes + list(range(10,45)), 'extra': [100,101], 'side': []}
        zones = self.array([self.array(cards, 'i') for cards in self.deck.values()])
        players = [0xfffffffffffffff0]*2; players[mine] = zones
        self.put(self.init + 16, 'Q', self.array(players))
        manager = self.alloc(64); self.put(self.client + 0xd0, 'Q', manager)
        self.put(manager + 0x30, 'B', 1)
        hand = []
        for i, code in enumerate(self.hand_codes):
            item = self.alloc(40); self.put(item + 16, 'ii', code, 10+i); self.put(item + 0x20, 'i', i); hand.append(item)
        self.hand_items = hand
        self.hand_list = self.sequence(hand)
        self.put(manager + 16, 'QQ', self.hand_list, 0xfffffffffffffff0)
        work, data = self.alloc(0x90), self.alloc(0x30)
        self.info = self.alloc(0x80); self.work = work
        self.put(self.engine + (0x118 if online else 0x128), 'Q', work)
        self.put(work + (0x18 if online else 16), 'Q', data); self.put(data + 16, 'Q', self.info)
        self.turn_offset, self.phase_offset = (0x14,0x18) if online else (0x10,0x14)
        self.effect_offset = 0x60 if online else 0x68
        self.put(self.info + self.phase_offset, 'i', 7)
        self.put(self.info + (0x24 if online else 0x18), 'B' if online else 'i', first)
        self.put(work + self.effect_offset, 'i', 1)
        cells = [0xfffffffffffffff0]*38; self.cells = []
        for pos in range(19):
            cell = self.alloc(0x80); self.cells.append(cell); cells[mine*19+pos] = cell
            self.put(cell + (0x28 if online else 0x54), 'H' if online else 'i', {13:5,14:2,15:35}.get(pos,0))
        self.matrix = self.array(cells); bounds = self.alloc(32)
        self.put(bounds, 'Qi4xQi4x', 2, 0, 19, 0); self.put(self.matrix + 16, 'Q', bounds)
        self.put(self.info + (0x50 if online else 0x20), 'Q', self.matrix)

    def alloc(self, size):
        address = self.next; self.next += (size+7)//8*8
        return address

    def put(self, address, fmt, *values):
        raw = struct.pack('<'+fmt, *values)
        self.data.update({address+i:b for i,b in enumerate(raw)})

    def read(self, address, size):
        if not 0x10000 <= address < 0x10000000: raise CaptureError('forbidden fixture address')
        self.reads.append((address,size))
        return bytes(self.data.get(address+i,0) for i in range(size))

    def klass(self, name, namespace=''):
        klass = self.alloc(0x140)
        for offset, text in ((16,name),(24,namespace)):
            value = self.alloc(96); self.put(value, '96s', text.encode()); self.put(klass+offset,'Q',value)
        return klass

    def string(self, text):
        obj=self.alloc(20+2*len(text)); self.put(obj+16,'i',len(text)); self.put(obj+20,str(2*len(text))+'s',text.encode('utf-16-le'))
        return obj

    def array(self, values, fmt='Q'):
        obj=self.alloc(32+len(values)*struct.calcsize(fmt)); self.put(obj+24,'Q',len(values)); self.put(obj+32,fmt*len(values),*values)
        return obj

    def sequence(self, values):
        obj=self.alloc(32); self.put(obj+16,'Qii',self.array(values),len(values),1)
        return obj

    def sample(self, **kwargs):
        with patch('masterduel_capture.card_ids', return_value={i:i for i in range(1,200)}):
            return Reader(self,self.base).sample(**kwargs)


class MasterDuelTests(unittest.TestCase):
    def test_solo_and_pvp_own_player_mapping_and_initial_deal(self):
        for online in (False,True):
            for mine in (0,1):
                for first in (0,1):
                    with self.subTest(online=online,mine=mine,first=first):
                        m=Memory(mine=mine,first=first,online=online); value=m.sample(); frame=value['frame']
                        self.assertEqual(value['construction']['deck'],m.deck)
                        self.assertEqual(frame['opening_sample']['draw'],m.hand_codes)
                        self.assertEqual(frame['evidence']['is_first'],mine==first)
                        self.assertFalse(frame['evidence']['rps_visible'])
                        self.assertEqual(frame['evidence']['selection_mechanism'],'coin_toss')
                        m.put(m.info+m.phase_offset,'i',2)
                        self.assertEqual(m.sample(with_deck=False)['frame']['detected_order'],'first' if mine==first else 'second')

    def test_freeze_five_cards_and_never_replace_with_later_draw(self):
        m=Memory(first=1); opening=ygopro_opening.create(True); frame=m.sample()['frame']
        ygopro_opening.observe(opening,frame['opening_sample'],frame,lambda:1)
        self.assertEqual(opening['cards'],m.hand_codes)
        self.assertEqual(opening['method'],'masterduel-duel-start-and-own-hand')
        self.assertEqual(opening['detected_order'],'second')
        m.put(m.info+m.phase_offset,'i',2); frame=m.sample(with_deck=False)['frame']
        frame['opening_sample']['hand'] += [99]; frame['opening_sample']['turn']=2
        ygopro_opening.observe(opening,frame['opening_sample'],frame,lambda:2)
        self.assertEqual(opening['cards'],m.hand_codes)
        self.assertEqual(opening['captured_ms'],1)

    def test_late_attach_or_noninitial_effect_never_supplies_draw_or_deck(self):
        for change in ('turn','phase','effect'):
            m=Memory()
            offset={'turn':m.info+m.turn_offset,'phase':m.info+m.phase_offset,'effect':m.work+m.effect_offset}[change]
            m.put(offset,'i',2)
            value=m.sample(); self.assertIsNone(value['frame']['opening_sample']['draw'])
            self.assertNotIn('construction',value); self.assertIn('deck_error',value)

    def test_lobby_loading_end_unsupported_and_new_round_identity(self):
        m=Memory(); original=m.sample()
        m.put(m.client+0x1c4,'i',10); self.assertEqual(m.sample()['frame']['phase'],'waiting_choice')
        m.put(m.client+0x1c4,'i',17); self.assertEqual(m.sample()['frame']['phase'],'ended')
        m.put(m.statics['DuelClient'],'Q',0); self.assertEqual(m.sample()['frame']['phase'],'waiting_start')
        for key,value in (('GameMode',7),('MyType',2),('tag',1),('Type',1)):
            m=Memory();m.put(m.settings[key]+16,'q',value)
            self.assertEqual(m.sample()['frame']['phase'],'unsupported')
        m=Memory(); m.put(m.base+CLASSES['DuelClient'],'Q',0x800001)
        self.assertEqual(m.sample()['frame']['phase'],'waiting_start')

    def test_bad_names_counts_hidden_hand_and_unknown_cards_fail_closed(self):
        mutations=[lambda m:m.put(m.classes['DuelClient']+16,'Q',0xfffffffffffffff0),
                   lambda m:m.put(m.matrix+24,'Q',999),
                   lambda m:m.put(m.hand_items[0]+0x18,'B',1),
                   lambda m:m.put(m.hand_items[0]+16,'i',9999),
                   lambda m:m.put(m.cells[13]+0x54,'i',4)]
        for mutation in mutations:
            m=Memory();mutation(m)
            with self.assertRaises(CaptureError):m.sample()

    def test_changed_memory_during_sample_is_rejected(self):
        m=Memory(); reader=Reader(m,m.base); reader.read(m.client+0x1c4,4)
        m.put(m.client+0x1c4,'i',17)
        with self.assertRaises(CaptureError):reader.verify()

    def test_canonical_card_mapping_not_beta_alias(self):
        self.assertEqual(card_ids()[13522],16188701)
        pairs=[tuple(map(int,row.split())) for row in (Path(__file__).resolve().parents[1]/'src/trainer/data/masterduel-ydk-ids.txt').read_text().splitlines()]
        first={}
        for code,md in pairs:first.setdefault(md,code)
        self.assertEqual(card_ids(),first)

    def test_attach_editor_block_restart_and_module_dispatch(self):
        capture=Capture()
        with patch('ygopro_capture.processes',return_value=[{'pid':123,'supported':True,'path':'fixture','created':1}]):
            attached=capture.attach(platform='masterduel')['process']
        with self.assertRaisesRegex(CaptureError,'智能化识别'):capture.deck(attached['capture_id'])
        with patch('ygopro_capture.WindowsProcess') as process,patch('masterduel_capture.Reader') as reader:
            memory=process.return_value.__enter__.return_value;memory.identity.return_value=('fixture',1)
            reader.return_value.sample.return_value={'frame':{}}
            capture.live_sample(attached['capture_id']);memory.image_base.assert_called_with(123,'GameAssembly.dll')
            memory.identity.return_value=('fixture',2)
            with self.assertRaises(CaptureError):capture.live_sample(attached['capture_id'])

    def test_fingerprint_requires_every_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            image=Path(temporary)/'masterduel.exe'
            self.assertFalse(verify_build(image,'bad')['supported'])
            self.assertFalse(verify_build(image,IMAGE_HASH)['supported'])
            hashes={}
            for relative in COMPONENTS:
                path=image.parent/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
                hashes[relative]=hashlib.sha256(b'fixture').hexdigest()
            with patch('masterduel_capture.COMPONENTS',hashes):
                self.assertTrue(verify_build(image,IMAGE_HASH)['supported'])
                path.write_bytes(b'changed');self.assertFalse(verify_build(image,IMAGE_HASH)['supported'])
