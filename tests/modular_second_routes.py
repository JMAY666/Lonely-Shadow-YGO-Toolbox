"""Actual second-turn replay, public board clearing and read-only continuation."""
from copy import deepcopy
from pathlib import Path
import json
import time
import uuid

from modular_decisions import model
from modular_salamangreat import DECK, GAZELLE, ROAR, BALELYNX, SANCTUARY, NORMAL, recipe_driver

RAIGEKI = 12580477
ASH, ALUBER, FUSION = 14558127, 62962630, 44362883


def run(runtime, evidence, api, current, answer, choose, save, finish, use_session, wait, sid_fn, tags):
    runtime, evidence = Path(runtime), Path(evidence)
    act, settle = recipe_driver(current, answer, choose)
    deck = deepcopy(DECK)
    for _ in range(6): deck['main'].remove(NORMAL)
    deck['main'] += [RAIGEKI] * 3 + [ASH] * 3
    opening = [RAIGEKI, GAZELLE, NORMAL, NORMAL, NORMAL]

    def start(opponent_hand=None, own_hand=None, use_ash=False):
        opponent_hand = opponent_hand or [NORMAL]
        own_hand = own_hand or opening
        opponent_deck = {'main': [NORMAL] * (40 - len(opponent_hand) - 1) + list(opponent_hand) + [FUSION], 'extra': [], 'side': []}
        saved = api('/api/decks', {'name': 'TEST ONLY second routes ' + uuid.uuid4().hex[:7], 'deck': deck, 'tag_selection': tags})
        sid = api('/api/start', {'deck_id': saved['id'], 'design': {'name': 'TEST ONLY second route native origin',
            'revision': saved['revision'], 'turn_order': 'second', 'conditions': {'hand_count': 5, 'slots': own_hand, 'banned': []},
            'opponent_ai': True, 'opponent_config': {'name': 'TEST ONLY public monster',
                'deck': opponent_deck,
                'conditions': {'hand_count': len(opponent_hand), 'slots': opponent_hand, 'banned': []}}}})['id']
        use_session(sid)
        for _ in range(30):
            state = current(); prompt = model(state['raw'], state['state'], state.get('effects'))
            if prompt['message'] == 11 and state['state']['turn'] == 2:
                assert any(c['controller'] == 1 and c['location'] == 4 for c in state['state']['cards'])
                return saved
            decline = next((c for c in prompt['choices'] if use_ash and c['semantic']['kind'] in ('activate', 'yes') and
                            (c.get('card') or {}).get('code') == ASH), None)
            decline = decline or next((c for c in prompt['choices'] if c['semantic']['kind'] in ('pass', 'no')), None)
            assert decline, prompt
            answer(decline['response'], state)
        raise AssertionError('Own second turn not reached')

    start()
    act('activate', RAIGEKI, zones=[(0, 8, 0)])
    act('summon', GAZELLE, cards=[ROAR], zones=[(0, 4, 1)], triggers=[GAZELLE])
    act('special', BALELYNX, cards=[GAZELLE, SANCTUARY], zones=[(0, 4, 5)], triggers=[BALELYNX])
    source = save(mark_field=True, mark_codes=[BALELYNX])
    print('PASS recorded second-turn clearing and Salamangreat source', flush=True)
    saved = start()
    actual_sid = sid_fn()
    journal = runtime / '_trainer/sessions' / actual_sid / 'native.jsonl'
    doc = api('/api/second-duel/start', {'request_id': uuid.uuid4().hex, 'deck_id': saved['id'],
        'deck_revision': saved['revision'], 'opening': opening})
    original = deepcopy(doc['input'])

    def call(action, **extra):
        nonlocal doc
        result = api('/api/second-duel/route-' + action, {'id': doc['id'], 'round_id': doc['input']['round_id'],
            'revision': doc['revision'], **extra})
        if 'current' in result: doc = result
        return result

    available = call('sources')
    assert any(r['id'] == actual_sid for r in available['records'])
    before = journal.read_bytes()
    call('sync', source_id=actual_sid, confirmed=True)
    assert doc['route_panel']['current'], doc['route_panel']
    assert len(doc['current']['hand']) == 6 and doc['input'] == original
    assert journal.read_bytes() == before
    assert all(c.get('code') is None for h in doc['native_history'] for c in h['state']['cards']
               if c.get('controller') == 1 and c['location'] in (1, 2, 64))
    assert not any(c['controller'] == 1 and c['location'] in (1, 2, 64) for c in doc['current']['cards'])

    def generate():
        nonlocal doc
        call('generate', sources=[source['id']], preference='shortest', goal='clear')
        value = wait(lambda: (r if (r := api('/api/second-duel/state', {'id': doc['id']}))['route_panel']['status'] != 'running' else None), timeout=90)
        doc = value
        assert doc['route_panel']['status'] == 'ready', doc['route_panel']
        result = doc['route_panel']['result']
        assert result['candidates'], result
        assert all(not any(c['controller'] == 1 and c['location'] == 4 for c in row['terminal']['cards']) for row in result['candidates'])
        return result['candidates'][0]

    candidate = generate()
    assert journal.read_bytes() == before, 'Planning must never submit source inputs'
    current_before = deepcopy(doc['current'])
    call('choose', candidate=candidate['id'])
    assert doc['current'] == current_before and doc['input'] == original
    assert len(doc['route_history'][0]['choices']) == 1
    print('PASS complete second-turn replay and conditional clearing route preserve source journal and immutable opening', flush=True)
    history = deepcopy(doc['native_history'])
    route_history = deepcopy(doc['route_history'])

    # The actual player summons first instead of following the planned order.
    act('summon', GAZELLE, cards=[ROAR], zones=[(0, 4, 1)], triggers=[GAZELLE])
    assert not api('/api/second-duel/state', {'id': doc['id']})['route_panel']['current']
    try: call('choose', candidate=candidate['id'])
    except RuntimeError as error: assert '旧路线' in str(error)
    else: raise AssertionError('Stale route adopted')
    call('sync', source_id=actual_sid, confirmed=True)
    assert doc['native_history'][:len(history)] == history
    assert doc['route_history'] == route_history and doc['input'] == original
    assert doc['current']['native_rules']['normal_summons_used'][0] == 1
    before = journal.read_bytes()
    followup = generate()
    assert all(not any(s.get('kind') == 'summon' for s in step.get('bound_decision', {}).get('selection', [])) for step in followup['steps'])
    assert journal.read_bytes() == before
    print('PASS actual deviation preserves executed history, spends the normal summon and replans only the remaining clear-and-Link route', flush=True)
    (evidence / 'second-routes-ui.json').write_text(json.dumps({'doc_id': doc['id'], 'source_id': actual_sid, 'plan_id': source['id']}, indent=2), encoding='utf-8')
    (evidence / 'second-routes-native.json').write_text(json.dumps({'checks': ['exact_replay','clear_public_monster','immutable_opening','no_source_inputs','hidden_state_masked','actual_deviation','spent_normal_summon','stale_rejection'],
        'initial_candidate': candidate, 'followup': followup}, ensure_ascii=False, indent=2), encoding='utf-8')
    finish()
    api('/api/second-duel/close', {'id': doc['id'], 'round_id': doc['input']['round_id']})

    # The AI actually responds with Ash. Its hidden hand never became a source
    # for the prior no-response recommendation; only the observed result enters.
    saved = start(opponent_hand=[NORMAL, ASH])
    actual_sid = sid_fn(); journal = runtime / '_trainer/sessions' / actual_sid / 'native.jsonl'
    doc = api('/api/second-duel/start', {'request_id': uuid.uuid4().hex, 'deck_id': saved['id'], 'deck_revision': saved['revision'], 'opening': opening})
    call('sync', source_id=actual_sid, confirmed=True)
    first = generate(); prefix = deepcopy(doc['native_history'])
    act('summon', GAZELLE, cards=[ROAR], zones=[(0, 4, 1)], triggers=[GAZELLE])
    assert any(c['controller'] == 1 and c.get('code') == ASH and c['location'] == 16 for c in current()['state']['cards'])
    call('sync', source_id=actual_sid, confirmed=True)
    assert doc['native_history'][:len(prefix)] == prefix
    actual_response = generate()
    assert not any(any(s.get('card', {}).get('code') == GAZELLE and s.get('kind') in ('activate', 'yes')
                       for s in step.get('bound_decision', {}).get('selection', [])) for step in actual_response['steps'])
    print('PASS an actually observed opponent Ash response preserves the public prefix and replans from the negated effect', flush=True)
    finish(); api('/api/second-duel/close', {'id': doc['id'], 'round_id': doc['input']['round_id']})

    # Opponent turn -> real hand-trap cost -> actual normal draw -> own route.
    spent_opening = [ASH, RAIGEKI, GAZELLE, NORMAL, NORMAL]
    saved = start(opponent_hand=[ALUBER], own_hand=spent_opening, use_ash=True)
    actual_sid = sid_fn(); journal = runtime / '_trainer/sessions' / actual_sid / 'native.jsonl'
    assert any(c['controller'] == 0 and c['code'] == ASH and c['location'] == 16 for c in current()['state']['cards'])
    doc = api('/api/second-duel/start', {'request_id': uuid.uuid4().hex, 'deck_id': saved['id'], 'deck_revision': saved['revision'], 'opening': spent_opening})
    call('sync', source_id=actual_sid, confirmed=True)
    assert len(doc['current']['hand']) == 5 and doc['input']['opening']['cards'] == spent_opening
    assert any(c['code'] == ASH and c['location'] == 16 for c in doc['current']['cards'])
    spent_route = generate()
    print('PASS real first-turn hand-trap consumption plus normal draw yields five current cards and a rule-verified remaining route', flush=True)
    (evidence / 'second-routes-ui.json').write_text(json.dumps({'doc_id': doc['id'], 'source_id': actual_sid, 'plan_id': source['id']}, indent=2), encoding='utf-8')
    (evidence / 'second-routes-response.json').write_text(json.dumps({'opponent_ash_followup': actual_response,
        'spent_handtrap_followup': spent_route, 'current_hand': doc['current']['hand'], 'opening': spent_opening}, ensure_ascii=False, indent=2), encoding='utf-8')
    finish()
