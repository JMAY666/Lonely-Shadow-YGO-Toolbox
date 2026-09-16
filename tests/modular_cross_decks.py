"""Published Swordsoul and Branded lines recorded and executed by the real core.

Sources and deviations are documented in docs/modular.md. This is free-practice
validation against the pinned runtime, not validation of a current event banlist.
"""
import json
import os
from pathlib import Path

from modular_decisions import model, terminal_key
from modular import board_pattern
from modular_salamangreat import recipe_driver

MOYE, TOKEN, LONGYUAN, LTOKEN = 20001443, 20001444, 93490856, 93490857
ASHUNA, CHIXIAO, BARONNE = 23431858, 69248256, 84815190
ALUBER, FUSION, ALBAZ, TRAGEDY, LUBELLION, MIRRORJADE = 62962630, 44362883, 68468459, 36577931, 70534340, 44146295
N, MONK = 1184620, 32519092
SWORD={'main':[MOYE]*3+[LONGYUAN]*3+[ASHUNA]*3+[N]*31,
       'extra':[CHIXIAO]*2+[BARONNE]*2+[MONK], 'side':[]}
BRANDED={'main':[ALUBER]*3+[FUSION]*3+[ALBAZ]*2+[TRAGEDY]*2+[N]*30,
         'extra':[LUBELLION]*2+[MIRRORJADE]*2+[MONK], 'side':[]}


def run(api,start,current,answer,choose,save,wait,sid_fn,evidence):
    act,settle=recipe_driver(current,answer,choose)
    results=[]
    if os.environ.get('YGO_MODULAR_CROSS_REUSE')=='1':
        plans=api('/api/plans')
        sword=api('/api/plan/'+next(p['id'] for p in plans if p['name']=='TEST ONLY cross Swordsoul'))
        branded=api('/api/plan/'+next(p['id'] for p in plans if p['name']=='TEST ONLY cross Branded'))
    else:
        start(SWORD,[MOYE,ASHUNA,N,N,N],'cross Swordsoul')
        act('summon',MOYE,cards=[ASHUNA],zones=[(0,4,0),(0,4,1)],triggers=[MOYE])
        p=model(current()['raw'],current()['state'],current().get('effects'))
        assert not any(c['semantic'].get('card',{}).get('code')==MONK and c['semantic']['kind']=='special' for c in p['choices'])
        act('special',CHIXIAO,cards=[MOYE,TOKEN],effect_cards={(CHIXIAO,CHIXIAO*16):[LONGYUAN]},zones=[(0,4,0)],triggers=[CHIXIAO,MOYE])
        act('activate',LONGYUAN,cards=[ASHUNA],zones=[(0,4,1),(0,4,2)],yes_descriptions=[LONGYUAN*16+2])
        act('special',BARONNE,cards=[LONGYUAN,LTOKEN],zones=[(0,4,1)],triggers=[LONGYUAN])
        assert current()['state']['lp'][1]==6800
        sword=save()
        for code,wanted in ((MOYE,{1,2}),(LONGYUAN,{1,2}),(CHIXIAO,{1})):
            identified={a.get('effect_number') for a in sword['actions'] if a.get('kind')=='effect' and any(c.get('code')==code for c in a.get('cards',[]))}
            assert wanted<=identified,(code,identified)
        print('PASS cross source Swordsoul',len(sword['modular_source']['edges']),flush=True)

        start(BRANDED,[ALUBER,N,N,N,N],'cross Branded')
        act('summon',ALUBER,cards=[FUSION],zones=[(0,4,0)],triggers=[ALUBER])
        # Stop the published line at Mirrorjade; search a second Aluber as the
        # explicitly chosen Tragedy target, without assuming the later end phase.
        act('activate',FUSION,cards=[(LUBELLION,64),(ALBAZ,1),(TRAGEDY,1),(N,2),(MIRRORJADE,64),(ALBAZ,16),(LUBELLION,4)],
            effect_cards={(TRAGEDY,TRAGEDY*16):[(ALUBER,1)]},zones=[(0,8,0),(0,4,1)],triggers=[LUBELLION,TRAGEDY])
        assert any(c.get('code')==MIRRORJADE and c.get('location')==4 for c in current()['state']['cards'])
        assert sum(c.get('code')==N and c.get('location')==16 for c in current()['state']['cards'])==1
        branded=save()
        print('PASS cross source Branded',len(branded['modular_source']['edges']),flush=True)

    for plan,deck,hand in ((sword,SWORD,[MOYE,ASHUNA,N,N]),(branded,BRANDED,[ALUBER,N,N])):
        start(deck,hand,'cross-source module execution')
        sid=sid_fn();before=current()
        api('/api/modular/configure',{'id':sid,'sources':[plan['id']],'preference':'shortest'})
        result=api('/api/modular/search',{'id':sid})
        assert current()==before,'Search changed live state'
        assert result['candidates'],(plan['name'],result)
        goal=sorted(board_pattern(terminal_key(plan['final_state']),False))
        assert any(sorted(board_pattern(terminal_key(c['terminal']),False))==goal for c in result['candidates'])
        if plan['id']==sword['id']:
            assert result['candidates'][0]['conditional'],'Future draw must be conditional'
            assert any(c.get('unknown') for c in result['candidates'][0]['terminal']['cards'] if c.get('location')==2)
            preview=Path(evidence)/'modular-preview.request';preview.write_text('preview',encoding='ascii');wait(lambda:not preview.exists(),timeout=60)
        api('/api/modular/auto',{'id':sid,'enabled':True})
        done=wait(lambda:(s if not (s:=api('/api/modular/state/'+sid))['auto'] and not s['busy'] else None),timeout=240)
        (Path(evidence)/'modular-cross-latest.json').write_text(json.dumps(done,ensure_ascii=False,indent=2),encoding='utf-8')
        assert done['reason']=='已到达所选路线的实际终场',(plan['name'],done['reason'],
            {k:done.get('result',{}).get(k) for k in ('status','nodes','seconds','rejected')})
        assert sorted(board_pattern(terminal_key(done['state']['state']),False))==goal
        results.append({'source':plan['name'],'search':result,'actual':done['state'],'audit':done['audit']})
        print('PASS cross module execution',plan['name'],len(done['completed']),flush=True)
        save()
    from copy import deepcopy
    no_albaz=deepcopy(BRANDED)
    no_albaz['main']=[N if c==ALBAZ else c for c in no_albaz['main']]
    for label,deck,hand in (('missing discard cost',BRANDED,[ALUBER]),('missing fusion material',no_albaz,[ALUBER,N,N])):
        start(deck,hand,'cross negative '+label);sid=sid_fn()
        api('/api/modular/configure',{'id':sid,'sources':[branded['id']],'preference':'shortest'})
        before=current();result=api('/api/modular/search',{'id':sid})
        assert not result['candidates'],(label,'impossible source reached terminal')
        assert current()==before
        results.append({'negative':label,'result':result})
        print('PASS cross negative',label,result['status'],flush=True)
        save()
    (Path(evidence)/'modular-cross-decks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
