"""Fresh CPU processes, corrupt features, worker death and package mismatch."""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sys

os.environ['HIP_VISIBLE_DEVICES']='-1'
import numpy as np
import torch
from policy_client import PolicyClient
from student_v2 import KEYS
from native_session import BASE


def main():
    model=Path(sys.argv[1]).resolve();data=Path(sys.argv[2]).resolve()
    if not model.is_relative_to(BASE.resolve()) or not data.is_relative_to(BASE.resolve()):raise ValueError('isolated inputs required')
    output=BASE/('worker-check-'+datetime.now().strftime('%Y%m%d-%H%M%S'));output.mkdir()
    report={'status':'running','checks':[]};worker=None
    try:
        with np.load(data,allow_pickle=False) as archive:
            samples=[{k:archive[k][i].copy() for k in KEYS} for i in (0,len(archive['legal'])//2,len(archive['legal'])-1)]
        torch.set_num_threads(4);reference=torch.export.load(io.BytesIO((model/'student-cpu.pt2').read_bytes())).module()
        expected=[]
        for sample in samples:
            tensors=[torch.from_numpy(sample[k]).unsqueeze(0) for k in KEYS]
            tensors=[t.float()/255 if t.dtype==torch.uint8 else t for t in tensors]
            with torch.no_grad():expected.append(int(reference(*tensors).argmax(1)))
        worker=PolicyClient(model,output/'worker-1.log')
        for threads in (2,4):
            for sample,index in zip(samples,expected):assert worker.predict(sample,threads)['index']==index
        report['checks'].append('fresh_cpu_process_2_and_4_threads_rankings_match')
        bad={**samples[0],'cards':samples[0]['cards'][:-1]}
        try:worker.predict(bad)
        except RuntimeError:pass
        else:raise AssertionError('truncated observation accepted')
        assert worker.predict(samples[0])['index']==expected[0]
        report['checks'].append('malformed_features_rejected_without_corrupting_worker')
        worker.process.terminate();worker.process.wait(timeout=10)
        try:worker.predict(samples[0])
        except (OSError,RuntimeError):pass
        else:raise AssertionError('dead worker returned an action')
        worker.close();worker=None
        worker=PolicyClient(model,output/'worker-2.log')
        assert worker.predict(samples[0])['index']==expected[0]
        report['checks'].append('worker_exit_stops_old_request_and_fresh_worker_matches')
        broken=output/'bad-package';broken.mkdir()
        manifest=json.loads((model/'model.json').read_text(encoding='utf-8'));manifest['code']={}
        (broken/'model.json').write_text(json.dumps(manifest),encoding='utf-8')
        try:PolicyClient(broken,output/'unused.log')
        except ValueError as error:assert 'mismatch' in str(error)
        else:raise AssertionError('incompatible model accepted')
        report['checks'].append('package_code_mismatch_rejected_before_process_start')
        report['status']='passed'
    finally:
        if worker:worker.close()
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Worker evidence:',output,report,flush=True)


if __name__=='__main__':main()
