"""One actual native practice through the opponent window, own turn and review."""
from copy import deepcopy
from pathlib import Path
import json
import uuid

from modular_decisions import model
from modular_salamangreat import DECK, GAZELLE, SPINNY, BALELYNX, SANCTUARY, NORMAL, recipe_driver

ASH, ALUBER, FUSION, IMPERM, RAIGEKI = 14558127, 62962630, 44362883, 10045474, 12580477


def run(runtime, evidence, api, current, answer, choose, save, finish, use_session, wait, sid_fn, tags):
    runtime, evidence = Path(runtime), Path(evidence)
    act, settle = recipe_driver(current, answer, choose)
    deck = deepcopy(DECK)
    for _ in range(6): deck['main'].remove(NORMAL)
    deck['main'] += [RAIGEKI]*3 + [ASH]*3
    opening = [ASH, RAIGEKI, GAZELLE, NORMAL, NORMAL]

    def start(opponent):
        request=evidence/'modular-layout.request';request.write_text('layout',encoding='ascii');wait(lambda:not request.exists())
        saved = api('/api/decks', {'name': 'TEST ONLY second flow '+uuid.uuid4().hex[:6], 'deck': deck, 'tag_selection': tags})
        opposing = {'main': opponent + [FUSION] + [NORMAL]*(39-len(opponent)), 'extra': [], 'side': []}
        sid = api('/api/start', {'deck_id': saved['id'], 'design': {'name': 'TEST ONLY continuous second practice',
            'revision': saved['revision'], 'turn_order': 'second', 'conditions': {'hand_count': 5, 'slots': opening, 'banned': []},
            'opponent_ai': True, 'opponent_config': {'name': 'TEST ONLY Aluber and response cases', 'deck': opposing,
                'conditions': {'hand_count': len(opponent), 'slots': opponent, 'banned': []}}}})['id']
        use_session(sid)
        for _ in range(35):
            s = current(); p = model(s['raw'], s['state'], s.get('effects'))
            if s['state'].get('chains') and s['state']['chains'][0]['effect']['handler_code'] == ALUBER:
                assert any((c.get('card') or {}).get('code') == ASH for c in p['choices'])
                return saved
            decline = next((c for c in p['choices'] if c['semantic']['kind'] in ('pass','no')), None)
            assert decline, p
            answer(decline['response'], s)
        raise AssertionError('No covered opponent response window')

    def reach_own():
        for _ in range(40):
            s = current(); p = model(s['raw'], s['state'], s.get('effects'))
            if s['state']['turn'] == 2 and p['message'] == 11: return s
            decline = next((c for c in p['choices'] if c['semantic']['kind'] in ('pass','no')), None)
            assert decline, p
            answer(decline['response'], s)
        raise AssertionError('Own turn not reached')

    start([ALUBER]); choose('activate', ASH); reach_own()
    act('summon', GAZELLE, cards=[SPINNY], zones=[(0,4,1)], triggers=[GAZELLE])
    act('activate', SPINNY, location=16, zones=[(0,4,0)])
    act('activate', RAIGEKI, zones=[(0,8,0)])
    act('special', BALELYNX, cards=[GAZELLE,SANCTUARY], zones=[(0,4,5)], triggers=[BALELYNX])
    source = save(mark_field=True, mark_codes=[BALELYNX])
    print('PASS native source recorded across a real first-turn hand trap and second-turn clear-and-Link sequence', flush=True)

    reports = []
    for case, opponent, gazelle_zone, spinny_zone in [('pass',[ALUBER],1,0),('double_imperm',[ALUBER,IMPERM,IMPERM],0,1)]:
        saved = start(opponent); actual_sid = sid_fn()
        journal = runtime/'_trainer/sessions'/actual_sid/'native.jsonl'
        doc = api('/api/second-duel/start', {'request_id': uuid.uuid4().hex, 'deck_id': saved['id'], 'deck_revision': saved['revision'], 'opening': opening})
        original = deepcopy(doc['input'])
        def route(action, **extra):
            nonlocal doc
            doc = api('/api/second-duel/route-'+action, {'id':doc['id'],'round_id':doc['input']['round_id'],'revision':doc['revision'],**extra})
            return doc
        def event(kind, **payload):
            nonlocal doc
            doc = api('/api/second-duel/event', {'id':doc['id'],'round_id':doc['input']['round_id'],'revision':doc['revision'],
                'event_id':uuid.uuid4().hex,'kind':kind,'payload':payload})
        before = journal.read_bytes()
        route('sync', source_id=actual_sid, confirmed=True)
        assert doc['capabilities']['engine_reconstruction'] and not doc['capabilities']['routes']
        native = doc['current']['native_window']; assert native['recognized'] and native['effect_id']=='aluber.search'
        assert journal.read_bytes()==before, 'Opponent-window import must not submit any source input'
        if case == 'pass':
            request=evidence/'second-flow.request'; response=evidence/'second-flow-response.json'
            request.write_text(json.dumps({'id':doc['id']}),encoding='utf-8')
            wait(lambda:not request.exists(),timeout=120)
            response_data=json.loads(response.read_text(encoding='utf-8')); assert not response_data.get('error'), response_data
            doc=api('/api/second-duel/state',{'id':doc['id']})
        else:
            ash=next(c for c in doc['current']['cards'] if c['code']==ASH and c['location']==2)
            event('resource_role',card_id=ash['id'],role='free')
            s=doc['current'];event('verify',turn=s['turn'],turn_player=s['turn_player'],phase=s['phase'],lp=s['lp'],opponent_hand_count=s['opponent_hand_count'],confirmed=True)
            event('hint_window',card_id=native['card_id'],effect_id=native['effect_id'],link=1,top=1,speed=1,
                  protections=[],protections_checked=True,other_rules='none',grave_rule='normal',objective='stop_effect',environment='local',confirmed=True)
            doc=api('/api/second-duel/advice',{'id':doc['id'],'round_id':doc['input']['round_id'],'revision':doc['revision'],'request_id':uuid.uuid4().hex})
        hint=deepcopy(doc['advice']); assert hint['items'][0]['recommendation']=='use',hint
        event('choice',note='TEST ONLY player intends to use Ash; actual result will be synced')
        prior_events=deepcopy(doc['events']); prior_hint=deepcopy(doc['advice_history'])
        choose('activate',ASH); reach_own()
        stale=api('/api/second-duel/state',{'id':doc['id']}); assert not stale['advice']['current']
        route('sync',source_id=actual_sid,confirmed=True)
        assert doc['input']==original and len(doc['current']['hand'])==5
        assert doc['events'][:len(prior_events)]==prior_events and doc['advice_history']==prior_hint
        assert doc['capabilities']['routes']
        review=api('/api/second-duel/review-window',{'id':doc['id'],'advice_id':hint['id']})
        assert len([c for c in review['known_state']['cards'] if c['controller']==0 and c['location']==2])==5
        assert review['actual']['own_hand_departures']==[ASH]
        assert any(r['kind']=='effect_negated' for r in review['actual']['outcomes'])
        assert not any(r['kind']=='activation_negated' for r in review['actual']['outcomes'])
        assert all(not a['selection'] for a in doc['native_actions'] if a['player']==1)
        route('generate',sources=[source['id']],preference='shortest',goal='clear')
        doc=wait(lambda:(r if (r:=api('/api/second-duel/state',{'id':doc['id']}))['route_panel']['status']!='running' else None),timeout=90)
        assert doc['route_panel']['result']['candidates'],doc['route_panel']
        first_history=deepcopy(doc['native_history'])
        act('summon',GAZELLE,cards=[SPINNY],zones=[(0,4,gazelle_zone)],triggers=[GAZELLE])
        act('activate',SPINNY,location=16,zones=[(0,4,spinny_zone)])
        act('activate',RAIGEKI,zones=[(0,8,0)])
        route('sync',source_id=actual_sid,confirmed=True)
        assert doc['native_history'][:len(first_history)]==first_history
        assert api('/api/second-duel/review-window',{'id':doc['id'],'advice_id':hint['id']})==review,'Later information cannot rewrite the old review'
        targets=[p for e in doc['native_outcomes'] if e['kind']=='targets' for p in e['places'] if p['controller']==0 and p['location']==4]
        if case=='double_imperm':
            assert len({p['sequence'] for p in targets})>=2,targets
            assert sum(c['controller']==1 and c.get('code')==IMPERM and c['location']==16 for c in doc['current']['cards'])==2
            assert sum(c.get('disabled',False) for c in doc['current']['cards'] if c['controller']==0 and c['location']==4)==2
        route('generate',sources=[source['id']],preference='shortest',goal='clear')
        doc=wait(lambda:(r if (r:=api('/api/second-duel/state',{'id':doc['id']}))['route_panel']['status']!='running' else None),timeout=90)
        assert doc['route_panel']['result']['candidates'],doc['route_panel']
        assert all(not any(s.get('kind')=='summon' for s in step.get('bound_decision',{}).get('selection',[])) for c in doc['route_panel']['result']['candidates'] for step in c['steps'])
        reports.append({'case':case,'review':review,'targets':targets,'remaining':doc['route_panel']['result']})
        print('PASS continuous native second-player flow',case,'retains original information and replans after actual responses',flush=True)
        finish()
        if case=='pass':api('/api/second-duel/close',{'id':doc['id'],'round_id':doc['input']['round_id']})
    (evidence/'second-flow-results.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
    (evidence/'second-flow-ui.json').write_text(json.dumps({'id':doc['id'],'advice_id':hint['id']}),encoding='utf-8')
