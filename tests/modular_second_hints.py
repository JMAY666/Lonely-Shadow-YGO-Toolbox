"""Bounded native cases for second-player hints, with explicit pass comparisons.

The caster is player 0 and the responder player 1 in these isolated fixtures.
This checks card interactions, not reconstruction of an external live duel.
"""
from pathlib import Path
import hashlib
import json
import time
import uuid

from modular_decisions import model
from modular_salamangreat import recipe_driver
from modular_cross_decks import SWORD, BRANDED, MOYE, TOKEN, ASHUNA, CHIXIAO, ALUBER, FUSION, ALBAZ, TRAGEDY, LUBELLION, N

ASH, IMPERM, OGRE, ORANGE, FAIRY, GREEN = 14558127, 10045474, 59438930, 17266660, 39552864, 21074344


def run(runtime, evidence, api, start, current, answer, choose, finish, use_session, wait, sid_fn):
    runtime, evidence = Path(runtime), Path(evidence)
    act, settle = recipe_driver(current, answer, choose)
    sources = {}
    for name in ('aluber', 'moye', 'fusion'):
        if name == 'moye':
            start(SWORD, [MOYE, ASHUNA, N, N, N], 'second hint Mo Ye')
            act('summon', MOYE, cards=[ASHUNA], zones=[(0, 4, 0), (0, 4, 1)], triggers=[MOYE])
            actor = MOYE
        elif name == 'aluber':
            start(BRANDED, [ALUBER, N, N, N, N], 'second hint Aluber')
            act('summon', ALUBER, cards=[FUSION], zones=[(0, 4, 0)], triggers=[ALUBER])
            actor = ALUBER
        else:
            start(BRANDED, [FUSION, FUSION, N, N, N], 'second hint Branded Fusion')
            act('activate', FUSION, cards=[LUBELLION, ALBAZ, TRAGEDY], zones=[(0, 8, 0), (0, 4, 0)])
            actor = FUSION
        report = finish()
        activation = next(a for a in report['actions'] if a.get('kind') == 'effect'
                          and any(c.get('code') == actor for c in a.get('cards', [])))
        point = next(p for p in report['branch_points'] if p['action_id'] == activation['id'] and p['player'] == 1)
        sources[name] = (report['id'], point, actor)
        print('PASS recorded native hint source', name, flush=True)

    def enter(source, hand, label):
        root_id, point, actor = sources[source]
        root = api('/api/report/' + root_id)
        root = api('/api/branches/create', {'id': root_id, 'revision': root['branches_revision'],
                    'checkpoint': point['checkpoint'], 'node_id': point['node_id']})
        branch = root['branches'][-1]
        root = api('/api/branches/update', {'id': root_id, 'branch_id': branch['id'], 'revision': root['branches_revision'],
                    'name': 'TEST ONLY ' + label, 'conditions': {'hand': hand, 'expected_action': point['action_id'],
                    'note': 'TEST ONLY finite hint interaction; no other responses', 'if': {'kind': 'unconditional', 'required': []}}})
        session = api('/api/branches/enter', {'id': root_id, 'branch_id': branch['id'], 'revision': root['branches_revision']})
        use_session(session['id'])
        folder = runtime / '_trainer/sessions' / session['id']
        wait(lambda: (value if (p := folder / 'branch-operation.json').exists()
                      and (value := json.loads(p.read_text(encoding='utf-8')))['status'] in ('ready', 'error') else None), timeout=60)
        assert json.loads((folder / 'branch-operation.json').read_text(encoding='utf-8'))['status'] == 'ready'
        return folder, point, actor

    def resolve(folder, code, should_activate):
        activated = False
        offers = []
        last = -1
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                node = json.loads((folder / 'modular-state.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                time.sleep(.03)
                continue
            if node['answered'] or node['version'] == last:
                time.sleep(.03)
                continue
            prompt = model(node['raw'], node['state'], node.get('effects'))
            choices = prompt['choices']
            if node['player'] == 0 and prompt['message'] == 11 and not node['state'].get('chain_depth'):
                assert activated == should_activate, (code, activated, should_activate, offers)
                return node, offers
            if len(choices) == 1 and choices[0]['semantic']['kind'] == 'pass':
                time.sleep(.03)
                continue
            wanted = next((c for c in choices if c['semantic']['kind'] in ('activate', 'yes')
                           and (c.get('card') or {}).get('code') == code), None) if node['player'] == 1 and not activated else None
            if node['player'] == 1:
                offers.append({'version': node['version'], 'available': bool(wanted), 'message': prompt['message']})
            # A later open window after the Fusion Summon can offer Impermanence
            # against the new monster; that is not a response to the spell.
            if wanted and not should_activate and node['state'].get('chain_depth'):
                raise AssertionError(('Unexpected legal responder', code, prompt))
            if not should_activate:
                wanted = None
            if prompt['mode'] == 'cards':
                wanted_codes = [FAIRY, MOYE, ALUBER] if node['player'] == 1 else [LUBELLION, ALBAZ, TRAGEDY, N]
                ordered = sorted(choices, key=lambda c: wanted_codes.index((c.get('card') or {}).get('code'))
                                 if (c.get('card') or {}).get('code') in wanted_codes else 999)
                raw = bytes([prompt['minimum'], *(c['response'] for c in ordered[:prompt['minimum']])]).hex()
            elif prompt['mode'] == 'places':
                raw = choices[0]['response']
            elif prompt['message'] == 19:
                raw = next(c['response'] for c in choices if c['semantic'].get('value') == 1)
            elif prompt['message'] == 14:
                raw = choices[0]['response']
            elif prompt['message'] == 26:
                choice = next((c for c in choices if c['semantic']['kind'] == 'select'
                               and c['semantic'].get('card', {}).get('code') in (ALBAZ, TRAGEDY)), None)
                choice = choice or next((c for c in choices if c['semantic']['kind'] == 'finish_selection'), None)
                assert choice, prompt
                raw = choice['response']
            else:
                choice = wanted or next((c for c in choices if c['semantic']['kind'] in ('pass', 'no', 'finish_selection')), None)
                assert choice, prompt
                if wanted:
                    activated = True
                raw = choice['response']
            if node['player'] == 1:
                state = api('/api/opponent/state/' + sid_fn())
                if state.get('version') != node['version'] or state.get('answered') or state.get('player') != 1:
                    continue
                api('/api/opponent/control', {'id': sid_fn(), 'command': 'answer', 'version': node['version'], 'raw': raw})
            else:
                lease = uuid.uuid4().hex
                (folder / 'modular-lease.txt').write_text(lease, encoding='ascii')
                temporary = folder / 'second-answer.tmp'
                temporary.write_text(f"answer {node['version']} {lease} 0 1\n{raw}\n", encoding='ascii')
                temporary.replace(folder / 'modular.request')
            last = node['version']
            time.sleep(.03)
        raise AssertionError('Native second-hint response timed out')

    results = []
    cases = [(source, response, [code], source != 'fusion' or response == 'ash')
             for source in ('aluber', 'moye', 'fusion') for response, code in (('ash', ASH), ('imperm', IMPERM), ('ogre', OGRE))]
    cases = [(s, r, h, legal and not (s == 'moye' and r == 'ash')) for s, r, h, legal in cases]
    cases += [(source, 'pass', [N], False) for source in sources]
    cases += [('moye', 'orange', [ORANGE, FAIRY], True)]
    cases += [('fusion', 'green', [GREEN, FAIRY], True)]
    for source, response, hand, legal in cases:
        label = source + '_' + response
        folder, point, actor = enter(source, hand, label)
        state, offers = resolve(folder, hand[0], legal)
        report = finish()
        events = [e for e in report.get('events', []) if e.get('native_seq', 0) > point['seq']]
        negation = 'activation' if any(e.get('message') == 75 for e in events) else 'effect' if any(e.get('message') == 76 for e in events) else None
        expected_negation = ('activation' if response in ('orange', 'green') else 'effect') if legal and response in ('ash', 'imperm', 'orange', 'green') else None
        assert negation == expected_negation, (label, negation, expected_negation)
        cards = state['state']['cards']
        removed = any(c.get('controller') == 0 and c.get('code') == actor and c.get('location') == 16 for c in cards) if source != 'fusion' else False
        assert removed == (legal and response in ('ogre', 'orange')), (label, removed)
        if source == 'aluber':
            gained = sum(c.get('controller') == 0 and c.get('code') == FUSION and c.get('location') == 2 for c in cards)
        elif source == 'moye':
            gained = sum(c.get('controller') == 0 and c.get('code') == TOKEN and c.get('location') == 4 for c in cards)
        else:
            gained = sum(c.get('controller') == 0 and c.get('code') == LUBELLION and c.get('location') == 4 for c in cards)
        assert gained == (0 if expected_negation else 1), (label, gained)
        paid = sum(c.get('controller') == 1 and c.get('code') in hand and c.get('location') == 16 for c in cards)
        assert paid == (len(hand) if legal else 0), (label, paid)
        synchro = any(c['semantic']['kind'] == 'special' and c['semantic'].get('card', {}).get('code') == CHIXIAO
                      for c in model(state['raw'], state['state'], state.get('effects'))['choices'])
        if source == 'moye':
            assert synchro == (not legal), (label, synchro)
        fusion_again = any(c['semantic']['kind'] == 'activate' and c['semantic'].get('card', {}).get('code') == FUSION
                           for c in model(state['raw'], state['state'], state.get('effects'))['choices'])
        if source == 'fusion':
            assert fusion_again == (response == 'green'), (label, fusion_again)
        results.append({'case': label, 'activated': legal, 'negation': negation, 'actor_removed': removed,
                        'gained': gained, 'immediate_chixiao': synchro, 'fusion_again': fusion_again,
                        'responder_cards_committed': paid, 'offers': offers, 'session': sid_fn()})
        (evidence / 'second-hints-progress.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('PASS native hint case', label, 'negation=', negation, 'removed=', removed, 'gain=', gained, flush=True)
    from app import Catalog
    from second_hint_proof import fingerprint
    receipt = {'schema': 1, 'scope': 'fixed local core, explicit responses; no MD platform certification',
               'caster': 0, 'responder': 1, 'cases': results,
               'resources': fingerprint(runtime, Catalog(runtime).cards),
               'engine_sha256': hashlib.sha256((runtime / 'YGOPro.exe').read_bytes()).hexdigest()}
    (evidence / 'second-hints-native.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
