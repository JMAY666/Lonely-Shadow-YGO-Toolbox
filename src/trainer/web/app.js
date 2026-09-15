'use strict';
const $ = (s) => document.querySelector(s);
const escape = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const zoneNames = {main:'主卡组',extra:'额外卡组',side:'副卡组',1:'卡组',2:'手牌',4:'怪兽区',8:'魔法陷阱区',16:'墓地',32:'除外',64:'额外卡组',128:'叠放素材'};
const statusNames = {starting:'正在启动',running:'展开中',stopping:'正在保存草稿',completed:'手动结束',interrupted:'中断',damaged:'记录损坏'};
const reasons = {manual:'手动结束',client_closed:'关闭了模拟器窗口',engine_ended:'引擎提前结束',native_exit_without_end:'模拟器异常退出或记录未完成',deck_load_failed:'构筑载入失败',launch_failed:'启动失败'};
const zones = ['main', 'extra', 'side'];
const zoneLimits = {main:60, extra:15, side:15};
const app = {token:'',deck:{main:[],extra:[],side:[]},deckTags:{tag_ids:[],primary_ids:[]},deckTagNames:{},id:null,revision:null,dirty:false,cache:new Map(),pendingCards:new Map(),offset:0,total:0,history:[],active:null,reportId:null,allEvents:false,searchGeneration:0,renderGeneration:0,detailGeneration:0,deckEpoch:0,selected:null,undo:[],savedState:null,busy:false};
const importState = {generation:0, preview:null, text:'', busy:false, creating:false, mode:'import'};
const dt = (v) => v ? new Date(v).toLocaleString('zh-CN',{hour12:false}) : '未知';
const duration = (v) => `${Math.floor(v/60000)} 分 ${Math.floor(v/1000)%60} 秒`;
let noticeTimer;
function notice(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').hidden=true,6000);}
async function api(url, body){const result=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Trainer-Token':app.token},body:JSON.stringify(body)});const data=await result.json();if(!result.ok){const error=new Error(data.error||'请求失败');error.status=result.status;throw error;}return data;}
function run(fn){return async(...args)=>{try{await fn(...args);}catch(e){notice(e.message);}};}
async function card(code) {
  if (app.cache.has(code)) return app.cache.get(code);
  if (!app.pendingCards.has(code)) {
    app.pendingCards.set(code, api(`/api/card/${code}`).then(c => {
      app.cache.set(code, c);
      return c;
    }).finally(() => app.pendingCards.delete(code)));
  }
  return app.pendingCards.get(code);
}
function switchView(view) {
  // Background completion updates the expansion's destination without taking
  // the user away from a different module or replacing its editor buffer.
  if (typeof moduleUI !== 'undefined' && moduleUI.current !== 'expansion' && view !== 'decks') {
    moduleUI.expansionView = view;
    return;
  }
  if(view==='compromise' && typeof branchUI!=='undefined' && !selectedBranch()?.valid)return notice('请先在展开时间轴中创建或选择妥协分支');
  if (view === 'confirmation' && (typeof reviewUI === 'undefined' || !reviewUI.pending)) { notice('请从当前方案的保存操作进入确认。'); view = 'history'; }
  if (activeDesignDeckEdit() && view !== 'decks') return notice('请先应用本次卡组编辑，或取消编辑并返回条件。');
  if (typeof flow !== 'undefined' && app.view !== view) {
    if (app.view === 'design' && flow.design && view !== 'training') notice('前置设计尚未开始，填写内容保留在“展开前置设计”中；退出应用会丢失这些设置。');
    else if (app.view === 'training' && app.active) notice('当前展开尚未保存为方案，记录继续进行，可返回展开场地。');
    else if (app.view === 'history' && flow.draft) notice('草稿尚未保存为正式方案，可返回继续调整；退出前请保存名称和备注修改。');
  }
  if (typeof moduleUI !== 'undefined' && moduleUI.current === 'expansion') moduleUI.expansionView = view;
  displayView(view);
}
function activeDesignDeckEdit() {
  return typeof flow !== 'undefined' && flow.deckEdit && (typeof moduleUI === 'undefined' || moduleUI.editorOwner === 'expansion');
}
function displayView(view) {
  app.view = view;
  if (typeof setDeckPage === 'function') setDeckPage(app.deckPage || 'manager');
  if(typeof closeBranchMenu==='function')closeBranchMenu(false);
  if(typeof closeReviewDetail==='function')closeReviewDetail();
  if (view !== 'decks') setLibraryOpen(false, false);
  $('#home').hidden = view !== 'home';
  const selecting = view === 'decks' && typeof moduleUI !== 'undefined' && moduleUI.current === 'expansion' && !activeDesignDeckEdit();
  $('#editor').hidden = view !== 'decks' || selecting;
  $('#deck-selection').hidden = !selecting;
  $('#history').hidden = view !== 'history';
  $('#training').hidden = view !== 'training';
  $('#design').hidden = view !== 'design';
  $('#plans').hidden = view !== 'plans';
    $('#tags').hidden = view !== 'tags';
    $('#compromise-design').hidden = view !== 'compromise';
  $('#save-confirmation').hidden = view !== 'confirmation';
  document.body.classList.toggle('history-view', ['history','plans','confirmation','tags'].includes(view));
    for (const name of ['decks', 'history', 'training', 'design', 'plans', 'compromise']) {
    const button = $(`#nav-${name}`);
    button.classList.toggle('active', view === name);
    if (view === name) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  void syncNativeHost().catch(e => notice(e.message));
}
async function syncNativeHost() {
  if (!window.trainerDesktop) return;
  if ($('#training').hidden || (typeof flow !== 'undefined' && flow.confirming) || (typeof rewindState !== 'undefined' && rewindState.busy)) return window.trainerDesktop.updateLayout({visible:false});
  const box = $('#native-stage').getBoundingClientRect();
  return window.trainerDesktop.updateLayout({visible:true,x:box.x,y:box.y,width:box.width,height:box.height,
    viewportWidth:window.innerWidth,viewportHeight:window.innerHeight, timeline:true});
}
async function waitNativeFrame(id) {
  for (let attempt=0; attempt<80 && app.active?.id===id; attempt++) {
    const state=await api(`/api/native/status?id=${id}`);
    if(app.active?.id!==id)return;
    if(state.frame_ready && state.visible && state.owns_stage_hit_test && state.composition_compatible){$('#native-loading').hidden=true;return true;}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(app.active?.id===id) $('#native-loading').textContent='训练场地未能显示，请结束本次训练并重新启动应用。';
  return false;
}
function setDeckTags(value, names = {}) {
  app.deckTags = structuredClone(value || {tag_ids:[],primary_ids:[]});
  app.deckTagNames = {...names};
}
function deckState() { return JSON.stringify({name:$('#deck-name').value.trim(), deck:app.deck, tags:app.deckTags}); }
function dirty() {
  app.dirty = deckState() !== app.savedState;
  $('#deck-status').textContent = app.dirty ? '● 有未保存的修改' : !app.id ? '新构筑 · 尚未保存' : app.id.startsWith('existing/') ? '已有构筑 · 保存时创建练习室副本' : '已保存 · 本地构筑';
  $('#deck-status').classList.toggle('is-dirty', app.dirty);
  updateStart();
}
function updateStart() {
  $('#start-training').disabled = !app.id || app.dirty || !!app.active || app.busy;
  for (const id of ['save-deck', 'deck-name', 'back-to-decks']) $(`#${id}`).disabled = app.busy;
  document.querySelectorAll('[data-open-deck],[data-deck-menu],[data-create-deck]').forEach(button => { button.disabled = app.busy; });
  $('#undo-deck').disabled = app.busy || !app.undo.length;
  $('#sort-deck').disabled = app.busy || !zones.some(zone => app.deck[zone].length);
  $('#nav-training').hidden = false;
  $('#nav-training').disabled = !app.active;
  const flowBusy = (typeof flow !== 'undefined' && flow.busy) || (typeof rewindState !== 'undefined' && rewindState.busy);
  $('#finish-training').disabled = !app.active || app.active.status === 'stopping' || flowBusy;
  $('#end-training').disabled = $('#finish-training').disabled;
  $('#restart-expansion').disabled = !app.active?.plan_stage || app.active.status === 'stopping' || flowBusy;
  $('#return-conditions').disabled = $('#restart-expansion').disabled;
  if (activeDesignDeckEdit()) $('#start-training').disabled=true;
  if (typeof updateModuleChrome === 'function') updateModuleChrome();
  if (typeof updateDeckSelectionControls === 'function') updateDeckSelectionControls();
  if (typeof updateDeckTagSummary === 'function') updateDeckTagSummary();
  if (typeof flow !== 'undefined' && flow.timer && (!app.active || app.active.status==='stopping') && flow.timer.started!==null) stopTimer();
  $('#training-title').textContent = app.active ? `${app.active.name} · ${statusNames[app.active.status]}` : '展开场地';
}
function setLibraryOpen(open, focus = true) {
  // The shared editor now always shows its third column.
  $('#card-library').hidden = false;
  if (open && focus) $('#search').focus();
}
async function deckList() {
  const generation = typeof deckManager === 'undefined' ? 0 : ++deckManager.listGeneration;
  const decks = await api('/api/decks');
  if (typeof deckManager !== 'undefined' && generation !== deckManager.listGeneration) return;
  if (typeof renderDeckBoxes === 'function') renderDeckBoxes(decks);
  if (typeof renderDeckSelectionList === 'function') renderDeckSelectionList(decks);
}
async function openDeck(id) {
  if (app.busy) return;
  if (!await allowDeckReplacement()) return;
  if (app.busy) return;
  ++app.deckEpoch;
  app.busy = true;
  updateStart();
  try {
    const d = await api(`/api/deck?id=${encodeURIComponent(id)}`);
    app.deck = d.deck;
    setDeckTags(d.tag_selection, d.tag_names);
    app.id = d.id;
    app.revision = d.revision;
    app.sourceName = d.name;
    app.undo = [];
    app.selected = null;
    ++app.detailGeneration;
    $('#card-detail').innerHTML = '<div class="detail-placeholder"><strong>选择一张卡牌</strong><p>从右侧卡牌库添加卡牌</p></div>';
    $('#deck-name').value = d.name;
    app.savedState = deckState();
    dirty();
    setDeckPage('editor');
    switchView('decks');
    await renderDeck();
    $('#deck-cards').scrollTop = 0;
    await deckList();
    const first = zones.flatMap(zone => app.deck[zone])[0];
    if (first) await showCard(first);
  } finally { app.busy = false; updateStart(); updateDetailCounts(); }
}
function confirmDeckDeletion(selected, clearing) {
  const dialog = $('#delete-dialog');
  $('#delete-message').textContent = `删除构筑“${selected.name}”？`;
  $('#delete-warning').textContent = '删除前会保存备份；训练历史和构筑快照保留。' +
    (clearing ? '当前编辑区将清空' + (app.dirty ? '，尚未保存的修改会被放弃。' : '。') : '当前正在编辑的其他构筑不受影响。');
  dialog.returnValue = 'cancel';
  return new Promise(resolve => {
    const form=dialog.querySelector('form');
    let settled=false;
    const finish=value=>{
      if(settled)return;
      settled=true;
      form.removeEventListener('submit',submit);
      dialog.removeEventListener('cancel',cancel);
      dialog.removeEventListener('close',closed);
      if(dialog.open)dialog.close(value);
      resolve(value==='delete');
    };
    const submit=event=>{event.preventDefault();finish(event.submitter?.value || 'cancel');};
    const cancel=event=>{event.preventDefault();finish('cancel');};
    const closed=()=>finish(dialog.returnValue);
    // Native dialog close events may wait for a frame in hidden/occluded windows.
    // Settle directly from the user's submit/cancel event instead.
    form.addEventListener('submit',submit);
    dialog.addEventListener('cancel',cancel);
    dialog.addEventListener('close',closed);
    dialog.showModal();
  });
}
async function deleteDeck(id) {
  if (activeDesignDeckEdit()) return;
  if (app.busy || !id) return;
  app.busy = true;
  updateStart();
  try {
    const selected = await api(`/api/deck?id=${encodeURIComponent(id)}`);
    const clearing = id === app.id;
    if (!await confirmDeckDeletion(selected, clearing)) return;
    await api('/api/decks/delete', { id, revision: selected.revision });
    if (clearing) {
      ++app.deckEpoch;
      app.deck = {main:[], extra:[], side:[]};
      setDeckTags();
      app.id = app.revision = null;
      app.undo = [];
      app.selected = null;
      ++app.detailGeneration;
      $('#deck-name').value = '新构筑';
      app.savedState = deckState();
      dirty();
      await renderDeck();
      setDeckPage('manager');
    }
    await deckList();
    notice(`已删除“${selected.name}”，备份已保留。`);
  } finally {
    app.busy = false;
    updateStart();
    updateDetailCounts();
    $('#refresh-decks').focus({preventScroll:true});
  }
}
function rememberDeck() {
  app.undo.push(structuredClone(app.deck));
  if (app.undo.length > 50) app.undo.shift();
}
async function newDeck() { openCreateDeck('blank'); }
async function addCard(code, zone) {
  if (app.busy) return;
  const epoch = app.deckEpoch;
  const c = await card(code);
  // An open/save may have started while the card request was in flight.
  if (app.busy || epoch !== app.deckEpoch) return;
  zone ??= c.extra ? 'extra' : 'main';
  if (!zones.includes(zone)) return;
  if (c.type & 0x4000) return notice('衍生物不能加入构筑。');
  if (zone !== 'side' && !!c.extra !== (zone === 'extra')) return notice('卡牌类型与主卡组／额外卡组分区不一致。');
  if (app.deck[zone].length >= zoneLimits[zone]) return notice(`${zoneNames[zone]}已达到 ${zoneLimits[zone]} 张上限。`);
  rememberDeck();
  app.deck[zone].push(code);
  dirty();
  await renderDeck();
}
async function removeCard(code, zone, index) {
  if (app.busy || !zones.includes(zone)) return;
  index = index === undefined ? app.deck[zone].lastIndexOf(code) : index;
  if (index < 0 || app.deck[zone][index] !== code) return;
  rememberDeck();
  app.deck[zone].splice(index, 1);
  dirty();
  await renderDeck();
}
async function undoDeck() {
  if (app.busy || !app.undo.length) return;
  app.deck = app.undo.pop();
  dirty();
  await renderDeck();
}
function sortKey(code) {
  const c = app.cache.get(code) || {type:0};
  const kind = c.type & 0x40 ? 1 : c.type & 0x2000 ? 2 : c.type & 0x800000 ? 3 : c.type & 0x4000000 ? 4 : c.type & 1 ? 0 : c.type & 2 ? 5 : c.type & 4 ? 6 : 7;
  return [kind, -(c.level & 255), code];
}
async function sortDeck() {
  if (app.busy) return;
  const sorted = Object.fromEntries(zones.map(zone => [zone, [...app.deck[zone]].sort((a,b) => {
    const ka = sortKey(a), kb = sortKey(b);
    return ka[0] - kb[0] || ka[1] - kb[1] || ka[2] - kb[2];
  })]));
  if (JSON.stringify(sorted) === JSON.stringify(app.deck)) return notice('当前构筑已按类型、等级和卡号排列。');
  rememberDeck();
  app.deck = sorted;
  dirty();
  await renderDeck();
}
function zoneStats(zone) {
  const kinds = zone === 'extra' ? [['融合',0x40,'fusion'],['同调',0x2000,'synchro'],['超量',0x800000,'xyz'],['连接',0x4000000,'link']] : [['怪兽',1,'monster'],['魔法',2,'spell'],['陷阱',4,'trap']];
  return kinds.map(([label,mask,kind]) => {
    const count = app.deck[zone].filter(code => (app.cache.get(code)?.type || 0) & mask).length;
    return `<span class="type-count ${kind}" title="${label} ${count} 张"><i></i><span>${label}</span> ${count}</span>`;
  }).join('');
}
async function renderDeck() {
  const generation = ++app.renderGeneration;
  const items = [...new Set(zones.flatMap(zone => app.deck[zone]))];
  await Promise.all(items.map(code => card(code).catch(() => {})));
  if (generation !== app.renderGeneration) return;
  const focused = document.activeElement?.closest('.deck-grid [data-detail]');
  const focusZone = focused?.dataset.from, focusIndex = Number(focused?.dataset.index);
  for (const zone of zones) {
    const codes = app.deck[zone], grid = $(`#cards-${zone}`);
    $(`#count-${zone}`).textContent = codes.length;
    $(`#stats-${zone}`).innerHTML = zoneStats(zone);
    grid.style.setProperty('--columns', zone === 'main' ? Math.max(10, Math.ceil(codes.length / 4)) : Math.max(10, codes.length));
    grid.innerHTML = codes.map((code,index) => {
      const c = app.cache.get(code) || {name:`未知卡牌 ${code}`};
      return `<button class="card-tile deck-card" data-detail="${code}" data-from="${zone}" data-index="${index}" aria-label="${escape(zoneNames[zone])}第 ${index+1} 张：${escape(c.name)}" title="${escape(c.name)} · 右键移除一张"><img src="/pics/${code}.jpg" alt="" draggable="false"></button>`;
    }).join('') || `<div class="zone-empty"><span>＋</span>尚未加入${zoneNames[zone]}${zone === 'main' ? '<small>从右侧卡牌库选择卡牌</small>' : ''}</div>`;
  }
  $('#deck-total').textContent = `${zones.reduce((sum,zone) => sum + app.deck[zone].length, 0)} 张`;
  fitDeckGrid();
  updateSelection();
  updateDetailCounts();
  updateStart();
  if (focused && app.deck[focusZone]?.length) $(`#cards-${focusZone} [data-index="${Math.min(focusIndex, app.deck[focusZone].length-1)}"]`)?.focus({preventScroll:true});
}
function fitDeckGrid() {
  const board = $('#deck-cards');
  if (!board.clientHeight) return;
  const columns = Math.max(3, Math.floor((board.clientWidth - 28) / 66));
  for (const zone of zones) $(`#cards-${zone}`).style.setProperty('--columns', columns);
}
function updateSelection() {
  document.querySelectorAll('.card-tile[data-detail]').forEach(tile => {
    const selected = Number(tile.dataset.detail) === app.selected;
    tile.classList.toggle('is-selected', selected);
    tile.setAttribute('aria-pressed', String(selected));
  });
}
function cardType(c) {
  if (!(c.type & 1)) return c.type & 2 ? '魔法卡' : c.type & 4 ? '陷阱卡' : '未知类型';
  const flags = [[0x40,'融合'],[0x2000,'同调'],[0x800000,'超量'],[0x4000000,'连接'],[0x1000000,'灵摆'],[0x80,'仪式'],[0x1000,'调整'],[0x20,'效果'],[0x10,'通常'],[0x4000,'衍生物']];
  return [...flags.filter(([flag]) => c.type & flag).map(([,label]) => label), '怪兽'].join(' / ');
}
function updateDetailCounts() {
  if (!app.selected) return;
  const c = app.cache.get(app.selected);
  for (const zone of zones) {
    const count = app.deck[zone].filter(code => code === app.selected).length;
    const label = $(`#detail-count-${zone}`);
    if (label) label.textContent = count;
    const add = $(`#card-detail [data-to="${zone}"]`), remove = $(`#card-detail [data-from="${zone}"]`);
    if (add) add.disabled = app.busy || !!(c?.type & 0x4000) || (zone !== 'side' && !!c?.extra !== (zone === 'extra')) || app.deck[zone].length >= zoneLimits[zone];
    if (remove) remove.disabled = app.busy || count === 0;
  }
  const target = app.targetZone || (c?.extra ? 'extra' : 'main');
  const quantity = app.deck[target].filter(code => code === app.selected).length;
  if ($('#selected-zone-count')) $('#selected-zone-count').textContent = `${zoneNames[target]}中已有 ${quantity} 张`;
}
async function showCard(code, sourceZone) {
  const generation = ++app.detailGeneration;
  const c = await card(code);
  if (generation !== app.detailGeneration) return;
  app.selected = code;
  app.targetZone = zones.includes(sourceZone) ? sourceZone : c.extra ? 'extra' : 'main';
  const monster = c.type & 1;
  const stat = value => value === undefined || value < 0 ? '?' : value;
  const attribute = ({1:'地',2:'水',4:'炎',8:'风',16:'光',32:'暗',64:'神'})[c.attribute] || '';
  $('#card-detail').innerHTML = `
    <div class="detail-top"><img class="hero" src="/pics/${code}.jpg" alt="${escape(c.name)}卡图"><div class="card-meta">
      <span class="attribute">${escape(attribute || (c.type & 2 ? '魔法' : c.type & 4 ? '陷阱' : '卡牌'))}</span>
      ${monster ? `<dl><dt>${c.type & 0x4000000 ? 'LINK' : c.type & 0x800000 ? '阶级' : '等级'}</dt><dd>${c.level & 255}</dd><dt>ATK</dt><dd>${stat(c.atk)}</dd>${c.type & 0x4000000 ? '' : `<dt>DEF</dt><dd>${stat(c.def)}</dd>`}</dl>` : ''}
      <small>${String(code).padStart(8,'0')}</small></div></div>
    <h3 class="detail-name">${escape(c.name)}</h3>
    <div class="card-type">${escape(cardType(c))}${monster && typeof cardRaces !== 'undefined' && cardRaces.some((_,i)=>c.race === 2**i) ? ` · ${cardRaces.find((_,i)=>c.race === 2**i)}族` : ''}</div>
    <div class="effect" tabindex="0" aria-label="卡片效果">${escape(c.desc || '无效果说明')}</div>
    <div class="detail-actions"><button id="favorite-card" aria-pressed="false">☆ 收藏卡牌</button>${c.type & 0x4000 ? '<p class="token-hint">衍生物仅供查看，不能加入构筑。</p>' : ''}<label class="target-zone">操作分区<select id="selected-zone">${zones.map(zone => `<option value="${zone}" ${app.targetZone === zone ? 'selected' : ''}>${zoneNames[zone]}</option>`).join('')}</select></label><small id="selected-zone-count"></small><div class="quantity-control"><button data-add="${code}" data-to="${app.targetZone}">增加一张</button><button data-remove="${code}" data-from="${app.targetZone}">减少一张</button></div></div>`;
  updateFavoriteButton();
  updateSelection();
  updateDetailCounts();
}
async function search() {
  const generation = ++app.searchGeneration;
  const offset = app.offset;
  $('#search-results').setAttribute('aria-busy', 'true');
  $('#search-count').textContent = '搜索中…';
  $('#prev-page').disabled = $('#next-page').disabled = true;
  try {
    const result = await api(`/api/cards?q=${encodeURIComponent($('#search').value)}&scope=name&kind=${$('#filter').value}&offset=${offset}&favorites=${app.libraryTab === 'favorites' ? '1' : '0'}&attribute=${$('#filter-attribute').value}&race=${$('#filter-race').value}&level=${$('#filter-level').value}`);
    if (generation !== app.searchGeneration) return;
    app.total = result.total;
    result.cards.forEach(c => app.cache.set(c.id, c));
    $('#search-count').textContent = `${result.total.toLocaleString()} 张`;
    $('#search-results').innerHTML = result.cards.map(c => `<button class="card-tile" data-detail="${c.id}" data-library="true" title="${escape(c.name)} · 双击加入${c.extra ? '额外卡组' : '主卡组'}" aria-label="查看${escape(c.name)}"><img loading="lazy" src="/pics/${c.id}.jpg" alt="" draggable="false"><span>${escape(c.name)}</span></button>`).join('') || '<div class="search-empty"><strong>未找到符合条件的卡牌</strong><p>试试更短的关键词，或切换卡牌类型。</p></div>';
    $('#search-results').scrollTop = 0;
    $('#prev-page').disabled = offset === 0;
    $('#next-page').disabled = offset + 60 >= app.total;
    $('#page-number').textContent = `${Math.floor(offset/60)+1} / ${Math.max(1,Math.ceil(app.total/60))}`;
    updateSelection();
  } catch (e) {
    if (generation !== app.searchGeneration) return;
    $('#search-count').textContent = '搜索失败';
    $('#search-results').innerHTML = '<div class="search-empty"><strong>暂时无法读取卡牌</strong><p>请点击“搜索”重试。</p></div>';
    $('#page-number').textContent = '—';
    throw e;
  } finally {
    if (generation === app.searchGeneration) $('#search-results').setAttribute('aria-busy', 'false');
  }
}
async function previewYdk(text) {
  if (typeof text !== 'string') throw new Error('请提供 YDK 文件的文本内容。');
  if (new TextEncoder().encode(text).length > 32 * 1024) throw new Error('YDK 文件不能超过 32 KB。');
  const lines = text.replace(/^\ufeff/, '').split(/\r\n|\n|\r/);
  if (lines.at(-1) === '') lines.pop();
  if (lines.length > 1000) throw new Error('YDK 文件行数过多，最多支持 1000 行。');
  const deck = {main:[],extra:[],side:[]}, errors = [], warnings = [], entries = [], seen = new Set();
  const markers = {'#main':'main','#extra':'extra','!side':'side'};
  let zone = null;
  lines.forEach((raw,index) => {
    const line = raw.trim(), number = index + 1, marker = line.toLowerCase();
    if (!line) return;
    if (Object.hasOwn(markers, marker)) {
      zone = markers[marker];
      if (seen.has(zone)) errors.push(`第 ${number} 行：${zoneNames[zone]}的分区标记重复，请只导入一副卡组。`);
      seen.add(zone);
      return;
    }
    if (['#side','!main','!extra'].includes(marker)) return errors.push(`第 ${number} 行：分区标记无效，请使用 #main、#extra 和 !side。`);
    if (line.startsWith('#')) return;
    if (!zone) return errors.push(`第 ${number} 行：卡号前缺少 #main、#extra 或 !side 分区标记。`);
    if (!/^[0-9]{1,10}$/.test(line) || Number(line) <= 0 || Number(line) > 0xffffffff) return errors.push(`第 ${number} 行：需要有效的数字卡号，不能使用卡名、数量写法或网页链接。`);
    const code = Number(line);
    deck[zone].push(code);
    entries.push({code,zone,number});
  });
  if (!seen.has('main')) errors.unshift('未找到 #main 分区标记。请选择 .ydk 文件，或粘贴完整的 YDK 内容。');
  if (!entries.length) errors.push('文件中没有可识别的卡牌。');
  for (const zone of zones) if (deck[zone].length > zoneLimits[zone]) errors.push(`${zoneNames[zone]}有 ${deck[zone].length} 张，超过 ${zoneLimits[zone]} 张上限，请修正后重新解析。`);
  const codes = [...new Set(entries.map(entry => entry.code))], catalog = new Map();
  // Limit concurrent local lookups for large or malformed files.
  let cursor = 0;
  await Promise.all(Array.from({length:Math.min(8,codes.length)}, async () => {
    while (cursor < codes.length) {
      const code = codes[cursor++];
      try { catalog.set(code, await card(code)); }
      catch (e) {
        if (e.status === 400) catalog.set(code, null);
        else throw new Error('暂时无法读取本地卡牌资料，请确认服务正常后重新解析。');
      }
    }
  }));
  for (const {code,zone,number} of entries) {
    const c = catalog.get(code);
    if (!c) errors.push(`第 ${number} 行：本地数据库找不到卡号 ${code}，请核对卡号或卡牌资源。`);
    else if (c.type & 0x4000) errors.push(`第 ${number} 行：${c.name}是衍生物，不能加入构筑。`);
    else if (zone !== 'side' && !!c.extra !== (zone === 'extra')) errors.push(`第 ${number} 行：${c.name}的分区不正确，应放在 ${c.extra ? '#extra' : '#main'} 下。`);
  }
  if (deck.main.length < 40) warnings.push(`主卡组目前 ${deck.main.length} 张，可以先导入编辑；开始训练需要 40–60 张。`);
  const missingScripts = new Set([...deck.main,...deck.extra].filter(code => {
    const c = catalog.get(code);
    return c && !(c.type & 0x10) && !c.script_available;
  }));
  if (missingScripts.size) warnings.push(`${missingScripts.size} 种卡牌缺少本地效果脚本，可以导入编辑，补齐脚本后才能训练。`);
  const cards = Object.fromEntries(zones.map(zone => {
    const quantities = new Map();
    deck[zone].forEach(code => quantities.set(code, (quantities.get(code) || 0) + 1));
    return [zone, [...quantities].map(([code,quantity]) => ({id:code, name:catalog.get(code)?.name || `未知卡牌 ${code}`, quantity}))];
  }));
  return {format:'YDK',deck,cards,counts:Object.fromEntries(zones.map(zone => [zone,deck[zone].length])),errors,warnings,can_import:errors.length === 0};
}
function setImportBusy(busy) {
  importState.busy = busy;
  $('#import-preview').disabled = busy || !$('#import-text').value.trim();
  $('#import-apply').disabled = app.busy || busy || (importState.mode !== 'blank' && !importState.preview?.can_import);
  for (const id of ['import-file','import-text','import-name','import-close','import-cancel','create-blank-mode','create-import-mode']) $(`#${id}`).disabled = app.busy || importState.creating;
}
function invalidateImport(message = '内容已修改，请点击“解析内容”重新检查。') {
  ++importState.generation;
  importState.preview = null;
  importState.text = '';
  $('#import-result').innerHTML = '';
  $('#import-status').classList.remove('has-errors');
  $('#import-status').textContent = message;
  setImportBusy(false);
}
function openImport() { openCreateDeck('import'); }
function importError(message) {
  importState.preview = null;
  $('#import-result').innerHTML = '';
  $('#import-status').classList.add('has-errors');
  $('#import-status').textContent = message;
  setImportBusy(false);
}
async function loadYdkFile(file) {
  if (app.busy || !file) return;
  invalidateImport('正在读取文件…');
  const generation = importState.generation;
  $('#import-file-info').textContent = file.name;
  if (!/\.ydk$/i.test(file.name)) return importError('请选择 .ydk 卡组文件。卡组截图、压缩包和网页链接不能作为 YDK 文件导入。');
  if (file.size > 32 * 1024) return importError('YDK 文件不能超过 32 KB。');
  setImportBusy(true);
  try {
    const text = await file.text();
    if (generation !== importState.generation || !$('#import-dialog').open) return;
    $('#import-text').value = text;
    if (!$('#import-name').value.trim()) $('#import-name').value = file.name.replace(/\.ydk$/i, '').slice(0,80) || '导入构筑';
    await previewImport();
  } catch (e) {
    if (generation === importState.generation) importError(`无法读取文件：${e.message}`);
  }
}
async function previewImport() {
  if (app.busy) return;
  invalidateImport('正在识别卡牌与分区…');
  const generation = importState.generation;
  const text = $('#import-text').value;
  if (!text.trim()) return importError('请先选择 YDK 文件，或粘贴文件内容。');
  if (new TextEncoder().encode(text).length > 32 * 1024) return importError('YDK 内容不能超过 32 KB。');
  setImportBusy(true);
  try {
    const result = await previewYdk(text);
    if (generation !== importState.generation || !$('#import-dialog').open) return;
    importState.preview = result;
    importState.text = text;
    $('#import-status').textContent = result.can_import ? 'YDK 已解析，可以整副导入。' : `检测到 ${result.errors.length} 处问题，修正后再导入。`;
    $('#import-status').classList.toggle('has-errors', !result.can_import);
    $('#import-result').innerHTML = `
      <div class="import-counts">${zones.map(zone => `<span>${zoneNames[zone]} <b>${result.counts[zone]}</b> 张</span>`).join('')}</div>
      ${result.errors.length ? `<ul class="import-errors">${result.errors.map(message => `<li>${escape(message)}</li>`).join('')}</ul>` : ''}
      ${result.warnings.length ? `<ul class="import-warnings">${result.warnings.map(message => `<li>${escape(message)}</li>`).join('')}</ul>` : ''}
      <div class="import-cards">${zones.map(zone => `<section><h3>${zoneNames[zone]}</h3><ul>${result.cards[zone].map(c => `<li><span>${escape(c.name)}<small>${String(c.id).padStart(8,'0')}</small></span><b>×${c.quantity}</b></li>`).join('') || '<li class="import-zone-empty">空</li>'}</ul></section>`).join('')}</div>`;
  } catch (e) {
    if (generation === importState.generation) importError(e.message);
  } finally {
    if (generation === importState.generation) setImportBusy(false);
  }
}
async function applyImportedDeck() {
  const preview = importState.preview;
  if (app.busy || importState.busy || !preview?.can_import) return;
  if (importState.text !== $('#import-text').value) return invalidateImport();
  if (!await allowDeckReplacement()) return;
  if (app.busy) return;
  const generation = importState.generation;
  app.busy = true;
  updateStart();
  setImportBusy(true);
  try {
    const decks = await api('/api/decks');
    if (generation !== importState.generation || !$('#import-dialog').open) return;
    const name = $('#import-name').value.trim();
    validateNewDeckName(name, decks);
    ++app.deckEpoch;
    app.deck = structuredClone(preview.deck);
    setDeckTags();
    app.id = null;
    app.revision = null;
    app.undo = [];
    app.selected = null;
    ++app.detailGeneration;
    app.savedState = null;
    $('#deck-name').value = name;
    dirty();
    setDeckPage('editor');
    switchView('decks');
    await renderDeck();
    $('#deck-cards').scrollTop = 0;
    const first = zones.flatMap(zone => app.deck[zone])[0];
    if (first) await showCard(first);
    $('#import-dialog').close();
    notice(`已导入“${name}”，点击“保存构筑”保存为新构筑。`);
  } catch (e) {
    importError(e.message);
  } finally { app.busy = false; updateStart(); updateDetailCounts(); setImportBusy(false); }
}
async function saveDeck() {
  if (activeDesignDeckEdit()) return finishDesignDeckEdit(true);
  if (app.busy) return;
  let name = $('#deck-name').value.trim();
  if (app.id?.startsWith('existing/') && name === (app.sourceName || app.id.split('/').at(-1).replace(/\.ydk$/,''))) name += ' - 练习';
  $('#deck-name').value = name;
  const savedState = deckState();
  const body = {name, deck:structuredClone(app.deck), id:app.id, revision:app.revision, tag_selection:structuredClone(app.deckTags)};
  app.busy = true;
  updateStart();
  updateDetailCounts();
  try {
    const saved = await api('/api/decks', body);
    app.id = saved.id;
    app.revision = saved.revision;
    app.sourceName = saved.name || name;
    if (saved.tag_names) app.deckTagNames = saved.tag_names;
    app.savedState = savedState;
    dirty();
    await deckList();
    notice('构筑已保存。');
  } finally { app.busy = false; dirty(); updateDetailCounts(); }
}
async function refreshHistory(){
  const previous=app.active;
  const generation=app.historyGeneration=(app.historyGeneration||0)+1;
  const history=await api('/api/history');
  if(generation!==app.historyGeneration)return;
  app.history=history;
  app.active=app.history.find(h=>['running','starting','stopping'].includes(h.status))||null;
  if(typeof resetTimelineSession==='function')resetTimelineSession(app.active?.id || null);
  $('#history-count').textContent=app.history.filter(h=>h.plan_stage==='draft').length||'';
  $('#active-training').hidden=!app.active || (typeof moduleUI !== 'undefined' && moduleUI.current !== 'expansion');
  if(app.active){$('#active-title').textContent=`${app.active.name} · ${statusNames[app.active.status]}`;$('#active-info').textContent=`${dt(app.active.started_ms)} 开始 · 过程正在记录，尚未保存为方案。`;}
  updateStart();
  const historyKey=JSON.stringify(app.history);
  if(app.historyKey!==historyKey){
    app.historyKey=historyKey;
    $('#history-list').innerHTML=app.history.map(h=>`<button class="history-item ${h.id===app.reportId?'current':''}" data-report="${h.id}"><strong>${escape(h.name)}</strong><small>${escape(h.deck_name || '原训练历史')}</small><small>${dt(h.started_ms)}</small><span class="badge ${h.status==='interrupted'?'warning':''}">${escape(typeof stageNames!=='undefined'&&stageNames[h.plan_stage] || statusNames[h.status] || h.status)}</span></button>`).join('')||'<div class="empty">还没有展开记录<br><small>保存牌组后进入方案前置设计。</small></div>';
  }
  if(typeof flow!=='undefined' && flow.restarting)return;
    if(previous&&!app.active){
      if(previous.compromise && typeof returnFromBranch==='function')await returnFromBranch(previous.compromise);
      else {await showReport(previous.id);notice(previous.plan_stage?'本次展开已保留为待确认草稿，请检查后点击“保存方案”。':'历史记录已保留。');}
    }
  else if(app.reportId && !$('#history').hidden && app.reportId===app.active?.id){await showReport(app.reportId,false);}
}
function cardsHtml(cards){return `<div class="report-cards">${cards.map(c=>`<div class="mini-card"><img src="/pics/${c.code}.jpg" alt="${escape(c.name)}"><small>${escape(c.name)}<br>#${c.instance_id??'未知'}</small></div>`).join('')}</div>`;}
function loc(l) {
  if (!l) return '未知区域';
  const side = l.controller === 0 ? '我方' : l.controller === 1 ? '对手' : '未知方';
  if (l.location & 128) return side + '叠放素材';
  if (l.location === 4) return side + (l.sequence >= 5 ? `额外怪兽区 ${l.sequence - 4}` : `主怪兽区 ${l.sequence + 1}`);
  return side + (zoneNames[l.location] || '未知区域') + (l.location === 8 ? ` ${l.sequence + 1}` : '');
}

function positions(v){return ({1:'攻击表示',2:'里侧攻击表示',4:'守备表示',8:'里侧守备表示'})[v]||'表示未知';}
function eventSummary(e){const names=e.cards.map(c=>c.name||String(c.code||'未知')).join('、');let text=names;if(e.origin)text+=`　${loc(e.origin)} → ${loc(e.destination)}`;if(e.cost)text+=`　费用：${e.cost.lp!==undefined?`${e.cost.lp} LP`:'引擎标记 COST'}`;if(e.chain)text+=`　连锁 ${e.chain}`;if(e.message===41)text+=`　${({1:'抽卡阶段',2:'准备阶段',4:'主要阶段 1',8:'战斗开始',128:'战斗结束',256:'主要阶段 2',512:'结束阶段'})[e.value]||e.value}`;if(e.amount!==undefined)text+=`　${e.player===0?'我方':'占位方'} ${e.amount} LP`;if(e.result)text+=`　${e.result}`;return text||'具体内容见原始事件；未提供的语义为未知。';}
async function showReport(id, navigate = true) {
  if (typeof allowReportChange === 'function' && !await allowReportChange(id)) return;
  app.reportId = id;
  const r = await api(`/api/report/${id}`);
  if (app.reportId !== id) return;
  if (navigate) switchView('history');
  if (typeof prepareDraft === 'function') prepareDraft(r);
  if (typeof mountReview === 'function') {
    document.querySelectorAll('[data-report]').forEach(b => b.classList.toggle('current', b.dataset.report === id));
    return;
  }
  const renderKey = `${id}:${r.report_version}:${r.record_count}:${r.status}:${r.plan_stage}:${app.allEvents}`;
  if (app.reportKey !== renderKey) {
    app.reportKey = renderKey;
    $('#report').innerHTML = (typeof expansionSummary === 'function' ? expansionSummary(r) : '') + renderTrainingReport(r, {raw: app.allEvents});
    $('#all-events').onchange = run(async e => {
      app.allEvents = e.target.checked;
      await showReport(id, false);
    });
  }
  document.querySelectorAll('[data-report]').forEach(b => b.classList.toggle('current', b.dataset.report === id));
}

document.addEventListener('click', run(async e => {
  const b = e.target.closest('button');
  if (!b || b.disabled) return;
  if (b.dataset.openImport) return openImport();
  if (b.dataset.detail) return showCard(Number(b.dataset.detail), b.dataset.from);
  if (b.dataset.add) return addCard(Number(b.dataset.add), b.dataset.to);
  if (b.dataset.remove) return removeCard(Number(b.dataset.remove), b.dataset.from);
  if (b.dataset.report) return showReport(b.dataset.report);
}));
document.addEventListener('dblclick', run(async e => {
  const tile = e.target.closest('[data-library][data-detail]');
  if (tile) await addCard(Number(tile.dataset.detail));
}));
document.addEventListener('contextmenu', run(async e => {
  const tile = e.target.closest('.deck-card[data-detail]');
  if (!tile) return;
  e.preventDefault();
  await removeCard(Number(tile.dataset.detail), tile.dataset.from, Number(tile.dataset.index));
}));
document.addEventListener('keydown', run(async e => {
  if ($('#editor').hidden || $('#deck-workbench').hidden || document.querySelector('dialog[open]') || e.target.closest('input,select,textarea,[contenteditable="true"]')) return;
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
    e.preventDefault();
    await undoDeck();
  }
}));
$('#nav-decks').onclick=run(async()=>{switchView('decks');await deckList();});$('#nav-history').onclick=run(async()=>{switchView('history');await refreshHistory();});
$('#save-deck').onclick=run(saveDeck);$('#deck-name').oninput=dirty;
$('#undo-deck').onclick = run(undoDeck);
$('#sort-deck').onclick = run(sortDeck);
$('#import-file').onchange = run(async e => {
  const file = e.target.files[0];
  e.target.value = '';
  await loadYdkFile(file);
});
$('#import-text').oninput = () => {
  $('#import-file-info').textContent = '当前使用粘贴的 YDK 内容。';
  invalidateImport();
};
$('#import-preview').onclick = run(previewImport);
$('#import-apply').onclick = run(createDeckFromDialog);
$('#import-close').onclick = $('#import-cancel').onclick = () => $('#import-dialog').close();
$('#import-dialog').onclose = () => invalidateImport('选择文件或点击“解析内容”重新检查。');
$('#import-dialog').oncancel = e => { if (app.busy || importState.creating) e.preventDefault(); };
document.addEventListener('dragover', e => {
  if (!$('#editor').hidden && Array.from(e.dataTransfer?.types || []).includes('Files')) e.preventDefault();
});
document.addEventListener('drop', run(async e => {
  if ($('#editor').hidden || !Array.from(e.dataTransfer?.types || []).includes('Files')) return;
  e.preventDefault();
  if (app.busy) return;
  openImport();
  if (e.dataTransfer.files.length !== 1) {
    invalidateImport();
    return importError('请一次拖入一个 YDK 文件，避免混合多副卡组。');
  }
  await loadYdkFile(e.dataTransfer.files[0]);
}));
let searchTimer;
function submitSearch() { clearTimeout(searchTimer); app.offset = 0; return search(); }
$('#search').oninput = () => {
  clearTimeout(searchTimer);
  ++app.searchGeneration;
  app.offset = 0;
  $('#search-results').setAttribute('aria-busy', 'true');
  $('#search-count').textContent = '搜索中…';
  $('#prev-page').disabled = $('#next-page').disabled = true;
  searchTimer = setTimeout(run(search), 200);
};
$('#search').onkeydown = run(async e => { if (e.key === 'Enter') { e.preventDefault(); await submitSearch(); } });
$('#search-button').onclick = run(submitSearch);
$('#filter').onchange = run(submitSearch);
$('#prev-page').onclick = run(async () => { app.offset = Math.max(0, app.offset-60); await search(); });
$('#next-page').onclick = run(async () => { app.offset += 60; await search(); });
$('#end-training').onclick=run(async()=>{if(!app.active)return;await api('/api/stop',{id:app.active.id});await refreshHistory();});$('#view-live').onclick=run(()=>showReport(app.active.id));$('#refresh-history').onclick=run(refreshHistory);
window.addEventListener('beforeunload',e=>{if(typeof unsavedSummary==='function'?unsavedSummary():app.dirty){e.preventDefault();e.returnValue='';}});
new ResizeObserver(fitDeckGrid).observe($('#deck-cards'));
run(async()=>{app.savedState=deckState();const data=await api('/api/bootstrap');app.token=data.token;$('#resource-count').textContent=`${data.cards.toLocaleString()} 张卡牌`;await initDeckManager().catch(e=>notice(e.message));await Promise.all([deckList(),search(),refreshHistory(),renderDeck()]);updateStart();setInterval(()=>{if(typeof flow!=='undefined'&&flow.busy)return;refreshHistory().catch(()=>{});},1500);})();

$('#nav-training').onclick = () => {switchView('training');if(app.active && window.trainerDesktop)void waitNativeFrame(app.active.id).catch(e=>notice(e.message));};
$('#training-report').onclick = run(() => app.active && showReport(app.active.id));
$('#finish-training').onclick = run(async () => {if(app.active){await api('/api/stop',{id:app.active.id});await refreshHistory();}});
new ResizeObserver(() => {void syncNativeHost().catch(() => {});}).observe($('#native-stage'));
window.addEventListener('resize', () => {void syncNativeHost().catch(() => {});});
new ResizeObserver(([entry]) => {
  if (typeof updateShellHeight === 'function') updateShellHeight();
  else document.documentElement.style.setProperty('--app-bar-height', `${entry.target.getBoundingClientRect().height}px`);
}).observe($('.app-bar'));
