"""Real-core checks for continuous summon permissions and lingering restrictions."""
from pathlib import Path
import json
import uuid

from modular_decisions import model, next_prompt, public_state
from modular_salamangreat import recipe_driver

NORMAL, TUNER, OTHER_TUNER = 1184620, 11066358, 21615956
FIELD, MST, FOOLISH, REBORN, CUE = 14442329, 5318639, 81439173, 83764718, 16387555


def run(runtime,evidence,api,start,current,answer,choose,save,finish,wait,sid_fn):
    act,settle=recipe_driver(current,answer,choose)
    def deck(cards): return {'main':list(cards)+[NORMAL]*(40-len(cards)), 'extra':[], 'side':[]}
    def can_summon(code):
        s=current()
        return any(c['semantic']['kind']=='summon' and c['semantic'].get('card',{}).get('code')==code
                   for c in model(s['raw'],s['state'],s.get('effects'))['choices'])
    def begin(hand,name,extra=()):
        start(deck([*hand,*extra]),hand,'continuous rules '+name);settle()
        assert current()['state']['normal_summon_limit']==[1,1]
        assert current()['state']['extra_normal_summon_used']==[False,False]
    def field_on(): act('activate',FIELD,location=2,zones=[(0,8,5)])
    def remove_field(): act('activate',MST,location=2,cards=[(FIELD,8)],zones=[(0,8,0)])

    hand=[NORMAL,NORMAL,TUNER,OTHER_TUNER,FIELD,FIELD,MST]
    begin(hand,'extra permission')
    act('summon',NORMAL,zones=[(0,4,0)])
    assert not can_summon(TUNER)
    field_on();assert can_summon(TUNER) and can_summon(OTHER_TUNER)
    assert not can_summon(NORMAL),'The field does not grant an extra summon to non-Tuners'
    assert current()['state']['normal_summons_used'][0]==1
    assert current()['state']['extra_normal_summon_used'][0] is False
    act('summon',TUNER,zones=[(0,4,1)])
    assert current()['state']['normal_summons_used'][0]==1
    assert current()['state']['extra_normal_summon_used'][0] is True
    assert not can_summon(OTHER_TUNER)
    source=save(mark_field=True)
    print('PASS field grants a Tuner-only extra Normal Summon; ordinary/extra usage stay distinct and a third summon is rejected',flush=True)

    begin(hand,'source probe');sid=sid_fn();before=current()
    api('/api/modular/configure',{'id':sid,'sources':[source['id']],'preference':'shortest'})
    result=api('/api/modular/search',{'id':sid})
    assert result['candidates'],(result['status'],result['rejected'])
    assert any(c['terminal']['extra_normal_summon_used'][0] and c['terminal']['normal_summons_used'][0]==1 for c in result['candidates'])
    assert current()==before,'Search must not consume the live instance summon permissions'
    finish()
    print('PASS disposable-source search retains the field permission and its consumption without changing the live test state',flush=True)

    begin(hand,'remove before extra')
    act('summon',NORMAL,zones=[(0,4,0)]);field_on();assert can_summon(TUNER)
    remove_field();assert not can_summon(TUNER)
    assert current()['state']['extra_normal_summon_used'][0] is False
    finish()
    begin(hand,'replace after extra')
    act('summon',NORMAL,zones=[(0,4,0)]);field_on();act('summon',TUNER,zones=[(0,4,1)])
    field_on();assert not can_summon(OTHER_TUNER)
    assert current()['state']['extra_normal_summon_used'][0] is True
    finish()
    print('PASS losing the field removes unused permission; replacing it cannot refresh an already used extra summon',flush=True)

    # Read legal Reborn targets in a disposable probe. No real response is sent.
    def reborn_targets():
        base=current();value=base;path=[];folder=Path(runtime)/'_trainer/sessions'/sid_fn()
        for _ in range(30):
            prompt=model(value['raw'],value['state'],value.get('effects'))
            if prompt['message']==15:
                assert current()==base
                return {c['semantic'].get('card',{}).get('code') for c in prompt['choices']}
            if prompt['message']==11:
                choice=next(c for c in prompt['choices'] if c['semantic']['kind']=='activate' and c['semantic'].get('card',{}).get('code')==REBORN)
            elif prompt['mode']=='places':choice=prompt['choices'][0]
            else:choice=next(c for c in prompt['choices'] if c['semantic']['kind'] in ('pass','no'))
            path.append(value['raw']+':'+choice['response']);token=uuid.uuid4().hex
            request=folder/'rules-probe.tmp'
            request.write_text(f"probe {base['version']} {token} 0 {len(path)}\n"+'\n'.join(path)+'\n',encoding='ascii')
            request.replace(folder/'modular.request')
            def reply():
                try: v=json.loads((folder/'modular-result.json').read_text(encoding='utf-8'))
                except (OSError,ValueError):return None
                return v if v.get('token')==token else None
            value=wait(reply);assert value['status']!='error',value
            value['raw'],_=next_prompt(value['batches'])
        raise AssertionError('Probe did not reach the target selection')

    begin([FIELD,TUNER,FOOLISH,REBORN,MST,NORMAL],'lingering restriction',[CUE])
    act('activate',FOOLISH,cards=[NORMAL],zones=[(0,8,0)])
    field_on();act('summon',TUNER,zones=[(0,4,0)])
    assert NORMAL in reborn_targets()
    act('activate',FIELD,location=8,effect=FIELD*16+1,cards=[(TUNER,4),(CUE,1)],options=[1190])
    assert NORMAL not in reborn_targets() and TUNER in reborn_targets()
    remove_field()
    assert NORMAL not in reborn_targets() and TUNER in reborn_targets()
    after=public_state(current()['state']);finish()
    print('PASS effect-three Tuner-only Special Summon restriction remains after the field leaves; replay probes offer only legal Reborn targets',flush=True)
    (Path(evidence)/'continuous-rules.json').write_text(json.dumps({'search_candidates':len(result['candidates']),'source':source['id'],'after_field_left':after},ensure_ascii=False,indent=2),encoding='utf-8')
