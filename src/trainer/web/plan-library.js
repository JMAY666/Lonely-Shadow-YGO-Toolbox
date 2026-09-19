'use strict';

const planLibraryUI={plans:[],folder:'',info:null,selection:null,importDocument:null,preview:null,favoritesOnly:false,favoriteBusy:new Set()};
const tagSearchKey=value=>String(value||'').normalize('NFKC').trim().toLocaleLowerCase();
const tagMatches=(tag,q)=>[tag.name,...tag.aliases||[]].some(value=>tagSearchKey(value).includes(tagSearchKey(q)));
function filterPlans(plans,query='',tag='',primaryOnly=false,favoritesOnly=false) {
  const q=tagSearchKey(query);
  return plans.filter(p=>{
    const tags=(p.tags||[]).filter(t=>!primaryOnly||t.primary);
    return (!favoritesOnly||p.favorite)&&(!tag||(tag==='untagged'?!p.tags?.length:tags.some(t=>t.id===tag)))&&
      (!q||tagSearchKey(p.name).includes(q)||tagSearchKey(p.deck_name).includes(q)||tags.some(t=>tagMatches(t,q))||(p.search_cards||[]).some(c=>tagSearchKey(c.name).includes(q)||String(c.code)===q));
  });
}
function tagChips(tags) {
  return `<span class="plan-tag-chips">${tags.map(t=>`<span class="plan-tag ${t.primary?'is-primary':''}" title="${escape([t.name,...t.aliases||[]].join(' / '))}">${t.primary?'★ ':''}${escape(t.name)}</span>`).join('')}</span>`;
}
function renderPlanList(plans=planLibraryUI.plans) {
  planLibraryUI.plans=plans;
  const tags=new Map();
  for(const p of plans)for(const tag of p.tags||[])tags.set(tag.id,tag);
  if(planLibraryUI.folder!=='untagged'&&!tags.has(planLibraryUI.folder))planLibraryUI.folder='';
  const folder=planLibraryUI.folder,q=$('#plan-search').value;
  const visible=filterPlans(plans,q,folder,false,planLibraryUI.favoritesOnly);
  $('#plan-favorites-only').setAttribute('aria-pressed',String(planLibraryUI.favoritesOnly));
  const name=folder==='untagged'?'未归类':tags.get(folder)?.name;
  $('#plan-folder-path').innerHTML=`<button data-plan-folder="">展开方案</button>${folder?`<span>›</span><strong>${escape(name)}</strong>`:''}`;
  $('#plan-folder-up').disabled=!folder;
  $('#plan-folder-up').onclick=()=>openPlanFolder('');
  $('#plan-count').textContent=`${visible.length} / ${plans.length} 个方案`;
  const folders=[...[...tags.values()].sort((a,b)=>a.name.localeCompare(b.name,'zh-CN')).map(t=>({id:t.id,name:t.name,count:plans.filter(p=>p.tags?.some(x=>x.id===t.id)).length})),...(plans.some(p=>!p.tags?.length)?[{id:'untagged',name:'未归类',count:plans.filter(p=>!p.tags?.length).length}]:[])];
  const directories=!folder&&!q.trim()?`<div class="plan-folder-grid">${folders.map(t=>`<button data-plan-folder="${escape(t.id)}" class="plan-folder"><svg viewBox="0 0 48 38" aria-hidden="true"><path d="M3 7Q3 3 7 3H20L25 9H41Q45 9 45 13V31Q45 35 41 35H7Q3 35 3 31Z" fill="#e3bd67"/><path d="M3 14H45V31Q45 35 41 35H7Q3 35 3 31Z" fill="#f3d68b"/></svg><strong>${escape(t.name)}</strong><small>${t.count} 个方案</small></button>`).join('')}</div>`:'';
  $('#plan-list').innerHTML=directories+visible.map(p=>`<div class="plan-file-row ${p.favorite?'is-favorite':''}"><button class="history-item plan-file ${p.id===flow.selectedPlan?'current':''}" data-plan="${escape(p.id)}"><span class="plan-file-icon" aria-hidden="true">▤</span><strong>${escape(p.name)}</strong><small>${escape(p.deck_name)}${p.imported?' · 已导入':''}</small><small>${dt(p.saved_ms)}</small></button>${planFavoriteButton(p)}</div>`).join('')+(!visible.length?`<div class="empty">${planLibraryUI.favoritesOnly?'当前筛选下没有收藏方案':plans.length?'没有匹配的方案':'还没有正式方案'}<br><small>${plans.length?'可调整搜索或收藏筛选。':'展开结束后保存，或导入分享文件。'}</small></div>`:'');
  document.querySelectorAll('[data-plan-folder]').forEach(b=>b.onclick=()=>openPlanFolder(b.dataset.planFolder));
  bindPlanFavorites($('#plan-list'));
}
function planFavoriteButton(plan) {
  return `<button class="plan-favorite-toggle" data-plan-favorite="${escape(plan.id)}" aria-pressed="${!!plan.favorite}" aria-label="${escape((plan.favorite?'取消收藏：':'收藏方案：')+plan.name)}" title="${plan.favorite?'取消收藏':'收藏方案'}" ${planLibraryUI.favoriteBusy.has(plan.id)?'disabled':''}>${plan.favorite?'★':'☆'}</button>`;
}
function bindPlanFavorites(container) {
  for(const button of container.querySelectorAll('[data-plan-favorite]'))button.onclick=run(async event=>{
    event.stopPropagation();const id=button.dataset.planFavorite;if(planLibraryUI.favoriteBusy.has(id))return;
    planLibraryUI.favoriteBusy.add(id);button.disabled=true;
    try {
      const saved=await api('/api/plan-favorites',{id,favorite:button.getAttribute('aria-pressed')!=='true'}),favorite=saved.plans.includes(id);
      // Responses for different stars may arrive out of order. Apply only the
      // acknowledged item, not an older snapshot of every other favorite.
      for(const plan of planLibraryUI.plans)if(plan.id===id)plan.favorite=favorite;
      if(typeof duelState==='function')for(const plan of duelState().result?.matches||[])if(plan.id===id)plan.favorite=favorite;
      renderPlanList();
      const detail=$('#saved-plan-favorite');
      if(detail){const plan=planLibraryUI.plans.find(p=>p.id===detail.dataset.id);if(plan){detail.innerHTML=planFavoriteButton(plan);bindPlanFavorites(detail);}}
      if(typeof duelState==='function'&&duelState().stage===duelStages.plans)renderDuel();
    } finally {
      planLibraryUI.favoriteBusy.delete(id);
      for(const control of document.querySelectorAll('[data-plan-favorite]'))if(control.dataset.planFavorite===id)control.disabled=false;
    }
  });
}
function openPlanFolder(id) {
  planLibraryUI.folder=id;$('#plan-search').value='';renderPlanList();
}
async function downloadPlan(plan) {
  const data=await api(`/api/plan-export/${plan.id}`);
  const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),anchor=document.createElement('a');
  anchor.href=url;anchor.download=(plan.name.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'_').replace(/[. ]+$/,'').slice(0,65)||'展开方案')+'.ygoplan.json';
  document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
  notice('方案分享文件已生成，包含构筑、起手、步骤、说明、终场和标签。');
}
function mountPlanLibrary(plan) {
  const actions=$('#plan-report .plan-actions');
  actions.insertAdjacentHTML('beforeend','<button id="export-plan">导出方案</button><button id="edit-plan-tags">编辑标签</button>');
  const title=$('#plan-report h2');title.insertAdjacentHTML('afterend','<div id="saved-plan-tags" class="saved-plan-tags"></div>');
  $('#export-plan').onclick=run(()=>downloadPlan(plan));
  $('#edit-plan-tags').onclick=run(()=>openPlanTags(plan.id));
  const summary=planLibraryUI.plans.find(p=>p.id===plan.id);
  actions.insertAdjacentHTML('beforeend',`<span id="saved-plan-favorite" data-id="${escape(plan.id)}">${planFavoriteButton({...plan,favorite:summary?.favorite})}</span>`);
  bindPlanFavorites(actions);
  $('#saved-plan-tags').innerHTML=tagChips(summary?.tags||[])+`<small>${summary?.tag_mode==='automatic'?'自动识别 · 可人工修改':summary?.tags?.length?'★ 为主标签':'尚未分类，可编辑标签或自动识别'}</small>`;
}

function ensureLibraryDialogs() {
  if($('#plan-tags-dialog'))return;
  document.body.insertAdjacentHTML('beforeend',`
  <dialog id="plan-tags-dialog" class="library-dialog" aria-labelledby="plan-tags-title"><header><h2 id="plan-tags-title">方案标签</h2><button data-library-close="plan-tags-dialog">关闭</button></header>
    <p>★ 主标签用于分类；可手动指定多个。自动识别按实际使用浓度，只设置一个主标签。</p>
    <div id="chosen-plan-tags"></div><div class="library-actions"><button id="auto-plan-tags">自动识别标签</button></div>
    <label>添加标签<input id="plan-tag-search" type="search" placeholder="输入系列正名或别名"></label><div id="tag-options" class="tag-options"></div>
    <details><summary>查看浓度与识别依据</summary><p>按实际参与路线的我方卡牌种类去重；至少 2 种且占比达到 20% 才自动添加。抽到但未使用的卡和对方卡牌不计入。</p><div id="tag-evidence"></div></details>
    <p id="plan-tags-status" role="status"></p><footer><button id="save-plan-tags" class="primary">保存标签</button></footer></dialog>
  <dialog id="plan-import-dialog" class="library-dialog" aria-labelledby="plan-import-title"><header><h2 id="plan-import-title">导入展开方案</h2><button data-library-close="plan-import-dialog">关闭</button></header>
    <p>选择分享的 .ygoplan.json 文件（最多 20 MB）。导入后可回看、调整、生成一图流或按条件再次展开。同名方案独立保存，重复文件不会重复导入。</p>
    <label>方案文件<input id="plan-import-file" type="file" accept=".json,.ygoplan.json,application/json"></label><div id="plan-import-preview"></div><p id="plan-import-status" role="status"></p><footer><button id="confirm-import-plan" class="primary" disabled>导入方案</button></footer></dialog>`);
  document.querySelectorAll('[data-library-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.libraryClose).close());
  $('#plan-tag-search').oninput=renderTagOptions;
  $('#auto-plan-tags').onclick=()=>{planLibraryUI.selection=structuredClone(planLibraryUI.info.suggestions);renderChosenTags();renderTagOptions();$('#plan-tags-status').textContent='已按浓度重新识别，保存后生效。';};
  $('#save-plan-tags').onclick=savePlanTags;
  $('#plan-import-file').onchange=previewPlanImport;
  $('#confirm-import-plan').onclick=commitPlanImport;
  $('#plan-tags-dialog').addEventListener('click',e=>{
    const button=e.target.closest('button'),s=planLibraryUI.selection;if(!button||!s)return;
    const {tagAdd,tagRemove,tagPrimary}=button.dataset;
    if(tagAdd&&!s.tag_ids.includes(tagAdd)&&s.tag_ids.length<30)s.tag_ids.push(tagAdd);
    if(tagRemove){s.tag_ids=s.tag_ids.filter(id=>id!==tagRemove);s.primary_ids=s.primary_ids.filter(id=>id!==tagRemove);}
    if(tagPrimary)s.primary_ids=s.primary_ids.includes(tagPrimary)?s.primary_ids.filter(id=>id!==tagPrimary):[...s.primary_ids,tagPrimary];
    if(tagAdd||tagRemove||tagPrimary){s.mode='manual';renderChosenTags();renderTagOptions();$('#plan-tags-status').textContent='标签选择尚未保存。';}
  });
}
async function openPlanTags(id) {
  ensureLibraryDialogs();
  planLibraryUI.info=await api(`/api/plan-tags/${id}`);
  planLibraryUI.selection=structuredClone(planLibraryUI.info.classification);
  $('#plan-tag-search').value='';$('#plan-tags-status').textContent='保存只修改分类，已保存的步骤与说明保留。';
  renderChosenTags();renderTagOptions();
  $('#tag-evidence').innerHTML=planLibraryUI.info.suggestions.candidates.map(item=>{
    const tag=planLibraryUI.info.tags.find(t=>t.id===item.id);
    return `<p><strong>${escape(tag?.name||item.id)}</strong> · ${item.count}/${item.total} 种 · ${Math.round(item.ratio*100)}% · ${item.eligible?'达到阈值':'未达到阈值'}<br><small>${item.cards.map(c=>escape(c.name+(c.basis?`（${c.basis}）`:''))).join('、')}</small></p>`;
  }).join('')||'<p>当前记录没有足够的系列卡牌证据，可手动添加。</p>';
  $('#plan-tags-dialog').showModal();
}
function renderChosenTags() {
  const s=planLibraryUI.selection;
  $('#chosen-plan-tags').innerHTML=s.tag_ids.map(id=>{
    const tag=planLibraryUI.info.tags.find(t=>t.id===id),primary=s.primary_ids.includes(id);
    return `<div class="chosen-tag"><span>${escape(tag?.name||id)}</span><button data-tag-primary="${escape(id)}" aria-pressed="${primary}" aria-label="${escape((primary?'取消':'设为')+'主标签：'+(tag?.name||id))}">${primary?'★ 主标签':'☆ 设为主标签'}</button><button data-tag-remove="${escape(id)}" aria-label="${escape('移除标签：'+(tag?.name||id))}">移除</button></div>`;
  }).join('')||'<p class="empty">暂未添加标签</p>';
}
function renderTagOptions() {
  const s=planLibraryUI.selection,q=$('#plan-tag-search').value;
  const options=planLibraryUI.info.tags.filter(t=>!s.tag_ids.includes(t.id)&&tagMatches(t,q));
  $('#tag-options').innerHTML=options.slice(0,40).map(t=>`<button data-tag-add="${escape(t.id)}" ${s.tag_ids.length>=30?'disabled':''}>＋ ${escape(t.name)}</button>`).join('')||'<p>没有匹配的可添加标签。可先关闭此窗口，从主栏目底部的“TAG 管理”新增。</p>';
}
async function savePlanTags() {
  const button=$('#save-plan-tags');button.disabled=true;
  try {
    const info=planLibraryUI.info,s=planLibraryUI.selection;
    const saved=await api('/api/plans/classify',{id:info.id,revision:info.edit_revision,classification:s,automatic:s.mode==='automatic'});
    await showPlan(saved.id);$('#plan-tags-dialog').close();notice('方案标签已保存。');
  }catch(e){$('#plan-tags-status').textContent=`保存失败：${e.message}`;}finally{button.disabled=false;}
}
async function previewPlanImport() {
  planLibraryUI.importDocument=null;planLibraryUI.preview=null;
  $('#confirm-import-plan').disabled=true;$('#plan-import-preview').innerHTML='';$('#plan-import-status').textContent='';
  const file=$('#plan-import-file').files[0];if(!file)return;
  try {
    if(!file.size||file.size>=20*1024*1024)throw new Error('文件必须小于 20 MB');
    const document=JSON.parse((await file.text()).replace(/^\uFEFF/,''));
    const preview=await api('/api/plans/import-preview',{document});
    if($('#plan-import-file').files[0]!==file)return;
    planLibraryUI.importDocument=document;planLibraryUI.preview=preview;
    $('#plan-import-preview').innerHTML=`<h3>${escape(preview.name)}</h3><p>${preview.steps} 项操作 · 主卡组 ${preview.deck_count.main} · 额外 ${preview.deck_count.extra} · 副卡组 ${preview.deck_count.side}</p>${tagChips(preview.tags)}<p>${preview.duplicate_id?'这个文件已导入，将打开已有方案。':'将新建独立方案，保留现有同名方案。'}</p>${preview.notes.map(n=>`<p>${escape(n)}</p>`).join('')}${preview.missing_cards.length?`<p>本地缺少 ${preview.missing_cards.length} 张卡的资源，可先回看冻结资料；再次展开前需补齐资源。</p>`:''}`;
    if(typeof OpeningRules!=='undefined'&&OpeningRules.has(document.plan?.expansion?.conditions))$('#plan-import-preview').insertAdjacentHTML('beforeend',OpeningRules.summary(document.plan));
    $('#confirm-import-plan').disabled=false;
  }catch(e){if($('#plan-import-file').files[0]===file)$('#plan-import-status').textContent=`无法导入：${e.message}`;}
}
async function commitPlanImport() {
  if(!planLibraryUI.preview)return;
  const button=$('#confirm-import-plan');button.disabled=true;$('#plan-import-file').disabled=true;
  try {
    const result=await api('/api/plans/import',{document:planLibraryUI.importDocument,fingerprint:planLibraryUI.preview.fingerprint});
    $('#plan-import-dialog').close();await showPlan(result.id);notice(result.duplicate?'已打开此前导入的方案。':'方案已导入，可回看、调整和分享。');
  }catch(e){$('#plan-import-status').textContent=`导入失败：${e.message}`;}finally{button.disabled=false;$('#plan-import-file').disabled=false;}
}
$('#plan-search').oninput=()=>renderPlanList();
$('#plan-favorites-only').onclick=()=>{planLibraryUI.favoritesOnly=!planLibraryUI.favoritesOnly;renderPlanList();};
$('#import-plan').onclick=()=>{
  ensureLibraryDialogs();planLibraryUI.importDocument=null;planLibraryUI.preview=null;
  $('#plan-import-file').value='';$('#plan-import-preview').innerHTML='';$('#plan-import-status').textContent='';$('#confirm-import-plan').disabled=true;$('#plan-import-dialog').showModal();
};
