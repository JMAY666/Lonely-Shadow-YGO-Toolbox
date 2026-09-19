"""The shared scoring head must respect candidate permutation and legal masking."""
import struct
import unittest
import torch
from contract_v2 import build,feature_arrays
from student_v2 import StudentV2,KEYS
from test_contract_v2 import fixture,CAT


class StudentTests(unittest.TestCase):
    def test_candidate_permutation_and_padding_mask(self):
        torch.set_num_threads(2);torch.manual_seed(29)
        state=fixture();state['raw']=(bytes([141,0,1])+struct.pack('<I',3)).hex()
        features=feature_arrays(build(state,CAT))
        tensors={key:torch.from_numpy(value.copy()).unsqueeze(0) for key,value in features.items()}
        for key,value in tensors.items():
            if value.dtype==torch.uint8:tensors[key]=value.float()/255
        model=StudentV2().eval()
        with torch.no_grad():before=model(*(tensors[k] for k in KEYS))
        permutation=torch.arange(64);permutation[0],permutation[1]=1,0
        for key in ('actions','action_numeric','members','legal'):tensors[key]=tensors[key][:,permutation]
        with torch.no_grad():after=model(*(tensors[k] for k in KEYS))
        torch.testing.assert_close(after,before[:,permutation])
        self.assertTrue(torch.isfinite(before).all())
        self.assertLess(int(before.argmax(1).item()),2)
        self.assertTrue((before[:,2:]==-1e9).all())


if __name__=='__main__':unittest.main()
