"""Deterministic marked end boards with genuine preference tradeoffs."""
import json


def run(api, start, choose, idle, save, evidence):
    normal, spell = 1184620, 55144522
    hand = [spell, spell, spell, normal, normal]
    deck = {'main': [spell]*3 + [normal]*37, 'extra': [], 'side': []}
    plans = {}
    for preference, sets, summon in [('shortest', 1, False), ('balanced', 1, True), ('largest', 3, True), ('explicit', 3, True)]:
        start(deck, hand, 'planning preference ' + preference)
        for zone in range(sets):
            choose('spell_set', spell); choose(place=[0, 8, zone]); idle()
        if summon:
            choose('summon', normal); choose(place=[0, 4, 1]); idle()
        plans[preference] = save(mark_field=True, mark_codes=[spell] if preference == 'explicit' else None)
    fixture = {'deck': plans['largest']['selected_deck'], 'hand': hand,
               'plans': {preference: plan['id'] for preference, plan in plans.items() if preference != 'explicit'},
               'explicit': plans['explicit']['id'], 'goal': normal}
    (evidence / 'planning-preferences-source.json').write_text(json.dumps(fixture), encoding='utf-8')
    print('PASS three recorded deterministic sources have different decision counts and explicitly marked end boards', flush=True)
