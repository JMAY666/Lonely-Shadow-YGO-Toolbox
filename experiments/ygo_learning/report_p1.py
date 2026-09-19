"""Audit the fixed experiment evidence and aggregate costs without quality claims."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
import numpy as np
from native_session import BASE,ROOT
from journal_audit import audit
from provenance import sha256
from budget import folder_bytes
sys.path.insert(0,str(ROOT/'src/trainer'))
from modular_decisions import canonical_state


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def stats(values):
    return {'n':len(values),'mean':float(np.mean(values)),'p50':float(np.percentile(values,50)),
            'p95':float(np.percentile(values,95)),'max':float(max(values))} if values else {'n':0}


def evidence(path):
    path=Path(path).resolve()
    if not path.is_relative_to(BASE.resolve()):raise ValueError('evidence outside isolated root')
    record=read(path);checked=audit(record)
    folder=Path(record['session']['folder'])
    final=record.get('final') or read(folder/'modular-state.json')
    replay=read(folder/'modular-result.json')
    if replay.get('status')!='ok' or replay.get('version')!=final['version']:
        raise ValueError('Missing final full replay: '+path.name)
    if not replay.get('boundary_raw','').endswith(final['raw']):raise ValueError('Replayed decision prompt differs')
    if canonical_state(replay['state'])!=canonical_state(final['state']) or replay['learning']!=final['learning']:
        raise ValueError('Replayed state or dynamic resources differ')
    return record,{'file':path.relative_to(ROOT).as_posix(),'sha256':sha256(path),
                   'final_prompt_and_state_replay':True,**checked}


def engine_accounting():
    seconds=[];incomplete=[]
    for root in BASE.glob('desktop-check-development-modular*/runtime/_trainer/sessions'):
        for path in root.glob('*/native.jsonl'):
            with path.open('rb') as stream:
                first=json.loads(stream.readline())
                stream.seek(max(0,path.stat().st_size-16384));lines=stream.read().splitlines()
            last=json.loads(lines[-1])
            if last.get('kind')=='end':seconds.append((last['time_ms']-first['time_ms'])/1000)
            else:incomplete.append(path.parent.name)
    return {'finished_sessions':len(seconds),'sum_native_session_seconds_including_failed_attempts_and_debug_waits':sum(seconds),
            'incomplete_session_ids':incomplete,'parallel_sessions_sum_time_not_wall_time':True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mechanisms',nargs='+',required=True)
    for arg in ('development','demonstrations','model','worker','parallel'):parser.add_argument('--'+arg,required=True)
    args=parser.parse_args();output=BASE/('report-'+datetime.now().strftime('%Y%m%d-%H%M%S'));output.mkdir()
    report={'scope':'P0B_P1_engineering_only','status':'running'}
    try:
        mechanisms={};source_checks=[];coverage=Counter()
        for folder in args.mechanisms:
            for path in sorted(Path(folder).glob('*.json')):
                if path.name in ('summary.json','failure.json','session.json'):continue
                record,checked=evidence(path)
                if record['case'] in mechanisms:raise ValueError('Duplicate mechanism fixture')
                if record['status']!='passed':raise ValueError('Mechanism result failed')
                mechanisms[record['case']]=record['assertions'];source_checks.append(checked)
        groups=('duplicates','costs','chains','negation','limits','dynamic','random','zones','choices','stale','replay','privacy')
        if set(mechanisms)!={f'{group}-{i}' for group in groups for i in range(1,6)}:raise ValueError('The 60 mechanism cases are incomplete')
        demos=[]
        for path in sorted(Path(args.demonstrations).glob('demo-*.json')):
            record,checked=evidence(path);demos.append(record['case']);source_checks.append(checked)
        if len(demos)!=5:raise ValueError('The five controlled demonstrations are incomplete')
        dev=Path(args.development);records=[]
        for path in sorted(dev.glob('case-*.json')):
            record,checked=evidence(path);records.append(record);source_checks.append(checked)
            coverage.update({int(k):v for k,v in checked['own_prompt_coverage'].items()})
        if len(records)!=50 or read(dev/'summary.json')['status']!='passed':raise ValueError('Development execution gate failed')
        manifest=read(dev/'manifest.json')
        hands={tuple(sorted(hand)) for hand in manifest['hands']}
        if len(hands)!=50 or hands & {tuple(hand) for hand in manifest['excluded_hands']}:raise ValueError('Opening split contamination')
        for record in records:
            actual=sorted(c['code'] for c in record['initial']['state']['cards'] if c['controller']==0 and c['location']==2)
            if actual!=sorted(record['hand']) or actual!=sorted(manifest['hands'][record['case']-1]):
                raise ValueError('Actual engine opening differs from the frozen requested hand')
        training=read(Path(args.model)/'training-report.json');worker=read(Path(args.worker)/'report.json')
        parallel=read(Path(args.parallel)/'report.json')
        if any(r['status']!='passed' for r in (training,worker,parallel)):raise ValueError('A prerequisite check failed')
        windows=read(dev/'runtime-profile.json')['windows']
        if len(windows)!=30 or any('legacy_error' in window for window in windows):raise ValueError('Thirty common timing windows are required')
        step_times=[step['timings'] for record in records for step in record['steps']]
        timing={key:stats([step[key] for step in step_times]) for key in
                ('read_ms','features_ms','learning_query_ms','selected_branch_replay_ms')}
        timing['student_model_ms']=stats([step['model_ms'] for step in step_times if step['model_ms']])
        timing['engine_ack_and_settlement_ms']=stats([step['acknowledgement']['wall_seconds']*1000 for record in records for step in record['steps']])
        timing['full_prefix_replay_ms']=stats([record['full_replay_ms'] for record in records])
        timing['family_seconds']=stats([record['seconds'] for record in records])
        comparisons={key:{metric:stats([window[key][metric] for window in windows]) for metric in
                    ('observation_features_ms','ipc_and_model_ms','window_to_response_ms')} for key in ('student_2','student_4','legacy_2')}
        for key in ('student_2','student_4'):comparisons[key]['model_ms']=stats([window[key]['model_ms'] for window in windows])
        directory_stat=dev.stat()
        batch_seconds=(dev/'summary.json').stat().st_mtime-getattr(directory_stat,'st_birthtime',directory_stat.st_ctime)
        # Windows st_ctime is creation time. Individual family measurements are
        # the portable denominator; batch duration is additional local evidence.
        mean=max(timing['family_seconds']['mean'],batch_seconds/50)
        p95=max(timing['family_seconds']['p95'],mean)
        budget={str(n):{'observed_family_mean_hours':mean*n/3600,
                       'two_attempts_per_family_at_p95_hours':2*p95*n/3600} for n in (200,2000)}
        storage=stats([folder_bytes(Path(record['session']['folder']))+(dev/f'case-{record["case"]:02}.json').stat().st_size for record in records])
        for count in (200,2000):
            budget[str(count)]['storage_attempts_per_family']=1
            budget[str(count)]['uncompressed_evidence_GiB_at_observed_mean']=storage['mean']*count/1024**3
            budget[str(count)]['uncompressed_evidence_GiB_at_p95']=storage['p95']*count/1024**3
        board_counts=[]
        for record in records:
            own=[record['initial'],*(step['after'] for step in record['steps'] if step['after']['state']['turn']==1)]
            state=own[-1]['state'];board_counts.append(sum(c['controller']==0 and c['location']==4 for c in state['cards']))
        report.update(status='passed',mechanism_cases=60,controlled_demonstrations=5,development_cases=50,
            status_counts=dict(Counter(record['status'] for record in records)),
            accepted_student_responses=sum(len(record['steps']) for record in records),
            student_model_calls=sum(record['model_calls'] for record in records),
            single_choice_bypasses=sum(record['single_choice_bypasses'] for record in records),
            native_answered_windows=sum(check['native_answered_windows'] for check in source_checks[-50:]),
            automatic_empty_chains=sum(check['automatic_empty_chains'] for check in source_checks[-50:]),
            own_prompt_coverage=dict(sorted(coverage.items())),source_checks=source_checks,
            model={key:training[key] for key in ('samples','parameters','training_accuracy','initial_loss','final_loss','gpu_training_seconds','device','export_sha256')},
            runtime=manifest['runtime'],worker_checks=worker['checks'],resources=read(dev/'summary.json')['resources'],
            family_monster_count_diagnostic=stats(board_counts),
            same_window_comparison=comparisons,timing=timing,hidden_app_worker_batch_seconds=batch_seconds,
            cold_student_process_ms=manifest['cold_student_process_ms'],cold_legacy_process_ms=manifest['cold_legacy_process_ms'],
            parallel=parallel,budget=budget,per_family_uncompressed_evidence_bytes=storage,engine_accounting=engine_accounting(),
            budget_caveats=['Teacher search and LLM cost are not measured or included.',
                'Two attempts per family is an explicit planning assumption, not a measured retry probability.',
                'All 50 execution outcomes including cycle stops remain in the timing denominator.',
                'Storage estimates use one retained record per family; two attempts double this storage.',
                'The hidden renderer is retained; this does not measure headless-core throughput.'],
            unverified=['T0/T1 teacher quality','held-out strategy benefit','new-card update and regression','production integration'])
    except Exception as error:report.update(status='failed',error=str(error));raise
    finally:
        (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Final evidence:',output,'status:',report['status'],flush=True)


if __name__=='__main__':main()
