"""Compare one isolated hidden engine with two, using the same five recipes."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time
from native_session import ROOT,BASE


def run_batch(folder,label,parallel):
    before=set(BASE.glob('throughput-*/summary.json'));children=[];logs=[]
    began=time.perf_counter()
    try:
        for index in range(parallel):
            log=(folder/f'{label}-{index+1}.log').open('w',encoding='utf-8');logs.append(log)
            arguments=['node',str(ROOT/'experiments/ygo_learning/desktop_p1.cjs'),'--suite=throughput']
            if index:arguments.append('--secondary')
            children.append(subprocess.Popen(arguments,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        for child in children:
            code=child.wait(timeout=max(1,300-(time.perf_counter()-began)))
            if code:raise ValueError(f'{label} child exited {code}')
    finally:
        for child in children:
            if child.poll() is None:child.terminate();child.wait(timeout=10)
        for log in logs:log.close()
    paths=sorted(set(BASE.glob('throughput-*/summary.json'))-before)
    if len(paths)!=parallel:raise ValueError('Missing/ambiguous throughput evidence')
    results=[json.loads(path.read_text(encoding='utf-8')) for path in paths]
    if len({r['profile'] for r in results})!=parallel:raise ValueError('Shared runtime profile detected')
    if any(r['status']!='passed' or len(r['cases'])!=5 for r in results):raise ValueError('Throughput case failed')
    overlap_seconds=max(r['case_finished_at'] for r in results)-min(r['case_started_at'] for r in results)
    intervals=[]
    for path,result in zip(paths,results):
        own=[]
        for case in result['cases']:
            record=json.loads((path.parent/(case['case']+'.json')).read_text(encoding='utf-8'))
            journal=Path(record['session']['folder'])/'native.jsonl'
            with journal.open('rb') as stream:
                first=json.loads(stream.readline());stream.seek(max(0,journal.stat().st_size-16384))
                last=json.loads(stream.read().splitlines()[-1])
            if last.get('kind')!='end':raise ValueError('Native benchmark did not stop')
            own.append((first['time_ms']/1000,last['time_ms']/1000))
        intervals.append(own)
    native_overlap=sum(max(0,min(a[1],b[1])-max(a[0],b[0])) for a in intervals[0] for b in intervals[1]) if parallel==2 else 0
    return {'label':label,'hidden_engines':parallel,'cases':parallel*5,'wall_seconds':time.perf_counter()-began,
            'cases_per_second':parallel*5/(time.perf_counter()-began),
            'case_interval_seconds':overlap_seconds,'active_cases_per_second':parallel*5/overlap_seconds,
            'simultaneous_native_seconds':native_overlap,
            'summaries':[str(path) for path in paths],'results':results}


def main():
    output=BASE/('parallel-check-'+datetime.now().strftime('%Y%m%d-%H%M%S'));output.mkdir()
    report={'scope':'five_fixed_engine_recipes_not_teacher_search','status':'running'}
    try:
        report['single']=run_batch(output,'single',1);print('PASS single hidden engine',flush=True)
        report['pair']=run_batch(output,'pair',2);print('PASS two isolated hidden engines',flush=True)
        if report['pair']['simultaneous_native_seconds']<=0:
            report['cold_preparation_pair']=report['pair']
            report['pair']=run_batch(output,'pair-warm',2)
        if report['pair']['simultaneous_native_seconds']<=0:raise ValueError('No simultaneous native workload observed')
        report['rate_ratio']=report['pair']['cases_per_second']/report['single']['cases_per_second']
        report['active_rate_ratio']=report['pair']['active_cases_per_second']/report['single']['active_cases_per_second']
        report['status']='passed'
    finally:
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Parallel evidence:',output,flush=True)


if __name__=='__main__':main()
