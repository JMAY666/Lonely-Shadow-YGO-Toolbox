'use strict';

// Every request is bound to both an input fingerprint and a view generation.
const OpeningView=(()=>{
  const create=()=>({serial:0,result:null,error:'',busy:false,supplemental:[],inputKey:null});
  const invalidate=s=>{++s.serial;s.result=null;s.error='';s.busy=false;};
  const accepts=(s,serial,key,current)=>s.serial===serial&&key===current;
  return {create,invalidate,accepts};
})();
if(typeof module!=='undefined')module.exports=OpeningView;
const openingIntel=OpeningView.create();
let openingIntelDeck=null;
const openingDuelState=()=>duelState().secondOpening||(duelState().secondOpening=OpeningView.create());
const openingIsSecond=()=>duelState().operationMode==='automatic'?duelState().automatic.order?.frame?.confirmed?.order==='second':!duelState().first;
function openingInput(scope){
  if(scope==='intel')return openingIntelDeck?{deck_id:openingIntelDeck.id,revision:openingIntelDeck.revision,hand:[]}:null;
  const s=duelState(),v=openingDuelState();
  if(s.operationMode==='manual')return s.deck?{deck_id:s.deck.id,revision:s.deck.revision,hand:s.hand,supplemental:v.supplemental}:null;
  const frame=s.automatic.order?.frame;
  if(!DuelOpening.ready(frame))return null;
  return {source:'automatic',monitor_id:frame.monitor_id,recognition_id:s.automatic.smartRun?.id,
    round_id:frame.round_id,snapshot_id:frame.opening.snapshot_id,deck_context:automaticDeckContext(),supplemental:v.supplemental};
}
function openingKey(scope){
  const s=duelState();
  return JSON.stringify([openingInput(scope),scope==='intel'?intelUI.tab:[s.session,s.stage,s.operationMode,openingIsSecond(),s.automatic.smartRun?.cycle,s.automatic.smartRun?.value?.reading_error],moduleUI.current]);
}
function clearSecondOpening(){
  if(!duelState().secondOpening)return;
  OpeningView.invalidate(duelState().secondOpening);duelState().secondOpening.supplemental=[];
}
function openingPaint(scope){if(scope==='intel')openingIntelRender();else if(moduleUI.current==='duel')renderDuel();}
async function openingAnalyze(scope){
  const state=scope==='intel'?openingIntel:openingDuelState(),input=openingInput(scope);
  if(!input)return;
  const serial=++state.serial,key=openingKey(scope);state.result=null;state.error='';state.busy=true;openingPaint(scope);
  try{
    const result=await api('/api/opening/analyze',input);
    if(!OpeningView.accepts(state,serial,key,openingKey(scope)))return;
    state.result=result;state.inputKey=key;
  }catch(error){if(OpeningView.accepts(state,serial,key,openingKey(scope)))state.error=error.message;}
  finally{if(state.serial===serial){state.busy=false;openingPaint(scope);}}
}
const openingName=code=>app.cache.get(Number(code))?.name||`卡号 ${code}`;
function openingCard(code){
  const report={id:'opening-catalog',catalog:Object.fromEntries(app.cache),events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  return `<div class="opening-card">${reviewCard({code,name:openingName(code),identity_known:true},'catalog',{report,face:true,zone:false,position:false,catalogue:true})}<span>${escape(openingName(code))}</span></div>`;
}
function openingResult(result,editable=false){
  const {concentration:c,analysis:a}=result,roleNames=result.role_names;
  const resource=role=>result.cards.filter(card=>card.roles.includes(role)).map(card=>`${card.name} ×${card.count}`).join('、');
  const routes=a.routes.map(route=>`<details class="opening-route"><summary>${escape(route.sources[0].name)} · ${route.condition.status==='satisfied'?'资源条件满足':route.condition.status==='unmet'?'资源不足':'待核对'} · ${route.one_card?'一卡起手依据':`需要 ${route.required_hand} 张起手资源`}</summary>
    <p>${escape(route.condition.reason)}</p><p>${escape(route.idea||'基本思路按下列录制步骤整理')}</p><p>入口：${route.opening.map(r=>`${escape(openingName(r.code))} ×${r.count}`).join(' + ')}${route.generic_cost?` + 任意手牌费用 ×${route.generic_cost}`:''}；来源为${route.turn_order==='second'?'后攻':'先攻'}录制。</p>
    <ol>${route.steps.map(step=>`<li>${escape(step)}</li>`).join('')||'<li>尚无可读步骤</li>'}</ol>
    <h4>终场来源效果 · ${route.endboard_count} 项</h4><ul>${route.endboard.map(e=>`<li>${escape(e.name)} · 效果 ${escape(e.effect)} · ${e.copies.length} 个来源副本 · ${e.status}<br>${escape(e.note)}</li>`).join('')||'<li>尚无终场效果标记；不视为零能力</li>'}</ul>
    <p>对本路线未见参与依据：${route.relative_unused.map(c=>escape(openingName(c))).join('、')||'无'}。仅为相对评价，通用用途保留；${route.generic_cost?'仍有通用费用需求，以上卡片可能用于费用。':'没有资料不等于无用。'}</p>
    <p class="opening-meta">${route.sources.map(s=>`${escape(s.name)} · ${escape(s.plan_id)}${s.branch_id?' / '+escape(s.branch_id):''} · ${s.revision.slice(0,10)}`).join('<br>')}</p>
    ${openingNote(route.key,result,editable)}</details>`).join('');
  return `<div class="opening-results"><p class="opening-boundary">${escape(result.boundary)}</p>
    <section><h3>构筑 · ${c.status}</h3><p>${c.total} 份主卡与额外，未归类 ${c.unclassified} 份。现有个人 TAG 保留。</p><div class="opening-series">${c.groups.map(g=>`<article><strong>${escape(g.name)} ${c.primary.includes(g.id)?'· 主系列':'· 小轴／系列候选'}</strong><p>${(g.ratio*100).toFixed(1)}% · 独占 ${g.exclusive} + 共享折算 ${g.shared.toFixed(1)}</p><small>主卡 ${g.main} / 额外 ${g.extra} · ${g.hierarchy.map(escape).join(' / ')}</small></article>`).join('')||'<p>没有可用系列依据</p>'}</div></section>
    <section><h3>1. 手坑 · ${result.handtrap_count} 张</h3><p>${escape(resource('handtrap')||'已知手牌中没有已核对用途的手坑')}。同名次数、时点与当前条件仍需核对。</p></section>
    <section><h3>2. 自身影响与冲突</h3>${result.warnings.map(w=>`<p>${escape(w.text)}</p>`).join('')||'<p>未发现已覆盖的特定组合提示；不代表没有冲突。</p>'}</section>
    <section class="opening-columns"><div><h3>3. 护航</h3><p>${escape(resource('protection')||'尚无已核对护航资料')}</p></div><div><h3>4. 解场</h3><p>${escape(resource('breaker')||'尚无已核对解场资料')}</p></div></section>
    <section><h3>5. 基本展开与补点候选</h3><p>展示 ${a.routes.length} / ${a.groups} 组独立方案${a.omitted?`，另 ${a.omitted} 组未展示`:''}。原始起手 ${result.frozen.length} 张，人工补充 ${result.supplemental.length} 张；多用途卡片不重复计入 ${result.hand_count} 张资源。</p>${routes||'<p>尚无适合本构筑的正式方案依据。</p>'}
    ${a.comparisons.length?`<details><summary>比较来源终场效果</summary>${a.comparisons.map(row=>`<p>${escape(a.routes.find(r=>r.key===row.a).sources[0].name)} → ${escape(a.routes.find(r=>r.key===row.b).sources[0].name)}：${row.relation}（差 ${row.difference} 项）<br>${row.note}</p>`).join('')}</details>`:''}</section>
    <section><h3>6. 取胜方向</h3><p>${escape(result.direction)}</p></section>
    <section><h3>7. 相对废件与缺资料</h3><p>相对无贡献卡片及卡组组件上手问题见各方案；不自动弃牌或调整构筑。</p><p>用途待补充：${result.cards.filter(c=>!c.roles.length).map(c=>`${escape(c.name)} ×${c.count}`).join('、')||'无'}</p>${a.coverage_gaps.map(t=>`<p>${escape(t)}</p>`).join('')}${a.errors.length?`<details><summary>未覆盖资料 · ${a.errors.length}</summary>${a.errors.map(t=>`<p>${escape(t)}</p>`).join('')}</details>`:''}</section>
    <section><h3>效果参与依据 · 局部推导只读</h3>${a.effects.map(e=>`<article class="opening-effect"><strong>${escape(openingName(e.code))} · ${escape(e.recommendation)} · ${e.coverage_count}/${e.sample_count} 组</strong><p>${escape(e.text)}</p><p>卡片参与覆盖 ${(100*e.card_coverage).toFixed(0)}%；发动 ${e.attempts} 次，处理完成 ${e.resolved} 次，有实际结果 ${e.applied} 次，被无效 ${e.negated} 次。</p><small>不足 3 组只给候选；持续效果无适用记录时不猜测参与。费用／素材与效果发动分别计数。</small>${openingNote(e.key,result,editable)}</article>`).join('')||'<p>尚无可确认的具体效果参与证据。</p>'}</section>
    <section><h3>已核对通用用途与条件</h3>${result.knowledge.map(e=>`<article class="opening-effect" data-opening-effect="${escape(e.key)}">${openingCard(e.code)}<div><strong>${escape(e.name)} · ${e.reviewed?'已核对':'卡文变化，待核对'}</strong><p>${escape(e.text)}</p><p>${escape(e.condition)}</p><p>${e.explanation.map(escape).join('<br>')}</p><p>用途：${e.roles.map(r=>roleNames[r]).join(' / ')||'未选择'} · ${e.priority==='primary'?'主要':'次要'}</p>
      ${e.override_stale?`<p role="status">旧人工覆盖已失效并保留待核对：${escape(JSON.stringify(e.override.value))}</p>`:''}
      ${editable&&e.reviewed?`<form data-opening-form="override" data-key="${escape(e.key)}"><fieldset><legend>个人展示选择（顺序决定展示顺序）</legend>${[...e.roles,...e.allowed_roles.filter(r=>!e.roles.includes(r))].map(r=>`<label><input type="checkbox" name="role" value="${r}" ${e.roles.includes(r)?'checked':''}>${roleNames[r]}</label>`).join('')}<label>用途顺序<select name="order"><option value="normal">按当前顺序</option><option value="reverse">反转所选顺序</option></select></label><label>展示优先<select name="priority"><option value="primary" ${e.priority==='primary'?'selected':''}>主要</option><option value="secondary" ${e.priority==='secondary'?'selected':''}>次要</option></select></label><label>备注<textarea name="note" maxlength="4000">${escape(e.note)}</textarea></label></fieldset><button type="submit">保存通用选择</button><button type="button" data-opening-command="restore" data-key="${escape(e.key)}">恢复自动</button><button type="button" data-opening-command="suggest" data-key="${escape(e.key)}">本地归纳候选</button></form>${e.candidate?`<p>机器候选（${e.candidate_stale?'已过期':'待采纳'}）：${e.candidate.value.roles.map(r=>roleNames[r]).join(' / ')}。保留人工修改。</p><button data-opening-command="apply" data-key="${escape(e.key)}" ${e.candidate_stale?'disabled':''}>采纳候选</button>`:''}`:`<p>${escape(e.note)}</p>`}
      <small><a href="${escape(e.source.url)}" data-opening-reference>官方效果依据</a> · 来源 ${escape(e.source.id)} · 核对日期 ${escape(e.source.checked_on)} · 版本 ${e.version.slice(0,10)}</small></div></article>`).join('')||'<p>本构筑暂无公开通用用途资料。</p>'}</section>
    ${editable?openingNote('deck',result,true):''}<p class="opening-meta">本地分析 · 来源版本 ${result.source_version.slice(0,12)} · 个人修订 ${result.revision}</p></div>`;
}
function openingNote(key,result,editable){
  const note=result.notes[key];
  return editable?`<form data-opening-form="note" data-key="${escape(key)}"><label>局部备注（只供阅读，不参与计算）<textarea name="note" maxlength="4000">${escape(note?.text||'')}</textarea></label>${note&&note.version!==result.source_version?'<p>备注来源版本已变化，请重新核对。</p>':''}<button type="submit">保存备注</button></form>`:note?`<p>个人备注：${escape(note.text)}</p>`:'';
}
function secondOpeningPage(){
  const s=duelState(),state=openingDuelState(),automatic=s.operationMode==='automatic',frame=s.automatic.order?.frame;
  const frozen=automatic?frame?.opening?.cards||[]:s.hand;
  const deck=automatic?s.automatic.deck?.deck:s.deck?.deck;
  const ready=automatic?DuelOpening.ready(frame):!DuelModel.handError(deck,s.count,s.hand);
  if(state.result&&state.inputKey!==openingKey('duel'))OpeningView.invalidate(state);
  return `<section class="opening-workspace" data-opening-scope="duel"><h2>后攻起手分析</h2>${automatic?`<div class="duel-opening-panel">${duelOpeningCards(frame)}<p>自动冻结起手；后续抽牌和消耗不会修改此快照。</p></div>`:'<p>请在上方录入本局起手，修改起手会清除旧分析。</p>'}
    <details><summary>人工补充资源 · ${state.supplemental.length} 张</summary><p>用于“额外已知手牌”的资源评估，不代表自动读取的当前手牌，也不自动扣除已使用的卡。</p><div class="opening-supplement">${state.supplemental.map((code,i)=>`<span>${escape(openingName(code))}<button data-opening-remove="${i}" aria-label="移除补充的${escape(openingName(code))}">×</button></span>`).join('')}</div><select aria-label="人工补充卡牌" data-opening-supplement>${[...new Set(deck?.main||[])].map(code=>`<option value="${code}">${escape(openingName(code))}</option>`).join('')}</select><button data-opening-add ${!ready?'disabled':''}>添加已知手牌</button></details>
    <button class="primary" data-opening-analyze ${!ready||state.busy?'disabled':''}>${state.busy?'正在本地分析…':'分析后攻起手'}</button><p role="alert" class="opening-error">${escape(state.error)}</p>${state.result?openingResult(state.result):'<p>对手场面未知；分析不会自动操作游戏。</p>'}</section>`;
}
async function openingIntelLoad(){
  OpeningView.invalidate(openingIntel);openingIntelDeck=null;openingIntelRender();
}
function openingIntelRender(){
  if(intelUI.tab!=='opening')return;
  $('[data-intel-count="opening"]').textContent='本地';
  $('#intel-actions').innerHTML='';$('#intel-controls').innerHTML='';$('#intel-list').innerHTML='';
  $('#intelligence .intel-layout').classList.add('opening-intel-layout');
  $('#intel-editor').innerHTML=`<section class="opening-workspace" data-opening-scope="intel"><h2>起手分析工作区</h2><p>从本地正式方案归纳基本思路与效果分工；只在本机处理。先选择构筑，再查看或维护通用展示选择。</p><label>构筑<select data-opening-deck><option value="">请选择构筑</option>${intelUI.decks.map(d=>`<option value="${escape(d.id)}" ${d.id===openingIntelDeck?.id?'selected':''}>${escape(d.name)}</option>`).join('')}</select></label><button data-opening-analyze ${!openingIntelDeck||openingIntel.busy?'disabled':''}>${openingIntel.busy?'正在归纳…':'重新归纳'}</button><p class="opening-error" role="alert">${escape(openingIntel.error)}</p>${openingIntel.result?`<form data-opening-form="settings"><fieldset><legend>分析参数</legend><label>双主相对比例<input type="number" name="dual_ratio" min="0.01" max="1" step="0.01" value="${openingIntel.result.settings.dual_ratio}"></label><label>第二系列最低浓度<input type="number" name="dual_minimum" min="0.01" max="1" step="0.01" value="${openingIntel.result.settings.dual_minimum}"></label><label>代表方案上限<input type="number" name="representatives" min="1" max="10" value="${openingIntel.result.settings.representatives}"></label></fieldset><button>保存参数</button></form>${openingResult(openingIntel.result,true)}`:''}</section>`;
}
async function openingSave(action,key,value){
  const result=openingIntel.result;if(!result||openingIntel.busy)return;
  const input=openingInput('intel'),effect=result.knowledge.find(e=>e.key===key),serial=++openingIntel.serial,identity=openingKey('intel');
  openingIntel.busy=true;intelUI.busy=true;
  const controls=[...document.querySelectorAll('[data-opening-scope="intel"] input,[data-opening-scope="intel"] select,[data-opening-scope="intel"] textarea,[data-opening-scope="intel"] button')].map(el=>[el,el.disabled]);
  for(const [el] of controls)el.disabled=true;
  try{
    await api('/api/opening/save',{action,key,value,input,revision:result.revision,source_version:result.source_version,version:effect?.version});
    if(!OpeningView.accepts(openingIntel,serial,identity,openingKey('intel')))return;
    intelUI.dirty=false;openingIntel.busy=false;await openingAnalyze('intel');
  }catch(error){if(OpeningView.accepts(openingIntel,serial,identity,openingKey('intel'))){openingIntel.error=error.message;const el=$('[data-opening-scope="intel"] .opening-error');if(el)el.textContent='保存失败：'+error.message+'；输入已保留。';}}
  finally{intelUI.busy=false;for(const [el,disabled] of controls)if(el.isConnected)el.disabled=disabled;if(openingIntel.serial===serial)openingIntel.busy=false;}
}
if(typeof document!=='undefined'){
  document.addEventListener('click',run(async event=>{
    const link=event.target.closest('[data-opening-reference]');if(link&&window.trainerDesktop?.openReferenceLink){event.preventDefault();await window.trainerDesktop.openReferenceLink(link.href);return;}
    const button=event.target.closest('button'),host=button?.closest('[data-opening-scope]');if(!host||button.disabled)return;
    const scope=host.dataset.openingScope,state=scope==='intel'?openingIntel:openingDuelState();
    if(button.hasAttribute('data-opening-analyze')){if(scope==='intel'&&!await intelDiscard())return;intelUI.dirty=false;await openingAnalyze(scope);return;}
    if(button.hasAttribute('data-opening-add')){
      const code=Number(host.querySelector('[data-opening-supplement]').value),input=openingInput(scope),s=duelState(),deck=s.operationMode==='automatic'?s.automatic.deck.deck:s.deck.deck;
      const hand=[...(input.hand||s.automatic.order.frame.opening.cards),...state.supplemental,code];
      if((DuelModel.counts(hand).get(code)||0)>(DuelModel.counts(deck.main).get(code)||0)){state.error='补充后数量超过构筑实际副本数';openingPaint(scope);return;}
      state.supplemental.push(code);OpeningView.invalidate(state);openingPaint(scope);return;
    }
    if(button.hasAttribute('data-opening-remove')){state.supplemental.splice(Number(button.dataset.openingRemove),1);OpeningView.invalidate(state);openingPaint(scope);return;}
    if(button.dataset.openingCommand)await openingSave(button.dataset.openingCommand,button.dataset.key);
  }));
  document.addEventListener('change',run(async event=>{
    if(event.target.matches('[data-opening-deck]')){
      const id=event.target.value;if(!await intelDiscard()){event.target.value=openingIntelDeck?.id||'';return;}
      intelUI.dirty=false;const serial=++openingIntel.serial;openingIntel.result=null;openingIntelDeck=null;
      if(!id){openingIntelRender();return;}
      try{const saved=await api('/api/deck?id='+encodeURIComponent(id));if(openingIntel.serial!==serial||intelUI.tab!=='opening')return;openingIntelDeck=saved;await Promise.all([...new Set([...saved.deck.main,...saved.deck.extra])].map(c=>card(c)));await openingAnalyze('intel');}
      catch(error){openingIntel.error=error.message;openingIntelRender();}
    }
  }));
  document.addEventListener('input',event=>{if(event.target.closest('[data-opening-form]'))intelUI.dirty=true;});
  document.addEventListener('submit',run(async event=>{
    const form=event.target.closest('[data-opening-form]');if(!form)return;event.preventDefault();
    const data=new FormData(form),action=form.dataset.openingForm;
    let value=action==='note'?data.get('note'):action==='settings'?Object.fromEntries(['dual_ratio','dual_minimum','representatives'].map(k=>[k,Number(data.get(k))])):{roles:data.getAll('role'),priority:data.get('priority'),note:data.get('note')};
    if(action==='override'&&data.get('order')==='reverse')value.roles.reverse();
    await openingSave(action,form.dataset.key,value);
  }));
}
