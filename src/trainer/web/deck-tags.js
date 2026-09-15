'use strict';

const deckTagUI = {serial:0, session:0, timer:null, epoch:0, deck:null, draft:null, names:{}, tags:[], cards:[],
  selectedCards:new Set(), suggestions:null, visible:60, busy:false};

function refreshDeckTagName(tag) {
  const states = [app, ...(typeof moduleUI === 'undefined' ? [] : Object.values(moduleUI.editors).map(buffer => buffer?.state))];
  for (const state of states) if (state?.deckTags?.tag_ids.includes(tag.id)) state.deckTagNames[tag.id] = tag.name;
  updateDeckTagSummary();
}
function updateDeckTagSummary() {
  const selected = app.deckTags, count = selected.tag_ids.length;
  const label = id => app.deckTagNames[id] || '未安装 TAG';
  const text = selected.tag_ids.map(id => `${selected.primary_ids.includes(id) ? '主' : '副'} · ${label(id)}`).join(' / ');
  $('#deck-tag-count').textContent = `TAG ${count}`;
  $('#deck-tag-count').title = text || '尚未设置卡组 TAG';
  $('#deck-tag-count').setAttribute('aria-label', `卡组包含 ${count} 个 TAG，点击设置`);
  $('#deck-tag-summary').textContent = text;
  $('#deck-tag-summary').title = text;
  for (const id of ['deck-tags-button','deck-tag-count','deck-tag-summary']) {
    $(`#${id}`).hidden = !!activeDesignDeckEdit();
    $(`#${id}`).disabled = app.busy;
  }
}
function deckTagRole(id) {
  return deckTagUI.draft.primary_ids.includes(id) ? 'primary' : deckTagUI.draft.tag_ids.includes(id) ? 'secondary' : '';
}
function setDeckTagRole(id, role) {
  const draft = deckTagUI.draft;
  if (role && !draft.tag_ids.includes(id) && draft.tag_ids.length >= 30) {
    $('#deck-tags-status').textContent = '最多选择 30 个 TAG，请先移除一个。'; return;
  }
  if (role) {
    if (!draft.tag_ids.includes(id)) draft.tag_ids.push(id);
  } else draft.tag_ids = draft.tag_ids.filter(key => key !== id);
  draft.primary_ids = draft.primary_ids.filter(key => key !== id);
  if (role === 'primary') draft.primary_ids.push(id);
  $('#deck-tags-status').textContent = '选择已调整，应用后点击「保存构筑」保存。';
  renderDeckTagSelection(); renderDeckTagOptions();
}
function renderDeckTagSelection() {
  const draft = deckTagUI.draft;
  $('#deck-tags-total').textContent = `${draft.tag_ids.length} 个 · 主 ${draft.primary_ids.length} / 副 ${draft.tag_ids.length - draft.primary_ids.length}`;
  $('#deck-tags-selected').innerHTML = ['primary','secondary'].map(role => {
    const ids = draft.tag_ids.filter(id => deckTagRole(id) === role);
    return `<div class="deck-tag-group"><strong>${role === 'primary' ? '主 TAG' : '副 TAG'}</strong><div>${ids.map(id => `<span class="deck-tag-chip ${role}"><span>${escape(deckTagUI.names[id] || '未安装 TAG')}</span><button type="button" data-deck-tag="${escape(id)}" data-role="${role === 'primary' ? 'secondary' : 'primary'}" aria-label="将${escape(deckTagUI.names[id] || id)}改为${role === 'primary' ? '副' : '主'} TAG">改${role === 'primary' ? '副' : '主'}</button><button type="button" data-deck-tag="${escape(id)}" data-role="" aria-label="移除${escape(deckTagUI.names[id] || id)}">×</button></span>`).join('') || '<small>未选择</small>'}</div></div>`;
  }).join('');
}
function renderDeckTagOptions() {
  const evidence = new Map((deckTagUI.suggestions?.candidates || []).map(item => [item.id,item]));
  $('#deck-tags-result-count').textContent = `${deckTagUI.tags.length} 个匹配 TAG`;
  $('#deck-tags-options').innerHTML = deckTagUI.tags.slice(0,deckTagUI.visible).map(tag => {
    const item = evidence.get(tag.id), role = deckTagRole(tag.id);
    const info = item ? `${item.count} / ${item.total} 张 · ${(item.ratio * 100).toFixed(1)}%` : tag.deck_card_ids.length ? '仅副卡组关联' : '本卡组暂无关联卡牌';
    const cards = item ? item.cards.map(c => `${c.name} ×${c.count}`).join('、') : '';
    return `<article class="deck-tag-option ${role ? 'selected' : ''}"><div><strong>${escape(tag.name)}</strong><small>${escape(tag.aliases.join(' / '))}</small><p>${escape(info)}</p>${cards ? `<details><summary>查看依据卡牌</summary><p>${escape(cards)}</p></details>` : ''}</div><div class="deck-tag-role">${[['primary','主 TAG'],['secondary','副 TAG']].map(([value,label]) => `<button type="button" data-deck-tag="${escape(tag.id)}" data-role="${value}" aria-label="${escape(tag.name)}：${label}" aria-pressed="${role === value}">${label}</button>`).join('')}</div></article>`;
  }).join('') || '<p class="deck-tags-empty">没有匹配的 TAG，试试其他文字或清除选卡。</p>';
  $('#deck-tags-more').hidden = deckTagUI.visible >= deckTagUI.tags.length;
}
function renderDeckTagCards() {
  const q = tagSearchKey($('#deck-tags-card-search').value);
  $('#deck-tags-card-count').textContent = `已选 ${deckTagUI.selectedCards.size} 种 / 共 ${deckTagUI.cards.length} 种`;
  $('#deck-tags-cards').innerHTML = deckTagUI.cards.filter(c => tagSearchKey(c.name).includes(q) || String(c.id).includes(q)).map(c => `<button type="button" data-deck-tag-card="${c.id}" aria-pressed="${deckTagUI.selectedCards.has(c.id)}" title="${escape(c.name)}"><img src="/pics/${c.id}.jpg" alt="" loading="lazy"><span>${escape(c.name)}<small>${zones.filter(z => c.counts[z]).map(z => `${zoneNames[z]} ×${c.counts[z]}`).join(' · ')}</small></span></button>`).join('') || '<p>本卡组没有匹配卡牌。</p>';
}
async function searchDeckTags() {
  const serial = ++deckTagUI.serial;
  deckTagUI.busy = true;
  $('#deck-tags-options').setAttribute('aria-busy','true');
  $('#deck-tags-result-count').textContent = '正在查找…';
  try {
    const data = await api('/api/decks/tag-options', {deck:deckTagUI.deck, query:$('#deck-tags-search').value, card_ids:[...deckTagUI.selectedCards]});
    if (serial !== deckTagUI.serial || !$('#deck-tags-dialog').open || deckTagUI.epoch !== app.deckEpoch) return;
    deckTagUI.tags = data.tags; deckTagUI.suggestions = data.suggestions; deckTagUI.visible = 60;
    Object.assign(deckTagUI.names, data.tag_names, Object.fromEntries(data.tags.map(t => [t.id,t.name])));
    for (const tag of data.tags) if (app.deckTags.tag_ids.includes(tag.id)) app.deckTagNames[tag.id] = tag.name;
    updateDeckTagSummary();
    renderDeckTagSelection(); renderDeckTagOptions();
  } catch (error) {
    if (serial === deckTagUI.serial && $('#deck-tags-dialog').open) {
      $('#deck-tags-result-count').textContent = '查找失败，可重置筛选重试';
      $('#deck-tags-status').textContent = `${error.message}。已有选择仍保留。`;
    }
  } finally {
    if (serial === deckTagUI.serial) {
      deckTagUI.busy = false; $('#deck-tags-options').setAttribute('aria-busy','false');
      $('#deck-tags-auto').disabled = !deckTagUI.suggestions;
    }
  }
}
async function openDeckTags() {
  if (app.busy || activeDesignDeckEdit() || $('#deck-tags-dialog').open) return;
  clearTimeout(deckTagUI.timer); ++deckTagUI.serial; ++deckTagUI.session;
  Object.assign(deckTagUI,{epoch:app.deckEpoch,deck:structuredClone(app.deck),draft:structuredClone(app.deckTags),names:{...app.deckTagNames},
    tags:[],cards:[],selectedCards:new Set(),suggestions:null,visible:60,busy:true});
  $('#deck-tags-name').textContent = $('#deck-name').value;
  $('#deck-tags-search').value = $('#deck-tags-card-search').value = '';
  $('#deck-tags-status').textContent = '应用后点击「保存构筑」保存。';
  $('#deck-tags-auto').disabled = true;
  renderDeckTagSelection(); renderDeckTagOptions(); renderDeckTagCards();
  $('#deck-tags-dialog').showModal(); $('#deck-tags-search').focus();
  const session = deckTagUI.session;
  try {
    const cards = await Promise.all([...new Set(zones.flatMap(z => deckTagUI.deck[z]))].map(card));
    if (session !== deckTagUI.session || !$('#deck-tags-dialog').open) return;
    deckTagUI.cards = cards.map(c => ({...c,counts:Object.fromEntries(zones.map(z => [z,deckTagUI.deck[z].filter(id => id === c.id).length]))}));
    renderDeckTagCards();
  } catch (error) {if (session === deckTagUI.session) $('#deck-tags-status').textContent = error.message;}
  if (session === deckTagUI.session && $('#deck-tags-dialog').open) {clearTimeout(deckTagUI.timer);await searchDeckTags();}
}
function closeDeckTags() {
  clearTimeout(deckTagUI.timer); ++deckTagUI.serial; ++deckTagUI.session; deckTagUI.busy = false;
  $('#deck-tags-dialog').close();
}
function applyDeckTags() {
  if (deckTagUI.epoch !== app.deckEpoch || app.busy) return;
  setDeckTags(deckTagUI.draft,deckTagUI.names); dirty(); closeDeckTags();
}
function queueDeckTagSearch() {
  clearTimeout(deckTagUI.timer); ++deckTagUI.serial;
  deckTagUI.timer = setTimeout(searchDeckTags,180);
}
$('#deck-tags-button').onclick = $('#deck-tag-count').onclick = run(openDeckTags);
$('#deck-tags-cancel').onclick = closeDeckTags;
$('#deck-tags-dialog').addEventListener('cancel',e => {e.preventDefault();closeDeckTags();});
$('#deck-tags-apply').onclick = applyDeckTags;
$('#deck-tags-search').oninput = queueDeckTagSearch;
$('#deck-tags-card-search').oninput = renderDeckTagCards;
$('#deck-tags-card-clear').onclick = () => {deckTagUI.selectedCards.clear();renderDeckTagCards();queueDeckTagSearch();};
$('#deck-tags-search-reset').onclick = () => {$('#deck-tags-search').value = '';deckTagUI.selectedCards.clear();renderDeckTagCards();queueDeckTagSearch();};
$('#deck-tags-more').onclick = () => {deckTagUI.visible += 60;renderDeckTagOptions();};
$('#deck-tags-clear').onclick = () => {deckTagUI.draft = {tag_ids:[],primary_ids:[]};renderDeckTagSelection();renderDeckTagOptions();};
$('#deck-tags-auto').onclick = () => {
  if (!deckTagUI.suggestions) return;
  const {tag_ids,primary_ids} = deckTagUI.suggestions;
  deckTagUI.draft = {tag_ids:[...tag_ids],primary_ids:[...primary_ids]};
  $('#deck-tags-status').textContent = tag_ids.length ? '已替换为自动推荐，可继续调整；应用后再保存构筑。' : '主卡组和额外卡组没有命中已有 TAG，可手动选择。';
  renderDeckTagSelection();renderDeckTagOptions();
};
$('#deck-tags-dialog').addEventListener('click',e => {
  const button = e.target.closest('button'); if (!button || button.disabled) return;
  if (button.dataset.deckTag) {
    const role = button.dataset.role;
    setDeckTagRole(button.dataset.deckTag,deckTagRole(button.dataset.deckTag) === role ? '' : role);
  }
  if (button.dataset.deckTagCard) {
    const id = Number(button.dataset.deckTagCard);
    if (deckTagUI.selectedCards.has(id)) deckTagUI.selectedCards.delete(id); else deckTagUI.selectedCards.add(id);
    renderDeckTagCards();queueDeckTagSearch();
  }
});
updateDeckTagSummary();
