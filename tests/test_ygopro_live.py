from copy import deepcopy
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_ygopro_order import Memory as OrderMemory, PROFILE
from ygopro_capture import Capture, CaptureError, WindowsProcess, PROFILES
from ygopro_live import read_snapshot


class Memory(OrderMemory):
    def __init__(self):
        super().__init__(started=1,in_duel=1,first=0,turn=2,lobby=0)
        struct.pack_into('<2i',self.memory[self.game+PROFILE['duel_info']],12,6000,8000)
        self.memory[self.game+PROFILE['building']]=b'\0\0'
        self.private=set();self.pointers={}
        for zi,location in enumerate((1,2,4,8,16,32,64)):
            for player in (0,1):
                slot=2*zi+player;start=0x4000000+slot*0x1000
                pointer=0x5000000+slot*0x1000;self.pointers[player,location]=pointer
                self.memory[self.game+PROFILE['field_vectors']+24*slot]=struct.pack('<3Q',start,start+8,start+8)
                self.memory[start]=struct.pack('<Q',pointer)
                position=1 if location==4 else 5 if location==16 else 10
                self.memory[pointer+PROFILE['client_controller']-1]=bytes([player,player,location,0,position])
                self.memory[pointer+PROFILE['client_code']]=struct.pack('<I',1184620+slot)
                if location==1 or player==1 and location in (2,8,32,64):self.private.add(pointer+PROFILE['client_code'])
        self.reads=[]

    def read(self,address,size):
        if address in self.private:raise AssertionError('Private card identity was read')
        self.reads.append((address,size))
        for base,data in self.memory.items():
            if base<=address and address+size<=base+len(data):return bytes(data[address-base:address-base+size])
        raise CaptureError('Unmapped test memory')


class LiveResourceTests(unittest.TestCase):
    def test_private_codes_are_not_read_and_combined_positions_are_valid(self):
        m=Memory();v=read_snapshot(m,m.base,PROFILE)
        self.assertEqual(v['lp'],[6000,8000]);self.assertEqual(v['turn'],2)
        self.assertFalse(v['rules_complete']);self.assertIsNone(v['phase'])
        self.assertFalse(any(c['location']==1 or c['controller']==1 and c['location'] in (2,64) for c in v['cards']))
        hidden=[c for c in v['cards'] if c['controller']==1 and c['location'] in (8,32)]
        self.assertTrue(all(c['code'] is None for c in hidden));self.assertEqual(len(hidden),2)

    def test_card_metadata_and_codes_are_rechecked_even_if_vectors_stay_equal(self):
        for kind in ('code','position','location'):
            m=Memory();read=m.read;count=0
            address=m.pointers[0,2]+(PROFILE['client_code'] if kind=='code' else PROFILE['client_controller']-1)
            def race(a,n):
                nonlocal count
                data=read(a,n)
                if a==address:
                    count+=1
                    if count>1:
                        data=bytearray(data);data[0 if kind=='code' else 4 if kind=='position' else 2]^=1;data=bytes(data)
                return data
            m.read=race
            with self.assertRaises(CaptureError):read_snapshot(m,m.base,PROFILE)

    def test_wrong_owner_location_slot_and_container_overflow_are_rejected(self):
        for kind in ('owner','location','slot','container'):
            m=Memory();a=m.pointers[0,4]+PROFILE['client_controller']-1
            data=bytearray(m.memory[a])
            if kind=='container':m.memory[m.game+PROFILE['field_vectors']+4*24]=struct.pack('<3Q',0x4004000,0x4004400,0x4004400)
            else:
                data[{'owner':0,'location':2,'slot':3}[kind]]=255;m.memory[a]=data
            with self.assertRaises(CaptureError):read_snapshot(m,m.base,PROFILE)

    def test_process_restart_and_two_different_reads_never_publish_a_snapshot(self):
        c=Capture();c.attached={'capture_id':'id','pid':123,'platform':'ygopro','image_hash':next(iter(PROFILES)),'path':'client','created':1}
        with patch('ygopro_capture.WindowsProcess') as factory,patch('ygopro_live.read_snapshot') as read,patch('ygopro_capture.time.sleep'):
            process=factory.return_value.__enter__.return_value
            process.identity.return_value=('client',2)
            with self.assertRaisesRegex(CaptureError,'重新启动'):c.resource_snapshot('id')
            process.identity.return_value=('client',1);read.side_effect=[{'turn':1},{'turn':2}]
            with self.assertRaisesRegex(CaptureError,'变化'):c.resource_snapshot('id')
            c.attached['platform']='masterduel'
            with self.assertRaisesRegex(CaptureError,'不支持'):c.resource_snapshot('id')

    def test_default_native_module_lookup_finds_the_actual_ygopro_name(self):
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
