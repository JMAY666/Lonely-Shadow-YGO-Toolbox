"""Bounded local resource checks for the known isolated Windows processes."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import time
from native_session import ROOT


def folder_bytes(root):
    total=0;pending=[str(root)]
    while pending:
        folder=pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_symlink() or os.path.isjunction(entry.path):
                    raise ValueError('Experiment size check refuses directory links')
                if entry.is_dir(follow_symlinks=False):pending.append(entry.path)
                else:total+=entry.stat(follow_symlinks=False).st_size
    return total


def working_bytes(pids):
    class Memory(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),
                  *[(name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage',
                    'QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD]
    total=0
    for pid in set(pids):
        handle=kernel.OpenProcess(0x410,False,pid)
        if not handle:continue  # Short-lived helpers may have exited.
        try:
            value=Memory();value.cb=ctypes.sizeof(value)
            if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(value),value.cb):raise OSError('Cannot sample isolated process memory')
            total+=value.WorkingSetSize
        finally:kernel.CloseHandle(handle)
    return total


class Budget:
    def __init__(self,session,worker_pids):
        self.session=session;self.worker_pids=worker_pids;self.started=time.monotonic();self.peak=0
        self.disk_peak=0;self.check(disk=True)

    def check(self,disk=False):
        if time.monotonic()-self.started>1800:raise ValueError('batch_30_minute_budget')
        path=self.session.runtime.parent/'learning-processes.json'
        info=None
        for _ in range(3):
            try:info=json.loads(path.read_text(encoding='utf-8'));break
            except json.JSONDecodeError:time.sleep(.01)
        if not info or time.time()*1000-info['time']>10000:raise ValueError('resource_monitor_stale')
        pids=info['pids']+self.worker_pids+[os.getpid()]
        if self.session.sid:
            native=self.session.read('native-window.json')
            if native:pids.append(native['pid'])
        memory=working_bytes(pids);self.peak=max(memory,self.peak)
        if memory>8*1024**3:raise ValueError('batch_8_GiB_memory_budget')
        if disk:
            size=folder_bytes(ROOT/'.local/ygo-learning');self.disk_peak=max(size,self.disk_peak)
            if size>20*1024**3:raise ValueError('experiment_20_GiB_disk_budget')
        return {'sampled_working_bytes':memory,'peak_sampled_working_bytes':self.peak,'checked_disk_bytes':self.disk_peak}
