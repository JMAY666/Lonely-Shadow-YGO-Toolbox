"""Old pinned TFLite, only for fresh-window timing; no committed duel policy."""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.ygo_agent.policy import Policy


def main():
    began=time.perf_counter();policy=Policy()
    print(json.dumps({'ready':True,'load_ms':(time.perf_counter()-began)*1000,'threads':2}),flush=True)
    for line in sys.stdin:
        request=json.loads(line)
        if request.get('op')=='stop':break
        try:
            policy.rstate=policy.features.init_rstate();policy.history=policy.features.HistoryActions();policy.pending=None
            began=time.perf_counter();rankings=policy._step(request['input'])
            print(json.dumps({'id':request['id'],'rankings':rankings,
                              'features_and_model_ms':(time.perf_counter()-began)*1000}),flush=True)
        except Exception as error:
            print(json.dumps({'id':request['id'],'error':str(error)}),flush=True)


if __name__=='__main__':main()
