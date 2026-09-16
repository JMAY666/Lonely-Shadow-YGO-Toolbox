'use strict';

function dropDuelForecast(s) {
  const f=s.forecast;if(!f)return;
  s.forecast=null;++f.generation;
  if(f.id)void modularDispatch('duel','plan-close',{id:f.id}).catch(()=>{});
}
function forecastStepText(step,catalog={}) {
  if(step.observation)return `${{draw:'实际抽到',mill:'实际随机堆墓',interruption:'受到阻抗'}[step.observation.kind]}：${step.observation.cards.map(c=>catalog[c]?.name||duelName(c)).join('、')}`;
  const selection=(step.bound_decision||step.decision).selection||[];
  const labels={summon:'通常召唤',special:'特殊召唤',activate:'发动效果',yes:'发动／确认',no:'不发动',card:'选择卡牌',material:'选择素材',place:'选择区域',option:'选择选项',finish_selection:'完成选择',spell_set:'盖放',pass:'放弃响应'};
  return selection.map(item=>`${step.operation_label||labels[item.kind]||item.kind||'选择'}${item.card?' '+(catalog[item.card.code]?.name||duelName(item.card.code)):item.place?' '+reviewPlace({controller:item.place[0],location:item.place[1],sequence:item.place[2]}):''}${item.effect&&step.effect_label?.text?'：'+step.effect_label.text:''}`).join('；')||'按提示完成选择';
}
function temporaryDuelPlan(data,candidate) {
  const prefix=data.prefix||[],steps=[...prefix,...candidate.steps],catalog=data.catalog;
  const state=value=>{const result=structuredClone(value);for(const c of result?.cards||[])c.identity_known=!!c.code&&!c.unknown;return result;};
  const nodes=[{id:'initial',kind:'initial',number:1,state:state(data.initial),action_ids:[]}],annotations={nodes:{},effects:{}};
  const groups=[];
  steps.forEach((step,index)=>{
    const starts=(step.bound_decision||step.decision).selection?.some(s=>['summon','special','activate','spell_set','monster_set'].includes(s.kind)||s.kind==='yes'&&s.effect);
    if(!groups.length||starts||index===prefix.length||step.observation)groups.push({start:index,steps:[]});
    const group=groups.at(-1);group.steps.push(step);group.end=index;
  });
  groups.forEach((group,i)=>{
    const step=group.steps[0],id='forecast-'+i,label=forecastStepText(step,catalog);
    nodes.push({id,kind:'step',number:i+2,state:state(group.steps.at(-1).state),action_ids:[],forecast_step:step,forecast_steps:group.steps,
      forecast_index:group.start-prefix.length,forecast_end:group.end-prefix.length,forecast_absolute_end:group.end});
    annotations.nodes[id]={name:label,notes:''};
  });
  nodes.push({id:'final',kind:'final',number:nodes.length+1,state:state(candidate.terminal||steps.at(-1)?.state||data.initial),action_ids:[]});
  const pending=!!candidate.observation_required||!candidate.steps.length;
  annotations.nodes.final={name:pending?'填写实际结果后继续':'预计终场',notes:pending?'后续尚未确定，请报告实际情况后重新计算。':'这是尚待确认的推演结果。'};
  return {id:'temporary-'+data.route,name:'本局临时方案',temporary:true,forecastRoute:data.route,forecastOffset:prefix.length,
    confirmed:groups.filter(g=>g.end<prefix.length).length,pendingObservation:!!candidate.observation_required,forecastCandidate:candidate.id,
    catalog,initial_hand:nodes[0].state.cards.filter(c=>c.controller===0&&c.location===2),final_state:nodes.at(-1).state,
    review:{nodes},annotations,actions:[],events:[],branches:[],requirements:{opening:duelState().hand.map(code=>({code,count:1}))}};
}
function renderForecastStep(node,report) {
  const steps=node.forecast_steps||[node.forecast_step],visible=steps.filter(step=>!step.automatic||(step.bound_decision||step.decision).selection?.some(s=>!['pass','no'].includes(s.kind)));
  const codes=[...new Set(steps.flatMap(step=>step.observation?.cards||(step.bound_decision||step.decision).selection.map(s=>s.card?.code).filter(Boolean)))];
  return `<article class="log-action forecast-step">${visible.map(step=>`<p>${escape(forecastStepText(step,report.catalog))}</p>`).join('')}<div class="compact-cards">${codes.map(code=>`<span><img src="/pics/${code}.jpg" alt="${escape(report.catalog[code]?.name||duelName(code))}"><small>${escape(report.catalog[code]?.name||duelName(code))}</small></span>`).join('')}</div><small>${node.number-2<report.confirmed?'已确认':'待确认'}${steps.some(s=>s.observation)?' · 已填报实际结果':''}</small></article>`;
}
function renderForecastTerminal(node,report) {
  const cards=(node.state?.cards||[]).filter(c=>c.controller===0&&[4,8,16,32].includes(c.location));
  return `<div class="forecast-step"><div class="compact-cards">${cards.filter(c=>c.code).map(c=>`<span><img src="/pics/${c.code}.jpg" alt="${escape(c.name||duelName(c.code))}"><small>${escape(c.name||duelName(c.code))} · ${escape(zoneNames[c.location])}</small></span>`).join('')}</div>${cards.some(c=>!c.code)?'<p>部分随机结果待填写。</p>':''}<small>手牌 ${(node.state?.cards||[]).filter(c=>c.controller===0&&c.location===2).length} · LP ${node.state?.lp?.[0]??'未知'}</small></div>`;
}
function renderDuelForecast() {
  const s=duelState(),f=s.forecast;if(!f)return;
  if(s.stage===5&&!f.showResults){
    const info=document.createElement('p');info.id='duel-forecast-progress';info.textContent=`本局临时方案 · 已确认 ${s.plan.confirmed} 步。下一步表示已照做；出现偏差请在对应步骤报告实际情况。`;
    $('#duel-body').prepend(info);return;
  }
  const panel=document.createElement('section');panel.className='modular-panel duel-forecast';panel.id='duel-modular-status';
  panel.innerHTML=`<h3>本局临时方案</h3><p>后台读取卡组和展开来源并计算路线。采用后进入步骤图，按实际操作推进。</p><details><summary>参与计算的来源</summary>${f.sources.map(source=>`<label><input type="checkbox" data-brain-source="${escape(source.id)}" ${f.selected.includes(source.id)?'checked':''}>${escape(source.name)}</label>`).join('')}</details><div id="duel-brain-controls" class="modular-toolbar"><label>偏好 <select id="duel-brain-preference"><option value="shortest">步骤最少</option><option value="largest">终场最大</option><option value="safest">稳妥优先</option></select></label><label><input id="duel-brain-precise" type="checkbox" ${f.precise?'checked':''}> 精确匹配</label><button id="duel-brain-search" ${f.busy?'disabled':''}>${f.busy?'正在生成…':'重新生成路线'}</button></div><p id="duel-brain-summary" role="status"></p><div id="duel-brain-routes"></div>`;
  $('#duel-body').prepend(panel);$('#duel-brain-preference').value=f.preference;
  $('#duel-brain-search').insertAdjacentHTML('beforebegin','<label>目标场上卡号 <input id="duel-brain-goal" type="text" placeholder="可留空"></label>');
  $('#duel-brain-goal').value=(f.goal||[]).join(' ');
  const changed=()=>{f.selected=[...panel.querySelectorAll('[data-brain-source]:checked')].map(el=>el.dataset.brainSource);f.preference=$('#duel-brain-preference').value;f.precise=$('#duel-brain-precise').checked;f.goal=$('#duel-brain-goal').value.trim().split(/[\s,，]+/).filter(Boolean).map(Number);return searchDuelBrain();};
  for(const input of panel.querySelectorAll('input,select'))input.onchange=run(changed);
  $('#duel-brain-search').onclick=run(changed);paintForecastResults();
}
function paintForecastResults() {
  const f=duelState().forecast,summary=$('#duel-brain-summary');if(!f||!summary)return;
  const candidates=f.data?.result?.candidates||[];
  summary.textContent=f.busy?'正在后台计算；当前页面与已确认进度保留。':f.error|| (f.data?`已生成 ${candidates.length} 条路线${candidates.length?'，采用后查看步骤图。':'。当前来源未找到后续，可调整来源或补充实际情况后重试。'}`:'选择展开来源后生成路线。');
  $('#duel-brain-search').disabled=!!f.busy;
  $('#duel-brain-routes').innerHTML=candidates.map((c,i)=>`<article class="modular-route"><h3>路线 ${i+1} · ${c.steps.length} 个步骤</h3><p>${c.observation_required?'到随机结果处暂停，填写实际卡牌后续算':c.conditional?'包含未确定条件':'已通过后台引擎校验'}</p><p>场上 ${c.evaluation.board} · 手牌 ${c.evaluation.hand} · LP ${c.evaluation.lp}</p><div class="modular-cards">${c.terminal.cards.filter(card=>card.controller===0&&[4,8].includes(card.location)&&card.code).map(card=>`<img src="/pics/${card.code}.jpg" alt="${escape(card.name)}">`).join('')}</div><details><summary>查看步骤与来源</summary><ol>${c.steps.map(step=>`<li>${escape(forecastStepText(step,f.data.catalog))}<small> · ${escape(step.source.name)}</small></li>`).join('')}</ol></details><button data-duel-adopt="${c.id}" ${f.busy?'disabled':''}>采用临时方案并进入下一步</button></article>`).join('');
  for(const button of $('#duel-brain-routes').querySelectorAll('[data-duel-adopt]'))button.onclick=run(()=>adoptDuelForecast(button.dataset.duelAdopt));
}
async function launchModularFromDuel() {
  const s=duelState();if(!s.deck||s.hand.some(c=>!c))throw new Error('请先确认卡组并填写完整起手');
  if(!s.forecast){const library=await api('/api/modular/library');if(s!==duelState())return;
    const sources=library.sources.filter(source=>source.status==='ready');
    s.forecast={sources,selected:sources.map(source=>source.id),preference:'shortest',precise:false,generation:0,showResults:true};
  }
  s.forecast.showResults=true;renderDuel();await searchDuelBrain();
}
async function searchDuelBrain() {
  const s=duelState(),f=s.forecast;if(!f)return;
  ++f.generation;f.queued=true;f.data=null;f.error='';if(s.plan?.temporary)s.plan.stale=true;
  if(f.busy){paintForecastResults();return;}
  f.busy=true;
  try {while(f.queued&&s===duelState()&&s.forecast===f){
    f.queued=false;const generation=f.generation;paintForecastResults();
    let data;
    try{data=await modularDispatch('duel','plan',{id:f.id,deck_id:s.deck.id,revision:s.deck.revision,hand_count:s.count,hand:[...s.hand],sources:[...f.selected],preference:f.preference,precise:f.precise,goal:[...(f.goal||[])]});}
    catch(error){if(generation!==f.generation)continue;throw error;}
    if(s!==duelState()||s.forecast!==f){void modularDispatch('duel','plan-close',{id:data.id}).catch(()=>{});return;}
    f.id=data.id;if(generation===f.generation)f.data=data;
  }}catch(error){if(s.forecast===f)f.error=error.message;}
  finally{f.busy=false;if(s.forecast===f)paintForecastResults();}
}
async function adoptDuelForecast(candidateId) {
  const s=duelState(),f=s.forecast;if(!f||f.busy)return;
  f.busy=true;paintForecastResults();
  try {
    const data=await modularDispatch('duel','plan-adopt',{id:f.id,candidate:candidateId});if(s!==duelState()||s.forecast!==f)return;
    f.data=data;f.showResults=false;s.plan=temporaryDuelPlan(data,data.result.candidates[0]);
    s.routes=duelPlanRoutes(s.plan);s.graph=DuelModel.graph(s.routes);
    const first=reviewNodes(s.plan).find(n=>n.kind==='step'&&n.forecast_index===0);
    s.position={key:'main/'+(first?.id||'final'),choice:0};s.enabled=true;s.ended=false;duelReach(5);duelTell('');
  }finally{f.busy=false;renderDuel();void syncDuelShortcuts();}
}
async function advanceDuelForecast() {
  const s=duelState(),f=s.forecast,p=s.plan;if(!f||f.busy||!p?.temporary)return;
  if(p.stale)return duelTell('当前后续正在重新生成，请采用最新路线后继续。');
  const node=duelNodeSource(s.graph.nodes.find(n=>n.key===s.position.key)).node;
  if(node.kind==='step'&&node.number-2>=p.confirmed){
    if(p.pendingObservation&&node.id===reviewNodes(p).filter(n=>n.kind==='step').at(-1)?.id)return openDuelObservation();
    f.busy=true;
    try{const value=await modularDispatch('duel','plan-confirm',{id:f.id,route:p.forecastRoute,index:node.forecast_index,through:node.forecast_end});if(s!==duelState())return;p.confirmed=reviewNodes(p).filter(n=>n.kind==='step'&&n.forecast_absolute_end<value.confirmed).length;}
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
