import copy
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/trainer'))
from ygopro_capture import read_order, PROFILES, CaptureError
from ygopro_order import OrderMonitor

PROFILE=next(iter(PROFILES.values()))


class Memory:
    base=0x1000000
    game=0x2000000

    def __init__(self,started=0,in_duel=0,finished=0,first=1,turn=0,lobby=1,rps=0,choosing=0,player=0,replay=0):
        data=bytearray(34)
        data[0:8]=bytes([started,in_duel,finished,replay,0,first,0,0])
        struct.pack_into('<i',data,28,turn)
        self.memory={self.base+PROFILE['game']:struct.pack('<Q',self.game),self.game+PROFILE['duel_info']:data,
                     self.game+PROFILE['player_type']:bytes([player])}
        for index,(name,value) in enumerate(zip(('lobby_window','rps_window','order_window'),(lobby,rps,choosing))):
            pointer=0x3000000+index*0x1000
            self.memory[self.game+PROFILE[name]]=struct.pack('<Q',pointer)
            self.memory[pointer+PROFILE['gui_visible']]=bytes([value])

    def read(self,address,size):return bytes(self.memory[address][:size])


def frame(phase,first=None,turn=0):
    return {'phase':phase,'detected_order':first,'evidence':{'turn':turn}}


class OrderTests(unittest.TestCase):
    def test_stale_first_flag_never_decides_waiting_rps_or_choice(self):
        for kwargs,phase in [({},'waiting_start'),({'started':1,'lobby':0,'rps':1},'rps'),
                             ({'started':1,'lobby':0,'choosing':1},'choose_order'),
                             ({'started':1,'in_duel':1,'lobby':0},'waiting_choice')]:
            memory=Memory(**kwargs);value=read_order(memory,memory.base,PROFILE)
            self.assertEqual(value['phase'],phase);self.assertIsNone(value['detected_order'])
        for first in (0,1):
            memory=Memory(started=1,in_duel=1,lobby=0,turn=1,first=first)
            self.assertEqual(read_order(memory,memory.base,PROFILE)['detected_order'],'first' if first else 'second')

    def test_ended_observer_replay_and_racing_flags_are_rejected(self):
        for kwargs,phase in [({'finished':1,'lobby':0},'ended'),({'player':7},'unsupported'),({'replay':1},'unsupported')]:
            memory=Memory(**kwargs);value=read_order(memory,memory.base,PROFILE)
            self.assertEqual(value['phase'],phase);self.assertIsNone(value['detected_order'])
        memory=Memory(started=2)
        with self.assertRaises(CaptureError):read_order(memory,memory.base,PROFILE)

    def monitor(self):
        source=SimpleNamespace(attached={'pid':123},raw=frame('waiting_start'))
        source.order=lambda _:copy.deepcopy(source.raw)
        written={}
        store=SimpleNamespace(root=Path('isolated-test'),ygopro_capture=source)
        return OrderMonitor(store,lambda p,data:written.update({p.name:copy.deepcopy(data)}),lambda:12345),source,written

    def test_first_second_and_opponent_choice_rounds_keep_separate_records(self):
        monitor,source,written=self.monitor();initial=monitor.start('capture')
        ids=[]
        for order,seen in [('first',True)]*3+[('second',True)]*3+[('second',False),('first',False)]:
            monitor.accept(frame('waiting_start'))
            monitor.accept(frame('rps'));monitor.accept(frame('waiting_choice'))
            if seen:monitor.accept(frame('choose_order'))
            source.raw=frame('detected',order,1);state=monitor.poll(initial['monitor_id'])
            ids.append(state['round_id']);self.assertEqual(state['self_choice_seen'],seen)
            result=monitor.confirm({**state,'order':order})
            self.assertEqual(result['confirmed']['order'],order)
            monitor.accept(frame('ended'))
            self.assertEqual(written[state['round_id']+'.json']['confirmed']['order'],order)
        self.assertEqual(len(set(ids)),8)

    def test_manual_override_persists_both_values_and_stale_confirmation_is_refused(self):
        monitor,source,written=self.monitor();monitor.start('capture')
        source.raw=frame('detected','first',1);state=monitor.poll(monitor.monitor_id)
        with self.assertRaisesRegex(ValueError,'手动'):monitor.confirm({**state,'order':'second'})
        result=monitor.confirm({**state,'order':'second','manual':True})
        self.assertEqual(result['confirmed']['detected_order'],'first')
        self.assertEqual(result['confirmed']['order'],'second')
        self.assertEqual(written[state['round_id']+'.json']['confirmations'][0]['source'],'manual')
        source.raw=frame('rps')
        with self.assertRaises(CaptureError):monitor.confirm({**state,'order':'first'})
        source.raw=frame('detected','second',1)
        with self.assertRaisesRegex(CaptureError,'状态已改变'):monitor.confirm({**state,'order':'first'})
        self.assertEqual(written[state['round_id']+'.json']['confirmed']['order'],'second')

    def test_temporary_read_failure_does_not_invent_a_new_round(self):
        monitor,source,_=self.monitor();monitor.start('capture')
        source.raw=frame('detected','first',1);state=monitor.poll(monitor.monitor_id)
        monitor.accept({'phase':'disconnected','detected_order':None,'evidence':{},'error':'reading'})
        recovered=monitor.poll(monitor.monitor_id)
        self.assertEqual(recovered['round_id'],state['round_id'])

    def test_failed_confirmation_write_does_not_claim_success(self):
        monitor,source,_=self.monitor();monitor.start('capture')
        source.raw=frame('detected','first',1);state=monitor.poll(monitor.monitor_id)
        def failed(*_):raise OSError('disk full')
        monitor.write=failed
        with self.assertRaises(OSError):monitor.confirm({**state,'order':'first'})
        self.assertIsNone(monitor.round['confirmed']);self.assertEqual(monitor.round['confirmations'],[])


if __name__=='__main__':unittest.main()
