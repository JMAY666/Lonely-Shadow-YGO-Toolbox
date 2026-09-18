"""Real-engine goals compared by resource cost, terminal size, decisions and their average."""
from modular_decisions import model, terminal_key
from modular import board_pattern


def record_and_compare(api,start,current,choose,idle,save,wait,sid_fn,evidence):
    normal,pot=1184620,55144522
    deck={'main':[normal]*38+[pot]*2,'extra':[],'side':[]}
    plans=[]
    for kind in ('short','large','safe'):
        start(deck,[normal,normal,pot],'preference '+kind)
        choose('spell_set',pot);choose(place=[0,8,0]);idle()
        if kind in ('large','safe'):
            choose('summon',normal);choose(place=[0,4,1]);idle()
        if kind in ('short','large'):
            choose('activate',pot,location=8);idle()
        plans.append(save())
    start(deck,[normal,normal,pot],'three preference comparison')
    sid=sid_fn();sources=[p['id'] for p in plans];before=current()
    results={}
    for preference,wanted in (('cheapest',plans[0]),('largest',plans[1]),('shortest',plans[0]),('balanced',None)):
        api('/api/modular/configure',{'id':sid,'sources':sources,'preference':preference})
        result=api('/api/modular/search',{'id':sid});results[preference]=result
        assert result['candidates'],result['status']
        best=result['candidates'][0]
        if wanted: assert best['steps'][-1]['source']['plan']==wanted['id'],(preference,[(c['remaining'],c['steps'][-1]['source']['name'],c['robustness']) for c in result['candidates']])
        assert current()==before
        print('PASS real preference',preference,best['remaining'],best['steps'][-1]['source']['name'],flush=True)
    import json
    from pathlib import Path
    (Path(evidence)/'modular-preferences.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    # Shared set-card prefix is actually executed. A preference change only
    # changes the remaining route and the expected terminal, not that prefix.
    api('/api/modular/configure',{'id':sid,'sources':sources,'preference':'shortest'})
    first=api('/api/modular/search',{'id':sid})['candidates'][0]
    api('/api/modular/execute',{'id':sid,'candidate':first['id']})
    wait(lambda:(s if (s:=current())['version']>before['version'] else None))
    if model(current()['raw'],current()['state'],current().get('effects'))['message']==18:choose(place=[0,8,0])
    idle();fixed=current()
    api('/api/modular/configure',{'id':sid,'sources':sources,'preference':'largest'})
    changed=api('/api/modular/search',{'id':sid})
    assert changed['candidates'][0]['steps'][-1]['source']['plan']==plans[1]['id']
    assert current()==fixed
    api('/api/modular/auto',{'id':sid,'enabled':True})
    done=wait(lambda:(s if not (s:=api('/api/modular/state/'+sid))['auto'] and not s['busy'] else None),timeout=120)
    assert done['reason']=='已到达所选路线的实际终场',done['reason']
    assert sorted(board_pattern(terminal_key(done['state']['state']),False))==sorted(board_pattern(terminal_key(plans[1]['final_state']),False))
    print('PASS mid-route preference change retains the live prefix and reaches the new terminal',flush=True)
    api('/api/stop',{'id':sid})
    import time
    wait(lambda:not any(h['status'] in ('running','starting','stopping') for h in api('/api/history')))
    return plans
