'use strict';

function dropDuelForecast(s) {
  for(const f of new Set([s.forecast,s.openingForecast,s.tutorialForecast].filter(Boolean)))releasePreparedForecast(s,f);
  s.forecast=s.openingForecast=s.tutorialForecast=null;
}
function forecastRequest(s,intent,body={}) {
  s.planningSession??=s.session;
  const value={session:s.planningSession,slot:body.slot||'opening',...body};
  return s.context?api('/api/automatic-duel/dispatch',{...value,context_id:s.context.context_id,intent}):modularDispatch('duel',intent,value);
}
function forecastTaskRequest(s,f,intent,body={}) {
  f.session??=s.planningSession??s.session;
  return forecastRequest(s,intent,{slot:f.slot,...body,session:f.session});
}
function forecastAlive(s,f) {return !s.ended&&(s===duelState()||typeof autoDuelState==='function'&&s===autoDuelState())&&[s.forecast,s.openingForecast,s.tutorialForecast].includes(f);}
function repaintForecast(s) {if(s.context){autoPaintForecastResults();}else paintForecastResults();}
function releasePreparedForecast(s,f) {
  ++f.generation;clearTimeout(f.timer);f.released=true;
  if(f.job)void forecastTaskRequest(s,f,'plan-cancel',{job:f.job,slot:f.slot}).catch(()=>{});
  if(f.id&&(f.adopted||!f.job))void forecastTaskRequest(s,f,'plan-close',{id:f.id}).catch(()=>{});
}
function selectForecastStage(s) {
  if(s.stage===duelStages.plans&&s.openingForecast)s.forecast=s.openingForecast;
  if(s.stage===duelStages.tutorial)s.forecast=s.tutorialForecast||null;
}
function forecastLibraryUrl(s) {
  return '/api/modular/library?deck_id='+encodeURIComponent(s.deck.id)+'&revision='+encodeURIComponent(s.deck.revision);
}
function updateForecastSources(f,library) {
  f.sources=library.sources.filter(source=>source.status==='ready');
  f.selected=f.selected.filter(id=>f.sources.some(source=>source.id===id));
  f.sourceReason=library.reason||'';
}
function renderForecastSourceList(f) {
  return '<p>仅使用与当前卡组主、副 Tag 匹配的展开方案。</p>'+(f.sources.length?f.sources.map(source=>`<label><input type="checkbox" data-brain-source="${escape(source.id)}" ${f.selected.includes(source.id)?'checked':''}>${escape(source.name)}</label>`).join(''):`<p>${escape(f.sourceReason||'没有匹配的可用展开来源')}</p>`);
}
function refreshForecastPanel(s,f) {
  if(s.forecast===f&&f.showResults){if(s.context)renderAutoDuel();else renderDuel();}
}
async function prepareDuelOpening(s) {
  if(s.openingForecast)return s.openingForecast;
  const previous=s.tutorialForecast||s.forecast;
  const f={sources:[],selected:[],preference:previous?.preference||s.planSort||'largest',precise:previous?.precise||false,
    goal:[...(previous?.goal||[])],preferenceManual:!!previous?.preferenceManual,generation:0,showResults:false,collapsed:true,anchor:null,slot:'opening',busy:true};
  s.openingForecast=f;if(s.stage===duelStages.plans)s.forecast=f;
  try {
    const library=await api(forecastLibraryUrl(s));if(!forecastAlive(s,f)||f.released)return f;
    f.sources=library.sources.filter(source=>source.status==='ready');
    f.sourceReason=library.reason||'';
    f.selected=previous?previous.selected.filter(id=>f.sources.some(source=>source.id===id)):f.sources.map(source=>source.id);
    refreshForecastPanel(s,f);
    f.busy=false;await prepareForecast(s,f);
  }catch(error){f.busy=false;f.error=error.message;repaintForecast(s);}
  return f;
}
async function pollPreparedForecast(s,f,generation=f.generation) {
  if(!forecastAlive(s,f)||f.released||generation!==f.generation||!f.job)return;
  const preference=f.preference;
  try {
    const value=await forecastTaskRequest(s,f,'plan-poll',{job:f.job,slot:f.slot,preference});
    if(!forecastAlive(s,f)||generation!==f.generation||f.released)return;
    f.jobState=value;f.id=value.id||f.id;f.version=value.version;
    f.busy=['queued','running'].includes(value.status);f.error=value.error||'';
    if(value.partial)f.data=value.partial;
    if(value.data){f.prepared[preference]=value.data;if(f.preference===preference)f.data=value.data;}
    if(['stale','cancelled'].includes(value.status)){
      f.data=null;f.prepared={};f.job=null;if(!f.adopted)f.id=null;
      f.error='状态已变化，正在重新准备四种偏好';
      await prepareForecast(s,f,{refresh:true});return;
    }
    if(!f.busy&&!value.data&&value.status==='failed'){f.data=null;f.prepared={};f.error=value.error||'计算失败，请重试';if(!f.adopted)f.id=null;}
    repaintForecast(s);
    // Keep checking versions while the result is visible or held for this duel.
    f.timer=setTimeout(()=>void pollPreparedForecast(s,f,generation),f.busy?650:3000);
  }catch(error){if(generation===f.generation){f.busy=false;f.data=null;f.prepared={};f.error=error.message;repaintForecast(s);}}
}
async function prepareForecast(s,f,{refresh=false}={}) {
  const key=JSON.stringify([s.deck.id,s.deck.revision,s.hand,f.selected,f.precise,f.goal,f.anchor,f.slot]);
  if(f.requestPending&&f.inputKey===key&&!refresh)return;
  if(f.job&&f.inputKey===key&&!refresh){
    if(f.prepared?.[f.preference]){f.data=f.prepared[f.preference];repaintForecast(s);}
    else {f.data=null;clearTimeout(f.timer);await pollPreparedForecast(s,f);}
    return;
  }
  // A cancelled first search closes its newly-created engine. Only reuse a
  // settled opening engine; continuations retain their confirmed session.
  const requestId=!f.busy||f.adopted?f.id:undefined;
  if(!requestId&&!f.adopted)f.id=null;
  const previousJob=f.job;f.job=null;
  clearTimeout(f.timer);const generation=++f.generation;f.requestPending=true;
  f.inputKey=key;f.prepared={};f.data=null;f.error='';f.busy=true;
  if(f.slot==='continuation'&&s.plan?.temporary)s.plan.stale=true;
  repaintForecast(s);
  try {
    if(refresh){
      const library=await api(forecastLibraryUrl(s));
      if(!forecastAlive(s,f)||f.released||generation!==f.generation)return;
      updateForecastSources(f,library);refreshForecastPanel(s,f);
      f.inputKey=JSON.stringify([s.deck.id,s.deck.revision,s.hand,f.selected,f.precise,f.goal,f.anchor,f.slot]);
    }
    if(!f.selected.length)throw Error(f.sourceReason||'请选择与当前卡组主、副 Tag 匹配的可用展开来源');
    const value=await forecastTaskRequest(s,f,'plan-prepare',{id:requestId,slot:f.slot,anchor:!requestId?f.anchor:undefined,refresh,request_generation:generation,
      deck_id:s.deck.id,revision:s.deck.revision,hand_count:s.count,hand:[...s.hand],sources:[...f.selected],
      preference:f.preference,precise:f.precise,goal:[...(f.goal||[])]});
    if(!forecastAlive(s,f)||f.released||generation!==f.generation){
      void forecastTaskRequest(s,f,'plan-cancel',{job:value.job,slot:f.slot}).catch(()=>{});return;
    }
    f.job=value.job;f.version=value.version;f.jobState=value;
    await pollPreparedForecast(s,f,generation);
  }catch(error){
    if(previousJob)void forecastTaskRequest(s,f,'plan-cancel',{job:previousJob,slot:f.slot}).catch(()=>{});
    if(generation===f.generation){f.busy=false;f.error=error.message;if(!f.adopted)f.id=null;repaintForecast(s);}
  }
  finally{if(generation===f.generation)f.requestPending=false;}
}
async function launchPreparedForecast(s) {
  if(!s.deck||s.hand.some(c=>!c))throw Error('请先确认卡组并填写完整起手');
  if(s.stage===duelStages.plans){
    if(s.forecast&&duelForecastHasProgress(s))s.tutorialForecast=s.forecast;
    s.forecast=await prepareDuelOpening(s);
    if(!s.forecast.preferenceManual&&s.planSort&&s.forecast.preference!==s.planSort){s.forecast.preference=s.planSort;await prepareForecast(s,s.forecast);}
  }else if(s.plan&&!s.plan.temporary){
    const active=s.graph.nodes.find(n=>n.key===s.position.key),node=(s.context?autoDuelNodeSource:duelNodeSource)(active).node;
    if(node.kind!=='step')throw Error('请选择普通方案中已完成的步骤，再生成展开后续');
    const anchor={plan:s.plan.id,revision:s.plan.edit_revision||0,route:s.plan.duel_source_route||active.route,node:node.id,number:node.number};
    if(!s.tutorialForecast||JSON.stringify(s.tutorialForecast.anchor)!==JSON.stringify(anchor)){
      if(s.tutorialForecast)releasePreparedForecast(s,s.tutorialForecast);
      const base=await prepareDuelOpening(s);
      s.tutorialForecast={sources:base.sources,sourceReason:base.sourceReason,selected:[...base.selected],preference:base.preferenceManual?base.preference:(s.planSort||base.preference),preferenceManual:!!base.preferenceManual,precise:base.precise,goal:[...base.goal],generation:0,anchor,slot:'continuation'};
    }
    s.forecast=s.tutorialForecast;await prepareForecast(s,s.forecast);
  }else {
    s.forecast=s.tutorialForecast||s.forecast;s.forecast.slot='continuation';
    await prepareForecast(s,s.forecast,{refresh:true});
  }
  s.forecast.showResults=true;s.forecast.collapsed=false;
  if(s.context)renderAutoDuel();else renderDuel();
}
function duelForecastHasProgress(s) {
  return !!(s.forecast?.anchor||s.forecast?.data?.confirmed||(s.forecast?.slot!=='opening'&&s.plan?.temporary&&s.plan.confirmed));
}
function forecastStartText(s) {
  if(s.forecast.anchor&&!s.plan?.temporary)return `从所选 Step ${s.forecast.anchor.number} 完成后的局面计算后续。`;
  return duelForecastHasProgress(s)?'从已确认操作后的局面计算后续，保留已确认步骤。':'从本局已确认的起手计算路线。';
}
function duelConditionResults(result) {
  return result.excluded?.length?`<details class="duel-condition-results"><summary>未列为可原样执行的方案（${result.excluded.length}）</summary><ul>${result.excluded.map(p=>`<li><strong>${escape(p.name)}</strong> · ${escape(({random:'依赖随机结果',incomplete:'条件待核对',implicit:'区域资源不满足'})[p.stage]||'既有匹配条件不满足')}：${escape(p.reason)}</li>`).join('')}</ul></details>`:'';
}
function forecastStepText(step,catalog={}) {
  if(step.observation)return `${{draw:'实际抽到',mill:'实际随机堆墓',interruption:'受到阻抗'}[step.observation.kind]}：${step.observation.cards.map(c=>catalog[c]?.name||duelName(c)).join('、')}`;
  const selection=(step.bound_decision||step.decision).selection||[];
  const labels={summon:'通常召唤',special:'特殊召唤',activate:'发动效果',yes:'发动／确认',no:'不发动',card:'选择卡牌',material:'选择素材',place:'选择区域',option:'选择选项',finish_selection:'完成选择',spell_set:'盖放',pass:'放弃响应'};
  return selection.map(item=>`${step.operation_label||labels[item.kind]||item.kind||'选择'}${item.card?' '+(catalog[item.card.code]?.name||duelName(item.card.code)):item.place?' '+reviewPlace({controller:item.place[0],location:item.place[1],sequence:item.place[2]}):''}${item.effect&&step.effect_label?.text?'：'+step.effect_label.text:''}`).join('；')||'按提示完成选择';
}
function forecastStartsOperation(step) {
  return (step.bound_decision||step.decision).selection?.some(s=>['summon','special','activate','spell_set','monster_set'].includes(s.kind)||s.kind==='yes'&&s.effect);
}
function temporaryDuelPlan(data,candidate) {
  const prefix=data.prefix||[],steps=[...prefix,...candidate.steps],catalog=data.catalog;
  const state=value=>{const result=structuredClone(value);for(const c of result?.cards||[])c.identity_known=!!c.code&&!c.unknown;return result;};
  const nodes=[{id:'initial',kind:'initial',number:1,state:state(data.initial),action_ids:[]}],annotations={nodes:{},effects:{},cards:{},final_marks:{}};
  const groups=(data.prefix_layout||[]).filter(g=>g.end<prefix.length).map(g=>({...g,steps:steps.slice(g.start,g.end+1)}));
  const frozenEnd=groups.at(-1)?.end??-1;
  steps.forEach((step,index)=>{
    if(index<=frozenEnd)return;
    const starts=forecastStartsOperation(step),previous=groups.at(-1);
    const leadingChoices=previous&&previous.start>=prefix.length&&!previous.steps.some(forecastStartsOperation)&&!previous.steps.some(s=>s.observation);
    if(!groups.length||starts&&!leadingChoices||index===prefix.length||step.observation)groups.push({start:index,steps:[]});
    const group=groups.at(-1);group.steps.push(step);group.end=index;
  });
  groups.forEach((group,i)=>{
    const step=group.steps.find(forecastStartsOperation)||group.steps[0],id='forecast-'+i;
    nodes.push({id,kind:'step',number:i+2,source_number:group.number,state:state(group.steps.at(-1).state),action_ids:[],forecast_step:step,forecast_steps:group.steps,
      forecast_index:group.start-prefix.length,forecast_end:group.end-prefix.length,forecast_absolute_end:group.end});
    annotations.nodes[id]={name:group.name||`Step ${group.number||i+2}`,notes:group.notes||''};
  });
  nodes.push({id:'final',kind:'final',number:nodes.length+1,state:state(candidate.terminal||steps.at(-1)?.state||data.initial),action_ids:[]});
  const pending=!!candidate.observation_required||!candidate.steps.length;
  annotations.nodes.final={name:pending?'填写实际结果后继续':'预计终场',notes:pending?'后续尚未确定，请报告实际情况后重新计算。':'这是尚待确认的推演结果。'};
  for(const target of candidate.terminal_targets||[]){const id=String(target.card.instance_id);annotations.final_marks[id]=structuredClone(target.mark);annotations.cards[id]=target.note||'';}
  return {id:'temporary-'+data.route,name:'本局临时方案',temporary:true,forecastRoute:data.route,forecastOffset:prefix.length,
    confirmed:groups.filter(g=>g.end<prefix.length).length,pendingObservation:!!candidate.observation_required,forecastCandidate:candidate.id,
    catalog,terminalMarkStatus:candidate.terminal_mark_status||'unmarked',terminalMarkCount:candidate.terminal_mark_count||0,
    initial_hand:nodes[0].state.cards.filter(c=>c.controller===0&&c.location===2),final_state:nodes.at(-1).state,
    review:{nodes},annotations,actions:[],events:[],branches:[],requirements:{opening:duelState().hand.map(code=>({code,count:1}))}};
}
function forecastOperations(steps) {
  const operations=[],summonNames={0x10000000:'通常召唤',0x11000000:'上级召唤',0x12000000:'二重召唤',0x20000000:'反转召唤',0x40000000:'特殊召唤',0x43000000:'融合召唤',0x45000000:'仪式召唤',0x46000000:'同调召唤',0x49000000:'超量召唤',0x4a000000:'灵摆召唤',0x4c000000:'连接召唤'};
  const history=steps.flatMap(s=>s.before?.cards||[]),materialIds=new Set();
  const setCards=new Set(steps.filter(s=>(s.bound_decision||s.decision).selection?.some(c=>['spell_set','monster_set'].includes(c.kind))).flatMap(s=>(s.bindings||[]).map(b=>b.card?.instance_id)).filter(id=>id!=null));
  for(const step of steps) {
    const before=step.before?.cards||[],after=step.state?.cards||[],byId=new Map(before.filter(c=>c.instance_id!=null).map(c=>[c.instance_id,c]));
    for(const card of after) {
      if(card.instance_id==null||card.unknown||!card.code)continue;
      let origin=byId.get(card.instance_id);
      if(!origin){
        const fromDeck=before.filter(c=>c.controller===card.controller&&c.location===1&&c.code===card.code).length-after.filter(c=>c.controller===card.controller&&c.location===1&&c.code===card.code).length;
        if(fromDeck>0)origin={controller:card.controller,location:1};
      }
      if(!origin)continue;
      if(origin.location===card.location&&origin.controller===card.controller&&origin.position===card.position){
        if(card.disabled&&!origin.disabled)operations.push({message:76,cards:[{...card,identity_known:true}],role:''});
        continue;
      }
      const summoned=card.location===4&&origin.location!==4&&!!card.summon_info;
      const materials=summoned?(card.material_instance_ids||[]).map(id=>history.find(c=>c.instance_id===id&&[2,4].includes(c.location))).filter(Boolean):[];
      for(const material of materials)materialIds.add(material.instance_id);
      const shown={...card,identity_known:true,...(summoned?{summon_method:summonNames[card.summon_info&0xff000000]||'特殊召唤',materials}: {})};
      operations.push({message:summoned?(shown.summon_method==='通常召唤'?61:63):setCards.has(card.instance_id)&&[4,8].includes(card.location)?54:origin.location===card.location?53:50,cards:[shown],origin,destination:card,role:card.reason&0x80?'Cost':''});
    }
  }
  return operations.filter(op=>!op.cards.every(c=>materialIds.has(c.instance_id)));
}
function renderForecastStep(node,report,split=true) {
  const steps=node.forecast_steps||[node.forecast_step],first=steps.find(forecastStartsOperation)||steps[0],selection=(first.bound_decision||first.decision).selection||[];
  if(split){
    const parts=[];
    for(const step of steps){if(!parts.length||forecastStartsOperation(step)&&parts.at(-1).some(forecastStartsOperation))parts.push([]);parts.at(-1).push(step);}
    if(parts.length>1)return parts.map(part=>renderForecastStep({...node,forecast_steps:part,forecast_step:part[0]},report,false)).join('');
  }
  const context={...reviewLogContext(report,'compact'),editable:false},opts={report,name:true,zone:false,position:false,miniLocation:true};
  const actor=(first.bindings||[]).map(b=>b.card).filter(Boolean);
  const activation=cardActivation({kind:'effect',cards:actor,engine_effect:first.bindings?.find(b=>b.effect)?.effect},report);
  const activationCards=activation?actor.map(c=>steps.flatMap(s=>s.state?.cards||[]).find(after=>after.instance_id===c.instance_id&&after.location===8)||c):actor;
  const effect=selection.some(s=>s.kind==='activate'||s.kind==='yes'&&s.effect),stages=[];
  if(effect){const number=first.effect_label?.number;stages.push(`<div class="chain-stage"><small class="log-role">${escape(activation||`发动${number?`效果 ${number}`:'效果'}`)}</small><div class="compact-cards">${activationCards.map(c=>reviewLogCard({...c,identity_known:!!c.code},node.id,opts)).join('')}</div></div>`);}
  for(const step of steps.filter(s=>s.observation)){
    const used=new Set(),kind=step.observation.kind,side=kind==='interruption'?1:0;
    const cards=step.observation.cards.map(code=>{const actual=step.state?.cards?.find(c=>c.code===code&&c.controller===side&&!used.has(c.instance_id));if(actual)used.add(actual.instance_id);return {...(actual||{code,controller:side}),identity_known:true};});
    stages.push(`<div class="chain-stage"><small class="log-role">${{draw:'实际抽到',mill:'实际随机堆墓',interruption:'实际受到阻抗'}[kind]}</small><div class="compact-cards">${cards.map(c=>reviewLogCard(c,node.id,opts)).join('')}</div></div>`);
  }
  const operations=forecastOperations(steps).filter(op=>!(activation&&op.message===50&&op.destination?.location===8&&op.origin?.location!==8&&op.cards.every(c=>actor.some(a=>a.instance_id===c.instance_id))));
  stages.push(...operations.map(op=>compactOperation(op,node.id,op.role,context)));
  if(!stages.length){const label=first.operation_label||({summon:'通常召唤',special:'特殊召唤',spell_set:'盖放',monster_set:'盖放',place:'选择区域',no:'不发动',pass:'放弃响应'}[selection[0]?.kind])||'按图示选择';stages.push(`<div class="chain-stage"><small class="log-role">${escape(label)}</small><div class="compact-cards">${actor.map(c=>reviewLogCard({...c,identity_known:!!c.code},node.id,opts)).join('')}</div></div>`);}
  if(steps.some(s=>s.state?.cards?.some(c=>c.unknown)))stages.push('<div class="chain-stage"><small>随机结果待填写</small><img class="forecast-unknown-card" src="/review-back.svg" alt="尚未确认的随机卡牌"></div>');
  return `<article class="log-action forecast-step"><div class="compact-chain">${stages.join('<span class="chain-arrow">→</span>')}</div><details class="forecast-step-details"><summary>操作详情与来源</summary>${steps.filter(s=>!s.automatic).map(s=>`<p>${escape(forecastStepText(s,report.catalog))}</p><small>${escape(s.source?.name||'')} · ${escape(s.source?.route_name||'')}</small>`).join('')}</details><small class="forecast-status">${node.number-2<report.confirmed?'已确认':'待确认'}${steps.some(s=>s.observation)?' · 已填报实际结果':''}</small></article>`;
}
function renderForecastTerminal(node,report) {
  const cards=DuelModel.markedFinalCards(report);
  if(!cards.length)return '<p class="forecast-terminal-empty">此路线尚无已匹配的来源终场标记；未标记卡牌不列为有效终场。</p>';
  return reviewFinalCards(node,report,report.annotations,{compact:true})+(report.terminalMarkStatus==='partial'?'<p>部分来源终场标记未能对应到当前区域。</p>':'');
}
function renderDuelForecast() {
  const s=duelState(),f=s.forecast;if(!f||!f.showResults&&s.stage!==duelStages.tutorial)return;
  // Browsing the plan list preserves the tutorial, but must not expose its
  // continuation controls as an opening-hand generator.
  if(s.stage===duelStages.plans&&duelForecastHasProgress(s))return;
  if(s.stage===duelStages.tutorial&&!f.showResults&&s.plan?.temporary){
    const info=document.createElement('p');info.id='duel-forecast-progress';info.textContent=`本局临时方案 · 已确认 ${s.plan.confirmed} 步。下一步表示已照做；出现偏差请在对应步骤报告实际情况。`;
    $('#duel-body').prepend(info);return;
  }
  const panel=document.createElement('section');panel.className='modular-panel duel-forecast';panel.id='duel-modular-status';
  panel.innerHTML=`<header class="duel-forecast-heading"><h3>本局临时方案</h3><small id="duel-brain-compact-status"></small><button id="duel-brain-toggle" aria-expanded="${!f.collapsed}" aria-controls="duel-brain-content"><span aria-hidden="true">${f.collapsed?'▾':'▴'}</span>${f.collapsed?'展开':'收起'}</button></header><div id="duel-brain-content" class="duel-forecast-content" ${f.collapsed?'hidden':''}><p>${forecastStartText(s)}采用后进入步骤图，按实际操作推进。</p><details><summary>参与计算的来源</summary>${renderForecastSourceList(f)}</details><div id="duel-brain-controls" class="modular-toolbar"><label>偏好 <select id="duel-brain-preference"><option value="cheapest">花费最少</option><option value="largest">终场最大</option><option value="shortest">步骤最少</option><option value="balanced">平均</option></select></label><label><input id="duel-brain-precise" type="checkbox" ${f.precise?'checked':''}> 精确匹配</label><button id="duel-brain-search" ${f.busy?'disabled':''}>${f.busy?'正在生成…':'重新生成路线'}</button></div><p id="duel-brain-summary" role="status"></p><div id="duel-brain-routes"></div></div>`;
  $('#duel-body').prepend(panel);$('#duel-brain-preference').value=f.preference;
  $('#duel-brain-toggle').onclick=()=>{f.collapsed=!f.collapsed;const button=$('#duel-brain-toggle');button.setAttribute('aria-expanded',String(!f.collapsed));button.innerHTML=`<span aria-hidden="true">${f.collapsed?'▾':'▴'}</span>${f.collapsed?'展开':'收起'}`;$('#duel-brain-content').hidden=f.collapsed;};
  $('#duel-brain-search').insertAdjacentHTML('beforebegin','<label>目标场上卡号 <input id="duel-brain-goal" type="text" placeholder="可留空"></label>');
  $('#duel-brain-goal').value=(f.goal||[]).join(' ');
  const changed=refresh=>{f.selected=[...panel.querySelectorAll('[data-brain-source]:checked')].map(el=>el.dataset.brainSource);if(f.preference!==$('#duel-brain-preference').value)f.preferenceManual=true;f.preference=$('#duel-brain-preference').value;f.precise=$('#duel-brain-precise').checked;f.goal=$('#duel-brain-goal').value.trim().split(/[\s,，]+/).filter(Boolean).map(Number);return searchDuelBrain({refresh});};
  for(const input of panel.querySelectorAll('input,select'))input.onchange=run(()=>changed(false));
  $('#duel-brain-search').onclick=run(()=>changed(true));paintForecastResults();
}
function forecastSearchNotice(result) {
  if(!result)return '';
  const count=result.candidates?.length||0;
  if(result.limited)return `搜索尚未完成：已达到本轮预算，目前 ${count} 条只是已发现的路线，不能据此判断其他偏好没有不同方案。四种偏好已共享本轮搜索；可重试继续扩大已检查范围。`;
  if(result.complete===false)return '部分来源或后续条件尚未确认，当前候选不代表所有可能路线。';
  if(!count)return '当前局面与所选来源未找到可用路线，请查看各来源的具体原因。';
  if(count===1)return '当前来源和设置下只找到一条可用路线，暂无其他候选可比较，各偏好可能推荐同一条。';
  return '按当前偏好比较所有已发现候选；若同一路线同时占优，多种偏好可以推荐相同路线。';
}
function forecastCandidatesHtml(f,preferenceLabel,adoptAttribute) {
  return (f.data?.result?.candidates||[]).map((c,i)=>`<article class="modular-route forecast-route">
    <button class="forecast-route-choice" ${adoptAttribute}="${escape(c.id)}" aria-label="采用路线 ${i+1} 并进入下一步" ${f.busy?'disabled':''}>
    <strong>路线 ${i+1} · ${c.remaining} 次剩余决策</strong>
    ${i===0&&!f.busy?`<span class="modular-badge">${preferenceLabel}当前推荐</span>`:''}
    <small>终场 ${c.evaluation.marked_cards||0} 张 · 效果 ${c.evaluation.marked_effects||0} 项${f.preference==='balanced'?` · 平均 ${c.ranking?.average??0}`:''}</small>
    ${forecastCandidateTerminal(c,true)}
    <small>${escape(forecastCostText(c))}</small>
    <small>${c.observation_required?'等待实际随机结果':c.conditional?'包含未确定条件':'已通过引擎校验'}</small>
    <span class="forecast-route-adopt">采用此路线 →</span></button>
    <details class="forecast-route-details" data-candidate="${escape(c.id)}" ${(f.expandedCandidates||[]).includes(c.id)?'open':''}><summary>步骤与来源详情</summary>
    ${c.terminal_source?`<p>终场来源：${escape(c.terminal_source.route_name||c.terminal_source.name)}</p>`:''}<p>${escape(c.evaluation.basis)}</p><p>${escape(c.resource_cost?.basis||'来源资源消耗尚未评估')}</p>${f.preference==='balanced'?`<p>资源 ${c.ranking?.resources??0} · 终场 ${c.ranking?.terminal??0} · 步骤 ${c.ranking?.steps??0}；三项各占三分之一。</p>`:''}${forecastCandidateTerminal(c)}
    ${c.adaptations?.length?`<details><summary>相对来源路线的调整（已由引擎逐步校验）</summary>${c.adaptations.map(a=>`<p>${escape(a)}</p>`).join('')}</details>`:''}
    <ol>${c.steps.map(step=>`<li>${escape(forecastStepText(step,f.data.catalog))}<small> · ${escape(step.source.name)}</small></li>`).join('')}</ol></details></article>`).join('');
}
function forecastCostText(candidate) {
  const cost=candidate.resource_cost;
  return cost?.status==='complete'?`花费：手牌 ${cost.hand} · 卡组 ${cost.main} · 额外 ${cost.extra}${cost.other?' · 其他 '+cost.other:''}`:'资源消耗尚未评估';
}
function bindForecastCandidateDetails(container,f) {
  for(const details of container.querySelectorAll('.forecast-route-details'))details.ontoggle=()=>{
    if(!details.isConnected)return;
    const selected=new Set(f.expandedCandidates||[]);
    if(details.open)selected.add(details.dataset.candidate);else selected.delete(details.dataset.candidate);
    f.expandedCandidates=[...selected];
  };
}
function paintForecastResults() {
  const f=duelState().forecast,summary=$('#duel-brain-summary');if(!f||!summary)return;
  const candidates=f.data?.result?.candidates||[];
  const result=f.data?.result,preferenceLabel={cheapest:'花费最少',largest:'终场最大',shortest:'步骤最少',balanced:'平均'}[f.preference];
  const cache=result?.cache,cacheText=cache?.prepared_hit?' · 复用已准备结果':cache?.result_hit?' · 同一偏好的完整搜索结果':cache?.probe_hits?` · 复用 ${cache.probe_hits} 次规则校验`:'';
  const duration=Number.isFinite(f.data?.result?.seconds)?` · ${f.data.result.seconds} 秒`:'';
  summary.textContent=f.busy?`四种偏好正在后台准备 · ${f.jobState?.progress?.phase||f.jobState?.status||"初始化"} · 已检查 ${f.jobState?.progress?.nodes||0} 次决策 · 已有 ${f.jobState?.progress?.candidates||0} 条部分候选（评价尚未完成）。当前教程进度保留。`:f.error|| (f.data?`已找到 ${candidates.length} 条路线 · 当前偏好：${preferenceLabel}${result.coverage?` · 来源路线检查 ${result.coverage.checked}/${result.coverage.total}`:''}${cacheText}${duration}。${forecastSearchNotice(result)}`:'选择展开来源后生成路线。');
  $('#duel-brain-compact-status').textContent=f.busy?'正在计算…':f.error?'生成未完成':f.data?`${candidates.length} 条候选${result.complete===false?' · 搜索尚未完成':''}`:'';
  $('#duel-brain-search').disabled=!!f.busy;
  $('#duel-brain-search').textContent=f.busy?'正在生成…':'重新生成路线';
  const checks=result?.coverage?.routes||[],states={queued:'尚未检查',checking:'检查未完成',checked:'已完成路线检查',goal_reached:'已匹配终场标记',blocked:'原路线在当前局面未通过',no_start:'当前窗口无可匹配的来源动作',needs_observation:'等待实际随机结果'};
  const coverage=checks.length?`<details class="forecast-source-checks"><summary>各来源原路线的检查结果</summary><ul>${checks.map(c=>`<li>${escape(c.source.route_name||c.source.name)}：${escape(states[c.status]||c.status)} · ${c.checked}/${c.total}${c.reason?` · ${escape(c.reason)}`:''}</li>`).join('')}</ul></details>`:'';
  $('#duel-brain-routes').innerHTML=coverage+forecastCandidatesHtml(f,preferenceLabel,'data-duel-adopt');
  bindForecastCandidateDetails($('#duel-brain-routes'),f);
  for(const button of $('#duel-brain-routes').querySelectorAll('[data-duel-adopt]'))button.onclick=run(()=>adoptDuelForecast(button.dataset.duelAdopt));
}
function forecastCandidateTerminal(candidate,compact=false) {
  const targets=candidate.terminal_targets||[];
  return `<div class="${compact?'duel-tile-cards forecast-terminal-cards':'duel-summary-cards'}">${targets.slice(0,compact?4:targets.length).map(({card,mark})=>`<figure><img src="/pics/${Number(card.code)}.jpg" alt="${escape(card.name||duelName(card.code))}"><figcaption title="${escape(card.name||duelName(card.code))}">${escape(card.name||duelName(card.code))}</figcaption><small class="duel-region">${escape(duelRegion(card))}${card.disabled?' · 当前无效':''}</small>${!compact&&Object.keys(mark.effects||{}).filter(k=>mark.effects[k]).length?`<small>标记效果 ${Object.values(mark.effects).filter(Boolean).length} 项</small>`:''}</figure>`).join('')||'<small>尚无可展示的来源终场标记。</small>'}${compact&&targets.length>4?`<small>另 ${targets.length-4} 张见详情</small>`:''}</div>${candidate.terminal_mark_status==='partial'?'<small>部分来源标记未对应到本局终场。</small>':''}`;
}
async function launchModularFromDuel() {return launchPreparedForecast(duelState());}
async function searchDuelBrain(options={}) {const s=duelState();if(s.forecast)return prepareForecast(s,s.forecast,options);}
async function adoptDuelForecast(candidateId) {
  const s=duelState(),f=s.forecast;if(!f||f.busy)return;
  const generation=f.generation;
  f.busy=true;paintForecastResults();
  try {
    const data=await forecastTaskRequest(s,f,'plan-adopt',{id:f.id,candidate:candidateId,job:f.job,version:f.version,preference:f.preference,slot:f.slot});
    if(s!==duelState()||s.forecast!==f||generation!==f.generation){if(data.id!==f.id)void forecastTaskRequest(s,f,'plan-close',{id:data.id}).catch(()=>{});return;}
    clearTimeout(f.timer);f.adopted=true;f.job=null;f.prepared={};f.data=data;f.showResults=false;if(s.tutorialForecast&&s.tutorialForecast!==f)releasePreparedForecast(s,s.tutorialForecast);s.tutorialForecast=f;if(s.openingForecast===f)s.openingForecast=null;s.plan=temporaryDuelPlan(data,data.result.candidates[0]);
    s.routes=duelPlanRoutes(s.plan);s.graph=DuelModel.graph(s.routes);
    const first=reviewNodes(s.plan).find(n=>n.kind==='step'&&n.forecast_index===0);
    s.position={key:'main/'+(first?.id||'final'),choice:0};s.enabled=true;s.ended=false;
    if(s.operationMode==='automatic')s.manualReached=Math.max(s.manualReached||0,duelStages.tutorial);
    else {duelReach(duelStages.tutorial);duelTell('');}
  }finally{if(generation===f.generation)f.busy=false;renderDuel();void syncDuelShortcuts();}
}
async function advanceDuelForecast() {
  const s=duelState(),f=s.forecast,p=s.plan;if(!f||f.busy||!p?.temporary)return;
  if(p.stale)return duelTell('当前后续正在重新生成，请采用最新路线后继续。');
  const node=duelNodeSource(s.graph.nodes.find(n=>n.key===s.position.key)).node;
  if(node.kind==='step'&&node.number-2>=p.confirmed){
    if(p.pendingObservation&&node.id===reviewNodes(p).filter(n=>n.kind==='step').at(-1)?.id)return openDuelObservation();
    f.busy=true;
    try{const value=await modularDispatch('duel','plan-confirm',{id:f.id,route:p.forecastRoute,index:node.forecast_index,through:node.forecast_end});if(s!==duelState()||s.forecast!==f||s.plan!==p)return;p.confirmed=reviewNodes(p).filter(n=>n.kind==='step'&&n.forecast_absolute_end<value.confirmed).length;}
    finally{f.busy=false;}
  }
  s.position=DuelModel.navigate(s.graph,s.position,'forward');renderDuel();
}
async function selectForecastNode(key) {
  const s=duelState(),p=s.plan,target=s.graph.nodes.find(n=>n.key===key);if(!target||s.forecast?.busy)return;
  const next=DuelModel.navigate(s.graph,s.position,'forward');
  if(key!==s.position.key&&key===next.key)return advanceDuelForecast();
  const node=duelNodeSource(target).node;
  if(node.kind==='final'&&p.confirmed<reviewNodes(p).filter(n=>n.kind==='step').length||node.kind==='step'&&node.number-2>p.confirmed)return duelTell('请先逐步确认前面的步骤。');
  s.position={key,choice:0};paintDuelPosition();
}
const observationDialog=document.createElement('dialog');observationDialog.id='duel-observation';observationDialog.className='duel-shortcut-dialog';document.body.append(observationDialog);
async function openDuelObservation() {
  const s=duelState(),f=s.forecast,p=s.plan;if(!p?.temporary||!f||f.busy)return;
  const node=duelNodeSource(s.graph.nodes.find(n=>n.key===s.position.key)).node;
  if(node.kind!=='step'||node.forecast_index<0)return duelTell('请选择当前临时路线中需要报告实际情况的步骤。');
  let selected=[],searchRevision=0,timer;
  observationDialog.innerHTML=`<h2>报告 Step ${node.number} 的实际情况</h2><p>${escape(forecastStepText(node.forecast_step,p.catalog))}</p><label>发生了什么 <select id="duel-observation-kind"><option value="draw">随机获得手牌</option><option value="mill">随机堆墓</option><option value="interruption">受到阻抗</option></select></label><p>填写本步骤实际出现的全部卡牌，可重复选择。阻抗填写发动的卡片及实际支付的手牌费用。</p><input id="duel-observation-query" type="search" placeholder="搜索卡名或卡号" aria-label="搜索实际卡牌"><div id="duel-observation-results" class="forecast-card-search"></div><div id="duel-observation-selected" class="forecast-card-search"></div><p id="duel-observation-error" role="status"></p><div class="duel-actions"><button id="duel-observation-cancel">取消</button><button id="duel-observation-submit">确认实际结果并重算后续</button></div>`;
  const paint=()=>{$('#duel-observation-selected').innerHTML=selected.map((c,i)=>`<button data-remove-observation="${i}"><img src="/pics/${c.code}.jpg" alt="">${escape(c.name)} ×</button>`).join('');for(const b of observationDialog.querySelectorAll('[data-remove-observation]'))b.onclick=()=>{selected.splice(Number(b.dataset.removeObservation),1);paint();};};
  $('#duel-observation-query').oninput=()=>{clearTimeout(timer);const revision=++searchRevision,q=$('#duel-observation-query').value.trim();timer=setTimeout(run(async()=>{if(!q)return;const data=await api('/api/cards?q='+encodeURIComponent(q));data.cards=data.cards.map(c=>({...c,code:c.id}));if(revision!==searchRevision||!observationDialog.open)return;$('#duel-observation-results').innerHTML=data.cards.slice(0,16).map(c=>`<button data-observation-code="${c.code}"><img src="/pics/${c.code}.jpg" alt="">${escape(c.name)}</button>`).join('');for(const b of observationDialog.querySelectorAll('[data-observation-code]'))b.onclick=()=>{selected.push(data.cards.find(c=>c.code===Number(b.dataset.observationCode)));paint();};}),180);};
  $('#duel-observation-cancel').onclick=()=>observationDialog.close();
  $('#duel-observation-submit').onclick=async()=>{
    if(!selected.length){$('#duel-observation-error').textContent='请选择实际卡牌。';return;}
    f.busy=true;for(const control of observationDialog.querySelectorAll('button,input,select'))control.disabled=true;
    $('#duel-observation-error').textContent='正在根据实际结果重新计算…';
    try{
      const kind=$('#duel-observation-kind').value;
      const data=await modularDispatch('duel','plan-observe',{id:f.id,route:p.forecastRoute,index:node.forecast_index,through:node.forecast_end,kind,cards:selected.map(c=>c.code)});
      if(s!==duelState()||s.forecast!==f)return;
      f.data=data;f.busy=false;observationDialog.close();
      if(data.result.candidates.length)await adoptDuelForecast(data.result.candidates[0].id);
      else {
        s.plan=temporaryDuelPlan(data,{steps:[],terminal:data.prefix.at(-1)?.state||data.initial});s.plan.stale=true;
        s.routes=duelPlanRoutes(s.plan);s.graph=DuelModel.graph(s.routes);s.position={key:'main/final',choice:0};
        f.showResults=true;renderDuel();duelTell('已记录实际结果，当前来源未找到可用后续。请调整来源后重新生成。');
      }
    }catch(error){$('#duel-observation-error').textContent=error.message;}
    finally{f.busy=false;for(const control of observationDialog.querySelectorAll('button,input,select'))control.disabled=false;}
  };
  observationDialog.showModal();await syncDuelShortcuts();
}
observationDialog.addEventListener('close',()=>void syncDuelShortcuts());
observationDialog.addEventListener('cancel',event=>{if(duelState().forecast?.busy)event.preventDefault();});
