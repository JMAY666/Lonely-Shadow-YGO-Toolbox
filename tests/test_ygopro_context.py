import struct
import unittest
from unittest.mock import patch

from test_ygopro_order import PROFILE
from ygopro_context import TurnObserver,read_turn_marker


def frame(turn,phase='detected',first=False):
    return {'phase':phase,'detected_order':'first' if first else 'second',
            'evidence':{'started':True,'in_duel':True,'finished':False,'turn':turn,'is_first':first}}


class ContextTests(unittest.TestCase):
    def test_only_observed_new_turn_with_counter_advance_can_identify_player(self):
        t=TurnObserver();t.observe('a',1,frame(0,'waiting_choice'),None,0)
        t.observe('a',1,frame(1),1,.1);self.assertEqual(t.current('a',1,False,1,.2),1)
        t.observe('a',1,frame(1),0,.3) # Next message can precede the next counter write.
        self.assertEqual(t.current('a',1,False,1,.4),1)
        t.observe('a',1,frame(2),0,.5);self.assertEqual(t.current('a',1,False,2,.6),0)

    def test_late_attach_missed_message_gap_scene_and_round_changes_remain_unknown(self):
        for change in ('late','miss','gap','scene','order','rewind','skip'):
            t=TurnObserver();t.observe('a',1,frame(1),1,0)
            if change=='late':t.observe('a',1,frame(1),1,.1)
            elif change=='miss':t.observe('a',1,frame(2),None,.1)
            elif change=='gap':t.observe('a',1,frame(2),0,3)
            elif change=='scene':t.observe('a',2,frame(2),0,.1)
            elif change=='order':t.observe('a',1,frame(2,first=True),0,.1)
            elif change=='rewind':t.observe('a',1,frame(0),0,.1)
            else:t.observe('a',1,frame(3),0,.1)
            self.assertIsNone(t.player,change)

    def test_repeated_player_is_not_overridden_by_parity_and_stale_cache_expires(self):
        t=TurnObserver();t.observe('a',1,frame(0,'waiting_choice'),None,0)
        t.observe('a',1,frame(1),1,.1);t.observe('a',1,frame(2),1,.2)
        self.assertEqual(t.current('a',1,False,2,.3),1)
        self.assertIsNone(t.current('a',1,False,2,3))
        t.observe('a',1,frame(2,'ended'),None,3);self.assertIsNone(t.current('a',1,False,2,3))

    def test_cache_reader_never_decodes_other_messages_or_a_changing_frame(self):
        class Memory:
            def __init__(self,raw):self.raw=raw;self.reads=[]
            def read(self,address,size):
                self.reads.append((address,size))
                return struct.pack('<Q',len(self.raw)) if address==PROFILE['message_size'] else self.raw[:size]
        current=frame(2)
        with patch('ygopro_context.read_order',return_value=current) as order:
            m=Memory(bytes([40,1]));self.assertEqual(read_turn_marker(m,0,PROFILE,current),0)
            m=Memory(bytes([75,1]));self.assertIsNone(read_turn_marker(m,0,PROFILE,current))
            self.assertNotIn((PROFILE['message'],2),m.reads)
            order.return_value=frame(3)
            self.assertIsNone(read_turn_marker(Memory(bytes([40,1])),0,PROFILE,current))
