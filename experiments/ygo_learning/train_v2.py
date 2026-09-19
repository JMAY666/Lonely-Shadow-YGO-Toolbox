"""Small, development-only v2 fit and CPU export; no strategy evaluation."""
from datetime import datetime
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('TORCH_BLAS_PREFER_HIPBLASLT','0')
import numpy as np
import torch
from student_v2 import StudentV2,KEYS
from provenance import code_identity

ROOT=Path(__file__).resolve().parents[2]
LOCAL=ROOT/'.local/ygo-learning/p0b-p1'


def main():
    data_path=Path(sys.argv[1]).resolve()
    if not data_path.is_relative_to(LOCAL.resolve()):raise ValueError('data must be isolated')
    output=LOCAL/('model-v2-'+datetime.now().strftime('%Y%m%d-%H%M%S'));output.mkdir()
    report={'schema':2,'scope':'development_fit_only_not_strategy_quality','status':'running'}
    try:
        data_manifest=json.loads(data_path.with_name('manifest.json').read_text(encoding='utf-8'))
        if data_manifest['code']!=code_identity():raise ValueError('dataset/code mismatch')
        if data_manifest['data_sha256']!=hashlib.sha256(data_path.read_bytes()).hexdigest():raise ValueError('dataset hash mismatch')
        if not torch.version.hip or not torch.cuda.is_available():raise RuntimeError('ROCm GPU required')
        indexes=[i for i in range(torch.cuda.device_count()) if '9070 XT' in torch.cuda.get_device_name(i)]
        if len(indexes)!=1:raise RuntimeError('RX 9070 XT not found unambiguously')
        device=torch.device('cuda',indexes[0]);torch.cuda.set_device(device)
        torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.manual_seed(29)
        with np.load(data_path,allow_pickle=False) as values:
            batch=[]
            for key in KEYS:
                tensor=torch.from_numpy(values[key].copy())
                if tensor.dtype==torch.uint8:tensor=tensor.float()/255
                batch.append(tensor)
            target=torch.from_numpy(values['acceptable'].copy()).bool()
        cpu_batch=tuple(batch);batch=tuple(v.to(device) for v in batch);labels=target.to(device)
        if not labels.any(1).all() or (labels & ~batch[-1]).any():raise ValueError('invalid training target')
        def objective(scores,accepted):
            return (torch.logsumexp(scores,1)-torch.logsumexp(scores.masked_fill(~accepted,-1e9),1)).mean()
        initial_model=StudentV2()
        cpu_check=deepcopy(initial_model)
        gpu_check=deepcopy(initial_model).to(device)
        for check_model,check_batch,check_labels in ((cpu_check,tuple(x[:16] for x in cpu_batch),target[:16]),
                                                    (gpu_check,tuple(x[:16] for x in batch),labels[:16])):
            objective(check_model(*check_batch),check_labels).backward()
        max_error=0.0
        for a,b in zip(cpu_check.parameters(),gpu_check.parameters()):
            torch.testing.assert_close(a.grad,b.grad.cpu(),rtol=0.001,atol=0.00002)
            max_error=max(max_error,float((a.grad-b.grad.cpu()).abs().max()))
        report['cpu_gpu_gradient_max_error']=max_error
        del cpu_check,gpu_check
        model=initial_model.to(device)
        opt=torch.optim.AdamW(model.parameters(),lr=0.002,eps=1e-6,weight_decay=0.0001,foreach=False)
        with torch.no_grad():initial=float(objective(model(*batch),labels).item())
        started=time.perf_counter()
        for step in range(400):
            opt.zero_grad(set_to_none=True)
            scores=model(*batch);loss=objective(scores,labels);loss.backward()
            if not torch.stack([torch.isfinite(p.grad).all() for p in model.parameters()]).all().item():
                raise ValueError('non-finite training gradient')
            opt.step()
            if (step+1)%100==0:print('v2 GPU updates',step+1,flush=True)
        torch.cuda.synchronize(device)
        training_seconds=time.perf_counter()-started
        with torch.no_grad():reference=model(*batch).cpu()
        accuracy=float(target.gather(1,reference.argmax(1)[:,None]).float().mean().item())
        final=float(objective(reference,target).item())
        if final>=initial*0.5 or accuracy<0.90:raise ValueError(f'development fit failed: {initial} -> {final}, {accuracy}')
        state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
        torch.save({'model':state,'optimizer':opt.state_dict(),'steps':400},output/'checkpoint.pt')
        checkpoint=torch.load(output/'checkpoint.pt',map_location=device,weights_only=True)
        resumed=StudentV2().to(device);resumed.load_state_dict(checkpoint['model'])
        resumed_opt=torch.optim.AdamW(resumed.parameters(),lr=0.002,eps=1e-6,weight_decay=0.0001,foreach=False)
        resumed_opt.load_state_dict(checkpoint['optimizer'])
        for m,o in ((model,opt),(resumed,resumed_opt)):
            o.zero_grad(set_to_none=True);objective(m(*batch),labels).backward();o.step()
        for a,b in zip(model.parameters(),resumed.parameters()):torch.testing.assert_close(a,b,rtol=0.0001,atol=0.00001)
        report['optimizer_resume_passed']=True
        cpu=StudentV2().eval();cpu.load_state_dict(torch.load(output/'checkpoint.pt',map_location='cpu',weights_only=True)['model'])
        with torch.no_grad():restored=cpu(*cpu_batch)
        torch.testing.assert_close(reference,restored,rtol=0.0002,atol=0.0002)
        if not torch.equal(reference.argmax(1),restored.argmax(1)):raise ValueError('CPU changed selected actions')
        dim=torch.export.Dim('batch',min=1,max=4096)
        exported=torch.export.export(cpu,tuple(x[:2] for x in cpu_batch),dynamic_shapes=tuple({0:dim} for _ in cpu_batch))
        buffer=io.BytesIO();torch.export.save(exported,buffer);(output/'student-cpu.pt2').write_bytes(buffer.getvalue())
        checked=torch.export.load(io.BytesIO(buffer.getvalue())).module()
        with torch.no_grad():actual=checked(*cpu_batch)
        assert torch.equal(actual.argmax(1),reference.argmax(1))
        report.update(status='passed',samples=len(target),parameters=sum(p.numel() for p in model.parameters()),
            initial_loss=initial,final_loss=final,training_accuracy=accuracy,gpu_training_seconds=training_seconds,
            training_and_export_seconds=time.perf_counter()-started,
            device=torch.cuda.get_device_name(device),torch=str(torch.__version__),
            data_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),
            contract_sha256=hashlib.sha256(Path(__file__).with_name('contract_v2.py').read_bytes()).hexdigest(),
            model_source_sha256=hashlib.sha256(Path(__file__).with_name('student_v2.py').read_bytes()).hexdigest(),
            export_sha256=hashlib.sha256(buffer.getvalue()).hexdigest(),cpu_export_rankings_equal=True)
        report.update(code=code_identity(),runtime=data_manifest['runtime'],encoded_codes=data_manifest['encoded_codes'],
                      source_hands=data_manifest['source_hands'],dataset_manifest_sha256=hashlib.sha256(data_path.with_name('manifest.json').read_bytes()).hexdigest())
        (output/'dataset-manifest.json').write_bytes(data_path.with_name('manifest.json').read_bytes())
        (output/'model.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        (output/'training-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Model evidence:',output,flush=True)


if __name__=='__main__':main()
