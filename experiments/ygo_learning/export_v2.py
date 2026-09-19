"""Re-encode confirmed development demonstrations; never read evaluation runs."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from native_session import ROOT,BASE
from contract_v2 import build,feature_arrays,committed_history
sys.path.insert(0,str(ROOT/'src/trainer'))
from app import Catalog
from modular_decisions import model,semantic_response
from provenance import runtime_identity,code_identity


def main():
    runtime=BASE/'desktop-check-development-modular/runtime'
    catalog=Catalog(runtime).cards
    rows=[];sources=[];case_hands=[];seen={};observed_decisions=0;codes=set()
    for arg in sys.argv[1:]:
        folder=Path(arg).resolve()
        if not folder.is_relative_to(BASE.resolve()) or folder.name.startswith('development'):
            raise ValueError('Only isolated gold/demonstration sources may train the development student')
        for path in sorted(folder.glob('*.json')):
            if path.name in ('summary.json','failure.json','session.json','manifest.json'):continue
            record=json.loads(path.read_text(encoding='utf-8'))
            if record.get('status')!='passed' or not record.get('steps'):continue
            history=[]
            case_hands.append(sorted(c['code'] for c in record['steps'][0]['before']['state']['cards'] if c['controller']==0 and c['location']==2))
            sources.append({'file':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            for step in record['steps']:
                before=step['before'];bundle=build(before,catalog);features=feature_arrays(bundle,history)
                codes.update(c['code'] for c in bundle['observation']['cards'] if c['identity_known'])
                options=bundle['candidates'];indexes=[i for i,c in enumerate(options) if step['response'] in c['responses']]
                if not indexes:
                    prompt=model(before['raw'],before['state'],before.get('effects'))
                    key=lambda raw:json.dumps(sorted(semantic_response(prompt,raw).get('selection',[]),key=lambda r:json.dumps(r,sort_keys=True)),sort_keys=True)
                    indexes=[i for i,c in enumerate(options) if key(c['response'])==key(step['response'])]
                if len(indexes)!=1:raise ValueError('Gold response cannot be represented uniquely')
                index=indexes[0]
                if len(options)>1:
                    observed_decisions+=1
                    fingerprint=hashlib.sha256(b''.join(features[k].tobytes() for k in sorted(features))).hexdigest()
                    if fingerprint not in seen:
                        acceptable=np.zeros(64,dtype=np.bool_);acceptable[index]=True
                        seen[fingerprint]=len(rows)
                        rows.append({**features,'target':np.int64(index),'acceptable':acceptable})
                    else:
                        rows[seen[fingerprint]]['acceptable'][index]=True
                history.append(committed_history(features,index,bundle['observation']))
    if not rows:raise ValueError('No confirmed development decisions')
    output=BASE/('data-v2-'+datetime.now().strftime('%Y%m%d-%H%M%S'));output.mkdir()
    np.savez_compressed(output/'data.npz',**{k:np.stack([r[k] for r in rows]) for k in rows[0]})
    manifest={'schema':2,'scope':'development_only_not_formal_dataset','decisions':len(rows),
              'observed_decisions':observed_decisions,'multiple_observed_choices':int(sum(r['acceptable'].sum()>1 for r in rows)),
              'label_meaning':'observed development choices, not claims of strategic optimality',
              'source_files':sources,'source_hands':case_hands,
              'encoded_codes':sorted(codes),'runtime':runtime_identity(runtime),'code':code_identity(),
              'contract_sha256':hashlib.sha256(Path(__file__).with_name('contract_v2.py').read_bytes()).hexdigest(),
              'data_sha256':hashlib.sha256((output/'data.npz').read_bytes()).hexdigest()}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'data':str(output/'data.npz'),'decisions':len(rows)},ensure_ascii=False))


if __name__=='__main__':main()
