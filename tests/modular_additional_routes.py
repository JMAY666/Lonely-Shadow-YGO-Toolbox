"""User-supplied Combo 4..15 and variants, tested without changing live roots.

Every response goes to the real disposable core, with an exact prompt guard.
Original invalid recipes and explicitly corrected variants are separate cases.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json
import time

from app import Store, process_identity
from modular_decisions import model, semantic_response, public_state
from modular_salamangreat import (recipe_driver, GAZELLE as G, SPINNY as S, BALELYNX as B,
                                 WOLF as W, JAGUAR as J, STALLIO as M, ROAR as R, SANCTUARY as A, NORMAL as N)

F, X, D, T, K, BAG, SHA = 20618081, 94620082, 16188701, 81275020, 53932291, 90590303, 71166481
DECK={'main':[G]*3+[S]*3+[J]*2+[R]*2+[A]*2+[F]*2+[X]*2+[D]*2+[T,K]+[N]*20,
      'extra':[B]*3+[W]*3+[M]*2+[BAG,SHA],'side':[]}


class ProbeRecipe:
    def __init__(self, planner, sid, root):
        self.planner,self.sid,self.root=planner,sid,root
        self.node=root;self.path=[];self.trace=[];self.line=None
        self.act,self.settle=recipe_driver(lambda:self.node,self.answer,self.choose)

    def choose(self, kind=None, code=None, place=None, option=None, index=0, effect=None, location=None):
        p=model(self.node['raw'],self.node['state'],self.node.get('effects'))
        choices=[c for c in p['choices'] if (kind is None or c['semantic']['kind']==kind)
            and (code is None or c['semantic'].get('card',{}).get('code')==code)
            and (place is None or c['semantic'].get('place')==place)
            and (option is None or c['semantic'].get('value')==option)
            and (effect is None or (c.get('effect') or {}).get('description')==effect)
            and (location is None or c['semantic'].get('card',{}).get('location')==location)]
        if not choices:raise ValueError(json.dumps({'wanted':{'kind':kind,'code':code,'effect':effect,'location':location},'legal':[c['semantic'] for c in p['choices']]},ensure_ascii=False))
        raw=choices[index]['response']
        if p['mode']=='cards':raw=bytes([1,raw]).hex()
        self.answer(raw,self.node)

    def answer(self, raw, expected=None):
        before=self.node;p=model(before['raw'],before['state'],before.get('effects'))
        decision=semantic_response(p,raw)
        self.path.append(before['raw']+':'+raw)
        self.node=self.planner.bridge(self.sid,self.root,self.path)
        while self.node['player']==1:
            self.path.append(self.node['raw']+':ai');self.node=self.planner.bridge(self.sid,self.root,self.path)
        if not self.node.get('raw'):raise ValueError('没有到达新的合法决策边界')
        self.trace.append({'original_step':self.line,'decision':decision,'raw':raw,
                           'before':public_state(before['state']),'after':public_state(self.node['state'])})
        return self.node

    def do(self, line, kind, code, **options):
        self.line=line;return self.act(kind,code,**options)

    def gazelle_open(self, starter, mill, line=1):
        self.do(line,'summon',starter,zones=[(0,4,1)])
        self.do(f'{line+1}–{line+4}','special',B,cards=[(starter,4)],
            effect_cards={(B,B*16):[A],(G,G*16+1):[mill]},zones=[(0,4,5),(0,4,0)],triggers=[B,G])

    def sanctuary(self,line):self.do(line,'activate',A,zones=[(0,8,5)])
    def revive_spinny(self,line,zone=0):self.do(line,'activate',S,effect=S*16+1,location=16,zones=[(0,4,zone)])
    def spinny_boost(self,line,mill=R):
        self.do(line,'activate',S,effect=S*16,location=2,cards=[(B,4)],
            effect_cards={(G,G*16+1):[mill]},zones=[(0,4,0)],triggers=[G])
    def fox_revive(self,line,discard,zone=2):self.do(line,'activate',X,location=16,cards=[(discard,2)],zones=[(0,4,zone)])
    def stallio(self,line,materials):self.do(line,'special',M,cards=[(c,4) for c in materials],zones=[(0,4,1)])
    def recruit(self,line,detach,recruit,mill=None):
        self.do(line,'activate',M,cards=[(detach,128),(recruit,1)],zones=[(0,4,0)],
            triggers=[G] if mill else [],effect_cards={(G,G*16+1):[mill]} if mill else {})
    def wolf(self,line,materials,zone=5,gazelle_mill=None):
        self.do(line,'special',W,cards=[(c,4) for c in materials],zones=[(0,4,zone),(0,4,0)],
            triggers=[G] if gazelle_mill else [],effect_cards={(G,G*16+1):[gazelle_mill]} if gazelle_mill else {})
    def reincarnate(self,line,code=W,zone=5,mill=None):
        self.do(line,'special',code,cards=[(code,4)],zones=[(0,4,zone),(0,4,0)],sanctuary=True,
            triggers=[G] if mill else [],effect_cards={(G,G*16+1):[mill]} if mill else {})
    def roar(self,line):self.do(line,'activate',W,effect=W*16+1,cards=[(R,16)])
    def jaguar(self,line,returned=W,zone=1):self.do(line,'activate',J,location=16,cards=[(returned,16),(G,16)],zones=[(0,4,zone)],triggers=[W])
    def bagooska(self,line):self.do(line,'special',BAG,cards=[(J,4),(F,4)],zones=[(0,4,1)],position=4)
    def debug(self,line,search):self.do(line,'summon',D,cards=[(search,1)],zones=[(0,4,0)],triggers=[D])
    def debug_link(self,line):self.do(line,'special',B,cards=[(D,4),(A,1)],zones=[(0,4,5)],triggers=[B])
    def terrortop(self,line=1):self.do(line,'special',T,cards=[(K,1)],zones=[(0,4,1)],triggers=[T])
    def taketomborg(self,line):self.do(line,'special',K,zones=[(0,4,0)])


def route(p, number, variant):
    if number==4:
        p.gazelle_open(S,J);p.revive_spinny(6,2);p.stallio(7,[G,S]);p.recruit(8,G,F)
        p.wolf(9,[B,M]);p.sanctuary(10);p.reincarnate(11);p.jaguar('12–13');p.bagooska(14)
    elif number==5:
        p.do(1,'summon',X,zones=[(0,4,1)]);p.do('2–3','special',B,cards=[(X,4),(A,1)],zones=[(0,4,5)],triggers=[B])
        p.sanctuary(4);p.fox_revive(5,S,0);p.revive_spinny(6,2);p.stallio(7,[X,S]);p.recruit('8–9',S,G,R)
        p.wolf(10,[B,M]);p.reincarnate(11);p.roar(12)
        p.do('13–14','special',B,cards=[(G,4),(G,16)],zones=[(0,4,1)],triggers=[W])
    elif number==6:
        p.gazelle_open(J,R);p.wolf(6,[B,G]);p.sanctuary(7);p.reincarnate(8);p.roar(9);p.jaguar('10–11')
    elif number==7:
        p.gazelle_open(F if variant=='falco' else J,J if variant=='falco' else F)
        p.sanctuary(6);p.reincarnate(7,B);p.jaguar(8,B)
        p.do(9,'activate',F,location=16,cards=[(G,4)],zones=[(0,4,0)]);p.bagooska(10)
    elif number==8:
        p.gazelle_open(X,R);p.sanctuary(6);p.fox_revive(7,S,2);p.stallio(8,[G,X]);p.recruit(9,G,S)
        p.wolf(10,[B,M]);p.reincarnate(11);p.roar(12)
        p.do('13–14','activate',S,location=16,zones=[(0,4,1)],cards=[(G,16)],triggers=[W])
        p.do(15,'special',SHA,cards=[(S,4),(S,4)],zones=[(0,4,1)],position=4)
    elif number in (9,10):
        p.gazelle_open(J if number==9 else X,R)
        if number==9:p.spinny_boost(6);p.revive_spinny(7,2);p.stallio(8,[G,S]);p.recruit(9,G,F);p.wolf(10,[B,M]);p.sanctuary(11)
        else:p.sanctuary(6);p.fox_revive(7,J,2);p.stallio(8,[G,X]);p.recruit(9,G,F);p.wolf(10,[B,M])
        p.reincarnate(12 if number==9 else 11);p.roar(13 if number==9 else 12);p.jaguar('14–15' if number==9 else '13–14');p.bagooska(16 if number==9 else 15)
    elif number==11:
        p.debug('1–2',G);p.debug_link('3–4');p.sanctuary(5);p.reincarnate('6–8',B,mill=S)
        p.revive_spinny(9,2);p.stallio(10,[G,S]);p.recruit(11,G,J);p.wolf(12,[B,J],6);p.jaguar('13–14',B,3)
    elif number in (12,13):
        p.debug('1–2',S if variant=='gazelle' else G);p.debug_link('3–4');p.spinny_boost('5–7',R if number==12 else J)
        p.revive_spinny(8,2);p.stallio(9,[G,S]);p.recruit(10,G,J if number==12 else F)
        p.wolf(11,[B,J] if number==12 else [B,M],6 if number==12 else 5);p.sanctuary(12);p.reincarnate(13,zone=6 if number==12 else 5)
        if number==12:p.roar(14);p.jaguar('15–16',W,3)
        else:p.jaguar('14–15');p.bagooska(16)
    elif number==14:
        p.terrortop();p.taketomborg(3);p.stallio(4,[T,K]);p.recruit('5–6',K,G,J);p.wolf(7,[G,M]);p.jaguar('8–9',M)
        p.do('10–11','special',B,cards=[(J,4),(A,1)],zones=[(0,4,1)],triggers=[B]);p.sanctuary(12);p.reincarnate(13,B,1)
    elif number==15:
        p.terrortop();p.debug('3–4',G);p.debug_link('5–6');p.taketomborg(7);p.stallio(8,[T,K]);p.recruit(9,K,S)
        p.wolf('10–12',[B,S],6,R);p.sanctuary(13);p.reincarnate(14,zone=6);p.roar(15)
        p.do('16–17','activate',S,location=16,zones=[(0,4,1 if variant=='original' else 3)],
             cards=[(G,16)],triggers=[] if variant=='corrected' else [W])
        p.do(18,'special',SHA,cards=[(G,4),(S,4)],zones=[(0,4,3)],position=4)


def run_additional(runtime, evidence, api, start, sid_fn, wait):
    runtime,evidence=Path(runtime),Path(evidence);planner=Store(runtime).modular
    cases=[(4,'original',[G,S]),(5,'original',[X,S]),(6,'original',[G,J]),
        (7,'jaguar',[G,J]),(7,'falco',[G,F]),(8,'original',[G,X,S]),(9,'original',[G,S,J]),(10,'original',[G,X,J]),
        (11,'original',[D]),(12,'gazelle',[D,G]),(12,'spinny',[D,S]),(13,'gazelle',[D,G]),(13,'spinny',[D,S]),
        (14,'original',[T]),(15,'original',[T,D]),(15,'location_fixed_only',[T,D]),(15,'corrected',[T,D])]
    results=[]
    for number,variant,hand in cases:
        root=start(DECK,hand+[N]*(5-len(hand)),f'Combo {number} {variant} isolated validation');sid=sid_fn()
        probe=ProbeRecipe(planner,sid,root);entry={'combo':number,'variant':variant,'opening':hand+[N]*(5-len(hand)),
            'deck':DECK,'mode':'disposable_real_core','status':'engine_verified'}
        try:
            route(probe,number,variant)
            expected={4:[W,BAG],5:[W,B],6:[W,J],7:[B,BAG],8:[W,SHA],9:[W,BAG],10:[W,BAG],11:[W,M,J],12:[W,M,J],13:[W,BAG],14:[W,B],15:[W,M,SHA]}[number]
            actual=Counter(c['code'] for c in probe.node['state']['cards'] if c['controller']==0 and c['location']==4)
            assert not Counter(expected)-actual,{'expected':expected,'actual':actual}
            assert not probe.node['state']['chain_depth'],'Unresolved chain at terminal'
        except (ValueError,AssertionError,KeyError) as error:
            entry.update(status='rejected',original_step=probe.line,reason=str(error))
        entry.update(decisions=len(probe.trace),trace=probe.trace,terminal=public_state(probe.node['state']))
        results.append(entry)
        (evidence/'modular-additional-routes.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print('ROUTE',number,variant,entry['status'],entry.get('original_step',''),entry.get('reason','')[:500],flush=True)
        # No probe may write to or replace the real starting state.
        assert planner.state(sid)['state']==root['state']
        api('/api/stop',{'id':sid});meta=json.loads((runtime/'_trainer/sessions'/sid/'session.json').read_text(encoding='utf-8'))
        wait(lambda:process_identity(meta['pid'])!=meta['process_identity'])
    return results
