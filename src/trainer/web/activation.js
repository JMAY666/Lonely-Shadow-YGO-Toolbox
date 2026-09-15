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
  return !action.results?.length && !['negated','disabled'].includes(action.status) && !(action.status==='resolved'&&cardActivation(action,report));
}

// Non-chain replacement effects have no MSG_CHAINING. Identify the audited
// operation from its native cause, never just from the card being banished.
function appliedReplacement(action, report) {
  const e=report?.events?.find(e=>e.id===action.id),c=e?.cards?.[0],source=e?.cause;
  const clause='②：自己场上的「转生炎兽」卡被战斗·效果破坏的场合，可以作为代替把墓地的这张卡除外。';
  if(e?.message!==50||c?.code!==14812471||c.instance_id==null||e.origin?.location!==16||e.destination?.location!==32||!(e.destination.position&5)||e.reason!==64||
    source?.owner_code!==c.code||source.handler_code!==c.code||source.handler_instance!==c.instance_id||source.event_code!==50||source.effect_type!==2058||source.range!==16||
    !String(report.catalog?.[c.code]?.desc||'').replaceAll('\r\n','\n').trim().endsWith(clause))return null;
  return {number:2,label:'适用② · 代替破坏',text:clause,result:`代替${c.controller===1?'对方':'我方'}「转生炎兽」卡被破坏`,card:c};
}
function actionSide(action) {
  const sides=new Set((action.cards||[]).map(c=>c.controller));
  return sides.size===1&&sides.has(1)?'对方':sides.size===1&&sides.has(0)?'我方':'';
}
function effectTargetEvidence(action,report) {
  const events=report?.events||[],start=events.findIndex(e=>e.id===(action.activation_ref||action.id));
  const targets=[],refs=[];
  if(start>=0)for(let i=start+1;i<events.length;i++) {
    const e=events[i];
    if(e.message===71&&e.activation_ref===(action.activation_ref||action.id))return {cards:targets.length?targets:action.targets||[],refs};
    if([70,72,74].includes(e.message))break;
    if(e.message===83){targets.push(...e.targets||e.cards||[]);refs.push(e.id);}
  }
  return {cards:action.targets||[],refs:[]};
}
function negationLinks(report) {
  const actions=report?.actions||[],events=report?.events||[],links=[];
  for(const [index,e] of events.entries()) {
    if(![75,76].includes(e.message)||!e.resolution_source_ref||!e.activation_ref)continue;
    const source=actions.find(a=>(a.activation_ref||a.id)===e.resolution_source_ref),affected=actions.find(a=>(a.activation_ref||a.id)===e.activation_ref);
    if(source&&affected&&source!==affected){links.push({source,affected,event:e,label:e.message===75?'发动被无效':'效果被无效',direct:true});continue;}
    // Impermanence installs a lingering disable; the later MSG_CHAIN_DISABLED
    // names the affected link itself. Connect the observed target/response and
    // subsequent disabled result, without claiming native causal attribution.
    if(e.message!==76||source!==affected||!affected?.chain_group)continue;
    const previous=events.slice(0,index).findLast(x=>[70,73,74].includes(x.message));
    if(previous?.message!==73)continue;
    const candidates=actions.filter(a=>a!==affected&&a.status==='resolved'&&a.chain_group===affected.chain_group&&a.chain_link>affected.chain_link&&a.activation_ref===previous.activation_ref&&
      a.cards?.[0]?.code===10045474&&a.engine_effect?.owner_code===10045474&&(a.engine_effect.effect_type&0x10)&&
      effectTargetEvidence(a,report).cards.some(c=>c.instance_id!=null&&affected.cards.some(t=>t.instance_id===c.instance_id&&t.controller===c.controller)));
    if(candidates.length===1)links.push({source:candidates[0],affected,event:e,label:'效果被无效',direct:false});
  }
  return links;
}
function groupedLogActions(actions,report) {
  const links=negationLinks(report).filter(l=>actions.includes(l.source)&&actions.includes(l.affected)&&actionSide(l.source)==='对方'&&actionSide(l.affected)==='我方');
  // Conflicting/multiple response chains retain their full separate records.
  const pairs=links.filter(l=>links.filter(x=>x.source===l.source||x.affected===l.affected).length===1);
  return actions.filter(a=>!pairs.some(l=>l.source===a||a.kind==='target'&&effectTargetEvidence(l.source,report).refs.includes(a.id))).map(a=>{
    const link=pairs.find(l=>l.affected===a);
    if(!link)return a;
    const target=effectTargetEvidence(link.source,report);
    return {...a,_interaction:{...link,source:{...link.source,targets:target.cards,evidence_refs:[...new Set([...(link.source.evidence_refs||[]),...target.refs])]}}};
  });
}
function observedBranchFacts(branch) {
  const facts=[...(branch.premises||[])];
  for(const link of negationLinks(branch.report)) {
    if(link.direct||actionSide(link.source)!=='对方'||actionSide(link.affected)!=='我方')continue;
    const index=facts.findIndex(p=>p.source_action===link.source.id),prior=facts[index];
    if(prior?.confirmed)continue;
    const fact={...prior,id:link.event.id,source_action:link.source.id,affected_action:link.affected.id,source_cards:link.source.cards,affected_cards:link.affected.cards,
      result:'以该怪兽为对象响应；随后该怪兽效果被无效',confirmed:false,chain_group:link.source.chain_group,chain_link:link.source.chain_link,
      basis:'按对象及相邻结算记录连接，原事件未直接标明无效来源',evidence_refs:[link.source.id,...effectTargetEvidence(link.source,branch.report).refs,link.event.id]};
    if(index<0)facts.push(fact);else facts[index]=fact;
  }
  return facts;
}
