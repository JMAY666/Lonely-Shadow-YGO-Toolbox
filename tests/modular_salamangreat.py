"""Explicit test-only source recipes, each input is accepted by the real core.

Coordinates are from player 0's view: MMZ 0..4, left EMZ 5, right EMZ 6.
These fixtures use the project's free-practice rules, not a tournament banlist.
"""
import json
from modular_decisions import model

GAZELLE, SPINNY, BALELYNX = 26889158, 52277807, 14812471
WOLF, JAGUAR, STALLIO = 87871125, 56003780, 87327776
ROAR, SANCTUARY, NORMAL = 51339637, 1295111, 1184620
DECK={'main':[GAZELLE]*3+[SPINNY]*3+[JAGUAR]*2+[ROAR]*2+[SANCTUARY]*2+[NORMAL]*28,
      'extra':[BALELYNX]*3+[WOLF]*3+[STALLIO]*2,'side':[]}


def recipe_driver(current, answer, choose):
    def settle(cards=(), zones=(), triggers=(), sanctuary=False, effect_cards=None, position=1, yes_descriptions=(), select_all=False, options=()):
        active_cards=cards
        def card_order(choice):
            card=choice['semantic'].get('card',{})
            for i,rule in enumerate(active_cards):
                if isinstance(rule,tuple):
                    if (card.get('code'),card.get('location'))==rule:return i
                elif card.get('code')==rule:return i
            return 1000
        for _ in range(80):
            s=current(); p=model(s['raw'],s['state'],s.get('effects'))
            context=p.get('context') or {}
            active_cards=(effect_cards or {}).get((context.get('handler_code'),context.get('description')),cards)
            if p['message']==11:return s
            choices=p['choices']; chosen=[]
            if p['message'] in (12,13,16):
                chosen=sorted([c for c in choices if c['semantic']['kind'] in ('yes','activate') and c['semantic'].get('card',{}).get('code') in triggers],key=lambda c:triggers.index(c['semantic']['card']['code']))
                if p['message']==13:chosen=[c for c in choices if c['semantic']['kind']=='yes' and c['semantic']['description'] in yes_descriptions]
                if not chosen:chosen=[c for c in choices if c['semantic']['kind'] in ('no','pass')]
            elif p['mode'] in ('cards','sum'):
                needed=p.get('minimum',1)-p.get('mandatory',0) if p['mode']=='sum' else p.get('minimum',1)
                ordered=sorted(choices,key=card_order)
                matching=[c for c in ordered if card_order(c)<1000]
                chosen=matching[:min(p.get('maximum',1),len(matching)) if select_all else max(1,needed)]
                assert len(chosen)>=needed,(p,cards)
                mandatory=p.get('mandatory',0)
                answer(bytes([len(chosen)+mandatory,*range(mandatory),*(c['response'] for c in chosen)]).hex(),s);continue
            elif p['message']==26:
                chosen=[c for c in choices if c['semantic']['kind']=='select' and card_order(c)<1000]
                if not chosen: chosen=[c for c in choices if c['semantic']['kind']=='finish_selection']
            elif p['mode']=='places':
                for place in zones:
                    chosen=[c for c in choices if c['semantic'].get('place')==list(place)]
                    if chosen:break
            elif p['message']==19:
                chosen=[c for c in choices if c['semantic']['value']==position] or choices
            elif p['message']==14:
                chosen=[c for c in choices if c['semantic']['value'] in options] if options else [c for c in choices if c['semantic']['value']==SANCTUARY*16] if sanctuary else choices
            else:raise AssertionError(json.dumps(p,ensure_ascii=False))
            assert chosen,json.dumps({'prompt':p,'cards':cards,'zones':zones,'triggers':triggers},ensure_ascii=False)
            answer(chosen[0]['response'],s)
        raise AssertionError('Recipe exceeded decision bound')
    def act(kind, code, effect=None, location=None, **options):
        choose(kind,code,effect=effect,location=location);return settle(**options)
    return act,settle


def record_sources(start, current, answer, choose, save):
    act,settle=recipe_driver(current,answer,choose)

    start(DECK,[GAZELLE]+[NORMAL]*4,'Combo 1 / Roar')
    act('summon',GAZELLE,cards=[ROAR],zones=[(0,4,1)],triggers=[GAZELLE])
    act('special',BALELYNX,cards=[GAZELLE,SANCTUARY],zones=[(0,4,5)],triggers=[BALELYNX])
    act('activate',SANCTUARY,zones=[(0,8,5)])
    act('special',BALELYNX,cards=[BALELYNX],zones=[(0,4,5),(0,8,0)],triggers=[ROAR],sanctuary=True)
    combo1=save();print('PASS Salamangreat Combo 1',len(combo1['modular_source']['edges']),flush=True)

    start(DECK,[GAZELLE]+[NORMAL]*4,'Combo 2 / Wolf')
    act('summon',GAZELLE,cards=[SPINNY],zones=[(0,4,1)],triggers=[GAZELLE])
    act('activate',SPINNY,zones=[(0,4,0)])
    act('special',STALLIO,cards=[GAZELLE,SPINNY],zones=[(0,4,1)])
    act('activate',STALLIO,cards=[(GAZELLE,128),(JAGUAR,1)],zones=[(0,4,0)])
    act('special',WOLF,cards=[STALLIO,JAGUAR],zones=[(0,4,5)])
    act('activate',JAGUAR,cards=[STALLIO,GAZELLE],zones=[(0,4,1)],triggers=[WOLF])
    act('special',BALELYNX,cards=[JAGUAR,SANCTUARY],zones=[(0,4,1)],triggers=[BALELYNX])
    act('activate',SANCTUARY,zones=[(0,8,5)])
    combo2=save();print('PASS Salamangreat Combo 2',len(combo2['modular_source']['edges']),flush=True)

    start(DECK,[GAZELLE,SPINNY]+[NORMAL]*3,'Combo 3 / two-card')
    act('summon',SPINNY,zones=[(0,4,1)])
    act('special',BALELYNX,cards=[(SPINNY,4)],effect_cards={(BALELYNX,BALELYNX*16):[SANCTUARY],(GAZELLE,GAZELLE*16+1):[ROAR]},zones=[(0,4,5),(0,4,1)],triggers=[BALELYNX,GAZELLE])
    act('activate',SPINNY,zones=[(0,4,0)])
    act('special',STALLIO,cards=[GAZELLE,SPINNY],zones=[(0,4,1)])
    act('activate',STALLIO,cards=[(GAZELLE,128),(JAGUAR,1)],zones=[(0,4,0)])
    act('special',WOLF,cards=[BALELYNX,JAGUAR],zones=[(0,4,6)])
    act('activate',SANCTUARY,zones=[(0,8,5)])
    act('special',WOLF,cards=[WOLF],zones=[(0,4,6)],sanctuary=True)
    act('activate',WOLF,cards=[ROAR])
    act('activate',JAGUAR,cards=[WOLF,GAZELLE],zones=[(0,4,3)],triggers=[WOLF])
    combo3=save();print('PASS Salamangreat Combo 3',len(combo3['modular_source']['edges']),flush=True)
    return [combo1,combo2,combo3],settle
