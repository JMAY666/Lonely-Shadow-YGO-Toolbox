'use strict';
// Isolated automatic-mode forecast controller and dialogs.

function autoRenderDuelForecast() {
  const s=autoDuelState(),f=s.forecast;if(!f||!f.showResults&&s.stage!==duelStages.tutorial)return;
  // Browsing the plan list preserves the tutorial, but must not expose its
  // continuation controls as an opening-hand generator.
  if(s.stage===duelStages.plans&&duelForecastHasProgress(s))return;
  if(s.stage===duelStages.tutorial&&!f.showResults&&s.plan?.temporary){
    const info=document.createElement('p');info.id='auto-duel-forecast-progress';info.textContent=`本局临时方案 · 已确认 ${s.plan.confirmed} 步。下一步表示已照做；出现偏差请在对应步骤报告实际情况。`;
    $('#auto-duel-content').prepend(info);return;
  }
  const panel=document.createElement('section');panel.className='modular-panel auto-duel-forecast';panel.id='auto-duel-modular-status';
  panel.innerHTML=`<header class="auto-duel-forecast-heading"><h3>本局临时方案</h3><small id="auto-duel-brain-compact-status"></small><button id="auto-duel-brain-toggle" aria-expanded="${!f.collapsed}" aria-controls="auto-duel-brain-content"><span aria-hidden="true">${f.collapsed?'▾':'▴'}</span>${f.collapsed?'展开':'收起'}</button></header><div id="auto-duel-brain-content" class="auto-duel-forecast-content" ${f.collapsed?'hidden':''}><p>${forecastStartText(s)}采用后进入步骤图，按实际操作推进。</p><details><summary>参与计算的来源</summary>${f.sources.map(source=>`<label><input type="checkbox" data-brain-source="${escape(source.id)}" ${f.selected.includes(source.id)?'checked':''}>${escape(source.name)}</label>`).join('')}</details><div id="auto-duel-brain-controls" class="modular-toolbar"><label>偏好 <select id="auto-duel-brain-preference"><option value="shortest">步骤最少</option><option value="largest">终场最大</option><option value="balanced">平均值（均衡）</option><option value="safest">稳妥优先</option></select></label><label><input id="auto-duel-brain-precise" type="checkbox" ${f.precise?'checked':''}> 精确匹配</label><button id="auto-duel-brain-search" ${f.busy?'disabled':''}>${f.busy?'正在生成…':'重新生成路线'}</button></div><p id="auto-duel-brain-summary" role="status"></p><div id="auto-duel-brain-routes"></div></div>`;
  $('#auto-duel-content').prepend(panel);$('#auto-duel-brain-preference').value=f.preference;
  $('#auto-duel-brain-toggle').onclick=()=>{f.collapsed=!f.collapsed;const button=$('#auto-duel-brain-toggle');button.setAttribute('aria-expanded',String(!f.collapsed));button.innerHTML=`<span aria-hidden="true">${f.collapsed?'▾':'▴'}</span>${f.collapsed?'展开':'收起'}`;$('#auto-duel-brain-content').hidden=f.collapsed;};
  $('#auto-duel-brain-search').insertAdjacentHTML('beforebegin','<label>目标场上卡号 <input id="auto-duel-brain-goal" type="text" placeholder="可留空"></label>');
  $('#auto-duel-brain-goal').value=(f.goal||[]).join(' ');
  const changed=refresh=>{f.selected=[...panel.querySelectorAll('[data-brain-source]:checked')].map(el=>el.dataset.brainSource);if(f.preference!==$('#auto-duel-brain-preference').value)f.preferenceManual=true;f.preference=$('#auto-duel-brain-preference').value;f.precise=$('#auto-duel-brain-precise').checked;f.goal=$('#auto-duel-brain-goal').value.trim().split(/[\s,，]+/).filter(Boolean).map(Number);return autoSearchDuelBrain({refresh});};
  for(const input of panel.querySelectorAll('input,select'))input.onchange=run(()=>changed(false));
  $('#auto-duel-brain-search').onclick=run(()=>changed(true));autoPaintForecastResults();
}

function autoPaintForecastResults() {
  const f=autoDuelState()?.forecast,summary=$('#auto-duel-brain-summary');if(!f||!summary)return;
  const candidates=f.data?.result?.candidates||[];
  const result=f.data?.result,preferenceLabel={shortest:'步骤最少',largest:'终场最大',balanced:'平均值（均衡）',safest:'稳妥优先'}[f.preference];
  const cache=result?.cache,cacheText=cache?.prepared_hit?' · 复用已准备结果':cache?.result_hit?' · 同一偏好的完整搜索结果':cache?.probe_hits?` · 复用 ${cache.probe_hits} 次规则校验`:'';
  const duration=Number.isFinite(f.data?.result?.seconds)?` · ${f.data.result.seconds} 秒`:'';
  summary.textContent=f.busy?`四种偏好正在后台准备 · ${f.jobState?.progress?.phase||f.jobState?.status||"初始化"} · 已检查 ${f.jobState?.progress?.nodes||0} 次决策 · 已有 ${f.jobState?.progress?.candidates||0} 条部分候选（评价尚未完成）。当前教程进度保留。`:f.error|| (f.data?`已找到 ${candidates.length} 条路线 · 当前偏好：${preferenceLabel}${result.coverage?` · 来源路线检查 ${result.coverage.checked}/${result.coverage.total}`:''}${cacheText}${duration}。${forecastSearchNotice(result)}`:'选择展开来源后生成路线。');
  $('#auto-duel-brain-compact-status').textContent=f.busy?'正在计算…':f.error?'生成未完成':f.data?`${candidates.length} 条候选${result.complete===false?' · 搜索尚未完成':''}`:'';
  $('#auto-duel-brain-search').disabled=!!f.busy;
  const checks=result?.coverage?.routes||[],states={queued:'尚未检查',checking:'检查未完成',checked:'已完成路线检查',goal_reached:'已匹配终场标记',blocked:'原路线在当前局面未通过',no_start:'当前窗口无可匹配的来源动作',needs_observation:'等待实际随机结果'};
  const coverage=checks.length?`<details class="forecast-source-checks"><summary>各来源原路线的检查结果</summary><ul>${checks.map(c=>`<li>${escape(c.source.route_name||c.source.name)}：${escape(states[c.status]||c.status)} · ${c.checked}/${c.total}${c.reason?` · ${escape(c.reason)}`:''}</li>`).join('')}</ul></details>`:'';
  $('#auto-duel-brain-routes').innerHTML=coverage+candidates.map((c,i)=>`<article class="modular-route"><h3>路线 ${i+1} · ${c.remaining} 次剩余决策${i===0&&!f.busy?` · ${preferenceLabel}当前推荐`:''}</h3>${c.terminal_source?`<p>终场标记来源：${escape(c.terminal_source.route_name||c.terminal_source.name)}</p>`:''}${f.preference==='safest'?`<p>稳妥性：${c.robustness?.status==='evaluated'?'已校验限定的灰流丽场景':'尚未充分评估，不能视为低风险'}</p>`:''}<p>${c.observation_required?'到随机结果处暂停，填写实际卡牌后续算':c.conditional?'包含未确定条件':'已通过后台引擎校验'}</p><p>标记终场 ${c.evaluation.marked_cards||0} 张 · 标记效果 ${c.evaluation.marked_effects||0} 项${f.preference==='balanced'?` · 平均 ${c.ranking?.average??0}`:''}</p><p>${escape(c.evaluation.basis)}</p>${forecastCandidateTerminal(c)}${c.adaptations?.length?`<details><summary>相对来源路线的调整（已由引擎逐步校验）</summary>${c.adaptations.map(a=>`<p>${escape(a)}</p>`).join('')}</details>`:''}<details><summary>查看步骤与来源</summary><ol>${c.steps.map(step=>`<li>${escape(forecastStepText(step,f.data.catalog))}<small> · ${escape(step.source.name)}</small></li>`).join('')}</ol></details><button data-auto-duel-adopt="${c.id}" ${f.busy?'disabled':''}>采用临时方案并进入下一步</button></article>`).join('');
  for(const button of $('#auto-duel-brain-routes').querySelectorAll('[data-auto-duel-adopt]'))button.onclick=run(()=>autoAdoptDuelForecast(button.dataset.autoDuelAdopt));
}

async function autoLaunchModularFromDuel() {return launchPreparedForecast(autoDuelState());}
async function autoSearchDuelBrain(options={}) {const s=autoDuelState();if(s.forecast)return prepareForecast(s,s.forecast,options);}

async function autoAdoptDuelForecast(candidateId) {
  const s=autoDuelState(),f=s.forecast;if(!f||f.busy)return;
  const generation=f.generation;
  f.busy=true;autoPaintForecastResults();
  try {
    const data=await autoDuelDispatch('plan-adopt',{id:f.id,candidate:candidateId,job:f.job,version:f.version,preference:f.preference,slot:f.slot});
    if(s!==autoDuelState()||s.forecast!==f||generation!==f.generation){if(data.id!==f.id)void forecastTaskRequest(s,f,'plan-close',{id:data.id}).catch(()=>{});return;}
    clearTimeout(f.timer);f.adopted=true;f.job=null;f.prepared={};f.data=data;f.showResults=false;if(s.tutorialForecast&&s.tutorialForecast!==f)releasePreparedForecast(s,s.tutorialForecast);s.tutorialForecast=f;if(s.openingForecast===f)s.openingForecast=null;s.plan=temporaryDuelPlan(data,data.result.candidates[0]);
    s.routes=duelPlanRoutes(s.plan);s.graph=DuelModel.graph(s.routes);
    const first=reviewNodes(s.plan).find(n=>n.kind==='step'&&n.forecast_index===0);
    s.position={key:'main/'+(first?.id||'final'),choice:0};s.enabled=true;s.ended=false;autoDuelReach(duelStages.tutorial);autoDuelTell('');
  }finally{if(generation===f.generation)f.busy=false;renderAutoDuel();void syncAutoDuelShortcuts();}
}

async function autoAdvanceDuelForecast() {
  const s=autoDuelState(),f=s.forecast,p=s.plan;if(!f||f.busy||!p?.temporary)return;
  if(p.stale)return autoDuelTell('当前后续正在重新生成，请采用最新路线后继续。');
  const node=autoDuelNodeSource(s.graph.nodes.find(n=>n.key===s.position.key)).node;
  if(node.kind==='step'&&node.number-2>=p.confirmed){
    if(p.pendingObservation&&node.id===reviewNodes(p).filter(n=>n.kind==='step').at(-1)?.id)return autoOpenDuelObservation();
    f.busy=true;
    try{const value=await autoDuelDispatch('plan-confirm',{id:f.id,route:p.forecastRoute,index:node.forecast_index,through:node.forecast_end});if(s!==autoDuelState()||s.forecast!==f||s.plan!==p)return;p.confirmed=reviewNodes(p).filter(n=>n.kind==='step'&&n.forecast_absolute_end<value.confirmed).length;}
    finally{f.busy=false;}
  }
  s.position=DuelModel.navigate(s.graph,s.position,'forward');renderAutoDuel();
}

async function autoSelectForecastNode(key) {
  const s=autoDuelState(),p=s.plan,target=s.graph.nodes.find(n=>n.key===key);if(!target||s.forecast?.busy)return;
  const next=DuelModel.navigate(s.graph,s.position,'forward');
  if(key!==s.position.key&&key===next.key)return autoAdvanceDuelForecast();
  const node=autoDuelNodeSource(target).node;
  if(node.kind==='final'&&p.confirmed<reviewNodes(p).filter(n=>n.kind==='step').length||node.kind==='step'&&node.number-2>p.confirmed)return autoDuelTell('请先逐步确认前面的步骤。');
  s.position={key,choice:0};paintAutoDuelPosition();
}

async function autoOpenDuelObservation() {
  const s=autoDuelState(),f=s.forecast,p=s.plan;if(!p?.temporary||!f||f.busy)return;
  const node=autoDuelNodeSource(s.graph.nodes.find(n=>n.key===s.position.key)).node;
  if(node.kind!=='step'||node.forecast_index<0)return autoDuelTell('请选择当前临时路线中需要报告实际情况的步骤。');
  let selected=[],searchRevision=0,timer;
  autoDuelObservationDialog.innerHTML=`<h2>报告 Step ${node.number} 的实际情况</h2><p>${escape(forecastStepText(node.forecast_step,p.catalog))}</p><label>发生了什么 <select id="auto-duel-observation-kind"><option value="draw">随机获得手牌</option><option value="mill">随机堆墓</option><option value="interruption">受到阻抗</option></select></label><p>填写本步骤实际出现的全部卡牌，可重复选择。阻抗填写发动的卡片及实际支付的手牌费用。</p><input id="auto-duel-observation-query" type="search" placeholder="搜索卡名或卡号" aria-label="搜索实际卡牌"><div id="auto-duel-observation-results" class="forecast-card-search"></div><div id="auto-duel-observation-selected" class="forecast-card-search"></div><p id="auto-duel-observation-error" role="status"></p><div class="auto-duel-actions"><button id="auto-duel-observation-cancel">取消</button><button id="auto-duel-observation-submit">确认实际结果并重算后续</button></div>`;
  const paint=()=>{$('#auto-duel-observation-selected').innerHTML=selected.map((c,i)=>`<button data-remove-observation="${i}"><img src="/pics/${c.code}.jpg" alt="">${escape(c.name)} ×</button>`).join('');for(const b of autoDuelObservationDialog.querySelectorAll('[data-remove-observation]'))b.onclick=()=>{selected.splice(Number(b.dataset.removeObservation),1);paint();};};
  $('#auto-duel-observation-query').oninput=()=>{clearTimeout(timer);const revision=++searchRevision,q=$('#auto-duel-observation-query').value.trim();timer=setTimeout(run(async()=>{if(!q)return;const data=await api('/api/cards?q='+encodeURIComponent(q));data.cards=data.cards.map(c=>({...c,code:c.id}));if(revision!==searchRevision||!autoDuelObservationDialog.open)return;$('#auto-duel-observation-results').innerHTML=data.cards.slice(0,16).map(c=>`<button data-observation-code="${c.code}"><img src="/pics/${c.code}.jpg" alt="">${escape(c.name)}</button>`).join('');for(const b of autoDuelObservationDialog.querySelectorAll('[data-observation-code]'))b.onclick=()=>{selected.push(data.cards.find(c=>c.code===Number(b.dataset.observationCode)));paint();};}),180);};
  $('#auto-duel-observation-cancel').onclick=()=>autoDuelObservationDialog.close();
  $('#auto-duel-observation-submit').onclick=async()=>{
    if(!selected.length){$('#auto-duel-observation-error').textContent='请选择实际卡牌。';return;}
    f.busy=true;for(const control of autoDuelObservationDialog.querySelectorAll('button,input,select'))control.disabled=true;
    $('#auto-duel-observation-error').textContent='正在根据实际结果重新计算…';
    try{
      const kind=$('#auto-duel-observation-kind').value;
      const data=await autoDuelDispatch('plan-observe',{id:f.id,route:p.forecastRoute,index:node.forecast_index,through:node.forecast_end,kind,cards:selected.map(c=>c.code)});
      if(s!==autoDuelState()||s.forecast!==f)return;
      f.data=data;f.busy=false;autoDuelObservationDialog.close();
      if(data.result.candidates.length)await autoAdoptDuelForecast(data.result.candidates[0].id);
      else {
        s.plan=temporaryDuelPlan(data,{steps:[],terminal:data.prefix.at(-1)?.state||data.initial});s.plan.stale=true;
        s.routes=duelPlanRoutes(s.plan);s.graph=DuelModel.graph(s.routes);s.position={key:'main/final',choice:0};
        f.showResults=true;renderAutoDuel();autoDuelTell('已记录实际结果，当前来源未找到可用后续。请调整来源后重新生成。');
      }
    }catch(error){$('#auto-duel-observation-error').textContent=error.message;}
    finally{f.busy=false;for(const control of autoDuelObservationDialog.querySelectorAll('button,input,select'))control.disabled=false;}
  };
  autoDuelObservationDialog.showModal();await syncAutoDuelShortcuts();
}
const autoDuelObservationDialog=document.createElement('dialog');autoDuelObservationDialog.id='auto-duel-observation';autoDuelObservationDialog.className='duel-shortcut-dialog';document.body.append(autoDuelObservationDialog);
autoDuelObservationDialog.addEventListener('close',()=>void syncAutoDuelShortcuts());
autoDuelObservationDialog.addEventListener('cancel',event=>{if(autoDuelState()?.forecast?.busy)event.preventDefault();});
