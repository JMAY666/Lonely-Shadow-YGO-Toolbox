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
  results: null, detail: null, revision: null, busy: false, querySerial: 0, detailSerial: 0, editing: false, noteDrafts: new Map()};

function annoEffectLabel(effect) {
  const prefix = effect.block === 'p' ? '灵摆·' : '';
  if (effect.number) return `${prefix}${annoCircled[effect.number - 1] || effect.number}`;
  if (effect.key.endsWith('-pre')) return `${prefix}${effect.effect_type === 'non_effect' ? '规则与限制' : '无编号前文'}`;
  return `${prefix}无编号`;
}
function annoCardKind(type) {
  if (type & 2) return `${type & 0x10000 ? '速攻' : type & 0x20000 ? '永续' : type & 0x40000 ? '装备' : type & 0x80000 ? '场地' : type & 0x80 ? '仪式' : '通常'}魔法`;
  if (type & 4) return `${type & 0x100000 ? '反击' : type & 0x20000 ? '永续' : '通常'}陷阱`;
  return [[0x1000000,'灵摆'],[0x4000000,'连接'],[0x800000,'超量'],[0x2000,'同调'],[0x40,'融合'],[0x80,'仪式'],[0x1000,'调整']].filter(([bit])=>type&bit).map(([,name])=>name).concat(type&0x20?'效果怪兽':type&0x10?'通常怪兽':'怪兽').join('·');
}
function annoTagName(id) { return annoUI.registry?.tags[id]?.name || id; }
function annoEvidenceItems(hit) {
  return (hit.evidence || []).map(item => {
    const names = {tag: '效果 TAG', action: '动作', from_zone: '来源区域', to_zone: '去向区域',
      usage: '次数限制', cost_kind: '费用', timing: '发动时点'};
    const vocabulary = {action:'actions',from_zone:'zones',to_zone:'zones',usage:'usage_limits',cost_kind:'cost_kinds',timing:'timings'};
    const value = item.condition === 'tag' ? (Array.isArray(item.value) ? item.value : [item.value]).map(annoTagName).join('、') : (annoUI.registry?.[vocabulary[item.condition]]?.[item.value] || item.value);
    return `<li>${escape(names[item.condition] || item.condition)}：${escape(value)} — ${escape(item.basis)}</li>`;
  }).join('');
}
function annoProcessingLines(items, registry, indent = '') {
  const lines = [];
  for (const item of items || []) {
    const action = registry.actions[item.action] || item.action;
    const count = item.count === undefined ? '' : `×${item.count === 'up_to_1' ? '至多1' : item.count === 'all' ? '全部' : item.count}`;
    const zones = (zonesText) => zonesText ? zonesText.map(zone => registry.zones[zone] || zone).join('／') : '';
    const flow = [zones(item.from_zones), zones(item.to_zones)].filter(Boolean).join(' → ');
    const selector = item.selector?.text || item.evidence || '';
    if (item.branch) lines.push(`${indent}分支 ${item.branch}（选择其一）：`);
    if (item.condition) lines.push(`${indent}前提：${item.condition}`);
    lines.push(`${indent}${item.optional ? '可选：' : ''}${action}${count}${flow ? `（${flow}）` : ''}${selector ? `：${selector}` : ''}`);
    if (item.duration) lines.push(`${indent}　持续：${item.duration}`);
    if (item.position) lines.push(`${indent}　表示形式：${item.position}`);
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
    lines.push(`发动：${[timing, zonesText && `区域 ${zonesText}`, ...(activation.conditions || [])].filter(Boolean).join('；')}${activation.fast_effect ? '（快速效果；仍须满足发动条件）' : ''}`);
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
function annoNotesHTML(notes) {
  if (!notes?.length) return '';
  return `<div class="anno-note">${notes.map(note=>`<p>${escape(note.text)}</p>`).join('')}</div>`;
}
function annoStatusBadge(status) {
  const meta = annoStatusMeta[status] || {label: status, cls: ''};
  return `<span class="anno-badge ${meta.cls}">${escape(meta.label)}</span>`;
}
function annoOverviewHTML(overview) {
  const eligible = overview.eligible_total ?? overview.catalog.cards - overview.tokens;
  const checked = (overview.statuses.reviewed || 0) + (overview.statuses.confirmed || 0);
  return `<p class="anno-status"><strong>已标注 ${overview.annotated_total} 张</strong> / 可标注 ${eligible.toLocaleString()} 张<span>完整核对 ${checked} 张 · 未标注 ≠ 没有能力</span></p>
    <details class="anno-coverage"><summary>覆盖与版本信息</summary><div class="anno-coverage-body">
      <div class="anno-topbar">${annoStatusOrder.map(status=>`<span class="anno-chip">${annoStatusMeta[status].label} <b>${overview.statuses[status] || 0}</b></span>`).join('')}</div>
      <p>卡库 ${overview.catalog.cards} 张 · 衍生物 ${overview.tokens} 张，不参与标注 · 效果标签 ${overview.registry.tags} 个（含兼容项）</p>
      <p>${escape(overview.curated.title)} · ${escape(overview.curated.checked_on)}。${escape(overview.note)}</p>
      ${overview.catalog.sources.map(source=>`<p>${escape(source.path)} · <code>${escape(String(source.sha256).slice(0,12))}…</code></p>`).join('')}
      ${overview.missing_codes.length ? `<p>${overview.missing_codes.length} 张资料对应的卡不在当前卡库。</p>` : ''}
    </div></details>${overview.stale_codes.length ? `<p class="anno-warning">${overview.stale_codes.length} 张卡文发生变化，旧标注已暂停参与能力查询。</p>` : ''}`;
}
function annoResultsHTML(result) {
  const head = `<p class="anno-list-heading" role="status">找到 ${result.total} 张${result.total ? ` · ${result.offset+1}–${result.offset+result.cards.length}` : ''}</p>`;
  if (!result.cards.length) return head + '<div class="anno-empty">没有符合条件的卡片。<br>未标注不代表没有该能力。<br>可清除能力条件或切换“全部卡片”。</div>';
  const body = result.cards.map(entry=>{
    const tags = [...new Set(entry.hits.flatMap(hit=>hit.tags || []))];
    return `<button type="button" class="anno-card" data-anno-card="${entry.code}" aria-pressed="${annoUI.detail?.code === entry.code}">
      <span class="anno-card-title">${escape(entry.name)}</span><span class="anno-card-meta">${escape(annoCardKind(entry.type))} · ${entry.code}</span>
      <span class="anno-card-labels">${annoStatusBadge(entry.status)}${entry.cross_effects ? '<span class="anno-badge is-auto">跨效果命中</span>' : ''}</span>
      <span class="anno-card-summary">${entry.no_effect ? '无效果卡' : tags.length ? escape(tags.slice(0,4).map(annoTagName).join(' · '))+(tags.length>4 ? ` +${tags.length-4}` : '') : entry.status === 'none' ? '尚未标注，能力未知' : '查看规则与效果'}</span>
    </button>`;
  }).join('');
  return head+body+`<div class="anno-pager"><button type="button" data-anno-page="${Math.max(0,result.offset-30)}" ${result.offset?'':'disabled'}>上一页</button><button type="button" data-anno-page="${result.offset+30}" ${result.offset+30<result.total?'':'disabled'}>下一页</button></div>`;
}
function annoEffectHTML(effect, registry, editable, code) {
  const structure = annoStructureLines(effect,registry);
  const tags = (effect.tags || []).map(tag=>`<span class="anno-badge" title="${escape(registry.tags[tag]?.definition || '')}">${escape(registry.tags[tag]?.name || tag)}${editable&&effect.annotated ? ` <button type="button" data-anno-tag-remove="${escape(effect.key)}" data-anno-tag="${escape(tag)}" aria-label="移除${escape(registry.tags[tag]?.name || tag)}">×</button>` : ''}</span>`).join(' ');
  const hit = annoUI.results?.cards.find(card=>card.code===annoUI.detail?.code)?.hits.find(hit=>hit.key===effect.key);
  return `<article class="anno-effect"><header><strong>${escape(annoEffectLabel(effect))}</strong><span class="anno-effect-kind">${escape(registry.effect_types?.[effect.effect_type] || (effect.annotated?'':'尚未标注'))}</span></header>
    <blockquote>${escape(effect.text || '')}</blockquote><div class="anno-tags">${tags}</div>
    ${structure.length || effect.notes?.length || hit?.evidence?.length ? `<details class="anno-more"><summary>处理、费用与说明</summary><div class="anno-struct">${structure.map(line=>`<p>${escape(line)}</p>`).join('')}</div>${hit?.evidence?.length ? `<ul class="anno-evidence">${annoEvidenceItems(hit)}</ul>` : ''}${annoNotesHTML(effect.notes)}</details>` : ''}
    ${editable&&effect.annotated ? `<div class="anno-edit-fields"><label>补充效果标签<select data-anno-tag-add="${escape(effect.key)}"><option value="">选择标签…</option>${Object.values(registry.tags).filter(tag=>!tag.deprecated&&!(effect.tags||[]).includes(tag.id)).map(tag=>`<option value="${escape(tag.id)}">${escape(tag.name)}</option>`).join('')}</select></label>
      <label>个人备注<input data-anno-note-input="${escape(effect.key)}" value="${escape(annoUI.noteDrafts.get(`${code}:${effect.key}`) || '')}" placeholder="记录纠错或核对依据" maxlength="4000"></label><button type="button" data-anno-note="${escape(effect.key)}">保存备注</button></div>` : ''}
  </article>`;
}
function annoSourceHTML(source) {
  try {
    const url = new URL(source.url);
    if (url.protocol !== 'https:' || url.hostname !== 'www.db.yugioh-card.com' || url.username || url.password) return `<span>${escape(source.title)}（链接待核对）</span>`;
    return `<a href="${escape(url.href)}" data-anno-source target="_blank" rel="noopener noreferrer">${escape(source.title)} ↗</a><small> ${escape(source.format || '地区未注明')} · 核对 ${escape(source.checked_on)}</small>`;
  } catch { return `<span>${escape(source.title || '来源待补充')}</span>`; }
}
function annoDetailHTML(view, registry) {
  const editable = annoUI.editing && view.digest_ok;
  const rules = view.effects.filter(effect=>effect.effect_type==='non_effect');
  const effects = view.effects.filter(effect=>!rules.includes(effect));
  const buttons = [];
  if (editable) {
    if (view.provenance?.source === 'user-draft') buttons.push('<button type="button" data-anno-op="discard-draft">丢弃自动草稿</button>');
    else if (view.status === 'none') buttons.push('<button type="button" data-anno-op="draft">生成待核对草稿</button>');
    if (view.status !== 'none') {
      if (view.full && view.origin !== 'auto') buttons.push(`<button type="button" data-anno-op="set-review" data-value="confirmed" ${view.status==='confirmed'?'disabled':''}>确认已核对</button>`);
      buttons.push('<button type="button" data-anno-op="set-review" data-value="pending">标为待核对</button>');
      buttons.push('<button type="button" data-anno-op="set-review" data-value="">撤销个人核对标记</button>');
    }
  }
  return `<div class="anno-panel anno-detail"><div class="anno-detail-heading"><div><p class="anno-card-meta">${escape(annoCardKind(view.type))} · ${view.code}</p><h2>${escape(view.name)}</h2><div class="anno-card-labels">${annoStatusBadge(view.status)}${view.no_effect?'<span class="anno-badge">无效果</span>':''}</div></div>
    <button type="button" id="anno-edit-toggle" aria-pressed="${annoUI.editing}" ${view.digest_ok?'':'disabled'}>${annoUI.editing?'完成修正':'个人修正'}</button></div>
    ${!view.digest_ok ? '<p class="anno-warning">卡库卡文已变化。以下为旧版标注，不参与能力查询；个人资料保留，等待复核。</p>' : ''}
    ${annoUI.editing ? '<p class="anno-edit-hint">修改保存在本机。结构化标注由资料文件维护；自动草稿须逐段复核后才能作为参考。</p>' : ''}
    <div class="anno-detail-body">${view.no_effect ? `<div class="anno-empty">${escape(annoCardKind(view.type))} · 无效果文本</div><blockquote>${escape(view.effects.map(e=>e.text).join('\n') || (view.digest_ok ? view.current_text : '旧卡文未保存'))}</blockquote>` :
      `${rules.length ? `<details class="anno-rules"><summary>规则与次数限制 <small>${rules.length} 段</small></summary>${rules.map(effect=>annoEffectHTML(effect,registry,editable,view.code)).join('')}</details>` : ''}
      ${effects.map(effect=>annoEffectHTML(effect,registry,editable,view.code)).join('') || '<p class="anno-empty">暂无可展示效果。</p>'}`}
    ${view.relations?.length ? `<details class="anno-more"><summary>效果之间的关系</summary>${view.relations.map(relation=>`<p><b>${escape(annoRelationLabel(relation.kind))}</b> · ${escape((relation.effects||[]).map(key=>annoEffectLabel(view.effects.find(effect=>effect.key===key)||{key})).join('、'))}<br>${escape(relation.text)}</p>`).join('')}</details>` : ''}
    <details class="anno-more anno-provenance"><summary>资料来源与核对信息</summary>
      ${(view.sources||[]).map(source=>`<p>${annoSourceHTML(source)}</p>`).join('') || '<p>尚未补充外部来源。</p>'}
      <p>${escape(view.review?.basis || '尚未人工核对。')}</p>
      ${view.effects.some(effect=>effect.engine) ? '<p>脚本映射已核对：仅表示效果编号与本地脚本的对应，不表示完整裁定或当前局面可发动。</p>' : ''}
      ${annoNotesHTML(view.notes)}<p class="anno-fingerprint">卡文指纹：${escape(view.text_digest || '')}</p>
      ${!view.digest_ok ? `<h4>当前卡库原文（未套用旧标注）</h4><blockquote>${escape(view.current_text || '')}</blockquote>` : ''}
    </details><div class="anno-buttons">${buttons.join('')}</div></div></div>`;
}
function annoQueryBody(offset=0) {
  return {op:'query',offset,q:$('#anno-q')?.value||'',kind:$('#anno-kind')?.value||'',catalog_scope:$('#anno-catalog-scope')?.value||'annotated',
    tag:$('#anno-tag')?.value||'',action:$('#anno-action')?.value||'',from_zone:$('#anno-from')?.value||'',to_zone:$('#anno-to')?.value||'',usage:$('#anno-usage')?.value||'',cost_kind:$('#anno-cost')?.value||'',timing:$('#anno-timing')?.value||'',scope:$('#anno-scope')?.value||'effect',
    etags:[...annoUI.tags],etag_mode:$('#anno-etag-mode')?.value||'all',status:$('#anno-status-filter')?.value?[$('#anno-status-filter').value]:annoStatusOrder};
}
function annoTagChipsHTML(registry) {
  return Object.entries(registry.categories).map(([category,name])=>`<fieldset class="anno-tag-group"><legend>${escape(name)}</legend>${Object.values(registry.tags).filter(tag=>tag.category===category&&!tag.deprecated).map(tag=>`<button type="button" class="anno-tag" data-anno-etag="${escape(tag.id)}" aria-pressed="${annoUI.tags.has(tag.id)}" title="${escape(tag.definition)}">${escape(tag.name)}</button>`).join('')}</fieldset>`).join('');
}
function annoRenderShell() {
  $('#card-annotations').innerHTML=`<header class="anno-heading"><div><div class="eyebrow">CARD ANNOTATIONS</div><h1>卡片标注</h1><p>查阅效果，理解条件，积累可靠的卡片资料。</p></div><button type="button" id="anno-refresh">刷新资料</button></header>
    <div id="anno-overview"></div><div class="anno-panel anno-search-panel"><form id="anno-form">
      <div class="anno-search-row"><label class="anno-search-keyword">搜索卡片<input type="search" id="anno-q" placeholder="卡名、卡文或卡号" maxlength="120"></label>
      <label>卡片范围<select id="anno-catalog-scope"><option value="annotated">已标注卡片</option><option value="all">全部卡片</option></select></label>
      <label>类型<select id="anno-kind"><option value="">全部类型</option><option value="monster">怪兽</option><option value="spell">魔法</option><option value="trap">陷阱</option><option value="extra">额外卡组</option></select></label><button type="submit" class="primary">查询</button><button type="button" id="anno-reset">重置</button></div>
      <details id="anno-advanced" class="anno-more"><summary>效果与高级筛选 <span id="anno-filter-count"></span></summary><div id="anno-tagpool" class="anno-tagpool"></div><div class="anno-query">
        <label>关联标签<select id="anno-tag"></select></label><label>处理动作<select id="anno-action"></select></label><label>来源区域<select id="anno-from"></select></label><label>去向区域<select id="anno-to"></select></label><label>次数限制<select id="anno-usage"></select></label><label>费用<select id="anno-cost"></select></label><label>发动时点<select id="anno-timing"></select></label>
        <label>核对状态<select id="anno-status-filter"><option value="">全部状态</option>${annoStatusOrder.map(status=>`<option value="${status}">${annoStatusMeta[status].label}</option>`).join('')}</select></label>
        <label>条件范围<select id="anno-scope"><option value="effect">同一效果内满足</option><option value="card">允许跨效果满足</option></select></label><label>标签组合<select id="anno-etag-mode"><option value="all">全部符合</option><option value="any">任一符合</option></select></label></div>
        <p class="anno-help">能力条件仅检索已标注内容。不同效果或可选分支不代表可以同时使用。</p><button type="submit">应用筛选</button></details></form></div>
    <div class="anno-layout"><div class="anno-panel anno-results" id="anno-results"></div><div id="anno-detail" aria-live="polite"></div></div>`;
}
function annoFillSelects(registry, libraryTags) {
  const fill=(id,vocabulary)=>{const select=$('#'+id),value=select.value;select.innerHTML='<option value="">全部</option>'+Object.entries(vocabulary).map(([value,name])=>`<option value="${escape(value)}">${escape(name)}</option>`).join('');select.value=value;};
  fill('anno-action',registry.actions);fill('anno-from',registry.zones);fill('anno-to',registry.zones);fill('anno-usage',registry.usage_limits);fill('anno-cost',registry.cost_kinds);fill('anno-timing',registry.timings);fill('anno-tag',Object.fromEntries(libraryTags.map(tag=>[tag.id,tag.name])));
  $('#anno-tagpool').innerHTML=annoTagChipsHTML(registry);
}
function annoRenderDetail() {
  $('#anno-detail').innerHTML=annoUI.detail?annoDetailHTML(annoUI.detail,annoUI.registry):'<div class="anno-panel anno-empty">选择一张卡片查看标注。</div>';
  document.querySelectorAll('[data-anno-card]').forEach(node=>node.setAttribute('aria-pressed',String(Number(node.dataset.annoCard)===annoUI.detail?.code)));
}
async function annoLoadDetail(code) {
  const serial=++annoUI.detailSerial;
  $('#anno-detail').setAttribute('aria-busy','true');
  try {
    const view=await api('/api/annotations',{op:'card',code});
    if(serial!==annoUI.detailSerial)return;
    if(annoUI.detail?.code!==code)annoUI.editing=false;
    annoUI.detail=view;annoRenderDetail();
  } finally {if(serial===annoUI.detailSerial)$('#anno-detail').setAttribute('aria-busy','false');}
}
async function enterCardAnnotations() {
  if(!$('#anno-form'))annoRenderShell();
  annoUI.busy=true;
  try {
    const [snapshot,tags]=await Promise.all([api('/api/annotations'),api('/api/tags').catch(()=>({tags:[]}))]);
    annoUI.registry={...snapshot.registry,tags:Object.fromEntries(snapshot.registry.tags.map(tag=>[tag.id,tag]))};annoUI.libraryTags=tags.tags||[];annoUI.revision=snapshot.revision;
    annoFillSelects(annoUI.registry,annoUI.libraryTags);$('#anno-overview').innerHTML=annoOverviewHTML(snapshot.overview);
    await annoRunQuery(0);
  } finally {annoUI.busy=false;}
}
async function annoRunQuery(offset=0) {
  const serial=++annoUI.querySerial;
  ++annoUI.detailSerial;
  const result=await api('/api/annotations',annoQueryBody(offset));
  if(serial!==annoUI.querySerial)return;
  annoUI.results=result;$('#anno-results').innerHTML=annoResultsHTML(result);
  const code=result.cards.find(card=>card.code===annoUI.detail?.code)?.code||result.cards[0]?.code;
  if(code)await annoLoadDetail(code);else {annoUI.detail=null;annoUI.editing=false;annoRenderDetail();}
}
function annoUpdateFilterCount() {
  const body=annoQueryBody();
  const count=annoUI.tags.size+['tag','action','from_zone','to_zone','usage','cost_kind','timing'].filter(key=>body[key]).length+($('#anno-status-filter').value?1:0)+(body.scope==='card'?1:0)+(body.etag_mode==='any'?1:0);
  $('#anno-filter-count').textContent=count?`· 已选 ${count} 项`:'';
}
async function annoRunOp(body,message) {
  annoUI.busy=true;
  try {
    const result=await api('/api/annotations',body);if(result.revision!==undefined)annoUI.revision=result.revision;
    if(body.op==='add-note'&&annoUI.noteDrafts.get(`${body.code}:${body.key}`)?.trim()===body.text)annoUI.noteDrafts.delete(`${body.code}:${body.key}`);
    notice(message);$('#anno-overview').innerHTML=annoOverviewHTML(await api('/api/annotations',{op:'overview'}));await annoRunQuery(annoUI.results?.offset||0);
  } catch(error) {
    // Refresh the lock after a conflict without dropping unsaved note input.
    try {annoUI.revision=(await api('/api/annotations')).revision;} catch {}
    throw error;
  } finally {annoUI.busy=false;}
}
$('#card-annotations').addEventListener('click',run(async event=>{
  const reference=event.target.closest('[data-anno-source]');
  if(reference&&window.trainerDesktop?.openReferenceLink){event.preventDefault();await window.trainerDesktop.openReferenceLink(reference.href);return;}
  if(annoUI.busy)return;
  if(event.target.id==='anno-refresh')return await enterCardAnnotations();
  if(event.target.id==='anno-reset'){annoUI.tags.clear();annoUI.editing=false;annoRenderShell();return await enterCardAnnotations();}
  if(event.target.id==='anno-edit-toggle'){annoUI.editing=!annoUI.editing;annoRenderDetail();return;}
  const etag=event.target.closest('[data-anno-etag]');
  if(etag){const id=etag.dataset.annoEtag;annoUI.tags.has(id)?annoUI.tags.delete(id):annoUI.tags.add(id);etag.setAttribute('aria-pressed',String(annoUI.tags.has(id)));annoUpdateFilterCount();return;}
  const page=event.target.closest('[data-anno-page]');if(page&&!page.disabled)return await annoRunQuery(Number(page.dataset.annoPage));
  const card=event.target.closest('[data-anno-card]');if(card)return await annoLoadDetail(Number(card.dataset.annoCard));
  const remove=event.target.closest('[data-anno-tag-remove]');
  if(remove)return await annoRunOp({op:'set-tags',code:annoUI.detail.code,key:remove.dataset.annoTagRemove,add:[],remove:[remove.dataset.annoTag],revision:annoUI.revision},'已保存个人标签修正');
  const note=event.target.closest('[data-anno-note]');
  if(note){const input=$(`[data-anno-note-input="${note.dataset.annoNote}"]`);if(!input?.value.trim())return notice('请填写备注内容');return await annoRunOp({op:'add-note',code:annoUI.detail.code,key:note.dataset.annoNote,text:input.value.trim(),revision:annoUI.revision},'已保存个人备注');}
  const op=event.target.closest('[data-anno-op]');
  if(op)return await annoRunOp({op:op.dataset.annoOp,code:annoUI.detail.code,value:op.dataset.value||null,revision:annoUI.revision},'已更新标注状态');
}));
$('#card-annotations').addEventListener('change',run(async event=>{
  const add=event.target.closest('[data-anno-tag-add]');
  if(add?.value&&!annoUI.busy)return await annoRunOp({op:'set-tags',code:annoUI.detail.code,key:add.dataset.annoTagAdd,add:[add.value],remove:[],revision:annoUI.revision},'已保存个人标签修正');
  if(event.target.id==='anno-status-filter'&&event.target.value==='none')$('#anno-catalog-scope').value='all';
  annoUpdateFilterCount();
}));
$('#card-annotations').addEventListener('submit',run(async event=>{
  if(event.target.id==='anno-form'){event.preventDefault();if(!annoUI.busy){await annoRunQuery(0);$('#anno-advanced').open=false;}}
}));
$('#card-annotations').addEventListener('input',event=>{
  if(event.target.matches('[data-anno-note-input]')&&annoUI.detail)annoUI.noteDrafts.set(`${annoUI.detail.code}:${event.target.dataset.annoNoteInput}`,event.target.value);
});
