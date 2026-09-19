"""Bounded IPC and version checks around the isolated CPU student process."""
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
from provenance import code_identity

ROOT=Path(__file__).resolve().parents[2]


class JsonWorker:
    def __init__(self, python, script, arguments, log):
        self.errors=Path(log).open('w',encoding='utf-8')
        try:
            self.process=subprocess.Popen([str(python),'-u',str(script),*arguments],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.errors,text=True,encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except Exception:
            self.errors.close();raise
        self.queue=queue.Queue()
        def reader():
            for line in self.process.stdout:self.queue.put(line)
            self.queue.put(None)
        threading.Thread(target=reader,daemon=True).start()
        try:
            self.ready=self.read(60)
            if self.ready.get('ready') is not True:raise RuntimeError('policy worker did not initialize')
        except Exception:
            self.close();raise

    def read(self, timeout):
        line=self.queue.get(timeout=timeout)
        if line is None:raise RuntimeError('student worker exited')
        return json.loads(line)

    def call(self, request):
        identifier=uuid.uuid4().hex
        started=time.perf_counter()
        self.process.stdin.write(json.dumps({'id':identifier,**request})+'\n')
        self.process.stdin.flush()
        result=self.read(30)
        if result.get('id')!=identifier or result.get('error'):raise RuntimeError(str(result))
        result['ipc_and_model_ms']=(time.perf_counter()-started)*1000
        return result

    def close(self):
        if self.process.poll() is None:
            try:self.process.stdin.write('{"op":"stop"}\n');self.process.stdin.flush()
            except (BrokenPipeError,OSError):pass
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=5)
        self.errors.close()


class PolicyClient(JsonWorker):
    def __init__(self, folder, log):
        self.folder=Path(folder).resolve()
        local=(ROOT/'.local/ygo-learning').resolve()
        if not self.folder.is_relative_to(local):raise ValueError('model is outside the isolated experiment')
        self.manifest=json.loads((self.folder/'model.json').read_text(encoding='utf-8'))
        if self.manifest.get('schema')!=2 or self.manifest.get('status')!='passed':raise ValueError('unsupported model package')
        if self.manifest.get('code')!=code_identity():raise ValueError('model/contract code mismatch')
        super().__init__(local/'.venv/Scripts/python.exe',Path(__file__).with_name('policy_worker.py'),[str(self.folder)],log)

    def predict(self, features, threads=4):
        encoded={key:{'dtype':str(value.dtype),'shape':list(value.shape),
                      'data':base64.b64encode(value.tobytes()).decode('ascii')} for key,value in features.items()}
        return self.call({'features':encoded,'threads':threads})


class LegacyClient(JsonWorker):
    def __init__(self, log):
        super().__init__(ROOT/'.local/ygo-agent-pilot/.venv/Scripts/python.exe',
                         Path(__file__).with_name('legacy_worker.py'),[],log)

    def predict(self, public_input):return self.call({'input':public_input})
