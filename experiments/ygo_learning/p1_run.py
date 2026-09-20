"""P0B/P1 bounded real-engine experiments; unfinished suites fail explicitly."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import traceback

from native_session import NativeSession, BASE, ROOT
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src/trainer'))
from modular_decisions import model, canonical_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--url', required=True)
    parser.add_argument('--suite', choices=['probe','mechanisms','demonstrations','development','throughput','teacher'], default='probe')
    parser.add_argument('--model')
    parser.add_argument('--count',type=int,choices=range(1,51),default=50)
    parser.add_argument('--protocol', default=str(ROOT/'.local/ygo-learning/p2-p3/protocol.json'))
    parser.add_argument('--first-family', type=int, choices=range(1,21), default=1)
    parser.add_argument('--groups', default='')
    parser.add_argument('--variants',type=int,choices=range(1,6),default=5)
    parser.add_argument('--first-variant',type=int,choices=range(1,6),default=1)
    args = parser.parse_args()
    if args.first_variant>args.variants:parser.error('--first-variant must not exceed --variants')
    session = NativeSession(args.runtime, args.url)
    suffix='-secondary' if 'secondary' in Path(args.runtime).parent.name else ''
    output_base = ROOT/'.local/ygo-learning/p2-p3' if args.suite=='teacher' else BASE
    output = output_base / (args.suite+suffix+'-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True, exist_ok=False)
    try:
        if args.suite=='teacher':
            from app import Catalog
            from calibration_p3 import run
            run(session, Catalog(Path(args.runtime)).cards, output, args.protocol,
                args.first_family, min(args.count,20))
            return
        if args.suite=='throughput':
            from app import Catalog
            from mechanisms import run
            from provenance import runtime_identity
            import time
            started=time.perf_counter();wall_started=time.time()
            results=run(session,Catalog(Path(args.runtime)).cards,output,groups=['replay'],variants=5)
            (output/'summary.json').write_text(json.dumps({'status':'passed','cases':results,
                'case_seconds':time.perf_counter()-started,'runtime':runtime_identity(Path(args.runtime)),
                'case_started_at':wall_started,'case_finished_at':time.time(),
                'profile':str(Path(args.runtime).parent)},ensure_ascii=False,indent=2),encoding='utf-8')
            return
        if args.suite=='development':
            if not args.model:raise ValueError('The frozen v2 student package is required')
            from app import Catalog
            from development import run
            report=run(session,Catalog(Path(args.runtime)).cards,output,args.model,args.count)
            if report['status']!='passed':raise ValueError('Development execution gate failed; inspect the preserved summary')
            return
        if args.suite in ('mechanisms','demonstrations'):
            from app import Catalog
            from mechanisms import run,demonstrations
            if args.suite=='mechanisms':
                results=run(session,Catalog(Path(args.runtime)).cards,output,
                            groups=args.groups.split(',') if args.groups else None,variants=args.variants,first_variant=args.first_variant)
            else:results=demonstrations(session,Catalog(Path(args.runtime)).cards,output)
            (output/'summary.json').write_text(json.dumps({'status':'passed','cases':results},ensure_ascii=False,indent=2),encoding='utf-8')
            return
        normal = 1184620
        state = session.start({'main':[normal]*40,'extra':[],'side':[]}, [normal]*5, 'initial observer')
        probe = session.probe(state)
        if probe['status'] != 'ok':
            raise ValueError(probe)
        assert canonical_state(probe['state']) == canonical_state(state['state'])
        assert probe['learning'] == state['learning']
        prompt = model(state['raw'], state['state'], state['effects'])
        chosen = next(c for c in prompt['choices'] if c['semantic']['kind']=='summon')
        following = session.answer(state, chosen['response'])
        (output/'initial.json').write_text(json.dumps(state, ensure_ascii=False, indent=2),encoding='utf-8')
        (output/'replay.json').write_text(json.dumps(probe, ensure_ascii=False, indent=2),encoding='utf-8')
        (output/'following.json').write_text(json.dumps(following, ensure_ascii=False, indent=2),encoding='utf-8')
        print('PASS dynamic snapshot, zero-step complete engine replay and exact action acknowledgement')
    except Exception as error:
        harness=getattr(session,'active_harness',None)
        (output/'failure.json').write_text(json.dumps({'error':str(error),'traceback':traceback.format_exc(),
            'case':harness.case if harness else None,'steps':harness.steps if harness else [],
            'passed_cases':harness.results if harness else []},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    finally:
        finished = session.finish()
        if finished:(output/'session.json').write_text(json.dumps(finished,ensure_ascii=False),encoding='utf-8')
        print('Evidence:', output)


if __name__ == '__main__':main()
