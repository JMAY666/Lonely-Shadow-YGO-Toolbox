'use strict';

const duelDefaults = {back:'Control+Shift+Left',forward:'Control+Shift+Right',up:'Control+Shift+Up',down:'Control+Shift+Down',end:''};
const duelLabels = {back:'后退',forward:'前进',up:'上一条路线',down:'下一条路线',end:'展开结束'};
const newDuel = () => ({stage:0,reached:0,mode:null,deck:null,deckPage:'method',decks:[],manualOrder:false,first:false,count:5,hand:Array(5).fill(null),
  marks:new Set(),target:null,result:null,plan:null,routes:null,graph:null,position:null,ended:false,enabled:false,session:crypto.randomUUID()});
const duelUI = {state:newDuel(),busy:false,generation:0,message:'',detailPreview:false,bindings:{...duelDefaults},shortcutStatus:null,shortcutQueue:Promise.resolve(),hoverTimer:null,closeTimer:null,previewAnchor:null};
const duelState = () => duelUI.state;
const blankDuelHand = count => Number.isSafeInteger(count)&&count>=1&&count<=(duelState().deck?.deck?.main?.length||0) ? Array(count).fill(null) : [];
const duelName = code => app.cache.get(code)?.name || duelState().plan?.catalog?.[code]?.name || `卡号 ${code}`;
function duelTell(message) {duelUI.message=message;$('#duel-message').textContent=message;}
function invalidateDuel(stage) {
  const s=duelState();
  ++duelUI.generation;
  s.result=s.plan=s.routes=s.graph=s.position=null;s.ended=false;s.reached=Math.min(s.reached,stage);
  s.session=crypto.randomUUID();s.enabled=false;
  void syncDuelShortcuts();
}
async function duelWork(fn) {
  if(duelUI.busy)return;
  duelUI.busy=true;renderDuel();
  try {await fn();}
  catch(error){duelTell(error.message);}
  finally {duelUI.busy=false;renderDuel();}
}
async function enterDuelModule() {
  await duelWork(async()=>{
    const s=duelState();
    s.decks=await api('/api/decks');
    if(window.trainerDesktop?.tutorialSettings) {
      const settings=await window.trainerDesktop.tutorialSettings();
      duelUI.bindings=settings.bindings;
      if(settings.error)duelTell(settings.error);
    }
    if(s.deck)await refreshDuelDeck();
    if(s.result&&!s.ended) {
      let latest;
      try {latest=await api('/api/duel/match',{deck_id:s.deck.id,revision:s.deck.revision,hand_count:s.count,hand:s.hand});}
      catch(error) {invalidateDuel(3);s.stage=3;throw new Error('无法重新验证方案，请重试筛选：'+error.message);}
      if(JSON.stringify(latest)!==JSON.stringify(s.result)) {
        invalidateDuel(3);s.result=latest;duelReach(4);duelTell('方案或标签已更新，筛选结果已刷新，请重新选择方案。');
      }
    }
  });
}
async function leaveDuelModule() {
  duelState().enabled=false;
  closeDuelPreview();closeDeckPreview();closeReviewDetail();
  await syncDuelShortcuts();
}
async function refreshDuelDeck() {
  const s=duelState();
  try {
    const saved=await api(`/api/deck?id=${encodeURIComponent(s.deck.id)}`);
    if(s.deck.revision!==saved.revision) {
      s.deck=saved;s.marks.clear();s.hand=blankDuelHand(s.count);s.target=null;
      invalidateDuel(1);s.stage=1;s.deckPage='preview';
      duelTell('源卡组已修改，已刷新预览并清空起手与方案。请重新确认。');
      return false;
    } else s.deck=saved;
    return true;
  } catch(error) {
    s.deck=null;s.hand=blankDuelHand(s.count);s.marks.clear();s.target=null;
    invalidateDuel(1);s.stage=1;s.deckPage='list';
    throw new Error('无法读取所选卡组，请重新选择：'+error.message);
  }
}
function duelGo(stage) {
  const s=duelState();
  if(duelUI.busy||s.ended||stage>s.reached||stage<0)return;
  s.stage=stage;closeDuelPreview();closeReviewDetail();
  if(stage!==5)s.enabled=false;
  renderDuel();void syncDuelShortcuts();
}
function duelReach(stage) {const s=duelState();s.stage=stage;s.reached=Math.max(s.reached,stage);}
function duelButton(action,label,disabled=false,primary=false) {
  return `<button data-duel-action="${action}" ${disabled||duelUI.busy?'disabled':''} class="${primary?'primary':''}">${label}</button>`;
}
function duelReadCard(code,extra={}) {
  const report={id:'duel-catalog',catalog:Object.fromEntries(app.cache),events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  return reviewCard({code,name:duelName(code),identity_known:true,...extra},'catalog',{report,face:true,zone:false,position:false,catalogue:true});
}
function duelDeckPreview() {
  const s=duelState();
  return `<div class="duel-section-heading"><div><h2>${escape(s.deck.name)}</h2>${deckTagHtml(s.deck)}<p>查看主／额外／副卡组；悬停查看卡牌详情。标记仅作为本次起手快捷候选。</p></div>${duelButton('deck-list','← 返回卡组列表')}</div>`+
    zones.map(zone=>`<section class="duel-zone"><h3>${zoneNames[zone]} <small>${s.deck.deck[zone].length} 张</small></h3><div class="duel-card-grid">${s.deck.deck[zone].map((code,i)=>{
      const key=`${zone}:${i}`,marked=s.marks.has(key);
      return `<article class="duel-card ${marked?'is-marked':''}">${duelReadCard(code)}<button data-duel-mark="${key}" aria-pressed="${marked}" ${duelUI.busy?'disabled':''}>${marked?'✓ 已标记':'标记'}</button></article>`;
    }).join('')||'<p>暂无卡牌</p>'}</div></section>`).join('');
}
function duelCandidate(code) {
  const s=duelState(),stock=DuelModel.counts(s.deck.deck.main).get(code),used=DuelModel.counts(s.hand).get(code)||0;
  const disabled=!DuelModel.place(s.deck.deck,s.count,s.hand,code,s.target??s.hand.indexOf(null));
  return `<article class="duel-candidate">${duelReadCard(code)}<strong>${escape(duelName(code))}</strong><small>投入 ${stock} · 已选 ${used} · 剩余 ${stock-used}</small><button data-duel-add="${code}" ${disabled||duelUI.busy?'disabled':''}>${s.target===null?'加入起手':'替换槽位 '+(s.target+1)}</button></article>`;
}
function duelHandPage() {
  const s=duelState(),main=s.deck.deck.main,quick=[...new Set([...s.marks].filter(k=>k.startsWith('main:')).map(k=>main[Number(k.split(':')[1])]).filter(Boolean))];
  return `<div class="duel-section-heading"><div><h2>准备起手 <small>${s.hand.filter(Boolean).length} / ${s.count}</small></h2><p>${escape(s.deck.name)} · 先手 · 点击卡图或加入按钮选牌，点击槽位选择替换位置。</p></div>${s.target!==null?duelButton('cancel-replace','取消替换'):''}</div>
    <div class="duel-hand">${s.hand.map((code,i)=>`<article class="duel-slot ${s.target===i?'selected':''}"><small>起手 ${i+1}</small>${code?duelReadCard(code).replace('<button ',`<button data-duel-slot="${i}" aria-pressed="${s.target===i}" `):`<button data-duel-slot="${i}" aria-pressed="${s.target===i}"><span class="duel-slot-plus">＋</span><strong>等待选牌</strong></button>`}${code?`<strong>${escape(duelName(code))}</strong><button data-duel-remove="${i}" ${duelUI.busy?'disabled':''}>移除</button>`:''}</article>`).join('')}</div>
    <div class="duel-candidates"><section><h3>全部主卡组 <small>${main.length} 张</small></h3><div class="duel-candidate-grid">${[...new Set(main)].map(duelCandidate).join('')}</div></section><aside><h3>已标记的主卡组卡牌</h3><p>与左侧共用剩余数量</p><div class="duel-candidate-grid">${quick.map(duelCandidate).join('')||'<p>尚未标记主卡组卡牌，可返回卡组预览标记。</p>'}</div></aside></div>`;
}
function duelOpeningText(plan) {
  return (plan.requirements?.opening||[]).map(c=>`${c.name||c.constraint||duelName(c.code)} ×${c.count}`).join(' + ')||'无额外指定起手要求（已记录空条件）';
}
function duelPlanSummary(plan) {
  const final=plan.requirements?.final;
  return `<h3>${escape(plan.name)}</h3><p>${plan.duel_tags.map(t=>`<span class="deck-tag-chip">${escape(t.name)}</span>`).join('')||'未填写 Tag'}</p><dl><dt>主线步骤</dt><dd>${buildPlanTutorial(plan).steps.length} 步</dd><dt>起手条件</dt><dd>${escape(duelOpeningText(plan))}</dd><dt>基本场 / 终场</dt><dd>${final?.cards?.length?final.cards.map(c=>escape(c.name||plan.catalog?.[c.code]?.name||duelName(c.code))).join('、'):'未填写'}</dd><dt>可用妥协分支</dt><dd>${plan.branches.map(b=>escape(b.name)).join('、')||'无'}</dd><dt>备注</dt><dd>${escape(plan.expansion?.notes||'未填写')}</dd></dl>${plan.requirements?.random?.length?'<p class="duel-warning">含途中随机依赖，教程保留原记录提示。</p>':''}`;
}
function duelMatchesPage() {
  const result=duelState().result;
  if(!result)return '<p>请完整准备起手后开始筛选。</p>';
  return `<div class="duel-section-heading"><div><h2>先攻展开</h2><p>相同 Tag ID 至少一个 → 主／额外资源 → 实际起手条件</p></div><label><input id="duel-detailed-preview" type="checkbox" ${duelUI.detailPreview?'checked':''}>详细悬浮预览（一图流）</label></div><p>关联 ${result.counts.tags} 个方案 · 可选 ${result.matches.length} 个 · 资源不足 ${result.counts.resources} · 起手不符 ${result.counts.opening} · 条件待补全 ${result.counts.incomplete} · 后手不适用 ${result.counts.turn_order||0}</p>
    <div class="duel-plan-grid">${result.matches.map(plan=>`<button class="duel-plan" data-duel-plan="${escape(plan.id)}"><span class="eyebrow">先攻展开 · ${plan.branches.length} 条妥协分支</span><strong>${escape(plan.name)}</strong><span>${plan.duel_tags.map(t=>escape(t.name)).join(' · ')||'未填写 Tag'}</span><small>${escape(duelOpeningText(plan))}</small><span class="duel-plan-enter">进入教程 →</span></button>`).join('')||`<div class="duel-empty"><h3>${escape(result.reason)}</h3><p>可以返回调整卡组、Tag 或实际起手。</p>${duelButton('edit-deck','返回卡组选择')}${duelButton('edit-hand','返回准备起手')}</div>`}</div>
    ${result.excluded.length?`<details class="duel-exclusions"><summary>查看未匹配原因 (${result.excluded.length})</summary>${result.excluded.map(p=>`<p><strong>${escape(p.name||'未命名方案')}</strong>：${escape(p.reason)}</p>`).join('')}</details>`:''}`;
}
function duelGraphHtml() {
  const s=duelState(),g=s.graph,w=Math.max(...g.nodes.map(n=>n.column))*196+224,h=s.routes.length*134+28;
  const point=key=>{const n=g.nodes.find(n=>n.key===key);return {x:n.column*196+18,y:n.row*134+24};};
  return `<div id="duel-graph-scroll" class="duel-graph-scroll"><div class="duel-graph"><svg width="${w}" height="${h}" aria-hidden="true"><defs><marker id="duel-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10" fill="var(--accent)"/></marker></defs>${g.edges.map(e=>{const a=point(e.from),b=point(e.to);return `<path data-duel-edge="${escape(e.to)}" d="M${a.x+164} ${a.y+38}H${a.x+180}V${b.y+38}H${b.x-4}" fill="none" stroke="var(--accent)" stroke-width="1.5" ${e.branch?'stroke-dasharray="5 4"':''} marker-end="url(#duel-arrow)"/>`;}).join('')}</svg>${g.nodes.map(n=>`<button data-duel-node="${escape(n.key)}" class="duel-node"><small>${escape(n.label)} · ${n.number?`Step ${n.number}`:n.id==='initial'?'起手':'终场'}</small><strong>${escape(n.title||n.actions?.[0]?.stages?.[0]?.label||'查看已记录操作')}</strong><span class="duel-current-dot" aria-hidden="true"></span></button>`).join('')}</div></div>`;
}
function duelNodeDetail(node) {
  const s=duelState(),route=s.routes.find(r=>r.id===node.route),plan=node.route==='main'?s.plan:s.plan.branches.find(b=>b.id===node.route).report;
  if(node.id==='initial')return `<h3>起手 / 首次操作前</h3><p>${escape(duelOpeningText(s.plan))}</p>`;
  if(node.id==='final')return `<h3>${escape(route.label)} · 终场</h3><p>${escape(route.model.finalNote||'终场说明未填写')}</p><div class="duel-final-cards">${route.model.finalCards.map(c=>`<figure><img src="${escape(c.src)}" alt=""><figcaption>${escape(c.name)}${c.notes.map(n=>`<p>${escape(n.text)}</p>`).join('')}</figcaption></figure>`).join('')||'<p>终场标记未填写</p>'}</div>`;
  const step=route.model.steps.find(n=>n.id===node.id),notes=plan.annotations?.nodes?.[node.id];
  return `<h3>${escape(route.label)} · Step ${node.number}</h3><p class="preserve-lines">${escape(notes?.name||'')} ${escape(notes?.notes||'')}</p>`+(step?.actions||[]).map(a=>`<section class="duel-action-detail">${a.stages.map(stage=>`<div><strong>${escape(stage.label)}</strong><p>${escape(stage.text||stage.hint||'')}</p><div class="duel-action-cards">${stage.cards.map(c=>`<figure><img src="${escape(c.src)}" alt="${escape(c.name)}"><figcaption>${escape(c.name)}${c.location?` · ${escape(c.location)}`:''}</figcaption></figure>`).join('')}</div></div>`).join('')}<p>${a.notes.map(n=>escape(n.text)).join(' · ')}</p><p class="preserve-lines">${escape(plan.annotations?.effects?.[a.id]||'')}</p></section>`).join('');
}
function duelTutorialPage() {
  const s=duelState();
  return `<div class="duel-section-heading"><div><h2>展开教程 · ${escape(s.plan.name)}</h2><p>高亮只表示教程位置，按实际操作手动推进。到达终场后仍需手动结束。</p></div><div class="duel-actions">${duelButton('toggle-shortcuts',s.enabled?'暂停后台快捷键':'启用后台快捷键',!window.trainerDesktop?.tutorialUpdate)}${duelButton('shortcuts','快捷键设置',!window.trainerDesktop?.tutorialSettings)}</div></div><p id="duel-shortcut-status" role="status"></p>${duelGraphHtml()}<div id="duel-route-choice" class="duel-route-choice"></div><article id="duel-current-detail" class="duel-current-detail"></article>${s.plan.duel_excluded_branches.length?`<details><summary>本次未纳入的分支</summary>${s.plan.duel_excluded_branches.map(b=>`<p>${escape(b.name)}：${escape(b.reason)}</p>`).join('')}</details>`:''}`;
}
function renderDuel() {
  const s=duelState(),mainStage=Math.min(s.stage,3),stages=['模式选择','卡组选择','决定先/后攻','卡组展开'];
  $('#duel-new').disabled=duelUI.busy;
  $('#duel-steps').innerHTML=stages.map((name,i)=>`<button data-duel-stage="${i}" ${i>s.reached||duelUI.busy?'disabled':''} ${i===mainStage?'aria-current="step"':''}><span>${i<mainStage?'✓':i+1}</span>${name}<small>${i<mainStage?'已完成':i===mainStage?'当前阶段':'待进行'}</small></button>`).join('');
  $('#duel-substeps').hidden=s.stage<3;
  $('#duel-substeps').innerHTML=['准备起手','展开方案选择','展开教程'].map((name,i)=>`<button data-duel-stage="${i+3}" ${i+3>s.reached||duelUI.busy?'disabled':''} ${s.stage===i+3?'aria-current="step"':''}>${i+1}. ${name}${s.stage>i+3?' ✓':''}</button>`).join('');
  let body='',footer=duelButton('back','← 返回上一步',s.stage===0);
  if(s.stage===0) {
    body=`<h2>选择对局模式</h2><div class="duel-mode-grid"><button data-duel-action="bo1" class="duel-mode" aria-pressed="${s.mode==='BO1'}"><span class="eyebrow">单局模式</span><strong>BO1</strong><p>选择卡组、录入真实起手，跟随已有方案展开。</p><span>开始 →</span></button><button class="duel-mode" disabled><span class="eyebrow">三局两胜</span><strong>BO3</strong><p>包含多局与换备流程。</p><span>待开发</span></button></div>`;
    footer='<span>本期支持 BO1 先攻展开辅助</span>';
  } else if(s.stage===1) {
    if(s.deckPage==='method')body=`<h2>选择卡组方式</h2><div class="duel-mode-grid">${duelButton('deck-list','手动选择 · 从已保存卡组中选择',false,true)}<button disabled>自动识别卡组 · 待开发</button></div>`;
    else if(s.deckPage==='preview'&&s.deck){body=duelDeckPreview();footer+=duelButton('start-duel','开始决斗 →',false,true);}
    else body=`<div class="duel-section-heading"><h2>选择已有卡组</h2>${duelButton('refresh-decks','刷新列表')}</div><div class="duel-plan-grid">${s.decks.map(d=>`<button class="duel-deck-box" data-duel-deck="${escape(d.id)}"><span class="selection-deck-icon" aria-hidden="true">◇</span><strong>${escape(d.name)}</strong>${deckTagHtml(d)}<span>预览卡组 →</span></button>`).join('')||'<p>暂无已保存卡组，请先在卡组编辑中保存。</p>'}</div>`;
  } else if(s.stage===2) {
    body=`<h2>决定先 / 后攻</h2><div class="duel-actions">${duelButton('manual-order','手动选择',false,s.manualOrder)}<button disabled>自动选择 · 待开发</button></div>`;
    if(s.manualOrder)body+=`<div class="duel-mode-grid"><button class="duel-mode" data-duel-action="first" aria-pressed="${s.first}"><span>⚑ 手动选择</span><strong>先手</strong><p>先攻展开 · ${s.first?'已选择':'点击选择'}</p></button><button class="duel-mode" disabled><span>↩ 后攻突破</span><strong>后手</strong><p>待开发</p></button></div><label class="duel-count-label" for="duel-count">先攻起手张数 <input id="duel-count" type="number" min="1" max="${s.deck.deck.main.length}" step="1" value="${Number.isFinite(s.count)?s.count:''}"></label><p id="duel-count-error" role="status"></p><p>默认 5 张，可按非正式对局需要调整，最多 ${s.deck.deck.main.length} 张。</p>`;
    footer+=duelButton('prepare','准备起手 →',!s.first||!Number.isInteger(s.count)||s.count<1||s.count>s.deck.deck.main.length,true);
  } else if(s.stage===3) {
    body=duelHandPage();const error=DuelModel.handError(s.deck.deck,s.count,s.hand);
    footer+=`<span role="status">${escape(error||'起手录入完成')}</span>`+duelButton('match','展开开始 →',!!error,true);
  } else if(s.stage===4) {
    body=duelMatchesPage();footer+=duelButton('rematch','重新筛选');
  } else if(s.stage===5) {
    body=duelTutorialPage();footer+=`<div class="duel-actions">${duelButton('back-step','← 后退')}${duelButton('forward-step','前进 →')}${duelButton('end','展开结束',false,true)}</div>`;
  } else {
    body=`<div class="duel-complete"><span>✓</span><h2>展开已结束</h2><p>${escape(s.deck.name)} · ${escape(s.plan?.name||'')} · BO1 先手</p><p>本次教程已结束，后台快捷键已释放。本期流程至此完成。</p><p>对局胜负由用户自行判定。</p></div>`;
    footer=duelButton('new','新开一场决斗',false,true);
  }
  $('#duel-body').innerHTML=body;$('#duel-footer').innerHTML=footer;duelTell(duelUI.message);
  if(duelUI.busy)$('#duel-body').querySelectorAll('button,input').forEach(el=>el.disabled=true);
  pruneReviewCards();
  if(s.stage===5)paintDuelPosition(false);
}
function paintDuelPosition(scroll=true) {
  const s=duelState();if(s.stage!==5||!s.position)return;
  // Set geometry through CSSOM, as the app's CSP blocks HTML style attributes.
  const canvas=$('#duel-graph-scroll .duel-graph');
  canvas.style.width=`${Math.max(...s.graph.nodes.map(n=>n.column))*196+224}px`;
  canvas.style.height=`${s.routes.length*134+28}px`;
  $('#duel-body').querySelectorAll('[data-duel-node]').forEach(button=>{
    const node=s.graph.nodes.find(n=>n.key===button.dataset.duelNode);
    button.style.left=`${node.column*196+18}px`;button.style.top=`${node.row*134+24}px`;
    const active=button.dataset.duelNode===s.position.key;button.classList.toggle('current',active);button.setAttribute('aria-current',active?'step':'false');
    if(active&&scroll)button.scrollIntoView({block:'nearest',inline:'nearest'});
  });
  const outgoing=s.graph.edges.filter(e=>e.from===s.position.key),choice=outgoing[s.position.choice||0];
  $('#duel-route-choice').innerHTML=outgoing.length?`<strong>${outgoing.length>1?'分叉处 · → 将进入：':'下一步：'}${escape(choice.label)}</strong>${outgoing.length>1?`<p>↑ / ↓ 选择路线，→ 进入所选路线</p><div class="duel-actions">${outgoing.map((edge,i)=>`<button data-duel-choice="${i}" aria-pressed="${i===(s.position.choice||0)}">${escape(edge.label)}</button>`).join('')}</div>`:''}`:'已到达此路线终场，可以后退查看或点击“展开结束”。';
  $('#duel-current-detail').innerHTML=duelNodeDetail(s.graph.nodes.find(n=>n.key===s.position.key));
  paintDuelShortcutStatus();
}
function duelNavigate(action) {
  const s=duelState();if(s.stage!==5||s.ended||duelUI.busy||$('#duel-shortcut-dialog').open||moduleUI.current!=='duel')return;
  if(action==='end'){void endDuel();return;}
  s.position=DuelModel.navigate(s.graph,s.position,action);paintDuelPosition();
}
async function endDuel() {
  const s=duelState();s.enabled=false;s.ended=true;s.stage=6;s.reached=6;s.session=crypto.randomUUID();
  closeDuelPreview();closeReviewDetail();await syncDuelShortcuts();renderDuel();
}
async function chooseDuelDeck(id) {
  const s=duelState(),saved=await api(`/api/deck?id=${encodeURIComponent(id)}`);
  await Promise.all([...new Set(zones.flatMap(z=>saved.deck[z]))].map(code=>card(code).catch(()=>{})));
  if(!s.deck||s.deck.id!==saved.id||s.deck.revision!==saved.revision){
    s.deck=saved;s.count=5;s.hand=Array(5).fill(null);s.marks.clear();s.first=false;s.target=null;invalidateDuel(1);
  }else s.deck=saved;
  s.deckPage='preview';closeDeckPreview();duelTell('');
}
async function matchDuel(force=false) {
  const s=duelState(),error=DuelModel.handError(s.deck.deck,s.count,s.hand);
  if(error)throw new Error(error);
  if(s.result&&!force){duelReach(4);return;}
  const generation=++duelUI.generation;
  const result=await api('/api/duel/match',{deck_id:s.deck.id,revision:s.deck.revision,hand_count:s.count,hand:s.hand});
  if(generation!==duelUI.generation)return;
  s.result=result;s.plan=s.routes=s.graph=s.position=null;s.ended=false;s.reached=4;duelReach(4);duelTell('');
}
function chooseDuelPlan(id) {
  const s=duelState(),plan=s.result.matches.find(p=>p.id===id);if(!plan)return;
  if(s.plan!==plan||s.ended) {
    s.plan=plan;s.routes=buildBranchedTutorial(plan,true).routes;s.graph=DuelModel.graph(s.routes);
    s.position={key:s.graph.start,choice:0};s.ended=false;s.session=crypto.randomUUID();
  }
  closeDuelPreview();duelReach(5);renderDuel();void syncDuelShortcuts();
}
function closeDuelPreview() {clearTimeout(duelUI.hoverTimer);clearTimeout(duelUI.closeTimer);duelUI.previewAnchor=null;$('#duel-preview').hidden=true;}
function showDuelPreview(anchor) {
  clearTimeout(duelUI.hoverTimer);clearTimeout(duelUI.closeTimer);duelUI.previewAnchor=anchor;
  duelUI.hoverTimer=setTimeout(()=>{
    if(!anchor.isConnected)return;
    const s=duelState(),plan=s.result?.matches.find(p=>p.id===anchor.dataset.duelPlan),node=s.graph?.nodes.find(n=>n.key===anchor.dataset.duelNode);
    let html=plan?duelPlanSummary(plan):node?duelNodeDetail(node):'';
    if(plan&&duelUI.detailPreview){const model=buildPlanTutorial(plan,true);html+=renderPlanTutorialSvg(model);}
    if(!html)return;
    $('#duel-preview-content').innerHTML=html;$('#duel-preview').hidden=false;
    const box=anchor.getBoundingClientRect(),p=$('#duel-preview');
    p.style.left=`${Math.max(12,Math.min(box.left,window.innerWidth-p.offsetWidth-12))}px`;
    p.style.top=`${Math.max(70,Math.min(box.bottom+8,window.innerHeight-p.offsetHeight-12))}px`;
  },300);
}
function paintDuelShortcutStatus() {
  const el=$('#duel-shortcut-status');if(!el)return;
  const s=duelState(),status=duelUI.shortcutStatus;
  el.textContent=!window.trainerDesktop?.tutorialUpdate?'当前网页环境仅支持软件内按键；后台快捷键请使用桌面版。':status?.error||(!s.enabled?'后台快捷键已暂停；软件内方向键仍可使用。':status?.registered?.length?'后台快捷键已启用：'+Object.entries(duelUI.bindings).filter(([,v])=>v).map(([k,v])=>`${duelLabels[k]} ${v}`).join(' · '):'后台快捷键已启用；切到其他软件时注册，回到本软件时使用窗口内按键。');
}
function syncDuelShortcuts() {
  if(!window.trainerDesktop?.tutorialUpdate)return Promise.resolve();
  const s=duelState(),payload={active:s.stage===5&&!s.ended&&moduleUI.current==='duel',enabled:s.enabled,suspended:$('#duel-shortcut-dialog').open,session:s.session,bindings:{...duelUI.bindings}};
  duelUI.shortcutQueue=duelUI.shortcutQueue.catch(()=>{}).then(()=>window.trainerDesktop.tutorialUpdate(payload)).then(status=>{
    if(status.session===duelState().session){duelUI.shortcutStatus=status;paintDuelShortcutStatus();}
  }).catch(error=>{duelUI.shortcutStatus={error:error.message};paintDuelShortcutStatus();});
  return duelUI.shortcutQueue;
}
function duelAccelerator(event) {
  const aliases={ArrowLeft:'LEFT',ArrowRight:'RIGHT',ArrowUp:'UP',ArrowDown:'DOWN',' ':'SPACE'};
  if(['Control','Alt','Shift','Meta'].includes(event.key))return '';
  return [...(event.ctrlKey?['CONTROL']:[]),...(event.altKey?['ALT']:[]),...(event.shiftKey?['SHIFT']:[]),...(event.metaKey?['SUPER']:[]),aliases[event.key]||event.key.toUpperCase()].join('+');
}
async function openDuelShortcuts() {
  const dialog=$('#duel-shortcut-dialog');
  $('#duel-shortcut-fields').innerHTML=Object.entries(duelLabels).map(([key,label])=>`<label>${label}<input data-duel-binding="${key}" value="${escape(duelUI.bindings[key])}" aria-label="${label}快捷键" maxlength="80"><button type="button" data-duel-clear-binding="${key}">清除</button></label>`).join('');
  $('#duel-shortcut-error').textContent='';dialog.showModal();await syncDuelShortcuts();
}
async function closeDuelShortcuts() {$('#duel-shortcut-dialog').close();await syncDuelShortcuts();}

$('#duel').addEventListener('click',run(async event=>{
  if(duelUI.busy)return;const s=duelState(),button=event.target.closest('button');if(!button||button.disabled)return;
  if(button.dataset.duelStage!==undefined){duelGo(Number(button.dataset.duelStage));return;}
  if(button.dataset.duelDeck){await duelWork(()=>chooseDuelDeck(button.dataset.duelDeck));return;}
  if(button.dataset.duelMark){const key=button.dataset.duelMark;s.marks.has(key)?s.marks.delete(key):s.marks.add(key);renderDuel();return;}
  if(button.dataset.duelSlot!==undefined){s.target=Number(button.dataset.duelSlot);renderDuel();return;}
  if(button.dataset.duelRemove!==undefined){s.hand[Number(button.dataset.duelRemove)]=null;s.target=null;invalidateDuel(3);renderDuel();return;}
  const candidate=button.closest('.duel-candidate');
  if(button.dataset.duelAdd||candidate&&button.dataset.reviewCard) {
    const code=Number(button.dataset.duelAdd||candidate.querySelector('[data-duel-add]').dataset.duelAdd);
    const hand=DuelModel.place(s.deck.deck,s.count,s.hand,code,s.target??s.hand.indexOf(null));
    if(hand&&JSON.stringify(hand)!==JSON.stringify(s.hand)){s.hand=hand;s.target=null;invalidateDuel(3);closeReviewDetail();renderDuel();}
    return;
  }
  if(button.dataset.duelPlan){chooseDuelPlan(button.dataset.duelPlan);return;}
  if(button.dataset.duelNode){s.position={key:button.dataset.duelNode,choice:0};paintDuelPosition(false);return;}
  if(button.dataset.duelChoice!==undefined){s.position.choice=Number(button.dataset.duelChoice);paintDuelPosition(false);return;}
  const action=button.dataset.duelAction;if(!action)return;
  if(action==='back'){duelGo(s.stage-1);return;}
  if(action==='bo1'){s.mode='BO1';duelReach(1);renderDuel();return;}
  if(action==='deck-list'){await duelWork(async()=>{s.decks=await api('/api/decks');s.deckPage='list';});return;}
  if(action==='refresh-decks'){await duelWork(async()=>{s.decks=await api('/api/decks');});return;}
  if(action==='start-duel'){await duelWork(async()=>{if(await refreshDuelDeck())duelReach(2);});return;}
  if(action==='first'){s.first=true;renderDuel();return;}
  if(action==='manual-order'){s.manualOrder=true;renderDuel();return;}
  if(action==='prepare'){if(s.first&&Number.isInteger(s.count)&&s.count>=1&&s.count<=s.deck.deck.main.length)duelReach(3);renderDuel();return;}
  if(action==='cancel-replace'){s.target=null;renderDuel();return;}
  if(action==='match'||action==='rematch'){await duelWork(()=>matchDuel(action==='rematch'));return;}
  if(action==='edit-deck'){s.deckPage='preview';duelGo(1);return;}
  if(action==='edit-hand'){duelGo(3);return;}
  if(action==='back-step'||action==='forward-step'){duelNavigate(action==='back-step'?'back':'forward');return;}
  if(action==='end'){await endDuel();return;}
  if(action==='toggle-shortcuts'){s.enabled=!s.enabled;await syncDuelShortcuts();renderDuel();return;}
  if(action==='shortcuts'){await openDuelShortcuts();return;}
  if(action==='new')await startNewDuel();
}));
async function startNewDuel() {
  duelState().enabled=false;duelState().stage=0;await syncDuelShortcuts();++duelUI.generation;
  duelUI.state=newDuel();duelUI.message='';duelUI.detailPreview=false;closeDuelPreview();closeReviewDetail();renderDuel();
}
$('#duel-new').onclick=run(startNewDuel);
$('#duel').addEventListener('input',event=>{
  if(event.target.id!=='duel-count')return;
  const s=duelState(),count=event.target.value===''?NaN:Number(event.target.value);
  if(count===s.count)return;
  s.count=count;s.target=null;invalidateDuel(2);
  const valid=Number.isInteger(count)&&count>=1&&count<=s.deck.deck.main.length;
  s.hand=valid?Array(count).fill(null):[];
  $('#duel-count-error').textContent=valid?'':'请输入不超过主卡组总张数的正整数';
  $('#duel-footer [data-duel-action="prepare"]').disabled=!s.first||!valid;
});
$('#duel').addEventListener('change',event=>{if(event.target.id==='duel-detailed-preview'){duelUI.detailPreview=event.target.checked;closeDuelPreview();}});
$('#duel').addEventListener('pointerover',run(async event=>{
  const deck=event.target.closest('[data-duel-deck]');if(deck){await showDeckPreview(deck);return;}
  const anchor=event.target.closest('[data-duel-plan],[data-duel-node]');if(anchor&&!anchor.contains(event.relatedTarget))showDuelPreview(anchor);
}));
$('#duel').addEventListener('pointerout',event=>{
  if(!deckManager.anchor?.contains(event.relatedTarget)&&!$('#deck-preview').contains(event.relatedTarget))delayCloseDeckPreview();
  if(duelUI.previewAnchor?.contains(event.relatedTarget)||$('#duel-preview').contains(event.relatedTarget))return;
  clearTimeout(duelUI.hoverTimer);duelUI.closeTimer=setTimeout(closeDuelPreview,220);
});
$('#duel-preview').onpointerenter=()=>clearTimeout(duelUI.closeTimer);
$('#duel-preview').onpointerleave=()=>{duelUI.closeTimer=setTimeout(closeDuelPreview,220);};
$('#duel-preview-close').onclick=closeDuelPreview;
window.addEventListener('resize',closeDuelPreview);
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){closeDuelPreview();return;}
  if(event.defaultPrevented||event.repeat||event.isComposing||event.target.closest('input,textarea,select,[contenteditable=true],[role=dialog]')||document.querySelector('dialog[open]'))return;
  const bare=!event.ctrlKey&&!event.altKey&&!event.shiftKey&&!event.metaKey;
  const action=(bare?{ArrowLeft:'back',ArrowRight:'forward',ArrowUp:'up',ArrowDown:'down'}[event.key]:null)||Object.entries(duelUI.bindings).find(([,key])=>key&&key.toUpperCase()===duelAccelerator(event))?.[0];
  if(action&&moduleUI.current==='duel'&&duelState().stage===5){event.preventDefault();duelNavigate(action);}
});
$('#duel-shortcut-dialog').addEventListener('keydown',event=>{
  if(!event.target.matches('[data-duel-binding]')||event.key==='Tab'||event.key==='Escape')return;
  if(event.key==='Backspace'||event.key==='Delete'){event.preventDefault();event.target.value='';return;}
  const value=duelAccelerator(event);if(value){event.preventDefault();event.target.value=value;}
});
$('#duel-shortcut-dialog').addEventListener('click',event=>{const key=event.target.dataset.duelClearBinding;if(key)$('#duel-shortcut-fields').querySelector(`[data-duel-binding="${key}"]`).value='';});
$('#duel-shortcut-cancel').onclick=run(closeDuelShortcuts);
$('#duel-shortcut-dialog').oncancel=event=>{event.preventDefault();void closeDuelShortcuts();};
$('#duel-shortcut-form').onsubmit=async event=>{
  event.preventDefault();const button=$('#duel-shortcut-save');button.disabled=true;
  try {
    const bindings=Object.fromEntries([...$('#duel-shortcut-fields').querySelectorAll('input')].map(i=>[i.dataset.duelBinding,i.value]));
    const saved=await window.trainerDesktop.tutorialSaveSettings(bindings);duelUI.bindings=saved.bindings;await closeDuelShortcuts();
  }catch(error){$('#duel-shortcut-error').textContent=error.message;}finally{button.disabled=false;}
};
window.trainerDesktop?.onTutorialAction(event=>{const s=duelState();if(event.session===s.session&&s.enabled)duelNavigate(event.action);});
window.trainerDesktop?.onTutorialStatus(status=>{if(status.session===duelState().session){duelUI.shortcutStatus=status;paintDuelShortcutStatus();}});
