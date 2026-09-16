"""Real ordinary-zone adaptation, exact mode and Link-arrow restrictions."""
from pathlib import Path
import json
from modular_decisions import model
from modular_salamangreat import recipe_driver,DECK,GAZELLE as G,JAGUAR as J,BALELYNX as B,WOLF as W,ROAR as R,SANCTUARY as A,NORMAL as N

DEBUG=16188701


def run(runtime,evidence,api,start,current,answer,choose,save,wait,sid_fn):
    act,settle=recipe_driver(current,answer,choose);results=[]
    deck={'main':[DEBUG]*3+[G]*3+[N]*34,'extra':[],'side':[]}
    start(deck,[DEBUG,N,N,N,N],'precision ordinary-zone source')
    act('summon',DEBUG,cards=[G],zones=[(0,4,0)],triggers=[DEBUG]);ordinary=save()
    start(deck,[DEBUG,N,N,N,N],'precision ordinary-zone alternate')
    choose('summon',DEBUG);choose(place=[0,4,1])
    while model(current()['raw'],current()['state'],current().get('effects'))['message']==16:choose('pass')
    sid=sid_fn();before=current()
    def search(precise,source):
        api('/api/modular/configure',{'id':sid_fn(),'sources':[source['id']],'preference':'shortest','precise':precise})
        return api('/api/modular/search',{'id':sid_fn()})
    exact=search(True,ordinary);assert not exact['candidates'],exact
    adaptive=search(False,ordinary);assert adaptive['candidates'],adaptive
    assert any(step.get('bound_decision')!=step['decision'] for step in adaptive['candidates'][0]['steps'])
    assert current()==before
    stale=adaptive['candidates'][0]['id'];search(True,ordinary)
    try:api('/api/modular/execute',{'id':sid,'candidate':stale})
    except RuntimeError as error:assert '过期' in str(error)
    else:raise AssertionError('Precision change must revoke old choices')
    adaptive=search(False,ordinary);api('/api/modular/auto',{'id':sid,'enabled':True})
    done=wait(lambda:(v if not (v:=api('/api/modular/state/'+sid))['auto'] and not v['busy'] else None),timeout=180)
    assert done['reason']=='已到达所选路线的实际终场',done['reason']
    assert any(c['code']==DEBUG and c['location']==4 and c['sequence']==1 for c in done['state']['state']['cards'])
    assert any(c['code']==G and c['location']==2 for c in done['state']['state']['cards'])
    results.append({'case':'ordinary zone relocation','exact':exact,'adaptive':adaptive,'actual':done['state']});save()
    print('PASS exact rejects changed zone; adaptive executes same effect in zone 2; toggle invalidates stale result',flush=True)

    def wolf_prefix(zone):
        act('summon',J,zones=[(0,4,0)])
        act('special',B,cards=[(J,4)],effect_cards={(B,B*16):[A],(G,G*16+1):[R]},zones=[(0,4,5),(0,4,0)],triggers=[B,G])
        act('special',W,cards=[B,G],zones=[(0,4,5)])
        act('activate',A,zones=[(0,8,5)])
        act('special',W,cards=[W],zones=[(0,4,zone)],sanctuary=True)
        act('activate',W,effect=W*16+1,cards=[R])
    start(DECK,[G,J,N,N,N],'precision left Wolf source');wolf_prefix(5)
    act('activate',J,cards=[W,G],zones=[(0,4,1)],triggers=[W]);linked=save()
    start(DECK,[G,J,N,N,N],'precision right Wolf alternate');wolf_prefix(6)
    sid=sid_fn()
    exact=search(True,linked);assert not exact['candidates'],exact
    adaptive=search(False,linked);assert adaptive['candidates'],(adaptive['status'],adaptive['rejected'])
    places=[choice['place'] for step in adaptive['candidates'][0]['steps'] for choice in step.get('bound_decision',{}).get('selection',[]) if choice['kind']=='place']
    assert [0,4,1] not in places,places
    assert any(c['code']==J and c['location']==4 and c['sequence']==3 for c in adaptive['candidates'][0]['terminal']['cards'])
    api('/api/modular/auto',{'id':sid,'enabled':True})
    done=wait(lambda:(v if not (v:=api('/api/modular/state/'+sid))['auto'] and not v['busy'] else None),timeout=240)
    assert done['reason']=='已到达所选路线的实际终场',done['reason']
    assert any(c['code']==J and c['location']==4 and c['sequence']==3 for c in done['state']['state']['cards'])
    results.append({'case':'right EMZ Link arrow','exact':exact,'adaptive':adaptive,'actual':done['state']});save()
    print('PASS adaptive Link route uses only the actual right-Wolf linked zone 4',flush=True)
    (Path(evidence)/'modular-precision.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
