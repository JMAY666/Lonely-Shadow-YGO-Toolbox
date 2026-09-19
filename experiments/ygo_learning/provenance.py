"""Hash the executable rule inputs and versioned learning contract, not user data."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_identity():
    paths=['experiments/ygo_learning/'+name for name in
           ('contract_v2.py','student_v2.py','student.py','policy_worker.py','policy_client.py')]
    paths+=['src/trainer/modular_decisions.py']
    return {path:sha256(ROOT/path) for path in paths}


def runtime_identity(runtime):
    runtime=Path(runtime)
    manifest=json.loads((runtime/'.desktop-resources.json').read_text(encoding='utf-8'))
    expected={path:record for path,record in manifest['files'].items()
              if path.startswith('script/') or path in ('cards.cdb','lflist.conf','strings.conf','YGOPro.exe')}
    scripts={p.relative_to(runtime).as_posix() for p in (runtime/'script').rglob('*') if p.is_file()}
    if scripts!={p for p in expected if p.startswith('script/')}:
        raise ValueError('Rule script set differs from the frozen runtime')
    actual={}
    for path,record in sorted(expected.items()):
        file=runtime/path
        if file.stat().st_size!=record['size'] or sha256(file)!=record['sha256']:
            raise ValueError('Rule resource hash mismatch: '+path)
        actual[path]=record['sha256']
    return {'bundle_version':manifest['version'],'rules_sha256':hashlib.sha256(
                json.dumps(actual,sort_keys=True).encode()).hexdigest(),
            'rules_files':len(actual),'rules_mode':'free_practice_not_tournament_banlist'}
