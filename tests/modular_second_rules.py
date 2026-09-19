"""Mask Change and attack-order cases, using the pinned unmodified native core."""
from pathlib import Path
from copy import deepcopy
import json
import uuid

from modular_decisions import model
from modular_salamangreat import recipe_driver

N, MASK, SHADOW, DARKLAW, OFFER, FISSURE = 1184620, 21143940, 50720316, 58481572, 19230407, 81674782
THRASHER, ECON, RAIGEKI, MOON = 65367484, 98045062, 12580477, 14087893
FADER = 19665973


def run(runtime,evidence,api,start,current,answer,choose,finish,use_session,wait,sid_fn,tags):
    runtime,evidence=Path(runtime),Path(evidence)
    act,settle=recipe_driver(current,answer,choose)
    mask_deck={'main':[MASK]*3+[SHADOW]*3+[OFFER]*3+[FISSURE]*3+[N]*28,'extra':[DARKLAW]*3,'side':[]}
    results=[]
    for case in ('resolved','destroyed_target','redirected_to_banish'):
        start(mask_deck,[SHADOW,MASK,OFFER,FISSURE,N],'TEST ONLY Mask Change '+case)
        act('summon',SHADOW,zones=[(0,4,0)])
        if case=='redirected_to_banish':act('activate',FISSURE,zones=[(0,8,3)])
        act('activate',MASK,cards=[SHADOW,DARKLAW],zones=[(0,8,0),(0,8,1),(0,4,0)],
            triggers=[OFFER] if case=='destroyed_target' else [])
        state=deepcopy(current()['state']);report=finish()
        dark=[c for c in state['cards'] if c['controller']==0 and c['location']==4 and c['code']==DARKLAW]
        assert bool(dark)==(case!='destroyed_target'),case
        assert not any(e.get('message') in (75,76) for e in report['events']),case
        shadow=next(c for c in state['cards'] if c['controller']==0 and c['code']==SHADOW and c['location'] in (16,32))
        assert shadow['location']==(32 if case=='redirected_to_banish' else 16),case
        if dark:assert dark[0]['summon_info']&0xff000000!=0x43000000,'Mask Change is not a Fusion Summon'
        results.append({'case':'mask_'+case,'summoned':bool(dark),'shadow_zone':shadow['location'],'negation_events':0,'source':report['id']})
        print('PASS native Mask Change',case,'summoned',bool(dark),'negation events 0',flush=True)

    deck={'main':[THRASHER]*3+[ECON]*3+[RAIGEKI]*3+[MOON]*3+[N]*28,'extra':[],'side':[]}
    def begin(opponent,lp,hand,opponent_hand=None):
        opponent_hand=opponent_hand or [N]
        request=evidence/'modular-layout.request';request.write_text('layout',encoding='ascii');wait(lambda:not request.exists())
        saved=api('/api/decks',{'name':'TEST ONLY battle '+uuid.uuid4().hex[:6],'deck':deck,'tag_selection':tags})
        sid=api('/api/start',{'deck_id':saved['id'],'design':{'name':'TEST ONLY native attack-order case','revision':saved['revision'],
            'turn_order':'second','opponent_lp':lp,'conditions':{'hand_count':5,'slots':hand,'banned':[]},'opponent_ai':opponent,
            'opponent_config':{'name':'TEST ONLY battle target','deck':{'main':opponent_hand+[N]*(40-len(opponent_hand)),'extra':[],'side':[]},
                               'conditions':{'hand_count':len(opponent_hand),'slots':opponent_hand,'banned':[]}}}})['id']
        use_session(sid)
        for _ in range(30):
            s=current();p=model(s['raw'],s['state'],s.get('effects'))
            if p['message']==11 and s['state']['turn']==2:return saved
            decline=next(c for c in p['choices'] if c['semantic']['kind'] in ('pass','no'));answer(decline['response'],s)
        raise AssertionError('Own main phase not reached')

    cases=[('direct',True,1000),('defense',True,1000),('restriction',True,3000),('repeat',False,3000),('unknown',True,1000)]
    for case,opponent,lp in cases:
        hand=[THRASHER,ECON,RAIGEKI,MOON,N]
        saved=begin(opponent,lp,hand,[N,FADER] if case=='direct' else None)
        if case=='restriction':act('special',THRASHER,zones=[(0,4,1)])
        if case=='unknown':act('special',THRASHER,zones=[(0,4,0)])
        else:act('summon',N,zones=[(0,4,0)])
        if case=='defense':act('activate',ECON,cards=[N],zones=[(0,8,0)],options=[ECON*16])
        if case in ('direct','restriction'):act('activate',RAIGEKI,zones=[(0,8,0)])
        if case=='unknown':act('activate',MOON,cards=[N],zones=[(0,8,0)])
        actual_sid=sid_fn();journal=runtime/'_trainer/sessions'/actual_sid/'native.jsonl';before=journal.read_bytes()
        doc=api('/api/second-duel/start',{'request_id':uuid.uuid4().hex,'deck_id':saved['id'],'deck_revision':saved['revision'],'opening':hand})
        def call(action,**extra):
            nonlocal doc
            doc=api('/api/second-duel/route-'+action,{'id':doc['id'],'round_id':doc['input']['round_id'],'revision':doc['revision'],**extra});return doc
        call('sync',source_id=actual_sid,confirmed=True)
        initial=deepcopy(doc['current']);opening=deepcopy(doc['input']);revision=doc['revision']
        own=next(c for c in doc['current']['cards'] if c['controller']==0 and c['location']==4 and (case=='unknown' or c['code']==N))
        target=next((c for c in doc['current']['cards'] if c['controller']==1 and c['location']==4),None)
        order=[{'attacker':own['id'],'target':target['id'] if case in ('defense','unknown') else 'direct'}]
        if case=='repeat':order*=2
        if case=='restriction':
            thrasher=next(c for c in doc['current']['cards'] if c['controller']==0 and c['location']==4 and c['code']==THRASHER)
            # Card-face totals establish the deliberately misleading heuristic;
            # availability and actual damage are asserted from core results.
            assert sum(doc['catalog'][str(c['code'])]['atk'] for c in doc['current']['cards'] if c['controller']==0 and c['location']==4)==3600
            order.append({'attacker':thrasher['id'],'target':'direct'})
        if case=='unknown':
            assert target['code'] is None
            try:call('battle',request_id=uuid.uuid4().hex,order=order)
            except RuntimeError as error:assert '未知里侧' in str(error)
            else:raise AssertionError('Unrevealed target was simulated as known')
            assert 'battle_history' not in doc
            result={'status':'hidden_target_rejected'}
        else:
            call('battle',request_id=uuid.uuid4().hex,order=order)
            result=doc['battle_history'][-1]['result']
            assert doc['current']==initial and doc['input']==opening and doc['revision']==revision
            if case=='direct':
                assert result['conditional_lethal'] and result['lp_after'][1]==0,result
                assert str(FADER) not in json.dumps(result) and str(FADER) not in doc['catalog']
            elif case=='defense':
                assert result['status']=='validated' and result['lp_after'][1]==1000 and not result['conditional_lethal'],result
            else:
                assert result['status']=='incomplete' and len(result['steps'])==1 and result['lp_after'][1]==1500 and not result['conditional_lethal'],result
        assert journal.read_bytes()==before,'Isolated battle must not append source inputs or outcomes'
        results.append({'case':case,'result':result,'source':actual_sid})
        print('PASS native battle',case,json.dumps({k:result.get(k) for k in ('status','conditional_lethal','lp_after')},ensure_ascii=False),flush=True)
        if case=='repeat':
            # A real battle-phase transition invalidates the old preview. The
            # new battle checkpoint can be reconstructed without losing history.
            old=deepcopy(doc['native_history']);choose('battle')
            for _ in range(25):
                s=current();p=model(s['raw'],s['state'],s.get('effects'))
                if p['message']==10:break
                decline=next(c for c in p['choices'] if c['semantic']['kind'] in ('pass','no'));answer(decline['response'],s)
            assert not api('/api/second-duel/state',{'id':doc['id']})['route_panel']['current']
            call('sync',source_id=actual_sid,confirmed=True)
            assert doc['native_history'][:len(old)]==old and doc['route_panel']['battle_ready'] and not doc['route_panel']['route_ready']
            before_actions=len(api('/api/report/'+actual_sid)['actions'])
            choose('attack',N)
            for _ in range(25):
                s=current();p=model(s['raw'],s['state'],s.get('effects'))
                if p['message']==10:break
                decline=next(c for c in p['choices'] if c['semantic']['kind'] in ('pass','no'));answer(decline['response'],s)
            def battle_recorded():
                value=api('/api/report/'+actual_sid)
                return value if any(e.get('message')==114 for e in value['events']) else None
            report=wait(battle_recorded)
            assert len(report['actions'])==before_actions,'Routine battles must remain out of original expansion steps'
            assert any(e.get('message')==110 for e in report['events'])
            call('sync',source_id=actual_sid,confirmed=True)
            assert doc['current']['lp'][1]==1500
            call('battle',request_id=uuid.uuid4().hex,order=[{'attacker':own['id'],'target':'direct'}])
            assert not doc['battle_history'][-1]['result']['steps'] and not doc['battle_history'][-1]['result']['conditional_lethal']
            (evidence/'second-battle-ui.json').write_text(json.dumps({'id':doc['id']}),encoding='utf-8')
        finish()
        if case!='repeat':api('/api/second-duel/close',{'id':doc['id'],'round_id':doc['input']['round_id']})
    (evidence/'second-rules-native.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
