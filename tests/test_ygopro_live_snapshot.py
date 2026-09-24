import struct
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import threading

from test_ygopro_order import Memory, PROFILE
from ygopro_capture import CaptureError
from ygopro_live import read_snapshot, capture


class PublicMemory(Memory):
    def __init__(self):
        super().__init__(started=1,in_duel=1,first=0,turn=2,lobby=0)
        struct.pack_into('<2i',self.memory[self.game+PROFILE['duel_info']],12,6500,8000)
        self.memory[self.game+PROFILE['building']]=b'\0\0'
        self.hidden=set()
        for z,location in enumerate((1,2,4,8,16,32,64)):
            for player in (0,1):
                address=0x5000000+(z*2+player)*0x1000;pointer=0x6000000+(z*2+player)*0x1000
                self.memory[self.game+PROFILE['field_vectors']+(z*2+player)*24]=struct.pack('<3Q',address,address+8,address+8)
                self.memory[address]=struct.pack('<Q',pointer)
                position=2 if z in (3,5) else 1
                self.memory[pointer+PROFILE['client_controller']-1]=bytes([player,player,location,0,position])
                code_address=pointer+PROFILE['client_code']
                if z==0 or player==1 and (z in (1,6) or z in (3,5)):
                    self.hidden.add(code_address)
                    self.hidden.add(code_address+12)
                else:
                    self.memory[code_address]=struct.pack('<I',1000+z*2+player)
                    self.memory[code_address+12]=struct.pack('<2I',0x1021,3)
        self.reads=[]

    def read(self,address,size):
        if address in self.hidden:raise AssertionError('Attempted hidden identity read')
        self.reads.append((address,size));return super().read(address,size)


class SnapshotTests(unittest.TestCase):
    def test_reads_public_zones_and_own_hand_without_any_hidden_identity(self):
        m=PublicMemory();result=read_snapshot(m,m.base,PROFILE,'capture')
        self.assertEqual(result['lp'],[6500,8000]);self.assertEqual(result['player'],0)
        self.assertEqual(result['opponent_hand'],1)
        self.assertFalse(result['history_complete']);self.assertFalse(result['window_verified'])
        self.assertFalse(result['capabilities']['phase'])
        self.assertFalse(any(c['zone']=='deck' or c['controller']==1 and c['zone'] in ('hand','extra') for c in result['cards']))
        self.assertTrue(all(c['code']==0 for c in result['cards'] if c['controller']==1 and c['zone'] in ('spell','banished')))

    def test_changed_public_code_or_zone_cancels_whole_snapshot(self):
        for kind in ('code','zone'):
            m=PublicMemory();original=m.read;target=0x6000000+2*0x1000+PROFILE['client_code'];calls=0
            def racing(address,size):
                nonlocal calls
                value=original(address,size)
                if address==target:
                    calls+=1
                    if calls>1:return struct.pack('<I',999)
                return value
            if kind=='code':m.read=racing
            else:m.memory[0x6000000+2*0x1000+PROFILE['client_controller']-1]=b'\0\0\x04\0\x01'
            with self.assertRaises(CaptureError):read_snapshot(m,m.base,PROFILE,'capture')

    def test_unsupported_view_and_oversized_zone_fail_closed(self):
        m=PublicMemory();m.memory[m.game+PROFILE['player_type']]=b'\x07'
        with self.assertRaises(CaptureError):read_snapshot(m,m.base,PROFILE,'capture')
        m=PublicMemory();m.memory[m.game+PROFILE['field_vectors']]=struct.pack('<3Q',0x5000000,0x5000000+101*8,0x5000000+101*8)
        with self.assertRaises(CaptureError):read_snapshot(m,m.base,PROFILE,'capture')

    def test_capture_requires_pinned_build_and_current_identity(self):
        source=SimpleNamespace(lock=threading.Lock(),attached={'capture_id':'a','platform':'masterduel'})
        with self.assertRaises(CaptureError):capture(source,'a')
        source.attached.update(platform='ygopro',image_hash='unknown')
        with self.assertRaises(CaptureError):capture(source,'a')

    def test_composite_spell_positions_keep_facedown_identity_hidden(self):
        m=PublicMemory();pointer=0x6000000+7*0x1000
        m.memory[pointer+PROFILE['client_controller']-1]=bytes([1,1,8,0,10])
        value=read_snapshot(m,m.base,PROFILE,'capture')
        card=next(c for c in value['cards'] if c['controller']==1 and c['zone']=='spell')
        self.assertEqual(card['code'],0);self.assertFalse(card['faceup'])
        m.memory[pointer+PROFILE['client_controller']-1]=bytes([1,1,8,0,3])
        with self.assertRaises(CaptureError):read_snapshot(m,m.base,PROFILE,'capture')


if __name__=='__main__':unittest.main()
