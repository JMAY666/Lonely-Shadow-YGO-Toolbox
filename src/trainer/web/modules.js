'use strict';

// The standalone editor and temporary preparation edits keep independent buffers.
// Expansion's first step uses a separate, read-only saved-deck selection.
const moduleUI = {current:'home', editorOwner:'decks', expansionView:'decks', switching:false, railCollapsed:false,
  editors:{decks:null, expansion:null}, scroll:{home:0,decks:0,expansion:0,duel:0,tags:0,modular:0,intelligence:0,cardanno:0}};
const editorKeys = ['deck','representatives','deckTags','deckTagNames','id','revision','sourceName','dirty','undo','savedState','selected','offset','deckPage','libraryTab','targetZone'];
const emptyDetail = $('#card-detail').innerHTML;
function captureEditor() {
  return {state:structuredClone(Object.fromEntries(editorKeys.map(key=>[key,app[key]]))),
    name:$('#deck-name').value,
    query:$('#search').value, filter:$('#filter').value, libraryOpen:!$('#card-library').hidden,
    filters:['attribute','race','level'].map(key=>$(`#filter-${key}`).value),
    detail:$('#card-detail').innerHTML, scroll:$('#deck-cards').scrollTop};
}
function emptyEditor(owner) {
  return {state:{deck:{main:[],extra:[],side:[]},id:null,revision:null,dirty:false,undo:[],selected:null,offset:0,
    deckTags:{tag_ids:[],primary_ids:[]},deckTagNames:{},representatives:[null,null,null],
    deckPage:'manager',libraryTab:'all',targetZone:'main',
    savedState:JSON.stringify({name:'新构筑',deck:{main:[],extra:[],side:[]},tags:{tag_ids:[],primary_ids:[]},representatives:[null,null,null]})},
    name:'新构筑',query:'',filter:'',libraryOpen:false,detail:emptyDetail,scroll:0};
}
function editorUnsavedSummary() {
  return ['decks','expansion'].filter(owner=>owner===moduleUI.editorOwner ? app.dirty : moduleUI.editors[owner]?.state.dirty)
    .map(owner=>`${owner==='decks'?'独立卡组编辑':'前置设计临时卡组编辑'}有未保存修改。`);
}
function updateShellHeight() {
  const height = $('.app-bar').getBoundingClientRect().height + $('#expansion-navigation').getBoundingClientRect().height;
  document.documentElement.style.setProperty('--app-bar-height', `${height}px`);
  void syncNativeHost().catch(()=>{});
}
function updateModuleChrome() {
  document.body.dataset.module = moduleUI.current;
  $('#expansion-navigation').hidden = moduleUI.current !== 'expansion';
  for (const name of ['home','decks','expansion','duel','tags','modular','intelligence','cardanno']) {
    const button = $(`#module-${name}`);
    button.classList.toggle('active', moduleUI.current===name);
    button.disabled = moduleUI.switching;
    if (moduleUI.current===name) button.setAttribute('aria-current','page');
    else button.removeAttribute('aria-current');
  }
  $('#start-training').hidden = true;
  $('#active-training').hidden = moduleUI.current !== 'expansion' || !app.active;
  $('#design-deck-edit').hidden = !activeDesignDeckEdit();
  $('#save-deck').textContent = activeDesignDeckEdit() ? '应用卡组并返回条件' : '保存构筑';
  $('#module-expansion-status').hidden = !app.active;
  updateShellHeight();
}
function toggleNavigation() {
  moduleUI.railCollapsed = !moduleUI.railCollapsed;
  document.body.classList.toggle('rail-collapsed',moduleUI.railCollapsed);
  $('#primary-navigation').hidden = moduleUI.railCollapsed;
  $('#navigation-toggle').setAttribute('aria-expanded',String(!moduleUI.railCollapsed));
  const label = moduleUI.railCollapsed ? '展开导航' : '收起导航';
  $('#navigation-toggle').setAttribute('aria-label',label);
  $('#navigation-toggle').title = label;
  updateShellHeight();
}
async function switchModule(target) {
  if (!['home','decks','expansion','duel','tags','modular','intelligence','cardanno'].includes(target) || target===moduleUI.current) return;
  if (moduleUI.switching || app.busy || flow.busy || flow.saving || flow.confirming || rewindState.busy || tagManagerUI.busy || (typeof intelUI!=='undefined'&&intelUI.busy) || (typeof annoUI!=='undefined'&&annoUI.busy) || (typeof duelUI!=='undefined'&&duelUI.busy) || document.querySelector('dialog[open]')) {
    notice('当前操作尚未完成，请完成后再切换模块。'); return;
  }
  moduleUI.switching = true;
  const previous = moduleUI.current;
  moduleUI.scroll[previous] = window.scrollY;
  const destination = ['home','tags','duel','modular','intelligence','cardanno'].includes(target) ? moduleUI.editorOwner : target;
  if (previous === 'modular') leaveModular();
  if (previous === 'duel') await leaveDuelModule();
  // Capture before hiding the drawer or invalidating any asynchronous rendering.
  if (['decks','expansion'].includes(previous)) moduleUI.editors[moduleUI.editorOwner] = captureEditor();
  app.busy = true;
  clearTimeout(searchTimer);
  ++app.deckEpoch; ++app.renderGeneration; ++app.detailGeneration; ++app.searchGeneration;
  moduleUI.current = target;
  try {
    if (destination !== moduleUI.editorOwner) {
      const buffer = moduleUI.editors[destination] || emptyEditor(destination);
      moduleUI.editorOwner = destination;
      Object.assign(app, structuredClone(buffer.state));
      $('#deck-name').value = buffer.name;
      $('#search').value = buffer.query; $('#filter').value = buffer.filter;
      ['attribute','race','level'].forEach((key,index)=>{$(`#filter-${key}`).value=buffer.filters?.[index] || '';});
      $('#card-detail').innerHTML = buffer.detail;
    }
    const view = target==='expansion' ? moduleUI.expansionView : target;
    updateModuleChrome();
    updateLibraryTabs(); updateFavoriteButton();
    displayView(view);
    dirty();
    await renderDeck();
    const buffer = moduleUI.editors[destination];
    if (['decks','expansion'].includes(target)) {
      // A failed list refresh never rolls back or discards an editor workspace.
      await deckList().catch(error=>notice(error.message));
      await search().catch(error=>notice(error.message));
      if (view==='decks') {
        setLibraryOpen(!!buffer?.libraryOpen, false);
        $('#deck-cards').scrollTop = buffer?.scroll || 0;
      }
    }
    if (target==='tags'&&!tagManagerUI.dirty) await refreshTagManager().catch(error=>notice(error.message));
    if (target==='duel') await enterDuelModule();
    if (target==='modular') await enterModular();
    if (target==='intelligence') await enterIntelligence();
    if (target==='cardanno') await enterCardAnnotations();
    window.scrollTo(0,moduleUI.scroll[target]);
    await syncNativeHost();
    if (app.active && previous==='expansion') notice('展开继续记录中。返回“展开”可继续操作。');
  } finally {
    app.busy = false; moduleUI.switching = false;
    updateStart(); updateDetailCounts(); updateModuleChrome();
  }
}
document.querySelectorAll('[data-module-target]').forEach(button=>{
  button.addEventListener('click',run(()=>switchModule(button.dataset.moduleTarget)));
});
$('#navigation-toggle').addEventListener('click',toggleNavigation);
new ResizeObserver(updateShellHeight).observe($('#expansion-navigation'));
updateModuleChrome();
displayView('home');
