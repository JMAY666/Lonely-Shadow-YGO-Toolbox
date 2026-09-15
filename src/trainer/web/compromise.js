'use strict';

const branchUI={root:null,key:null,selected:null,viewing:false,resources:false,drafts:new Map(),cards:new Map(),config:null,window:null,busy:false};
const branchMenu={context:null,anchor:null};
const selectedBranch=()=>branchUI.root?.branches?.find(b=>b.id===branchUI.selected);
function branchConfigurationDirty() {
  const d=branchUI.config,b=d&&branchUI.root?.branches?.find(b=>b.id===d.id);
  return !!b&&(d.name!==b.name||JSON.stringify({hand:d.hand,expected_action:d.expected_action,note:d.note})!==JSON.stringify(b.conditions));
}
const branchName=code=>branchUI.cards.get(Number(code))?.name||branchUI.root?.catalog?.[code]?.name||String(code);
const branchRestoreMessage=code=>({replay_mismatch:'重放结果与原始记录不一致',state_mismatch:'完整状态校验未通过',
  scene_changes_prior_events:'此手牌配置改变了分支点之前的操作',scene_changes_prior_state:'此手牌配置改变了分支点之前的场面',
  scene_changes_prompt:'此手牌配置无法回到同一合法响应窗口',prompt_unavailable:'缺少可恢复的响应窗口',prompt_not_at_boundary:'该响应不在可恢复的处理边界',
  invalid_replay:'重放记录不完整或已损坏',invalid_scene:'场景手牌配置无效',replay_timeout:'重放超时或已中断',create_failed:'无法创建恢复场地',write_failed:'恢复记录写入失败'})[code]||'恢复校验失败';
function stashBranchDraft() {
  if(flow.draft&&branchUI.root&&flow.draft.id===branchUI.root.id) {
    branchUI.drafts.set(branchUI.key||'main',flow.draft);
    // The name/overall note belongs to the whole plan. Route-specific notes
    // remain in each draft's annotations; switching routes must not drop edits.
    for(const draft of branchUI.drafts.values()) {
      draft.name=flow.draft.name;draft.notes=flow.draft.notes;
    }
  }
}
function adoptBranchRoot(root) {
  closeBranchMenu(false);
  if(root.compromise)return;
  stashBranchDraft();
  if(branchUI.root?.id!==root.id) {
    Object.assign(branchUI,{selected:null,viewing:false,resources:false,config:null});branchUI.drafts.clear();
  }
  branchUI.root=root;branchUI.key=null;branchUI.viewing=false;
  flow.draft=branchUI.drafts.get('main')||null;
  updateBranchNav();
}
function updateBranchNav() {
  const b=selectedBranch(), enabled=!!b&&b.valid!==false&&!branchUI.root?.imported;
  $('#nav-compromise').disabled=!enabled;
  $('#nav-compromise').parentElement.title=enabled?'配置当前选中的妥协分支':'请先在展开时间轴中创建或选择妥协分支';
}
function branchControls(id) {
  const branches=branchUI.root?.branches||[];
  const nodes=branchUI.root?.review?.nodes||[],groups=new Map();
  if(!branches.length)return `<section id="${id}" class="branch-controls"><div class="branch-map-caption"><strong>主线 · ${nodes.length} 个步骤</strong><span>从步骤右键创建妥协分支</span></div></section>`;
  for(const b of branches){const key=b.source.node_id;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(b);}
  const ordered=[...groups].sort((a,b)=>nodes.findIndex(n=>n.id===a[0])-nodes.findIndex(n=>n.id===b[0]));
  return `<section id="${id}" class="branch-controls" aria-label="可视化路线切换"><div class="branch-map-caption"><strong>${branchUI.viewing?escape(selectedBranch()?.name||'妥协分支'):'主线'} <small>· ${branches.length} 条分支</small></strong><span>点击路线切换 · 悬停查看条件</span></div>
    <div class="branch-map-scroll"><div class="branch-map"><button class="branch-main-route" data-branch-route="main" aria-pressed="${!branchUI.viewing}"><strong>主线</strong><small>完整展开</small></button>
    ${ordered.map(([nodeId,items])=>`<div class="branch-fork"><button class="branch-origin" data-branch-origin="${escape(nodeId)}" data-branch-tooltip="${escape(items.map(b=>b.id).join(','))}"><span>●</span> ${nodes.find(n=>n.id===nodeId)?.kind==='initial'?'起手':`Step ${nodes.find(n=>n.id===nodeId)?.number||'?'}`}</button><div class="branch-fork-routes">${items.map(b=>`<button class="branch-route" data-branch-route="${escape(b.id)}" data-branch-tooltip="${escape(b.id)}" aria-pressed="${branchUI.viewing&&branchUI.selected===b.id}"><strong>${escape(b.name)}</strong><small>${escape(b.source.timing)}${b.valid===false?' · 起点失效':!b.report?' · 待展开':''}</small></button>`).join('')}</div></div>`).join('')}
    <button class="branch-main-end" data-branch-origin="final">主线终场 →</button></div></div>
    ${id==='saved-branch'?`<label class="branch-resource-toggle"><input id="${id}-resources" type="checkbox" ${branchUI.resources?'checked':''} ${branchUI.selected?'':'disabled'}>统计包含当前分支的新增资源</label>`:''}</section>`;
}
function bindBranchControls(id, render) {
  const box=$('#'+id);
  box.querySelectorAll('[data-branch-route]').forEach(button=>button.onclick=run(async()=>{
    const route=button.dataset.branchRoute;hideBranchTooltip();
    // Stash annotations before changing the selected route; all drafts stay local until save.
    stashBranchDraft();branchUI.viewing=route!=='main';if(branchUI.viewing)branchUI.selected=route;
    updateBranchNav();await render();
    $('#'+id)?.querySelector(`[data-branch-route="${CSS.escape(route)}"]`)?.focus({preventScroll:true});
  }));
  box.querySelectorAll('[data-branch-origin]').forEach(button=>button.onclick=run(async()=>{
    const node=button.dataset.branchOrigin;stashBranchDraft();branchUI.viewing=false;hideBranchTooltip();await render();
    if(id==='review-branch')selectReviewNode(node);
  }));
  const resource=$(`#${id}-resources`);
  if(resource)resource.onchange=run(async e=>{branchUI.resources=e.target.checked;await render();});
  bindBranchTooltips(box);
}
function hideBranchTooltip() {
  const tip=$('#branch-route-tooltip');if(tip)tip.hidden=true;
  document.querySelectorAll('[aria-describedby="branch-route-tooltip"]').forEach(el=>el.removeAttribute('aria-describedby'));
}
function bindBranchTooltips(box) {
  box.querySelectorAll('[data-branch-tooltip]').forEach(button=>{
    const show=()=>{
      if(!$('#branch-route-tooltip'))document.body.insertAdjacentHTML('beforeend','<div id="branch-route-tooltip" class="branch-route-tooltip" role="tooltip" hidden></div>');
      const tip=$('#branch-route-tooltip'),ids=button.dataset.branchTooltip.split(',');
      tip.innerHTML=ids.map(id=>{
        const b=branchUI.root?.branches?.find(b=>b.id===id);if(!b)return '';
        const hand=[...new Set(b.conditions?.hand||[])].map(code=>`${branchName(code)} ×${b.conditions.hand.filter(c=>c===code).length}`).join('、');
        return `<strong>${escape(b.name)}</strong><p>分支时点：${escape(b.source.operation)} · ${escape(b.source.timing)}</p><p>预设条件：${escape(hand||'未配置对手手牌')}${b.conditions?.note?'；'+escape(b.conditions.note):''}</p><p>实际记录：${observedBranchFacts(b).map(p=>escape(`对方 ${p.source_cards.map(c=>c.name).join('、')} → ${p.affected_cards.map(c=>c.name).join('、')||'影响待核对'}：${p.result}`)).join('<br>')||'尚无已记录干扰'}</p>${b.valid===false?`<p>${escape(b.invalid_reason||'分支起点失效')}</p>`:''}`;
      }).join('<hr>');
      tip.hidden=false;button.setAttribute('aria-describedby','branch-route-tooltip');
      const b=button.getBoundingClientRect(),t=tip.getBoundingClientRect();
      tip.style.left=Math.max(8,Math.min(b.left,innerWidth-t.width-8))+'px';
      tip.style.top=Math.max(8,b.bottom+t.height+12<innerHeight?b.bottom+8:b.top-t.height-8)+'px';
    };
    button.onmouseenter=show;button.onfocus=show;button.onmouseleave=hideBranchTooltip;button.onblur=hideBranchTooltip;
    button.addEventListener('keydown',e=>{if(e.key==='Escape')hideBranchTooltip();});
  });
}
function branchCards(cards=[]) {
  return cards.map(c=>`<span class="branch-card"><img src="/pics/${Number(c.code)}.jpg" alt="${escape(c.name||branchName(c.code))}"><span>${escape(c.name||branchName(c.code))}</span></span>`).join('');
}
function branchPremises(branch, edit=false) {
  if(!branch)return '';
  return `<section class="branch-premises"><h3>${escape(branch.name)} · 分支前提</h3><p>起点：${escape(branch.source.operation)} · ${escape(branch.source.timing)}${branch.source.chain_depth?` · 连锁 ${branch.source.chain_depth}`:''}</p>
    ${branch.valid===false?`<p class="review-warning">${escape(branch.invalid_reason)}</p>`:''}
    <details><summary>预设条件（配置不代表发动或生效）</summary><div class="branch-cards">${Object.entries(branch.conditions.hand.reduce((a,c)=>(a[c]=(a[c]||0)+1,a),{})).map(([code,n])=>`${branchCards([{code,name:branchName(code)}])}<span>×${n}</span>`).join('')||'未配置对手手牌'}</div><p>${escape(branch.conditions.note||'')}</p></details>
    <h4>实际记录</h4>${observedBranchFacts(branch).map(p=>`<div class="branch-event">${branchCards(p.source_cards)}<b>→</b>${p.affected_cards.length?branchCards(p.affected_cards):'<span>受影响卡牌未确认</span>'}<div><strong>${escape(p.result)}</strong><small>连锁 ${p.chain_group??'?'} / ${p.chain_link??'?'} · ${escape(p.basis)} · 证据 ${escape(p.evidence_refs.join('、'))}</small>${p.note?`<p>${escape(p.note)}</p>`:''}${edit&&!p.confirmed?`<button data-branch-associate="${escape(p.source_action)}">补充关联或说明</button>`:''}</div></div>`).join('')||'<p>尚无已记录的对方发动；预设卡牌不会显示为实际阻抗。</p>'}
    ${branch.report?`<details><summary>接管原始操作 · ${(branch.report.control_records||[]).length} 条</summary><ol>${(branch.report.control_records||[]).map(r=>`<li>记录 ${r.seq} · ${r.kind==='response'?`对手手动选择（规则窗口 ${r.prompt}）`:`${r.manual?'接管对手':'交还 AI 托管'}`}</li>`).join('')}</ol></details>`:'<p>尚未进入妥协场，无分支终场。</p>'}</section>`;
}
function displayBranchRoute() {
  closeBranchMenu(false);
  stashBranchDraft();
  const root=branchUI.root,b=selectedBranch();
  const common=branchUI.drafts.get('main')||branchUI.drafts.get(branchUI.key)||{};
  const chosen=branchUI.viewing&&b?b:null;
  branchUI.key=chosen?.id||null;
  flow.draft=branchUI.drafts.get(branchUI.key||'main')||null;
  const pending={actions:[],events:[],catalog:root.catalog,initial_hand:[],final_state:null,status:'configured',review:{nodes:[{id:'initial',kind:'initial',number:1,state:null,action_ids:[]},{id:'final',kind:'final',number:2,state:null,action_ids:[]}],boundary_note:'尚未进入妥协场，此分支没有场面或终场。'}};
  const r=chosen?{...(chosen.report||pending),id:root.id,name:common.name??root.name,plan_stage:chosen.report?root.plan_stage:'branch_pending',edit_revision:root.edit_revision,
    expansion:{...(chosen.report?.expansion||root.expansion),name:common.name??root.expansion.name,notes:common.notes??root.expansion.notes},_route:chosen.id}: {...root,_route:'main'};
  reviewUI.report=null;mountReview(r);
  if(chosen&&flow.draft){flow.draft.originalName=root.expansion.name;flow.draft.originalNotes=root.expansion.notes;}
  updateBranchNav();
}
function mountBranchSidebar() {
  const root=branchUI.root;
  if(!root||root.id!==reviewUI.report?.id||reviewUI.report.compromise&&!reviewUI.report._route)return;
  hideBranchTooltip();
  $('#review-route-map').innerHTML=branchControls('review-branch');
  bindBranchControls('review-branch',displayBranchRoute);
  const b=selectedBranch();
  if(branchUI.viewing&&b)$('#review-steps').insertAdjacentHTML('afterend',`<details class="branch-record-details"><summary>分支条件与实际记录 · ${escape(b.name)}</summary>${branchPremises(b,true)}</details>`);
  $('#review-steps').insertAdjacentHTML('beforebegin','<p class="branch-context-hint">右键步骤查看分支操作 · Shift+F10</p>');
  document.querySelectorAll('#review-steps [data-review-node]').forEach(button=>{
    button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-controls','branch-context-menu');
    button.setAttribute('aria-keyshortcuts','Shift+F10');button.title='右键打开分支操作（Shift+F10）';
    const forks=!branchUI.viewing&&(root.branches||[]).filter(b=>b.source.node_id===button.dataset.reviewNode);
    if(forks?.length){button.dataset.branchTooltip=forks.map(b=>b.id).join(',');button.insertAdjacentHTML('beforeend',`<em class="review-fork-badge">⑂ ${forks.length} 条分支</em>`);}
  });
  bindBranchTooltips($('#review-steps'));
  document.querySelectorAll('[data-branch-associate]').forEach(button=>button.onclick=run(()=>editBranchAssociation(button.dataset.branchAssociate)));
  if(branchUI.viewing&&$('#delete-draft'))$('#delete-draft').onclick=run(deleteSelectedBranch);
  if($('#draft-conditions')&&branchUI.viewing)$('#draft-conditions').onclick=run(openBranchDesign);
}
function branchNodeContext(nodeId) {
  const root=branchUI.root,node=reviewUI.nodes.find(n=>n.id===nodeId);
  if(!root||root.id!==reviewUI.report?.id||!node)return null;
  const points=(root.branch_points||[]).filter(p=>p.node_id===nodeId);
  const reason=branchUI.viewing||reviewUI.report.compromise?'妥协分支内部暂不支持创建子分支。':
    app.active?'请先结束当前展开，再从主线创建妥协分支。':
    flow.busy||flow.saving||branchUI.busy?'正在处理当前操作，请稍后再试。':
    !flow.draft?'此记录只读，不能创建妥协分支。':
    !points.length?'此步骤没有可准确恢复的时点；缺少重放资料的旧记录只能回看。':'';
  return {rootId:root.id,revision:root.branches_revision||0,mainRevision:root.review?.revision,
    route:branchUI.key,nodeId,number:node.number,title:reviewTitle(node),name:flow.draft?.name||root.name,points,reason};
}
function branchMenuPosition(x,y,width,height,viewportWidth,viewportHeight) {
  return {left:Math.max(8,Math.min(x+4,viewportWidth-width-8)),top:Math.max(8,Math.min(y+4,viewportHeight-height-8))};
}
function branchMenuTrigger(context) {
  return context&&branchUI.root?.id===context.rootId?
    document.querySelector(`#review-steps [data-review-node="${CSS.escape(context.nodeId)}"]`):null;
}
function closeBranchMenu(focus=true) {
  const context=branchMenu.context;
  if(!context)return;
  branchMenu.context=null;branchMenu.anchor=null;
  const dialog=$('#branch-context-menu'),trigger=branchMenuTrigger(context);
  trigger?.removeAttribute('aria-expanded');
  if(dialog?.open)dialog.close();
  if(focus)trigger?.focus({preventScroll:true});
}
function openBranchMenu(nodeId,x,y) {
  closeBranchMenu(false);
  if(app.view!=='history'||!branchNodeContext(nodeId))return;
  selectReviewNode(nodeId);
  const context=branchNodeContext(nodeId),dialog=$('#branch-context-menu');
  if(!context)return;
  branchMenu.context=context;
  const trigger=branchMenuTrigger(context);
  branchMenu.anchor=trigger?.getBoundingClientRect();trigger?.setAttribute('aria-expanded','true');
  dialog.innerHTML=`<header><h2 id="branch-context-title">创建妥协分支</h2><button id="branch-context-close" aria-label="关闭分支操作">×</button></header>
    <p class="branch-context-source">${escape(context.name)}<br><strong>Step ${context.number}${context.title===`Step ${context.number}`?'':' · '+escape(context.title)}</strong></p>
    <label for="branch-point">分支时点</label><select id="branch-point" ${context.reason?'disabled':''}>${context.points.map(p=>`<option value="${p.checkpoint}">${escape(p.timing)}${p.chain_depth?' · 连锁 '+p.chain_depth:''}</option>`).join('')||'<option>无可用时点</option>'}</select>
    <p id="branch-context-operation"></p><p id="branch-context-status" role="status">${escape(context.reason||'准确恢复到所选时点，主线后续步骤和终场保持完整。')}</p>
    <footer><button id="branch-context-cancel">取消</button><button id="create-compromise" class="primary" ${context.reason?'disabled':''}>从此处创建妥协分支</button></footer>`;
  const describe=()=>{$('#branch-context-operation').textContent=context.points.find(p=>p.checkpoint===Number($('#branch-point').value))?.operation||'';};
  $('#branch-point').onchange=describe;describe();
  $('#branch-context-close').onclick=$('#branch-context-cancel').onclick=()=>{if(!branchMenu.context?.submitting)closeBranchMenu();};
  $('#create-compromise').onclick=run(createBranchFromMenu);
  // Show at a safe initial position, then measure and place before this frame paints.
  dialog.style.left='8px';dialog.style.top='8px';dialog.showModal();
  const box=dialog.getBoundingClientRect(),position=branchMenuPosition(x,y,box.width,box.height,innerWidth,innerHeight);
  dialog.style.left=position.left+'px';dialog.style.top=position.top+'px';
  (context.reason?$('#branch-context-close'):$('#branch-point')).focus({preventScroll:true});
}
async function createBranchFromMenu() {
  const context=branchMenu.context;
  if(!context||branchUI.busy)return;
  const fresh=branchNodeContext(context.nodeId),point=Number($('#branch-point').value);
  if(!fresh||fresh.rootId!==context.rootId||fresh.revision!==context.revision||fresh.mainRevision!==context.mainRevision||fresh.route!==context.route||fresh.reason||!context.points.some(p=>p.checkpoint===point)) {
    $('#branch-context-status').textContent=fresh?.reason||'路线或分支时点已变化，请关闭后重新右键选择。';
    $('#create-compromise').disabled=true;return;
  }
  branchUI.busy=true;context.submitting=true;
  $('#branch-context-menu').querySelectorAll('button,select').forEach(el=>el.disabled=true);
  $('#branch-context-status').textContent='正在创建分支……';
  try {
    stashBranchDraft();
    const result=await api('/api/branches/create',{id:context.rootId,revision:context.revision,checkpoint:point,node_id:context.nodeId});
    closeBranchMenu(false);
    if(branchUI.root?.id!==context.rootId)return;
    branchUI.root=result;branchUI.selected=result.branches.at(-1).id;branchUI.config=null;updateBranchNav();await openBranchDesign();
  } catch(error) {
    if(branchMenu.context===context) {
      $('#branch-context-status').textContent=`创建失败：${error.message}。当前时点仍保留，可重试或取消。`;
      $('#branch-context-menu').querySelectorAll('button,select').forEach(el=>el.disabled=false);
    } else throw error;
  } finally {branchUI.busy=false;context.submitting=false;}
}
async function openBranchDesign() {
  const b=selectedBranch();if(!b||b.valid===false)return notice('请先在展开时间轴中创建或选择妥协分支');
  if(branchUI.config?.id!==b.id)branchUI.config={id:b.id,name:b.name,...structuredClone(b.conditions)};
  await Promise.all([...new Set(b.conditions.hand)].map(async code=>branchUI.cards.set(code,await card(code))));
  renderBranchDesign();switchView('compromise');
}
function renderBranchDesign() {
  const b=selectedBranch(),d=branchUI.config;if(!b||!d)return;
  const counts=d.hand.reduce((a,c)=>(a[c]=(a[c]||0)+1,a),{});
  $('#compromise-design').innerHTML=`<header><div class="eyebrow">COMPROMISE / SETUP</div><h1>妥协场构建前置</h1><p>当前方案：${escape(branchUI.root.name)}<br>当前分支：${escape(b.name)}<br>分支起点：${escape(b.source.operation)} · ${escape(b.source.timing)} · 节点 #${b.source.checkpoint}</p></header>
    <div class="branch-setup-grid"><section class="panel"><label>分支名称<input id="branch-name" maxlength="80" value="${escape(d.name)}"></label><label>预期受干扰的我方操作<select id="branch-expected"><option value="">暂不标记</option>${branchUI.root.actions.filter(a=>a.cards.some(c=>c.controller===0)).map(a=>`<option value="${escape(a.id)}" ${d.expected_action===a.id?'selected':''}>${escape((a.heading||a.summary).slice(0,100))}</option>`).join('')}</select></label><label>预设条件说明<textarea id="branch-note" rows="3" maxlength="4000">${escape(d.note)}</textarea></label><p>下列卡牌只替换本分支场景中的对手手牌，不改变来源卡组。是否可以发动、响应与实际结算均由规则引擎决定。</p><h2>对手场景手牌 · ${d.hand.length} 张</h2><div class="branch-cards">${Object.entries(counts).map(([c,n])=>`<div class="branch-hand-item">${branchCards([{code:c,name:branchName(c)}])}<label>数量<input data-branch-count="${c}" type="number" min="0" max="60" value="${n}"></label><button data-branch-remove="${c}">移除</button></div>`).join('')||'<p>空手牌，可从右侧搜索添加。</p>'}</div><p id="branch-setup-status" role="status">${b.operation?.status==='error'?'恢复失败：'+escape(b.operation.error)+'，主线与原始记录保留。':b.session_id?'已有一次妥协尝试，可查看结果，或修改条件后重新进入。':'尚未进入场地；创建和配置均未正式保存。'}</p><div class="plan-actions"><button id="branch-enter" class="primary" ${app.active?'disabled':''}>进入妥协场</button><button id="branch-return">返回方案调整</button><button id="branch-delete" class="danger">删除当前分支</button></div></section>
    <section class="panel"><h2>添加阻抗卡牌</h2><label>搜索卡名、编号或效果<input id="branch-search" type="search" placeholder="例如：灰流丽"></label><div id="branch-search-results" class="branch-search-results"></div></section></div>`;
  $('#branch-name').oninput=e=>d.name=e.target.value;
  $('#branch-expected').onchange=e=>d.expected_action=e.target.value||null;
  $('#branch-note').oninput=e=>d.note=e.target.value;
  document.querySelectorAll('[data-branch-count]').forEach(input=>input.onchange=()=>{
    const n=Number(input.value),code=Number(input.dataset.branchCount);
    if(!Number.isInteger(n)||n<0||n>60)return notice('数量需为 0–60 的整数');
    d.hand=d.hand.filter(c=>c!==code).concat(Array(n).fill(code));renderBranchDesign();
  });
  document.querySelectorAll('[data-branch-remove]').forEach(button=>button.onclick=()=>{d.hand=d.hand.filter(c=>c!==Number(button.dataset.branchRemove));renderBranchDesign();});
  let generation=0,timer;
  $('#branch-search').oninput=e=>{clearTimeout(timer);const q=e.target.value,version=++generation;timer=setTimeout(()=>void run(async()=>{
    const result=await api('/api/cards?q='+encodeURIComponent(q));if(generation!==version||!$('#branch-search-results'))return;
    const cards=result.cards.filter(c=>!c.extra&&!(c.type&0x4000));cards.forEach(c=>branchUI.cards.set(c.id,c));
    $('#branch-search-results').innerHTML=cards.map(c=>`<button data-branch-add="${c.id}" title="添加 1 张">${branchCards([{code:c.id,name:c.name}])}＋1</button>`).join('');
    document.querySelectorAll('[data-branch-add]').forEach(button=>button.onclick=()=>{if(d.hand.length>=60)return notice('场景手牌最多 60 张');d.hand.push(Number(button.dataset.branchAdd));renderBranchDesign();});
  })(),250);};
  $('#branch-enter').onclick=run(enterBranch);
  $('#branch-return').onclick=run(async()=>{await saveBranchConfiguration();displayBranchRoute();switchView('history');});
  $('#branch-delete').onclick=run(deleteSelectedBranch);
}
async function saveBranchConfiguration() {
  const d=branchUI.config,b=selectedBranch();if(!d||d.id!==b?.id)return;
  const conditions={hand:d.hand,expected_action:d.expected_action,note:d.note};
  if(d.name===b.name&&JSON.stringify(conditions)===JSON.stringify(b.conditions))return;
  const cached=branchUI.drafts.get(b.id);
  if(cached&&b.report&&JSON.stringify(cached.annotations)!==cached.originalAnnotations) {
    branchUI.root=await api('/api/branches/update',{id:branchUI.root.id,branch_id:b.id,revision:branchUI.root.branches_revision,annotations:cached.annotations});
    cached.originalAnnotations=JSON.stringify(cached.annotations);
  }
  branchUI.root=await api('/api/branches/update',{id:branchUI.root.id,branch_id:b.id,revision:branchUI.root.branches_revision,name:d.name,conditions});
  d.name=selectedBranch().name;
  if(selectedBranch().session_id!==b.session_id)branchUI.drafts.delete(b.id);
}
async function enterBranch() {
  if(branchUI.busy||app.active)return;branchUI.busy=true;$('#branch-enter').disabled=true;
  try {
    await saveBranchConfiguration();let b=selectedBranch();
    if(b.session_id) {
      if(!await confirmFlow('重新构建此妥协分支？','当前模拟结果会由新尝试替换，原始记录保留。主线与其他分支不变。','重新构建'))return;
      branchUI.root=await api('/api/branches/update',{id:branchUI.root.id,branch_id:b.id,revision:branchUI.root.branches_revision,reset:true});b=selectedBranch();branchUI.drafts.delete(b.id);
    }
    $('#native-loading').hidden=false;$('#native-loading').textContent='正在准确重放主线并校验分支响应窗口……';
    switchView('training');await syncNativeHost();
    const session=await api('/api/branches/enter',{id:branchUI.root.id,branch_id:b.id,revision:branchUI.root.branches_revision});
    branchUI.root.branches_revision=session.branches_revision;b.session_id=session.id;
    resetTimer(session.id,branchUI.root.expansion?.timer||{mode:'off',seconds:0});
    switchView('training');await refreshHistory();await syncNativeHost();
    for(let i=0;i<350;i++) {
      const state=await api(`/api/opponent/state/${session.id}`);
      if(state.operation?.status==='error')throw new Error(branchRestoreMessage(state.operation.error)+'。主线与原始记录保留，请调整条件或重新选择起点。');
      if(state.operation?.status==='ready') {await waitNativeFrame(session.id);startTimer(session.id);openOpponentWindow(session.id);notice('已进入妥协场并暂停对手 AI，请在对手窗口选择合法响应。');return;}
      if(!state.running)throw new Error('恢复未完成，原始记录已保留');
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    throw new Error('恢复超时，请查看分支状态');
  } finally {branchUI.busy=false;if($('#branch-enter'))$('#branch-enter').disabled=!!app.active;}
}
function openOpponentWindow(id) {branchUI.window=window.open(`/opponent.html?session=${encodeURIComponent(id)}`,'opponent-'+id,'width=1050,height=800');}
async function opponentControl(command) {
  const id=app.active?.id;if(!app.active?.compromise)return;
  const state=await api(`/api/opponent/state/${id}`);
  await api('/api/opponent/control',{id,command,version:state.version});
  if(command==='take')openOpponentWindow(id);
}
async function returnFromBranch(context) {
  stashBranchDraft();
  const root=await api('/api/report/'+context.root_id);
  if(branchUI.root?.id!==root.id)branchUI.drafts.clear();
  branchUI.root=root;branchUI.key=null;branchUI.selected=context.branch_id;branchUI.viewing=true;branchUI.config=null;
  flow.draft=null;app.reportId=root.id;displayBranchRoute();switchView('history');
  const branch=selectedBranch();
  notice(branch?.operation?.status==='error'?branchRestoreMessage(branch.operation.error)+'。主线保持完整，请从前置面板调整条件或重新选择起点。':'妥协展开已记录为所属方案的分支草稿，请核对后统一确认保存。');
}
async function prepareBranchSave() {
  if(branchUI.busy)return false;
  if(!branchUI.root||branchUI.root.id!==flow.draft?.id)return true;
  branchUI.busy=true;
  try {
  await saveBranchConfiguration();stashBranchDraft();
  const root=branchUI.root;
  for(const b of root.branches||[]) {
    const d=branchUI.drafts.get(b.id);
    if(d&&JSON.stringify(d.annotations)!==d.originalAnnotations) {
      branchUI.root=await api('/api/branches/update',{id:root.id,branch_id:b.id,revision:branchUI.root.branches_revision,annotations:d.annotations});
      d.originalAnnotations=JSON.stringify(d.annotations);
    }
  }
  branchUI.viewing=false;displayBranchRoute();return true;
  } finally {branchUI.busy=false;}
}
async function deleteSelectedBranch() {
  const b=selectedBranch();if(!b)return;
  if(!await confirmFlow('删除“'+b.name+'”？','仅从本方案的待保存分支中移除，主线、其他分支和原始记录保留。确认保存方案后正式生效。','删除分支'))return;
  branchUI.root=await api('/api/branches/update',{id:branchUI.root.id,branch_id:b.id,revision:branchUI.root.branches_revision,delete:true});
  branchUI.drafts.delete(b.id);Object.assign(branchUI,{selected:null,viewing:false,resources:false,config:null});
  displayBranchRoute();switchView('history');notice('已从草稿移除分支，请确认保存方案。');
}
async function editBranchAssociation(id) {
  const b=selectedBranch(),p=b?.premises.find(p=>p.source_action===id);if(!p)return;
  const dialog=document.createElement('dialog');dialog.className='branch-association';
  dialog.innerHTML=`<h2>补充关联或说明</h2><p>此处为用户说明，不会改写引擎结算结果。</p><label>受影响的我方操作<select id="branch-association-action">${b.report.actions.filter(a=>a.cards.some(c=>c.controller===0)).map(a=>`<option value="${escape(a.id)}">${escape((a.heading||a.summary).slice(0,100))}</option>`).join('')}</select></label><label>说明<textarea id="branch-association-note" maxlength="4000"></textarea></label><button id="branch-association-save">保留说明</button><button id="branch-association-close">取消</button>`;
  document.body.append(dialog);dialog.showModal();dialog.onclose=()=>dialog.remove();
  $('#branch-association-close').onclick=()=>dialog.close();
  $('#branch-association-save').onclick=run(async()=>{
    const associations={...(b.associations||{}),[id]:{action_id:$('#branch-association-action').value,note:$('#branch-association-note').value}};
    branchUI.root=await api('/api/branches/update',{id:branchUI.root.id,branch_id:b.id,revision:branchUI.root.branches_revision,associations});dialog.close();displayBranchRoute();
  });
}
function scopedBranchRequirements(root,b,include) {
  const base=root.requirements;if(!base)return null;
  const result=structuredClone(base),chosen=b?.report?.requirements;
  if(include&&chosen)for(const zone of ['main','extra','opening','random']) {
    const counts=new Map(),needed=new Map();
    const key=c=>`${c.code}:${c.constraint||''}`;
    for(const c of base[zone]||[])counts.set(key(c),(counts.get(key(c))||0)+c.count);
    for(const c of chosen[zone]||[])needed.set(key(c),{...c,count:(needed.get(key(c))?.count||0)+c.count});
    for(const [id,c]of needed)if(c.count>(counts.get(id)||0))result[zone].push({...c,count:c.count-(counts.get(id)||0)});
  }
  return result;
}
function branchResourceHtml(root,b,include) {
  const base=root.requirements,chosen=b?.report?.requirements;if(!base)return '';
  const counts=items=>items.reduce((m,c)=>(m.set(`${c.code}:${c.constraint||''}`,{...c,count:(m.get(`${c.code}:${c.constraint||''}`)?.count||0)+c.count}),m),new Map());
  return `<section class="branch-resource-summary"><h3>资源统计 · 主线${include&&b?' ＋ '+escape(b.name)+'的新增资源':''}</h3>${['main','extra'].map(zone=>{
    const a=counts(base[zone]||[]),extra=[];
    if(include&&chosen)for(const [key,c]of counts(chosen[zone]||[]))if(c.count>(a.get(key)?.count||0))extra.push({...c,count:c.count-(a.get(key)?.count||0)});
    const list=items=>[...items].map(c=>`${escape(c.name||c.constraint)} ×${c.count}`).join('、')||'无';
    return `<p>${zone==='main'?'主卡组':'额外卡组'} · 主线：${list(a.values())}${include?'<br>当前分支新增：'+list(extra):''}</p>`;
  }).join('')}<small>共享份数取两条路线中的较大值；不会累加其他互斥分支。对手卡牌仅列在分支前提中。</small></section>`;
}
function mountSavedBranches(plan) {
  if(!plan.branches?.length)return;
  adoptBranchRoot(plan);
  $('#plan-report').insertAdjacentHTML('afterbegin','<div id="saved-branch-panel"></div>');
  const render=()=>{
    const b=selectedBranch();
    $('#saved-branch-panel').innerHTML=branchControls('saved-branch')+branchResourceHtml(plan,b,branchUI.resources)+(branchUI.viewing&&b?branchPremises(b):'');
    bindBranchControls('saved-branch',render);updateBranchNav();
    const route=branchUI.viewing?b?.report:plan;
    // Rebuild all summary sections together so the end board cannot belong to a different route.
    const container=$('#saved-route-summary');
    if(container)container.innerHTML=route?.requirements?summaryHtml({...scopedBranchRequirements(plan,b,branchUI.resources),final:route.requirements.final},route):'<p>该分支尚无已完成的终场。</p>';
    if(route) {
      const rawView=raw=>{$('#saved-raw-report').innerHTML=renderTrainingReport(route,{raw}).replaceAll('all-events','plan-all-events');$('#plan-all-events').onchange=e=>rawView(e.target.checked);};rawView(false);
    } else $('#saved-raw-report').innerHTML='<p>尚未进入妥协场。</p>';
    $('#generate-plan-tutorial').onclick=()=>openPlanTutorial(plan);
  };render();
}
$('#nav-compromise').onclick=run(openBranchDesign);
document.addEventListener('contextmenu',run(event=>{
  const node=event.target.closest?.('#review-steps [data-review-node]');
  if(!node||app.view!=='history')return;
  event.preventDefault();
  const box=node.getBoundingClientRect();
  openBranchMenu(node.dataset.reviewNode,event.clientX||box.right,event.clientY||box.top+24);
}));
document.addEventListener('keydown',run(event=>{
  if(event.key!=='ContextMenu'&&!(event.key==='F10'&&event.shiftKey&&!event.ctrlKey&&!event.altKey&&!event.metaKey))return;
  const node=event.target.closest?.('#review-steps [data-review-node]');
  if(!node||app.view!=='history')return;
  event.preventDefault();if(event.repeat)return;
  const box=node.getBoundingClientRect();openBranchMenu(node.dataset.reviewNode,box.right,box.top+24);
}));
const branchDialog=$('#branch-context-menu');
branchDialog.addEventListener('cancel',event=>{event.preventDefault();if(!branchMenu.context?.submitting)closeBranchMenu();});
branchDialog.addEventListener('keydown',event=>{
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(!branchMenu.context?.submitting)closeBranchMenu();}
});
branchDialog.addEventListener('pointerdown',event=>{
  const box=branchDialog.getBoundingClientRect();
  if(!branchMenu.context?.submitting&&event.target===branchDialog&&(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom))closeBranchMenu();
});
document.addEventListener('scroll',event=>{
  hideBranchTooltip();
  if(!branchMenu.context||branchDialog.contains(event.target))return;
  const box=branchMenuTrigger(branchMenu.context)?.getBoundingClientRect(),anchor=branchMenu.anchor;
  if(!box||!anchor||Math.abs(box.left-anchor.left)>.5||Math.abs(box.top-anchor.top)>.5)closeBranchMenu(false);
},true);
window.addEventListener('resize',()=>{hideBranchTooltip();closeBranchMenu(false);});
const opponentBar=document.createElement('div');opponentBar.id='opponent-control-bar';opponentBar.className='opponent-control-bar';opponentBar.hidden=true;
opponentBar.innerHTML='<strong id="opponent-control-label">妥协对局</strong><button id="take-opponent">接管对手</button><button id="release-opponent">交还 AI 托管</button>';
$('#native-stage').parentElement.insertBefore(opponentBar,$('#native-stage'));
$('#take-opponent').onclick=run(()=>opponentControl('take'));$('#release-opponent').onclick=run(()=>opponentControl('release'));
let pollingOpponent=false;
setInterval(async()=>{
  opponentBar.hidden=!app.active?.compromise;if(opponentBar.hidden||pollingOpponent)return;
  pollingOpponent=true;const id=app.active.id;
  try {const s=await api(`/api/opponent/state/${id}`);if(app.active?.id===id)$('#opponent-control-label').textContent=`${app.active.name} · ${s.manual?'对手由用户接管':'对手由 AI 托管'} · ${s.player===1&&!s.answered?'等待对手选择':'等待我方或引擎处理'}`;}
  catch{}finally{pollingOpponent=false;}
},500);
