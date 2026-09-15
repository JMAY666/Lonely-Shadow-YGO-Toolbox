'use strict';

// Reading and confirming a deck never touches either editor or writes the library.
const deckSelection = {selected:null, loading:false, busy:false, generation:0, picks:new Set(), copying:false, drag:null, dragFrame:null, suppressClick:false};

function renderDeckSelectionList(decks) {
  $('#selection-count').textContent = `${decks.length} 副`;
  $('#selection-list').innerHTML = decks.map(d => `<button class="selection-deck" data-select-deck="${escape(d.id)}" title="${escape(d.name)}" aria-label="预览卡组：${escape(d.name)}"><span class="selection-deck-icon" aria-hidden="true">◇</span><span><strong>${escape(d.name)}</strong><small>${d.source === 'library' ? '我的卡组' : '已有卡组'}</small>${deckTagHtml(d)}</span><span class="selection-deck-arrow" aria-hidden="true">→</span></button>`).join('') || '<div class="selection-empty"><h2>暂无可用卡组</h2><p>请先在左侧“卡组编辑”中保存卡组，再回来选择。</p></div>';
}
function updateDeckSelectionControls() {
  const blocked = deckSelection.busy || app.busy;
  $('#selection-back').disabled = blocked;
  $('#refresh-selection').disabled = blocked;
  $('#selection-next').disabled = blocked || deckSelection.loading || !deckSelection.selected || !!app.active;
  $('#selection-next').title = app.active ? '请先结束当前展开' : '';
  const picked = selectedDeckCards();
  $('#selection-picked-count').textContent = `已标记 ${picked.length} 张`;
  $('#copy-selection-names').disabled = blocked || deckSelection.copying || !picked.length;
  $('#clear-selection-picks').disabled = blocked || !picked.length;
  $('#selection-cards').querySelectorAll('[data-selection-key]').forEach(item => {
    const marked = deckSelection.picks.has(item.dataset.selectionKey);
    item.classList.toggle('is-marked',marked);
    item.querySelector('button')?.setAttribute('aria-description',marked ? '已标记卡牌' : '未标记卡牌');
  });
  updatePreviewMarkButton();
}
function previewMarkKey() {
  const selected = typeof reviewUI === 'undefined' ? null : reviewUI.selected;
  const key = selected?.selection_key;
  if (!key || $('#deck-selection').hidden || reviewUI.detailReport?.id !== `selection:${deckSelection.selected?.id}`) return null;
  const [zone,index] = key.split(':');
  return deckSelection.selected?.deck[zone]?.[Number(index)] === selected.code ? key : null;
}
function updatePreviewMarkButton() {
  const key = previewMarkKey(), button = $('#toggle-preview-card-mark');
  button.hidden = key === null;
  button.disabled = app.busy || deckSelection.busy;
  const marked = key !== null && deckSelection.picks.has(key);
  button.textContent = marked ? '取消标记' : '添加标记';
  button.setAttribute('aria-pressed',String(marked));
}
function togglePreviewMark() {
  const key = previewMarkKey();
  if (key === null || app.busy || deckSelection.busy) return;
  if (deckSelection.picks.has(key)) deckSelection.picks.delete(key);
  else deckSelection.picks.add(key);
  updateDeckSelectionControls();
}
function selectedDeckCards() {
  if (!deckSelection.selected) return [];
  return zones.flatMap(zone => deckSelection.selected.deck[zone].flatMap((code, index) => deckSelection.picks.has(`${zone}:${index}`) ? [{code,zone}] : []));
}
function selectionMessage(message) {
  $('#selection-message').textContent = message;
  $('#selection-message').hidden = !message;
}
function backToDeckSelection() {
  if (deckSelection.busy) return;
  ++deckSelection.generation;
  closeReviewDetail();
  deckSelection.loading = false;
  $('#selection-list-page').hidden = false;
  $('#selection-preview-page').hidden = true;
  selectionMessage('');
  updateDeckSelectionControls();
  const id = deckSelection.selected?.id;
  const button = [...$('#selection-list').querySelectorAll('[data-select-deck]')].find(b => b.dataset.selectDeck === id);
  (button || $('#refresh-selection')).focus({preventScroll:true});
}
async function previewExpansionDeck(id) {
  if (deckSelection.busy || app.busy) return;
  const generation = ++deckSelection.generation;
  const previous = deckSelection.selected;
  closeReviewDetail();
  deckSelection.selected = null;
  deckSelection.loading = true;
  $('#selection-list-page').hidden = true;
  $('#selection-preview-page').hidden = false;
  $('#selection-name').textContent = '卡组预览';
  $('#selection-summary').textContent = '';
  $('#selection-cards').innerHTML = '';
  selectionMessage('正在读取卡组…');
  updateDeckSelectionControls();
  try {
    const saved = await api(`/api/deck?id=${encodeURIComponent(id)}`);
    await Promise.all([...new Set(zones.flatMap(zone => saved.deck[zone]))].map(code => card(code).catch(() => {})));
    if (generation !== deckSelection.generation) return;
    if (previous?.id !== saved.id || previous?.revision !== saved.revision) deckSelection.picks.clear();
    deckSelection.selected = saved;
    renderExpansionDeckPreview();
    selectionMessage('');
  } catch (error) {
    if (generation === deckSelection.generation) selectionMessage(`无法读取卡组：${error.message}。请返回列表重新选择。`);
  } finally {
    if (generation === deckSelection.generation) {
      deckSelection.loading = false;
      updateDeckSelectionControls();
      if (deckSelection.selected && !$('#deck-selection').hidden) $('#selection-next').focus({preventScroll:true});
    }
  }
}
function renderExpansionDeckPreview() {
  const saved = deckSelection.selected;
  closeReviewDetail();
  $('#selection-name').textContent = saved.name;
  $('#selection-summary').textContent = zones.map(zone => `${zoneNames[zone]} ${saved.deck[zone].length} 张`).join(' · ');
  $('#selection-tags').innerHTML = deckTagHtml(saved);
  const report = {id:`selection:${saved.id}`,catalog:Object.fromEntries(app.cache),events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  $('#selection-cards').innerHTML = zones.map(zone => `<section class="selection-zone" aria-label="${zoneNames[zone]}"><h2>${zoneNames[zone]} <small>${saved.deck[zone].length} 张</small></h2><div class="selection-card-grid">${saved.deck[zone].map((code, index) => {
    const name = app.cache.get(code)?.name || String(code), key = `${zone}:${index}`;
    return `<article class="selection-card-item" data-selection-key="${key}">${reviewCard({code,name,identity_known:true,selection_key:key},'catalog',{report,face:true,zone:false,position:false,catalogue:true})}</article>`;
  }).join('') || '<p>暂无卡牌</p>'}</div></section>`).join('');
  pruneReviewCards();
  updateDeckSelectionControls();
}
async function copySelectedCardNames(codes) {
  if (deckSelection.copying || !codes.length) return;
  const captured = [...codes];
  deckSelection.copying = true;
  updateDeckSelectionControls();
  if (flow.design) renderDesignCardShortcuts();
  try {
    let count;
    if (window.trainerDesktop?.copyCardNames) ({count} = await window.trainerDesktop.copyCardNames(captured));
    else {
      const names = [...new Set((await Promise.all([...new Set(captured)].map(card))).map(c => c.name))];
      if (!navigator.clipboard?.writeText) throw new Error('当前环境无法访问剪贴板');
      await navigator.clipboard.writeText(names.join(' + '));
      count = names.length;
    }
    notice(`已复制 ${count} 个卡名，可粘贴到方案名称。`);
  } catch (error) {
    notice(`复制失败：${error.message}`);
  } finally {
    deckSelection.copying = false;
    updateDeckSelectionControls();
    if (flow.design) renderDesignCardShortcuts();
  }
}
async function confirmExpansionDeck() {
  if (deckSelection.busy || deckSelection.loading || !deckSelection.selected || app.busy || app.active) return;
  deckSelection.busy = true;
  app.busy = true;
  updateStart();
  try {
    const saved = await api(`/api/deck?id=${encodeURIComponent(deckSelection.selected.id)}`);
    if ($('#deck-selection').hidden) return;
    // A library update while previewing must be seen before it is confirmed.
    if (saved.revision !== deckSelection.selected.revision) {
      await Promise.all([...new Set(zones.flatMap(zone => saved.deck[zone]))].map(code => card(code).catch(() => {})));
      deckSelection.selected = saved;
      deckSelection.picks.clear();
      renderExpansionDeckPreview();
      return selectionMessage('卡组已更新，预览已刷新。请重新标记需要的卡牌并确认。');
    }
    selectionMessage('');
    await openDesign({...saved,quick_cards:selectedDeckCards()});
  } catch (error) {
    selectionMessage(`暂时无法进入下一步：${error.message}`);
  } finally {
    deckSelection.busy = false;
    app.busy = false;
    updateStart();
  }
}

function designQuickCards() {
  const d = flow.design;
  return d ? (d.quick_cards || []).filter(c => zones.includes(c.zone) && d.deck[c.zone]?.includes(c.code)) : [];
}
function mainQuickCodes() {
  return [...new Set(designQuickCards().filter(c => c.zone === 'main').map(c => c.code))];
}
function openingShortcutError(code, slot) {
  const d = flow.design;
  if (!d || !d.name.trim()) return '请先填写方案名称';
  if (flow.busy) return '当前操作尚未完成';
  if (!mainQuickCodes().includes(code)) return '卡牌不在本次主卡组快捷候选中';
  if (slot < 0 || slot >= handCount(d)) return '起手槽位已满，可拖到指定槽位替换';
  if (d.conditions.banned.includes(code)) return '这张卡已被禁止出现在起手中';
  const used = d.conditions.slots.filter((c, index) => c === code && index !== slot).length;
  if (used >= d.deck.main.filter(c => c === code).length) return '已达到主卡组中这张卡的实际份数';
  return '';
}
function shortcutButtons(slot, attribute) {
  const d = flow.design;
  return mainQuickCodes().map(code => {
    const draggable = attribute === 'data-opening-shortcut';
    const canPlace = draggable && d.conditions.slots.slice(0,handCount(d)).some((_,index)=>!openingShortcutError(code,index));
    const error = canPlace ? '' : openingShortcutError(code,slot), used = d.conditions.slots.filter(c => c === code).length;
    return `<button type="button" ${attribute}="${code}" data-opening-draggable="${draggable && !error}" draggable="false" ${error ? 'disabled' : ''} title="${escape(error || (draggable ? '点击填入空槽位，或拖到指定槽位替换' : '填入起手槽位'))}"><img src="/pics/${code}.jpg" alt="" draggable="false"><span><strong>${escape(cardName(d,code))}</strong><small>主卡组 ${d.deck.main.filter(c => c === code).length} 张 · 已指定 ${used} 张</small></span></button>`;
  }).join('');
}
function renderDesignCardShortcuts() {
  const picked = designQuickCards(), d = flow.design;
  $('#design-card-shortcuts').hidden = !picked.length;
  $('#copy-design-card-names').disabled = !picked.length || deckSelection.copying;
  if (!d) return;
  const slot = d.conditions.slots.slice(0,handCount(d)).findIndex(code => code === null);
  $('#design-opening-shortcuts').innerHTML = shortcutButtons(slot,'data-opening-shortcut') || '<p>额外与副卡组的标记用于复制卡名；起手候选仅包含主卡组卡牌。</p>';
}
function renderOpeningShortcuts() {
  const show = flow.target === 'player' && flow.mode === 'required' && mainQuickCodes().length;
  $('#opening-shortcut-section').hidden = !show;
  $('#opening-shortcut-choices').innerHTML = show ? shortcutButtons(flow.slot,'data-shortcut-choice') : '';
}
function applyOpeningShortcut(code, targetSlot) {
  const d = flow.design;
  if (!d) return;
  const slot = targetSlot === undefined ? d.conditions.slots.slice(0,handCount(d)).findIndex(card => card === null) : targetSlot;
  if (!Number.isInteger(slot)) return;
  const error = openingShortcutError(code, slot);
  if (error) return notice(error);
  d.conditions.slots[slot] = code;
  d.startError = '';
  renderDesign();
}
function clearOpeningDrag() {
  const drag = deckSelection.drag;
  deckSelection.drag = null;
  if (deckSelection.dragFrame !== null) cancelAnimationFrame(deckSelection.dragFrame);
  deckSelection.dragFrame = null;
  $('#opening-drag-preview')?.remove();
  drag?.source.classList.remove('is-dragging');
  if (drag?.source.hasPointerCapture(drag.pointerId)) drag.source.releasePointerCapture(drag.pointerId);
  document.querySelectorAll('#opening-slots .is-drop-target,#opening-slots .is-drop-invalid').forEach(slot => slot.classList.remove('is-drop-target','is-drop-invalid'));
}
function currentOpeningDrag() {
  return deckSelection.drag?.design === flow.design ? deckSelection.drag : null;
}
function openingDropTarget(x,y) {
  const slot = document.elementFromPoint(x,y)?.closest('[data-slot]');
  return slot && $('#opening-slots').contains(slot) ? slot : null;
}
function paintOpeningDrag() {
  const drag = currentOpeningDrag();
  if (!drag?.active) return clearOpeningDrag();
  const ghost = $('#opening-drag-preview');
  ghost.style.left = `${drag.x + 12}px`; ghost.style.top = `${drag.y + 12}px`;
  const target = openingDropTarget(drag.x,drag.y);
  document.querySelectorAll('#opening-slots [data-slot]').forEach(slot => {
    const error = slot === target && openingShortcutError(drag.code,Number(slot.dataset.slot));
    slot.classList.toggle('is-drop-target',slot === target && !error);
    slot.classList.toggle('is-drop-invalid',slot === target && !!error);
  });
  // Keep lower slots reachable while a candidate is held near the viewport edge.
  if (drag.y > innerHeight - 32) window.scrollBy(0,12);
  else if (drag.y < 80) window.scrollBy(0,-12);
  deckSelection.dragFrame = requestAnimationFrame(paintOpeningDrag);
}

$('#selection-list').addEventListener('click', run(async event => {
  const button = event.target.closest('[data-select-deck]');
  if (button) await previewExpansionDeck(button.dataset.selectDeck);
}));
$('#toggle-preview-card-mark').onclick = togglePreviewMark;
$('#clear-selection-picks').onclick = () => { deckSelection.picks.clear(); updateDeckSelectionControls(); };
$('#copy-selection-names').onclick = run(() => copySelectedCardNames(selectedDeckCards().map(c => c.code)));
$('#copy-design-card-names').onclick = run(() => copySelectedCardNames(designQuickCards().map(c => c.code)));
$('#copy-preview-card-name').onclick = run(() => copySelectedCardNames(reviewUI.selected?.code ? [reviewUI.selected.code] : []));
document.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  if (button.dataset.openingShortcut) applyOpeningShortcut(Number(button.dataset.openingShortcut));
  if (button.dataset.shortcutChoice) chooseOpening(Number(button.dataset.shortcutChoice));
});
$('#design-opening-shortcuts').addEventListener('pointerdown', event => {
  const button = event.target.closest('[data-opening-shortcut]');
  if (!button || button.disabled || button.dataset.openingDraggable !== 'true' || event.button !== 0 || event.isPrimary === false) return;
  clearOpeningDrag();
  const code = Number(button.dataset.openingShortcut);
  deckSelection.drag = {code,design:flow.design,source:button,pointerId:event.pointerId,startX:event.clientX,startY:event.clientY,x:event.clientX,y:event.clientY,active:false};
  button.setPointerCapture(event.pointerId);
});
$('#design-opening-shortcuts').addEventListener('pointermove', event => {
  const drag = currentOpeningDrag();
  if (!drag || event.pointerId !== drag.pointerId) return;
  drag.x = event.clientX; drag.y = event.clientY;
  if (!drag.active && Math.hypot(drag.x-drag.startX,drag.y-drag.startY) < 6) return;
  event.preventDefault();
  if (!drag.active) {
    drag.active = true;
    drag.source.classList.add('is-dragging');
    const ghost = document.createElement('div'), art = document.createElement('img');
    ghost.id = 'opening-drag-preview'; art.src = `/pics/${drag.code}.jpg`; art.alt = '';
    ghost.append(art); document.body.append(ghost);
    paintOpeningDrag();
  }
});
$('#design-opening-shortcuts').addEventListener('pointerup', event => {
  const drag = currentOpeningDrag();
  if (!drag || event.pointerId !== drag.pointerId) return clearOpeningDrag();
  const target = drag.active ? openingDropTarget(event.clientX,event.clientY) : null;
  clearOpeningDrag();
  if (!drag.active) return;
  event.preventDefault();
  deckSelection.suppressClick = true;
  setTimeout(()=>{deckSelection.suppressClick=false;},0);
  if (target) applyOpeningShortcut(drag.code,Number(target.dataset.slot));
});
$('#design-opening-shortcuts').addEventListener('pointercancel',clearOpeningDrag);
$('#design-opening-shortcuts').addEventListener('lostpointercapture',()=>{if(deckSelection.drag)clearOpeningDrag();});
document.addEventListener('click',event=>{if(deckSelection.suppressClick){deckSelection.suppressClick=false;event.preventDefault();event.stopImmediatePropagation();}},true);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&deckSelection.drag)clearOpeningDrag();});
window.addEventListener('blur',clearOpeningDrag);
$('#selection-back').onclick = backToDeckSelection;
$('#selection-next').onclick = run(confirmExpansionDeck);
$('#refresh-selection').onclick = run(deckList);
$('#selection-list').addEventListener('pointerover', run(async e => {const tile=e.target.closest('[data-select-deck]');if(tile)await showDeckPreview(tile);}));
$('#selection-list').addEventListener('pointerout', e => {if(!deckManager.anchor?.contains(e.relatedTarget)&&!$('#deck-preview').contains(e.relatedTarget))delayCloseDeckPreview();});
// File drops in this step do not open the editor's import workflow or navigate away.
for (const event of ['dragover', 'drop']) $('#deck-selection').addEventListener(event, e => e.preventDefault());
