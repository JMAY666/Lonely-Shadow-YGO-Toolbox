"""Real-core fixtures. Run only via the hidden Electron modular smoke profile."""
from pathlib import Path
import json
import sys
import time
import urllib.request
import urllib.parse
import uuid
import hashlib
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/trainer'))
from modular_decisions import model, integer
from app import process_identity


def main(runtime, url, evidence):
    runtime, evidence = Path(runtime), Path(evidence)
    assert 'desktop-check-' in str(runtime) and '-modular' in str(runtime), 'Isolated acceptance runtime required'
    token = json.load(urllib.request.urlopen(url+'/api/bootstrap'))['token']
    def api(path, body=None):
        request = urllib.request.Request(url+path, data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type':'application/json','X-Trainer-Token':token})
        try:
            with urllib.request.urlopen(request, timeout=120) as response: return json.load(response)
        except urllib.error.HTTPError as error: raise RuntimeError(error.read().decode()) from error
    def wait(fn, timeout=30):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            result=fn()
            if result: return result
            time.sleep(.07)
        raise AssertionError('Native acceptance condition timed out')
    sid = None
    def state():
        path=runtime/'_trainer/sessions'/sid/'modular-state.json'
        if not path.exists(): return None
        try:value=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):return None
        return value if not value['answered'] and value['player']==0 else None
    def current(): return wait(state)
    def answer(raw, expected=None):
        before=expected or current(); folder=runtime/'_trainer/sessions'/sid; lease=uuid.uuid4().hex
        (folder/'modular-lease.txt').write_text(lease,encoding='ascii')
        temp=folder/'acceptance-request.tmp';temp.write_text(f"answer {before['version']} {lease} 0 1\n{raw}\n",encoding='ascii');temp.replace(folder/'modular.request')
        return wait(lambda: (v if (v:=state()) and v['version']>before['version'] else None))
    def choose(kind=None, code=None, place=None, option=None, index=0, effect=None, location=None):
        current_state=current(); prompt=model(current_state['raw'],current_state['state'],current_state.get('effects'))
        choices=[c for c in prompt['choices'] if (kind is None or c['semantic']['kind']==kind) and
            (code is None or c['semantic'].get('card',{}).get('code')==code) and
            (place is None or c['semantic'].get('place')==place) and
            (effect is None or (c.get('effect') or {}).get('description')==effect) and
            (location is None or c['semantic'].get('card',{}).get('location')==location) and
            (option is None or c['semantic'].get('value')==option)]
        assert choices, json.dumps({'wanted':[kind,code,place,option], 'prompt':prompt},ensure_ascii=False)
        choice=choices[index]; raw=choice['response']
        if prompt['mode']=='cards': raw=bytes([1,raw]).hex()
        elif prompt['mode']=='sum': raw=bytes([1+prompt['mandatory'],*range(prompt['mandatory']),raw]).hex()
        return answer(raw,current_state)
    def start(deck, hand, name):
        nonlocal sid
        request=evidence/'modular-layout.request';request.write_text('layout',encoding='ascii');wait(lambda:not request.exists())
        saved=api('/api/decks',{'name':name.replace('/','-')+' '+uuid.uuid4().hex[:5],'deck':deck})
        sid=api('/api/start',{'deck_id':saved['id'],'design':{'name':'TEST ONLY '+name,'notes':'Isolated real-engine fixture',
            'revision':saved['revision'],'conditions':{'hand_count':len(hand),'slots':hand,'banned':[]},'opponent_ai':False}})['id']
        return current()
    def finish():
        api('/api/stop',{'id':sid})
        meta=json.loads((runtime/'_trainer/sessions'/sid/'session.json').read_text(encoding='utf-8'))
        wait(lambda:process_identity(meta['pid'])!=meta['process_identity'])
        # The journal can finish before the server's retained process handle
        # observes exit. Use its authoritative running flag before saving.
        wait(lambda:api('/api/modular/state/'+sid).get('state',{}).get('running') is False)
        wait(lambda:not any(h['status'] in ('running','starting','stopping') for h in api('/api/history')))
        report=wait(lambda: (r if (r:=api('/api/report/'+sid))['status']=='completed' else None))
        return report
    def use_session(identifier):
        nonlocal sid
        sid=identifier
        request=evidence/'modular-layout.request';request.write_text('layout',encoding='ascii');wait(lambda:not request.exists())
    def save(mark_field=False):
        report=finish()
        body={'id':sid,'name':report['name'],'notes':'TEST ONLY isolated source'}
        if mark_field:
            from copy import deepcopy
            edits=deepcopy(report.get('annotations') or {})
            edits['final_marks']={str(c['instance_id']):{'marked':True,'effects':{}} for c in report['final_state']['cards'] if c['controller']==0 and c['location'] in (4,8)}
            body['annotations']=edits
        preview=api('/api/plans/preview',body)
        plan=api('/api/plans/save',{**body,'annotations':preview['annotations'],'confirmation':preview['confirmation']})
        wait(lambda:not any(h['status'] in ('running','starting','stopping') for h in api('/api/history')))
        return plan
    def idle():
        for _ in range(20):
            s=current(); p=model(s['raw'],s['state'],s.get('effects'))
            if p['message']==11:return s
            if p['message']==16:choose('pass')
            elif p['message']==19:choose(option=1)
            else:raise AssertionError(json.dumps(p))
        raise AssertionError('Unsettled core')
    if os.environ.get('YGO_MODULAR_FORECAST_ONLY')=='1':
        from modular_forecast import run
        run(runtime,evidence,api,start,current,answer,choose,save)
        return
    if os.environ.get('YGO_MODULAR_PIPELINE_ONLY')=='1':
        normal=1184620;deck={'main':[normal]*40,'extra':[],'side':[]}
        start(deck,[normal]*3,'pipeline normal source')
        choose('summon',normal);choose(place=[0,4,1]);idle();plan=save(mark_field=True)
        pot=55144522;start({'main':[normal]*20+[pot]*20,'extra':[],'side':[]},[normal,pot,pot],'pipeline continuation source')
        choose('summon',normal);choose(place=[0,4,1]);idle()
        choose('spell_set',pot);choose(place=[0,8,0]);idle();followup=save(mark_field=True)
        (evidence/'pipeline-source.json').write_text(json.dumps({'plan':plan['id'],'deck':plan['selected_deck'],
            'followup':{'plan':followup['id'],'deck':followup['selected_deck']}},ensure_ascii=False),encoding='utf-8')
        print('PASS pipeline source recorded through expansion and formal save',flush=True)
        return
    if os.environ.get('YGO_MODULAR_PRECISION_ONLY')=='1':
        from modular_precision import run
        run(runtime,evidence,api,start,current,answer,choose,save,wait,lambda:sid)
        return
    if os.environ.get('YGO_MODULAR_IF_ONLY')=='1':
        from modular_if_routes import run
        run(runtime,evidence,api,start,current,answer,choose,save,finish,use_session,wait,lambda:sid)
        return
    if os.environ.get('YGO_MODULAR_MECHANICS_ONLY')=='1':
        from modular_mechanics import run
        run(api,start,current,answer,choose,save,wait,lambda:sid,evidence)
        return
    if os.environ.get('YGO_MODULAR_CROSS_ONLY')=='1':
        from modular_cross_decks import run
        run(api,start,current,answer,choose,save,wait,lambda:sid,evidence)
        return
    if os.environ.get('YGO_MODULAR_PREFERENCES_ONLY')=='1':
        from modular_preferences import record_and_compare
        record_and_compare(api,start,current,choose,idle,save,wait,lambda:sid,evidence)
        return
    if os.environ.get('YGO_MODULAR_ADDITIONAL_ONLY')=='1':
        from modular_additional_routes import run_additional
        results=run_additional(runtime,evidence,api,start,lambda:sid,wait)
        unexpected=[{'combo':r['combo'],'variant':r['variant'],'reason':r.get('reason','')[:300]} for r in results
                    if (r['status']=='engine_verified') != (r['combo']!=15 or r['variant']=='corrected')]
        assert not unexpected,unexpected
        return
    if os.environ.get('YGO_MODULAR_SEARCH_ONLY')=='1':
        from app import Store
        from modular_decisions import bind
        from modular_salamangreat import DECK, GAZELLE, SPINNY, NORMAL
        summaries=api('/api/plans')
        combos=[next(p for p in summaries if p['name'].startswith('TEST ONLY Combo '+str(i))) for i in (1,2,3)]
        start(DECK,[GAZELLE,SPINNY]+[NORMAL]*3,'Salamangreat search diagnostic')
        api('/api/modular/configure',{'id':sid,'sources':[p['id'] for p in combos],'preference':'shortest'})
        planner=Store(runtime).modular;planner.library.sync();root_state=current()
        for combo in combos:
            node=root_state;path=[]
            for index,edge in enumerate(planner.library.edges([combo['id']])):
                prompt=model(node['raw'],node['state'],node.get('effects'));raw=bind(edge['decision'],prompt)
                if raw is None:
                    print('BIND BLOCK',combo['name'],index,json.dumps({'expected':edge['decision'],'actual':{k:prompt[k] for k in ('message','player','context')},'choices':[c['semantic'] for c in prompt['choices']]},ensure_ascii=False),flush=True);break
                path.append(node['raw']+':'+raw);node=planner.bridge(sid,root_state,path)
                while node['player']==1:
                    path.append(node['raw']+':ai');node=planner.bridge(sid,root_state,path)
            else: print('PASS exact source replay',combo['name'],len(path),flush=True)
        result=planner.search(sid)
        print('DIAGNOSTIC SEARCH',result['status'],result['nodes'],len(result['candidates']),result['rejected'],flush=True)
        (evidence/'modular-diagnostic-search.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    normal, pot = 1184620, 55144522
    deck={'main':[normal]*38+[pot]*2,'extra':[],'side':[]}
    start(deck,[normal,normal,pot],'normal short')
    choose('summon',normal);choose(place=[0,4,1]);idle();short=save()
    print('PASS short source',len(short['modular_source']['edges']),flush=True)
    start(deck,[normal,normal,pot],'normal draw')
    choose('summon',normal);choose(place=[0,4,1]);idle();choose('activate',pot);choose(place=[0,8,0]);idle();long=save()
    print('PASS long source',len(long['modular_source']['edges']),flush=True)
    start(deck,[normal,normal,pot,normal],'combined hand')
    api('/api/modular/configure',{'id':sid,'sources':[short['id'],long['id']],'preference':'shortest'})
    before=current();folder=runtime/'_trainer/sessions'/sid
    before_files={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ('native.jsonl','core-calls.txt')}
    result=api('/api/modular/search',{'id':sid})
    (evidence/'modular-first-search.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result['candidates'], result
    assert current()==before,'Searching changed the live duel'
    assert before_files=={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in before_files},'Searching changed the live history'
    print('PASS isolated search',result['nodes'],len(result['candidates']),flush=True)
    stale=result['candidates'][0]['id']
    api('/api/modular/configure',{'id':sid,'sources':[short['id'],long['id']],'preference':'largest'})
    try:api('/api/modular/execute',{'id':sid,'candidate':stale})
    except RuntimeError:pass
    else:raise AssertionError('Stale preference decision was executed')
    assert current()==before
    refreshed=api('/api/modular/search',{'id':sid});old_version=refreshed['token'][2]
    api('/api/plans/update',{'id':long['id'],'name':long['name']+' revised','notes':long['expansion']['notes'],
                           'original_name':long['name'],'original_notes':long['expansion']['notes']})
    updated=wait(lambda:(v if (v:=api('/api/modular/state/'+sid)).get('result') and v['result']['token'][2]!=old_version else None),timeout=60)
    assert current()==before
    assert before_files=={name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in before_files}
    try:api('/api/modular/execute',{'id':sid,'candidate':refreshed['candidates'][0]['id']})
    except RuntimeError:pass
    else:raise AssertionError('Stale source decision was executed')
    api('/api/modular/configure',{'id':sid,'sources':[short['id'],long['id']],'preference':'shortest'})
    print('PASS source auto-update and preference/source stale-decision rejection',flush=True)
    api('/api/modular/auto',{'id':sid,'enabled':True})
    def completed():
        value=api('/api/modular/state/'+sid)
        if not value['auto'] and not value['busy']:
            assert value['reason']=='已到达所选路线的实际终场', {'reason':value['reason'],'completed':len(value['completed']),'pending':bool(value['pending'])}
            return value
    finished=wait(completed,timeout=90)
    assert len(finished['completed'])>=2
    api('/api/modular/auto',{'id':sid,'enabled':False})
    print('PASS built-in AI',flush=True)
    api('/api/stop',{'id':sid})
    meta=json.loads((runtime/'_trainer/sessions'/sid/'session.json').read_text(encoding='utf-8'));wait(lambda:process_identity(meta['pid'])!=meta['process_identity'])
    from modular_salamangreat import record_sources, DECK, GAZELLE, SPINNY, NORMAL, ROAR
    combos, settle = record_sources(start,current,answer,choose,lambda:save(mark_field=True))
    combo=combos[2];selected=next(n for n in combo['review']['nodes'] if n.get('kind')=='step' and n['number']==9)
    saved=api('/api/deck?id='+urllib.parse.quote(combo['selected_deck'],safe=''))
    request={'consumer':'duel','intent':'plan','deck_id':saved['id'],'revision':saved['revision'],
        'hand_count':5,'hand':[GAZELLE,SPINNY]+[NORMAL]*3,'sources':[p['id'] for p in combos],'preference':'shortest',
        'anchor':{'plan':combo['id'],'revision':combo['edit_revision'],'route':'main','node':selected['id'],'number':9}}
    continuation=api('/api/modular/dispatch',request)['result']
    assert continuation['confirmed']>0 and continuation['anchor']['number']==9
    assert continuation['result']['candidates'],continuation['result']
    assert not any(choice['kind']=='summon' for c in continuation['result']['candidates'] for step in c['steps']
                   for choice in (step.get('bound_decision') or step['decision'])['selection'])
    (evidence/'modular-step9-continuation.json').write_text(json.dumps(continuation,ensure_ascii=False,indent=2),encoding='utf-8')
    api('/api/modular/dispatch',{'consumer':'duel','intent':'plan-close','id':continuation['id']})
    print('PASS real Combo 3 Step 9 continuation preserves its source prefix and searches only later decisions',flush=True)
    start(DECK,[GAZELLE,SPINNY]+[NORMAL]*3,'Salamangreat shared opening')
    api('/api/modular/configure',{'id':sid,'sources':[p['id'] for p in combos],'preference':'shortest'})
    result=api('/api/modular/search',{'id':sid})
    (evidence/'modular-salamangreat.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Salamangreat search',result['status'],result['nodes'],len(result['candidates']),result['rejected'],flush=True)
    assert result['candidates']
    assert {p['id'] for p in combos} <= {c['steps'][-1]['source']['plan'] for c in result['candidates']},'All three sources must be reachable from this actual hand'
    chosen=next(c for c in result['candidates'] if c['steps'][-1]['source']['plan']==combos[0]['id'])
    api('/api/modular/execute',{'id':sid,'candidate':chosen['id']})
    # The player chooses Spinny in Gazelle's actual effect-2 selection, instead
    # of the Roar needed by the selected route. Nothing is rewound or replaced.
    wait(lambda:(v if (v:=state()) and v['version']>result['start']['version'] else None))
    settle(cards=[SPINNY],zones=[(0,4,1)],triggers=[GAZELLE])
    assert any(c['code']==SPINNY and c['controller']==0 and c['location']==16 for c in current()['state']['cards'])
    original_opening=json.loads((runtime/'_trainer/sessions'/sid/'session.json').read_text(encoding='utf-8'))['expansion']['actual_opening']
    prefix=(runtime/'_trainer/sessions'/sid/'native.jsonl').read_bytes()
    api('/api/modular/configure',{'id':sid,'sources':[p['id'] for p in combos],'preference':'shortest','goal':[ROAR]})
    api('/api/modular/auto',{'id':sid,'enabled':True})
    adapted=wait(completed,timeout=240)
    assert {combos[0]['id'],combos[1]['id']} <= {c['step']['source']['plan'] for c in adapted['completed']}
    assert any(a['kind']=='terminal_reached' and a.get('original_goal_met') is False for a in adapted['audit'])
    assert (runtime/'_trainer/sessions'/sid/'native.jsonl').read_bytes().startswith(prefix)
    assert json.loads((runtime/'_trainer/sessions'/sid/'session.json').read_text(encoding='utf-8'))['expansion']['actual_opening']==original_opening
    report=api('/api/report/'+sid)
    assert sum(e.get('message')==60 and any(c['code']==GAZELLE for c in e['cards']) for e in report['events'])==1
    (evidence/'modular-adaptation.json').write_text(json.dumps(adapted,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS Gazelle effect-2 deviation -> source B via built-in AI -> alternative terminal; opening and prefix retained',flush=True)


if __name__=='__main__': main(*sys.argv[1:])
