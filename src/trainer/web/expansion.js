'use strict';

const flow = {design:null, draft:null, selectedPlan:null, slot:0, mode:'required', busy:false, saving:false, restarting:false};
const stageNames = {recording:'正在记录 · 未保存方案', draft:'待确认草稿', saved:'已保存方案', discarded:'已放弃尝试', deleted:'原始记录 · 正式方案已删除'};

function unsavedSummary() {
  const messages = [];
  if (app.dirty) messages.push('构筑有未保存修改。');
  if (flow.design) messages.push('前置设计尚未开始，退出后需要重新填写。');
  if (app.active) messages.push('展开尚未结束，退出将保留中断记录，尚未保存为正式方案。');
  if (flow.draft && draftDirty()) messages.push('当前草稿名称或备注的修改尚未保存。');
  else if (flow.draft) messages.push('待确认草稿已保留在本地，但尚未保存为正式方案。');
  return messages.join('\n');
}
function draftDirty() { return flow.draft && (flow.draft.name !== flow.draft.originalName || flow.draft.notes !== flow.draft.originalNotes); }

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
  const catalog = await Promise.all([...new Set(selected.deck.main)].map(card));
  flow.design = {...selected, catalog:Object.fromEntries(catalog.map(c => [c.id,c])), name:'', notes:'', conditions:{slots:Array(5).fill(null),banned:[]}, opponent_ai:false};
  $('#plan-name').value = ''; $('#plan-notes').value = ''; $('#opponent-ai').checked = false;
  $('#design-deck').textContent = `${selected.name} · 主卡组 ${selected.deck.main.length} 张 · 额外 ${selected.deck.extra.length} 张`;
  $('#opponent-description').textContent = (await api('/api/opponent')).description;
  $('#nav-design').disabled = false;
  renderDesign(); switchView('design'); $('#plan-name').focus();
}

function conditionError(design) {
  if (!design.name.trim()) return '请先填写方案名称。';
  const counts = new Map(), required = new Map(), {slots,banned} = design.conditions;
  for (const code of design.deck.main) counts.set(code, (counts.get(code)||0)+1);
  for (const code of slots.filter(c => c !== null)) required.set(code, (required.get(code)||0)+1);
  for (const [code,count] of required) {
    if (banned.includes(code)) return `${design.catalog[code].name} 同时被指定和禁用，请取消其中一项。`;
    if (count > counts.get(code)) return `${design.catalog[code].name} 在主卡组中只有 ${counts.get(code)} 张，不能指定 ${count} 张。`;
  }
  const available = [...counts].reduce((sum,[code,count]) => sum + (banned.includes(code)?0:count-(required.get(code)||0)),0);
  const missing = slots.filter(c => c===null).length;
  if (available < missing) return `排除禁用卡并扣除指定副本后，只剩 ${available} 张可抽取，还需要 ${missing} 张，无法组成 5 张起手。`;
  if (design.deck.main.length < 40 || design.deck.main.length > 60) return '开始展开需要 40–60 张主卡组。';
  return '';
}
function renderDesign() {
  const d = flow.design; if (!d) return;
  $('#design-conditions').disabled = !d.name.trim() || flow.busy;
  $('#opening-slots').innerHTML = d.conditions.slots.map((code,i) => `<button data-slot="${i}" class="opening-slot"><span>起手 ${i+1}</span>${code ? `<img src="/pics/${code}.jpg" alt=""><strong>${escape(d.catalog[code].name)}</strong><small>指定 1 张 · 点击替换或移除</small>` : '<span class="slot-plus">＋</span><strong>随机补齐</strong><small>点击添加或禁止卡牌</small>'}</button>`).join('');
  $('#banned-cards').innerHTML = d.conditions.banned.map(code => `<button data-unban="${code}" title="取消禁用">${escape(d.catalog[code].name)} <span>× 取消禁用</span></button>`).join('') || '<small>未设置禁用卡，所有剩余副本均可抽取。</small>';
  $('#design-error').textContent = d.startError || conditionError(d);
  $('#begin-expansion').disabled = !!conditionError(d) || flow.busy || !!app.active;
}
function renderChoices() {
  const d = flow.design;
  $('#opening-title').textContent = `起手槽位 ${flow.slot+1} · ${flow.mode === 'required' ? '添加卡牌' : '禁止卡牌（整副起手生效）'}`;
  $('#choose-required').classList.toggle('primary', flow.mode === 'required');
  $('#choose-banned').classList.toggle('primary', flow.mode === 'banned');
  $('#clear-slot').disabled = d.conditions.slots[flow.slot] === null;
  $('#opening-choices').innerHTML = Object.values(d.catalog).map(c => {
    const total = d.deck.main.filter(x => x===c.id).length;
    const assigned = d.conditions.slots.filter(x => x===c.id).length;
    return `<button data-choice="${c.id}" class="opening-choice"><img src="/pics/${c.id}.jpg" alt=""><span><strong>${escape(c.name)}</strong><small>牌组内 ${total} 张 · 已指定 ${assigned} 张 · 剩余可指定 ${total-assigned} 张</small><small>${d.conditions.banned.includes(c.id) ? '已禁止出现在初始手牌' : flow.mode==='required' ? '指定后仍可随机抽到其余副本' : '加入独立禁用列表，不占起手槽位'}</small></span></button>`;
  }).join('');
}
function chooseOpening(code) {
  const d = flow.design, {slots,banned} = d.conditions;
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
async function beginExpansion() {
  if (flow.busy || !flow.design) return;
  const problem = conditionError(flow.design); if (problem) return notice(problem);
  flow.busy = true; renderDesign();
  try {
    const d = flow.design;
    $('#native-loading').hidden = false; $('#native-loading').textContent = window.trainerDesktop ? '正在准备展开场地……' : '请在本次打开的原生窗口操作，完成后回到这里点击“展开结束”。';
    switchView('training'); await syncNativeHost();
    const session = await api('/api/start', {deck_id:d.id, design:{name:d.name,notes:d.notes,conditions:d.conditions,opponent_ai:d.opponent_ai,revision:d.revision}});
    flow.design = null; $('#nav-design').disabled = true; app.reportId = session.id;
    await refreshHistory();
    if (window.trainerDesktop) void waitNativeFrame(session.id).catch(e=>notice(e.message));
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
    await syncNativeHost();
    $('#native-loading').hidden = false; $('#native-loading').textContent = '正在恢复本次起手与初始场地……';
    const result = await api('/api/restart', {id:previous});
    app.active = null; app.reportId = result.id; app.reportKey = null; flow.draft = null;
    await refreshHistory();
    if (window.trainerDesktop) void waitNativeFrame(result.id).catch(e=>notice(e.message));
    notice('已恢复同一起手和初始状态，当前记录从头开始。');
  } finally { flow.busy = false; flow.restarting = false; updateStart(); }
}
async function finishExpansion() {
  if (flow.busy || !app.active) return;
  flow.busy = true; updateStart();
  try { await api('/api/stop', {id:app.active.id}); await refreshHistory(); }
  finally { flow.busy = false; updateStart(); }
}

function expansionSummary(r) {
  if (!r.expansion) return '<p>原训练历史 · 原始记录和冻结牌组保持可访问。</p>';
  const e = r.expansion, name = c => escape(r.catalog[c]?.name || c);
  return `<div class="expansion-summary"><span class="badge">${stageNames[r.plan_stage] || '展开记录'}</span><h3>关联牌组：${escape(r.deck_name)}</h3><p>指定起手：${e.conditions.slots.map(c=>c===null?'随机补齐':name(c)).join(' · ')}</p><p>整副起手禁用：${e.conditions.banned.map(name).join('、') || '无'}</p><p>对手 AI：${e.opponent_ai ? `开启 · ${escape(e.opponent_config.name)}` : '关闭 · 无对手干扰'}</p>${e.opponent_ai ? `<p>${escape(e.opponent_config.description)}</p>`:''}<p class="plan-notes-text">备注：${escape(e.notes || '无')}</p></div>`;
}
async function allowReportChange(id) {
  if (flow.saving && flow.draft?.id !== id) return false;
  if (flow.draft?.id !== id && draftDirty()) return confirmFlow('切换记录？', '当前草稿名称和备注有未保存修改；已落盘的原始草稿仍会保留。', '放弃文字修改并切换');
  return true;
}
function prepareDraft(r) {
  const area = $('#draft-editor');
  if (r.plan_stage !== 'draft') { area.hidden = true; flow.draft = null; return; }
  area.hidden = false;
  if (flow.draft?.id === r.id) return;
  flow.draft = {id:r.id,name:r.expansion.name,notes:r.expansion.notes,originalName:r.expansion.name,originalNotes:r.expansion.notes};
  area.innerHTML = `<h2>待确认草稿</h2><p>起手条件与执行记录已冻结，只能调整方案名称和备注。</p><label for="draft-name">方案名称</label><input id="draft-name" maxlength="80" value="${escape(flow.draft.name)}"><label for="draft-notes">备注</label><textarea id="draft-notes" maxlength="4000" rows="3">${escape(flow.draft.notes)}</textarea><p id="draft-message" role="status">草稿已保留在本地，尚未保存为正式方案。</p><button id="save-plan" class="primary">保存方案</button>`;
  $('#draft-name').oninput = e => { flow.draft.name = e.target.value; $('#save-plan').disabled = !e.target.value.trim(); };
  $('#draft-notes').oninput = e => { flow.draft.notes = e.target.value; };
  $('#save-plan').onclick = run(savePlan);
}
async function savePlan() {
  if (flow.busy || !flow.draft) return;
  flow.busy = true; flow.saving = true; $('#save-plan').disabled = true;
  $('#draft-name').disabled = $('#draft-notes').disabled = true;
  const draft = {...flow.draft};
  try {
    const saved = await api('/api/plans/save', {id:draft.id,name:draft.name,notes:draft.notes});
    flow.draft = null; $('#draft-editor').hidden = true;
    app.reportKey = null;
    notice(`方案“${saved.name}”已保存，可在展开管理中查看。`);
    await refreshHistory().catch(e=>notice(`方案已保存，记录列表刷新失败：${e.message}`));
    await showPlan(saved.id).catch(e=>notice(`方案已保存，可稍后从展开管理重新打开：${e.message}`));
  } catch (e) { if ($('#draft-message')) $('#draft-message').textContent = `保存失败：${e.message}。内容已保留，可以重试。`; throw e; }
  finally { flow.busy = false; flow.saving = false; if ($('#save-plan')) {$('#save-plan').disabled = !flow.draft?.name.trim();$('#draft-name').disabled=$('#draft-notes').disabled=false;} }
}
async function refreshPlans() {
  const plans = await api('/api/plans');
  $('#plan-list').innerHTML = plans.map(p=>`<button class="history-item ${p.id===flow.selectedPlan?'current':''}" data-plan="${p.id}"><strong>${escape(p.name)}</strong><small>${escape(p.deck_name)}</small><small>${dt(p.saved_ms)}</small></button>`).join('') || '<div class="empty">还没有正式方案<br><small>展开结束后，在草稿中点击“保存方案”。</small></div>';
}
async function showPlan(id) {
  flow.selectedPlan = id;
  const plan = await api(`/api/plan/${id}`);
  if (flow.selectedPlan !== id) return;
  switchView('plans'); await refreshPlans();
  if (flow.selectedPlan !== id) return;
  const render = raw => {
    $('#plan-report').innerHTML = `<div class="plan-actions"><span>保存于 ${dt(plan.saved_ms)}</span><button id="delete-plan" class="danger">删除方案</button></div>${expansionSummary(plan)}${renderTrainingReport(plan,{raw}).replaceAll('all-events','plan-all-events')}`;
    $('#plan-all-events').onchange = e => render(e.target.checked);
    $('#delete-plan').onclick = run(async()=>{
      if (!await confirmFlow(`删除方案“${plan.name}”？`, '只删除此正式方案；源牌组、其他方案和原始历史记录保留。', '删除此方案')) return;
      await api('/api/plans/delete',{id,name:plan.name}); flow.selectedPlan = null;
      $('#plan-report').innerHTML = '<div class="empty">方案已删除。</div>'; await refreshPlans(); notice(`已删除方案“${plan.name}”。`);
    });
  };
  render(false);
}

$('#start-training').onclick = run(openDesign);
$('#nav-design').onclick = () => switchView('design');
$('#nav-plans').onclick = run(async()=>{switchView('plans');await refreshPlans();});
$('#refresh-plans').onclick = run(refreshPlans);
$('#design-back').onclick = () => switchView('decks');
$('#plan-name').oninput = e => { flow.design.name=e.target.value;flow.design.startError=''; renderDesign(); };
$('#plan-notes').oninput = e => { flow.design.notes=e.target.value; };
$('#opponent-ai').onchange = e => { flow.design.opponent_ai=e.target.checked; };
$('#begin-expansion').onclick = run(beginExpansion);
$('#restart-expansion').onclick = run(restartExpansion);
$('#finish-training').onclick = $('#end-training').onclick = run(finishExpansion);
$('#opening-close').onclick = () => $('#opening-dialog').close();
$('#choose-required').onclick = () => {flow.mode='required';$('#opening-error').textContent='';renderChoices();};
$('#choose-banned').onclick = () => {flow.mode='banned';$('#opening-error').textContent='';renderChoices();};
$('#clear-slot').onclick = () => {flow.design.conditions.slots[flow.slot]=null;$('#opening-dialog').close();renderDesign();};
document.addEventListener('click',run(async e=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if (b.dataset.slot!==undefined) {flow.slot=Number(b.dataset.slot);flow.mode='required';$('#opening-error').textContent='';renderChoices();$('#opening-dialog').showModal();}
  if (b.dataset.choice) chooseOpening(Number(b.dataset.choice));
  if (b.dataset.unban) {flow.design.conditions.banned=flow.design.conditions.banned.filter(c=>c!==Number(b.dataset.unban));renderDesign();}
  if (b.dataset.plan) await showPlan(b.dataset.plan);
}));
