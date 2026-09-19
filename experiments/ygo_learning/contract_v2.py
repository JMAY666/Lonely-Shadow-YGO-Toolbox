"""Player-visible observation and exact, bounded response enumeration for P1.

Native IDs/raw responses stay in the controller. Model inputs contain only the
canonical player observation, public choices and committed own history.
"""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from modular_decisions import model, encode_binding, semantic_response, effect_key

MAX_CARDS, MAX_ACTIONS, MAX_MEMBERS = 160, 64, 16
CARD_FIELDS, ACTION_FIELDS, HISTORY_FIELDS, CHAIN_FIELDS = 41, 27, 29, 22
KINDS = ('summon','special','position','monster_set','spell_set','activate','attack','battle','main2',
         'end_turn','yes','no','pass','card','material','place','select','unselect','finish_selection',
         'cancel_selection','sort_card','declare_mask','counter','cancel','option','position_choice')
ZONES = {1:1,2:2,4:3,8:4,16:5,32:6,64:7,128:8}


class Unsupported(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':')).encode()).hexdigest()


def known(card):
    if card['controller'] == 0:
        if card['location']==1 and card.get('owner',0)!=0:return False
        return True
    if card['location'] in (1,2):
        return False
    if card['location']==64:return bool(card.get('position',0)&5)
    return not (card['location'] in (4,8,32,128) and not card.get('position',0)&5)


def effect_public(effect, allowed_codes):
    if not effect:
        return None
    if effect.get('handler_code') not in allowed_codes:
        return {'identity_known':False}
    value = {k:effect.get(k) for k in ('description','effect_type','event_code','range','handler_code',
                                      'category','property_flags','self_range','opponent_range')}
    # No Lua handles, callback labels, native IDs or opaque counter keys.
    return value


def observation(snapshot, catalog):
    if snapshot.get('answered') or snapshot.get('player') != 0:
        raise Unsupported('not_current_player_decision')
    learning = snapshot.get('learning',{})
    if learning.get('schema') != 2 or learning.get('available') is not True:
        raise Unsupported('dynamic_observation_unavailable')
    state = snapshot['state']
    dynamic = {row['instance_id']:row for row in learning['cards']}
    if len(dynamic) != len(learning['cards']):
        raise Unsupported('duplicate_dynamic_identity')
    cards = sorted(state['cards'], key=lambda c:(c['controller'], c['location'],
        (c['code'] if known(c) else 0) if c['controller']==0 and c['location']==1 else c['sequence'], c.get('sequence',0)))
    if len(cards)>MAX_CARDS:
        raise Unsupported('card_capacity')
    entities = {}
    output = []
    for i,c in enumerate(cards):
        if c['location'] not in ZONES:
            raise Unsupported('unknown_zone')
        visible = known(c)
        seq = 0 if c['location']==1 else c['sequence']
        entity = f'{c["controller"]}:{c["location"]}:{seq}'
        if c['location']==1:entity += ':'+str(c['code'] if visible else 0)
        if c['location']==128:entity += ':'+str(i)
        entities[c['instance_id']] = (i,entity)
        row = {'controller':c['controller'],'location':c['location'],'sequence':seq,
               'position':c['position'] if c['location'] not in (1,2) else 0,
               'identity_known':visible,'code':c['code'] if visible else 0,'entity':entity}
        if visible:
            if c['code'] not in catalog:
                raise Unsupported('card_metadata_missing')
            base = catalog[c['code']]
            row['base'] = {key:base.get(key,0) for key in ('type','race','attribute','level','atk','def')}
            if c['location']!=1:
                if c['instance_id'] not in dynamic:
                    raise Unsupported('known_card_dynamic_missing')
                row['dynamic'] = {k:v for k,v in dynamic[c['instance_id']].items() if k!='instance_id'}
                row['disabled'] = bool(c.get('disabled'))
                row['counters'] = deepcopy(c.get('counters',[]))
        output.append(row)
    # Overlay parent identity is a visible location reference, never a native ID.
    for c,row in zip(cards,output):
        if c.get('overlay_target') is not None:
            parent = entities.get(c['overlay_target'])
            if not parent:raise Unsupported('missing_overlay_parent')
            row['overlay_parent'] = parent[1]
    allowed = {c['code'] for c in output if c['identity_known'] and c['location']!=1}
    observed = {'schema':2,'turn':state['turn'],'turn_player':state['turn_player'],'phase':state['phase'],
        'lp':state['lp'],'cards':output,'chain_depth':state['chain_depth'],
        'chains':[{'link':c['link'],'effect':effect_public(c.get('effect'),allowed)} for c in state.get('chains',[])],
        'normal_used':state['normal_summons_used'][0], 'normal_limit':state['normal_summon_limit'][0],
        'extra_normal_used':state['extra_normal_summon_used'][0],
        'own_effect_usage':sorted([{'used':c['used']} for c in state.get('effect_usage',[]) if c['player']==0],key=lambda x:x['used']),
        'restriction_authority':'native_legal_prompt_and_complete_replay'}
    return observed, entities


def _sum_valid(prompt, raw, indexes):
    if prompt.get('sum_mode'):
        raise Unsupported('sum_overflow_not_in_first_scope')
    mandatory = [struct.unpack_from('<I',raw,10+11*i+7)[0] for i in range(prompt['mandatory'])]
    values = mandatory + [prompt['choices'][i]['semantic']['value'] for i in indexes]
    sums = {0}
    for value in values:
        options = {v for v in (value&65535,value>>16) if v>0}
        if not options:raise Unsupported('invalid_sum_value')
        sums = {s+v for s in sums for v in options if s+v<=prompt['target']}
    return prompt['target'] in sums


def candidates(snapshot, observed, entities):
    prompt = model(snapshot['raw'],snapshot['state'],snapshot.get('effects'))
    choices, mode = prompt['choices'],prompt['mode']
    if prompt.get('unsupported') or mode=='declaration':
        raise Unsupported('unsupported_prompt')
    raw = bytes.fromhex(snapshot['raw'])
    possibilities = []
    if mode=='single':
        possibilities = [(c['response'],[i]) for i,c in enumerate(choices)]
    elif mode in ('cards','sum','places','mask'):
        if len(choices)>MAX_MEMBERS and (mode=='sum' or mode=='cards' and prompt.get('maximum',1)>1):
            raise Unsupported('combination_capacity')
        mandatory = prompt.get('mandatory',0)
        minimum = max(0,prompt.get('minimum',1)-mandatory)
        maximum = min(len(choices),prompt.get('maximum',len(choices))-mandatory)
        if mode=='cards':minimum=0 if prompt['minimum']==0 else 1
        explored = 0
        for count in range(minimum,maximum+1):
            for indexes in itertools.combinations(range(len(choices)),count):
                explored += 1
                if explored>8192:raise Unsupported('combination_search_budget')
                if mode=='sum' and not _sum_valid(prompt,raw,indexes):continue
                response = encode_binding({},prompt,list(indexes))
                if response is not None:possibilities.append((response,list(indexes)))
                if len(possibilities)>1024:raise Unsupported('action_enumeration_capacity')
        if prompt.get('cancel'):possibilities.append(('ffffffff',[]))
    elif mode=='sort':
        if len(choices)>4:raise Unsupported('sort_capacity')
        possibilities = [(encode_binding({},prompt,list(order)),list(order))
                         for order in itertools.permutations(range(len(choices)))]
    elif mode=='counters':
        def visit(index,left,amounts):
            if len(possibilities)>MAX_ACTIONS:raise Unsupported('counter_capacity')
            if index==len(choices):
                if left==0:possibilities.append((b''.join(struct.pack('<H',x) for x in amounts).hex(),
                                               [i for i,x in enumerate(amounts) if x]))
                return
            for value in range(min(left,choices[index]['available'])+1):visit(index+1,left-value,amounts+[value])
        visit(0,prompt['amount'],[])
    else:
        raise Unsupported('unsupported_prompt_mode')
    if not 0<len(possibilities)<=1024:
        raise Unsupported('empty_or_excessive_actions')
    allowed = {c['code'] for c in observed['cards'] if c['identity_known']}
    result = []
    for response,indexes in possibilities:
        semantic = semantic_response(prompt,response)
        selected = []
        members = []
        for index in indexes:
            choice = choices[index]
            item = deepcopy(choice['semantic'])
            if choice.get('card'):
                native = choice['card']
                ref = entities.get(native.get('instance_id'))
                if not ref and native.get('controller')==0 and native.get('location') in (1,64):
                    # Deck-selection packets can deliberately replace the real
                    # sequence with zero. The response index is still authoritative.
                    matching=[c for c in snapshot['state']['cards'] if c['controller']==0
                              and c['location']==native['location'] and c['code']==native['code']]
                    if matching:
                        refs=[entities[c['instance_id']] for c in matching]
                        def comparable(row):return {k:v for k,v in row.items() if k not in ('entity','sequence')}
                        if len({digest(comparable(observed['cards'][r[0]])) for r in refs})==1:
                            ref=refs[0]
                if not ref:raise Unsupported('ambiguous_card_reference')
                members.append(ref[0])
                card = observed['cards'][ref[0]]
                item['card'] = {k:card[k] for k in ('controller','location','sequence','code','identity_known','entity')}
            if item.get('effect'):item['effect']=effect_public(choice.get('effect'),allowed)
            if mode=='counters':item['amount']=struct.unpack_from('<H',bytes.fromhex(response),index*2)[0]
            if choice.get('effect') and (choice.get('card') or {}).get('controller')==0:
                effect=choice['effect']
                available=all(k in effect for k in ('count_remaining','count_max'))
                item['usage']={'available':available,'scope':'effect_object; global legality remains in core',
                               'remaining':effect.get('count_remaining') if available else None,
                               'maximum':effect.get('count_max') if available else None}
            selected.append(item)
        if mode in ('cards','sum','mask'):selected.sort(key=lambda x:json.dumps(x,sort_keys=True))
        public = {'message':prompt['message'],'mode':mode,'selection':selected,
                  'cancel':bool(semantic.get('cancel')),'context':effect_public((snapshot.get('effects') or {}).get('context'),allowed)}
        result.append({'response':response,'public':public,'members':members,
                       'identity':digest([snapshot['version'],snapshot['raw'],response])})
    # Identical observable choices (e.g. duplicate copies in a shuffled deck)
    # share one model choice. Their private response aliases remain controller data.
    grouped={}
    for option in result:
        key=json.dumps(option['public'],sort_keys=True)
        if key not in grouped:grouped[key]={**option,'responses':[]}
        grouped[key]['responses'].append(option['response'])
    if len(grouped)>MAX_ACTIONS:raise Unsupported('action_capacity')
    return [grouped[key] for key in sorted(grouped)]


def build(snapshot, catalog):
    observed, entities = observation(snapshot,catalog)
    options = candidates(snapshot,observed,entities)
    return {'observation':observed,'candidates':options,
            'state_key':digest(observed),'window':(snapshot['version'],snapshot['raw'])}


def feature_arrays(bundle, history=(), supported_codes=None):
    import numpy as np
    obs, options = bundle['observation'], bundle['candidates']
    cards = np.zeros((MAX_CARDS,CARD_FIELDS),dtype=np.uint8)
    card_numeric = np.zeros((MAX_CARDS,8),dtype=np.float32)
    actions = np.zeros((MAX_ACTIONS,ACTION_FIELDS),dtype=np.uint8)
    action_numeric = np.zeros((MAX_ACTIONS,8),dtype=np.float32)
    members = np.zeros((MAX_ACTIONS,MAX_CARDS),dtype=np.float32)
    legal = np.arange(MAX_ACTIONS)<len(options)
    def number(value):
        if not isinstance(value,(int,float)) or not np.isfinite(value) or abs(value)>1e9:
            raise Unsupported('numeric_field_out_of_scope')
        return float(value)
    def word(value):
        if not isinstance(value,int) or not 0<=value<2**32:raise Unsupported('integer_field_range')
        return list(value.to_bytes(4,'little'))
    def small(value):
        value=int(value)
        if not 0<=value<256:raise Unsupported('byte_field_range')
        return value
    entity_first={}
    for i,c in enumerate(obs['cards']):
        entity_first.setdefault(c['entity'],i)
        if supported_codes is not None and c['identity_known'] and c['code'] not in supported_codes:
            raise Unsupported('unsupported_card_code')
        dyn=c.get('dynamic');base=c.get('base',{})
        if c.get('counters'):
            raise Unsupported('typed_counters_not_in_first_scope')
        values=dyn or {'type':base.get('type',0),'attribute':base.get('attribute',0),'race':base.get('race',0),
                       'level':base.get('level',0)&255,'rank':0,'link':0,'link_marker':0}
        row=[c['controller'],ZONES[c['location']],small(c['sequence']),small(c['position']),int(c['identity_known'])]
        row+=word(c['code'])
        for key in ('type','attribute','race','level','rank','link','link_marker'):row+=word(values.get(key,0))
        parent=next((j+1 for j,x in enumerate(obs['cards']) if x['entity']==c.get('overlay_parent')),0)
        if 'overlay_parent' in c and not parent:raise Unsupported('missing_overlay_parent_feature')
        row += [int(c.get('disabled',False)),int(bool(dyn)),int('overlay_parent' in c),parent]
        cards[i]=row
        if dyn:
            card_numeric[i]=[number(dyn['attack'])/10000,number(dyn['defense'])/10000,
                number(dyn['base_attack'])/10000,number(dyn['base_defense'])/10000,
                number(dyn['level'])/13,number(dyn['rank'])/13,number(dyn['link'])/8,
                sum(number(x['count']) for x in c.get('counters',[]))/16]
    counts=lambda p,z:sum(c['controller']==p and c['location']==z for c in obs['cards'])
    global_bytes=[small(obs['turn']),obs['turn_player'],obs['phase']&255,(obs['phase']>>8)&255]
    global_bytes += [small(counts(p,z)) for z in (2,1,64,16,32,4,8) for p in (0,1)]
    global_bytes += [small(obs['chain_depth']),small(obs['normal_used']),small(obs['normal_limit']),
                     int(obs['extra_normal_used']),2]
    global_numeric=np.array([number(obs['lp'][0])/8000,number(obs['lp'][1])/8000,
        number(obs['normal_used']),number(obs['normal_limit']),int(obs['extra_normal_used']),
        number(obs['chain_depth'])/10,*[counts(p,z)/60 for z in (2,1,64,16) for p in (0,1)],
        sum(number(x['used']) for x in obs['own_effect_usage'])/16,len(options)/MAX_ACTIONS],dtype=np.float32)
    for i,option in enumerate(options):
        public=option['public'];selected=public['selection'];first=selected[0] if selected else {}
        kind='cancel' if public['cancel'] else first.get('kind','card')
        # Older semantic names remain explicit categories, never guessed responses.
        if kind not in KINDS:raise Unsupported('unsupported_action_kind:'+kind)
        selected_cards=[c['card'] for c in selected if c.get('card')]
        primary=selected_cards[0] if selected_cards else {}
        secondary=selected_cards[1] if len(selected_cards)>1 else {}
        effect=first.get('effect') or public.get('context') or {}
        place=first.get('place',[0,0,0])
        row=[small(public['message']),KINDS.index(kind),small(len(selected)),
             ZONES.get(primary.get('location'),0),small(primary.get('sequence',0)),
             ZONES.get(place[1],0),small(place[2])]
        row+=word(int(effect.get('effect_type') or 0))+word(primary.get('code',0))+word(secondary.get('code',0))
        scalar=next((first[k] for k in ('value','flag','amount','description') if first.get(k) is not None),None)
        row+=word(int(scalar if scalar is not None else effect.get('description') or 0))
        row += [int(public['cancel']),small(primary.get('controller',0)),
                small(secondary.get('controller',0)),small(place[0])]
        actions[i]=row
        for order,member in enumerate(option['members']):
            canonical=entity_first[obs['cards'][member]['entity']]
            weight=order+1 if public['mode']=='sort' else selected[order].get('amount',1) if public['mode']=='counters' else 1
            members[i,canonical]+=weight
        usage=first.get('usage') or {}
        usage_value=(number(usage['remaining'])/max(1,number(usage['maximum']))) if usage.get('available') else 0
        action_numeric[i]=[len(selected)/16,len(option['members'])/16,
            sum(card_numeric[m,0] for m in option['members']),sum(card_numeric[m,1] for m in option['members']),
            sum(card_numeric[m,4] for m in option['members']),sum(number(c.get('amount',0)) for c in selected)/16,
            usage_value,int(usage.get('available',False))]
    history_array=np.zeros((32,HISTORY_FIELDS),dtype=np.uint8)
    for i,row in enumerate(list(history)[-32:][::-1]):history_array[i]=row
    if len(obs['chains'])>16:raise Unsupported('chain_capacity')
    chains=np.zeros((16,CHAIN_FIELDS),dtype=np.uint8)
    for i,chain in enumerate(obs['chains']):
        effect=chain.get('effect') or {}
        chain_known=bool(effect) and effect.get('identity_known',True)
        row=[small(chain['link']),int(chain_known)]
        for key in ('handler_code','description','effect_type','category','event_code'):
            row+=word(int(effect.get(key) or 0)) if chain_known else [0]*4
        chains[i]=row
    return {'cards':cards,'card_numeric':card_numeric,'global':np.array(global_bytes,dtype=np.uint8),
            'global_numeric':global_numeric,'actions':actions,'action_numeric':action_numeric,
            'members':members,'history':history_array,'chains':chains,'legal':legal}


def committed_history(features, index, observation):
    return [*features['actions'][index].tolist(),int(observation['turn']),int(observation['phase']).bit_length()]
