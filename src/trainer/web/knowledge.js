/* knowledge.js — 「知识包」工作区模块（本地 Electron 应用，纯浏览器端） */
(() => {
  'use strict';

  /* ================= 常量与公共状态 ================= */
  const KINDS = ['source', 'build', 'route', 'step', 'fragment', 'branch', 'endboard', 'countermeasure'];
  const KIND_LABEL = { source: '来源', build: '构筑', route: '展开', step: '步骤', fragment: '共用片段', branch: '妥协', endboard: '终场', countermeasure: '对策' };
  const REP_LABEL = { tutorial: '文字教程', strategy: '结构化策略', decisions: '原始决策记录' };
  const FIELD_LABEL = {
    content: '内容', url: '链接', note: '来源备注', notes: '使用说明', main: '主卡组', extra: '额外卡组', side: '副卡组',
    side_unknown: '含未知副卡组', conditions: '条件', cards: '卡片', action: '动作', costs: '费用', targets: '对象',
    limits: '限制', result: '结果', steps: '步骤', representation: '呈现方式', opening: '起手', anchor: '锚点步骤',
    route: '所属路线', timing: '时机', interference: '干扰', resources: '资源', continuation: '延续', constraints: '约束',
    effects: '效果', opponent: '对手', situation: '局面', responses: '应对', exceptions: '例外'
  };

  const knowledgeUI = {
    tab: 'installed', snapshot: null, project: null, packageView: null, selected: null,
    dirty: false, busy: false, edit: null,
    search: '', kindFilter: '', tagFilter: '', showDeleted: false,
    conflict: null, candidates: null, installPreview: null, error: '',
    decks: null, plans: null, sourceFile: null, projectBase:null, rawDraft:{}, publishVersion:'', renderEpoch:0,
    jobs:[],jobErrors:[],nativeStatus:{},jobForm:{route:'',build:'',hands:'',scenario:'none',seconds:15,nodes:160,depth:48},jobTimer:null
  };
  window.knowledgeUI = knowledgeUI;

  let knowledgeRoot = null;

  /* ================= 小工具 ================= */
  const rawEscape = (typeof escape === 'function' && escape('<') !== '<') ? escape : null;
  const esc = (v) => {
    const s = String(v == null ? '' : v);
    return rawEscape ? rawEscape(s) : s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  };
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const uid = () => (crypto.randomUUID ? crypto.randomUUID() : 'r-' + Date.now() + '-' + Math.random().toString(16).slice(2));
  const getPath = (obj, path) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), obj);
  const setPath = (obj, path, v) => {
    const ks = path.split('.'); let o = obj;
    for (let i = 0; i < ks.length - 1; i++) { if (typeof o[ks[i]] !== 'object' || o[ks[i]] === null) o[ks[i]] = {}; o = o[ks[i]]; }
    o[ks[ks.length - 1]] = v;
  };
  const cardsText = (list) => (Array.isArray(list) ? list.join('\n') : '');
  const parseCards = (text) => String(text || '').split(/[\s,;，；]+/).map((s) => s.trim()).filter(Boolean).map(value=>{
    const code=Number(value);
    if(!/^\d+$/.test(value)||!Number.isInteger(code)||code<=0||code>0xffffffff)throw Error('卡号需要正整数，以空格或换行分隔；重复卡号表示张数');
    return code;
  });
  const draftKey=el=>(el.dataset.kScope==='doc'?'doc':`edit:${knowledgeUI.selected}`)+':'+el.dataset.kBind;
  const recordLabel = (id, doc) => { const r = doc && doc.records && doc.records[id]; return r ? (r.title || r.id) : String(id); };
  const tagLabel = (id) => { const t = knowledgeUI.snapshot && knowledgeUI.snapshot.tags && knowledgeUI.snapshot.tags.find((x) => x.id === id); return t ? (t.name || id) : '未解析:' + id; };
  const packageName = (id) => { const p = ((knowledgeUI.snapshot || {}).packages || []).find((x) => x.id === id); return p ? (p.name || id) : id; };
  const briefJSON = (v) => { const s = JSON.stringify(v); return s && s.length > 160 ? s.slice(0, 160) + '…' : (s || '—'); };
  const safeName = (s) => String(s || 'knowledge').replace(/[\\/:*?"<>|]+/g, '_');
  const optionHTML = (value, current, text) => `<option value="${esc(value)}" ${String(current) === String(value) ? 'selected' : ''}>${esc(text)}</option>`;
  const currentDoc = () => knowledgeUI.tab === 'projects'
    ? (knowledgeUI.project && knowledgeUI.project.document)
    : (knowledgeUI.packageView && knowledgeUI.packageView.document);

  function downloadJSON(name, obj) {
    const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  /* ================= 应用内对话框（不使用浏览器 confirm/prompt） ================= */
  function dialog(opts) {
    return new Promise((resolve) => {
      const root = knowledgeRoot;
      if (!root) { resolve(null); return; }
      const layer = document.createElement('dialog');
      layer.className = 'knowledge-confirm';
      layer.setAttribute('role', 'dialog');
      layer.setAttribute('aria-modal', 'true');
      layer.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;max-width:none;max-height:none;box-sizing:border-box;margin:0;border:0;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;z-index:20000;color:var(--text-main)';
      layer.innerHTML = `<div class="knowledge-dialog knowledge-status" style="background:var(--surface-panel);color:inherit;padding:22px;max-width:42em;max-height:85vh;overflow:auto;margin:1em;border-radius:12px">
        <h3>${esc(opts.title || '')}</h3>
        ${opts.message ? `<p>${esc(opts.message)}</p>` : ''}
        ${opts.warning ? `<p class="knowledge-error" role="alert">${esc(opts.warning)}</p>` : ''}
        ${opts.input ? `<label class="knowledge-field">${esc(opts.input.label || '')}<input type="text" value="${esc(opts.input.value || '')}"></label>` : ''}
        ${opts.checkbox ? `<label class="knowledge-field"><input type="checkbox" ${opts.checkbox.checked ? 'checked' : ''}> ${esc(opts.checkbox.label || '')}</label>` : ''}
        <div class="knowledge-toolbar"><button data-c="ok">${esc(opts.okLabel || '确定')}</button><button data-c="cancel">取消</button></div></div>`;
      const input = layer.querySelector('input[type="text"]');
      const cb = layer.querySelector('input[type="checkbox"]');
      const previousFocus=document.activeElement;
      const done = (v) => { layer.close();layer.remove(); previousFocus?.focus(); resolve(v); };
      layer.addEventListener('click', (e) => {
        const b = e.target.closest('button'); if (!b) return;
        if (b.dataset.c !== 'ok') { done(null); return; }
        done(input || cb ? { value: input ? input.value : '', checked: cb ? cb.checked : false } : true);
      });
      layer.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') done(null);
        else if (e.key === 'Enter' && input) done({ value: input.value, checked: cb ? cb.checked : false });
        else if(e.key==='Tab'){
          const controls=[...layer.querySelectorAll('input,button')],first=controls[0],last=controls.at(-1);
          if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
          else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
        }
      });
      root.appendChild(layer);
      layer.showModal();
      (input||layer.querySelector('button')).focus();
    });
  }

  async function confirmDiscard() {
    if (!knowledgeUI.dirty) return true;
    const msg = (window.knowledgeUnsavedSummary && knowledgeUnsavedSummary()) || '当前有未保存的修改';
    if (typeof confirmFlow === 'function') return await confirmFlow('保留当前输入？', msg + '。继续操作将放弃这些修改。', '放弃修改');
    return await dialog({ title: '保留当前输入？', message: msg + '。继续操作将放弃这些修改。', okLabel: '放弃修改' });
  }

  function discardEdits() {
    if (knowledgeUI.packageView && knowledgeUI.packageView.editing) {
      knowledgeUI.packageView.editing = false; knowledgeUI.edit = null;
    } else if (knowledgeUI.tab === 'projects' && knowledgeUI.dirty && knowledgeUI.project) {
      knowledgeUI.project = clone(knowledgeUI.projectBase); knowledgeUI.edit = null; knowledgeUI.candidates = null;
    }
    knowledgeUI.dirty = false;
    knowledgeUI.rawDraft={};
  }

  /* ================= 错误与忙态 ================= */
  function fail(err) {
    const msg = String((err && (err.message || err.error || err.reason)) || err || '操作失败');
    knowledgeUI.error = msg;
    notice(msg);
    const box=$('#knowledge-error');if(box){box.textContent=msg;box.hidden=false;}
  }
  function setBusy(b) {
    knowledgeUI.busy = b;
    if (knowledgeRoot) knowledgeRoot.querySelectorAll('button,input,select,textarea').forEach((el) => { el.disabled = b; });
  }
  async function act(fn) {
    if (knowledgeUI.busy || !knowledgeRoot) return;
    setBusy(true);
    try { await fn(); knowledgeUI.error = ''; }
    catch (err) { fail(err); }
    finally { knowledgeUI.busy = false; render(); }
  }

  /* ================= 数据获取 ================= */
  async function fetchSummary() { knowledgeUI.snapshot = await api('/api/knowledge'); return knowledgeUI.snapshot; }

  async function loadSourceLists() {
    try {
      knowledgeUI.decks = await api('/api/decks');
      let plans = await api('/api/plans') || [];
      plans = await Promise.all(plans.map(async (p) => p.edit_revision != null
        ? p
        : { ...p, edit_revision: (await api('/api/plan/' + encodeURIComponent(p.id))).edit_revision }));
      knowledgeUI.plans = plans;
      fillSelects();
    } catch (err) { fail(new Error('导入来源列表读取失败：'+err.message)); const el=$('#knowledge-error');if(el){el.textContent=knowledgeUI.error;el.hidden=false;} }
  }
  function fillSelects() {
    const d = document.getElementById('k-source-deck'), p = document.getElementById('k-source-plan');
    if (d) {const selected=d.value;d.innerHTML = '<option value="">选择卡组…</option>' + (knowledgeUI.decks || []).map((x) => optionHTML(x.id, selected, x.name)).join('');}
    if (p) {const selected=p.value;p.innerHTML = '<option value="">选择方案…</option>' + (knowledgeUI.plans || []).map((x) => optionHTML(x.id, selected, x.name)).join('');}
  }

  /* ================= 表单绑定（scope: doc=项目文档, edit=当前记录副本） ================= */
  function bindInput(el) {
    const scope = el.dataset.kScope === 'doc' ? currentDoc() : knowledgeUI.edit;
    if (!scope) return;
    let val;
    if(el.dataset.kType==='side-unknown'){
      const field=knowledgeRoot.querySelector('textarea[data-k-bind="data.side"]');
      val=el.checked?null:parseCards(field?.value||'');if(field)field.disabled=el.checked;
    }
    else if (el.type === 'checkbox') val = el.checked;
    else if (el.dataset.kType === 'cards') {if(el.disabled)return;val = parseCards(el.value);}
    else if (el.dataset.kType === 'lines') val = el.value.split('\n').map((x) => x.trim()).filter(Boolean);
    else if (el.dataset.kType === 'refs') val = Array.from(el.selectedOptions || []).map((o) => clone((scope.refs||[]).find(r=>r.id===o.value)||{ id: o.value, relation: 'uses' }));
    else if (el.dataset.kType === 'json') {
      if (el.value === (el.dataset.kOriginal || '')) return; /* 未改动则原样保留对象 */
      try { val = JSON.parse(el.value || 'null'); el.setCustomValidity(''); }
      catch (err) { el.setCustomValidity('JSON 格式错误'); throw new Error('高级 JSON 字段格式错误（' + el.dataset.kBind + '）'); }
    }
    else if (el.tagName === 'SELECT' && el.multiple) val = Array.from(el.selectedOptions || []).map((o) => o.value);
    else val = el.value;
    setPath(scope, el.dataset.kBind, val);
    knowledgeUI.dirty = true;
    const chip = document.getElementById('knowledge-dirty');
    if (chip) chip.hidden = false;
  }
  function flushBinds() {
    if (!knowledgeRoot) return;
    knowledgeRoot.querySelectorAll('[data-k-bind]').forEach((el) => {if(el.dataset.kTouched==='1')bindInput(el);});
  }

  /* ================= 渲染 ================= */
  function render() {
    if (!knowledgeRoot) return;
    const sidebarScroll=knowledgeRoot.querySelector('.knowledge-sidebar')?.scrollTop||0;
    const s = knowledgeUI;
    const sidebar = s.tab === 'projects'
      ? (s.project ? recordSidebarHTML(s.project.document, true) : projectListHTML())
      : (s.packageView ? recordSidebarHTML(s.packageView.document, false) : packageListHTML());
    knowledgeRoot.innerHTML = `<div class="knowledge-workspace">
      ${headerHTML()}
      <div id="knowledge-error" class="knowledge-error" role="alert" ${s.error ? '' : 'hidden'}>${esc(s.error)}</div>
      <div class="knowledge-layout">
        <aside class="knowledge-sidebar">${sidebar}</aside>
        <section class="knowledge-main">${s.tab === 'projects' ? projectMainHTML() : packageMainHTML()}</section>
      </div>
      <input type="file" id="knowledge-file-input" accept=".json,.ydk,.txt" hidden>
      <input type="file" id="knowledge-source-file-input" accept=".json,.ydk,.txt" hidden>
      <input type="file" id="knowledge-install-input" accept=".json" hidden>
    </div>`;
    fillSelects();
    const sidebarElement=knowledgeRoot.querySelector('.knowledge-sidebar');if(sidebarElement)sidebarElement.scrollTop=sidebarScroll;
    for(const el of knowledgeRoot.querySelectorAll('[data-k-bind]')){
      const raw=knowledgeUI.rawDraft[draftKey(el)];
      if(raw!==undefined&&el.type!=='checkbox'&&!(el.tagName==='SELECT'&&el.multiple)){el.value=raw;el.dataset.kTouched='1';}
    }
    const epoch=++knowledgeUI.renderEpoch;
    if(typeof card==='function')for(const el of knowledgeRoot.querySelectorAll('[data-knowledge-card-name]')){
      card(Number(el.dataset.knowledgeCardName)).then(value=>{if(epoch===knowledgeUI.renderEpoch&&el.isConnected)el.textContent=value.name;}).catch(()=>{});
    }
  }

  function headerHTML() {
    const s = knowledgeUI;
    const toolbar = s.tab === 'projects'
      ? `<button data-k-action="project-new">新建项目</button>
         <button data-k-action="project-sample">示例项目</button>
         <button id="knowledge-file" data-k-action="project-import-file">导入文件</button>`
      : `<button data-k-action="install-file">安装知识包文件</button>`;
    return `<header class="knowledge-header">
      <h1>知识包</h1>
      <nav class="knowledge-tabs" role="tablist">
        <button role="tab" aria-selected="${s.tab === 'installed'}" class="${s.tab === 'installed' ? 'active' : ''}" data-k-action="tab" data-tab="installed">已安装</button>
        <button role="tab" aria-selected="${s.tab === 'projects'}" class="${s.tab === 'projects' ? 'active' : ''}" data-k-action="tab" data-tab="projects">制作项目</button>
      </nav>
      <div class="knowledge-toolbar">${toolbar}<button data-k-action="refresh">刷新列表</button></div>
    </header>`;
  }

  function projectListHTML() {
    const items = (knowledgeUI.snapshot && knowledgeUI.snapshot.projects) || [];
    const li = items.length
      ? items.map((p) => `<li><button class="knowledge-record" data-k-action="project-open" data-id="${esc(p.id)}">
          <strong>${esc(p.name)}</strong><span class="knowledge-muted">${esc(p.theme || '未设主题')}${p.updated ? ' · ' + esc(p.updated) : ''}</span>
        </button></li>`).join('')
      : '<li class="knowledge-muted">还没有项目，点上方「新建项目」开始。</li>';
    return `<ul class="knowledge-records">${li}</ul>`;
  }

  function packageListHTML() {
    const snap = knowledgeUI.snapshot || {};
    const items = snap.packages || [];
    const po = snap.personal_overrides;
    const n = typeof po==='number'?po:Array.isArray(po) ? po.length : (po && typeof po === 'object' ? Object.keys(po).length : 0);
    const li = items.length
      ? items.map((p) => `<li><button class="knowledge-record" data-k-action="package-open" data-id="${esc(p.id)}">
          <strong>${esc(p.name)}</strong>
          <span class="knowledge-muted">${p.active ? '版本 ' + esc(p.active) : '未启用'} · ${p.enabled ? '已启用' : '已停用'}${(p.versions || []).length ? ' · ' + p.versions.length + ' 个已装版本' : ''}${p.status ? ' · ' + esc(p.status) : ''}</span>
          <small>${esc(p.environment||'适用环境见版本详情')}${p.counts?` · 构筑 ${p.counts.build||0} / 展开 ${p.counts.route||0}`:''}</small>
        </button></li>`).join('')
      : '<li class="knowledge-muted">还没有安装知识包。</li>';
    return `<ul class="knowledge-records">${li}</ul>${n ? '<p class="knowledge-muted">已有 ' + n + ' 项个人覆盖修改</p>' : ''}`;
  }

  function recordSidebarHTML(doc, editable) {
    const s = knowledgeUI;
    const tags = (s.snapshot && s.snapshot.tags) || [];
    const kinds = [...new Set(Object.values(doc.records).map((r) => r.kind).filter(Boolean))];
    return `
      <div class="knowledge-toolbar">
        <button data-k-action="${editable ? 'project-back' : 'package-back'}">‹ 返回${editable ? '项目' : '知识包'}列表</button>
        <input type="search" placeholder="搜索标题 / 类型…" value="${esc(s.search)}" data-k-role="search" aria-label="搜索记录">
        <select data-k-role="filter-kind" aria-label="按类型筛选">
          <option value="">全部类型</option>${kinds.map((k) => optionHTML(k, s.kindFilter, KIND_LABEL[k] || k)).join('')}
        </select>
        <select data-k-role="filter-tag" aria-label="按标签筛选">
          <option value="">全部标签</option>${tags.map((t) => optionHTML(t.id, s.tagFilter, t.name || t.id)).join('')}
        </select>
        <label class="knowledge-muted"><input type="checkbox" data-k-role="filter-deleted" ${s.showDeleted ? 'checked' : ''}> 显示已删除</label>
        ${editable ? `<div class="knowledge-field"><label for="k-add-kind">新增记录</label>
          <div class="knowledge-toolbar"><select id="k-add-kind" data-k-role="add-kind" aria-label="新增记录类型">${KINDS.map((k) => optionHTML(k, '', KIND_LABEL[k])).join('')}</select>
          <button data-k-action="record-add">新增记录</button></div></div>` : ''}
      </div>
      <ul class="knowledge-records" id="knowledge-record-list">${recordListHTML(doc)}</ul>`;
  }

  function filteredRecords(doc) {
    const s = knowledgeUI;
    const q = s.search.trim().toLowerCase();
    return Object.values(doc.records).filter((r) => {
      if (r.deleted && !s.showDeleted) return false;
      if (s.kindFilter && r.kind !== s.kindFilter) return false;
      if (s.tagFilter && !(r.tags || []).includes(s.tagFilter)) return false;
      if (q && !((r.title || '') + ' ' + (KIND_LABEL[r.kind] || r.kind || '') + ' ' + (r.id || '')).toLowerCase().includes(q)) return false;
      return true;
    });
  }
  function recordListHTML(doc) {
    const list = filteredRecords(doc);
    if (!list.length) return '<li class="knowledge-muted">没有匹配的记录</li>';
    return list.map((r) => `<li><button class="knowledge-record ${knowledgeUI.selected === r.id ? 'active' : ''}" data-k-action="record-select" data-id="${esc(r.id)}">
        <strong>${esc(r.title || '（无标题）')}</strong>
        <span class="knowledge-muted">${esc(KIND_LABEL[r.kind] || r.kind || '')}${r.deleted ? ' · 已删除' : ''}</span>
      </button></li>`).join('');
  }
  function refreshRecordList() {
    const doc = currentDoc();
    const ul = document.getElementById('knowledge-record-list');
    if (doc && ul) ul.innerHTML = recordListHTML(doc);
  }

  /* ---------- 项目主区 ---------- */
  function projectMainHTML() {
    const p = knowledgeUI.project;
    if (!p) return '<p class="knowledge-muted">选择左侧项目，或新建 / 导入一个知识包项目。</p>';
    const doc = p.document, pkg = doc.package || {};
    const editing = knowledgeUI.selected && knowledgeUI.edit;
    return `
      <div class="knowledge-toolbar">
        <button id="knowledge-save" data-k-action="save">保存</button>
        <button data-k-action="review-structure">结构检查</button>
        <button data-k-action="review-human">人工复核</button>
        <span class="knowledge-field"><label for="knowledge-publish-version">发布版本号</label>
          <input id="knowledge-publish-version" value="${esc(knowledgeUI.publishVersion)}" placeholder="如 1.0.0"></span>
        <button id="knowledge-publish" data-k-action="publish">发布并下载</button>
        <button data-k-action="export">导出项目</button>
        <button data-k-action="duplicates">查找重复</button>
        <span id="knowledge-dirty" class="knowledge-status" role="status" ${knowledgeUI.dirty ? '' : 'hidden'}>未保存</span>
      </div>
      <details class="knowledge-project-settings"><summary>${esc(pkg.name||'制作项目')} · ${esc(pkg.environment||'尚未设置适用环境')} · 项目信息</summary><div class="knowledge-form">
        <div class="knowledge-grid">
          <label class="knowledge-field">项目名称<input data-k-scope="doc" data-k-bind="package.name" value="${esc(pkg.name || '')}"></label>
          <label class="knowledge-field">主题<input data-k-scope="doc" data-k-bind="package.theme" value="${esc(pkg.theme || '')}"></label>
          <label class="knowledge-field">版本<output>${esc(pkg.version || '—')}</output></label>
          <label class="knowledge-field">适用环境<input data-k-scope="doc" data-k-bind="package.environment" value="${esc(pkg.environment || '')}" placeholder="例如 Master Duel · 资料日期与禁限版本"></label>
          <label class="knowledge-field">最低应用版本<input data-k-scope="doc" data-k-bind="package.app_min" value="${esc(pkg.app_min||'1.42.0')}"></label>
        </div>
      </div></details>
      ${editing ? recordEditorHTML(knowledgeUI.edit, doc, false) : '<p class="knowledge-muted">在左侧选择或新增一条记录开始编辑。</p>'}
      ${importSourcesHTML()}
      ${jobsHTML()}
      ${duplicatesHTML()}
      ${inspectionHTML(p.inspection, doc, p.impact)}
      ${provenanceHTML(p)}`;
  }

  function importSourcesHTML() {
    return `<details class="knowledge-source"><summary>导入来源（已存卡组 / 已存方案 / 原始文件）</summary>
      <div class="knowledge-grid">
        <label class="knowledge-field">从已存卡组导入（显式保存的卡组）<select id="k-source-deck" data-k-role="source-deck"><option value="">选择卡组…</option></select></label>
        <label class="knowledge-field">从已存方案导入<select id="k-source-plan" data-k-role="source-plan"><option value="">选择方案…</option></select></label>
      </div>
      <div class="knowledge-toolbar">
        <button data-k-action="import-deck">导入所选卡组</button>
        <button data-k-action="import-plan">导入所选方案</button>
        <button data-k-action="import-file">导入原始文件（.json/.ydk/.txt）</button>
      </div></details>`;
  }

  function duplicatesHTML() {
    const c = knowledgeUI.candidates;
    if (!c || !knowledgeUI.project) return '';
    const doc = knowledgeUI.project.document;
    const groups = (c.duplicates || []).map((g, i) => `<li>第 ${i + 1} 组：${g.map((id) => `<button class="knowledge-record" data-k-action="record-select" data-id="${esc(id)}">${esc(recordLabel(id, doc))}</button>`).join('、')}</li>`).join('');
    return `<details class="knowledge-issues" ${(c.duplicates || []).length ? 'open' : ''}><summary>重复候选</summary>
      <p class="knowledge-muted">${esc(c.note || '以下记录可能重复，请人工确认。')}</p>
      <ul>${groups || '<li class="knowledge-muted">未发现重复候选</li>'}</ul></details>`;
  }

  function inspectionHTML(insp, doc, impact) {
    if (!insp) return '';
    const issues = (insp.issues || []).map((is) => `<li class="${is.blocking ? 'knowledge-error' : ''}">${is.blocking ? '【阻断】' : ''}${esc(recordLabel(is.record, doc))}：${esc(is.message || is.code || '')}</li>`).join('');
    const counts = Object.entries(insp.counts || {}).map(([k, v]) => `${esc(KIND_LABEL[k] || k)} ${esc(v)}`).join(' · ');
    const checks = (insp.checks || []).map((c) => `<li>${esc(({structure:'结构检查',human:'人工核对',engine:'规则引擎记录',strategy:'策略评估'})[c.type]||'检查')}（${esc(({passed:'通过记录',failed:'未通过',stale:'待复核',unknown:'未确认'})[c.state]||'未知')}）${c.note ? '：' + esc(c.note) : ''}${c.target ? ' · 对象：' + esc(recordLabel(c.target, doc)) : ''}</li>`).join('');
    const caps = insp.capabilities || {};
    return `<section class="knowledge-issues"><h3>检查与影响</h3>
      <p class="knowledge-status">${counts || '暂无统计'} <span class="knowledge-muted">资料浏览 · ${caps.execute ? '引擎已接入' : '未接入执行'}</span></p>
      <h4>问题</h4><ul>${issues || '<li class="knowledge-muted">无已知问题</li>'}</ul>
      ${checks ? '<h4>随内容保存的检查记录</h4><p class="knowledge-muted">记录只证明所列版本与场景；包内声明不直接授予本机计算或执行资格。</p><ul>' + checks + '</ul>' : '<p class="knowledge-muted">尚无核对记录。</p>'}
      ${impactHTML(impact)}</section>`;
  }
  function impactHTML(impact) {
    if (!impact) return '';
    const counts = `修改 ${(impact.changed||[]).length} 项，影响 ${(impact.affected||[]).length} 项，可复用 ${(impact.reused||[]).length} 项，失效验证 ${(impact.checks_stale||[]).length} 项`;
    const names = Array.isArray(impact.affected)
      ? impact.affected.map((a) => esc(typeof a === 'string' ? a : ((a && (a.name || a.title || a.id)) || ''))).filter(Boolean).join('、')
      : '';
    if (!counts && !names) return '';
    return `<h4>影响</h4>${impact.environment_changed?'<p>适用环境或全局约束已改变，相关内容需要重新核对。</p>':''}<p>${counts ? '计数：' + counts : ''}${counts && names ? '；' : ''}${names ? '涉及：' + names : ''}</p>`;
  }
  function provenanceHTML(p) {
    return `<details class="knowledge-source"><summary>来源与版本信息</summary><dl>
      <dt>项目 ID</dt><dd>${esc(p.id)}</dd>
      <dt>修订号</dt><dd>${esc(p.revision)}</dd>
      <dt>更新时间</dt><dd>${esc(p.updated || '—')}</dd>
    </dl></details>`;
  }

  function jobRowsHTML(){
    const labels={queued:'排队中',running:'校验中',completed:'场景检查完成',cancelled:'已取消',paused:'已暂停',failed:'任务失败',stale:'输入过期'};
    return knowledgeUI.jobs.map(job=>`<article class="knowledge-status"><strong>${esc(labels[job.status]||job.status)}</strong>
      <p>完成 ${job.completed}/${job.case_count} 场景 · 复用 ${job.reused} 场景 · ${esc(job.progress?.phase||'')} ${job.progress?.nodes!=null?'已检查 '+esc(job.progress.nodes)+' 个节点':''}</p>
      <p class="knowledge-muted">每场搜索预算 ${esc(job.limits.seconds)} 秒 / ${esc(job.limits.nodes)} 节点 / ${esc(job.limits.depth)} 深度。${esc(job.overhead_note||'')}</p>
      ${job.cases.map(c=>`<p>${esc(c.hand.join(' '))} · ${c.scenario==='ash'?'限定灰流丽场景':'无额外干扰'}：${esc(({passed:'确认通过',unknown:'未确认',pending:'待处理',running:'处理中',failed:'未通过'})[c.status]||c.status)} ${esc(c.note||'')}</p>`).join('')}
      ${job.error?`<p class="knowledge-error">${esc(job.error)}</p>`:''}
      ${['queued','running'].includes(job.status)?`<button data-k-action="job-cancel" data-id="${esc(job.id)}">取消此任务</button>`:''}
      ${['cancelled','paused','failed'].includes(job.status)?`<button data-k-action="job-resume" data-id="${esc(job.id)}">从已完成场景继续</button>`:''}</article>`).join('')
      +knowledgeUI.jobErrors.map(e=>`<p class="knowledge-error">${esc(e.error)}</p>`).join('');
  }

  function jobsHTML(){
    const doc=knowledgeUI.project?.document;if(!doc)return '';
    const routes=Object.values(doc.records).filter(r=>!r.deleted&&r.kind==='route'&&r.data.representation==='decisions'&&r.data.plan);
    const form=knowledgeUI.jobForm;
    if(!routes.some(r=>r.id===form.route)&&routes.length){
      form.route=routes[0].id;form.build=(routes[0].refs||[]).find(ref=>doc.records[ref.id]?.kind==='build')?.id||'';
      form.hands=(routes[0].data.plan.initial_hand||[]).map(c=>c.code).join(' ');
    }
    const builds=Object.values(doc.records).filter(r=>!r.deleted&&r.kind==='build');
    return `<section id="knowledge-jobs"><details class="knowledge-project-settings" ${knowledgeUI.jobs.length?'open':''}><summary>规则验证与任务 · ${routes.length} 条原始决策路线 · ${knowledgeUI.jobs.length} 个任务</summary>
      <p class="knowledge-muted">仅核对所选记录、构筑、起手与干扰场景。文字步骤不会自动变成引擎动作，也不会训练模型或操作实际对局。</p>
      ${routes.length?`<div class="knowledge-grid">
        <label class="knowledge-field">验证路线<select data-k-job="route">${routes.map(r=>optionHTML(r.id,form.route,r.title)).join('')}</select></label>
        <label class="knowledge-field">适用构筑<select data-k-job="build">${builds.map(r=>optionHTML(r.id,form.build,r.title)).join('')}</select></label>
        <label class="knowledge-field">已确认起手（每行一组卡号，最多 8 组）<textarea data-k-job="hands">${esc(form.hands)}</textarea></label>
        <label class="knowledge-field">干扰场景<select data-k-job="scenario">${optionHTML('none',form.scenario,'无额外干扰')}${optionHTML('ash',form.scenario,'仅现有灰流丽场景')}</select></label>
        ${[['seconds','每场搜索秒数',32],['nodes','节点预算',320],['depth','决策深度',128]].map(([key,label,max])=>`<label class="knowledge-field">${label}<input type="number" min="1" max="${max}" data-k-job="${key}" value="${esc(form[key])}"></label>`).join('')}
      </div><p class="knowledge-muted">${esc(knowledgeUI.nativeStatus[form.route]?.reason||'提交时核对原始决策、依赖与本机规则版本。')}</p>
      <button data-k-action="job-start" ${knowledgeUI.dirty?'disabled':''}>开始限定场景验证</button>`:'<p>当前只有文字或结构化策略资料。请先导入具备原始决策证据的正式展开记录；本入口不会根据文字猜测动作。</p>'}
      <button data-k-action="jobs-refresh">刷新验证与任务</button><div id="knowledge-job-list">${jobRowsHTML()}</div></details></section>`;
  }

  async function refreshJobs(syncProject=false){
    clearTimeout(knowledgeUI.jobTimer);
    const project=knowledgeUI.project;if(!project)return;
    const previous=knowledgeUI.jobs.some(j=>['running','queued'].includes(j.status));
    const [list,status]=await Promise.all([api('/api/knowledge',{op:'job.list',project_id:project.id}),api('/api/knowledge',{op:'project.verification-status',id:project.id})]);
    if(knowledgeUI.project?.id!==project.id)return;
    knowledgeUI.jobs=list.jobs;knowledgeUI.jobErrors=list.errors;knowledgeUI.nativeStatus=status;
    const running=list.jobs.some(j=>['running','queued'].includes(j.status));
    if(syncProject||(previous&&!running)){
      const latest=await api('/api/knowledge',{op:'project.get',id:project.id});
      if(knowledgeUI.project?.id!==project.id)return;
      const content=d=>JSON.stringify({...d,checks:[]});
      if(!knowledgeUI.dirty){
        knowledgeUI.project=latest;knowledgeUI.projectBase=clone(latest);
        if(knowledgeUI.selected)knowledgeUI.edit=clone(latest.document.records[knowledgeUI.selected]);
      }else if(content(latest.document)===content(knowledgeUI.projectBase.document)){
        // Only independently produced validation records changed; preserve every unsaved edit.
        project.revision=latest.revision;project.document.checks=clone(latest.document.checks);
        project.inspection=latest.inspection;knowledgeUI.projectBase=clone(latest);
      }
    }
    const panel=$('#knowledge-job-list');if(panel)panel.innerHTML=jobRowsHTML();
    if(running&&typeof moduleUI!=='undefined'&&moduleUI.current==='knowledge'){
      knowledgeUI.jobTimer=setTimeout(()=>{if(moduleUI.current==='knowledge')void refreshJobs(false).catch(fail);},1200);
    }
  }

  async function startJob(){
    if(knowledgeUI.dirty){notice('请先保存制作项目，再固定验证输入');return;}
    const form=knowledgeUI.jobForm,project=knowledgeUI.project;if(!project)return;
    const cases=form.hands.split('\n').map(line=>line.trim()).filter(Boolean).map(line=>({hand:parseCards(line),scenario:form.scenario}));
    await act(async()=>{
      await api('/api/knowledge',{op:'job.start',project_id:project.id,route_id:form.route,build_id:form.build,cases,
        limits:{seconds:Number(form.seconds),nodes:Number(form.nodes),depth:Number(form.depth)}});
      await refreshJobs(false);notice('已提交规则校验；可以取消，并从已完成场景恢复');
    });
  }

  /* ---------- 记录编辑器 ---------- */
  function recordEditorHTML(rec, doc, overlay) {
    return `<section class="knowledge-form" id="knowledge-editor">
      <h3>${overlay ? '编辑个人副本' : '记录编辑'}${rec.deleted ? '（已删除）' : ''}</h3>
      <div class="knowledge-grid">
        <label class="knowledge-field">标题<input data-k-scope="edit" data-k-bind="title" value="${esc(rec.title || '')}"></label>
        <label class="knowledge-field">类型<output>${esc(KIND_LABEL[rec.kind] || rec.kind || '')}</output></label>
        </div><details class="knowledge-record-settings"><summary>分类与关联 · ${(rec.tags||[]).length} 个 TAG · ${(rec.refs||[]).length} 个引用</summary><div class="knowledge-grid">
        <label class="knowledge-field">标签（可多选）<select multiple size="5" data-k-scope="edit" data-k-bind="tags">${tagOptions(rec)}</select></label>
        <label class="knowledge-field">依赖的内容与来源<select multiple size="5" data-k-scope="edit" data-k-bind="refs" data-k-type="refs">${refOptions(rec, doc)}</select></label>
        <label class="knowledge-field">整理备注（仅展示，不改变适用条件）<textarea data-k-scope="edit" data-k-bind="editor_note">${esc(rec.editor_note||'')}</textarea></label>
      </div></details>
      ${kindEditorHTML(rec, doc)}
      ${relatedHTML(rec, doc)}
      <div class="knowledge-toolbar">
        ${overlay
          ? '<button data-k-action="overlay-save">保存个人修改</button><button data-k-action="overlay-cancel">停止编辑</button>'
          : `<button data-k-action="record-delete">${rec.deleted ? '恢复记录' : '标记删除'}</button>`}
      </div>
    </section>`;
  }

  function tagOptions(rec) {
    const tags = (knowledgeUI.snapshot && knowledgeUI.snapshot.tags) || [];
    const known = new Set(tags.map((t) => t.id));
    const used = rec.tags || [];
    const unknown = used.filter((t) => !known.has(t));
    return tags.map((t) => optionHTML(t.id, used.includes(t.id) ? t.id : '', (t.name || t.id) + ((t.aliases || []).length ? '（' + t.aliases.join('、') + '）' : ''))).join('')
      + unknown.map((t) => optionHTML(t, t, '未解析：' + t)).join('');
  }
  function refOptions(rec, doc) {
    const options=Object.values(doc.records)
      .filter((r) => !r.deleted && r.id !== rec.id)
      .map((r) => optionHTML(r.id, (rec.refs || []).some((x) => x.id === r.id) ? r.id : '', (r.title || '（无标题）') + '（' + (KIND_LABEL[r.kind] || r.kind || '') + '）')).join('');
    return options+(rec.refs||[]).filter(ref=>!doc.records[ref.id]||doc.records[ref.id].deleted).map(ref=>optionHTML(ref.id,ref.id,'待修复引用：'+ref.id)).join('');
  }
  function dependencyIds(rec){return [...new Set([...(rec.refs||[]).map(x=>x.id),...(rec.data?.steps||[]),...['anchor','route'].map(k=>rec.data?.[k]).filter(Boolean)])];}
  function relatedHTML(rec, doc) {
    const deps = dependencyIds(rec).filter((id) => doc.records[id]);
    const rev = Object.values(doc.records).filter((r) => !r.deleted&&dependencyIds(r).includes(rec.id));
    const link = (id) => `<button class="knowledge-record" data-k-action="record-select" data-id="${esc(id)}">${esc(recordLabel(id, doc))}</button>`;
    return `<div class="knowledge-links"><span>依赖：</span>${deps.length ? deps.map(link).join('') : '<span class="knowledge-muted">无</span>'}</div>
      <div class="knowledge-links"><span>被引用：</span>${rev.length ? rev.map((r) => link(r.id)).join('') : '<span class="knowledge-muted">无</span>'}</div>`;
  }

  function kindEditorHTML(rec, doc) {
    const d = rec.data || (rec.data = {});
    const txt = (lab, path, val) => `<label class="knowledge-field">${esc(lab)}<input data-k-scope="edit" data-k-bind="${esc(path)}" value="${esc(val == null ? '' : val)}"></label>`;
    const area = (lab, path, val) => `<label class="knowledge-field">${esc(lab)}<textarea rows="2" data-k-scope="edit" data-k-bind="${esc(path)}">${esc(val == null ? '' : val)}</textarea></label>`;
    const big = (lab, path, val) => `<label class="knowledge-field">${esc(lab)}<textarea rows="6" data-k-scope="edit" data-k-bind="${esc(path)}">${esc(val == null ? '' : val)}</textarea></label>`;
    const cards = (lab, path, val) => `<div class="knowledge-field"><label>${esc(lab)}<textarea rows="3" data-k-scope="edit" data-k-bind="${esc(path)}" data-k-type="cards" ${path==='data.side'&&d.side===null?'disabled':''}>${esc(cardsText(val))}</textarea></label><button data-k-action="pick-card" data-field="${esc(path)}">检索并添加卡牌</button></div>`;
    const lines = (lab, path, val) => `<label class="knowledge-field">${esc(lab)}<textarea rows="3" data-k-scope="edit" data-k-bind="${esc(path)}" ${Array.isArray(val) ? 'data-k-type="lines"' : ''}>${esc(Array.isArray(val) ? val.join('\n') : (val == null ? '' : val))}</textarea></label>`;
    const json = (lab, path, val) => {
      const s = JSON.stringify(val == null ? null : val, null, 2);
      return `<details class="knowledge-field"><summary>${esc(lab)}（高级 JSON，修改后才写入）</summary>
        <textarea rows="6" data-k-scope="edit" data-k-bind="${esc(path)}" data-k-type="json" data-k-original="${esc(s)}">${esc(s)}</textarea></details>`;
    };
    switch (rec.kind) {
      case 'source': {
        const c = d.content;
        const contentField = typeof c === 'string'
          ? big('内容', 'data.content', c)
          : `<div class="knowledge-field"><span>内容（结构化对象，未改动将原样保留）</span><pre>${esc(JSON.stringify(c == null ? null : c, null, 2))}</pre>${json('编辑内容 JSON', 'data.content', c)}</div>`;
        return `<div class="knowledge-grid">${contentField}${txt('链接', 'data.url', d.url)}${area('备注', 'data.note', d.note)}</div>`;
      }
      case 'build':
        return `<div class="knowledge-grid">${cards('主卡组（重复数字表示张数）', 'data.main', d.main)}
          ${cards('额外卡组', 'data.extra', d.extra)}${cards('副卡组', 'data.side', d.side)}
          <label class="knowledge-field"><input type="checkbox" data-k-scope="edit" data-k-bind="data.side" data-k-type="side-unknown" ${d.side===null ? 'checked' : ''}> 来源未披露副卡（保持未知）</label>
          ${area('使用条件', 'data.conditions', d.conditions)}${area('备注', 'data.notes', d.notes)}</div>`;
      case 'route': case 'fragment': {
        const steps = Array.isArray(d.steps) ? d.steps : [];
        const stepRecs = Object.values(doc.records).filter((r) => r.kind === 'step' && !r.deleted);
        const repOpts = ['tutorial', 'strategy'];
        if (d.plan) repOpts.push('decisions');
        return `<div class="knowledge-grid">
          <fieldset class="knowledge-field"><legend>步骤顺序</legend><ol>${steps.map((sid, i) => `<li><span>${esc(recordLabel(sid, doc))}</span>
            <button data-k-action="step-up" data-i="${i}" ${i === 0 ? 'disabled' : ''}>上移</button>
            <button data-k-action="step-down" data-i="${i}" ${i === steps.length - 1 ? 'disabled' : ''}>下移</button>
            <button data-k-action="step-remove" data-i="${i}">移除</button></li>`).join('') || '<li class="knowledge-muted">尚未添加步骤</li>'}</ol>
            <select data-k-role="step-pick" aria-label="选择要添加的步骤">${stepRecs.filter((r) => !steps.includes(r.id)).map((r) => optionHTML(r.id, '', r.title || r.id)).join('')}</select>
            <button data-k-action="step-add">添加步骤</button></fieldset>
          <label class="knowledge-field">呈现方式<select data-k-scope="edit" data-k-bind="data.representation">${repOpts.map((x) => optionHTML(x, d.representation, REP_LABEL[x] || x)).join('')}</select>
            ${d.plan ? '' : '<span class="knowledge-muted">导入对局方案后可选「决策」</span>'}</label>
          ${cards('起手卡列表', 'data.opening.cards', (d.opening || {}).cards)}
          ${area('起手说明', 'data.opening.notes', (d.opening || {}).notes)}
          ${area('使用条件', 'data.conditions', d.conditions)}${area('备注', 'data.notes', d.notes)}
          ${d.plan ? '<p class="knowledge-muted">已关联对局方案数据（由导入生成，界面不改动）。</p>' : ''}</div>`;
      }
      case 'step':
        return `<div class="knowledge-grid">${cards('涉及卡片', 'data.cards', d.cards)}${txt('动作', 'data.action', d.action)}
          ${txt('费用', 'data.costs', d.costs)}${txt('对象', 'data.targets', d.targets)}${txt('限制', 'data.limits', d.limits)}
          ${area('结果', 'data.result', d.result)}${area('条件', 'data.conditions', d.conditions)}</div>`;
      case 'branch': {
        const steps = Object.values(doc.records).filter((r) => r.kind === 'step' && !r.deleted);
        const routes = Object.values(doc.records).filter((r) => r.kind === 'route' && !r.deleted);
        return `<div class="knowledge-grid">
          <label class="knowledge-field">锚点步骤<select data-k-scope="edit" data-k-bind="data.anchor"><option value="">（无）</option>${steps.map((r) => optionHTML(r.id, d.anchor, r.title || r.id)).join('')}</select></label>
          <label class="knowledge-field">所属路线<select data-k-scope="edit" data-k-bind="data.route"><option value="">（无）</option>${routes.map((r) => optionHTML(r.id, d.route, r.title || r.id)).join('')}</select></label>
          ${txt('时机', 'data.timing', d.timing)}${txt('干扰', 'data.interference', d.interference)}${txt('资源', 'data.resources', d.resources)}
          ${area('条件', 'data.conditions', d.conditions)}${area('延续', 'data.continuation', d.continuation)}${area('备注', 'data.notes', d.notes)}</div>`;
      }
      case 'endboard':
        return `<div class="knowledge-grid">${cards('卡片构成', 'data.cards', d.cards)}${txt('资源', 'data.resources', d.resources)}
          ${area('约束', 'data.constraints', d.constraints)}${area('备注', 'data.notes', d.notes)}${json('效果列表', 'data.effects', d.effects)}</div>`;
      case 'countermeasure':
        return `<div class="knowledge-grid">${txt('对手 / 对局', 'data.opponent', d.opponent)}${area('局面', 'data.situation', d.situation)}
          ${lines('应对', 'data.responses', d.responses)}${lines('例外', 'data.exceptions', d.exceptions)}${area('备注', 'data.notes', d.notes)}</div>`;
      default:
        return '<p class="knowledge-muted">未知类型，仅可编辑标题 / 标签 / 引用。</p>';
    }
  }

  /* ---------- 已安装包主区 ---------- */
  function packageMainHTML() {
    const s = knowledgeUI;
    if (s.installPreview) return installPreviewHTML(s.installPreview);
    if (s.conflict) return conflictHTML(s.conflict);
    const pv = s.packageView;
    if (!pv) return '<p class="knowledge-muted">选择左侧已安装的知识包查看详情，或安装新的知识包文件。</p>';
    const doc = pv.document, pkg = doc.package || {}, insp = pv.inspection;
    const meta = ((s.snapshot || {}).packages || []).find((p) => p.id === pv.id) || {};
    const installedVers = (meta.versions || []).map((v) => v.version);
    const caps = (insp && insp.capabilities) || {};
    const rec = s.selected ? doc.records[s.selected] : null;
    return `
      <div class="knowledge-toolbar">
        <label class="knowledge-field">查看版本<select data-k-role="package-version" aria-label="查看版本">${installedVers.map((v) => optionHTML(v, pv.version, v)).join('')}</select></label>
        <button data-k-action="package-switch-version">查看所选版本</button>
        <button data-k-action="package-enable">启用所选版本 / 回退</button>
        ${meta.active ? '<button data-k-action="package-disable">停用</button>' : ''}
        <button data-k-action="package-edit">继续编辑（导入为项目）</button>
        <button data-k-action="package-uninstall">卸载</button>
        <button data-k-action="package-compute">${meta.compute_enabled?'停止参与计算':'允许已验证路线参与计算'}</button>
        <span id="knowledge-dirty" class="knowledge-status" role="status" ${s.dirty ? '' : 'hidden'}>未保存</span>
      </div>
      <p class="knowledge-status">${esc(pkg.name || packageName(pv.id))} · 版本 ${esc(pv.version)} · 环境 ${esc(pkg.environment || '—')}
        <span class="knowledge-muted">资料浏览 · ${caps.execute ? '引擎已接入' : '未接入执行'}</span>
        ${meta.enabled ? '' : '<span class="knowledge-muted">当前未启用</span>'}</p>
      ${rec ? recordViewHTML(rec, pv) : '<p class="knowledge-muted">在左侧选择记录浏览内容。</p>'}
      ${inspectionHTML(insp, doc, null)}
      <section class="knowledge-status"><strong>本机计算资格</strong>${Object.entries(pv.runtime||{}).map(([id,value])=>`<p>${esc(recordLabel(id,doc))}：${esc(value.reason)}</p>`).join('')}<p>资料安装不会自动出牌。只有本机验证仍有效、且得到计算许可的原始决策记录可进入模块化来源。</p></section>
      ${packageProvenanceHTML(pv, meta)}`;
  }

  function recordViewHTML(rec, pv) {
    const doc = pv.document;
    const fields = Object.entries(rec.data || {}).map(([k, v]) => {
      if (['plan','evidence_identity','native_binding'].includes(k)) return '';
      if (k === 'side_unknown' && !v) return '';
      if(k==='steps'&&Array.isArray(v))return `<div class="knowledge-field"><span>步骤顺序</span><ol>${v.map(id=>`<li><button data-k-action="record-select" data-id="${esc(id)}">${esc(recordLabel(id,doc))}</button></li>`).join('')}</ol></div>`;
      if(['anchor','route'].includes(k)&&typeof v==='string')return `<div class="knowledge-field"><span>${esc(FIELD_LABEL[k])}</span><button data-k-action="record-select" data-id="${esc(v)}">${esc(recordLabel(v,doc))}</button></div>`;
      if(['main','extra','side','cards'].includes(k)&&Array.isArray(v)){
        const counts=new Map();for(const code of v)counts.set(code,(counts.get(code)||0)+1);
        return `<div class="knowledge-field"><span>${esc(FIELD_LABEL[k])} · ${v.length} 张</span><div class="knowledge-card-strip">${[...counts].map(([code,count])=>`<figure><img loading="lazy" src="/pics/${Number(code)}.jpg" alt="卡号 ${Number(code)}"><figcaption><span data-knowledge-card-name="${Number(code)}">${Number(code)}</span> ×${count}</figcaption></figure>`).join('')}</div></div>`;
      }
      return `<div class="knowledge-field"><span>${esc(FIELD_LABEL[k] || k)}</span><div>${renderValue(v)}</div></div>`;
    }).join('');
    return `<section class="knowledge-form">
      <p class="knowledge-muted">原始版本：v${esc(pv.version)}${rec.deleted ? ' · 已删除' : ''}</p>
      <h3>${esc(rec.title || '（无标题）')} <small>${esc(KIND_LABEL[rec.kind] || rec.kind || '')}</small></h3>
      <p>${(rec.tags || []).map((t) => '<i>' + esc(tagLabel(t)) + '</i>').join(' ')}</p>
      ${(rec.refs || []).length ? `<p class="knowledge-links">依赖：${rec.refs.map((x) => `<button class="knowledge-record" data-k-action="record-select" data-id="${esc(x.id)}">${esc(recordLabel(x.id, doc))}</button>`).join('')}</p>` : ''}
      ${fields}
      ${relatedHTML(rec,doc)}
      ${pv.personalNotes?.[rec.id]?`<p class="knowledge-status">个人批注：${esc(pv.personalNotes[rec.id])}</p>`:''}
      <div class="knowledge-toolbar">
        ${rec.kind === 'build' ? '<button data-k-action="copy-build">复制为个人卡组</button>' : ''}
        ${pv.editing ? '' : '<button data-k-action="overlay-edit">编辑个人副本</button>'}
      </div>
    </section>
    ${pv.editing && knowledgeUI.edit ? recordEditorHTML(knowledgeUI.edit, doc, true) : ''}`;
  }

  function renderValue(v) {
    if(v===null||v===undefined)return '<span class="knowledge-muted">未知 / 未披露</span>';
    if (typeof v === 'boolean') return esc(v ? '是' : '否');
    if (Array.isArray(v)) return v.length && v.every((x) => typeof x !== 'object') ? esc(v.join(' ')) : `<pre>${esc(JSON.stringify(v, null, 2))}</pre>`;
    if (v && typeof v === 'object') return `<pre>${esc(JSON.stringify(v, null, 2))}</pre>`;
    const s = String(v);
    if (/^https?:\/\//i.test(s)) return `<a href="${esc(s)}" target="_blank" rel="noopener noreferrer">${esc(s)}</a>`;
    return esc(s);
  }

  function packageProvenanceHTML(pv, meta) {
    const v = ((meta || {}).versions || []).find((x) => String(x.version) === String(pv.version));
    return `<details class="knowledge-source"><summary>来源与版本信息</summary><dl>
      <dt>知识包 ID</dt><dd>${esc(pv.id)}</dd>
      <dt>版本</dt><dd>${esc(pv.version)}</dd>
      ${v && v.digest ? '<dt>内容摘要</dt><dd>' + esc(v.digest) + '</dd>' : ''}
    </dl></details>`;
  }

  function conflictHTML(c) {
    const doc = (knowledgeUI.packageView && knowledgeUI.packageView.document) || {};
    return `<section class="knowledge-conflict">
      <h3>启用「${esc(packageName(c.package_id))}」版本 ${esc(c.version)}：检测到冲突</h3>
      <p class="knowledge-muted">逐条选择保留本地数据还是知识包数据；未列出的字段不受影响，由服务端三方合并保留。</p>
      ${c.conflicts.map((cf, i) => `<div class="knowledge-conflict">
        <h4>${esc(recordLabel(cf.record, doc))}</h4>
        <p class="knowledge-muted">冲突字段：${esc((cf.paths || []).join('、') || '—')}</p>
        <label class="knowledge-field"><input type="radio" name="kcf-${i}" data-k-action="conflict-pick" data-record="${esc(cf.record)}" value="local" checked> 保留本地：${esc(briefJSON(cf.local))}</label>
        <label class="knowledge-field"><input type="radio" name="kcf-${i}" data-k-action="conflict-pick" data-record="${esc(cf.record)}" value="incoming"> 使用知识包：${esc(briefJSON(cf.incoming))}</label>
      </div>`).join('')}
      <div class="knowledge-toolbar"><button data-k-action="conflict-activate">确认启用</button><button data-k-action="conflict-cancel">取消</button></div>
    </section>`;
  }

  function installPreviewHTML(ip) {
    const prev = ip.preview || {};
    const pkg = prev.package || {};
    return `<section class="knowledge-form">
      <h3>安装知识包：${esc(pkg.name || '（未知名称）')} ${pkg.version ? '版本 ' + esc(pkg.version) : ''}</h3>
      <p class="knowledge-status">${prev.compatible ? '兼容' : '不兼容'}${prev.compatibility_reason ? ' · ' + esc(prev.compatibility_reason) : ''}${prev.duplicate ? ' · 与已安装内容重复' : ''}</p>
      ${(prev.conflicts || []).map((cf, i) => `<div class="knowledge-conflict"><h4>${esc(cf.record)}</h4>
        <p class="knowledge-muted">字段：${esc((cf.paths || []).join('、') || '—')}</p>
        <p>本地：${esc(briefJSON(cf.local))}</p><p>知识包：${esc(briefJSON(cf.incoming))}</p></div>`).join('')}
      <div class="knowledge-toolbar">
        <button data-k-action="install-confirm">安装保存（默认不启用）</button>
        <button data-k-action="install-cancel">取消</button>
      </div>${inspectionHTML(prev.inspection,ip.bundle?.document||{},null)}</section>`;
  }

  /* ================= 项目操作 ================= */
  function loadProject(pr) {
    knowledgeUI.project = pr; knowledgeUI.tab = 'projects';
    knowledgeUI.projectBase=clone(pr);knowledgeUI.rawDraft={};knowledgeUI.publishVersion=pr.document.package.version;
    knowledgeUI.selected = null; knowledgeUI.edit = null; knowledgeUI.dirty = false; knowledgeUI.candidates = null;
    loadSourceLists();
    knowledgeUI.jobForm={route:'',build:'',hands:'',scenario:'none',seconds:15,nodes:160,depth:48};
    knowledgeUI.jobs=[];knowledgeUI.nativeStatus={};void refreshJobs(false).catch(fail);
  }
  async function openProject(id) {
    if (!(await confirmDiscard())) return;
    await act(async () => { loadProject(await api('/api/knowledge', { op: 'project.get', id })); });
  }
  async function createProject() {
    if (!(await confirmDiscard())) return;
    const name = await dialog({ title: '新建知识包项目', input: { label: '项目名称' }, okLabel: '创建' });
    if (name == null) return;
    if (!String(name.value || '').trim()) { notice('项目名称不能为空'); return; }
    const theme = await dialog({ title: '主题（可选）', input: { label: '主题' }, okLabel: '确定' });
    if(theme===null)return;
    await act(async () => {
      const pr = await api('/api/knowledge', { op: 'project.create', name: String(name.value).trim(), theme: String((theme && theme.value) || '').trim() });
      await fetchSummary(); loadProject(pr); notice('项目已创建');
    });
  }
  async function sampleProject() {
    if (!(await confirmDiscard())) return;
    await act(async () => {
      const pr = await api('/api/knowledge', { op: 'project.sample' });
      await fetchSummary(); loadProject(pr); notice('示例项目已创建，可直接编辑');
    });
  }
  async function importProjectFile(file) {
    if (!(await confirmDiscard())) return;
    if(file.size>32*1024*1024)throw Error('知识包或项目文件超过 32 MB，请拆分内容');
    const text = (await file.text()).replace(/^\uFEFF/,'');
    let document = text;
    if (/\.json$/i.test(file.name)) {
      try { const parsed = JSON.parse(text); if (parsed && typeof parsed === 'object') document = parsed; }
      catch (err) { throw Error('项目文件不是有效 JSON；普通资料请在制作项目内使用“导入原始文件”'); }
    }
    if(typeof document!=='object')throw Error('请选择导出的项目或知识包 JSON；普通资料可在项目内导入');
    await act(async () => {
      const pr = await api('/api/knowledge', { op: 'project.import', document });
      await fetchSummary(); loadProject(pr); notice('导入完成，已打开为项目');
    });
  }

  async function selectRecord(id) {
    if (knowledgeUI.selected === id) return;
    if (!(await confirmDiscard())) return;
    if(knowledgeUI.dirty)discardEdits();
    const doc = currentDoc();
    if (!doc || !doc.records[id]) return;
    if (knowledgeUI.packageView) knowledgeUI.packageView.editing = false;
    knowledgeUI.selected = id;
    knowledgeUI.edit = clone(doc.records[id]);
    knowledgeUI.dirty = false;
    knowledgeUI.rawDraft={};
    render();
    const selected=knowledgeRoot.querySelector('#knowledge-record-list .active');if(selected)selected.scrollIntoView({block:'nearest'});
  }

  async function pickCard(field){
    flushBinds();if(!knowledgeUI.edit)return;
    const panel=document.createElement('dialog');panel.className='knowledge-card-dialog';
    panel.innerHTML='<h3>检索卡牌</h3><label>卡名或卡号<input type="search" aria-label="知识包卡牌搜索" placeholder="输入卡名或卡号"></label><p class="knowledge-muted" role="status">从当前本机卡库选择；点击一次添加一张。</p><div class="knowledge-cards"></div><button data-close>完成选择</button>';
    const input=panel.querySelector('input'),results=panel.querySelector('.knowledge-cards'),status=panel.querySelector('[role="status"]');
    let serial=0,timer=null;
    async function search(){
      const generation=++serial;
      try{
        const data=await api('/api/cards?q='+encodeURIComponent(input.value));
        if(!panel.isConnected||generation!==serial)return;
        results.innerHTML=data.cards.map(c=>`<button class="knowledge-card" data-card="${Number(c.id)}"><img loading="lazy" src="/pics/${Number(c.id)}.jpg" alt=""><strong>${esc(c.name)}</strong><small>${Number(c.id)}</small></button>`).join('');
        status.textContent=`找到 ${data.total} 张卡牌，显示前 ${data.cards.length} 张；可继续缩小范围。`;
      }catch(error){status.textContent=error.message;}
    }
    input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>void search(),200);});
    panel.addEventListener('click',event=>{
      const add=event.target.closest('[data-card]');
      if(add){
        const values=[...(getPath(knowledgeUI.edit,field)||[]),Number(add.dataset.card)];setPath(knowledgeUI.edit,field,values);
        knowledgeUI.rawDraft[`edit:${knowledgeUI.selected}:${field}`]=cardsText(values);knowledgeUI.dirty=true;
        const textarea=knowledgeRoot.querySelector(`textarea[data-k-bind="${field}"]`);
        if(textarea){textarea.value=cardsText(values);textarea.disabled=false;textarea.dataset.kTouched='1';}
        if(field==='data.side'){const unknown=knowledgeRoot.querySelector('[data-k-type="side-unknown"]');if(unknown)unknown.checked=false;}
        status.textContent='已添加 '+add.querySelector('strong').textContent+'；继续选择或点击完成。';
      }else if(event.target.closest('[data-close]'))panel.close();
    });
    panel.addEventListener('close',()=>{clearTimeout(timer);++serial;panel.remove();render();},{once:true});
    knowledgeRoot.append(panel);panel.showModal();input.focus();await search();
  }

  function defaultData(kind) {
    if (kind === 'build') return { main: [], extra: [], side: [] };
    if (kind === 'route' || kind === 'fragment') return { steps: [], opening: { cards: [], notes: '' } };
    if (kind === 'step' || kind === 'endboard') return { cards: [] };
    return {};
  }
  function addRecord(kind) {
    const doc = knowledgeUI.project.document;
    const id = uid();
    doc.records[id] = { id, kind, revision: 1, title: '新'+KIND_LABEL[kind], tags: [], refs: [], data: defaultData(kind) };
    knowledgeUI.selected = id;
    knowledgeUI.edit = clone(doc.records[id]);
    knowledgeUI.dirty = true;
    knowledgeUI.rawDraft={};
    render();
  }
  function stepMove(i, dir) {
    flushBinds();
    const st = knowledgeUI.edit.data.steps || (knowledgeUI.edit.data.steps = []);
    const j = i + dir;
    if (j < 0 || j >= st.length) return;
    const [x] = st.splice(i, 1); st.splice(j, 0, x);
    knowledgeUI.dirty = true; render();
  }

  async function saveProject() {
    const p = knowledgeUI.project; if (!p) return;
    try { flushBinds(); } catch (err) { fail(err); return; }
    const doc = clone(p.document);
    if (knowledgeUI.edit && knowledgeUI.selected) doc.records[knowledgeUI.selected] = clone(knowledgeUI.edit);
    await act(async () => {
      const np = await api('/api/knowledge', { op: 'project.save', id: p.id, revision: p.revision, document: doc });
      knowledgeUI.project = np; knowledgeUI.dirty = false;
      knowledgeUI.projectBase=clone(np);knowledgeUI.rawDraft={};
      if (knowledgeUI.selected && np.document.records[knowledgeUI.selected]) knowledgeUI.edit = clone(np.document.records[knowledgeUI.selected]);
      await fetchSummary();
      notice('项目已保存');
    });
  }

  function reviewProject(kind) {
    const p = knowledgeUI.project; if (!p) return;
    if (knowledgeUI.dirty) { notice('请先保存修改再执行复核'); return; }
    if(!knowledgeUI.selected){notice('请先选择需要记录核对结果的条目；下方已经展示整个项目的结构检查结果。');return;}
    return act(async () => {
      const np = await api('/api/knowledge', { op: 'project.review', id: p.id, revision: p.revision, target: knowledgeUI.selected || '', note: '', kind });
      knowledgeUI.project = np;
      knowledgeUI.projectBase=clone(np);
      notice(kind === 'human' ? '已记录人工复核' : '结构检查完成');
    });
  }

  async function publishProject() {
    const p = knowledgeUI.project; if (!p) return;
    if (knowledgeUI.dirty) { notice('请先保存修改再发布'); return; }
    const inp = document.getElementById('knowledge-publish-version');
    const ver = ((inp && inp.value) || '').trim();
    if (!ver) { notice('请填写发布版本号'); return; }
    const rawCount=Object.values(p.document.records).filter(r=>r.kind==='source'&&!r.deleted).length;
    const confirmed=await dialog({title:'发布版本 '+ver,message:`将包含 ${Object.values(p.document.records).filter(r=>!r.deleted).length} 条内容及 ${rawCount} 份来源资料。请确认原始资料适合随包分享；未验证状态会保留。`,okLabel:'确认发布并下载'});
    if(!confirmed)return;
    await act(async () => {
      const bundle = await api('/api/knowledge', { op: 'project.publish', id: p.id, revision: p.revision, version: ver });
      downloadJSON(safeName((p.document.package || {}).name) + '-' + safeName(ver) + '.知识包.json', bundle);
      await fetchSummary();
      knowledgeUI.project = await api('/api/knowledge', { op: 'project.get', id: p.id });
      knowledgeUI.projectBase=clone(knowledgeUI.project);
      notice('已发布版本 ' + ver + '，JSON 文件已开始下载');
    });
  }

  function exportProject() {
    const p = knowledgeUI.project; if (!p) return;
    if(knowledgeUI.dirty){notice('请先保存修改再导出，避免遗漏当前输入');return;}
    return act(async () => {
      const out = await api('/api/knowledge', { op: 'project.export', id: p.id });
      downloadJSON(safeName((p.document.package || {}).name) + '-项目.json', out);
      notice('项目已导出');
    });
  }

  function findDuplicates() {
    const p = knowledgeUI.project; if (!p) return;
    if(knowledgeUI.dirty){notice('请先保存修改再检查重复候选');return;}
    return act(async () => {
      knowledgeUI.candidates = await api('/api/knowledge', { op: 'project.candidates', id: p.id, revision: p.revision });
    });
  }

  async function importSource(kind) {
    const p = knowledgeUI.project; if (!p) return;
    if (!(await confirmDiscard())) return;
    await act(async () => {
      const body = { op: 'project.import-source', id: p.id, revision: p.revision };
      if (kind === 'deck') {
        const sel = document.getElementById('k-source-deck');
        if (!sel || !sel.value) throw new Error('请先在下拉框选择卡组');
        const d = await api('/api/deck?id=' + encodeURIComponent(sel.value));
        body.kind = 'deck'; body.source_id = sel.value; body.source_revision = d.revision;
      } else if (kind === 'plan') {
        const sel = document.getElementById('k-source-plan');
        if (!sel || !sel.value) throw new Error('请先在下拉框选择方案');
        const meta = (knowledgeUI.plans || []).find((x) => x.id === sel.value);
        let rev = meta && meta.edit_revision;
        if (rev == null) rev = (await api('/api/plan/' + encodeURIComponent(sel.value))).edit_revision;
        body.kind = 'plan'; body.source_id = sel.value; body.source_revision = rev;
      } else {
        const f = knowledgeUI.sourceFile;
        if (!f) throw new Error('未选择文件');
        body.kind = 'file'; body.title = f.title; body.content = f.content;
      }
      const pr = await api('/api/knowledge', body);
      knowledgeUI.project = pr; knowledgeUI.dirty = false; knowledgeUI.selected = null; knowledgeUI.edit = null;
      knowledgeUI.projectBase=clone(pr);knowledgeUI.rawDraft={};
      notice('来源已导入项目');
    });
  }
  async function importSourceFile(file) {
    if(file.size>8*1024*1024)throw Error('单份原始附件超过 8 MB，请拆分后导入');
    const bytes=new Uint8Array(await file.arrayBuffer());let raw='';
    for(let i=0;i<bytes.length;i+=32768)raw+=String.fromCharCode(...bytes.subarray(i,i+32768));
    knowledgeUI.sourceFile = { title: file.name, content: {filename:file.name,media_type:file.type||'text/plain',text:await file.text(),base64:btoa(raw)} };
    await importSource('file');
  }

  /* ================= 知识包操作 ================= */
  function defaultVersion(meta) {
    if (meta.active) return meta.active;
    const vs = (meta.versions || []).filter((v) => v.installed);
    if (vs.length) return vs[vs.length - 1].version;
    return (meta.versions || []).length ? meta.versions[meta.versions.length - 1].version : '';
  }
  async function openPackage(pid, version) {
    if (knowledgeUI.packageView && knowledgeUI.packageView.editing && knowledgeUI.dirty) {
      if (!(await confirmDiscard())) return;
      discardEdits();
    }
    const meta = (((knowledgeUI.snapshot || {}).packages || []).find((p) => p.id === pid)) || {};
    const ver = version || defaultVersion(meta);
    await act(async () => {
      const res = await api('/api/knowledge', ver
        ? { op: 'package.get', package_id: pid, version: ver }
        : { op: 'package.get', package_id: pid });
      knowledgeUI.packageView = {
        id: pid,
        version: String(ver || (res.document && res.document.package && res.document.package.version) || ''),
        document: res.document, inspection: res.inspection, index:res.index, runtime:res.runtime, personalNotes:res.personal_notes||{}, editing: false
      };
      knowledgeUI.conflict = null; knowledgeUI.installPreview = null;
      knowledgeUI.selected = null; knowledgeUI.edit = null; knowledgeUI.dirty = false;
      knowledgeUI.rawDraft={};
    });
  }

  async function activatePackage(pid, version, resolutions) {
    if(knowledgeUI.dirty){notice('请先保存或取消当前个人修改，再切换启用版本');return;}
    await act(async () => {
      const snap = knowledgeUI.snapshot || {};
      const meta = (snap.packages || []).find((p) => p.id === pid) || {};
      const ver = version || meta.active;
      if (!ver) throw new Error('该知识包没有可启用的版本');
      if (!resolutions) {
          const prev = await api('/api/knowledge', { op: 'package.activation-preview', package_id: pid, version: ver });
          if (prev && Array.isArray(prev.conflicts) && prev.conflicts.length) {
            knowledgeUI.conflict = { package_id: pid, version: ver, conflicts: prev.conflicts, resolutions: Object.fromEntries(prev.conflicts.map(c=>[c.record,'local'])) };
            knowledgeUI.packageView = null;
            return;
          }
      }
      const body = { op: 'package.activate', package_id: pid, version: ver, revision: snap.revision };
      if (resolutions && Object.keys(resolutions).length) body.resolutions = resolutions;
      await api('/api/knowledge', body);
      knowledgeUI.conflict = null;
      await fetchSummary();
      const frozen=await api('/api/knowledge',{op:'package.get',package_id:pid,version:ver});
      knowledgeUI.packageView={id:pid,version:ver,document:frozen.document,inspection:frozen.inspection,index:frozen.index,runtime:frozen.runtime,personalNotes:frozen.personal_notes||{},editing:false};
      notice('知识包已启用');
    });
  }

  function disablePackage() {
    const pv = knowledgeUI.packageView; if (!pv) return;
    return act(async () => {
      await api('/api/knowledge', { op: 'package.disable', package_id: pv.id, revision: knowledgeUI.snapshot.revision });
      await fetchSummary(); notice('已停用知识包');
    });
  }
  async function uninstallPackage() {
    const pv = knowledgeUI.packageView; if (!pv) return;
    if(knowledgeUI.dirty){notice('请先保存或取消当前个人修改，再卸载');return;}
    const ok = typeof confirmFlow === 'function'
      ? await confirmFlow('卸载知识包？', '将卸载「' + packageName(pv.id) + '」，个人数据与历史版本快照会保留。', '卸载')
      : await dialog({ title: '卸载知识包？', message: '将卸载「' + packageName(pv.id) + '」，个人数据与历史版本快照会保留。', okLabel: '卸载' });
    if (!ok) return;
    await act(async () => {
      await api('/api/knowledge', { op: 'package.uninstall', package_id: pv.id, revision: knowledgeUI.snapshot.revision });
      knowledgeUI.packageView = null;
      await fetchSummary(); notice('已卸载');
    });
  }
  async function continueEditing() {
    const pv = knowledgeUI.packageView; if (!pv) return;
    if (!(await confirmDiscard())) return;
    await act(async () => {
      const docu = { format: 'ygo-deck-knowledge-project', schema: 1, document: pv.document };
      const pr = await api('/api/knowledge', { op: 'project.import', document: docu });
      await fetchSummary();
      knowledgeUI.packageView = null;
      loadProject(pr);
      notice('已导入为可编辑项目');
    });
  }
  async function overlaySave() {
    const pv = knowledgeUI.packageView; if (!pv || !knowledgeUI.edit) return;
    try { flushBinds(); } catch (err) { fail(err); return; }
    const noteVal = await dialog({ title: '保存个人修改', message: '个人修改以覆盖层保存，不会改动知识包本体。', input: { label: '修改备注（可选）' }, okLabel: '保存个人修改' });
    if (noteVal == null) return;
    await act(async () => {
      await api('/api/knowledge', {
        op: 'package.overlay', package_id: pv.id, version: pv.version,
        record_id: knowledgeUI.edit.id, local: knowledgeUI.edit,
        note: String(noteVal.value || ''), revision: knowledgeUI.snapshot.revision
      });
      knowledgeUI.dirty = false; pv.editing = false; knowledgeUI.edit = null;
      knowledgeUI.rawDraft={};
      await fetchSummary();
      const updated=await api('/api/knowledge',{op:'package.get',package_id:pv.id,version:pv.version});
      pv.document=updated.document;pv.inspection=updated.inspection;pv.runtime=updated.runtime;pv.personalNotes=updated.personal_notes||{};
      notice('个人修改已保存');
    });
  }
  async function copyBuild() {
    const pv = knowledgeUI.packageView; if (!pv) return;
    const rec = pv.document.records[pv.selected || knowledgeUI.selected]; if (!rec) return;
    const unknown = rec.data?.side===null;
    const opts = { title: '复制为个人卡组', input: { label: '新卡组名称', value: rec.title || '' }, okLabel: '复制' };
    if (unknown) {
      opts.warning = '该构筑包含「未知副卡组」内容，复制时需要选择处理方式。';
      opts.checkbox = { label: '明确另存为不带副卡的个人构筑', checked: false };
    }
    const res = await dialog(opts);
    if (res == null) return;
    const name = String(res.value || '').trim();
    if (!name) { notice('请填写卡组名称'); return; }
    await act(async () => {
      const out = await api('/api/knowledge', {
        op: 'personal.copy-build', package_id: pv.id, version: pv.version,
        record_id: rec.id, name, omit_unknown_side: unknown ? !!res.checked : false
      });
      const nm = out && (out.name || out.id);
      notice(nm ? '已保存为个人卡组「' + (typeof nm === 'string' ? nm : name) + '」' : '已保存为个人卡组');
    });
  }
  async function installFile(file) {
    if(!(await confirmDiscard()))return;
    if(file.size>32*1024*1024)throw Error('知识包文件超过 32 MB');
    const text = (await file.text()).replace(/^\uFEFF/,'');
    let bundle;
    try { bundle = JSON.parse(text); } catch (err) { notice('文件不是有效的 JSON 知识包'); return; }
    await act(async () => {
      const prev = await api('/api/knowledge', { op: 'package.preview', bundle });
      await fetchSummary();
      knowledgeUI.installPreview = { bundle, digest: prev.digest, preview: prev };
      knowledgeUI.packageView = null; knowledgeUI.conflict = null;
      knowledgeUI.dirty=false;knowledgeUI.rawDraft={};
    });
  }
  function installConfirm() {
    const ip = knowledgeUI.installPreview; if (!ip) return;
    return act(async () => {
      await api('/api/knowledge', { op: 'package.install', bundle: ip.bundle, digest: ip.digest, revision: knowledgeUI.snapshot.revision, enable: false });
      knowledgeUI.installPreview = null;
      await fetchSummary();
      notice('知识包已安装（默认未启用），可在列表中选择并启用');
    });
  }

  /* ================= 公共 API ================= */
  window.knowledgeUnsavedSummary = function knowledgeUnsavedSummary() {
    const s = knowledgeUI;
    if (s.packageView && s.packageView.editing && s.dirty) {
      const rec = s.selected && s.packageView.document.records[s.selected];
      return '知识包「' + ((s.packageView.document.package || {}).name || packageName(s.packageView.id)) + '」的个人副本有未保存修改' + (rec ? '（正在编辑：' + (rec.title || rec.id) + '）' : '');
    }
    if (s.project && s.dirty) {
      const rec = s.selected && s.project.document.records[s.selected];
      return '项目「' + ((s.project.document.package || {}).name || s.project.id) + '」有未保存修改' + (rec ? '（正在编辑：' + (rec.title || rec.id) + '）' : '');
    }
    return '';
  };

  window.enterKnowledge = async function enterKnowledge() {
    return run(async () => {
      if (!knowledgeRoot) init();
      if (!knowledgeRoot) return;
      render(); /* 先按现有状态渲染，不覆盖脏项目缓冲与固定的 packageView */
      await fetchSummary();
      render();
      if (knowledgeUI.project && !knowledgeUI.decks) loadSourceLists();
      if(knowledgeUI.project)void refreshJobs(false).catch(fail);
    })();
  };

  const shelfGens = new WeakMap();
  const shelfBound = new WeakSet();
  window.knowledgeShelf = async function knowledgeShelf(container, kinds) {
    if (!container) return;
    const gen = (shelfGens.get(container) || 0) + 1;
    shelfGens.set(container, gen);
    try {
      const items = await api('/api/knowledge', { op: 'catalog', kinds: kinds || undefined }) || [];
      if (shelfGens.get(container) !== gen) return; /* 迟到的响应不再覆盖新加载 */
      if (!knowledgeUI.snapshot) { try { await fetchSummary(); } catch (err) { /* 忽略，卡片退化为显示原始 ID */ } }
      if (shelfGens.get(container) !== gen) return;
      renderShelf(container, items);
    } catch (err) {
      if (shelfGens.get(container) === gen) container.hidden = true;
    }
  };
  function renderShelf(container, items) {
    if (!items.length) { container.hidden = true; return; }
    const groups = new Map();
    for (const it of items) {
      const key = it.package_id + '@' + it.version;
      if (!groups.has(key)) groups.set(key, { name: it.package_name || it.package_id, version: it.version, items: [] });
      groups.get(key).items.push(it);
    }
    container.hidden = false;
    container.innerHTML = `<section class="knowledge-shelf"><h3>已启用知识包</h3>` +
      [...groups.values()].map((g) => `<div class="knowledge-group"><h4>${esc(g.name)} <span class="knowledge-muted">版本 ${esc(g.version)}</span></h4>
        <div class="knowledge-cards">${g.items.map(shelfCardHTML).join('')}</div></div>`).join('') + '</section>';
    if (!shelfBound.has(container)) {
      shelfBound.add(container);
      container.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-k-action="shelf-open"]');
        if (!btn) return;
        openKnowledgeRecord(btn.dataset.package, btn.dataset.version, btn.dataset.record);
      });
    }
  }
  function shelfCardHTML(it) {
    const r = it.record || {};
    const chips = (it.checks || []).map((c) => '<i>' + esc(typeof c === 'string' ? c : (c.state || c.id || '')) + '</i>').join(' ');
    const tags = (r.tags || []).map((t) => esc(tagLabel(t))).join(' · ');
    return `<button class="knowledge-card" data-k-action="shelf-open" data-package="${esc(it.package_id)}" data-version="${esc(it.version)}" data-record="${esc(r.id)}">
      <strong>${esc(r.title || r.id)}</strong>
      <span class="knowledge-muted">${esc(KIND_LABEL[r.kind] || r.kind || '')}${tags ? ' · ' + tags : ''}</span>
      ${chips ? '<span class="knowledge-status">' + chips + '</span>' : ''}
    </button>`;
  }

  window.openKnowledgeRecord = async function openKnowledgeRecord(package_id, version, recordid) {
    return run(async () => {
      if (knowledgeUI.dirty) {
        if (!(await confirmDiscard())) return;
        discardEdits();
      }
      if (typeof switchModule === 'function') { try { await switchModule('knowledge'); } catch (err) { /* 已在模块内 */ } }
      if(typeof moduleUI!=='undefined'&&moduleUI.current!=='knowledge')return;
      knowledgeUI.tab = 'installed'; knowledgeUI.conflict = null; knowledgeUI.installPreview = null;
      if (!knowledgeUI.snapshot) { try { await fetchSummary(); } catch (err) { /* 忽略 */ } }
      await act(async () => {
        const res = await api('/api/knowledge', { op: 'package.get', package_id: package_id, version: version });
        knowledgeUI.packageView = { id: package_id, version: String(version || ''), document: res.document, inspection: res.inspection,index:res.index,runtime:res.runtime,personalNotes:res.personal_notes||{}, editing: false };
        knowledgeUI.selected = recordid; knowledgeUI.edit = null; knowledgeUI.dirty = false;
        knowledgeUI.rawDraft={};
      });
      const attr = (window.CSS && CSS.escape) ? CSS.escape(String(recordid)) : String(recordid);
      const el = document.querySelector('#knowledge [data-k-action="record-select"][data-id="' + attr + '"]');
      if (el) el.scrollIntoView({ block: 'center' });
    })();
  };

  /* ================= 事件处理（#knowledge 内委托） ================= */
  async function onClick(e) {
    const btn = e.target.closest('[data-k-action]');
    if (!btn || !knowledgeRoot) return;
    if (knowledgeUI.busy) return;
    const a = btn.dataset.kAction, id = btn.dataset.id;
    try {
      switch (a) {
        case 'pick-card': await pickCard(btn.dataset.field);return;
        case 'jobs-refresh': await act(()=>refreshJobs(true));return;
        case 'job-start': await startJob();return;
        case 'job-cancel': case 'job-resume':
          await act(async()=>{await api('/api/knowledge',{op:a==='job-cancel'?'job.cancel':'job.resume',id});await refreshJobs(true);});return;
        case 'package-compute': {
          const pv=knowledgeUI.packageView;if(!pv)return;
          const meta=knowledgeUI.snapshot.packages.find(p=>p.id===pv.id);
          await act(async()=>{await api('/api/knowledge',{op:'package.compute',package_id:pv.id,revision:knowledgeUI.snapshot.revision,enabled:!meta.compute_enabled});await fetchSummary();});return;
        }
        case 'refresh': await act(fetchSummary);return;
        case 'tab': {
          if (!(await confirmDiscard())) return;
          discardEdits();
          knowledgeUI.tab = btn.dataset.tab; knowledgeUI.conflict = null; knowledgeUI.installPreview = null;
          await fetchSummary();
          render(); return;
        }
        case 'project-open': await openProject(id); return;
        case 'project-back': {
          if (!(await confirmDiscard())) return;
          discardEdits();
          knowledgeUI.project=null;knowledgeUI.projectBase=null;
          knowledgeUI.selected = null; knowledgeUI.edit = null; knowledgeUI.candidates = null;
          render(); return;
        }
        case 'record-select': await selectRecord(id); return;
        case 'record-add': {
          if (!(await confirmDiscard())) return;
          const sel = knowledgeRoot.querySelector('[data-k-role="add-kind"]');
          if(knowledgeUI.dirty)discardEdits();
          addRecord(sel ? sel.value : 'source'); return;
        }
        case 'record-delete': {
          flushBinds();
          const rec = knowledgeUI.edit; if (!rec) return;
          rec.deleted = !rec.deleted;
          const live = knowledgeUI.project.document.records[rec.id];
          if (live) live.deleted = rec.deleted;
          knowledgeUI.dirty = true; render(); return;
        }
        case 'step-up': stepMove(+btn.dataset.i, -1); return;
        case 'step-down': stepMove(+btn.dataset.i, 1); return;
        case 'step-remove': {
          flushBinds();
          const st = knowledgeUI.edit.data.steps || [];
          st.splice(+btn.dataset.i, 1); knowledgeUI.dirty = true; render(); return;
        }
        case 'step-add': {
          flushBinds();
          const sel = knowledgeRoot.querySelector('[data-k-role="step-pick"]');
          const sid = sel && sel.value;
          if (!sid) { notice('请先创建步骤记录或选择要添加的步骤'); return; }
          (knowledgeUI.edit.data.steps || (knowledgeUI.edit.data.steps = [])).push(sid);
          knowledgeUI.dirty = true; render(); return;
        }
        case 'save': await saveProject(); return;
        case 'review-structure': await reviewProject('structure'); return;
        case 'review-human': await reviewProject('human'); return;
        case 'publish': await publishProject(); return;
        case 'export': await exportProject(); return;
        case 'duplicates': await findDuplicates(); return;
        case 'import-deck': await importSource('deck'); return;
        case 'import-plan': await importSource('plan'); return;
        case 'import-file': {
          const inp = knowledgeRoot.querySelector('#knowledge-source-file-input');
          if (inp) inp.click(); return;
        }
        case 'project-new': await createProject(); return;
        case 'project-sample': await sampleProject(); return;
        case 'project-import-file': {
          const inp = knowledgeRoot.querySelector('#knowledge-file-input');
          if (inp) inp.click(); return;
        }
        case 'package-open': await openPackage(id); return;
        case 'package-switch-version': {
          const sel = knowledgeRoot.querySelector('[data-k-role="package-version"]');
          if (sel && sel.value) await openPackage(knowledgeUI.packageView.id, sel.value);
          return;
        }
        case 'package-enable': {
          const pv = knowledgeUI.packageView; if (!pv) return;
          const sel = knowledgeRoot.querySelector('[data-k-role="package-version"]');
          await activatePackage(pv.id, (sel && sel.value) || pv.version);
          return;
        }
        case 'package-disable': await disablePackage(); return;
        case 'package-uninstall': await uninstallPackage(); return;
        case 'package-edit': await continueEditing(); return;
        case 'package-back': {
          if (!(await confirmDiscard())) return;
          discardEdits();
          knowledgeUI.packageView = null; knowledgeUI.selected = null; knowledgeUI.edit = null;
          render(); return;
        }
        case 'overlay-edit': {
          const pv = knowledgeUI.packageView; if (!pv) return;
          const rec = pv.document.records[knowledgeUI.selected]; if (!rec) return;
          if (knowledgeUI.dirty && !(await confirmDiscard())) return;
          discardEdits();
          pv.editing = true; knowledgeUI.edit = clone(rec); knowledgeUI.dirty = false;
          render(); return;
        }
        case 'overlay-save': await overlaySave(); return;
        case 'overlay-cancel': {
          if (knowledgeUI.dirty && !(await confirmDiscard())) return;
          discardEdits(); render(); return;
        }
        case 'copy-build': await copyBuild(); return;
        case 'conflict-cancel': knowledgeUI.conflict = null; render(); return;
        case 'conflict-activate': {
          const c = knowledgeUI.conflict; if (!c) return;
          await activatePackage(c.package_id, c.version, c.resolutions || {});
          return;
        }
        case 'install-file': {
          const inp = knowledgeRoot.querySelector('#knowledge-install-input');
          if (inp) inp.click(); return;
        }
        case 'install-confirm': await installConfirm(); return;
        case 'install-cancel': knowledgeUI.installPreview = null; render(); return;
        default: return;
      }
    } catch (err) { fail(err); render(); }
  }

  function onInput(e) {
    const el = e.target;
    if (!el || !el.dataset) return;
    if(el.dataset.kJob){knowledgeUI.jobForm[el.dataset.kJob]=el.value;return;}
    if(el.id==='knowledge-publish-version'){knowledgeUI.publishVersion=el.value;return;}
    if (el.dataset.kRole === 'search') { knowledgeUI.search = el.value; refreshRecordList(); return; }
    if (el.dataset.kBind) {
      el.dataset.kTouched='1';knowledgeUI.rawDraft[draftKey(el)]=el.value;knowledgeUI.dirty=true;
      const chip=$('#knowledge-dirty');if(chip)chip.hidden=false;
      try { bindInput(el);el.setCustomValidity(''); } catch (err) { el.setCustomValidity(err.message); }
    }
  }

  function onChange(e) {
    const el = e.target;
    if (!el || !el.dataset) return;
    if(el.dataset.kJob){
      knowledgeUI.jobForm[el.dataset.kJob]=el.value;
      if(el.dataset.kJob==='route'){
        const doc=knowledgeUI.project.document,rec=doc.records[el.value],form=knowledgeUI.jobForm;
        form.build=(rec?.refs||[]).find(ref=>doc.records[ref.id]?.kind==='build')?.id||'';
        form.hands=(rec?.data.plan?.initial_hand||[]).map(c=>c.code).join(' ');
        const panel=$('#knowledge-jobs');if(panel)panel.outerHTML=jobsHTML();
      }
      return;
    }
    if (el.dataset.kBind) {
      el.dataset.kTouched='1';knowledgeUI.dirty=true;
      try { bindInput(el); } catch (err) { notice('字段格式错误：' + (err.message || '')); }
      return;
    }
    switch (el.dataset.kRole) {
      case 'filter-kind': knowledgeUI.kindFilter = el.value; refreshRecordList(); return;
      case 'filter-tag': knowledgeUI.tagFilter = el.value; refreshRecordList(); return;
      case 'filter-deleted': knowledgeUI.showDeleted = el.checked; refreshRecordList(); return;
      default: break;
    }
    if (el.dataset.kAction === 'conflict-pick' && el.checked) {
      const c = knowledgeUI.conflict;
      if (c) c.resolutions[el.dataset.record] = el.value;
      return;
    }
    if (el.id === 'knowledge-file-input' && el.files && el.files[0]) {
      const f = el.files[0]; el.value = ''; void importProjectFile(f).catch(fail); return;
    }
    if (el.id === 'knowledge-source-file-input' && el.files && el.files[0]) {
      const f = el.files[0]; el.value = ''; void importSourceFile(f).catch(fail); return;
    }
    if (el.id === 'knowledge-install-input' && el.files && el.files[0]) {
      const f = el.files[0]; el.value = ''; void installFile(f).catch(fail); return;
    }
  }

  /* ================= 初始化 ================= */
  let initTries = 0;
  function init() {
    if(knowledgeRoot)return;
    const el = document.getElementById('knowledge');
    if (!el) { if (++initTries < 100) setTimeout(init, 200); return; }
    knowledgeRoot = el;
    knowledgeRoot.addEventListener('click', onClick);
    knowledgeRoot.addEventListener('input', onInput);
    knowledgeRoot.addEventListener('change', onChange);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();
