'use strict';

const flow = {design:null, draft:null, selectedPlan:null, slot:0, target:'player', mode:'required', busy:false, saving:false, restarting:false, deckEdit:null, timer:null};
const stageNames = {recording:'正在记录 · 未保存方案', draft:'待确认草稿', saved:'已保存方案', discarded:'已放弃尝试', abandoned:'原始记录 · 草稿已放弃', deleted:'原始记录 · 正式方案已删除'};
const maxValue = 2147483647;
const cardName = (d, code) => d.catalog?.[code]?.name || flow.design?.catalog?.[code]?.name || String(code);
const handCount = d => d.conditions.hand_count === undefined ? 5 : d.conditions.hand_count;
const inputInteger = e => e.target.value.trim() === '' ? null : Number(e.target.value);
const inRange = (n,min,max) => Number.isInteger(n) && n >= min && n <= max;

function unsavedSummary() {
  const messages = [];
  if (app.dirty) messages.push('构筑有未保存修改。');
  if (flow.design) messages.push('前置设计尚未开始，退出后需要重新填写。');
  if (app.active) messages.push('展开尚未结束，退出将保留中断记录，尚未保存为正式方案。');
  if (flow.draft && draftDirty()) messages.push('当前方案的名称、步骤或卡牌说明尚未保存。');
  else if (flow.draft && !flow.draft.saved) messages.push('待确认草稿已保留在本地，但尚未保存为正式方案。');
  return messages.join('\n');
}
function draftDirty() { return flow.draft && (flow.draft.name !== flow.draft.originalName || flow.draft.notes !== flow.draft.originalNotes || (flow.draft.annotations && JSON.stringify(flow.draft.annotations) !== flow.draft.originalAnnotations)); }

async function confirmFlow(title, warning, action) {
  const dialog = $('#flow-dialog'), form = dialog.querySelector('form');
  $('#flow-message').textContent = title; $('#flow-warning').textContent = warning; $('#flow-confirm').textContent = action;
  flow.confirming = true;
  await syncNativeHost();
  return new Promise(resolve => {
    const done = value => {
      form.removeEventListener('submit', submit); dialog.removeEventListener('cancel', cancel);
      dialog.close(); flow.confirming = false; void syncNativeHost().catch(e=>notice(e.message)); resolve(value);
    };
    const submit = e => { e.preventDefault(); done(e.submitter?.value === 'confirm'); };
    const cancel = e => { e.preventDefault(); done(false); };
    form.addEventListener('submit', submit); dialog.addEventListener('cancel', cancel); dialog.showModal();
  });
}

async function openDesign() {
  if (flow.busy) return;
  if (app.dirty || !app.id) return notice('请先保存构筑。');
  if (draftDirty()) {
    if (!await confirmFlow('开始新的前置设计？', '当前草稿名称和备注有未保存修改，继续将放弃这些文字修改；已落盘的草稿保留。', '放弃文字修改并继续')) return;
    flow.draft = null;
  }
  if (flow.design) {
    if (flow.design.id === app.id && flow.design.revision === app.revision) return switchView('design');
    if (!await confirmFlow('重新填写前置设计？', '当前前置设计尚未开始，继续会替换其名称、备注和起手条件。', '重新设计')) return;
  }
  const selected = await api(`/api/deck?id=${encodeURIComponent(app.id)}`);
  const opponent = await api('/api/opponent');
  await mountDesign({...selected, deck_name:selected.name, name:'', notes:'', conditions:{hand_count:5,slots:Array(5).fill(null),banned:[]},
    opponent_ai:false, opponent_responses:true, opponent_config:{...opponent,conditions:{hand_count:5,slots:[...opponent.opening],banned:[]}},
    turn_order:'first',player_lp:8000,opponent_lp:8000,timer:{mode:'off',seconds:0}});
  $('#plan-name').focus();
}
async function mountDesign(design) {
  flow.design = design;
  const catalog = await Promise.all([...new Set([...design.deck.main,...design.opponent_config.deck.main])].map(code=>card(code).catch(()=>design.catalog?.[code] || {id:code,name:String(code)})));
  design.catalog = {...design.catalog,...Object.fromEntries(catalog.map(c => [c.id,c]))};
  flow.design = design;
  $('#plan-name').value = design.name; $('#plan-notes').value = design.notes;
  const decks = await api('/api/decks').catch(e=>{notice(`条件已保留，卡组列表加载失败：${e.message}`);return [];});
  $('#opponent-deck').innerHTML = '<option value="">当前训练卡组</option>'+decks.map(d=>`<option value="${escape(d.id)}">${escape(d.name)}</option>`).join('');
  $('#nav-design').disabled = false;
  renderDesign(); switchView('design');
}

function handError(design) {
  const count = handCount(design);
  if (!inRange(count,1,60)) return '起手数量请输入 1–60 的整数。';
  if (count > design.deck.main.length) return `主卡组只有 ${design.deck.main.length} 张，无法提供 ${count} 张起手；额外和副卡组不参与抽取。`;
  const counts = new Map(), required = new Map(), {slots,banned} = design.conditions;
  if (slots.slice(count).some(c=>c!==null)) return `起手数量已设为 ${count} 张，但超出数量的槽位仍有指定卡牌，请移除或增加起手数量。`;
  for (const code of design.deck.main) counts.set(code, (counts.get(code)||0)+1);
  for (const code of slots.filter(c => c !== null)) required.set(code, (required.get(code)||0)+1);
  for (const code of [...required.keys(),...banned]) if (!counts.has(code)) return `${cardName(design,code)} 已不在当前主卡组，请调整原有起手或禁止条件。`;
  for (const [code,count] of required) {
    if (banned.includes(code)) return `${cardName(design,code)} 同时被指定和禁用，请取消其中一项。`;
    if (count > counts.get(code)) return `${cardName(design,code)} 在主卡组中只有 ${counts.get(code)} 张，不能指定 ${count} 张。`;
  }
  const available = [...counts].reduce((sum,[code,count]) => sum + (banned.includes(code)?0:count-(required.get(code)||0)),0);
  const missing = count - [...required.values()].reduce((a,b)=>a+b,0);
  if (available < missing) return `排除禁用卡并扣除指定副本后，只剩 ${available} 张可抽取，还需要 ${missing} 张，无法组成 ${count} 张起手。`;
  if (design.deck.main.length < 40 || design.deck.main.length > 60) return '开始展开需要 40–60 张主卡组。';
  return '';
}
function conditionError(design) {
  if (!design.name.trim()) return '请先填写方案名称。';
  const problem = handError(design); if (problem) return `玩家：${problem}`;
  if (design.opponent_ai) {const error = handError(design.opponent_config);if(error)return `对手：${error}`;}
  for (const [field,label] of [['player_lp','玩家'],['opponent_lp','对手']]) {
    if (!inRange(design[field] === undefined ? 8000 : design[field],1,maxValue)) return `${label}初始 LP 请输入 1–2,147,483,647 的整数。`;
  }
  const timer = design.timer || {mode:'off',seconds:0};
  if (!['off','up','down'].includes(timer.mode)) return '请选择计时模式。';
  if (!inRange(timer.seconds,timer.mode==='down'?1:0,maxValue)) return `计时时长请输入 ${timer.mode==='down'?1:0}–2,147,483,647 的整数（秒）。`;
  return '';
}
function resizeSlots(d, count) {
  d.conditions.hand_count = count;
  if (!inRange(count,1,60)) return;
  while (d.conditions.slots.length > count && d.conditions.slots.at(-1) === null) d.conditions.slots.pop();
  while (d.conditions.slots.length < count) d.conditions.slots.push(null);
}
function slotsHtml(d, opponent=false) {
  return d.conditions.slots.map((code,i) => `<button data-${opponent?'opponent-slot':'slot'}="${i}" class="opening-slot ${i>=handCount(d)?'overflow-slot':''}"><span>${i>=handCount(d)?'超出数量 · 请调整':'起手'} ${i+1}</span>${code ? `<img src="/pics/${code}.jpg" alt=""><strong>${escape(cardName(d,code))}</strong><small>指定 1 张 · 点击替换或移除</small>` : '<span class="slot-plus">＋</span><strong>随机补齐</strong><small>点击指定卡牌</small>'}</button>`).join('');
}
function renderDesign() {
  const d = flow.design; if (!d) return;
  $('#design-conditions').disabled = !d.name.trim() || flow.busy;
  $('#design-deck').textContent = `${d.deck_name || d.name} · 主卡组 ${d.deck.main.length} 张 · 额外 ${d.deck.extra.length} 张`;
  $('#opening-slots').innerHTML = slotsHtml(d);
  $('#hand-count').value = handCount(d) ?? '';
  $('#hand-count').max = Math.min(60,d.deck.main.length);
  for(const count of [1,2,3]) $(`[data-hand-count="${count}"]`).classList.toggle('primary',handCount(d)===count);
  $('#hand-count-hint').textContent = `实际初始手牌总数；当前最多 ${Math.min(60,d.deck.main.length)} 张。超出数量的已有指定不会自动移除。`;
  $('#banned-cards').innerHTML = d.conditions.banned.map(code => `<button data-unban="${code}" title="取消禁用">${escape(cardName(d,code))} <span>× 取消禁用</span></button>`).join('') || '<small>未设置禁用卡，所有剩余副本均可抽取。</small>';
  $('#opponent-ai').checked = !!d.opponent_ai;
  $('#opponent-settings').hidden = !d.opponent_ai;
  if (d.opponent_config) {
    const o=d.opponent_config;
    $('#opponent-description').textContent = '基础 AI 沿用内核策略，自身回合优先通常召唤后结束。';
    $('#opponent-deck-info').textContent = `${o.name} · 主卡组 ${o.deck.main.length} 张 · 额外 ${o.deck.extra.length} 张`;
    $('#opponent-slots').innerHTML=slotsHtml(o,true);$('#opponent-hand-count').value=handCount(o) ?? '';
    $('#opponent-responses').checked = d.opponent_responses !== false;
  }
  $('#turn-order').value = d.turn_order || 'first';
  $('#player-lp').value = d.player_lp === undefined ? 8000 : d.player_lp ?? '';
  $('#opponent-lp').value = d.opponent_lp === undefined ? 8000 : d.opponent_lp ?? '';
  const timer=d.timer || {mode:'off',seconds:0};
  $('#timer-mode').value=timer.mode;$('#timer-duration').hidden=timer.mode==='off';
  $('#timer-seconds-label').textContent=timer.mode==='down'?'总时长（秒）':'起始时长（秒）';
  $('#timer-seconds').min=timer.mode==='down'?1:0;$('#timer-seconds').value=timer.seconds ?? '';
  $('#design-error').textContent = d.startError || conditionError(d);
  $('#begin-expansion').disabled = !!conditionError(d) || flow.busy || !!app.active;
}
function renderChoices() {
  const d = choiceDesign();
  $('#opening-title').textContent = `${flow.target==='opponent'?'对手':'玩家'}起手槽位 ${flow.slot+1} · ${flow.mode === 'required' ? '添加卡牌' : '禁止卡牌（整副起手生效）'}`;
  $('#choose-banned').hidden=flow.target==='opponent';
  $('#choose-required').classList.toggle('primary', flow.mode === 'required');
  $('#choose-banned').classList.toggle('primary', flow.mode === 'banned');
  $('#clear-slot').disabled = d.conditions.slots[flow.slot] === null;
  $('#opening-choices').innerHTML = [...new Set(d.deck.main)].map(code => {
    const total = d.deck.main.filter(x => x===code).length;
    const assigned = d.conditions.slots.filter(x => x===code).length;
    return `<button data-choice="${code}" class="opening-choice"><img src="/pics/${code}.jpg" alt=""><span><strong>${escape(cardName(d,code))}</strong><small>牌组内 ${total} 张 · 已指定 ${assigned} 张 · 剩余可指定 ${Math.max(0,total-assigned)} 张</small><small>${d.conditions.banned.includes(code) ? '已禁止出现在初始手牌' : flow.mode==='required' ? '指定后仍可随机抽到其余副本' : '加入独立禁用列表，不占起手槽位'}</small></span></button>`;
  }).join('');
}
function choiceDesign() { return flow.target==='opponent' ? flow.design.opponent_config : flow.design; }
function openChoices(target, slot=0, mode='required') {
  flow.target=target;flow.slot=slot;flow.mode=mode;$('#opening-error').textContent='';renderChoices();$('#opening-dialog').showModal();
}
function chooseOpening(code) {
  const d = choiceDesign(), {slots,banned} = d.conditions;
  if (flow.mode === 'banned') {
    if (slots.includes(code)) { $('#opening-error').textContent = '这张卡已被指定，请先移除对应槽位，再加入起手禁用列表。'; return; }
    if (!banned.includes(code)) banned.push(code);
  } else {
    if (banned.includes(code)) { $('#opening-error').textContent = '这张卡已被禁用，请先在独立禁用列表取消，才能指定。'; return; }
    const count = slots.filter((x,i) => x===code && i!==flow.slot).length + 1;
    const total = d.deck.main.filter(x => x===code).length;
    if (count > total) { $('#opening-error').textContent = `主卡组只有 ${total} 张，不能指定 ${count} 张。`; return; }
    slots[flow.slot] = code;
  }
  $('#opening-dialog').close(); renderDesign();
}
function designPayload(d) {
  return Object.fromEntries(['name','notes','deck','deck_name','conditions','opponent_ai','opponent_responses','opponent_config','turn_order','player_lp','opponent_lp','timer'].map(k=>[k,d[k]]));
}
async function selectOpponent(id) {
  if (!id || flow.busy) return;
  flow.busy=true;renderDesign();
  try {
    const selected=await api(`/api/deck?id=${encodeURIComponent(id)}`);
    const cards=await Promise.all([...new Set(selected.deck.main)].map(card));
    Object.assign(flow.design.catalog,Object.fromEntries(cards.map(c=>[c.id,c])));
    Object.assign(flow.design.opponent_config,{id:selected.id,name:selected.name,deck:selected.deck});
    flow.design.startError='';renderDesign();
  } finally {flow.busy=false;$('#opponent-deck').value='';renderDesign();}
}
async function editDesignDeck(target) {
  if (!flow.design || flow.busy || flow.deckEdit) return;
  const d=target==='opponent'?flow.design.opponent_config:flow.design;
  const keys=['deck','id','revision','undo','savedState','selected'];
  flow.deckEdit={target,restore:Object.fromEntries(keys.map(k=>[k,structuredClone(app[k])])),name:$('#deck-name').value};
  ++app.deckEpoch;app.deck=structuredClone(d.deck);app.id=null;app.revision=null;app.undo=[];app.selected=null;
  $('#deck-name').value=target==='opponent'?d.name:d.deck_name;
  app.savedState=deckState();dirty();
  $('#design-deck-edit').hidden=false;$('#design-deck-edit-title').textContent=`正在编辑本次${target==='opponent'?'对手':'玩家'}卡组`;
  $('#save-deck').textContent='应用卡组并返回条件';
  switchView('decks');await renderDeck();await deckList();
}
async function finishDesignDeckEdit(apply) {
  if (!flow.deckEdit || app.busy) return;
  if (!apply && app.dirty && !await confirmFlow('取消本次卡组编辑？','尚未应用的卡牌修改将放弃，前置设计保留编辑前的卡组。','放弃修改')) return;
  const edit=flow.deckEdit, name=$('#deck-name').value.trim(), deck=structuredClone(app.deck), id=app.id;
  if(apply&&!name)return notice('请填写卡组名称。');
  app.busy=true;updateStart();
  try {
    if (apply) {
      const cards=await Promise.all([...new Set(deck.main)].map(card));
      Object.assign(flow.design.catalog,Object.fromEntries(cards.map(c=>[c.id,c])));
      const d=edit.target==='opponent'?flow.design.opponent_config:flow.design;
      d.deck=deck;
      if(edit.target==='opponent') {d.name=name;d.id=id || 'custom';}
      else d.deck_name=name;
      flow.design.startError='';
    }
    flow.deckEdit=null;Object.assign(app,edit.restore);++app.deckEpoch;
    $('#deck-name').value=edit.name;$('#save-deck').textContent='保存构筑';$('#design-deck-edit').hidden=true;
    dirty();await renderDeck();await deckList();renderDesign();switchView('design');
    if(apply)notice('已应用本次训练卡组；原有起手与禁止条件保留，请检查校验提示。');
  } finally {app.busy=false;updateStart();}
}
async function returnConditions() {
  if (flow.busy || !app.active) return;
  if (!await confirmFlow('返回修改条件？','本次尚未保存的操作将放弃，原始记录保留。双方配置将带回前置设计，再次开始会重新随机补牌；已有正式方案不变。','返回修改条件')) return;
  flow.busy=true;flow.restarting=true;updateStart();
  try {
    const d=await api('/api/return-to-design',{id:app.active.id});
    stopTimer();app.active=null;app.reportId=null;app.reportKey=null;flow.draft=null;
    await mountDesign(d);await refreshHistory();
    notice('条件已保留。修改后再次开始，将生成新的起手和独立操作记录。');
  } finally {flow.busy=false;flow.restarting=false;renderDesign();updateStart();}
}
async function reopenConditions(id) {
  if(flow.busy || app.active)return notice('请先结束当前展开。');
  if((flow.design || draftDirty()) && !await confirmFlow('载入此方案的条件？','将替换当前尚未开始的前置设计或未保存文字；正式方案和原始记录保留。','载入条件'))return;
  const d=await api(`/api/design/${id}`);flow.draft=null;await mountDesign(d);
}
function timerValue(timer, now=performance.now()) {
  const elapsed=timer.elapsed+(timer.started===null?0:Math.max(0,now-timer.started));
  return timer.mode==='down'?Math.max(0,timer.seconds-Math.floor(elapsed/1000)):timer.seconds+Math.floor(elapsed/1000);
}
function renderTimer() {
  const t=flow.timer, output=$('#expansion-timer');
  output.hidden=!t || t.mode==='off';
  if(!t || t.mode==='off')return;
  const seconds=timerValue(t);
  output.textContent=`${t.mode==='down'?'倒计时':'正计时'} ${Math.floor(seconds/3600).toString().padStart(2,'0')}:${Math.floor(seconds/60%60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`;
  if(t.mode==='down' && seconds===0 && !t.expired){
    t.expired=true;stopTimer();$('#timer-expired').hidden=false;notice('倒计时已结束，场地仍可继续操作。');
  }
}
function stopTimer() {
  const t=flow.timer;if(!t)return;
  if(t.started!==null)t.elapsed+=Math.max(0,performance.now()-t.started);
  t.started=null;clearInterval(t.interval);t.interval=null;renderTimer();
}
function resetTimer(id, config={mode:'off',seconds:0}) {
  stopTimer();flow.timer={id,...config,elapsed:0,started:null,interval:null,expired:false};
  $('#timer-expired').hidden=true;renderTimer();
}
function startTimer(id) {
  const t=flow.timer;if(!t || t.id!==id || t.mode==='off' || t.started!==null || t.expired)return;
  t.started=performance.now();t.interval=setInterval(renderTimer,200);renderTimer();
}
async function waitOperable(id) {
  if(window.trainerDesktop && !await waitNativeFrame(id))return;
  for(let i=0;i<200 && app.active?.id===id;i++) {
    const state=await api(`/api/ready/${id}`);
    if(app.active?.id!==id)return;
    if(state.ready){startTimer(id);return;}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
}
async function beginExpansion() {
  if (flow.busy || !flow.design) return;
  const problem = conditionError(flow.design); if (problem) return notice(problem);
  flow.busy = true; renderDesign();
  try {
    const d = flow.design;
    $('#native-loading').hidden = false; $('#native-loading').textContent = window.trainerDesktop ? '正在准备展开场地……' : '请在本次打开的原生窗口操作，完成后回到这里点击“展开结束”。';
    switchView('training'); await syncNativeHost();
    const session = await api('/api/start', {deck_id:d.id, design:designPayload(d)});
    app.active={...session,name:d.name,plan_stage:'recording'};
    resetTimer(session.id,d.timer);
    flow.design = null; $('#nav-design').disabled = true; app.reportId = session.id;
    await refreshHistory().catch(e=>notice(`展开已开始，列表刷新失败：${e.message}`));
    void waitOperable(session.id).catch(e=>notice(e.message));
    notice('正在记录本次尝试。满意后点击“展开结束”，检查草稿并保存方案。');
  } catch (e) { if(flow.design)flow.design.startError=e.message; switchView('design'); throw e; }
  finally { flow.busy = false; renderDesign(); updateStart(); }
}
async function restartExpansion() {
  if (flow.busy || !app.active) return;
  if (!await confirmFlow('重新展开？', '将放弃当前尝试的步骤，恢复本次实际起手及双方初始状态。其他方案和历史不受影响。', '保留起手并重新展开')) return;
  flow.busy = true; flow.restarting = true; updateStart();
  try {
    const previous = app.active.id;
    stopTimer();
    await syncNativeHost();
    $('#native-loading').hidden = false; $('#native-loading').textContent = '正在恢复本次起手与初始场地……';
    const result = await api('/api/restart', {id:previous});
    const design = await api(`/api/design/${result.id}`); resetTimer(result.id,design.timer);
    app.active = null; app.reportId = result.id; app.reportKey = null; flow.draft = null;
    await refreshHistory();
    void waitOperable(result.id).catch(e=>notice(e.message));
    notice('已恢复同一起手和初始状态，当前记录从头开始。');
  } finally { flow.busy = false; flow.restarting = false; updateStart(); }
}
async function finishExpansion() {
  if (flow.busy || !app.active) return;
  flow.busy = true; updateStart();
  try { await api('/api/stop', {id:app.active.id}); stopTimer(); await refreshHistory(); }
  finally { flow.busy = false; updateStart(); }
}

function expansionSummary(r) {
  if (!r.expansion) return '<p>原训练历史 · 原始记录和冻结牌组保持可访问。</p>';
  const e = r.expansion, name = c => escape(r.catalog[c]?.name || c);
  const timer=e.timer || {mode:'off',seconds:0}, opponent=e.opponent_config;
  return `<div class="expansion-summary"><span class="badge">${stageNames[r.plan_stage] || '展开记录'}</span><h3>关联牌组：${escape(r.deck_name)}</h3><p>玩家初始手牌 ${e.conditions.hand_count || 5} 张 · ${e.turn_order==='second'?'后手':'先手'} · 初始 LP：玩家 ${e.player_lp || 8000} / 对手 ${e.opponent_lp || 8000}</p><p>指定起手：${e.conditions.slots.map(c=>c===null?'随机补齐':name(c)).join(' · ')}</p><p>整副起手禁用：${e.conditions.banned.map(name).join('、') || '无'}</p><p>对手 AI：${e.opponent_ai ? `开启 · ${escape(opponent.name)} · 可选响应${e.opponent_responses===false?'关闭':'开启'}` : '关闭 · 无对手干扰'}</p>${e.opponent_ai ? `<p>对手指定起手：${(opponent.conditions?.slots || opponent.opening || []).map(c=>c===null?'随机补齐':name(c)).join(' · ')}</p>`:''}<p>计时：${{off:'关闭',up:'正计时',down:'倒计时'}[timer.mode]}${timer.mode==='off'?'':` · ${timer.seconds} 秒`}</p><p class="plan-notes-text">备注：${escape(e.notes || '无')}</p></div>`;
}
async function allowReportChange(id) {
  if (flow.deleting) return false;
  if (flow.saving && (flow.draft?.id || flow.savingId) !== id) return false;
  if (flow.draft?.id !== id && draftDirty()) return confirmFlow('切换记录？', '当前方案名称、步骤或卡牌说明有未保存修改；已落盘的原始记录仍会保留。', '放弃说明修改并切换');
  return true;
}
function prepareDraft(r) {
  if (typeof mountReview === 'function') return mountReview(r);
  const area = $('#draft-editor');
  if (!['draft','saved'].includes(r.plan_stage)) { area.hidden = true; flow.draft = null; return; }
  area.hidden = false;
  if (flow.draft?.id === r.id) return;
  flow.draft = {id:r.id,saved:r.plan_stage==='saved',name:r.expansion.name,notes:r.expansion.notes,originalName:r.expansion.name,originalNotes:r.expansion.notes};
  area.innerHTML = `<h2>${flow.draft.saved?'编辑已保存方案':'待确认草稿'}</h2><p>起手条件与执行记录已冻结，只能调整方案名称和备注。</p><label for="draft-name">方案名称</label><input id="draft-name" maxlength="80" value="${escape(flow.draft.name)}"><label for="draft-notes">备注</label><textarea id="draft-notes" maxlength="4000" rows="3">${escape(flow.draft.notes)}</textarea><p id="draft-message" role="status">${flow.draft.saved?'正式方案已保存。':'草稿已保留在本地，尚未保存为正式方案。'}</p><div class="plan-actions"><button id="save-plan" class="primary">${flow.draft.saved?'保存修改':'保存方案'}</button><button id="draft-conditions">以此条件再次展开</button><button id="delete-draft" class="danger">${flow.draft.saved?'删除方案':'放弃草稿'}</button></div>`;
  $('#draft-name').oninput = e => { flow.draft.name = e.target.value; $('#save-plan').disabled = !e.target.value.trim(); };
  $('#draft-notes').oninput = e => { flow.draft.notes = e.target.value; };
  $('#save-plan').onclick = run(savePlan);
  $('#delete-draft').onclick=run(deleteDraft);
  $('#draft-conditions').onclick=run(()=>reopenConditions(r.id));
}
async function deleteDraft() {
  if(flow.busy || !flow.draft)return;
  const d={...flow.draft};
  if(!await confirmFlow(d.saved?`删除方案“${d.originalName}”？`:'放弃当前草稿？',
    d.saved?'仅删除此方案，来源卡组、其他方案及独立的对局记录保留。':'当前草稿及未保存的文字修改将放弃，原始操作记录和来源卡组保留。',d.saved?'删除方案':'放弃草稿'))return;
  flow.busy=true;flow.deleting=true;
  try {
    await api(d.saved?'/api/plans/delete':'/api/drafts/discard',{id:d.id,name:d.originalName});
    flow.draft=null;flow.selectedPlan=null;app.reportId=null;app.reportKey=null;$('#draft-editor').hidden=true;
    if ($('#review-workspace')) $('#review-workspace').hidden=true;
    if (typeof reviewUI !== 'undefined') {reviewUI.report=null;reviewUI.pending=null;}
    $('#report').hidden=false;
    $('#report').innerHTML='<div class="empty">已处理。可选择其他记录或开始新的前置设计。</div>';
    $('#plan-report').innerHTML='<div class="empty">请选择方案。</div>';
    switchView(d.saved?'plans':'history');
    await Promise.allSettled([refreshPlans(),refreshHistory()]);notice(d.saved?'方案已删除。':'草稿已放弃，原始记录保留。');
  } catch(e) {$('#draft-message').textContent=`操作失败：${e.message}。当前内容已保留。`;throw e;}
  finally {flow.busy=false;flow.deleting=false;}
}
async function savePlan() {
  if (typeof previewReview === 'function') return previewReview();
  if (flow.busy || !flow.draft) return;
  flow.busy = true; flow.saving = true; $('#save-plan').disabled = true;
  $('#draft-name').disabled = $('#draft-notes').disabled = true;
  const draft = {...flow.draft};
  flow.savingId=draft.id;
  try {
    const saved = await api(draft.saved?'/api/plans/update':'/api/plans/save', {id:draft.id,name:draft.name,notes:draft.notes,
      original_name:draft.originalName,original_notes:draft.originalNotes});
    flow.draft = null; $('#draft-editor').hidden = true;
    app.reportKey = null;
    notice(`方案“${saved.name}”已保存，可在展开管理中查看。`);
    await refreshHistory().catch(e=>notice(`方案已保存，记录列表刷新失败：${e.message}`));
    await showPlan(saved.id).catch(e=>notice(`方案已保存，可稍后从展开管理重新打开：${e.message}`));
  } catch (e) { if ($('#draft-message')) $('#draft-message').textContent = `保存失败：${e.message}。内容已保留，可以重试。`; throw e; }
  finally { flow.busy = false; flow.saving = false; flow.savingId=null; if ($('#save-plan')) {$('#save-plan').disabled = !flow.draft?.name.trim();$('#draft-name').disabled=$('#draft-notes').disabled=false;} }
}
async function refreshPlans() {
  const plans = await api('/api/plans');
  if(typeof renderPlanList==='function'){renderPlanList(plans);return;}
  $('#plan-list').innerHTML = plans.map(p=>`<button class="history-item ${p.id===flow.selectedPlan?'current':''}" data-plan="${p.id}"><strong>${escape(p.name)}</strong><small>${escape(p.deck_name)}</small><small>${dt(p.saved_ms)}</small></button>`).join('') || '<div class="empty">还没有正式方案<br><small>展开结束后，在草稿中点击“保存方案”。</small></div>';
}
async function showPlan(id) {
  if(!await allowReportChange(id))return;
  flow.selectedPlan = id;
  const plan = await api(`/api/plan/${id}`);
  if (flow.selectedPlan !== id) return;
  switchView('plans'); await refreshPlans();
  if (flow.selectedPlan !== id) return;
  if (typeof renderSavedPlan === 'function') {renderSavedPlan(plan);return;}
  const render = raw => {
    $('#plan-report').innerHTML = `<div class="plan-actions"><span>保存于 ${dt(plan.saved_ms)}</span><button id="edit-plan">调整方案</button><button id="plan-conditions">以此条件再次展开</button><button id="delete-plan" class="danger">删除方案</button></div>${expansionSummary(plan)}${renderTrainingReport(plan,{raw}).replaceAll('all-events','plan-all-events')}`;
    $('#edit-plan').onclick=run(()=>showReport(id));
    $('#plan-conditions').onclick=run(()=>reopenConditions(id));
    $('#plan-all-events').onchange = e => render(e.target.checked);
    $('#delete-plan').onclick = run(async()=>{
      if(flow.busy)return;
      if (!await confirmFlow(`删除方案“${plan.name}”？`, '只删除此正式方案；源牌组、其他方案和原始历史记录保留。', '删除此方案')) return;
      flow.busy=true;flow.deleting=true;
      try {
        await api('/api/plans/delete',{id,name:plan.name}); flow.selectedPlan = null;
        if(flow.draft?.id===id){flow.draft=null;$('#draft-editor').hidden=true;}
        app.reportKey=null;
        $('#plan-report').innerHTML = '<div class="empty">方案已删除。</div>';
        await refreshPlans().catch(e=>notice(`方案已删除，列表刷新失败：${e.message}`));
        await refreshHistory();notice(`已删除方案“${plan.name}”。`);
      } finally {flow.busy=false;flow.deleting=false;}
    });
  };
  render(false);
}

$('#start-training').onclick = run(openDesign);
$('#nav-design').onclick = () => switchView('design');
$('#nav-plans').onclick = run(async()=>{switchView('plans');await refreshPlans();});
$('#refresh-plans').onclick = run(refreshPlans);
$('#design-back').onclick = run(()=>editDesignDeck('player'));
$('#edit-opponent-deck').onclick=run(()=>editDesignDeck('opponent'));
$('#cancel-design-deck-edit').onclick=run(()=>finishDesignDeckEdit(false));
$('#opponent-deck').onchange=run(e=>selectOpponent(e.target.value));
$('#plan-name').oninput = e => { flow.design.name=e.target.value;flow.design.startError=''; renderDesign(); };
$('#plan-notes').oninput = e => { flow.design.notes=e.target.value; };
$('#opponent-ai').onchange = e => { flow.design.opponent_ai=e.target.checked;renderDesign(); };
$('#opponent-responses').onchange=e=>{flow.design.opponent_responses=e.target.checked;};
$('#turn-order').onchange=e=>{flow.design.turn_order=e.target.value;};
for(const [id,field] of [['player-lp','player_lp'],['opponent-lp','opponent_lp']]) $(`#${id}`).oninput=e=>{flow.design[field]=inputInteger(e);flow.design.startError='';renderDesign();};
$('#hand-count').oninput=e=>{resizeSlots(flow.design,inputInteger(e));flow.design.startError='';renderDesign();};
$('#opponent-hand-count').oninput=e=>{resizeSlots(flow.design.opponent_config,inputInteger(e));flow.design.startError='';renderDesign();};
$('#timer-mode').onchange=e=>{flow.design.timer.mode=e.target.value;if(e.target.value==='off'&&!inRange(flow.design.timer.seconds,0,maxValue))flow.design.timer.seconds=0;flow.design.startError='';renderDesign();};
$('#timer-seconds').oninput=e=>{flow.design.timer.seconds=inputInteger(e);flow.design.startError='';renderDesign();};
$('#add-opening-ban').onclick=()=>openChoices('player',0,'banned');
$('#begin-expansion').onclick = run(beginExpansion);
$('#restart-expansion').onclick = run(restartExpansion);
$('#return-conditions').onclick=run(returnConditions);
$('#finish-training').onclick = $('#end-training').onclick = run(finishExpansion);
$('#opening-close').onclick = () => $('#opening-dialog').close();
$('#choose-required').onclick = () => {flow.mode='required';$('#opening-error').textContent='';renderChoices();};
$('#choose-banned').onclick = () => {flow.mode='banned';$('#opening-error').textContent='';renderChoices();};
$('#clear-slot').onclick = () => {const d=choiceDesign();d.conditions.slots[flow.slot]=null;resizeSlots(d,handCount(d));$('#opening-dialog').close();renderDesign();};
document.addEventListener('click',run(async e=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if (b.dataset.handCount!==undefined) {resizeSlots(flow.design,Number(b.dataset.handCount));flow.design.startError='';renderDesign();}
  if (b.dataset.slot!==undefined) openChoices('player',Number(b.dataset.slot));
  if (b.dataset.opponentSlot!==undefined) openChoices('opponent',Number(b.dataset.opponentSlot));
  if (b.dataset.choice) chooseOpening(Number(b.dataset.choice));
  if (b.dataset.unban) {flow.design.conditions.banned=flow.design.conditions.banned.filter(c=>c!==Number(b.dataset.unban));renderDesign();}
  if (b.dataset.plan) await showPlan(b.dataset.plan);
}));
