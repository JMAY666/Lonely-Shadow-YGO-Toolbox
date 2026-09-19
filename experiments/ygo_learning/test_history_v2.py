"""History transactions reject stale/duplicate acknowledgements and restore exactly."""
from copy import deepcopy
import unittest
from contract_v2 import build,feature_arrays
from confirmed_history import ConfirmedHistory
from test_contract_v2 import fixture,CAT


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=fixture();self.bundle=build(self.snapshot,CAT);self.features=feature_arrays(self.bundle)
        self.ack={'version':1,'raw':self.snapshot['raw'],'response':self.bundle['candidates'][0]['response'],
                  'acknowledged':True,'following_version':2}

    def test_duplicate_does_not_advance_history(self):
        history=ConfirmedHistory();history.commit(self.bundle,self.features,0,self.ack)
        rows=deepcopy(history.rows)
        with self.assertRaisesRegex(ValueError,'duplicate'):history.commit(self.bundle,self.features,0,self.ack)
        self.assertEqual(history.rows,rows)

    def test_wrong_actual_action_keeps_history_empty(self):
        history=ConfirmedHistory();ack={**self.ack,'response':'ffffffff'}
        with self.assertRaisesRegex(ValueError,'response_mismatch'):history.commit(self.bundle,self.features,0,ack)
        self.assertEqual(history.rows,[])

    def test_restored_prefix_equals_confirmed_history(self):
        history=ConfirmedHistory();history.commit(self.bundle,self.features,0,self.ack)
        restored=ConfirmedHistory.rebuild([{'before':self.snapshot,'response':self.ack['response'],
                                           'acknowledgement':self.ack}],CAT,set(CAT))
        self.assertEqual(history.rows,restored.rows)

    def test_old_window_acknowledgement_rejected(self):
        with self.assertRaisesRegex(ValueError,'window_mismatch'):
            ConfirmedHistory().commit(self.bundle,self.features,0,{**self.ack,'version':0})


if __name__=='__main__':unittest.main()
