"""Save real IF branches, then let the hub dispatch their actual extenders.

Swordsoul's Longyuan extension follows the published handtrap guide. Orange
Light and Ghost Ogre are additional explicit rule scenarios, never assumed to
be the same type of interruption as Infinite Impermanence.
"""
from pathlib import Path
import json
import time
import uuid
import os
from modular_decisions import model, integer
from modular_salamangreat import recipe_driver
from modular_cross_decks import SWORD,MOYE,TOKEN,LONGYUAN,LTOKEN,ASHUNA,CHIXIAO,BARONNE,N

IMPERM,ORANGE,FAIRY,OGRE=10045474,17266660,39552864,59438930
SCENARIOS=[('effect_negated',[IMPERM]),('activation_negated',[ORANGE,FAIRY]),('resource_moved',[OGRE])]
if os.environ.get('YGO_MODULAR_IF_CASE'):
    SCENARIOS=[row for row in SCENARIOS if row[0]==os.environ['YGO_MODULAR_IF_CASE']]


def run(runtime,evidence,api,start,current,answer,choose,save,finish,use_session,wait,sid_fn):
    act,settle=recipe_driver(current,answer,choose);results=[]
    start(SWORD,[MOYE,LONGYUAN,ASHUNA,N,N],'IF Swordsoul main')
    act('summon',MOYE,cards=[ASHUNA],zones=[(0,4,0),(0,4,1)],triggers=[MOYE])
    act('activate',LONGYUAN,cards=[ASHUNA],zones=[(0,4,2),(0,4,3)],yes_descriptions=[LONGYUAN*16+2])
    act('special',BARONNE,cards=[LONGYUAN,LTOKEN],zones=[(0,4,2)],triggers=[LONGYUAN])
    act('special',CHIXIAO,cards=[MOYE,TOKEN],effect_cards={(CHIXIAO,CHIXIAO*16):[LONGYUAN]},zones=[(0,4,0)],triggers=[CHIXIAO,MOYE])
    main=finish();main_id=main['id']
    affected=next(a for a in main['actions'] if a.get('kind')=='effect' and a.get('effect_number')==1 and any(c.get('code')==MOYE for c in a.get('cards',[])))
    point=next(p for p in main['branch_points'] if p['action_id']==affected['id'] and p['player']==1)

    def enter(root_id,source_point,kind,opponent,name,required=True):
        root=api('/api/report/'+root_id)
        root=api('/api/branches/create',{'id':root_id,'revision':root['branches_revision'],
            'checkpoint':source_point['checkpoint'],'node_id':source_point['node_id']})
        branch=root['branches'][-1]
        condition={'kind':kind,'required':[{'code':LONGYUAN,'location':2,'count':1},{'code':ASHUNA,'location':2,'count':1}] if required else []}
        root=api('/api/branches/update',{'id':root_id,'branch_id':branch['id'],'revision':root['branches_revision'],'name':name,
            'conditions':{'hand':opponent,'expected_action':source_point['action_id'],'note':'TEST ONLY real interruption and extender','if':condition}})
        pending=next(b for b in root['branches'] if b['id']==branch['id'])
        assert pending['if_condition']['status']=='unverified','Preset hand must not satisfy IF'
        session=api('/api/branches/enter',{'id':root_id,'branch_id':branch['id'],'revision':root['branches_revision']})
        use_session(session['id']);folder=Path(runtime)/'_trainer/sessions'/session['id']
        wait(lambda:(v if (p:=folder/'branch-operation.json').exists() and (v:=json.loads(p.read_text(encoding='utf-8')))['status'] in ('ready','error') else None),timeout=60)
        assert json.loads((folder/'branch-operation.json').read_text(encoding='utf-8'))['status']=='ready'
        return branch['id'],folder

    def respond(folder,opponent,leave_own=False):
        activated=False;last=-1;deadline=time.monotonic()+75
        while time.monotonic()<deadline:
            try:node=json.loads((folder/'modular-state.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):time.sleep(.02);continue
            if node['answered'] or node['version']==last:time.sleep(.05);continue
            prompt=model(node['raw'],node['state'],node.get('effects'));choices=prompt['choices']
            if len(choices)==1 and choices[0]['semantic']['kind']=='pass':
                time.sleep(.05);continue  # The native client acknowledges an empty window.
            if node['player']==0:
                if leave_own or prompt['message']==11:return node
                chosen=next((c for c in choices if c['semantic']['kind'] in ('pass','no')),None)
                if prompt['mode']=='places':chosen=choices[0]
                if prompt['message']==19:chosen=next(c for c in choices if c['semantic']['value']==1)
                assert chosen,prompt
                token=uuid.uuid4().hex;(folder/'modular-lease.txt').write_text(token,encoding='ascii')
                tmp=folder/'if-answer.tmp';tmp.write_text(f"answer {node['version']} {token} 0 1\n{chosen['response']}\n",encoding='ascii');tmp.replace(folder/'modular.request')
            else:
                if prompt['mode']=='cards':
                    ordered=sorted(choices,key=lambda c:((c.get('card') or {}).get('code') not in (FAIRY,MOYE),c['response']))
                    raw=bytes([prompt['minimum'],*(c['response'] for c in ordered[:prompt['minimum']])]).hex()
                else:
                    wanted=next((c for c in choices if c['semantic']['kind'] in ('activate','yes') and (c.get('card') or {}).get('code')==opponent[0]),None) if not activated else None
                    chosen=wanted or next((c for c in choices if c['semantic']['kind'] in ('pass','no')),None)
                    if prompt['mode']=='places':chosen=choices[0]
                    if prompt['message']==19:chosen=next(c for c in choices if c['semantic']['value']==1)
                    assert chosen,prompt
                    if wanted:activated=True
                    raw=chosen['response']
                op=api('/api/opponent/state/'+sid_fn())
                if op.get('version')!=node['version'] or op.get('answered') or op.get('player')!=1:continue
                api('/api/opponent/control',{'id':sid_fn(),'command':'answer','version':node['version'],'raw':raw})
            last=node['version'];time.sleep(.05)
        raise AssertionError('Interruption response sequence timed out')

    branches={}
    for kind,opponent in SCENARIOS:
        branch_id,folder=enter(main_id,point,kind,opponent,'TEST ONLY IF '+kind)
        respond(folder,opponent)
        # Ogre destroys Mo Ye but its already-activated effect still summons a
        # token. Negation scenarios do not get that token for free.
        if kind=='resource_moved':assert any(c['code']==TOKEN and c['location']==4 for c in current()['state']['cards'])
        else:assert not any(c['code']==TOKEN and c['location']==4 for c in current()['state']['cards'])
        act('activate',LONGYUAN,cards=[ASHUNA],zones=[(0,4,1),(0,4,2),(0,4,3)],yes_descriptions=[LONGYUAN*16+2])
        act('special',BARONNE,cards=[LONGYUAN,LTOKEN],zones=[(0,4,1)],triggers=[LONGYUAN])
        finish()
        root=api('/api/report/'+main_id);branch=next(b for b in root['branches'] if b['id']==branch_id)
        assert branch['if_condition']['status']=='verified',(kind,branch['if_condition'])
        branches[kind]=branch_id
        print('PASS real saved IF condition and extender',kind,flush=True)
    body={'id':main_id,'name':main['name'],'notes':'TEST ONLY modular IF sources'}
    preview=api('/api/plans/preview',body)
    saved=api('/api/plans/save',{**body,'annotations':preview['annotations'],'confirmation':preview['confirmation']})
    assert len(saved['branches'])==len(SCENARIOS)

    for kind,opponent in SCENARIOS:
        _,folder=enter(main_id,point,kind,opponent,'TEST ONLY live '+kind)
        sid=sid_fn();prefix=(folder/'native.jsonl').read_bytes()
        api('/api/modular/dispatch',{'consumer':'duel','intent':'configure','id':sid,'sources':[main_id],
            'preference':'shortest','precise':False,'goal':[CHIXIAO,BARONNE]})
        # Enable while the opponent is still making its real response. No
        # starting-hand reset or route replacement is needed after it resolves.
        api('/api/modular/auto',{'id':sid,'enabled':True})
        respond(folder,opponent,leave_own=True)
        done=wait(lambda:(v if not (v:=api('/api/modular/state/'+sid))['auto'] and not v['busy'] else None),timeout=300)
        (Path(evidence)/'modular-if-latest.json').write_text(json.dumps(done,ensure_ascii=False,indent=2),encoding='utf-8')
        assert done['reason']=='已到达所选路线的实际终场',(kind,done['reason'],(done.get('result') or {}).get('rejected'))
        assert (folder/'native.jsonl').read_bytes().startswith(prefix)
        assert any(a['kind']=='terminal_reached' and a.get('source',{}).get('route')==branches[kind] for a in done['audit'])
        assert any(a['kind']=='terminal_reached' and a['original_goal_met'] is False for a in done['audit'])
        report=finish()
        assert sum(a['kind']=='summon' and any(c.get('code')==MOYE for c in a.get('cards',[])) for a in report['actions'])==1
        results.append({'kind':kind,'status':done,'report_id':sid})
        print('PASS active AI survives actual interruption and dispatches a saved IF extender',kind,flush=True)
    start(SWORD,[MOYE,ASHUNA,N,N,N],'IF negative missing Longyuan')
    act('summon',MOYE,cards=[ASHUNA],zones=[(0,4,0),(0,4,1)],triggers=[MOYE])
    negative=finish()
    action=next(a for a in negative['actions'] if a.get('kind')=='effect' and any(c.get('code')==MOYE for c in a.get('cards',[])))
    negative_point=next(p for p in negative['branch_points'] if p['player']==1 and p['action_id']==action['id'])
    _,folder=enter(negative['id'],negative_point,'effect_negated',[IMPERM],'TEST ONLY missing extender')
    respond(folder,[IMPERM]);sid=sid_fn();before=current()
    api('/api/modular/configure',{'id':sid,'sources':[main_id],'preference':'shortest','precise':False,'goal':[CHIXIAO,BARONNE]})
    api('/api/modular/auto',{'id':sid,'enabled':True})
    stopped=wait(lambda:(v if not (v:=api('/api/modular/state/'+sid))['auto'] and not v['busy'] else None),timeout=120)
    assert not stopped['result']['candidates'],stopped['reason']
    assert current()==before,'Missing extender must not reset or consume the live state'
    results.append({'kind':'missing extender','status':stopped});finish()
    print('PASS missing extender pauses without a fabricated route, redraw or repeated normal summon',flush=True)
    (Path(evidence)/'modular-if-routes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
