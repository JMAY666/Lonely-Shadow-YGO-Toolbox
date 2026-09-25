'use strict';

const deckManager = {decks:[], listGeneration:0, previewGeneration:0, previewScroll:0, anchor:null, closeTimer:null, leaving:null, menuId:null, menuAnchor:null, menuPoint:null, menuScroll:0, renameTarget:null};
const favoriteUI = {cards:new Set(), ready:false, busy:false};
const cardAttributes = {1:'地',2:'水',4:'炎',8:'风',16:'光',32:'暗',64:'神'};
const cardRaces = ['战士','魔法使','天使','恶魔','不死','机械','水','炎','岩石','鸟兽','植物','昆虫','雷','龙','兽','兽战士','恐龙','鱼','海龙','爬虫类','念动力','幻神兽','创造神','幻龙','电子界','幻想魔'];

function setDeckPage(page) {
  app.deckPage = page;
  $('#deck-manager').hidden = page !== 'manager';
  $('#deck-workbench').hidden = page !== 'editor';
  const backLabel = activeDesignDeckEdit() ? '选择其他卡组' : '返回卡组管理';
  $('#back-to-decks').title = backLabel;
  $('#back-to-decks').setAttribute('aria-label', backLabel);
  closeDeckPreview();
  closeDeckMenu();
}
function renderDeckBoxes(decks) {
  deckManager.decks = decks;
  closeDeckPreview();
  closeDeckMenu();
  $('#deck-list-count').textContent = `${decks.length} 副`;
  $('#deck-boxes').innerHTML = '<button class="deck-box new-deck-box" data-create-deck="true"><span class="deck-plus" aria-hidden="true">＋</span><strong>新建卡组</strong><small>空白卡组 / 导入 YDK</small></button>' + decks.map(d => `
    <article class="deck-box-item"><button class="deck-box" data-open-deck="${escape(d.id)}" aria-label="编辑卡组：${escape(d.name)}">
      ${deckBoxArt(d)}<strong>${escape(d.name)}</strong>
    </button><button class="deck-box-menu" data-deck-menu="${escape(d.id)}" aria-label="卡组操作：${escape(d.name)}" title="卡组操作" aria-haspopup="menu">···</button></article>`).join('');
}
function closeDeckPreview() {
  ++deckManager.previewGeneration;
  clearTimeout(deckManager.closeTimer);
  deckManager.anchor = null;
  $('#deck-preview').hidden = true;
}
function delayCloseDeckPreview() {
  clearTimeout(deckManager.closeTimer);
  deckManager.closeTimer = setTimeout(closeDeckPreview, 220);
}
function positionDeckPreview() {
  const preview = $('#deck-preview'), anchor = deckManager.anchor;
  if (!anchor || preview.hidden || !anchor.isConnected || !anchor.getClientRects().length) return closeDeckPreview();
  const box = anchor.getBoundingClientRect(), width = preview.offsetWidth, height = preview.offsetHeight;
  let left = box.right + 10;
  if (left + width > window.innerWidth - 12) left = box.left - width - 10;
  left = Math.max(12, Math.min(left, window.innerWidth - width - 12));
  preview.style.left = `${left}px`;
  preview.style.top = `${Math.max(12, Math.min(box.top, window.innerHeight - height - 12))}px`;
}
async function showDeckPreview(anchor) {
  if (deckManager.menuId) return;
  clearTimeout(deckManager.closeTimer);
  if (deckManager.anchor === anchor) return;
  const generation = ++deckManager.previewGeneration, preview = $('#deck-preview');
  deckManager.anchor = anchor;
  deckManager.previewScroll = $('#deck-manager').scrollTop;
  preview.innerHTML = '<p>正在读取已保存卡组…</p>';
  preview.hidden = false;
  positionDeckPreview();
  try {
    // Read the saved deck each time, never the unsaved editor buffer.
    const saved = await api(`/api/deck?id=${encodeURIComponent(anchor.dataset.openDeck || anchor.dataset.selectDeck || anchor.dataset.duelDeck)}`);
    const codes = [...new Set(zones.flatMap(zone => saved.deck[zone]))];
    await Promise.all(codes.map(code => card(code).catch(() => {})));
    if (generation !== deckManager.previewGeneration) return;
    preview.innerHTML = `<header><strong>${escape(saved.name)}</strong><small>已保存的卡组</small></header>${deckTagHtml(saved)}` + zones.map(zone => {
      const counts = new Map();
      saved.deck[zone].forEach(code => counts.set(code, (counts.get(code) || 0) + 1));
      return `<section><h3>${zoneNames[zone]} <b>${saved.deck[zone].length} 张</b></h3><div class="deck-preview-cards">${[...counts].map(([code,count]) => `<figure title="${escape(app.cache.get(code)?.name || `未知卡牌 ${code}`)} ×${count}"><img src="/pics/${code}.jpg" alt="${escape(app.cache.get(code)?.name || `卡号 ${code}`)}"><figcaption>×${count}</figcaption></figure>`).join('') || '<small>暂无卡牌</small>'}</div></section>`;
    }).join('');
  } catch (error) {
    if (generation !== deckManager.previewGeneration) return;
    preview.innerHTML = `<p>无法读取此卡组：${escape(error.message)}</p>`;
  }
  positionDeckPreview();
}
function confirmLeaveDeck() {
  if (deckManager.leaving) return deckManager.leaving;
  const dialog = $('#leave-deck-dialog'), form = dialog.querySelector('form');
  deckManager.leaving = new Promise(resolve => {
    let settled = false;
    const finish = choice => {
      if (settled) return;
      settled = true;
      form.removeEventListener('submit', submit);
      dialog.removeEventListener('cancel', cancel);
      dialog.removeEventListener('close', closed);
      if (dialog.open) dialog.close(choice);
      resolve(choice);
    };
    const submit = event => { event.preventDefault(); finish(event.submitter?.value || 'cancel'); };
    const cancel = event => { event.preventDefault(); finish('cancel'); };
    const closed = () => finish(dialog.returnValue || 'cancel');
    dialog.returnValue = 'cancel';
    form.addEventListener('submit', submit);
    dialog.addEventListener('cancel', cancel);
    dialog.addEventListener('close', closed);
    dialog.showModal();
  }).finally(() => { deckManager.leaving = null; });
  return deckManager.leaving;
}
function closeDeckMenu(focus = false) {
  const anchor = deckManager.menuAnchor;
  deckManager.menuId = deckManager.menuAnchor = null;
  $('#deck-context-menu').hidden = true;
  if (focus && anchor?.isConnected) anchor.focus({preventScroll:true});
}
function positionDeckMenu() {
  const anchor = deckManager.menuAnchor, point = deckManager.menuPoint;
  if (!anchor?.isConnected) return closeDeckMenu();
  const menu = $('#deck-context-menu'), box = anchor.getBoundingClientRect();
  menu.style.left = `${Math.max(8, Math.min(point?.x ?? box.left + 20, window.innerWidth - menu.offsetWidth - 8))}px`;
  menu.style.top = `${Math.max(8, Math.min(point?.y ?? box.top + 20, window.innerHeight - menu.offsetHeight - 8))}px`;
}
function showDeckMenu(anchor, point) {
  if (app.busy || !anchor) return;
  closeDeckPreview();
  deckManager.menuId = anchor.dataset.openDeck;
  deckManager.menuAnchor = anchor;
  deckManager.menuPoint = point || null;
  deckManager.menuScroll = $('#deck-manager').scrollTop;
  const menu = $('#deck-context-menu');
  menu.hidden = false;
  menu.querySelector('[data-deck-command="delete"]').disabled = !!activeDesignDeckEdit();
  positionDeckMenu();
  menu.querySelector('button').focus({preventScroll:true});
}
function handleDeckManagerScroll() {
  const current = $('#deck-manager').scrollTop;
  // Revealing a compact tile may queue its scroll event before pointerover.
  // Keep a preview opened at that same position; a later user scroll closes it.
  if (current !== deckManager.previewScroll) closeDeckPreview();
  else positionDeckPreview();
  if (!deckManager.menuId) return;
  // A queued scroll event from revealing the box may arrive after its context
  // menu opens. Only a subsequent, real scroll should dismiss a pointer menu.
  if (current === deckManager.menuScroll || !deckManager.menuPoint) {
    deckManager.menuScroll = current;
    positionDeckMenu();
  } else closeDeckMenu();
}
async function exportSavedDeck(id, copy = false) {
  if (app.busy) return;
  app.busy = true; updateStart();
  try {
    if (copy && window.trainerDesktop?.copyDeckCode) {
      await window.trainerDesktop.copyDeckCode(id);
    } else {
      const exported = await api(`/api/decks/export?id=${encodeURIComponent(id)}`);
      if (copy) {
        if (!navigator.clipboard?.writeText) throw new Error('当前环境无法复制到剪贴板，请使用“导出 YDK 文件”。');
        await navigator.clipboard.writeText(exported.text);
      } else {
        const blob = new Blob([exported.text], {type:'text/plain;charset=utf-8'}), url = URL.createObjectURL(blob), anchor = document.createElement('a');
        let name = exported.name.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'_').replace(/[. ]+$/,'').slice(0,70) || '卡组';
        if (/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name)) name = '卡组-' + name;
        anchor.href = url; anchor.download = name + '.ydk';
        document.body.append(anchor); anchor.click(); anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      }
    }
    notice(copy ? 'YDK 代码已复制到剪贴板。' : '已生成 YDK 文件。');
  } catch (error) {
    if (copy) throw new Error(`复制失败：${error.message}。可以改用“导出 YDK 文件”。`);
    throw error;
  } finally { app.busy = false; updateStart(); }
}
async function openDeckRename(id) {
  if (app.busy) return;
  app.busy = true; updateStart();
  try {
    const saved = await api(`/api/deck?id=${encodeURIComponent(id)}`);
    deckManager.renameTarget = saved;
    $('#rename-deck-name').value = saved.name;
    $('#rename-deck-error').textContent = '';
    $('#rename-deck-dialog').showModal();
    $('#rename-deck-name').focus();
    $('#rename-deck-name').select();
  } finally { app.busy = false; updateStart(); }
}
async function submitDeckRename() {
  if (app.busy || !deckManager.renameTarget) return;
  const saved = deckManager.renameTarget, name = $('#rename-deck-name').value.trim();
  app.busy = true; updateStart();
  for (const id of ['rename-deck-name','rename-deck-save','rename-deck-cancel']) $(`#${id}`).disabled = true;
  try {
    validateNewDeckName(name, deckManager.decks.filter(d => d.id !== saved.id));
    await api('/api/decks/rename', {id:saved.id,revision:saved.revision,name});
    deckManager.renameTarget = null;
    $('#rename-deck-dialog').close();
    notice('卡组名称已保存。');
    await deckList().catch(error => notice(`名称已保存，列表刷新失败：${error.message}。请点击刷新列表。`));
  } catch (error) { $('#rename-deck-error').textContent = error.message; }
  finally {
    app.busy = false; updateStart();
    for (const id of ['rename-deck-name','rename-deck-save','rename-deck-cancel']) $(`#${id}`).disabled = false;
  }
}
async function allowDeckReplacement() {
  if (!app.dirty) return true;
  const choice = await confirmLeaveDeck();
  if (choice === 'save') {
    // A temporary design editor saves by returning to preparation. It cannot
    // simultaneously be replaced; the user can re-enter it after applying.
    await saveDeck();
    return !app.dirty && app.view === 'decks';
  }
  return choice === 'discard';
}
async function returnToDeckManager() {
  if (app.busy) return;
  if (!await allowDeckReplacement()) return;
  if (app.busy) return;
  app.busy = true; updateStart();
  try {
  // Commit the navigation only after the list can be loaded. Failed reads keep edits.
  await deckList();
  ++app.deckEpoch; ++app.detailGeneration;
  app.deck = {main:[],extra:[],side:[]};
  setDeckTags();
  setDeckRepresentatives();
  app.id = app.revision = app.selected = null;
  app.undo = [];
  $('#deck-name').value = '新构筑';
  app.savedState = deckState();
  dirty();
  setDeckPage('manager');
  } finally { app.busy = false; updateStart(); }
}
function setCreateMode(mode) {
  importState.mode = mode;
  $('#create-import-fields').hidden = mode !== 'import';
  $('#create-blank-mode').setAttribute('aria-pressed', String(mode === 'blank'));
  $('#create-import-mode').setAttribute('aria-pressed', String(mode === 'import'));
  $('#import-result').hidden = mode !== 'import';
  $('#import-apply').textContent = mode === 'import' ? '导入并编辑' : '创建并编辑';
  $('#import-status').textContent = mode === 'blank' ? '先创建空白卡组，编辑完成后保存。' : '选择文件或粘贴完整 YDK 文本，然后解析内容。';
  setImportBusy(false);
}
function openCreateDeck(mode = 'blank') {
  if (app.busy) return;
  setCreateMode(mode);
  if (!$('#import-dialog').open) $('#import-dialog').showModal();
  $('#import-name').focus();
}
function validateNewDeckName(name, decks) {
  if (!name || name.length > 80 || /[<>:"/\\|?*\u0000-\u001f]/.test(name) || /[. ]$/.test(name) || /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name)) throw new Error('请输入有效的卡组名称（1–80 字，不含文件名禁用字符）。');
  if (decks.some(d => d.name.toLocaleLowerCase() === name.toLocaleLowerCase())) throw new Error('同名卡组已存在，请更换名称；不会覆盖已有卡组。');
}
async function createDeckFromDialog() {
  if (app.busy || importState.busy || importState.creating) return;
  if (importState.mode === 'import') return applyImportedDeck();
  importState.creating = true;
  setImportBusy(true);
  try {
    const name = $('#import-name').value.trim(), decks = await api('/api/decks');
    validateNewDeckName(name, decks);
    if (!await allowDeckReplacement()) return;
    if (!$('#import-dialog').open) return;
    app.busy = true; updateStart(); setImportBusy(true);
    ++app.deckEpoch; ++app.detailGeneration;
    app.deck = {main:[],extra:[],side:[]};
    setDeckTags();
    setDeckRepresentatives();
    app.id = app.revision = app.selected = null;
    app.undo = [];
    app.savedState = null;
    $('#deck-name').value = name;
    $('#card-detail').innerHTML = '<div class="detail-placeholder"><strong>选择一张卡牌</strong><p>从右侧卡牌库添加卡牌</p></div>';
    dirty();
    setDeckPage('editor');
    switchView('decks');
    await renderDeck();
    $('#import-dialog').close();
    notice(`已新建“${name}”，编辑完成后请保存。`);
  } catch (error) { importError(error.message); }
  finally { app.busy = false; importState.creating = false; updateStart(); setImportBusy(false); }
}
async function refreshFavorites() {
  const saved = await api('/api/card-favorites');
  favoriteUI.cards = new Set(saved.cards);
  favoriteUI.ready = true;
  updateFavoriteButton();
}
function updateFavoriteButton() {
  const button = $('#favorite-card');
  if (!button) return;
  const selected = favoriteUI.cards.has(app.selected);
  button.textContent = selected ? '★ 已收藏 · 取消收藏' : '☆ 收藏卡牌';
  button.setAttribute('aria-pressed', String(selected));
  button.disabled = !app.selected || favoriteUI.busy;
}
async function toggleFavorite() {
  if (!app.selected || favoriteUI.busy) return;
  const code = app.selected;
  favoriteUI.busy = true;
  updateFavoriteButton();
  try {
    if (!favoriteUI.ready) await refreshFavorites();
    const saved = await api('/api/card-favorites', {id:code,favorite:!favoriteUI.cards.has(code)});
    favoriteUI.cards = new Set(saved.cards);
    if (app.libraryTab === 'favorites') { app.offset = 0; await search(); }
  } finally { favoriteUI.busy = false; updateFavoriteButton(); }
}
function updateLibraryTabs() {
  for (const tab of ['all','favorites']) {
    const selected = (app.libraryTab || 'all') === tab;
    $(`#library-${tab}`).setAttribute('aria-selected', String(selected));
    $(`#library-${tab}`).tabIndex = selected ? 0 : -1;
  }
  $('#search-results').setAttribute('aria-labelledby', `library-${app.libraryTab || 'all'}`);
}
async function selectLibraryTab(tab) {
  app.libraryTab = tab;
  updateLibraryTabs();
  await submitSearch();
}
function initDeckManager() {
  $('#card-detail').onclick = run(async event => { if (event.target.closest('#favorite-card')) await toggleFavorite(); });
  $('#card-detail').onchange = event => {
    if (event.target.id !== 'selected-zone') return;
    app.targetZone = event.target.value;
    $('#card-detail [data-add]').dataset.to = app.targetZone;
    $('#card-detail [data-remove]').dataset.from = app.targetZone;
    updateDetailCounts();
  };
  $('#filter-attribute').innerHTML += Object.entries(cardAttributes).map(([code,name]) => `<option value="${code}">${name}</option>`).join('');
  $('#filter-race').innerHTML += cardRaces.map((name,index) => `<option value="${2**index}">${name}族</option>`).join('');
  $('#filter-level').innerHTML += Array.from({length:14}, (_,level) => `<option value="${level}">${level}</option>`).join('');
  $('#back-to-decks').onclick = run(returnToDeckManager);
  $('#refresh-decks').onclick = run(deckList);
  $('#create-blank-mode').onclick = () => { if (!app.busy) setCreateMode('blank'); };
  $('#create-import-mode').onclick = () => { if (!app.busy) setCreateMode('import'); };
  $('#library-all').onclick = run(() => selectLibraryTab('all'));
  $('#library-favorites').onclick = run(() => selectLibraryTab('favorites'));
  $('.library-tabs').onkeydown = run(async event => {
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
    event.preventDefault();
    const tab = event.key === 'Home' ? 'all' : event.key === 'End' ? 'favorites' : app.libraryTab === 'favorites' ? 'all' : 'favorites';
    $(`#library-${tab}`).focus(); await selectLibraryTab(tab);
  });
  for (const id of ['filter-attribute','filter-race','filter-level','filter-effect']) $(`#${id}`).onchange = run(submitSearch);
  if(typeof initCapabilityFilters==='function')void initCapabilityFilters().catch(error=>notice(error.message));
  $('#clear-search').onclick = run(async () => { $('#search').value = ''; await submitSearch(); });
  $('#reset-filters').onclick = run(async () => { for (const id of ['filter','filter-attribute','filter-race','filter-level','filter-effect']) $(`#${id}`).value = ''; await submitSearch(); });
  $('#deck-boxes').onclick = run(async event => {
    const tile = event.target.closest('button');
    if (!tile || tile.disabled) return;
    if (tile?.dataset.createDeck) openCreateDeck();
    else if (tile?.dataset.openDeck) await openDeck(tile.dataset.openDeck);
    else if (tile?.dataset.deckMenu) showDeckMenu(tile.closest('.deck-box-item').querySelector('[data-open-deck]'));
  });
  $('#deck-boxes').oncontextmenu = event => {
    const tile = event.target.closest('[data-open-deck]') || event.target.closest('.deck-box-item')?.querySelector('[data-open-deck]');
    if (!tile) return;
    event.preventDefault(); showDeckMenu(tile, {x:event.clientX,y:event.clientY});
  };
  $('#deck-boxes').onkeydown = event => {
    if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return;
    const tile = event.target.closest('.deck-box-item')?.querySelector('[data-open-deck]');
    if (tile) { event.preventDefault(); showDeckMenu(tile); }
  };
  $('#deck-context-menu').onclick = run(async event => {
    const command = event.target.closest('[data-deck-command]');
    if (!command || command.disabled) return;
    const id = deckManager.menuId;
    closeDeckMenu();
    if (!id) return;
    if (command.dataset.deckCommand === 'open') await openDeck(id);
    else if (command.dataset.deckCommand === 'rename') await openDeckRename(id);
    else if (command.dataset.deckCommand === 'copy') await exportSavedDeck(id, true);
    else if (command.dataset.deckCommand === 'export') await exportSavedDeck(id);
    else if (command.dataset.deckCommand === 'delete') await deleteDeck(id);
  });
  $('#deck-context-menu').onkeydown = event => {
    const buttons = [...$('#deck-context-menu').querySelectorAll('button:not(:disabled)')];
    const index = buttons.indexOf(document.activeElement);
    if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
      event.preventDefault();
      buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length].focus();
    }
  };
  $('#rename-deck-dialog form').onsubmit = run(async event => { event.preventDefault(); await submitDeckRename(); });
  const cancelRename = () => { deckManager.renameTarget = null; $('#rename-deck-dialog').close(); };
  $('#rename-deck-cancel').onclick = cancelRename;
  $('#rename-deck-dialog').oncancel = event => { event.preventDefault(); if (!app.busy) cancelRename(); };
  $('#deck-boxes').onpointerover = $('#deck-boxes').onfocusin = run(async event => {
    const tile = event.target.closest('[data-open-deck]');
    if (tile) await showDeckPreview(tile);
  });
  $('#deck-boxes').onpointerout = $('#deck-boxes').onfocusout = event => {
    if (deckManager.anchor?.contains(event.relatedTarget) || $('#deck-preview').contains(event.relatedTarget)) return;
    delayCloseDeckPreview();
  };
  $('#deck-preview').onpointerenter = () => clearTimeout(deckManager.closeTimer);
  $('#deck-preview').onpointerleave = delayCloseDeckPreview;
  window.addEventListener('resize', positionDeckPreview);
  window.addEventListener('resize', () => closeDeckMenu());
  document.addEventListener('scroll', event => { if (!$('#deck-preview').contains(event.target)) positionDeckPreview(); }, true);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeDeckPreview(); closeDeckMenu(true); } });
  document.addEventListener('click', event => { if (!event.target.closest('#deck-context-menu,[data-deck-menu]')) closeDeckMenu(); });
  $('#deck-manager').addEventListener('scroll', handleDeckManagerScroll);
  setDeckPage(app.deckPage || 'manager');
  return refreshFavorites();
}
