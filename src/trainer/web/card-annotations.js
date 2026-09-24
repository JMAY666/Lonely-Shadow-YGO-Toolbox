'use strict';

// Static card-effect annotations: query with evidence, review status, notes.
// This page never claims a card can be activated right now; that stays with
// the rule engine and live duel state (docs/card-annotation-system.md).
const annoCircled = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳';
const annoStatusMeta = {
  none: {label: '未标注', cls: ''}, auto: {label: '自动草稿', cls: 'is-auto'},
  partial: {label: '部分标注', cls: 'is-auto'}, reviewed: {label: '已核对', cls: 'is-review'},
  confirmed: {label: '已确认', cls: 'is-review'}, pending: {label: '待核对', cls: 'is-pending'},
  stale: {label: '卡文已变化', cls: 'is-stale'},
};
const annoStatusOrder = ['reviewed', 'confirmed', 'auto', 'partial', 'pending', 'stale', 'none'];
const annoUI = {data: null, registry: null, tags: new Set(), libraryTags: [], statuses: new Set(annoStatusOrder),
  results: null, detail: null, revision: null, busy: false, serial: 0};

function annoEffectLabel(effect) {
  const prefix = effect.block === 'p' ? '灵摆·' : '';
  if (effect.number) return `${prefix}${annoCircled[effect.number - 1] || effect.number}`;
  if (effect.key.endsWith('-pre')) return `${prefix}前置文本`;
  return `${prefix}无编号`;
}
function annoCardKind(type) {
  const names = [];
  if (type & 1) names.push(type & 0x20 ? '效果怪兽' : type & 0x10 ? '通常怪兽' : '怪兽');
  if (type & 2) names.push('魔法');
  if (type & 4) names.push('陷阱');
  return names.join('·') || '未知';
}
function annoEvidenceItems(hit) {
  return (hit.evidence || []).map(item => {
    const names = {tag: '效果 TAG', action: '动作', from_zone: '来源区域', to_zone: '去向区域',
      usage: '次数限制', cost_kind: '费用', timing: '发动时点'};
    const value = Array.isArray(item.value) ? item.value.join('、') : item.value;
    return `<li>${escape(names[item.condition] || item.condition)}：${escape(value)} — ${escape(item.basis)}</li>`;
  }).join('');
}
function annoProcessingLines(items, registry, indent = '') {
  const lines = [];
  for (const item of items || []) {
    const action = registry.actions[item.action] || item.action;
    const count = item.count === undefined ? '' : `×${item.count === 'up_to_1' ? '至多1' : item.count}`;
    const zones = (zonesText) => zonesText ? zonesText.map(zone => registry.zones[zone] || zone).join('／') : '';
    const flow = [zones(item.from_zones), zones(item.to_zones)].filter(Boolean).join(' → ');
    const selector = item.selector?.text || item.evidence || '';
    lines.push(`${indent}${action}${count}${flow ? `（${flow}）` : ''}${selector ? `：${selector}` : ''}`);
    for (const restriction of item.restrictions || []) lines.push(`${indent}　限制：${restriction}`);
    lines.push(...annoProcessingLines(item.then, registry, indent + '　↳ '));
    for (const branch of item.branches || []) {
      lines.push(`${indent}　若「${branch.condition}」：`);
      lines.push(...annoProcessingLines(branch.actions, registry, indent + '　　· '));
      lines.push(...annoProcessingLines(branch.then, registry, indent + '　　· '));
    }
  }
  return lines;
}
function annoStructureLines(effect, registry) {
  const structure = effect.structure || {};
  const lines = [];
  const activation = structure.activation;
  if (activation) {
    const timing = registry.timings[activation.timing] || activation.timing || '';
    const zonesText = (activation.zones || []).map(zone => registry.zones[zone] || zone).join('／');
    lines.push(`发动：${[timing, zonesText && `区域 ${zonesText}`, ...(activation.conditions || [])].filter(Boolean).join('；')}${activation.fast_effect ? '（可在对方回合使用）' : ''}`);
  }
  for (const cost of structure.cost || []) lines.push(`费用：${registry.cost_kinds[cost.kind] || cost.kind}${cost.text ? ` — ${cost.text}` : ''}`);
  for (const target of structure.targeting || []) lines.push(`对象：${target.count}×${target.filter}`);
  for (const line of annoProcessingLines(structure.processing, registry)) lines.push(`处理：${line}`);
  for (const usage of structure.usage || []) lines.push(`次数：${registry.usage_limits[usage] || usage}`);
  return lines;
}
function annoRelationLabel(kind) {
  return {material_rule: '素材规则', summon_condition: '召唤条件', shared_limit: '共享次数限制',
    usage_limit_group: '次数限制组', exclusive_choice: '互斥选择', choose_branch: '分支选择',
    order: '顺序', depends_on: '依赖'}[kind] || kind;
}
function annoNotesHTML(notes, title = '备注') {
  if (!notes?.length) return '';
  return `<div class="anno-note"><b>${escape(title)}</b>${notes.map(note =>
    `<div>${escape(note.text)}${note.source_refs?.length ? ` <small>来源：${escape(note.source_refs.join('、'))}</small>` : ''}</div>`).join('')}</div>`;
}
function annoStatusBadge(status) {
  const meta = annoStatusMeta[status] || {label: status, cls: ''};
  return `<span class="anno-badge ${meta.cls}">${escape(meta.label)}</span>`;
}
function annoOverviewHTML(overview) {
  const source = (overview.catalog.sources || [])[0];
  const chips = annoStatusOrder.map(status =>
    `<button class="anno-chip is-status" data-anno-status="${status}" aria-pressed="${annoUI.statuses.has(status)}">${escape(annoStatusMeta[status].label)} <b>${overview.statuses[status] ?? 0}</b></button>`).join('');
  return `<p class="anno-topbar">${chips}</p>
    <p class="anno-status">卡库 ${overview.catalog.cards} 张（含衍生物 ${overview.tokens}，不参与标注）` +
    `${source ? ` · 基础库 ${escape(source.path)} <code>${escape(String(source.sha256).slice(0, 12))}…</code>` : ''}` +
    ` · 已标注 ${overview.annotated_total} 张 · 资料版本「${escape(overview.curated.title)}」（${escape(overview.curated.checked_on)}）· 效果 TAG ${overview.registry.tags} 个` +
    `${overview.stale_codes.length ? ` · <span class="anno-warn">${overview.stale_codes.length} 张卡文已变化待核对</span>` : ''}` +
    `${overview.missing_codes.length ? ` · ${overview.missing_codes.length} 张标注卡不在当前卡库` : ''}</p>
    <p class="anno-status">覆盖口径：${escape(overview.note)}</p>`;
}
function annoHitHTML(hit) {
  return `<article class="anno-hit"><header>${escape(annoEffectLabel(hit))}${hit.engine ? '<span class="anno-badge is-engine">引擎已验证</span>' : ''}</header>
    <blockquote>${escape(hit.text || '')}</blockquote>
    ${hit.evidence?.length ? `<ul class="anno-evidence">${annoEvidenceItems(hit)}</ul>` : ''}
    <div>${(hit.tags || []).map(tag => `<span class="anno-badge">${escape(tag)}</span>`).join(' ')}</div></article>`;
}
function annoResultsHTML(result) {
  if (!result.cards.length) return `<div class="anno-empty">已标注范围内没有命中。未标注不代表没有该能力。</div>`;
  const head = `命中 ${result.total} 张（已标注 ${result.annotated_total} / 卡库 ${result.catalog_total}，第 ${result.offset + 1}–${result.offset + result.cards.length} 张）`;
  const body = result.cards.map(entry => `
    <div class="anno-card" data-anno-card="${entry.code}" tabindex="0" role="button">
      <h3>${escape(entry.name)} <small>#${entry.code} · ${escape(annoCardKind(entry.type || 0))}</small> ${annoStatusBadge(entry.status)}${entry.cross_effects ? '<span class="anno-badge is-auto">跨效果命中</span>' : ''}</h3>
      ${entry.hits.map(annoHitHTML).join('')}
    </div>`).join('');
  const pager = `<div class="anno-actions">
      <button data-anno-page="${Math.max(0, result.offset - 30)}" ${result.offset ? '' : 'disabled'}>上一页</button>
      <button data-anno-page="${result.offset + 30}" ${result.offset + 30 < result.total ? '' : 'disabled'}>下一页</button>
    </div>`;
  return `<p class="anno-status">${escape(head)} · ${escape(result.note)}</p>${body}${pager}`;
}
function annoEffectHTML(effect, registry, editable) {
  const structure = annoStructureLines(effect, registry).map(line => `<div>${escape(line)}</div>`).join('');
  const tagChips = (effect.tags || []).map(tag =>
    `<span class="anno-badge">${escape(registry.tags[tag]?.name || tag)}${editable && effect.annotated ? ` <button data-anno-tag-remove="${escape(effect.key)}" data-anno-tag="${escape(tag)}" aria-label="移除标签">×</button>` : ''}</span>`).join(' ');
  const addTag = editable && effect.annotated ? `<select data-anno-tag-add="${escape(effect.key)}" aria-label="添加效果 TAG"><option value="">＋ 添加 TAG…</option>${Object.values(registry.tags).filter(tag => !(effect.tags || []).includes(tag.id)).map(tag => `<option value="${escape(tag.id)}">${escape(tag.name)}</option>`).join('')}</select>` : '';
  return `<div class="anno-effect"><header>${escape(annoEffectLabel(effect))}${effect.annotated ? '' : '<span class="anno-badge">未标注</span>'}${effect.engine ? '<span class="anno-badge is-engine">引擎已验证</span>' : ''}</header>
    <blockquote>${escape(effect.text || '')}</blockquote>
    ${tagChips || addTag ? `<div>${tagChips} ${addTag}</div>` : ''}
    ${structure ? `<div class="anno-struct">${structure}</div>` : ''}
    ${annoNotesHTML(effect.notes, '标注备注')}
    ${editable && effect.annotated ? `<div class="anno-buttons"><input type="text" data-anno-note-input="${escape(effect.key)}" placeholder="为这个效果补充备注（纠错／核对依据）" maxlength="4000"><button data-anno-note="${escape(effect.key)}">添加备注</button></div>` : ''}
  </div>`;
}
function annoDetailHTML(view, registry) {
  const editable = view.status !== 'none';
  const review = view.review || {};
  const buttons = [];
  if (view.provenance?.source === 'user-draft') {
    buttons.push(`<button data-anno-op="discard-draft">丢弃自动草稿</button>`);
  } else if (view.status === 'none') {
    buttons.push(`<button data-anno-op="draft">生成自动草稿（不入已核对）</button>`);
  }
  if (view.digest_ok && view.status !== 'none') {
    buttons.push(`<button data-anno-op="set-review" data-value="confirmed" ${view.status === 'confirmed' ? 'disabled' : ''}>确认已核对</button>`);
    buttons.push(`<button data-anno-op="set-review" data-value="pending" ${view.status === 'pending' ? 'disabled' : ''}>标为待核对</button>`);
    buttons.push(`<button data-anno-op="set-review" data-value="" ${view.status === 'reviewed' || view.status === 'auto' ? 'disabled' : ''}>撤销核对标记</button>`);
  }
  const provenance = view.provenance ? `<p class="anno-status">来源：${view.provenance.source === 'curated'
    ? `内置资料「${escape(view.provenance.title || '')}」（核对于 ${escape(view.provenance.checked_on || '')}）`
    : '本地自动草稿'} · 审核状态 ${escape(review.status || '')}／${escape(review.origin || '')}${view.review?.basis ? ` · ${escape(view.review.basis)}` : ''} · 卡文指纹 <code>${escape(String(view.text_digest).slice(0, 12))}…</code>${view.digest_ok ? '' : ' <span class="anno-warn">与当前卡文不一致，已冻结为待核对</span>'}</p>` : '';
  return `<div class="anno-panel anno-detail"><div class="anno-detail-body">
    <h2>${escape(view.name)} <small>#${view.code} · ${escape(annoCardKind(view.type || 0))}</small> ${annoStatusBadge(view.status)}</h2>
    ${provenance}
    ${!view.digest_ok ? `<p class="anno-status anno-warn">卡库卡文已变化：以下标注按旧卡文冻结展示，进入复核流程后再更新；个人备注保留。</p>` : ''}
    <section class="anno-section"><h4>效果分段（${view.effects.length}）${view.missing_keys.length ? ` · ${view.missing_keys.length} 段未标注` : view.no_effect ? ' · 无效果卡' : ''}</h4>
      ${view.effects.map(effect => annoEffectHTML(effect, registry, view.digest_ok)).join('') || '<div class="anno-empty">无卡文</div>'}
    </section>
    ${view.relations?.length ? `<section class="anno-section"><h4>效果间关系</h4>${view.relations.map(relation =>
      `<div class="anno-struct">${escape(annoRelationLabel(relation.kind))}［${escape((relation.effects || []).join('、') || '卡牌级')}］<span>${escape(relation.text)}</span></div>`).join('')}</section>` : ''}
    ${annoNotesHTML(view.notes, '卡片备注')}
    <div class="anno-buttons">${buttons.join('')}</div>
  </div></div>`;
}
function annoQueryBody(offset = 0) {
  const body = {op: 'query', offset,
    q: $('#anno-q')?.value || '', kind: $('#anno-kind')?.value || '',
    tag: $('#anno-tag')?.value || '', action: $('#anno-action')?.value || '',
    from_zone: $('#anno-from')?.value || '', to_zone: $('#anno-to')?.value || '',
    usage: $('#anno-usage')?.value || '', cost_kind: $('#anno-cost')?.value || '',
    timing: $('#anno-timing')?.value || '', scope: $('#anno-scope')?.value || 'effect',
    etags: [...annoUI.tags], etag_mode: $('#anno-etag-mode')?.value || 'all',
    status: [...annoUI.statuses]};
  return body;
}
function annoSelect(id, value, options, label) {
  return `<label>${escape(label)}<select id="${id}"><option value="">全部</option>${options.map(option =>
    `<option value="${escape(option.value)}" ${option.value === value ? 'selected' : ''}>${escape(option.name)}</option>`).join('')}</select></label>`;
}
function annoTagChipsHTML(registry) {
  return Object.values(registry.tags).map(tag =>
    `<button class="anno-tag" data-anno-etag="${escape(tag.id)}" aria-pressed="${annoUI.tags.has(tag.id)}" title="${escape(tag.definition)}">${escape(tag.name)}</button>`).join('');
}
function annoRenderShell() {
  $('#card-annotations').innerHTML = `
    <header class="anno-heading"><div><div class="eyebrow">CARD ANNOTATIONS</div><h1>卡片标注</h1></div><button id="anno-refresh">刷新</button></header>
    <div id="anno-overview"></div>
    <div class="anno-layout">
      <div>
        <div class="anno-panel"><form id="anno-form" class="anno-query">
          <label>关键词<input type="search" id="anno-q" placeholder="卡名／卡文／卡号" maxlength="120"></label>
          ${annoSelect('anno-kind', '', [{value:'monster',name:'怪兽'},{value:'spell',name:'魔法'},{value:'trap',name:'陷阱'},{value:'extra',name:'额外卡组'}], '卡片类型')}
          <label>关联 TAG（系列／用途）<select id="anno-tag"><option value="">全部</option></select></label>
          <label>动作<select id="anno-action"></select></label>
          <label>来源区域<select id="anno-from"></select></label>
          <label>去向区域<select id="anno-to"></select></label>
          <label>次数限制<select id="anno-usage"></select></label>
          <label>费用<select id="anno-cost"></select></label>
          <label>发动时点<select id="anno-timing"></select></label>
          <label>查询范围<select id="anno-scope"><option value="effect">单效果（默认，不串效果）</option><option value="card">整卡（条件可由不同效果分别满足）</option></select></label>
          <label>效果 TAG 匹配<select id="anno-etag-mode"><option value="all">全部命中</option><option value="any">任一命中</option></select></label>
          <div class="anno-tagpool" id="anno-tagpool" aria-label="效果 TAG"></div>
          <div class="anno-actions"><button type="submit">查询</button><button type="button" id="anno-reset">重置</button></div>
        </form></div>
        <div class="anno-panel anno-results" id="anno-results"><div class="anno-empty">输入条件后查询。查询只在已标注范围内命中，并逐条说明命中的是哪个效果、依据是什么。</div></div>
      </div>
      <div id="anno-detail"></div>
    </div>`;
}
function annoFillSelects(registry, libraryTags) {
  const fill = (id, vocabulary) => { const select = $(`#${id}`); if (!select) return;
    select.innerHTML = `<option value="">全部</option>` + Object.entries(vocabulary).map(([value, name]) =>
      `<option value="${escape(value)}">${escape(name)}</option>`).join(''); };
  fill('anno-action', registry.actions); fill('anno-from', registry.zones); fill('anno-to', registry.zones);
  fill('anno-usage', registry.usage_limits); fill('anno-cost', registry.cost_kinds); fill('anno-timing', registry.timings);
  const tag = $('#anno-tag');
  tag.innerHTML = `<option value="">全部</option>` + libraryTags.map(entry =>
    `<option value="${escape(entry.id)}">${escape(entry.name)}${entry.kind === 'purpose' ? ' · 用途' : ''}</option>`).join('');
  $('#anno-tagpool').innerHTML = annoTagChipsHTML(registry);
}
async function annoLoadDetail(code) {
  const serial = ++annoUI.serial;
  const view = await api('/api/annotations', {op: 'card', code});
  if (serial !== annoUI.serial) return;
  annoUI.detail = view;
  annoRenderDetail();
}
function annoRenderDetail() {
  const target = $('#anno-detail');
  if (!target) return;
  target.innerHTML = annoUI.detail ? annoDetailHTML(annoUI.detail, annoUI.registry)
    : '<div class="anno-panel"><div class="anno-empty">点击左侧卡牌查看效果级标注、依据与备注。</div></div>';
}
async function enterCardAnnotations() {
  annoRenderShell();
  $('#anno-detail').innerHTML = '<div class="anno-panel"><div class="anno-empty">正在载入标注资料…</div></div>';
  annoUI.busy = true;
  try {
    const [snapshot, tags] = await Promise.all([
      api('/api/annotations'),
      api('/api/tags').catch(() => ({tags: []})),
    ]);
    annoUI.registry = {...snapshot.registry, tags: Object.fromEntries(snapshot.registry.tags.map(tag => [tag.id, tag]))};
    annoUI.registry.raw = snapshot.registry;
    annoUI.libraryTags = tags.tags || [];
    annoUI.revision = snapshot.revision;
    annoFillSelects(snapshot.registry, annoUI.libraryTags);
    $('#anno-overview').innerHTML = annoOverviewHTML(snapshot.overview);
    await annoRunQuery(0);
  } finally { annoUI.busy = false; }
}
async function annoRunQuery(offset) {
  const serial = ++annoUI.serial;
  const result = await api('/api/annotations', annoQueryBody(offset));
  if (serial !== annoUI.serial) return;
  annoUI.results = result;
  $('#anno-results').innerHTML = annoResultsHTML(result);
}
async function annoRunOp(body, message) {
  annoUI.busy = true;
  try {
    const result = await api('/api/annotations', body);
    if (result.revision !== undefined) annoUI.revision = result.revision;
    if (message) notice(message);
    const overview = await api('/api/annotations', {op: 'overview'});
    $('#anno-overview').innerHTML = annoOverviewHTML(overview);
    if (annoUI.detail) await annoLoadDetail(annoUI.detail.code);
    await annoRunQuery(annoUI.results?.offset || 0);
  } finally { annoUI.busy = false; }
}
$('#card-annotations').addEventListener('click', run(async event => {
  if (event.target.id === 'anno-refresh') return await enterCardAnnotations();
  if (event.target.id === 'anno-reset') { annoUI.tags.clear(); annoUI.statuses = new Set(annoStatusOrder); return await enterCardAnnotations(); }
  const etag = event.target.closest('[data-anno-etag]');
  if (etag) { const id = etag.dataset.annoEtag; annoUI.tags.has(id) ? annoUI.tags.delete(id) : annoUI.tags.add(id);
    etag.setAttribute('aria-pressed', String(annoUI.tags.has(id))); return; }
  const status = event.target.closest('[data-anno-status]');
  if (status) { const id = status.dataset.annoStatus; annoUI.statuses.has(id) ? annoUI.statuses.delete(id) : annoUI.statuses.add(id);
    status.setAttribute('aria-pressed', String(annoUI.statuses.has(id))); return; }
  const page = event.target.closest('[data-anno-page]');
  if (page && !page.disabled) { await annoRunQuery(Number(page.dataset.annoPage)); return; }
  const cardNode = event.target.closest('[data-anno-card]');
  if (cardNode) {
    document.querySelectorAll('.anno-card').forEach(node => node.style.outline = '');
    cardNode.style.outline = '2px solid var(--accent)';
    await annoLoadDetail(Number(cardNode.dataset.annoCard));
    return;
  }
  const removeTag = event.target.closest('[data-anno-tag-remove]');
  if (removeTag) {
    await annoRunOp({op: 'set-tags', code: annoUI.detail.code, key: removeTag.dataset.annoTagRemove,
      add: [], remove: [removeTag.dataset.annoTag], revision: annoUI.revision}, '已移除效果标签（记录为个人修正）');
    return;
  }
  const note = event.target.closest('[data-anno-note]');
  if (note) {
    const input = $(`[data-anno-note-input="${note.dataset.annoNote}"]`);
    if (!input?.value.trim()) return notice('请先填写备注内容');
    await annoRunOp({op: 'add-note', code: annoUI.detail.code, key: note.dataset.annoNote,
      text: input.value.trim(), revision: annoUI.revision}, '已保存备注');
    return;
  }
  const op = event.target.closest('[data-anno-op]');
  if (op) {
    const kind = op.dataset.annoOp;
    if (kind === 'draft') return await annoRunOp({op: 'draft', code: annoUI.detail.code}, '已生成自动草稿：状态为自动草稿，不计入已核对');
    if (kind === 'discard-draft') return await annoRunOp({op: 'discard-draft', code: annoUI.detail.code, revision: annoUI.revision}, '已丢弃自动草稿');
    if (kind === 'set-review') return await annoRunOp({op: 'set-review', code: annoUI.detail.code,
      value: op.dataset.value || null, revision: annoUI.revision}, '已更新核对状态');
  }
}));
$('#card-annotations').addEventListener('change', run(async event => {
  const addTag = event.target.closest('[data-anno-tag-add]');
  if (addTag?.value) {
    await annoRunOp({op: 'set-tags', code: annoUI.detail.code, key: addTag.dataset.annoTagAdd,
      add: [addTag.value], remove: [], revision: annoUI.revision}, '已添加效果标签（记录为个人修正）');
  }
}));
$('#card-annotations').addEventListener('submit', run(async event => {
  if (event.target.id === 'anno-form') { event.preventDefault(); await annoRunQuery(0); }
}));
