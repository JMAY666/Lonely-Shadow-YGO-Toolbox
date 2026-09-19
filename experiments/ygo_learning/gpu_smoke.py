"""Validate a real GPU training loop on accepted pilot choices, not duel strength."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback

# AMD documents this per-process workaround for some Radeon training workloads.
os.environ.setdefault('TORCH_BLAS_PREFER_HIPBLASLT', '0')

import numpy as np
import torch
from torch import nn

from student import Student

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local/ygo-learning'
KEYS = ('cards', 'global', 'history', 'actions', 'legal')
SHAPES = ((160, 41), (23,), (32, 14), (24, 12), (24,))


def checked_local(path):
    path = path.resolve()
    if not path.is_relative_to(LOCAL.resolve()):
        raise ValueError('Probe inputs and outputs must remain inside the isolated experiment')
    return path


def load_data(folder):
    path = checked_local(folder) / 'accepted-choices.npz'
    manifest = json.loads(path.with_name('manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['data_sha256']:
        raise ValueError('Dataset hash mismatch')
    if manifest.get('scope') != 'environment_only_overfit_probe_not_strategy_evaluation':
        raise ValueError('Unexpected dataset provenance')
    with np.load(path, allow_pickle=False) as arrays:
        values = []
        count = len(arrays['target'])
        for key, shape in zip(KEYS, SHAPES):
            value = arrays[key]
            if value.shape != (count, *shape):
                raise ValueError(f'Bad shape for {key}: {value.shape}')
            if key == 'legal':
                if value.dtype != np.bool_:
                    raise ValueError('Legal mask must be boolean')
                values.append(torch.from_numpy(value.copy()))
            else:
                if value.dtype != np.uint8:
                    raise ValueError(f'Unexpected feature encoding: {key}')
                values.append(torch.from_numpy(value.copy()).float() / 255.0)
        target = torch.from_numpy(arrays['target'].copy()).long()
    if count < 10 or not ((target >= 0) & (target < 24)).all():
        raise ValueError('Invalid target range or sample count')
    if not values[-1].gather(1, target[:, None]).all() or not (values[-1].sum(1) > 1).all():
        raise ValueError('Every example must label a legal multi-choice decision')
    return tuple(values), target, manifest


def optimizer(model):
    # A larger epsilon prevents round-off in almost-zero gradients from becoming
    # a disproportionately different first update on CPU versus ROCm.
    return torch.optim.AdamW(model.parameters(), lr=0.003, eps=1e-6, weight_decay=0.0001, foreach=False)


def sync(device):
    if device.type == 'cuda':
        torch.cuda.synchronize(device)


def backward(model, opt, inputs, targets):
    opt.zero_grad(set_to_none=True)
    logits = model(*inputs)
    loss = nn.functional.cross_entropy(logits, targets)
    loss.backward()
    finite = [torch.isfinite(loss), *(torch.isfinite(p.grad).all() for p in model.parameters()
                                   if p.requires_grad and p.grad is not None)]
    if any(p.grad is None for p in model.parameters()) or not torch.stack(finite).all().item():
        raise ValueError('Missing or non-finite gradients/loss')
    return loss


def cpu_tree(value):
    if isinstance(value, torch.Tensor):
        return value.detach().cpu().clone()
    if isinstance(value, dict):
        return {k: cpu_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [cpu_tree(v) for v in value]
    if isinstance(value, tuple):
        return tuple(cpu_tree(v) for v in value)
    return value


def metrics(model, inputs, targets):
    with torch.no_grad():
        scores = model(*inputs)
        prediction = scores.argmax(1)
        if not inputs[-1].gather(1, prediction[:, None]).all():
            raise ValueError('Student selected padding/an illegal candidate')
        return {'loss': nn.functional.cross_entropy(scores, targets).item(),
                'accuracy': (prediction == targets).float().mean().item()}


def train(initial, inputs, targets, device, steps):
    model = deepcopy(initial).to(device)
    batch = tuple(x.to(device) for x in inputs)
    labels = targets.to(device)
    opt = optimizer(model)
    before = metrics(model, batch, labels)
    sync(device)
    began = time.perf_counter()
    for step in range(steps):
        backward(model, opt, batch, labels)
        opt.step()
        if (step + 1) % 50 == 0:
            print(f'{device}: {step + 1}/{steps} updates', flush=True)
    sync(device)
    seconds = time.perf_counter() - began
    after = metrics(model, batch, labels)
    changed = sum(not torch.equal(a.detach().cpu(), b.detach().cpu())
                  for a, b in zip(initial.parameters(), model.parameters()))
    if changed == 0 or after['loss'] >= before['loss'] * 0.5 or after['accuracy'] < 0.90:
        raise ValueError(f'Small-data learning check failed: {before} -> {after}, changed={changed}')
    return model, opt, {'before': before, 'after': after, 'steps': steps,
                        'batch_size': len(targets), 'seconds_with_checks': seconds,
                        'updates_per_second_with_checks': steps / seconds,
                        'changed_parameter_tensors': changed}


def inference_timing(model, inputs, device):
    # Includes host->device inputs and device->host selected index for one state.
    durations = []
    for index in range(40):
        row = tuple(x[index % len(x):index % len(x) + 1] for x in inputs)
        sync(device)
        began = time.perf_counter()
        with torch.no_grad():
            model(*(x.to(device) for x in row)).argmax(1).item()
        sync(device)
        elapsed = (time.perf_counter() - began) * 1000
        if index >= 10:
            durations.append(elapsed)
    return {'requests': len(durations), 'median_ms': statistics.median(durations),
            'p95_ms': float(np.percentile(durations, 95)), 'includes_transfers': True}


def verify_export(path, folder):
    inputs, target, _ = load_data(folder)
    # Some native PyTorch archive readers/writers reject Chinese Windows paths.
    program = torch.export.load(io.BytesIO(path.read_bytes()))
    model = program.module()
    with torch.no_grad():
        scores = model(*inputs)
        one = model(*(x[:1] for x in inputs))
    torch.testing.assert_close(one, scores[:1], rtol=0.0001, atol=0.0001)
    if not all(p.device.type == 'cpu' for p in model.parameters()):
        raise ValueError('Export did not load on CPU')
    prediction = scores.argmax(1)
    if not inputs[-1].gather(1, prediction[:, None]).all():
        raise ValueError('CPU export selected an illegal candidate')
    return {'device': 'cpu', 'batch_one_and_full': True,
            'predictions': prediction.tolist(), 'accuracy': (prediction == target).float().mean().item()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--steps', type=int, default=200)
    parser.add_argument('--data', type=Path, default=LOCAL / 'smoke-data')
    parser.add_argument('--verify-export', type=Path)
    args = parser.parse_args()
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.set_float32_matmul_precision('highest')
    if args.verify_export:
        print(json.dumps(verify_export(checked_local(args.verify_export), args.data)))
        return
    if not 100 <= args.steps <= 500:
        raise ValueError('Use 100 to 500 bounded environment-check updates')
    folder = LOCAL / ('student-smoke-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'student_gpu_environment_and_small_data_overfit_only',
              'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'running',
              'architecture': 'byte-field-embedding-v2',
              'limitations': ['not a trained production duel AI', 'no held-out strategic evaluation',
                              'not a conversion or fine-tune of the upstream TFLite checkpoint']}
    report['source_sha256'] = {}
    (folder / 'source').mkdir()
    for name in ('gpu_smoke.py', 'student.py', 'prepare_smoke_data.py', 'requirements-rocm-windows.lock.txt'):
        content = Path(__file__).with_name(name).read_bytes()
        report['source_sha256'][name] = hashlib.sha256(content).hexdigest()
        (folder / 'source' / name).write_bytes(content)
    try:
        if not torch.version.hip or not torch.cuda.is_available():
            raise RuntimeError('An actual ROCm GPU is required; no silent CPU fallback')
        devices = [{'index': i, 'name': torch.cuda.get_device_name(i),
                    'total_memory': torch.cuda.get_device_properties(i).total_memory}
                   for i in range(torch.cuda.device_count())]
        selected = [d for d in devices if '9070 XT' in d['name']]
        if len(selected) != 1:
            raise RuntimeError('Expected exactly one RX 9070 XT; do not train on the integrated GPU')
        device = torch.device('cuda', selected[0]['index'])
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
        report.update(torch=str(torch.__version__), hip=str(torch.version.hip), python=sys.version,
                      devices=devices, selected_device=selected[0], cpu_threads=4,
                      hipblaslt_preference=os.environ['TORCH_BLAS_PREFER_HIPBLASLT'],
                      optimizer={'name': 'AdamW', 'learning_rate': 0.003, 'epsilon': 1e-6,
                                 'weight_decay': 0.0001, 'foreach': False}, seed=19)
        inputs, targets, manifest = load_data(args.data)
        report['data'] = {k: manifest[k] for k in ('data_sha256', 'accepted_windows', 'distinct_multi_choices')}
        torch.manual_seed(19)
        initial = Student()
        report['parameters'] = sum(p.numel() for p in initial.parameters())

        cpu_check, gpu_check = deepcopy(initial), deepcopy(initial).to(device)
        cpu_opt, gpu_opt = optimizer(cpu_check), optimizer(gpu_check)
        gpu_inputs = tuple(x.to(device) for x in inputs)
        gpu_targets = targets.to(device)
        cpu_loss = backward(cpu_check, cpu_opt, inputs, targets)
        gpu_loss = backward(gpu_check, gpu_opt, gpu_inputs, gpu_targets)
        torch.testing.assert_close(cpu_loss, gpu_loss.cpu(), rtol=0.0001, atol=0.00001)
        max_grad_error = 0.0
        for a, b in zip(cpu_check.parameters(), gpu_check.parameters()):
            torch.testing.assert_close(a.grad, b.grad.cpu(), rtol=0.001, atol=0.00002)
            max_grad_error = max(max_grad_error, (a.grad - b.grad.cpu()).abs().max().item())
        cpu_opt.step()
        gpu_opt.step()
        for a, b in zip(cpu_check.parameters(), gpu_check.parameters()):
            torch.testing.assert_close(a, b.cpu(), rtol=0.001, atol=0.0001)
        report['cpu_gpu_first_update'] = {'passed': True, 'max_gradient_absolute_error': max_grad_error}
        del cpu_check, gpu_check, cpu_opt, gpu_opt

        gpu_model, gpu_opt, report['gpu_training'] = train(initial, inputs, targets, device, args.steps)
        cpu_model, _, report['cpu_training'] = train(initial, inputs, targets, torch.device('cpu'), args.steps)
        with torch.no_grad():
            reference = gpu_model(*gpu_inputs).detach().cpu()
        checkpoint = folder / 'student-checkpoint.pt'
        torch.save({'model': cpu_tree(gpu_model.state_dict()), 'optimizer': cpu_tree(gpu_opt.state_dict()),
                    'steps': args.steps, 'data_sha256': manifest['data_sha256']}, checkpoint)
        saved = torch.load(checkpoint, map_location='cpu', weights_only=True)
        restored = Student().to(device)
        restored.load_state_dict(saved['model'])
        restored_opt = optimizer(restored)
        restored_opt.load_state_dict(saved['optimizer'])
        backward(gpu_model, gpu_opt, gpu_inputs, gpu_targets)
        gpu_opt.step()
        backward(restored, restored_opt, gpu_inputs, gpu_targets)
        restored_opt.step()
        for a, b in zip(gpu_model.parameters(), restored.parameters()):
            torch.testing.assert_close(a, b, rtol=0.0001, atol=0.00001)
        report['checkpoint_resume'] = {'passed': True, 'extra_verified_update': 1}

        deploy = Student().eval()
        deploy.load_state_dict(saved['model'])
        with torch.no_grad():
            scores = deploy(*inputs)
        torch.testing.assert_close(reference, scores, rtol=0.0001, atol=0.0001)
        if not torch.equal(reference.argmax(1), scores.argmax(1)):
            raise ValueError('CPU restore changed action rankings')
        batch_dim = torch.export.Dim('batch', min=1, max=1024)
        exported = torch.export.export(deploy, tuple(x[:2] for x in inputs),
                                       dynamic_shapes=tuple({0: batch_dim} for _ in inputs))
        export_path = folder / 'student-cpu.pt2'
        archive = io.BytesIO()
        torch.export.save(exported, archive)
        export_path.write_bytes(archive.getvalue())
        child_env = {**os.environ, 'HIP_VISIBLE_DEVICES': '-1', 'PYTHONIOENCODING': 'utf-8'}
        checked = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--verify-export',
                                  str(export_path), '--data', str(args.data)],
                                 capture_output=True, text=True, encoding='utf-8', timeout=60, env=child_env)
        (folder / 'export-check.stderr.txt').write_text(checked.stderr, encoding='utf-8')
        if checked.returncode:
            raise RuntimeError(f'Fresh CPU export check failed: {checked.stderr[-2000:]}')
        export_result = json.loads(checked.stdout)
        if export_result.pop('predictions') != reference.argmax(1).tolist():
            raise ValueError('Fresh CPU export changed action rankings')
        report['cpu_export'] = {**export_result, 'passed': True, 'fresh_process': True}
        deploy_gpu = deepcopy(deploy).to(device).eval()
        report['cpu_inference'] = inference_timing(deploy, inputs, torch.device('cpu'))
        report['gpu_inference'] = inference_timing(deploy_gpu, inputs, device)
        report['gpu_peak_allocated_bytes'] = torch.cuda.max_memory_allocated(device)
        report['gpu_peak_reserved_bytes'] = torch.cuda.max_memory_reserved(device)
        if report['gpu_peak_reserved_bytes'] > 10 * 1024 ** 3:
            raise ValueError('Experiment exceeded the GPU memory budget')
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
        raise
    finally:
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Evidence:', folder, flush=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
