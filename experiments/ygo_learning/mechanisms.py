"""Sixty fresh, parameterized, real-engine contract fixtures for P1."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
import time

from native_session import ROOT
from contract_v2 import build, feature_arrays, digest, Unsupported
sys.path.insert(0,str(ROOT/'tests'))
from modular_salamangreat import recipe_driver
from modular_decisions import model, canonical_state, semantic_response
from module_conditions import facts_from_report

NORMAL,POT,AXE,MOYE,LONGYUAN,CHI,CHENG,TOKEN=1184620,55144522,40619825,20001443,93490856,69248256,96633955,20001444
# Card names/IDs and source recipes are checked against the local pinned database.
SS_CHIXIAO=69248256
SS_CHENGYING=96633955
ASHUNA,LTOKEN,BARONNE,MONK,ASH,ROTA,ONE,LEVEL1,IP=23431858,93490857,84815190,32519092,14558127,32807846,2295440,27125110,65741786


def deck(*cards,extra=()):
    main=list(cards)
    return {'main':main+[NORMAL]*(40-len(main)),'extra':list(extra),'side':[]}


class Harness:
    def __init__(self, session, catalog, output):
        self.s,self.catalog,self.output=session,catalog,Path(output)
        self.case=None;self.steps=[];self.results=[]
        self.act,self.settle=recipe_driver(self.current,self.answer,self.choose)

    def current(self):return self.s.current()

    def answer(self, raw, expected=None):
        before=expected or self.current()
        bundle=build(before,self.catalog)
        # Binding uses the exact raw alias when possible; set-selection order is
        # normalized only by the core's existing semantic decoder for gold recipes.
        indexes=[i for i,c in enumerate(bundle['candidates']) if raw in c['responses']]
        if not indexes:
            p=model(before['raw'],before['state'],before.get('effects'))
            sem=semantic_response(p,raw)
            key=lambda x:json.dumps(sorted(x.get('selection',[]),key=lambda r:json.dumps(r,sort_keys=True)),sort_keys=True)
            indexes=[i for i,c in enumerate(bundle['candidates']) if key(semantic_response(p,c['response']))==key(sem)]
        if len(indexes)!=1:raise AssertionError('Controlled response missing/ambiguous in v2 candidates')
        following=self.s.answer(before,raw)
        self.steps.append({'before':before,'response':raw,'candidate_index':indexes[0],
                           'after':following,'actor':bundle['observation']})
        return following

    def choose(self, kind=None, code=None, effect=None, location=None, place=None, option=None, index=0):
        state=self.current();p=model(state['raw'],state['state'],state.get('effects'))
        choices=[c for c in p['choices'] if (kind is None or c['semantic']['kind']==kind)
            and (code is None or c['semantic'].get('card',{}).get('code')==code)
            and (effect is None or (c.get('effect') or {}).get('description')==effect)
            and (location is None or c['semantic'].get('card',{}).get('location')==location)
            and (place is None or c['semantic'].get('place')==list(place))
            and (option is None or c['semantic'].get('value')==option)]
        if not choices:raise AssertionError({'wanted':[kind,code,effect,location,place,option],'prompt':p})
        raw=choices[index]['response']
        if p['mode']=='cards':raw=bytes([1,raw]).hex()
        elif p['mode']=='sum':raw=bytes([1+p['mandatory'],*range(p['mandatory']),raw]).hex()
        return self.answer(raw,state)

    def start(self, group, number, cards, hand, opponent=None, responses=False):
        self.case=f'{group}-{number+1}';self.steps=[]
        self.began=time.perf_counter()
        return self.s.start(cards,hand,self.case,opponent,responses)

    def finish(self, assertions, report_check=None, end_turn=False):
        state=self.current();probe=self.s.probe(state)
        assert probe['status']=='ok',probe
        assert canonical_state(probe['state'])==canonical_state(state['state'])
        assert probe['learning']==state['learning']
        bundle=build(state,self.catalog);feature_arrays(bundle)
        if end_turn:
            after=self.choose('end_turn')
            # End-turn is a request, not the completed boundary. These controlled
            # demonstrations explicitly decline any remaining optional effects.
            for _ in range(20):
                if after['state']['turn']>state['state']['turn']:break
                prompt=model(after['raw'],after['state'],after.get('effects'))
                choices=[c for c in prompt['choices'] if c['semantic']['kind'] in ('no','pass')]
                assert len(choices)==1,('Unexpected mandatory end-phase choice',prompt)
                after=self.answer(choices[0]['response'],after)
            else:raise AssertionError('End phase exceeded decision bound')
            last=self.s.probe(after)
            assert last['status']=='ok' and canonical_state(last['state'])==canonical_state(after['state'])
            assert last['learning']==after['learning']
        result=self.s.finish()
        if report_check:report_check(result['report'])
        record={'case':self.case,'status':'passed','assertions':assertions,'steps':self.steps,
                'session':result,'final_replay_seconds':probe['transport_seconds'],
                'elapsed_seconds':time.perf_counter()-self.began}
        (self.output/(self.case+'.json')).write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
        self.results.append({'case':self.case,'status':'passed','assertions':assertions,
                             'responses':len(self.steps),'seconds':record['elapsed_seconds']})
        print('PASS',self.case,assertions,flush=True)
        return result

    def reject_probe(self, state, response, expected):
        before=(self.s.folder/'native.jsonl').read_bytes()
        result=self.s.probe(state,[state['raw']+':'+response])
        assert result.get('error') in expected,result
        current=self.current()
        assert current['version']==state['version'] and canonical_state(current['state'])==canonical_state(state['state'])
        assert (self.s.folder/'native.jsonl').read_bytes()==before


def run(session, catalog, output, groups=None, variants=5,first_variant=1):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    h=Harness(session,catalog,out)
    session.active_harness=h
    for code,name in ((AXE,'恶魔之斧'),(ONE,'一对一'),(LEVEL1,'千眼邪教神'),(ROTA,'增援')):
        assert catalog[code]['name']==name,(code,catalog[code]['name'],name)
    requested=set(groups or ('duplicates','costs','chains','negation','limits','dynamic','random',
                             'zones','choices','stale','replay','privacy'))
    for i in range(first_variant-1,variants):
        if 'duplicates' in requested:
            s=h.start('duplicates',i,deck(*([NORMAL]*5)),[NORMAL]*(i+1))
            hand=[c for c in s['state']['cards'] if c['controller']==0 and c['location']==2]
            assert len(hand)==i+1 and len({c['instance_id'] for c in hand})==i+1
            b=build(s,catalog);assert sum(c['location']==2 and c['controller']==0 for c in b['observation']['cards'])==i+1
            h.finish(['opening_count','duplicate_instances','full_replay'])
        if 'costs' in requested:
            h.start('costs',i,deck(LONGYUAN,ASHUNA,extra=[BARONNE]),[LONGYUAN,ASHUNA]+[NORMAL]*i)
            h.act('activate',LONGYUAN,cards=[ASHUNA],zones=[(0,4,i),(0,4,(i+1)%5)],
                  yes_descriptions=[LONGYUAN*16+2])
            s=h.current()
            assert any(c['code']==ASHUNA and c['location']==16 for c in s['state']['cards'])
            assert s['state']['normal_summons_used'][0]==0
            h.act('special',BARONNE,cards=[LONGYUAN,LTOKEN],zones=[(0,4,i)],triggers=[LONGYUAN])
            s=h.current();bar=next(c for c in s['state']['cards'] if c['code']==BARONNE and c['location']==4)
            assert len(bar['material_instance_ids'])==2 and s['state']['lp'][1]==6800
            h.finish(['actual_discard_cost','two_synchro_materials','damage_resolution'])
        if 'chains' in requested:
            h.start('chains',i,deck(*([MOYE,ASHUNA,LONGYUAN]*3),extra=[CHI]),[MOYE,ASHUNA]+[NORMAL]*i)
            h.act('summon',MOYE,cards=[ASHUNA],zones=[(0,4,i),(0,4,(i+1)%5)],triggers=[MOYE])
            triggers=[CHI,MOYE] if i%2==0 else [MOYE,CHI]
            h.act('special',CHI,cards=[MOYE,TOKEN],effect_cards={(CHI,CHI*16):[LONGYUAN]},
                  zones=[(0,4,i)],triggers=triggers)
            assert any(c['code']==LONGYUAN and c['location']==2 for c in h.current()['state']['cards'])
            # Empty response windows may be acknowledged by the native client
            # before the collector returns. The full journal remains the oracle.
            rows=[json.loads(line) for line in (session.folder/'native.jsonl').read_text(encoding='utf-8').splitlines()]
            assert any(row.get('state',{}).get('chain_depth',0)>=2 for row in rows)
            h.finish(['simultaneous_trigger_choices','chain_depth','search_and_draw_resolution'])
        if 'negation' in requested:
            opponent={'name':'TEST ONLY Ash response','deck':deck(ASH,ASH,ASH),'opening':[ASH]+[NORMAL]*4}
            cards=deck(LONGYUAN,ASHUNA,POT,extra=[BARONNE]) if i==4 else deck(POT)
            before=h.start('negation',i,cards,[LONGYUAN,ASHUNA,POT] if i==4 else [POT]+[NORMAL]*i,opponent,True)
            if i==4:
                h.act('activate',LONGYUAN,cards=[ASHUNA],zones=[(0,4,0),(0,4,1)],yes_descriptions=[LONGYUAN*16+2])
                h.act('special',BARONNE,cards=[LONGYUAN,LTOKEN],zones=[(0,4,0)],triggers=[LONGYUAN])
                before=h.current()
            h.act('activate',POT,zones=[(0,8,i)],triggers=[BARONNE] if i==4 else [])
            after=h.current()
            count=lambda s,p:sum(c['controller']==p and c['location']==2 for c in s['state']['cards'])
            assert count(after,0)==count(before,0)+(1 if i==4 else -1) and count(after,1)==4
            def check_negation(report):
                facts=facts_from_report(report)
                if i==4:
                    # Production IF facts intentionally concern our own effects.
                    # This fixture negates the opponent: inspect the raw event link.
                    events={event['id']:event for event in report['events']}
                    assert any(event.get('message')==75 and any(c.get('code')==ASH and c.get('controller')==1
                        for c in events.get(event.get('activation_ref'),{}).get('cards',[])) for event in events.values())
                else:assert any(f['kind']=='effect_negated' and f.get('code')==POT for f in facts),facts
                assert not any(f['kind']=='activation_negated' and f.get('code')==POT for f in facts)
            h.finish(['opponent_cost','activation_negated_and_spell_resolves' if i==4 else 'effect_not_activation_negated',
                      'actual_draw_result'],check_negation)
        if 'limits' in requested:
            h.start('limits',i,deck(ASHUNA,MOYE,LONGYUAN,extra=[MONK,CHI]),[ASHUNA,MOYE,LONGYUAN]+[NORMAL]*i)
            h.act('activate',ASHUNA,location=2,zones=[(0,4,i)])
            before=model(h.current()['raw'],h.current()['state'],h.current().get('effects'))
            assert any(c['semantic']['kind']=='special' and c['semantic'].get('card',{}).get('code')==MONK for c in before['choices'])
            h.act('summon',MOYE,cards=[LONGYUAN],zones=[(0,4,(i+1)%5),(0,4,(i+2)%5)],triggers=[MOYE])
            state=h.current();p=model(state['raw'],state['state'],state.get('effects'))
            assert state['state']['normal_summons_used'][0]==1
            assert any(x['player']==0 and x['used']>0 for x in state['state']['effect_usage'])
            assert not any(c['semantic']['kind']=='special' and c['semantic'].get('card',{}).get('code')==MONK for c in p['choices'])
            h.reject_probe(state,'00000000',{'illegal_response'})
            h.finish(['normal_summon_limit','effect_usage_recorded','token_lock_with_eligible_link_material'])
        if 'dynamic' in requested:
            h.start('dynamic',i,deck(NORMAL,AXE),[NORMAL,AXE]+[NORMAL]*3)
            h.act('summon',NORMAL,zones=[(0,4,i)])
            s=h.current();c=next(c for c in s['state']['cards'] if c['controller']==0 and c['location']==4)
            base=next(x for x in s['learning']['cards'] if x['instance_id']==c['instance_id'])['attack']
            h.act('activate',AXE,cards=[(NORMAL,4)],zones=[(0,8,i)])
            s=h.current();now=next(x for x in s['learning']['cards'] if x['instance_id']==c['instance_id'])
            assert now['attack']==base+1000 and now['base_attack']==catalog[NORMAL]['atk']
            h.finish(['equip_dynamic_attack','base_attack_separate','query_replay'])
        if 'zones' in requested:
            h.start('zones',i,deck(NORMAL),[NORMAL]*5)
            h.choose('summon',NORMAL)
            s=h.current();p=model(s['raw'],s['state'],s.get('effects'))
            assert p['mode']=='places'
            h.reject_probe(s,'000407',{'illegal_response'})
            h.choose(place=(0,4,i));h.settle()
            assert any(c['location']==4 and c['sequence']==i and c['controller']==0 for c in h.current()['state']['cards'])
            h.finish(['allowed_zone','invalid_zone_rejected','instance_position'])
        if 'random' in requested:
            h.start('random',i,deck(POT),[POT]+[NORMAL]*i)
            before=h.current();h.act('activate',POT,zones=[(0,8,i)])
            after=h.current()
            count=lambda s:sum(c['controller']==0 and c['location']==2 for c in s['state']['cards'])
            assert count(after)==count(before)+1
            h.finish(['actual_draw_delta','consumed_spell','random_replay'])
        if 'choices' in requested:
            if i==0:
                h.start('choices',i,deck(MOYE,ASHUNA),[MOYE,ASHUNA,NORMAL])
                h.act('summon',MOYE,zones=[(0,4,0)],triggers=[])
                assert not any(c['code']==TOKEN and c['location']==4 for c in h.current()['state']['cards'])
                checks=['optional_effect_declined','no_token_or_reveal_cost']
            elif i in (1,2):
                h.start('choices',i,deck(ROTA),[ROTA]+[NORMAL]*i)
                h.choose('activate',ROTA);h.choose(place=(0,8,i))
                state=h.current();p=model(state['raw'],state['state'],state.get('effects'))
                assert p['mode']=='cards' and p['minimum']==1
                h.reject_probe(state,'ffffffff' if i==1 else '00',{'illegal_response'})
                h.settle(cards=[NORMAL])
                checks=['mandatory_selection','cancel_rejected' if i==1 else 'empty_selection_rejected']
            elif i==3:
                h.start('choices',i,deck(ONE,LEVEL1,ASHUNA),[ONE,ASHUNA]+[NORMAL]*3)
                h.choose('activate',ONE)
                if model(h.current()['raw'],h.current()['state'])['mode']=='places':h.choose(place=(0,8,0))
                state=h.current();b=build(state,catalog)
                assert model(state['raw'],state['state'])['mode']=='cards'
                options=[c for c in b['candidates'] if not c['public']['cancel']]
                assert len(options)>=2
                first=session.probe(state,[state['raw']+':'+options[0]['response']])
                second=session.probe(state,[state['raw']+':'+options[1]['response']])
                assert first['status']==second['status']=='ok'
                assert h.current()['version']==state['version']
                h.answer(options[1]['response'],state);h.settle(cards=[LEVEL1],zones=[(0,8,0),(0,4,0)])
                assert sum(c['controller']==0 and c['location']==2 for c in h.current()['state']['cards'])==3
                checks=['uncommitted_choice_replaced','cost_paid_once','selected_target_resolved']
            else:
                h.start('choices',i,deck(ASHUNA,NORMAL,extra=[IP]),[ASHUNA]+[NORMAL]*4)
                h.act('summon',NORMAL,zones=[(0,4,0)])
                h.act('activate',ASHUNA,location=2,zones=[(0,4,1)])
                h.choose('special',IP)
                assert model(h.current()['raw'],h.current()['state'])['message']==26
                h.choose('select',NORMAL)
                h.choose('unselect',NORMAL)
                h.choose('cancel_selection');h.settle()
                assert sum(c['controller']==0 and c['location']==4 for c in h.current()['state']['cards'])==2
                assert not any(c['code']==IP and c['location']==4 for c in h.current()['state']['cards'])
                checks=['material_select_unselect','cancel_summon','no_material_cost_on_cancel']
            h.finish(checks)
        if 'stale' in requested:
            s=h.start('stale',i,deck(NORMAL),[NORMAL]*(i+1))
            h.choose('summon',NORMAL)
            try:session.request('answer',s,['00000000'])
            except ValueError as error:assert str(error)=='stale_state'
            else:raise AssertionError('stale request accepted')
            h.choose(place=(0,4,i));h.settle()
            assert h.current()['state']['normal_summons_used'][0]==1
            h.finish(['stale_window_rejected','no_duplicate_summon','prefix_preserved'])
        if 'replay' in requested:
            s=h.start('replay',i,deck(NORMAL,POT),[NORMAL,POT]+[NORMAL]*i)
            initial=session.probe(s)
            assert initial['status']=='ok'
            p=model(s['raw'],s['state'],s.get('effects'))
            chosen=next(c for c in p['choices'] if c['semantic']['kind']=='summon')
            first=session.probe(s,[s['raw']+':'+chosen['response']])
            assert first['status']=='ok'
            h.answer(chosen['response'],s)
            assert canonical_state(first['state'])==canonical_state(h.current()['state'])
            h.choose(place=(0,4,i));h.settle()
            h.finish(['branch_prefix_replay','predicted_and_actual_state','no_live_probe_mutation'])
        if 'privacy' in requested:
            opponent={'name':'TEST ONLY hidden resources','deck':deck(POT), 'opening':[NORMAL]*5}
            s=h.start('privacy',i,deck(NORMAL,POT),[NORMAL]*(i+1),opponent)
            first=build(s,catalog);changed=deepcopy(s)
            own_deck=[c for c in changed['state']['cards'] if c['controller']==0 and c['location']==1]
            sequences=[c['sequence'] for c in own_deck][::-1]
            for c,seq in zip(own_deck,sequences):c['sequence']=seq
            for c in changed['state']['cards']:
                if c['controller']==1 and c['location'] in (1,2,64):c['code']=AXE
            second=build(changed,catalog)
            assert first['observation']==second['observation']
            assert [x['public'] for x in first['candidates']]==[x['public'] for x in second['candidates']]
            a,b=feature_arrays(first),feature_arrays(second)
            assert all((a[k]==b[k]).all() for k in a)
            missing=deepcopy(s);missing['learning']['cards']=[]
            try:build(missing,catalog)
            except Unsupported as error:assert str(error)=='known_card_dynamic_missing'
            else:raise AssertionError('missing dynamic data accepted')
            excess=deepcopy(s)
            excess['state']['cards']=[dict(s['state']['cards'][0],instance_id=10000+j) for j in range(161)]
            try:build(excess,catalog)
            except Unsupported as error:assert str(error)=='card_capacity'
            else:raise AssertionError('card overflow truncated')
            h.finish(['hidden_identity_invariance','deck_order_invariance','missing_dynamic_rejected','capacity_rejected'])
    missing=requested-{'duplicates','dynamic','zones','random','stale','replay','privacy','costs','chains','negation','limits','choices'}
    if missing:raise NotImplementedError('Fixture groups not yet implemented: '+','.join(sorted(missing)))
    return h.results


def demonstrations(session,catalog,output):
    from experiments.ygo_agent.run import read_deck
    import random
    public=read_deck(ROOT/'.local/ygo-agent-pilot/TenyiSword.ydk')
    opponent={'name':'TEST ONLY controlled response deck','deck':deck(ASH,ASH,ASH),'opening':[NORMAL]*5}
    fill=[c for c in public['main'] if c in (ASH,97268402,23434538,10045474)]
    rng=random.Random(8019);seen=set();hands=[]
    while len(hands)<5:
        hand=[MOYE,ASHUNA,*rng.sample(fill,3)]
        key=tuple(sorted(hand))
        if key in seen:continue
        seen.add(key);hands.append(hand)
    h=Harness(session,catalog,output);session.active_harness=h
    for i,hand in enumerate(hands):
        opponent['opening']=([ASH]+[NORMAL]*4) if i%2 else [NORMAL]*5
        h.start('demo',i,public,hand,opponent,i%2==1)
        h.settle()
        h.act('summon',MOYE,cards=[ASHUNA],zones=[(0,4,0),(0,4,1)],triggers=[MOYE])
        h.act('special',CHI,cards=[MOYE,TOKEN],effect_cards={(CHI,CHI*16):[LONGYUAN]},
              zones=[(0,4,0)],triggers=[CHI,MOYE])
        h.act('activate',LONGYUAN,cards=[ASHUNA],zones=[(0,4,1),(0,4,2)],yes_descriptions=[LONGYUAN*16+2])
        h.act('special',BARONNE,cards=[LONGYUAN,LTOKEN],zones=[(0,4,1)],triggers=[LONGYUAN])
        assert {CHI,BARONNE}<={c['code'] for c in h.current()['state']['cards'] if c['controller']==0 and c['location']==4}
        h.finish(['public_swordsoul_development_demo','actual_end_turn','full_replay'],end_turn=True)
    return h.results
