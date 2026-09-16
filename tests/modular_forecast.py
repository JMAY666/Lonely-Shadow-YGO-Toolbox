"""Actual background forecast, declared random outcomes and an Ash interruption."""
from collections import Counter
import json
import time
from pathlib import Path
from urllib.parse import quote

from modular_salamangreat import recipe_driver

N, POT, CHARGE, RYKO, ASH = 1184620, 55144522, 94886282, 21502796, 14558127
DECK = {'main': [POT, CHARGE, RYKO] + [N]*37, 'extra': [], 'side': []}


def run(runtime, evidence, api, start, current, answer, choose, save):
    act, settle = recipe_driver(current, answer, choose)
    start(DECK, [N]*3, 'forecast normal continuation')
    act('summon', N, zones=[(0,4,0)]); normal = save()
    start(DECK, [POT,N,N], 'forecast random draw')
    act('activate', POT, zones=[(0,8,0)]); draw = save()
    start(DECK, [CHARGE,N,N], 'forecast random mill')
    act('activate', CHARGE, zones=[(0,8,0)], cards=[RYKO]); mill = save()
    (Path(evidence)/'forecast-sources.json').write_text(json.dumps({'draw':{'plan':draw['id'],'deck':draw['selected_deck']}}),'utf8')
    history = api('/api/history'); results = []
    def dispatch(intent, **body): return api('/api/modular/dispatch', {'consumer':'duel','intent':intent,**body})['result']
    for name, source, opening, zone, cards in [('draw',draw,[POT,N,N],2,[N,N]),('mill',mill,[CHARGE,N,N],16,[N,N,N])]:
        saved = api('/api/deck?id='+quote(source['selected_deck']))
        value = dispatch('plan', deck_id=saved['id'], revision=saved['revision'], hand_count=3, hand=opening, sources=[source['id']], preference='shortest')
        sid = value['id']
        try:
            assert api('/api/history') == history
            assert api('/api/native/status?id='+sid)['visible'] is False
            candidate = next(c for c in value['result']['candidates'] if c.get('observation_required'))
            assert zone in candidate['observation_required'], candidate
            assert any(c.get('unknown') for c in candidate['terminal']['cards'] if c['location']==zone)
            adopted = dispatch('plan-adopt', id=sid, candidate=candidate['id'])
            index = len(candidate['steps'])-1
            for i in range(index): dispatch('plan-confirm', id=sid, route=adopted['route'], index=i)
            corrected = dispatch('plan-observe', id=sid, route=adopted['route'], index=index, kind=name, cards=cards)
            assert corrected['prefix'][-1]['observation']['cards']==cards
            assert corrected['confirmed']==index+1
            assert corrected['result']['candidates'], corrected
            actual = corrected['prefix'][-1]['state']['cards']
            assert sum(c.get('code')==N and c['location']==zone for c in actual)>=len(cards)
            results.append({'kind':name,'steps':len(candidate['steps']),'continuations':len(corrected['result']['candidates'])})
            print('PASS forecast',name,'actual cards become known and remaining route is regenerated',flush=True)
        finally: dispatch('plan-close', id=sid)
    saved=api('/api/deck?id='+quote(draw['selected_deck']))
    value=dispatch('plan', deck_id=saved['id'],revision=saved['revision'],hand_count=3,hand=[POT,N,N],sources=[draw['id'],normal['id']],preference='shortest')
    sid=value['id']
    try:
        candidate=next(c for c in value['result']['candidates'] if c.get('observation_required'))
        adopted=dispatch('plan-adopt',id=sid,candidate=candidate['id'])
        index=next(i for i,s in enumerate(candidate['steps']) if any(c.get('kind')=='activate' and c.get('card',{}).get('code')==POT for c in s['decision']['selection']))
        for i in range(index):dispatch('plan-confirm',id=sid,route=adopted['route'],index=i)
        try:dispatch('plan-observe',id=sid,route=adopted['route'],index=index,kind='interruption',cards=[ASH,N])
        except RuntimeError as error:assert '手牌费用' in str(error),str(error)
        else:raise AssertionError('An unspent reported hand cost must be rejected')
        corrected=dispatch('plan-observe',id=sid,route=adopted['route'],index=index,kind='interruption',cards=[ASH])
        assert corrected['prefix'][-1]['observation']['cards']==[ASH]
        assert corrected['result']['candidates'],corrected
        assert all(not c.get('unknown') for c in corrected['prefix'][-1]['state']['cards'] if c['controller']==0 and c['location']==2)
        results.append({'kind':'interruption','continuations':len(corrected['result']['candidates'])})
        print('PASS reported Ash resolves through the core and replans a normal-summon continuation',flush=True)
    finally:dispatch('plan-close',id=sid)
    assert api('/api/history')==history
    start(DECK,[N]*3,'forecast parallel live expansion')
    live=next(row['id'] for row in api('/api/history') if row['status']=='running')
    journal=Path(runtime)/'_trainer/sessions'/live/'native.jsonl';before=journal.read_bytes()
    saved=api('/api/deck?id='+quote(normal['selected_deck']))
    value=dispatch('plan',deck_id=saved['id'],revision=saved['revision'],hand_count=3,hand=[N]*3,sources=[normal['id']],preference='shortest')
    assert value['result']['candidates']
    dispatch('plan-close',id=value['id'])
    assert journal.read_bytes()==before,'Background forecast must preserve another live expansion'
    assert next(row['id'] for row in api('/api/history') if row['status']=='running')==live
    api('/api/stop',{'id':live})
    for _ in range(200):
        if not any(row['status'] in ('running','starting','stopping') for row in api('/api/history')):break
        time.sleep(.05)
    else:raise AssertionError('Parallel live fixture did not finish')
    print('PASS temporary planning preserves the input journal and lifetime of an independent live expansion',flush=True)
    (Path(evidence)/'forecast-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),'utf8')
