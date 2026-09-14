'use strict';

// Display projection for new and frozen legacy plans. Never mutate evidence.
function cardActivation(action, report) {
  if(action.kind!=='effect')return null;
  const events=report?.events||[], event=events.find(e=>e.id===(action.activation_ref||action.id));
  const native=action.engine_effect||event?.engine_effect;
  const card=action.cards?.[0]||event?.cards?.[0]||{};
  const type=Number(report?.catalog?.[card.code]?.type||0);
  if(!(type&6))return null;
  if(Number.isInteger(native?.effect_type)) {
    if(!(native.effect_type&0x10))return null;
  } else {
    // Older logs need observed placement of this same instance before chaining.
    const evidence=new Set(action.evidence_refs||[]), start=events.indexOf(event);
    const placed=events.some((e,i)=>i<start&&evidence.has(e.id)&&e.cards?.some(c=>
      card.instance_id!=null&&c.instance_id===card.instance_id)&&
      e.message===50&&e.destination?.location===8&&e.origin?.location!==8&&(e.destination.position&5));
    if(!placed)return null;
  }
  return type&2?(type&0x80000?'发动场地魔法卡':type&0x20000?'发动永续魔法卡':type&0x40000?'发动装备魔法卡':type&0x10000?'发动速攻魔法卡':type&0x80?'发动仪式魔法卡':'发动魔法卡'):
    type&0x20000?'发动永续陷阱卡':type&0x100000?'发动反击陷阱卡':'发动陷阱卡';
}
function activationResultMissing(action, report) {
  return !action.results?.length && !(action.status==='resolved'&&cardActivation(action,report));
}
