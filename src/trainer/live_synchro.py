"""Bounded two-material Kewl Tune continuation references, not game execution."""
from itertools import combinations

# Official material text; only these plain two-material cases are covered.
RECIPES = {42781164: ('kewl', None), 88170262: ('named', 16509007),
           15665977: ('named', 89392810), 41069676: ('tuners', None)}
HAND_MATERIAL = {16387555,16509007,89392810,17209452,43904702,42781164}


def options(state, cards, catalog, locks, preserve=()):
    if state['player'] != 0 or state['phase'] not in ('main1','main2') or 'fusion_extra_only' in locks: return []
    material = [c for c in state['cards'] if c['controller']==0 and c['id'] not in preserve
                and c['zone'] in ('monster','hand') and (c['zone']=='hand' or c['faceup'])
                and c.get('tuner') is True and type(c.get('level')) is int and c['level']>0]
    available = [c for c in state['cards'] if c['controller']==0 and c['zone']=='extra'
                 and cards.get(c['code'],{}).get('base_code') in RECIPES]
    out=[]
    for a,b in combinations(material,2):
        field=[c for c in (a,b) if c['zone']=='monster']; hand=[c for c in (a,b) if c['zone']=='hand']
        if not field or len(hand)>1: continue
        if hand and not any(cards.get(c['code'],{}).get('base_code') in HAND_MATERIAL for c in field):continue
        bases={cards.get(c['code'],{}).get('base_code') for c in (a,b)}
        for target in available:
            base=cards[target['code']]['base_code']; kind,required=RECIPES[base]
            if a['level']+b['level'] != catalog[target['code']].get('level',0)&255:continue
            if kind=='named' and required not in bases:continue
            if kind=='kewl' and not any(code in HAND_MATERIAL for code in bases):continue
            out.append({'target_id':target['id'],'code':target['code'],'materials':[a['id'],b['id']],
                        'material_codes':[a['code'],b['code']],'levels':[a['level'],b['level']],
                        'uses_hand':bool(hand),'destination':'banished' if 'banish_instead' in locks else 'grave',
                        'source':cards[target['code']]['source']})
    return out[:24]
