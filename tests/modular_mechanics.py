"""Real source/execution coverage for graveyard, Pendulum and Ritual decks.

Published recipe references are in docs/modular.md. Tests intentionally exercise
the pinned free-practice rules, including illegal-material/scale negatives.
"""
from copy import deepcopy
from pathlib import Path
import json

from modular_decisions import model, terminal_key
from modular import board_pattern
from modular_salamangreat import recipe_driver

N=1184620
UNI,BAKE,PRINCE,MARE,SKULL,LADY,KING=49959355,6128460,57473560,22339232,32274490,40991587,36021814
SCOUT,MONOLITH,GOLD,STEEL,MFUS,NOVA,INFINITY=65518099,51194046,33256280,60473572,73594093,58069384,10443957
KALEIDO,UNICORE,HERALD,BRIO=51124303,89463537,79606837,26674724
CHARGE,RYKO=94886282,21502796
GRAVE={'main':[UNI]*3+[BAKE]*3+[PRINCE]*2+[MARE]*3+[SKULL]*2+[LADY]*2+[KING]*2+[N]*23,'extra':[],'side':[]}
PEND={'main':[SCOUT]*3+[MONOLITH]*2+[GOLD]*3+[STEEL]*3+[MFUS]*2+[N]*27,'extra':[NOVA]*2+[INFINITY]*2,'side':[]}
RITUAL={'main':[KALEIDO]*3+[UNICORE]*3+[BRIO]*3+[N]*31,'extra':[HERALD]*3,'side':[]}
MILL={'main':[CHARGE]*3+[RYKO]*3+[N]*34,'extra':[],'side':[]}


def run(api,start,current,answer,choose,save,wait,sid_fn,evidence):
    act,settle=recipe_driver(current,answer,choose);results=[]
    start(GRAVE,[UNI,N,N,N,N],'mechanic Skull Servant')
    act('summon',UNI,zones=[(0,4,0)])
    act('activate',UNI,effect=UNI*16+1,cards=[(UNI,4),(BAKE,1)],zones=[(0,4,0)],triggers=[BAKE,PRINCE],
        effect_cards={(BAKE,0):[(PRINCE,1),(MARE,1),(PRINCE,2)],(PRINCE,PRINCE*16):[(SKULL,1),(LADY,1)]})
    act('activate',PRINCE,effect=PRINCE*16+1,cards=[(SKULL,16),(LADY,16),(KING,1)],zones=[(0,4,1)])
    act('activate',MARE,cards=[(LADY,32)],options=[MARE*16+1],zones=[(0,4,2)])
    grave=save();print('PASS graveyard source: mill triggers, two searches, discard, banish cost and revival',flush=True)

    start(PEND,[SCOUT,GOLD,STEEL,N,N],'mechanic Metalfoes Qli')
    act('activate',SCOUT,location=2,zones=[(0,8,0)])
    act('activate',SCOUT,location=8,cards=[MONOLITH])
    assert current()['state']['lp'][0]==7200
    act('activate',GOLD,location=2,zones=[(0,8,4)])
    act('activate',GOLD,location=8,cards=[(SCOUT,8),(MFUS,1)],zones=[(0,8,2)])
    assert any(c['code']==SCOUT and c['location']==64 and c['position']&5 for c in current()['state']['cards'])
    act('activate',STEEL,location=2,zones=[(0,8,0)])
    act('special',STEEL,location=8,cards=[(SCOUT,64),(MONOLITH,2)],select_all=True,zones=[(0,4,5),(0,4,0)])
    state=current();scout=next(c for c in state['state']['cards'] if c['code']==SCOUT and c['location']==4)
    assert scout['sequence'] in (5,6),'Face-up Extra Deck Pendulum needs EMZ or a Link arrow'
    assert not any(c['semantic']['kind']=='special' and c['semantic'].get('card',{}).get('location')==8 for c in model(state['raw'],state['state'],state.get('effects'))['choices'])
    act('special',NOVA,cards=[SCOUT,MONOLITH],zones=[(0,4,0)])
    act('special',INFINITY,cards=[NOVA],zones=[(0,4,0)])
    host=next(c for c in current()['state']['cards'] if c['code']==INFINITY and c['location']==4)
    assert sum(c.get('overlay_target')==host['instance_id'] for c in current()['state']['cards'])==3
    pend=save();print('PASS Pendulum source: scale cost, face-up Extra Deck, simultaneous summon and overlay carryover',flush=True)

    start(RITUAL,[KALEIDO,UNICORE,N,N,N],'mechanic Nekroz')
    act('activate',KALEIDO,cards=[(HERALD,64),(UNICORE,2),(BRIO,1)],zones=[(0,8,0),(0,4,0)],triggers=[HERALD])
    ritual=save();print('PASS Ritual source: exact levels, Extra Deck material and Herald graveyard search',flush=True)

    for plan,deck,hand in ((grave,GRAVE,[UNI,N,N]),(pend,PEND,[SCOUT,GOLD,STEEL,N]),(ritual,RITUAL,[KALEIDO,UNICORE,N])):
        start(deck,hand,'mechanic module execution');sid=sid_fn();before=current()
        reply=api('/api/modular/dispatch',{'consumer':'duel','intent':'configure','id':sid,'sources':[plan['id']],'preference':'shortest'})
        assert reply['inputs']['session']==sid and reply['inputs']['deck']
        result=api('/api/modular/dispatch',{'consumer':'duel','intent':'search','id':sid})['result']
        assert current()==before
        assert result['candidates'],(plan['name'],result['status'],result['rejected'])
        api('/api/modular/dispatch',{'consumer':'duel','intent':'auto','id':sid,'enabled':True})
        done=wait(lambda:(v if not (v:=api('/api/modular/state/'+sid))['auto'] and not v['busy'] else None),timeout=300)
        (Path(evidence)/'modular-mechanics-latest.json').write_text(json.dumps(done,ensure_ascii=False,indent=2),encoding='utf-8')
        assert done['reason']=='已到达所选路线的实际终场',(plan['name'],done['reason'])
        assert sorted(board_pattern(terminal_key(done['state']['state']),False))==sorted(board_pattern(terminal_key(plan['final_state']),False))
        results.append({'source':plan['name'],'search':result,'actual':done['state'],'audit':done['audit']})
        print('PASS mechanic source to actual AI execution',plan['name'],flush=True);save()

    # A level-8 Extra Deck card cannot pay for the lone level-4 ritual monster.
    wrong=deepcopy(RITUAL);wrong['extra']=[69248256]
    start(wrong,[KALEIDO,UNICORE,KALEIDO],'negative ritual level')
    state=current();assert not any(c['semantic']['kind']=='activate' and c['semantic'].get('card',{}).get('code')==KALEIDO for c in model(state['raw'],state['state'],state.get('effects'))['choices'])
    save();print('PASS invalid Ritual level rejected by current legal prompt',flush=True)
    start(PEND,[GOLD,GOLD,SCOUT,N],'negative equal scales')
    act('activate',GOLD,location=2,zones=[(0,8,0)]);act('activate',GOLD,location=2,zones=[(0,8,4)])
    state=current();assert not any(c['semantic']['kind']=='special' and c['semantic'].get('card',{}).get('location')==8 for c in model(state['raw'],state['state'],state.get('effects'))['choices'])
    save();print('PASS equal Pendulum scales reject Pendulum Summon',flush=True)

    start(MILL,[CHARGE,N,N],'mechanic random Lightsworn mill')
    act('activate',CHARGE,cards=[RYKO],zones=[(0,8,0)])
    mill=save()
    start(MILL,[CHARGE,N,N],'random mill information boundary');sid=sid_fn()
    api('/api/modular/configure',{'id':sid,'sources':[mill['id']],'preference':'shortest'})
    result=api('/api/modular/search',{'id':sid})
    assert result['candidates'],(result['status'],result['rejected'])
    assert all(c['conditional'] for c in result['candidates'])
    assert any(c.get('unknown') for c in result['candidates'][0]['terminal']['cards'] if c.get('location')==16)
    results.append({'source':mill['name'],'search':result})
    save();print('PASS random top-deck mill stays conditional and hides hypothetical grave/deck identities',flush=True)
    (Path(evidence)/'modular-mechanics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
