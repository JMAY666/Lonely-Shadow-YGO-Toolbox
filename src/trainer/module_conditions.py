"""Declarative IF branches backed by engine events, never executable expressions."""
from collections import Counter
from copy import deepcopy
from modular_decisions import effect_key, digest
from protocol import packets, u32

IF_KINDS = ('recorded', 'activation_negated', 'effect_negated', 'resource_moved', 'unconditional')
LABELS = {'recorded':'按实际干扰生成 IF','activation_negated':'发动被无效','effect_negated':'效果被无效',
          'resource_moved':'关键场上卡被效果移走','unconditional':'按合法资源接续，不限定干扰'}


def resources(state):
    counted=Counter((c.get('code'),c.get('location')) for c in state.get('cards',[]) if c.get('controller')==0)
    return [[code,zone,count] for (code,zone),count in counted.items()]


def validate_if(value, catalog):
    value={} if value is None else value
    if not isinstance(value,dict):raise ValueError('IF 条件类型无效')
    kind=value.get('kind','recorded')
    if kind not in IF_KINDS:raise ValueError('IF 条件类型无效')
    required=value.get('required',[])
    if not isinstance(required,list) or len(required)>20:raise ValueError('补点资源条件最多 20 项')
    normalized=[]
    for row in required:
        if not isinstance(row,dict) or type(row.get('code')) is not int or row['code'] not in catalog or row.get('location') not in (2,4,8,16,32,64) or type(row.get('count')) is not int or not 1<=row['count']<=60:
            raise ValueError('补点资源的卡号、区域或份数无效')
        normalized.append({key:row[key] for key in ('code','location','count')})
    return {'kind':kind,'required':normalized}


def facts_from_report(report, start_seq=0):
    events={e['id']:e for e in report.get('events',[])};facts=[]
    for event in events.values():
        if event.get('native_seq',0)<=start_seq:continue
        if event.get('message') in (75,76):
            affected=events.get(event.get('activation_ref'),{})
            card=next(iter(affected.get('cards',[])),{})
            if card.get('controller')!=0:continue
            native=affected.get('engine_effect') or event.get('engine_effect')
            facts.append({'kind':'activation_negated' if event['message']==75 else 'effect_negated',
                'code':card.get('code'),'effect':effect_key(native),'action':affected.get('id'),
                'evidence':[affected.get('id'),event['id']], 'seq':event.get('native_seq',0), 'instance':card.get('instance_id')})
        elif event.get('message')==50 and event.get('reason',0)&0x40:
            origin,dest=event.get('origin',{}),event.get('destination',{})
            if origin.get('controller')==0 and origin.get('location') in (4,8) and (dest.get('controller')!=0 or dest.get('location') not in (4,8)):
                cause=event.get('cause') or {};card=next(iter(event.get('cards',[])),{})
                # A payment or our own material use is not an opposing removal.
                opponent=cause.get('handler_instance') is not None and any(c.get('instance_id')==cause.get('handler_instance') and c.get('controller')==1
                             for e in events.values() for c in e.get('cards',[]))
                if opponent:facts.append({'kind':'resource_moved','code':card.get('code'),'effect':None,
                    'from':origin.get('location'),'to':dest.get('location'),'instance':card.get('instance_id'),'seq':event.get('native_seq',0),'evidence':[event['id']]})
    modules=report.get('review',{}).get('module_graph',{}).get('modules',[])
    for fact in facts:
        after=next((m for m in modules if m.get('kind')=='decision' and m.get('seq',0)>=fact['seq'] and m.get('state')),None)
        if after:fact['resources']=resources(after['state'])
    return facts


def branch_condition(base, branch):
    declared=branch.get('conditions',{}).get('if',{'kind':'recorded','required':[]})
    expected=branch.get('conditions',{}).get('expected_action') or branch.get('source',{}).get('action_id')
    action=next((a for a in base.get('actions',[]) if a['id']==expected),{})
    card=next((c for c in action.get('cards',[]) if c.get('controller')==0),{})
    facts=facts_from_report(branch.get('report') or {},branch.get('source',{}).get('seq',0))
    matches=[f for f in facts if card.get('code') and f['code']==card.get('code') and
             (declared['kind']=='recorded' or f['kind']==declared['kind']) and
             (f['kind']=='resource_moved' and card.get('instance_id') is not None and f.get('instance')==card['instance_id']
              or f['kind']!='resource_moved' and f.get('action')==expected)]
    if declared['kind']=='unconditional':status='verified';selected=None
    else:
        selected=next((f for f in matches if f['kind']=='resource_moved' or f.get('effect') and
                       f['effect'].get('operation_line') is not None and f['effect'].get('labels') is not None),None)
        status='verified' if selected else 'unverified'
    return {'schema':1, 'kind':declared['kind'], 'label':LABELS[declared['kind']],
            'required':deepcopy(declared.get('required',[])), 'status':status,
            'event':deepcopy(selected), 'affected_card':card.get('code'), 'affected_action':expected,
            'note':'仅实际事件与当前资源满足时可衔接；对手预设手牌不等于干扰已发生'}


def condition_matches(guard, facts, state):
    if not guard:return True
    if guard.get('status')!='verified':return False
    needed=Counter()
    for row in guard.get('required',[]):needed[(row['code'],row['location'])]+=row['count']
    def available(fact=None):
        rows=(fact or {}).get('resources',resources(state))
        return not (needed-Counter({(code,zone):count for code,zone,count in rows}))
    if guard['kind']=='unconditional':return available()
    expected=guard.get('event') or {}
    return any(available(f) and f.get('kind')==expected.get('kind') and f.get('code')==expected.get('code') and
               (f['kind']=='resource_moved' and f.get('from')==expected.get('from') and f.get('to')==expected.get('to')
                or f['kind']!='resource_moved' and f.get('effect')==expected.get('effect')) for f in facts)


def advance_facts(memory, before, after, batches, selected_effect=None):
    """Follow simulated chain events with metadata from actual decision windows."""
    value=deepcopy(memory or {'chains':{},'facts':[]});chains=value['chains']
    cards=before.get('cards',[])+after.get('cards',[])
    for state in (before,after):
        for row in state.get('chains',[]):
            effect=row.get('effect') or {};card=next((c for c in cards if c.get('instance_id')==effect.get('handler_instance')), {})
            chains[str(row['link'])]={'code':effect.get('handler_code'),'controller':card.get('controller'),'effect':effect_key(effect)}
    for raw in batches:
        for _,msg,body in packets(bytes.fromhex(raw)):
            if msg==70:
                key=str(body[15]);known=chains.get(key,{})
                exact=effect_key(selected_effect) if selected_effect and selected_effect.get('handler_code')==u32(body) and selected_effect.get('description')==u32(body,11) else known.get('effect')
                chains[key]={'code':u32(body),'controller':body[8],'effect':deepcopy(exact)}
            elif msg in (75,76):
                effect=chains.get(str(body[0]),{})
                if effect.get('controller')==0 and effect.get('effect'):
                    value['facts'].append({'kind':'activation_negated' if msg==75 else 'effect_negated',
                        'code':effect['code'],'effect':effect['effect'],'resources':resources(after)})
            elif msg==74:chains.clear()
    # Repeated packets can occur when the native UI skips acknowledgement windows.
    value['facts']=list({digest(f):f for f in value['facts']}.values())
    return value
