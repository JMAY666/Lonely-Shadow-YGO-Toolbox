"""Provenance and candidate-identity checks for the isolated training probe."""
from copy import deepcopy
import unittest

import torch

from prepare_smoke_data import checked_session, require_confirmed
from student import Student


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.step = {'engine_accepted': True, 'prompt': '0b00', 'response': '00000000'}
        self.node = {'player': 0, 'raw': '0b00', 'seq': 10}
        self.responses = [{'raw': '00000000'}]
        self.following = {'seq': 12}

    def test_confirmed_native_transition(self):
        require_confirmed(self.step, self.node, self.responses, self.following)

    def test_unexecuted_suggestion_rejected(self):
        with self.assertRaises(ValueError):
            require_confirmed({**self.step, 'engine_accepted': False}, self.node, self.responses, self.following)

    def test_retried_or_different_response_rejected(self):
        for responses in (self.responses * 2, [{'raw': '01000000'}]):
            with self.subTest(responses=responses), self.assertRaises(ValueError):
                require_confirmed(self.step, self.node, responses, self.following)

    def test_stale_or_wrong_player_rejected(self):
        for node in ({**self.node, 'raw': '1000'}, {**self.node, 'player': 1}):
            with self.subTest(node=node), self.assertRaises(ValueError):
                require_confirmed(self.step, node, self.responses, self.following)
        with self.assertRaises(ValueError):
            require_confirmed(self.step, self.node, self.responses, {'seq': 9})

    def test_session_path_cannot_escape_pilot(self):
        for session in ('../private', '../../../../../user-data', ''):
            with self.subTest(session=session), self.assertRaises(ValueError):
                checked_session(session)


class CandidateTests(unittest.TestCase):
    def test_action_permutation_preserves_semantics_and_mask(self):
        torch.set_num_threads(4)
        torch.manual_seed(5)
        model = Student().eval()
        inputs = [torch.rand(2, 160, 41), torch.rand(2, 23), torch.rand(2, 32, 14),
                  torch.rand(2, 24, 12), torch.zeros(2, 24, dtype=torch.bool)]
        inputs[-1][0, [1, 6, 12]] = True
        inputs[-1][1, [3, 10]] = True
        order = torch.randperm(24)
        permuted = deepcopy(inputs)
        permuted[3], permuted[4] = inputs[3][:, order], inputs[4][:, order]
        with torch.no_grad():
            original, shuffled = model(*inputs), model(*permuted)
        torch.testing.assert_close(shuffled, original[:, order])
        self.assertTrue(inputs[-1].gather(1, original.argmax(1)[:, None]).all())
        self.assertTrue(torch.equal(order[shuffled.argmax(1)], original.argmax(1)))


if __name__ == '__main__':
    unittest.main()
