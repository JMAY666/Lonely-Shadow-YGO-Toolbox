"""Fifty held-apart development openings: execution audit, never a win-rate test."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import random
import time

import numpy as np
from native_session import ROOT,BASE
from contract_v2 import build,feature_arrays,digest,Unsupported
from confirmed_history import ConfirmedHistory
from provenance import runtime_identity,code_identity,sha256
from policy_client import PolicyClient,LegacyClient
from mechanisms import NORMAL,ASH,deck
from modular_decisions import canonical_state
from journal_audit import audit
from budget import Budget


def summary(values):
    return {'n':len(values),'p50':float(np.percentile(values,50)),
            'p95':float(np.percentile(values,95)),'max':max(values)} if values else {'n':0}


def fresh_hands(public,manifest,count):
    excluded={tuple(sorted(hand)) for hand in manifest['source_hands']}
    # The three original POC games used these two opening multisets.
    excluded.update({tuple(sorted(h)) for h in ([20001443,93490856,23431858,14558127,10045474],
                                                [20001443,23431858,14558127,97268402,10045474])})
    for previous in BASE.glob('development-*/manifest.json'):
        prior=json.loads(previous.read_text(encoding='utf-8'))
        excluded.update(tuple(sorted(hand)) for hand in prior.get('hands',[]))
    rng=random.Random(190927);hands=[];seen=set(excluded)
    while len(hands)<count:
        hand=rng.sample(public['main'],5);key=tuple(sorted(hand))
        if key not in seen:hands.append(hand);seen.add(key)
    return hands,sorted(excluded)


def profile_window(state,catalog,student,legacy,warm=False):
    from experiments.ygo_agent.adapter import NativeInput
    timings={}
    for threads in (2,4):
        began=time.perf_counter();bundle=build(state,catalog)
        features=feature_arrays(bundle,supported_codes=set(student.manifest['encoded_codes']))
        encode=(time.perf_counter()-began)*1000
        if warm:
            for _ in range(5):student.predict(features,threads)
        result=student.predict(features,threads)
        timings[f'student_{threads}']={**result,'observation_features_ms':encode,
                                      'window_to_response_ms':encode+result['ipc_and_model_ms']}
    try:
        began=time.perf_counter();native=NativeInput(state,catalog);public=native.input()
        encode=(time.perf_counter()-began)*1000
        if native.prompt['mode']!='single':raise ValueError('legacy timing requires a single fresh window')
        if warm:
            for _ in range(5):legacy.predict(public)
        result=legacy.predict(public)
        response=native.response(result['rankings'][0],[])
        if response not in {r for c in bundle['candidates'] for r in c['responses']}:
            raise ValueError('legacy response is outside the v2 legal candidates')
        timings['legacy_2']={**result,'observation_features_ms':encode,
                            'window_to_response_ms':encode+result['ipc_and_model_ms']}
    except Exception as error:timings['legacy_error']=str(error)
    return timings


def run(session,catalog,output,model_folder,count=50):
    from experiments.ygo_agent.run import read_deck
    output=Path(output);student=legacy=None
    began=time.perf_counter();identity=runtime_identity(session.runtime)
    resource_check_ms=(time.perf_counter()-began)*1000
    results=[];profiling=[];code=code_identity()
    runner_sources={p.name:sha256(p) for p in Path(__file__).parent.glob('*.py')}
    try:
        started=time.perf_counter();student=PolicyClient(model_folder,output/'student-stderr.log')
        cold_student_ms=(time.perf_counter()-started)*1000
        if identity!=student.manifest['runtime']:raise ValueError('model/rules mismatch')
        started=time.perf_counter();legacy=LegacyClient(output/'legacy-stderr.log')
        cold_legacy_ms=(time.perf_counter()-started)*1000
        budget=Budget(session,[student.process.pid,legacy.process.pid])
        public=read_deck(ROOT/'.local/ygo-agent-pilot/TenyiSword.ydk')
        hands,excluded=fresh_hands(public,student.manifest,count)
        manifest={'scope':'P1_development_only_no_generalization_claim','count':count,'hands':hands,
                  'excluded_hands':excluded,'deck':public,'runtime':identity,'code':code,'runner_sources':runner_sources,
                  'model_manifest_sha256':sha256(Path(model_folder)/'model.json'),'model':str(model_folder),
                  'seed_for_hand_sampling':190927,'native_seeds':'saved_in_each_test_only_session',
                  'teacher_fallback':False,'limits':{'decisions':120,'seconds':180,'same_state_visits':3},
                  'cold_student_process_ms':cold_student_ms,'cold_legacy_process_ms':cold_legacy_ms,
                  'student_load':student.ready,'legacy_load':legacy.ready,'resource_check_ms':resource_check_ms}
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        supported=set(student.manifest['encoded_codes'])
        for case,hand in enumerate(hands,1):
            budget.check(disk=True)
            record={'case':case,'hand':hand,'cohort':'one_possible_ash' if case%2==0 else 'no_extra_response',
                    'steps':[],'status':'running','replayed':False,'model_calls':0,'single_choice_bypasses':0}
            started=time.perf_counter();state=None;history=ConfirmedHistory();visits=Counter()
            opponent={'name':'TEST ONLY development opponent','deck':deck(ASH,ASH,ASH),
                      'opening':([ASH]+[NORMAL]*4) if case%2==0 else [NORMAL]*5}
            try:
                state=session.start(public,hand,f'development-{case}',opponent,case%2==0)
                record['initial']=state
                if case<=30:
                    # All timings use this same actor window and an empty history.
                    sample=profile_window(state,catalog,student,legacy,warm=case==1)
                    sample['case']=case;profiling.append(sample)
                active_started=time.perf_counter()
                for decision in range(120):
                    budget.check()
                    if state['state']['turn']>1:
                        record['status']='turn_completed';break
                    if time.perf_counter()-active_started>180:
                        record['status']='time_budget_stopped';break
                    began=time.perf_counter();latest=session.current();read_ms=(time.perf_counter()-began)*1000
                    if (latest['version'],latest['raw'])!=(state['version'],state['raw']):raise ValueError('stale_state')
                    began=time.perf_counter();bundle=build(state,catalog)
                    features=feature_arrays(bundle,history.rows,supported)
                    feature_ms=(time.perf_counter()-began)*1000
                    visits[bundle['state_key']+digest([c['public'] for c in bundle['candidates']])]+=1
                    if max(visits.values())>3:
                        record['status']='strategy_cycle_stopped';break
                    if len(bundle['candidates'])==1:
                        choice={'index':0,'model_ms':0,'ipc_and_model_ms':0};record['single_choice_bypasses']+=1
                    else:
                        choice=student.predict(features);record['model_calls']+=1
                    index=choice['index']
                    if not 0<=index<len(bundle['candidates']):raise ValueError('student_index_out_of_range')
                    option=bundle['candidates'][index]
                    probe=session.probe(state,[state['raw']+':'+option['response']])
                    if probe['status']!='ok':
                        record['status']='response_mapping_error';record['probe_failure']=probe;break
                    before=state;state=session.answer(before,option['response'])
                    acknowledgement=deepcopy(session.samples[-1])
                    history.commit(bundle,features,index,acknowledgement)
                    record['steps'].append({'before':before,'after':state,'candidate':option['public'],
                        'candidate_index':index,'response':option['response'],'acknowledgement':acknowledgement,
                        'timings':{'read_ms':read_ms,'features_ms':feature_ms,**choice,
                                   'selected_branch_replay_ms':probe['transport_seconds']*1000,
                                   'learning_query_ms':before['learning_query_us']/1000}})
                else:record['status']='decision_budget_stopped'
            except Unsupported as error:record.update(status='model_unsupported',error=str(error))
            except Exception as error:record.update(status='execution_error',error=f'{type(error).__name__}: {error}')
            finally:
                if session.sid:
                    try:
                        state=session.current()
                        replay=session.probe(state)
                        if replay['status']!='ok' or canonical_state(replay['state'])!=canonical_state(state['state']) or replay['learning']!=state['learning']:
                            raise ValueError('Full prefix replay differs from the actual state')
                        record.update(replayed=True,final=state,full_replay_ms=replay['transport_seconds']*1000)
                        rebuilt=ConfirmedHistory.rebuild(record['steps'],catalog,supported)
                        if rebuilt.rows!=history.rows:raise ValueError('Committed history differs after restoration')
                        record['history_restored']=True
                    except Exception as error:record.update(replayed=False,replay_error=str(error))
                    record['session']=session.finish()
                    journal=Path(record['session']['folder'])/'native.jsonl'
                    rows=[json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines()]
                    record['native_journal_counts']=dict(Counter(row['kind'] for row in rows))
                    record['journal_sha256']=sha256(journal)
                    try:record['journal_audit']=audit(record)
                    except Exception as error:record.update(status='journal_mismatch',audit_error=str(error))
                record['seconds']=time.perf_counter()-started
                record['resources']=budget.check()
                if code_identity()!=code:raise ValueError('Code changed during the experiment')
                save_started=time.perf_counter()
                (output/f'case-{case:02}.json').write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
                write_ms=(time.perf_counter()-save_started)*1000
                item={k:record[k] for k in ('case','status','seconds','replayed','model_calls','single_choice_bypasses')}
                item.update(responses=len(record['steps']),log_write_ms=write_ms)
                if record.get('error'):item['error']=record['error']
                results.append(item)
                print(f'DEV {case}/{count} {record["status"]} responses={len(record["steps"])} replay={record["replayed"]}',flush=True)
        allowed={'turn_completed','strategy_cycle_stopped','decision_budget_stopped','time_budget_stopped','model_unsupported'}
        report={'scope':'execution_audit_not_strategy_quality','status':'passed' if all(r['replayed'] and r['status'] in allowed for r in results) else 'failed',
                'cases':results,'counts':dict(Counter(r['status'] for r in results)),
                'runtime':identity,'response_mapping_errors':sum(r['status']=='response_mapping_error' for r in results),
                'expected_bounded_stops_are_not_completed_turns':True}
        report['resources']=budget.check(disk=True)
        (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/'runtime-profile.json').write_text(json.dumps({'manifest':manifest,'windows':profiling,
                  'family_seconds':summary([r['seconds'] for r in results]),
                  'timings_scope':'hidden renderer retained; samples include selected-branch replay checks; no search/LLM'},
                  ensure_ascii=False,indent=2),encoding='utf-8')
        return report
    finally:
        if legacy:legacy.close()
        if student:student.close()
