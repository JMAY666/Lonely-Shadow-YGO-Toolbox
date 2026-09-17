"""Current card scripts execute the example; no written recipe proves legality."""
from copy import deepcopy
import json
from modular_salamangreat import recipe_driver, DECK, GAZELLE, NORMAL, ROAR, SANCTUARY, BALELYNX
from duel import project
from implicit_conditions import attach


def run(api, start, current, answer, choose, save, evidence):
    deck=deepcopy(DECK);deck['main'].remove(SANCTUARY);deck['main'].append(NORMAL)
    start(deck,[GAZELLE]+[NORMAL]*4,'implicit Salamangreat example')
    act,_=recipe_driver(current,answer,choose)
    act('summon',GAZELLE,cards=[ROAR],zones=[(0,4,1)],triggers=[GAZELLE])
    act('special',BALELYNX,cards=[GAZELLE,SANCTUARY],zones=[(0,4,5)],triggers=[BALELYNX])
    act('activate',SANCTUARY,zones=[(0,8,5)])
    act('special',BALELYNX,cards=[BALELYNX],zones=[(0,4,5),(0,8,0)],triggers=[ROAR],sanctuary=True)
    plan=save(mark_field=True);rows=plan['requirements']['implicit']['conditions']
    assert any(c['code']==ROAR and c['source_zone']==1 and c['purpose']=='定向送墓' for c in rows),rows
    assert any(c['code']==SANCTUARY and c['source_zone']==1 and c['purpose']=='检索' for c in rows),rows
    grave=next(c for c in rows if c['code']==ROAR and c['source_zone']==16)
    assert grave['supplied_by'] and grave['purpose']=='盖放',grave
    assert project(plan,deck,[GAZELLE]+[NORMAL]*4)[0]
    blocked=project(plan,deck,[GAZELLE,SANCTUARY]+[NORMAL]*3)
    assert blocked[1]=='implicit' and '剩余0张' in blocked[2],blocked
    copies=deepcopy(deck);copies['main'].remove(NORMAL);copies['main'].append(SANCTUARY)
    assert project(plan,copies,[GAZELLE,SANCTUARY]+[NORMAL]*3)[0]
    assert api('/api/plan/'+plan['id'])['requirements']['implicit']['conditions']==rows
    old=deepcopy(plan);old['requirements'].pop('implicit')
    assert attach(old)['requirements']['implicit']['conditions']==rows
    assert 'implicit' not in old['requirements']
    proof={'plan':plan['id'],'deck':plan['selected_deck'],'engine':plan.get('engine_sha256'),'scripts':plan.get('scripts_sha256'),
           'conditions':rows,'blocked':blocked[2],'current_card_text':{str(c):plan['catalog'][str(c)]['desc'] for c in (GAZELLE,ROAR,SANCTUARY,BALELYNX)}}
    (evidence/'implicit-engine-results.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    print('PASS current core: Gazelle mill, Balelynx search, Sanctuary relink and Roar self-set; remaining-copy checks and legacy upgrade',flush=True)
