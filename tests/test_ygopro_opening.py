import struct
import unittest
from unittest.mock import patch

import test_ygopro_order as order_fixture
from test_ygopro_order import Memory, PROFILE, frame
from ygopro_capture import read_order, read_opening_sample, CaptureError


CARDS = [111, 222, 111, 333, 444]


class OpeningMemory(Memory):
    def __init__(self, hand=None, first=1, player=0):
        super().__init__(started=1,in_duel=1,first=first,turn=0,lobby=0)
        hand=CARDS if hand is None else hand
        start=0x5000000
        self.memory[self.game+PROFILE['hand_vector']]=struct.pack('<3Q',start,start+len(hand)*8,start+60*8)
        self.memory[start]=b''.join(struct.pack('<Q',0x6000000+i*0x100) for i in range(len(hand)))
        for index,code in enumerate(hand):
            pointer=0x6000000+index*0x100
            self.memory[pointer+PROFILE['client_code']]=struct.pack('<I',code)
            self.memory[pointer+PROFILE['client_controller']]=b'\0\2'
        packet=struct.pack('<BBB5I',90,player,5,*CARDS)
        self.memory[self.base+PROFILE['message']]=packet
        self.memory[self.base+PROFILE['message_size']]=struct.pack('<Q',len(packet))


class OpeningTests(unittest.TestCase):
    def monitor(self):return order_fixture.OrderTests().monitor()

    def deal(self,monitor,source,cards=CARDS,first=True):
        monitor.start('capture')
        monitor.accept(frame('rps'))
        raw=frame('waiting_choice');raw['evidence']['is_first']=first
        raw['opening_sample']={'hand':cards[:2], 'draw':list(cards), 'turn':0}
        monitor.accept(raw)
        raw['opening_sample']={'hand':list(cards), 'draw':None, 'turn':0}
        monitor.accept(raw)
        source.raw=frame('detected','first' if first else 'second',1)
        return monitor.poll(monitor.monitor_id)

    def test_message_and_own_hand_are_read_with_duplicate_copies(self):
        memory=OpeningMemory();order=read_order(memory,memory.base,PROFILE)
        result=read_opening_sample(memory,memory.base,PROFILE,order)
        self.assertEqual(result['draw'],CARDS);self.assertEqual(result['hand'],CARDS)
        memory=OpeningMemory(first=0,player=1);order=read_order(memory,memory.base,PROFILE)
        self.assertEqual(read_opening_sample(memory,memory.base,PROFILE,order)['draw'],CARDS)

    def test_opponent_message_is_never_decoded_and_wrong_zone_is_rejected(self):
        memory=OpeningMemory(player=1);order=read_order(memory,memory.base,PROFILE)
        original=memory.read
        def checked(address,size):
            if address==memory.base+PROFILE['message']:self.assertLessEqual(size,3)
            return original(address,size)
        memory.read=checked
        self.assertIsNone(read_opening_sample(memory,memory.base,PROFILE,order)['draw'])
        memory=OpeningMemory();order=read_order(memory,memory.base,PROFILE)
        memory.memory[0x6000000+PROFILE['client_controller']]=b'\1\2'
        with self.assertRaises(CaptureError):read_opening_sample(memory,memory.base,PROFILE,order)

    def test_partial_deal_cannot_be_confirmed_and_later_draws_cannot_replace_snapshot(self):
        monitor,source,written=self.monitor();state=self.deal(monitor,source)
        opening=state['opening'];self.assertEqual(opening['cards'],CARDS)
        self.assertEqual(opening['status'],'ready')
        source.raw={**frame('detected','first',3),'opening_sample':{'hand':CARDS+[555],'draw':[555],'turn':3}}
        later=monitor.poll(monitor.monitor_id)
        self.assertEqual(later['opening'],opening)
        self.assertEqual(written[state['round_id']+'.json']['opening']['cards'],CARDS)

    def test_first_confirmation_is_bound_to_round_and_frozen_snapshot(self):
        monitor,source,written=self.monitor();state=self.deal(monitor,source)
        with self.assertRaises(CaptureError):monitor.confirm_opening({**state,'snapshot_id':state['opening']['snapshot_id']})
        monitor.confirm({**state,'order':'first'})
        with self.assertRaises(CaptureError):monitor.confirm_opening({**state,'snapshot_id':'old'})
        saved=monitor.confirm_opening({**state,'snapshot_id':state['opening']['snapshot_id']})
        self.assertEqual(saved['opening']['confirmed']['cards'],CARDS)
        source.raw=frame('rps')
        with self.assertRaises(CaptureError):monitor.confirm_opening({**state,'snapshot_id':state['opening']['snapshot_id']})
        self.assertEqual(written[state['round_id']+'.json']['opening']['confirmed']['cards'],CARDS)

    def test_second_opening_is_saved_but_cannot_enter_first_player_flow(self):
        monitor,source,written=self.monitor();state=self.deal(monitor,source,first=False)
        monitor.confirm({**state,'order':'second'})
        with self.assertRaisesRegex(CaptureError,'后攻起手'):
            monitor.confirm_opening({**state,'snapshot_id':state['opening']['snapshot_id']})
        self.assertEqual(written[state['round_id']+'.json']['opening']['cards'],CARDS)

    def test_late_connection_or_missed_deal_never_labels_current_hand_as_opening(self):
        monitor,source,_=self.monitor();source.raw=frame('detected','first',2)
        state=monitor.start('capture');self.assertEqual(state['opening']['status'],'missed')
        monitor.accept(frame('rps'))
        state=monitor.accept(frame('detected','first',1))
        self.assertEqual(state['opening']['status'],'missed');self.assertEqual(state['opening']['cards'],[])

    def test_partially_dealt_cards_wait_for_the_complete_message_count(self):
        monitor,source,_=self.monitor();monitor.start('capture');monitor.accept(frame('rps'))
        raw=frame('waiting_choice');raw['evidence']['is_first']=True
        raw['opening_sample']={'hand':CARDS[:1],'draw':CARDS,'turn':0}
        value=monitor.accept(raw)
        self.assertEqual(value['opening']['status'],'dealing');self.assertEqual(value['opening']['cards'],[])
        self.assertNotIn('candidate',value['opening'])

    def test_sampling_gap_does_not_reuse_a_previous_opening_when_turn_flags_match(self):
        monitor,source,written=self.monitor();state=self.deal(monitor,source)
        with patch('ygopro_order.time.monotonic',return_value=monitor.last_success+3):
            resumed=monitor.poll(monitor.monitor_id)
        self.assertNotEqual(resumed['round_id'],state['round_id'])
        self.assertGreater(resumed['revision'],state['revision'])
        self.assertIn(resumed['round_id']+'.json',written)
        self.assertEqual(resumed['opening']['status'],'missed');self.assertEqual(resumed['opening']['cards'],[])
        self.assertEqual(written[state['round_id']+'.json']['opening']['cards'],CARDS)

    def test_failed_snapshot_write_retries_even_when_duel_flags_are_unchanged(self):
        monitor,source,written=self.monitor();monitor.start('capture');monitor.accept(frame('rps'))
        raw=frame('waiting_choice');raw['evidence']['is_first']=True
        raw['opening_sample']={'hand':CARDS[:1],'draw':CARDS,'turn':0};monitor.accept(raw)
        original=monitor.write
        def failed(*_):raise OSError('disk full')
        monitor.write=failed
        raw['opening_sample']['hand']=list(CARDS);source.raw=raw
        with self.assertRaises(OSError):monitor.poll(monitor.monitor_id)
        self.assertTrue(monitor.pending_persist)
        self.assertEqual(written[monitor.round['id']+'.json']['opening']['status'],'dealing')
        monitor.write=original;state=monitor.poll(monitor.monitor_id)
        self.assertFalse(monitor.pending_persist)
        self.assertEqual(written[state['round_id']+'.json']['opening']['cards'],CARDS)


if __name__=='__main__':unittest.main()
