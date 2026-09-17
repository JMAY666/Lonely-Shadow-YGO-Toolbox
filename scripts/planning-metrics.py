"""Test-only sampler for a hidden acceptance service and its owned engines."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

root, output = map(Path, sys.argv[1:3])
assert 'desktop-check-' in str(root.resolve()) and '.local' in str(output.resolve())
output.with_suffix('.stop').unlink(missing_ok=True)  # Previous run's sampler stop marker only.
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
psapi = ctypes.WinDLL('psapi', use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)]*4)]


class Memory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD),
                *[(name, ctypes.c_size_t) for name in ('peak', 'working', 'paged_peak', 'paged', 'nonpaged_peak', 'nonpaged', 'pagefile', 'pagefile_peak')]]


psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
handles, times, peaks = {}, {}, []
started = time.monotonic()
try:
    while time.monotonic()-started < 600 and not output.with_suffix('.stop').exists():
        pids = set()
        service = root/'runtime/_trainer/service.json'
        if service.exists(): pids.add(json.loads(service.read_text('utf8'))['pid'])
        for path in (root/'runtime/_trainer/sessions').glob('*/session.json'):
            try:
                meta = json.loads(path.read_text('utf8'))
                if meta.get('purpose') == 'duel_planning' and meta.get('status') == 'running': pids.add(meta['pid'])
            except (OSError, ValueError): pass
        working = 0
        for pid in pids:
            handle = handles.setdefault(pid, kernel.OpenProcess(0x410, False, pid)) if pid not in handles else handles[pid]
            if not handle: continue
            fields = [wintypes.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(handle, *map(ctypes.byref, fields)):
                cpu = sum((f.dwHighDateTime << 32)+f.dwLowDateTime for f in fields[2:])/1e7
                times.setdefault(pid, [cpu, cpu])[1] = cpu
            memory = Memory(); memory.cb = ctypes.sizeof(memory)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb): working += memory.working
        peaks.append(working)
        time.sleep(.5)
finally:
    for handle in handles.values():
        if handle: kernel.CloseHandle(handle)
    output.write_text(json.dumps({'seconds': round(time.monotonic()-started,3),
        'service_engine_cpu_seconds': round(sum(b-a for a,b in times.values()),3),
        'service_engine_peak_working_mb': round(max(peaks, default=0)/1048576,2), 'samples': len(peaks)},indent=2),encoding='utf8')
