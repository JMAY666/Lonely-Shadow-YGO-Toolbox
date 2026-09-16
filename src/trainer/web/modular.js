'use strict';
const modularUI={sources:[],selected:new Set(),deck:null,status:null,busy:false,timer:null,stageHome:null,lastRender:''};
const modularEscape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function modularDispatch(consumer,intent,body={}){
  const response=await api('/api/modular/dispatch',{...body,consumer,intent});
  return response.result;
}
function mountModularField(container){
  const stage=$('#native-stage');
  if(!modularUI.stageHome)modularUI.stageHome={parent:stage.parentNode,next:stage.nextSibling};
  container.append(stage);
}
function restoreModularField(){
  const home=modularUI.stageHome;if(home)home.parent.insertBefore($('#native-stage'),home.next);
  modularUI.stageHome=null;
}
function modularFieldVisible(){return !!app.active&&app.view==='duel'&&!!$('#duel-brain-field')?.contains($('#native-stage'));}
async function enterModular(){
  mountModularField($('#modular-field'));
  const data=await api('/api/modular/data');
  $('#modular-data').innerHTML=data.providers.map(p=>`<article><strong>${modularEscape(p.owner)}</strong><p>${p.records} 项原始数据 · 版本 ${p.version.slice(0,8)}</p></article>`).join('')+'<article><strong>决斗调度</strong><p>按本局输入请求路线与决策；后续功能通过数据提供方与调用方接口接入。</p></article>';
  await refreshModularLibrary();
  const decks=await api('/api/decks');
  $('#modular-deck').innerHTML='<option value="">选择已有卡组</option>'+decks.map(d=>`<option value="${modularEscape(d.id)}">${modularEscape(d.name)}</option>`).join('');
  if(app.active){const status=await api('/api/modular/state/'+app.active.id);if(status.selected.length)modularUI.selected=new Set(status.selected);$('#modular-preference').value=status.preference;$('#modular-precise').checked=!!status.precise;$('#modular-goal').value=status.goal.join(' ');await refreshModularLibrary();}
  await refreshModular();clearInterval(modularUI.timer);modularUI.timer=setInterval(()=>void refreshModular().catch(e=>notice(e.message)),1000);
}
function leaveModular(){
  clearInterval(modularUI.timer);
  restoreModularField();
}
async function refreshModularLibrary(){
  const library=await api('/api/modular/library');modularUI.sources=library.sources;
  modularUI.selected=new Set([...modularUI.selected].filter(id=>library.sources.some(source=>source.id===id)));
  $('#modular-sources').innerHTML=library.sources.map(s=>`<label><input type="checkbox" data-modular-source="${modularEscape(s.id)}" ${modularUI.selected.has(s.id)?'checked':''}> ${modularEscape(s.name)}<small>${s.snapshots} 个快照 · ${s.connections} 个连接 · ${modularEscape(({ready:'可参与引擎校验',incomplete:'资料待补充',failed:'更新失败'})[s.status])}${s.unknown.length?' · '+modularEscape(s.unknown[0].reason):''}</small></label>`).join('')||'<p>请先在「展开」中记录并保存方案。旧方案缺少效果标识时会显示补录原因。</p>';
  $('#modular-sources').querySelectorAll('input').forEach(input=>input.onchange=run(async()=>{if(input.checked)modularUI.selected.add(input.dataset.modularSource);else modularUI.selected.delete(input.dataset.modularSource);await modularPreferencesChanged();}));
  $('#modular-sources').querySelectorAll('label').forEach((label,index)=>{
    const details=document.createElement('details');details.innerHTML='<summary>查看来源快照与连接</summary><div>正在读取…</div>';label.after(details);
    details.ontoggle=async()=>{
      if(!details.open||details.dataset.loaded)return;
      try{
        const source=await api('/api/modular/source/'+encodeURIComponent(library.sources[index].id));
        if(!details.isConnected)return;details.dataset.loaded='true';
        details.querySelector('div').innerHTML=`<p>来源版本 ${source.version.slice(0,12)} · 快照为记录时状态；能否在当前对局连接需再次经过引擎校验。</p>`+source.routes.map(route=>`<h4>${modularEscape(route.name)}</h4><ol>${route.snapshots.filter(n=>n.player===0).map(n=>{
          const edge=route.edges.find(e=>e.from===n.id),selected=edge?.decision.selection?.[0],c=selected?.card,effect=selected?.effect;
          return `<li><details><summary>快照 ${modularEscape(n.id)} · ${edge?modularEscape(selected?.kind||'选择'):'记录终点／待补充'}${c?' · 卡号 '+c.code:''}${effect?' · 效果说明 '+effect.description:''}</summary><p>回合 ${n.state.turn} · 阶段 ${n.state.phase} · 连锁 ${n.state.chain_depth} · LP ${n.state.lp?.join(' / ')}${edge?' · 后继快照 '+edge.to:''}</p><p>${n.state.cards.filter(c=>c.controller===0&&[2,4,8,16,32,128].includes(c.location)).map(c=>modularEscape(c.name||c.code)+' #'+c.instance_id+'（区域 '+c.location+' / 位置 '+c.sequence+'）').join('、')}</p><p>效果次数、代价、素材与持续限制由本局重放引擎校验；缺失信息不视为满足。</p></details></li>`;
        }).join('')}</ol>`).join('');
      }catch(error){details.querySelector('div').textContent=error.message;}
    };
  });
}
async function configureModular(){
  if(!app.active)throw new Error('请先确定起手并开始本次对局');
  const goal=$('#modular-goal').value.trim().split(/[\s,，]+/).filter(Boolean).map(Number);
  return api('/api/modular/configure',{id:app.active.id,sources:[...modularUI.selected],preference:$('#modular-preference').value,precise:$('#modular-precise').checked,goal});
}
async function modularPreferencesChanged(){
  if(!app.active)return;
  await configureModular(); // Immediately revoke stale candidates, even during a search.
  if(modularUI.busy){modularUI.queued=true;return;}
  await searchModular(false);
}
async function searchModular(configure=true){
  if(modularUI.busy){modularUI.queued=true;return;}modularUI.busy=true;
  $('#modular-status').textContent='正在从当前局面校验来源动作并搜索路线…';
  try{if(configure)await configureModular();await api('/api/modular/search',{id:app.active.id});await refreshModular(true);}finally{modularUI.busy=false;if(modularUI.queued){modularUI.queued=false;void searchModular(false).catch(e=>notice(e.message));}}
}
function modularStep(step){
  const decision=step.bound_decision||step.decision,selection=decision.selection?.[0],effect=selection?.effect;
  const card=step.state.cards.find(c=>c.code===selection?.card?.code);
  const kind=step.operation_label||{summon:'通常召唤',special:'特殊召唤',activate:'发动',yes:'发动／确认',no:'不发动',card:'选择卡牌',material:'选择素材',place:'选择区域',option:'选择效果选项',finish_selection:'完成选择',spell_set:'盖放',pass:'放弃响应'}[selection?.kind]||selection?.kind||'选择';
  const label=step.effect_label;
  const place=selection?.place?reviewPlace({controller:selection.place[0],location:selection.place[1],sequence:selection.place[2]}):'';
  return `${step.if_condition?'IF '+step.if_condition.label+' → ':''}${step.automatic?'规则自动应答':label?.source==='pendulum_card_activation'?'发动灵摆卡':kind} ${card?.name||selection?.card?.code||place||''}${effect&&label?.source!=='pendulum_card_activation'?' · '+(label?.number?'效果 '+label.number+'：'+label.text:'效果说明 '+effect.description+'，卡面编号待核对')+' / 脚本处理行 '+(effect.operation_line??'待确认'):''}${step.bound_decision&&JSON.stringify(step.bound_decision)!==JSON.stringify(step.decision)?'（实际区域已适配并通过引擎）':''}`;
}
function modularRoutesHtml(value){
  const result=value.result;
  return (result?.candidates||[]).map((c,i)=>`<article class="modular-route"><h3>路线 ${i+1} · ${c.remaining} 次剩余决策</h3>${c.terminal_source?`<p>终场来源：${modularEscape(c.terminal_source.route_name)}${c.terminal_if?` · IF ${modularEscape(c.terminal_if.label)}`:''}</p>`:''}<span class="modular-badge">${c.validation==='next_step_rechecked'?'本步复核通过':c.conditional?'含条件／随机结果':'完整引擎校验'}</span><span class="modular-badge">${c.goal_met?'符合当前目标':'替代终场'}</span>${c.original_goal_met===false?'<span class="modular-badge">与原目标不同</span>':''}<p>场上 ${c.evaluation.board} · 手牌 ${c.evaluation.hand} · 额外 ${c.evaluation.extra} · LP ${c.evaluation.lp}</p><p>${modularEscape(c.evaluation.basis)}</p><p>稳妥性：${c.robustness.status==='evaluated'?c.robustness.scenarios.map(s=>modularEscape(s.name)+(s.continued?'：可继续':'：未找到后续')).join('；'):'未评估，不视为低风险'}</p><div class="modular-cards">${c.terminal.cards.filter(card=>card.controller===0&&[4,8].includes(card.location)).map(card=>`<img src="/pics/${card.code}.jpg" alt="${modularEscape(card.name)}" title="${modularEscape(card.name)}">`).join('')}</div><details><summary>来源、具体效果与后续决策</summary><ol>${c.steps.map((s,j)=>`<li>${j===0?'当前：':'后续：'}${modularEscape(modularStep(s))}<small> · ${modularEscape(s.source.name)} / ${modularEscape(s.source.route_name)} · 快照 ${modularEscape(s.source.snapshot)} · 版本 ${s.source.version.slice(0,8)}</small></li>`).join('')}</ol></details><button data-modular-execute="${c.id}" ${value.pending||value.busy?'disabled':''}>采用路线并执行下一步</button></article>`).join('')||'<p>选择来源并查找路线。没有候选时可继续在场地中手动操作，再按实际结果重算。</p>';
}
function renderModular(value){
  const result=value.result,state=value.state;
  $('#modular-auto').textContent=value.auto?'停止自动执行':'启用内置 YGO AI';
  $('#modular-auto').setAttribute('aria-pressed',String(value.auto));
  $('#modular-matching').textContent=value.precise?'精确匹配：核对已记录的可见局面与区域细节；所有动作仍须通过引擎。':'自适应匹配：可调整无关区域细节；效果、代价、素材、次数、连接与召唤限制仍由引擎逐步校验。';
  $('#modular-status').textContent=`${value.auto?'自动模式':'手动模式'} · ${value.reason}\n当前路线已确认 ${value.actual_count??0} 次决策 · 本局累计 AI 确认输入 ${value.completed.length} 次${value.pending?' · 当前操作等待引擎确认':''}${result?'\n'+({found:`找到 ${result.candidates.length} 条候选`,limited:'搜索达到限制',incomplete:'条件信息不足',no_route:'当前模块库未找到路线'})[result.status]+` · 校验 ${result.nodes} 次 · ${result.seconds} 秒${result.limited?' · 搜索未穷尽':''}`:''}`;
  if(value.original_goal!==null&&value.original_goal!==undefined)$('#modular-status').textContent+='\n原目标记录：'+(value.original_goal.map(row=>Array.isArray(row)?`${duelName(row[0])}（区域 ${row[1]} / 位置 ${row[2]}）`:duelName(row)).join('、')||'空场')+'；当前目标：'+(value.goal.map(duelName).join('、')||'按当前偏好选择可达终场');
  if(result&&Object.keys(result.rejected).length)$('#modular-status').textContent+='\n未衔接原因：'+Object.keys(result.rejected).slice(0,4).join('；');
  $('#modular-snapshot').textContent=state?`回合 ${state.state.turn} · 阶段 ${state.state.phase} · 连锁 ${state.state.chain_depth} · 决策版本 ${state.version} · 已用通常召唤 ${state.state.normal_summons_used?.[0]??'由引擎检查'} · 效果次数与持续限制在重放引擎中校验`:'等待当前局面';
  $('#modular-current-cards').innerHTML=(state?.state.cards||[]).filter(c=>c.controller===0&&[2,4,8,16,32].includes(c.location)).map(c=>`<img src="/pics/${c.code}.jpg" alt="${modularEscape(c.name)}" title="${modularEscape(c.name)} · 区域 ${c.location} · 实例 ${c.instance_id}">`).join('');
  $('#modular-routes').innerHTML=modularRoutesHtml(value);
  $('#modular-routes').querySelectorAll('[data-modular-execute]').forEach(button=>button.onclick=run(async()=>{await api('/api/modular/execute',{id:app.active.id,candidate:button.dataset.modularExecute});await refreshModular(true);}));
  $('#modular-actual').innerHTML=(value.actual_steps||[]).map(step=>`<li>${modularEscape(modularStep(step))}<small> · 快照 ${modularEscape(step.node)} → ${modularEscape(step.next_module)}${step.state.chain_depth?' · 连锁尚在处理':''}</small></li>`).join('');
  $('#modular-audit').textContent=value.audit.slice(-12).map(a=>`${new Date(a.time_ms).toLocaleTimeString()} · ${{preference_changed:'偏好已调整',sources_updating:'来源更新，旧候选作废',mode_changed:'自动模式调整',decision_confirmed:'输入由引擎确认',terminal_reached:'实际终场已到达',ai_paused:'AI 暂停',search_completed:'路线校验完成',decision_submitted:'输入已提交，等待确认',route_adopted:'采用路线'}[a.kind]||a.kind}${a.preference?' · '+a.preference:''}${a.source?' · '+a.source.name:''}`).join('\n');
}
async function refreshModular(force=false){
  if(moduleUI.current!=='modular')return;
  $('#modular-start').disabled=!!app.active;$('#modular-finish').disabled=!app.active;
  for(const id of ['modular-search','modular-auto'])$('#'+id).disabled=!app.active;
  if(!app.active){
    $('#modular-status').textContent='当前没有进行中的引擎对局。可在展开或决斗中确定起手并调用模块化。';
    $('#modular-snapshot').textContent=modularUI.status?.state?'上次查看的局面；原始记录保留在展开回看中。':'等待当前局面';
    $('#modular-routes').querySelectorAll('[data-modular-execute]').forEach(button=>button.disabled=true);
    return;
  }
  const value=await api('/api/modular/state/'+app.active.id);modularUI.status=value;
  const key=JSON.stringify([value.state?.version,value.auto,value.precise,value.preference,value.pending?.lease,value.result?.token,value.completed.length,value.busy,value.reason]);
  if(force||key!==modularUI.lastRender){modularUI.lastRender=key;renderModular(value);}
  await syncNativeHost();
}
$('#modular-refresh').onclick=run(refreshModularLibrary);
$('#modular-deck').onchange=run(async()=>{modularUI.deck=$('#modular-deck').value?await api('/api/deck?id='+encodeURIComponent($('#modular-deck').value)):null;});
$('#modular-start').onclick=run(async()=>{
  const d=modularUI.deck;if(!d)throw new Error('请选择起手使用的卡组');
  const hand=$('#modular-hand').value.trim().split(/[\s,，]+/).filter(Boolean).map(Number);
  if(!hand.length)throw new Error('请输入实际起手的卡牌编号，以空格分隔；数量和副本将由卡组校验');
  // Use the existing preparation/start/recording flow, including its host layout.
  await switchModule('expansion');displayView('training');await syncNativeHost();
  const session=await api('/api/start',{deck_id:d.id,design:{name:'模块化展开',notes:'',revision:d.revision,conditions:{hand_count:hand.length,slots:hand,banned:[]},opponent_ai:false,turn_order:'first'}});
  await refreshHistory();await switchModule('modular');
  for(let i=0;i<80;i++){try{const s=await api('/api/modular/state/'+session.id);if(s.state?.raw)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  await configureModular();await refreshModular(true);
});
$('#modular-search').onclick=run(searchModular);
$('#modular-preference').onchange=run(modularPreferencesChanged);
$('#modular-precise').onchange=run(modularPreferencesChanged);
$('#modular-goal').onchange=run(modularPreferencesChanged);
$('#modular-auto').onclick=run(async()=>{if(!modularUI.status?.auto)await configureModular();await api('/api/modular/auto',{id:app.active.id,enabled:!modularUI.status?.auto});await refreshModular(true);});
$('#modular-finish').onclick=run(async()=>{if(app.active){await api('/api/modular/auto',{id:app.active.id,enabled:false});await api('/api/stop',{id:app.active.id});await switchModule('expansion');await refreshHistory();}});
$('#training-modular').onclick=run(async()=>{if(!app.active)return notice('请先开始展开。');await switchModule('modular');notice('已接入同一真实对局。选择来源并查找路线；启用 AI 前保持手动模式。');});
const expansionModularStop=document.createElement('button');expansionModularStop.id='training-modular-stop';expansionModularStop.textContent='停止模块化 AI';expansionModularStop.hidden=true;
$('#training-modular').after(expansionModularStop);
expansionModularStop.onclick=run(async()=>{if(app.active)await api('/api/modular/auto',{id:app.active.id,enabled:false});expansionModularStop.hidden=true;notice('已停止自动执行，当前对局可继续手动操作。');});
setInterval(async()=>{
  if(moduleUI.current!=='expansion'||!app.active){expansionModularStop.hidden=true;return;}
  const id=app.active.id;
  try{const value=await api('/api/modular/state/'+id);if(app.active?.id===id)expansionModularStop.hidden=!value.auto;}catch{}
},1200);
async function launchModularFromDuel(){
  const s=duelState(),input=duelInputKey(s);
  if(!s.deck||s.hand.some(c=>!c))throw new Error('请先确认卡组并填写完整起手');
  if(app.active){
    if(s.modularSession!==app.active.id||s.modularInput!==input)throw new Error('已有另一场展开正在进行。请先结束该场，或从“展开”的“模块化续展”继续当前真实局面。');
    renderDuel();await refreshDuelModular();$('#duel-modular-status')?.scrollIntoView({block:'start'});return;
  }
  const deck=await api('/api/deck?id='+encodeURIComponent(s.deck.id));
  if(deck.revision!==s.deck.revision)throw new Error('卡组已修改，请返回决斗卡组选择确认');
  const sources=(await api('/api/modular/library')).sources.filter(source=>source.status==='ready').map(source=>source.id);
  await switchModule('expansion');displayView('training');await syncNativeHost();
  const session=await api('/api/start',{deck_id:deck.id,design:{name:'决斗 · 模块化验证',notes:'从决斗已录入起手进入真实引擎；原手动教程进度保留',revision:deck.revision,conditions:{hand_count:s.hand.length,slots:[...s.hand],banned:[]},opponent_ai:false,turn_order:'first'}});
  s.modularSession=session.id;s.modularInput=input;app.reportId=session.id;
  await refreshHistory();
  await modularDispatch('duel','configure',{id:session.id,sources,preference:'shortest',goal:[]});
  await switchModule('duel');renderDuel();await refreshDuelModular();$('#duel-modular-status')?.scrollIntoView({block:'start'});
  await syncNativeHost();await waitNativeFrame(session.id);
  notice('本次起手已交给模块化处理。可在决斗窗口查找路线和执行；手动教程进度仍保留。');
}
window.addEventListener('scroll',()=>{if(moduleUI.current==='modular'||modularFieldVisible())void syncNativeHost().catch(()=>{});},{passive:true});
