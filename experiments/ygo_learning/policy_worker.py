"""CPU-only policy process. Receives feature tensors, never native private state."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

os.environ['HIP_VISIBLE_DEVICES']='-1'
import numpy as np
import torch
from student_v2 import KEYS

SHAPES={'cards':(160,41),'card_numeric':(160,8),'global':(23,),'global_numeric':(16,),
        'history':(32,29),'chains':(16,22),'actions':(64,27),'action_numeric':(64,8),
        'members':(64,160),'legal':(64,)}


def main():
    folder=Path(sys.argv[1]).resolve()
    manifest=json.loads((folder/'model.json').read_text(encoding='utf-8'))
    data=(folder/'student-cpu.pt2').read_bytes()
    if hashlib.sha256(data).hexdigest()!=manifest['export_sha256']:
        raise ValueError('CPU model hash mismatch')
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    started=time.perf_counter();model=torch.export.load(io.BytesIO(data)).module()
    print(json.dumps({'ready':True,'load_ms':(time.perf_counter()-started)*1000,'schema':2}),flush=True)
    for line in sys.stdin:
        request=json.loads(line)
        try:
            if request.get('op')=='stop':break
            threads=request.get('threads',4)
            if threads not in (2,4):raise ValueError('unsupported thread count')
            torch.set_num_threads(threads)
            tensors=[]
            for key in KEYS:
                item=request['features'][key]
                dtype='bool' if key=='legal' else 'float32' if key in ('card_numeric','global_numeric','action_numeric','members') else 'uint8'
                if item['dtype']!=dtype or tuple(item['shape'])!=SHAPES[key]:
                    raise ValueError('unsupported feature dtype')
                raw=base64.b64decode(item['data'],validate=True)
                if len(raw)>1024*1024:raise ValueError('feature payload too large')
                array=np.frombuffer(raw,dtype=item['dtype']).reshape(item['shape']).copy()
                if not np.isfinite(array).all():raise ValueError('non-finite features')
                tensor=torch.from_numpy(array)
                if item['dtype']=='uint8':tensor=tensor.float()/255
                tensors.append(tensor.unsqueeze(0))
            began=time.perf_counter()
            with torch.no_grad():scores=model(*tensors);index=int(scores.argmax(1).item())
            elapsed=(time.perf_counter()-began)*1000
            if not torch.isfinite(scores).all().item() or not tensors[-1][0,index].item():raise ValueError('policy selected padding or invalid score')
            print(json.dumps({'id':request['id'],'index':index,'model_ms':elapsed,'threads':threads}),flush=True)
        except Exception as error:
            print(json.dumps({'id':request.get('id'),'error':f'{type(error).__name__}: {error}'}),flush=True)


if __name__=='__main__':main()
