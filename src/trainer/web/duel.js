'use strict';

const duelDefaults = TutorialBindings.defaults;
const duelLabels = TutorialBindings.labels;
const duelStages = Object.freeze({mode:0,function:1,deck:2,order:3,hand:4,plans:5,tutorial:6,complete:7});
const newDuel = () => ({stage:duelStages.mode,reached:duelStages.mode,mode:null,operationMode:null,functionPage:'choice',automatic:DuelAutomatic.create(),deck:null,deckPage:'list',decks:[],first:false,count:5,hand:Array(5).fill(null),
  marks:new Set(),target:null,result:null,plan:null,routes:null,graph:null,position:null,ended:false,enabled:false,planSort:'shortest',favoritesOnly:false,session:crypto.randomUUID()});
const duelUI = {state:newDuel(),busy:false,generation:0,message:'',detailPreview:false,handCount:5,bindings:{...duelDefaults},shortcutStatus:null,shortcutQueue:Promise.resolve(),hoverTimer:null,closeTimer:null,previewAnchor:null,previewRect:null,previewKind:null,previewId:null,previewSuppressed:null,handHoverSuppressed:null};
const duelState = () => duelUI.state;
const duelInputKey=s=>JSON.stringify([s.deck?.id,s.deck?.revision,s.hand]);
const duelEngineBound=s=>!!app.active&&s.modularSession===app.active.id&&s.modularInput===duelInputKey(s);
const duelRouteCache=new WeakMap();
function duelPlanRoutes(plan) {
  if(!duelRouteCache.has(plan))duelRouteCache.set(plan,buildBranchedTutorial(plan,true).routes);
  return duelRouteCache.get(plan);
}
const duelPlanStepCount=plan=>duelPlanRoutes(plan).find(route=>route.id==='main').model.steps.length;
function duelPlanBranches(plan) {
  const routes=duelPlanRoutes(plan),graph=DuelModel.graph(routes),reachable=new Set(graph.nodes.map(node=>node.route));
  return (plan.branches||[]).filter(branch=>branch.valid!==false&&reachable.has(branch.id));
}
function duelPlanCounts(plan) {
  const modular=plan.modular_source;
  return `<span class="duel-plan-counts"><small class="duel-plan-step-count">主线 ${duelPlanStepCount(plan)} 步</small><small class="duel-plan-branch-count">可用分支 ${duelPlanBranches(plan).length}</small><small>${modular?.edges?.length?`模块连接 ${modular.edges.length} · 使用时逐步校验`:'模块资料待补充'}</small></span>`;
}
const duelHandCount = () => duelUI.handCount;
const blankDuelHand = count => Number.isSafeInteger(count)&&count>=1&&count<=(duelState().deck?.deck?.main?.length||0) ? Array(count).fill(null) : [];
const duelName = code => app.cache.get(code)?.name || duelState().plan?.catalog?.[code]?.name || `卡号 ${code}`;
function duelTell(message) {duelUI.message=message;$('#duel-message').textContent=message;}
function invalidateDuel(stage) {
  const s=duelState();
  if(typeof dropDuelForecast==='function')dropDuelForecast(s);
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
    duelUI.handCount=(await api('/api/duel/settings')).hand_count;
    if(window.trainerDesktop?.tutorialSettings) {
      const settings=await window.trainerDesktop.tutorialSettings();
      duelUI.bindings=settings.bindings;
      if(settings.error)duelTell(settings.error);
    }
    if(s.deck&&s.operationMode!=='automatic')await refreshDuelDeck();
    if(s.result&&!s.ended) {
      let latest;
      try {latest=await api('/api/duel/match',{deck_id:s.deck.id,revision:s.deck.revision,hand_count:s.count,hand:s.hand});}
      catch(error) {invalidateDuel(duelStages.hand);s.stage=duelStages.hand;throw new Error('无法重新验证方案，请重试筛选：'+error.message);}
      if(JSON.stringify(latest)!==JSON.stringify(s.result)) {
        invalidateDuel(duelStages.hand);s.result=latest;duelReach(duelStages.plans);duelTell('方案或标签已更新，筛选结果已刷新，请重新选择方案。');
      }
    }
  });
}
async function leaveDuelModule() {
  if(typeof stopDuelOrderWatch==='function')stopDuelOrderWatch();
  if($('#duel-brain-field')?.contains($('#native-stage')))restoreModularField();
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
      invalidateDuel(duelStages.deck);s.stage=duelStages.deck;s.deckPage='preview';
      duelTell('源卡组已修改，已刷新预览并清空起手与方案。请重新确认。');
      return false;
    } else s.deck=saved;
    return true;
  } catch(error) {
    s.deck=null;s.hand=blankDuelHand(s.count);s.marks.clear();s.target=null;
    invalidateDuel(duelStages.deck);s.stage=duelStages.deck;s.deckPage='list';
    throw new Error('无法读取所选卡组，请重新选择：'+error.message);
  }
}
function duelGo(stage) {
  const s=duelState();
  if(duelUI.busy||s.ended||stage>s.reached||stage<duelStages.mode)return;
  if(s.operationMode==='automatic'&&stage>duelStages.hand)return;
  if(s.operationMode==='automatic'&&stage===duelStages.order&&!s.automatic.order?.frame?.monitor_id)return;
  if(s.operationMode==='automatic'&&stage===duelStages.hand&&!DuelOrder.confirmed(s.automatic.order))return;
  s.stage=stage;closeDuelPreview();closeReviewDetail();
  s.enabled=stage===duelStages.tutorial;
  renderDuel();void syncDuelShortcuts();
}
function duelReach(stage) {const s=duelState();s.stage=stage;s.reached=Math.max(s.reached,stage);}
function duelButton(action,label,disabled=false,primary=false) {
  return `<button type="button" ${['back-step','forward-step'].includes(action)?`aria-label="${action==='back-step'?'后退':'前进'}"`:''} data-duel-action="${action}" ${disabled||duelUI.busy?'disabled':''} class="${primary?'primary':''}">${label}</button>`;
}
function duelReadCard(code,extra={}) {
  const report={id:'duel-catalog',catalog:Object.fromEntries(app.cache),events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  return reviewCard({code,name:duelName(code),identity_known:true,...extra},'catalog',{report,face:true,zone:false,position:false,catalogue:true});
}
function duelDeckPreview(deck=duelState().deck,marks=duelState().marks) {
  return `<div class="duel-section-heading"><h2>${escape(deck.name)}</h2></div>`+
    zones.map(zone=>`<section class="duel-zone"><h3>${zoneNames[zone]} <small>${deck.deck[zone].length} 张</small></h3><div class="duel-card-grid">${deck.deck[zone].map((code,i)=>{
      const key=`${zone}:${i}`;
      return `<article class="duel-card ${marks.has(key)?'is-marked':''}" data-duel-mark-key="${key}">${duelReadCard(code,{duel_mark_key:key})}</article>`;
    }).join('')||'<p>暂无卡牌</p>'}</div></section>`).join('');
}
function duelPreviewMarks() {const s=duelState();return s.operationMode==='automatic'?s.automatic.marks:s.marks;}
function updateDuelMarkButton() {
  const key=reviewUI.selected?.duel_mark_key,s=duelState(),button=$('#toggle-duel-card-mark'),marks=duelPreviewMarks();
  const page=s.operationMode==='automatic'?s.automatic.page:s.deckPage;
  button.hidden=moduleUI.current!=='duel'||s.stage!==duelStages.deck||page!=='preview'||!key;
  button.disabled=duelUI.busy;button.textContent=marks.has(key)?'取消标记':'添加标记';
  button.setAttribute('aria-pressed',String(marks.has(key)));
}
function duelCandidate(code) {
  const s=duelState(),stock=DuelModel.counts(s.deck.deck.main).get(code),used=DuelModel.counts(s.hand).get(code)||0,remaining=stock-used;
  const marked=[...s.marks].some(k=>k.startsWith('main:')&&s.deck.deck.main[Number(k.split(':')[1])]===code);
  const disabled=!DuelModel.place(s.deck.deck,s.count,s.hand,code,s.target??s.hand.indexOf(null));
  return `<article class="duel-candidate ${marked?'is-marked':''} ${remaining===0?'is-exhausted':''}">${duelReadCard(code).replace('<button ',`<button data-duel-add="${code}" aria-disabled="${disabled||duelUI.busy}" `)}<span class="duel-stock" aria-label="剩余 ${remaining} 张">${remaining}</span></article>`;
}
function duelHandPage() {
  const s=duelState(),main=s.deck.deck.main;
  return `<section class="duel-hand-setup"><div class="duel-section-heading"><h2>准备起手 <small>${s.hand.filter(Boolean).length} / ${s.count}</small></h2></div>
    <div class="duel-hand">${s.hand.map((code,i)=>`<article class="duel-slot ${s.target===i?'selected':''}">${code?duelReadCard(code).replace('<button ',`<button data-duel-slot="${i}" aria-pressed="${s.target===i}" `):`<button data-duel-slot="${i}" aria-label="起手 ${i+1} 空槽位" aria-pressed="${s.target===i}"><span class="duel-slot-plus">＋</span></button>`}</article>`).join('')}</div>
    </section><section class="duel-candidates"><h3>主卡组 <small>${main.length} 张</small></h3><div class="duel-candidate-grid">${[...new Set(main)].sort(compareDeckCards).map(duelCandidate).join('')}</div></section>`;
}
function duelOpeningText(plan) {
  return (plan.requirements?.opening||[]).map(c=>`${c.name||c.constraint||duelName(c.code)} ×${c.count}`).join(' + ')||'无额外指定起手要求（已记录空条件）';
}
function duelRegion(c) {
  if(c.controller===1)return '对方'+duelRegion({...c,controller:0});
  if(c.location&128)return '素材';
  return ({1:'主卡组',2:'手牌区',4:'怪兽区',8:c.sequence===5?'场地区':'魔陷区',16:'墓地',32:'除外区',64:'额外卡组'})[c.location]||'位置未记录';
}
function duelSummaryCards(plan,kind,limit=Infinity) {
  const final=reviewNodes(plan).find(n=>n.kind==='final')||{id:'final',state:plan.final_state};
  const marks=plan.annotations?.final_marks||{};
  const marked=DuelModel.markedFinalCards(plan);
  const cards=kind==='opening'?plan.requirements?.opening||[]:marked;
  return cards.slice(0,limit).map(c=>{
    const node=kind==='opening'?'initial':final.id,random=kind==='final'&&reviewRandomDraw(c,final,plan),known=c.code&&!random;
    const label=random?'随机抽牌':c.name||c.constraint||plan.catalog?.[c.code]?.name||'任意手牌';
    return `<figure><img src="${known?`/pics/${Number(c.code)}.jpg`:'/review-back.svg'}" alt="${escape(label)}" loading="lazy"><figcaption>${escape(label)}</figcaption>${kind==='opening'?`<small>×${c.count||1}</small>`:`<small class="duel-region">${escape(duelRegion(c))}</small>`}</figure>`;
  }).join('');
}
function duelPlanSummary(plan,detailed=false) {
  return `<h3>${escape(plan.name)}</h3>${duelPlanCounts(plan)}${plan.expansion?.notes?`<p class="preserve-lines">${escape(plan.expansion.notes)}</p>`:''}<section><h4>起手</h4><div class="duel-summary-cards">${duelSummaryCards(plan,'opening')||'<span>无指定起手</span>'}</div></section><section><h4>终场</h4><div class="duel-summary-cards">${duelSummaryCards(plan,'final')||'<span>未记录终场卡牌</span>'}</div>${duelFinalNotes(plan,detailed)}</section>${detailed?duelBranchDetails(plan)+renderPlanTutorialSvg(buildPlanTutorial(plan,true)):''}`;
}
function duelFinalNotes(plan,detailed=false) {
  const final=reviewNodes(plan).find(node=>node.kind==='final'),edits=plan.annotations||{};
  const general=[...new Set([edits.nodes?.[final?.id||'final']?.notes,plan.requirements?.final?.notes].map(note=>String(note||'').trim()).filter(Boolean))];
  const cards=(final?.state?.cards||plan.final_state?.cards||[]).filter(card=>edits.final_marks?.[String(card.instance_id)]?.marked);
  const notes=cards.map(card=>{
    const id=String(card.instance_id),mark=edits.final_marks[id],note=String(edits.cards?.[id]||'').trim();
    const random=reviewRandomDraw(card,final||{id:'final',state:plan.final_state},plan);
    const parts=reviewEffectParts(plan.catalog?.[card.code]?.desc);
    const effects=Object.entries(mark.effects||{}).filter(([,value])=>value).map(([key,value])=>{
      const part=parts.find(part=>String(part.key)===key),label=part?part.label+'效果':'效果备注';
      return `<div class="duel-final-effect"><strong>${escape(label)}</strong>${detailed&&part&&!random?`<p class="preserve-lines">${escape(part.text)}</p>`:''}${value.note?.trim()?`<p class="duel-saved-note preserve-lines">${escape(value.note)}</p>`:''}</div>`;
    }).join('');
    if(!note&&!effects)return '';
    const name=random?'随机抽牌':card.name||plan.catalog?.[card.code]?.name||`卡号 ${card.code}`;
    return `<article><strong>${escape(name)} · ${escape(duelRegion(card))}</strong>${note?`<p class="duel-saved-note preserve-lines">${escape(note)}</p>`:''}${effects}</article>`;
  }).join('');
  if(!general.length&&!notes)return '';
  return `<section class="duel-final-notes"><h4>终场备注</h4>${general.map(note=>`<p class="duel-saved-note preserve-lines">${escape(note)}</p>`).join('')}${notes}</section>`;
}
function duelBranchDetails(plan) {
  const branches=duelPlanBranches(plan);if(!branches.length)return '';
  return `<section class="duel-branch-list"><h4>分支详情</h4>${branches.map(branch=>{
    const report=branch.report,source=branch.source||{},node=reviewNodes(plan).find(node=>node.id===source.node_id);
    const at=source.node_id==='initial'?'起手':node?.number!=null?`主线 Step ${node.number}`:'记录的分支起点';
    const named=card=>card.name||report.catalog?.[card.code]?.name||plan.catalog?.[card.code]?.name||`卡号 ${card.code}`;
    const hand=[...DuelModel.counts(branch.conditions?.hand||[])].map(([code,count])=>`${named({code})} ×${count}`).join('、');
    const facts=observedBranchFacts(branch).map(fact=>`<p class="preserve-lines"><strong>${fact.confirmed?'已确认干扰':'记录关联（待核对）'}</strong>：${escape((fact.source_cards||[]).map(named).join('、'))} → ${escape((fact.affected_cards||[]).map(named).join('、')||'影响待核对')}：${escape(fact.result||'')}${fact.note?`<br>${escape(fact.note)}`:''}</p>`).join('');
    const steps=duelPlanRoutes(plan).find(route=>route.id===branch.id).model.steps.length;
    return `<article class="duel-branch-detail" data-duel-branch-detail="${escape(branch.id)}"><h4>${escape(branch.name)} <small>${steps} 步</small></h4><p>${escape(at)} · ${escape(source.timing||'时点未记录')}${source.operation?`<br>${escape(source.operation)}`:''}</p><p>对手预设手牌：${escape(hand||'未配置')}</p>${branch.conditions?.note?`<p class="preserve-lines">${escape(branch.conditions.note)}</p>`:''}${facts||'<p>尚无已记录干扰。</p>'}<h4>分支终场</h4><div class="duel-summary-cards">${duelSummaryCards(report,'final')||'<span>未记录终场卡牌</span>'}</div>${duelFinalNotes(report,true)}</article>`;
  }).join('')}</section>`;
}
function duelMatchesPage() {
  const s=duelState(),result=s.result;if(!result)return '';
  // Score against the full matched set so a favorite filter never changes scores.
  const ranked=DuelModel.rankPlans(result.matches,s.planSort,duelPlanStepCount).filter(r=>!s.favoritesOnly||r.plan.favorite);
  return `<div class="duel-section-heading"><h2>方案选择</h2><div class="duel-actions">${duelButton('modular','生成临时方案')}${duelButton('rematch','刷新')}</div></div><div class="duel-plan-filters"><label>方案排序 <select id="duel-plan-sort">${[['shortest','步骤最少'],['largest','终场最大'],['balanced','平均值（均衡）']].map(([value,label])=>`<option value="${value}" ${s.planSort===value?'selected':''}>${label}</option>`).join('')}</select></label><button data-duel-action="favorites-only" aria-pressed="${s.favoritesOnly}">★ 只看收藏</button><small>${ranked.length} / ${result.matches.length} 个方案</small></div><p class="duel-sort-basis">终场只比较已标记卡牌数，再比较标记效果数。平均值为步骤得分与终场排名得分各占 50%，仅用于当前方案比较。</p><div class="duel-plan-grid">${ranked.map(({plan,cards,effects,average})=>`<article class="duel-plan-tile ${plan.favorite?'is-favorite':''}"><button class="duel-plan" data-duel-plan="${escape(plan.id)}"><span class="duel-plan-heading"><strong>${escape(plan.name)}</strong>${duelPlanCounts(plan)}</span><small>${cards?`标记终场 ${cards} 张 · 效果 ${effects} 项`:'未标记有效终场'}${s.planSort==='balanced'?` · 平均 ${average.toFixed(1)}`:''}</small>${plan.expansion?.notes?`<span class="duel-plan-note">${escape(plan.expansion.notes)}</span>`:''}<span class="duel-tile-cards">${duelSummaryCards(plan,'opening',3)}</span><span class="duel-tile-arrow" aria-hidden="true">↓</span><span class="duel-tile-cards">${duelSummaryCards(plan,'final',4)||'<small>未标记终场卡牌</small>'}</span></button>${planFavoriteButton(plan)}</article>`).join('')||`<div class="duel-empty"><h3>${escape(s.favoritesOnly?'当前匹配结果中没有收藏方案':result.reason||'暂无可用方案')}</h3>${s.favoritesOnly?duelButton('favorites-only','查看全部方案'):duelButton('edit-hand','调整起手')}</div>`}</div>`;
}
function duelNodeSource(node) {
  const s=duelState(),report=node.route==='main'?s.plan:s.plan.branches.find(b=>b.id===node.route)?.report;
  const nodes=reviewNodes(report);
  const recorded=nodes.find(n=>n.id===node.id)||nodes.find(n=>n.kind===node.id);
  return {report,node:recorded||{id:node.id,kind:node.id,action_ids:[],state:null}};
}
function duelNodeDetail(node,mode='detailed') {
  const source=duelNodeSource(node),edit=source.report.annotations?.nodes?.[source.node.id];
  return `<h3>${escape(node.label)} · ${escape(edit?.name||node.title||(node.id==='initial'?'起手':node.id==='final'?'终场':`Step ${node.number}`))}</h3>${edit?.notes?`<p class="preserve-lines">${escape(edit.notes)}</p>`:''}${renderRecordedStep(source.report,source.node,mode)}`;
}
function duelGraphHtml() {
  const s=duelState();
  return `<div id="duel-graph-scroll" class="duel-graph-scroll"><div class="duel-graph-surface"><div class="duel-graph"><svg aria-hidden="true"></svg>${s.graph.nodes.map(n=>`<article role="button" tabindex="0" data-duel-node="${escape(n.key)}" class="duel-node" aria-label="${escape(n.label)} ${n.id==='initial'?'起手':n.id==='final'?'终场':`Step ${n.number}`}"><small>${escape(n.label)} · ${n.id==='initial'?'起手':n.id==='final'?'终场':`Step ${n.number}`}</small><div class="duel-node-log">${duelNodeDetail(n,'compact')}</div><span class="duel-current-dot" aria-hidden="true"></span></article>`).join('')}</div></div></div>`;
}
function layoutDuelGraph() {
  const s=duelState(),viewport=$('#duel-graph-scroll'),canvas=viewport?.querySelector('.duel-graph');if(!canvas)return;
  const available=Math.max(160,viewport.clientHeight-28),columns=[];
  const maximumWidth=Math.max(480,Math.min(900,viewport.clientWidth-32));
  for(const n of s.graph.nodes) {
    const el=canvas.querySelector(`[data-duel-node="${CSS.escape(n.key)}"]`),actions=el.querySelectorAll('.duel-node-log > .log-action').length;
    el.style.width='316px';el.style.setProperty('--node-action-columns','1');
    // Give a tall step more horizontal space before scaling the whole diagram.
    for(let width=416;el.offsetHeight>available&&width<=maximumWidth;width+=100) {
      el.style.width=width+'px';
      if(actions>1&&width>=516)el.style.setProperty('--node-action-columns',String(Math.min(actions,2)));
    }
    columns[n.column]=Math.max(columns[n.column]||0,el.offsetWidth+36);
  }
  const rows=s.routes.map((_,row)=>Math.max(120,...s.graph.nodes.filter(n=>n.row===row).map(n=>canvas.querySelector(`[data-duel-node="${CSS.escape(n.key)}"]`).offsetHeight))+28);
  const scale=Math.min(1,(viewport.clientHeight-8)/Math.max(...rows));duelUI.graphScale=scale;
  const points=new Map();
  s.graph.nodes.forEach(n=>{
    const b=canvas.querySelector(`[data-duel-node="${CSS.escape(n.key)}"]`),x=columns.slice(0,n.column).reduce((a,b)=>a+b,14),y=rows.slice(0,n.row).reduce((a,b)=>a+b,12);
    b.style.left=x+'px';b.style.top=y+'px';points.set(n.key,{x,y:y+36,width:b.offsetWidth});
  });
  const width=columns.reduce((a,b)=>a+b,14),height=rows.reduce((a,b)=>a+b,12),svg=canvas.querySelector('svg');
  canvas.style.width=width+'px';canvas.style.height=height+'px';svg.setAttribute('width',width);svg.setAttribute('height',height);
  canvas.style.transform=`scale(${scale})`;
  canvas.parentElement.style.width=width*scale+'px';canvas.parentElement.style.height=height*scale+'px';
  svg.innerHTML=`<defs><marker id="duel-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10" fill="var(--accent)"/></marker></defs>`+s.graph.edges.map(e=>{const a=points.get(e.from),b=points.get(e.to);return `<path d="M${a.x+a.width} ${a.y}H${a.x+a.width+18}V${b.y}H${b.x-4}" fill="none" stroke="var(--accent)" stroke-width="1.5" ${e.branch?'stroke-dasharray="5 4"':''} marker-end="url(#duel-arrow)"/>`;}).join('');
  const separator=$('#duel-graph-resize');separator?.setAttribute('aria-valuenow',String(Math.round(viewport.offsetHeight)));
}
function resizeDuelGraph(height) {
  const viewport=$('#duel-graph-scroll');if(!viewport)return;
  duelUI.graphHeight=Math.max(200,Math.min(Math.max(1200,innerHeight*2),height));
  viewport.style.height=duelUI.graphHeight+'px';layoutDuelGraph();
  focusDuelPosition();
}
function mountDuelGraphResize() {
  const viewport=$('#duel-graph-scroll'),separator=$('#duel-graph-resize');
  viewport.style.height=(duelUI.graphHeight||Math.max(300,Math.round(innerHeight*.45)))+'px';
  separator.setAttribute('aria-valuemax',String(Math.max(1200,innerHeight*2)));
  let drag;
  separator.onpointerdown=event=>{
    if(event.button!==0)return;event.preventDefault();closeDuelPreview();closeReviewDetail();
    drag={id:event.pointerId,y:event.clientY,height:viewport.offsetHeight};separator.setPointerCapture(event.pointerId);
    document.body.classList.add('duel-resizing');
  };
  separator.onpointermove=event=>{if(drag)resizeDuelGraph(drag.height+event.clientY-drag.y);};
  const finish=()=>{drag=null;document.body.classList.remove('duel-resizing');};
  separator.onpointerup=event=>{if(drag)resizeDuelGraph(drag.height+event.clientY-drag.y);finish();};
  separator.onpointercancel=finish;separator.onlostpointercapture=finish;
  separator.ondblclick=()=>{duelUI.graphHeight=null;resizeDuelGraph(Math.max(300,Math.round(innerHeight*.45)));};
  separator.onkeydown=event=>{
    if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    event.preventDefault();event.stopPropagation();
    resizeDuelGraph(event.key==='Home'?200:event.key==='End'?Math.max(1200,innerHeight*2):viewport.offsetHeight+(event.key==='ArrowDown'?24:-24));
  };
}
function duelTutorialPage() {
  const s=duelState();
  return `<div class="duel-section-heading"><h2>${escape(s.plan.name)}</h2><div class="duel-actions">${duelButton('toggle-shortcuts',s.enabled?'暂停快捷键':'启用快捷键')}${duelButton('shortcuts','快捷键设置')}${duelButton('modular',s.plan?.temporary?'重新生成后续':'生成展开后续')}</div></div><p id="duel-shortcut-status" role="status"></p>${duelGraphHtml()}<div id="duel-graph-resize" class="duel-graph-resize" role="separator" tabindex="0" aria-label="调整教程图高度" aria-orientation="horizontal" aria-valuemin="200" aria-valuemax="1800" title="拖动调整教程图高度；双击恢复默认"><span></span></div><div id="duel-route-choice" class="duel-route-choice"></div><article id="duel-current-detail" class="duel-current-detail"></article><div id="duel-zone-content" class="review-zone-popover" role="dialog" aria-label="区域卡牌" hidden></div>`;
}
function renderDuel() {
  if($('#duel-brain-field')?.contains($('#native-stage')))restoreModularField();
  closeDuelPreview();
  const s=duelState(),mainStage=Math.min(s.stage,duelStages.hand),stages=['模式选择','功能选择','卡组选择','决定先/后攻','卡组展开'];
  $('#duel').dataset.stage=String(s.stage);
  $('#duel-steps').innerHTML=stages.map((name,i)=>`<button data-duel-stage="${i}" ${i>s.reached||duelUI.busy||s.operationMode==='automatic'&&(i===duelStages.hand&&!DuelOrder.confirmed(s.automatic.order)||i===duelStages.order&&!s.automatic.order?.frame?.monitor_id)?'disabled':''} ${i===mainStage?'aria-current="step"':''}><span>${i<mainStage?'✓':i+1}</span>${name}</button>`).join('');
  const automatic=s.operationMode==='automatic',deckPage=automatic?s.automatic.page:s.deckPage,hasDeck=automatic?!!s.automatic.deck&&s.automatic.fresh:!!s.deck;
  $('#duel-substeps').hidden=![duelStages.function,duelStages.deck,duelStages.hand,duelStages.plans,duelStages.tutorial].includes(s.stage)||automatic&&s.stage===duelStages.hand;
  $('#duel-substeps').setAttribute('aria-label',s.stage===duelStages.function?'功能选择流程':s.stage===duelStages.deck?'卡组选择流程':'卡组展开流程');
  if(s.stage===duelStages.function)$('#duel-substeps').innerHTML=['手动或自动','平台选择'].map((name,i)=>`<button data-duel-function-page="${i?'platform':'choice'}" ${duelUI.busy||i&&!automatic?'disabled':''} ${s.functionPage===(i?'platform':'choice')?'aria-current="step"':''}>${i+1}. ${name}</button>`).join('');
  else if(s.stage===duelStages.deck)$('#duel-substeps').innerHTML=[automatic?'卡组识别':'选择卡组','卡牌预览'].map((name,i)=>{
    const page=i?'preview':automatic?'recognition':'list';
    return `<button data-duel-deck-page="${page}" ${duelUI.busy||i&&!hasDeck?'disabled':''} ${deckPage===page?'aria-current="step"':''}>${i+1}. ${name}</button>`;
  }).join('');
  else $('#duel-substeps').innerHTML=['准备起手','方案选择','展开教程'].map((name,i)=>`<button data-duel-stage="${i+duelStages.hand}" ${i+duelStages.hand>s.reached||duelUI.busy?'disabled':''} ${s.stage===i+duelStages.hand?'aria-current="step"':''}>${i+1}. ${name}</button>`).join('');
  let body='',footer='';
  if(s.stage===duelStages.mode) {
    body=`<div class="duel-mode-grid"><button data-duel-action="bo1" class="duel-mode"><span class="duel-mode-symbol" aria-hidden="true">◇</span><strong>BO1</strong><span>单局模式</span></button><button class="duel-mode" disabled><span class="duel-mode-symbol" aria-hidden="true">◇◇</span><strong>BO3</strong><span>三局两胜</span><small>待开发</small></button></div>`;
  } else if(s.stage===duelStages.function) {
    body=s.functionPage==='platform'&&automatic?duelPlatformPage():`<div class="duel-mode-grid"><button data-duel-action="manual" class="duel-mode"><strong>手动选择</strong><span>自行选择卡组与起手</span></button><button data-duel-action="automatic" class="duel-mode"><strong>自动选择</strong><span>从游戏平台识别卡组</span></button></div>`;
  } else if(s.stage===duelStages.deck) {
    if(automatic){body=deckPage==='preview'&&hasDeck?duelAutomaticPreview():duelRecognitionPage();if(deckPage==='preview'&&hasDeck)footer=duelButton('start-duel','开始决斗',false,true);}
    else if(s.deckPage==='preview'&&s.deck){body=duelDeckPreview();footer=duelButton('start-duel','开始决斗',false,true);}
    else body=`<div class="duel-section-heading"><h2>选择卡组</h2>${duelButton('refresh-decks','刷新列表')}</div><div class="duel-deck-grid">${s.decks.map(d=>`<button class="duel-deck-box" data-duel-deck="${escape(d.id)}" aria-label="选择卡组：${escape(d.name)}">${deckBoxArt(d)}<strong>${escape(d.name)}</strong></button>`).join('')||'<p>暂无已保存卡组</p>'}</div>`;
  } else if(s.stage===duelStages.order) {
    if(automatic){body=duelAutomaticOrderPage();footer=duelButton('confirm-order','确认，下一步',!DuelOrder.ready(s.automatic.order),true);}
    else body=`<div class="duel-mode-grid"><button class="duel-mode" data-duel-action="first"><strong>先手</strong></button><button class="duel-mode" disabled><strong>后手</strong><small>待开发</small></button></div>`;
  } else if(s.stage===duelStages.hand) {
    if(automatic)body=duelAutomaticConfirmedPage();
    else {body=duelHandPage();footer=duelButton('match','方案选择',!!DuelModel.handError(s.deck.deck,s.count,s.hand),true);}
  } else if(s.stage===duelStages.plans) body=duelMatchesPage();
  else if(s.stage===duelStages.tutorial) {
    body=duelTutorialPage();footer=`${s.plan?.temporary?duelButton('report-outcome','报告实际情况'):''}${duelButton('back-step','←')}${duelButton('forward-step','→')}${duelButton('end','展开结束',false,true)}`;
  } else {
    body=`<div class="duel-complete"><span>✓</span><h2>展开已结束</h2><p>${escape(s.deck.name)} · ${escape(s.plan?.name||'')}</p></div>`;
    footer=duelButton('new','再来一场',false,true);
  }
  $('#duel-body').innerHTML=body;$('#duel-footer').innerHTML=footer;$('#duel-footer').hidden=!footer;duelTell(duelUI.message);
  if(s.stage===duelStages.deck&&automatic&&deckPage==='preview'&&hasDeck)mountDuelAutomaticPreview();
  if(s.forecast&&s.stage>=duelStages.plans&&s.stage<=duelStages.tutorial)renderDuelForecast();
  if(s.stage===duelStages.plans){$('#duel-plan-sort').onchange=event=>{s.planSort=event.target.value;renderDuel();};bindPlanFavorites($('#duel-body'));}
  if(duelUI.busy)$('#duel-body').querySelectorAll('button,input').forEach(el=>el.disabled=true);
  if(s.stage===duelStages.tutorial){
    $('#duel-graph-scroll').querySelectorAll('button,input,textarea').forEach(el=>el.tabIndex=-1);
    mountDuelGraphResize();layoutDuelGraph();paintDuelPosition();
  }
  pruneReviewCards();
  if(typeof syncDuelOrderWatch==='function')syncDuelOrderWatch();
}
function focusDuelPosition() {
  const viewport=$('#duel-graph-scroll'),current=viewport?.querySelector('.duel-node.current');if(!current)return;
  const scale=duelUI.graphScale||1;
  viewport.scrollLeft=Math.max(0,current.offsetLeft*scale-(viewport.clientWidth-current.offsetWidth*scale)/2);
  viewport.scrollTop=Math.max(0,current.offsetTop*scale-8);
}
function paintDuelPosition(scroll=true) {
  const s=duelState();if(s.stage!==duelStages.tutorial||!s.position)return;
  const graph=$('#duel-graph-scroll');
  graph.querySelectorAll('[data-duel-node]').forEach(button=>{
    const active=button.dataset.duelNode===s.position.key;button.classList.toggle('current',active);button.setAttribute('aria-current',active?'step':'false');
  });
  if(scroll)focusDuelPosition();
  const outgoing=s.graph.edges.filter(e=>e.from===s.position.key);
  $('#duel-route-choice').hidden=outgoing.length<2;
  $('#duel-route-choice').innerHTML=outgoing.length>1?outgoing.map((edge,i)=>`<button data-duel-choice="${i}" aria-pressed="${i===(s.position.choice||0)}">${escape(edge.label)}</button>`).join(''):'';
  const current=s.graph.nodes.find(n=>n.key===s.position.key),source=duelNodeSource(current),edit=source.report.annotations?.nodes?.[source.node.id];
  $('#duel-current-detail').innerHTML=`<header><h3>${escape(current.label)} · ${escape(edit?.name||(current.id==='initial'?'初始手牌':current.id==='final'?'终场':`Step ${current.number}`))}</h3>${edit?.notes?`<p>${escape(edit.notes)}</p>`:''}</header><div class="review-board">${renderBoard(source.node,source.report)}</div>`;
  $('#duel-zone-content').hidden=true;
  const edges=s.graph.edges;
  $('[data-duel-action="back-step"]').disabled=!edges.some(e=>e.to===s.position.key);
  $('[data-duel-action="forward-step"]').disabled=!outgoing.length;
  paintDuelShortcutStatus();pruneReviewCards();
}
function duelNavigate(action) {
  const s=duelState();if(s.stage!==duelStages.tutorial||s.ended||duelUI.busy||s.forecast?.busy||document.querySelector('dialog[open]')||moduleUI.current!=='duel')return;
  if(action==='end'){void endDuel();return;}
  if(action==='forward'&&s.plan?.temporary){void advanceDuelForecast().catch(error=>duelTell(error.message));return;}
  closeDuelPreview();closeReviewDetail();
  if(document.activeElement?.closest('.duel-node'))document.activeElement.blur();
  s.position=DuelModel.navigate(s.graph,s.position,action);paintDuelPosition();
}
async function endDuel() {
  if(typeof dropDuelForecast==='function')dropDuelForecast(duelState());
  if(app.active && duelState().modularSession===app.active.id){
    await api('/api/modular/auto',{id:app.active.id,enabled:false});
    await api('/api/stop',{id:app.active.id});
  }
  const s=duelState();s.enabled=false;s.ended=true;s.stage=duelStages.complete;s.reached=duelStages.complete;s.session=crypto.randomUUID();
  closeDuelPreview();closeReviewDetail();await syncDuelShortcuts();renderDuel();
}
async function chooseDuelDeck(id) {
  const s=duelState(),saved=await api(`/api/deck?id=${encodeURIComponent(id)}`);
  await Promise.all([...new Set(zones.flatMap(z=>saved.deck[z]))].map(code=>card(code).catch(()=>{})));
  if(!s.deck||s.deck.id!==saved.id||s.deck.revision!==saved.revision){
    s.deck=saved;s.count=duelHandCount();s.hand=Array(s.count).fill(null);s.marks.clear();s.first=false;s.target=null;invalidateDuel(duelStages.deck);
  }else s.deck=saved;
  s.deckPage='preview';closeDeckPreview();duelTell('');
}
async function matchDuel(force=false) {
  const s=duelState(),error=DuelModel.handError(s.deck.deck,s.count,s.hand);
  if(error)throw new Error(error);
  if(s.result&&!force){duelReach(duelStages.plans);return;}
  const generation=++duelUI.generation;
  const result=await api('/api/duel/match',{deck_id:s.deck.id,revision:s.deck.revision,hand_count:s.count,hand:s.hand});
  if(generation!==duelUI.generation)return;
  s.result=result;s.plan=s.routes=s.graph=s.position=null;s.ended=false;s.reached=duelStages.plans;duelReach(duelStages.plans);duelTell('');
}
function chooseDuelPlan(id) {
  const s=duelState(),plan=s.result.matches.find(p=>p.id===id);if(!plan)return;
  if(s.forecast)dropDuelForecast(s);
  if(s.plan!==plan||s.ended) {
    s.plan=plan;s.routes=duelPlanRoutes(plan);s.graph=DuelModel.graph(s.routes);
    s.position={key:s.graph.start,choice:0};s.ended=false;s.session=crypto.randomUUID();
  }
  s.enabled=true;closeDuelPreview();duelReach(duelStages.tutorial);renderDuel();void syncDuelShortcuts();
}
function clearDuelPreviewTimers() {
  clearTimeout(duelUI.hoverTimer);clearTimeout(duelUI.closeTimer);
  duelUI.hoverTimer=duelUI.closeTimer=null;
}
function closeDuelPreview(suppress=false) {
  if(suppress)duelUI.previewSuppressed=duelUI.previewAnchor;
  clearDuelPreviewTimers();
  const panel=$('#duel-preview');
  if(panel.contains(document.activeElement))document.activeElement.blur();
  if(reviewUI.anchor?.element?.closest('#duel-preview'))closeReviewDetail();
  duelUI.previewAnchor=duelUI.previewRect=duelUI.previewKind=duelUI.previewId=null;panel.hidden=true;
}
function duelPreviewPlacement({anchor,graph,width,height,viewport,footer,beside=false}) {
  if(beside) {
    const side=anchor.right+8+width<=viewport.width-12?anchor.right+8:anchor.left-8-width>=12?anchor.left-8-width:null;
    if(side!==null)return {left:side,top:Math.max(70,Math.min(anchor.top,viewport.height-height-12)),height};
  }
  const left=Math.max(12,Math.min(anchor.left,viewport.width-width-12));
  const overlapsFooter=footer&&left<footer.right&&left+width>footer.left;
  const bottom=Math.min(viewport.height-12,overlapsFooter?footer.top-12:Infinity);
  const below={top:Math.max(70,graph.bottom+8),bottom};
  const above={top:70,bottom:Math.min(bottom,graph.top-8)};
  const available=area=>Math.max(0,area.bottom-area.top);
  const area=available(below)>=Math.min(height,180)||available(below)>=available(above)?below:above;
  const fittedHeight=Math.min(height,available(area));
  // Never move a tall preview back across the graph just to fit it on screen.
  if(fittedHeight<80)return null;
  return {left,top:area===below?area.top:area.bottom-fittedHeight,height:fittedHeight};
}
function paintDuelPreview() {
  const s=duelState(),plan=duelUI.previewKind==='plan'?s.result?.matches.find(p=>p.id===duelUI.previewId):null,node=duelUI.previewKind==='node'?s.graph?.nodes.find(n=>n.key===duelUI.previewId):null;
  if(!plan&&!node)return;
  $('#duel-preview-content').innerHTML=plan?`<div class="duel-preview-modes" role="group" aria-label="预览方式"><button data-duel-preview-mode="compact" aria-pressed="${!duelUI.detailPreview}">简略</button><button data-duel-preview-mode="detailed" aria-pressed="${duelUI.detailPreview}">详细</button></div>${duelPlanSummary(plan,duelUI.detailPreview)}`:duelNodeDetail(node);
  const p=$('#duel-preview');p.style.maxHeight='';p.hidden=false;
  const box=duelUI.previewAnchor.getBoundingClientRect();
  const placement=duelPreviewPlacement({anchor:box,graph:node?$('#duel-graph-scroll').getBoundingClientRect():box,width:p.offsetWidth,height:p.offsetHeight,
    viewport:{width:innerWidth,height:innerHeight},footer:$('#duel-footer').hidden?null:$('#duel-footer').getBoundingClientRect(),beside:!!plan});
  if(!placement){p.hidden=true;return;}
  p.style.left=placement.left+'px';p.style.top=placement.top+'px';p.style.maxHeight=placement.height+'px';
  pruneReviewCards();
}
function showDuelPreview(anchor) {
  if(duelUI.previewClickPoint)return;
  clearTimeout(duelUI.closeTimer);duelUI.closeTimer=null;
  if(duelUI.previewSuppressed===anchor||duelUI.previewAnchor===anchor&&(duelUI.hoverTimer||!$('#duel-preview').hidden))return;
  if(duelUI.previewAnchor!==anchor)closeDuelPreview();
  clearDuelPreviewTimers();duelUI.previewAnchor=anchor;duelUI.previewRect=anchor.getBoundingClientRect();
  duelUI.hoverTimer=setTimeout(()=>{
    duelUI.hoverTimer=null;
    if(duelUI.previewAnchor!==anchor||!anchor.isConnected||!anchor.matches(':hover')||document.querySelector('dialog[open]'))return;
    closeReviewDetail();duelUI.previewKind=anchor.dataset.duelPlan?'plan':'node';duelUI.previewId=anchor.dataset.duelPlan||anchor.dataset.duelNode;
    paintDuelPreview();
  },280);
}
function pauseDuelPreviewForClick(event) {
  duelUI.previewClickPoint={x:event.clientX,y:event.clientY};
  closeDuelPreview();closeReviewDetail();
}
function resumeDuelPreviewAfterMove(event) {
  const point=duelUI.previewClickPoint;
  if(!point||event.buttons||Math.hypot(event.clientX-point.x,event.clientY-point.y)<4)return;
  duelUI.previewClickPoint=null;
  const anchor=event.target.closest?.('[data-duel-plan],[data-duel-node]');
  if(anchor&&moduleUI.current==='duel')showDuelPreview(anchor);
}
function withinDuelPreview(target) {
  return !!target&&(duelUI.previewAnchor?.contains(target)||$('#duel-preview').contains(target)||
    !!reviewUI.anchor?.element?.closest('#duel-preview')&&$('#review-card-popover').contains(target));
}
function scheduleDuelPreviewClose() {
  clearDuelPreviewTimers();
  duelUI.closeTimer=setTimeout(()=>{
    duelUI.closeTimer=null;
    if(duelUI.previewAnchor?.matches(':hover')||$('#duel-preview').matches(':hover')||
      reviewUI.anchor?.element?.closest('#duel-preview')&&$('#review-card-popover').matches(':hover'))return;
    closeDuelPreview();
  },220);
}
function paintDuelShortcutStatus() {
  const el=$('#duel-shortcut-status');if(!el)return;
  el.textContent=duelUI.shortcutStatus?.error||'';
  el.hidden=!el.textContent;
}
function syncDuelShortcuts() {
  if(!window.trainerDesktop?.tutorialUpdate)return Promise.resolve();
  const s=duelState(),payload={active:s.stage===duelStages.tutorial&&!s.ended&&moduleUI.current==='duel',enabled:s.enabled,suspended:!!document.querySelector('dialog[open]'),session:s.session,bindings:{...duelUI.bindings}};
  duelUI.shortcutQueue=duelUI.shortcutQueue.catch(()=>{}).then(()=>window.trainerDesktop.tutorialUpdate(payload)).then(status=>{
    if(status.session===duelState().session){duelUI.shortcutStatus=status;paintDuelShortcutStatus();}
  }).catch(error=>{duelUI.shortcutStatus={error:error.message};paintDuelShortcutStatus();});
  return duelUI.shortcutQueue;
}
function duelAccelerator(event) {
  return TutorialBindings.accelerator(event);
}
async function openDuelShortcuts() {
  closeDuelPreview();closeReviewDetail();
  const dialog=$('#duel-shortcut-dialog');
  if(window.trainerDesktop?.tutorialSettings)duelUI.bindings=(await window.trainerDesktop.tutorialSettings()).bindings;
  $('#duel-shortcut-fields').innerHTML=Object.entries(duelLabels).map(([key,label])=>`<label>${label}<input data-duel-binding="${key}" value="${escape(duelUI.bindings[key])}" aria-label="${label}快捷键" maxlength="80"><button type="button" data-duel-clear-binding="${key}">清除</button></label>`).join('');
  $('#duel-shortcut-error').textContent='';dialog.showModal();await syncDuelShortcuts();
}
async function closeDuelShortcuts() {$('#duel-shortcut-dialog').close();await syncDuelShortcuts();}
async function openAppSettings() {
  closeDuelPreview();closeReviewDetail();
  closeDeckPreview();
  const settings=await api('/api/duel/settings');duelUI.handCount=settings.hand_count;
  $('#duel-default-count').value=settings.hand_count;$('#app-settings-error').textContent='';
  $('#app-settings-dialog').showModal();await syncDuelShortcuts();await syncNativeHost();
  if(typeof loadSuperpreSettings==='function')void loadSuperpreSettings(true);
}
async function closeAppSettings() {$('#app-settings-dialog').close();await syncDuelShortcuts();await syncNativeHost();}

$('#duel').addEventListener('click',run(async event=>{
  if(duelUI.busy)return;const s=duelState(),node=event.target.closest('[data-duel-node]'),button=event.target.closest('button');
  if(node){event.stopPropagation();closeDuelPreview(true);closeReviewDetail();if(s.plan?.temporary){await selectForecastNode(node.dataset.duelNode);return;}s.position={key:node.dataset.duelNode,choice:0};node.focus({preventScroll:true});paintDuelPosition();return;}
  if(!button||button.disabled)return;
  if(button.dataset.duelFunctionPage){s.functionPage=button.dataset.duelFunctionPage;duelTell('');renderDuel();return;}
  if(button.dataset.duelDeckPage){if(s.operationMode==='automatic')s.automatic.page=button.dataset.duelDeckPage;else s.deckPage=button.dataset.duelDeckPage;closeReviewDetail();closeDeckPreview();duelTell('');renderDuel();return;}
  if(button.dataset.duelAutoTag){
    const draft=s.automatic,id=button.dataset.duelAutoTag,role=button.dataset.role,current=draft.primaryIds.includes(id)?'primary':draft.tagIds.includes(id)?'secondary':'';
    draft.notice='TAG 已调整，保存后更新本地卡组。';DuelAutomatic.setRole(draft,id,current===role?'':role);
    $('#duel-auto-tags').innerHTML=duelAutomaticTags();duelAutomaticSaveFeedback();return;
  }
  if(button.dataset.reviewZone){event.stopPropagation();showDuelZone(button.dataset.reviewZone);return;}
  if(button.dataset.duelCloseZone!==undefined){$('#duel-zone-content').hidden=true;return;}
  if(button.dataset.duelStage!==undefined){duelGo(Number(button.dataset.duelStage));return;}
  if(button.dataset.duelDeck){await duelWork(()=>chooseDuelDeck(button.dataset.duelDeck));return;}
    if(button.dataset.duelSlot!==undefined){event.stopPropagation();s.target=s.target===Number(button.dataset.duelSlot)?null:Number(button.dataset.duelSlot);closeReviewDetail();renderDuel();return;}
  if(button.dataset.duelRemove!==undefined){s.hand[Number(button.dataset.duelRemove)]=null;s.target=null;invalidateDuel(duelStages.hand);renderDuel();return;}
  const candidate=button.closest('.duel-candidate');
  if(button.dataset.duelAdd||candidate&&button.dataset.reviewCard) {
    event.stopPropagation();
    const code=Number(button.dataset.duelAdd||candidate.querySelector('[data-duel-add]').dataset.duelAdd);
    if(button.getAttribute('aria-disabled')==='true')return;
    const hand=DuelModel.place(s.deck.deck,s.count,s.hand,code,s.target??s.hand.indexOf(null));
    if(hand&&JSON.stringify(hand)!==JSON.stringify(s.hand)){duelUI.handHoverSuppressed={code,rect:button.getBoundingClientRect()};s.hand=hand;s.target=null;invalidateDuel(duelStages.hand);closeReviewDetail();renderDuel();}
    return;
  }
  if(button.dataset.duelPlan){chooseDuelPlan(button.dataset.duelPlan);return;}
  if(button.dataset.duelChoice!==undefined){s.position.choice=Number(button.dataset.duelChoice);paintDuelPosition(false);return;}
  const action=button.dataset.duelAction;if(!action)return;
  if(await duelAutomaticAction(action))return;
  if(action==='back'){duelGo(s.stage-1);return;}
  if(action==='modular'){await launchModularFromDuel();return;}
  if(action==='report-outcome'){await openDuelObservation();return;}
  if(action==='bo1'){s.mode='BO1';duelReach(duelStages.function);duelTell('');renderDuel();return;}
  if(action==='manual'){await duelWork(async()=>{s.decks=await api('/api/decks');if(s.operationMode!=='manual')invalidateDuel(duelStages.function);s.operationMode='manual';s.functionPage='choice';if(s.deck)await refreshDuelDeck();duelReach(duelStages.deck);duelTell('');});return;}
  if(action==='deck-list'){await duelWork(async()=>{s.decks=await api('/api/decks');s.deckPage='list';});return;}
  if(action==='refresh-decks'){await duelWork(async()=>{s.decks=await api('/api/decks');});return;}
  if(action==='start-duel'){await duelWork(async()=>{if(await refreshDuelDeck())duelReach(duelStages.order);});return;}
  if(action==='first'){if(s.count>s.deck.deck.main.length)return duelTell('起手张数超过主卡组张数，请在全局设置中调整。');s.first=true;duelReach(duelStages.hand);duelTell('');renderDuel();return;}
      if(action==='cancel-replace'){s.target=null;renderDuel();return;}
  if(action==='match'||action==='rematch'){await duelWork(()=>matchDuel(action==='rematch'));return;}
  if(action==='edit-deck'){s.deckPage='preview';duelGo(duelStages.deck);return;}
  if(action==='edit-hand'){duelGo(duelStages.hand);return;}
  if(action==='favorites-only'){s.favoritesOnly=!s.favoritesOnly;renderDuel();return;}
  if(action==='back-step'||action==='forward-step'){duelNavigate(action==='back-step'?'back':'forward');return;}
  if(action==='end'){await endDuel();return;}
  if(action==='toggle-shortcuts'){s.enabled=!s.enabled;await syncDuelShortcuts();renderDuel();return;}
  if(action==='shortcuts'){await openDuelShortcuts();return;}
  if(action==='new')await startNewDuel();
}));
async function startNewDuel() {
  dropDuelForecast(duelState());
  duelState().enabled=false;duelState().stage=duelStages.mode;await syncDuelShortcuts();++duelUI.generation;
  duelUI.state=newDuel();duelUI.message='';duelUI.detailPreview=false;closeDuelPreview();closeReviewDetail();renderDuel();
}
$('#duel').addEventListener('pointerover',run(async event=>{
  if(event.pointerType==='touch'||event.buttons)return;
  const deck=event.target.closest('[data-duel-deck]');if(deck){await showDeckPreview(deck);return;}
  const anchor=event.target.closest('[data-duel-plan],[data-duel-node]');if(anchor&&!anchor.contains(event.relatedTarget))showDuelPreview(anchor);
}));
$('#duel').addEventListener('pointerdown',event=>{
  if(event.button===0&&event.target.closest('[data-duel-node],#duel-footer'))pauseDuelPreviewForClick(event);
},true);
$('#duel-footer').addEventListener('pointerenter',()=>{closeDuelPreview();closeReviewDetail();});
document.addEventListener('pointermove',resumeDuelPreviewAfterMove);
$('#duel').addEventListener('pointerout',event=>{
  if(!deckManager.anchor?.contains(event.relatedTarget)&&!$('#deck-preview').contains(event.relatedTarget))delayCloseDeckPreview();
  if(duelUI.previewSuppressed&&!duelUI.previewSuppressed.contains(event.relatedTarget))duelUI.previewSuppressed=null;
  if(!duelUI.previewAnchor||withinDuelPreview(event.relatedTarget))return;
  scheduleDuelPreviewClose();
});
for(const panel of [$('#duel-preview'),$('#review-card-popover')]) {
  panel.addEventListener('pointerenter',()=>{if(withinDuelPreview(panel)){clearTimeout(duelUI.closeTimer);duelUI.closeTimer=null;}});
  panel.addEventListener('pointerleave',event=>{if(duelUI.previewAnchor&&!withinDuelPreview(event.relatedTarget))scheduleDuelPreviewClose();});
}
$('#duel-preview-close').onclick=()=>closeDuelPreview(true);
window.addEventListener('resize',()=>{closeDuelPreview();if(duelState().stage===duelStages.tutorial){layoutDuelGraph();focusDuelPosition();}});
document.addEventListener('scroll',event=>{
  const anchor=duelUI.previewAnchor,rect=duelUI.previewRect;if(!anchor||!rect||event.target.closest?.('#duel-preview,#review-card-popover'))return;
  const now=anchor.getBoundingClientRect();
  if(!anchor.isConnected||Math.abs(now.left-rect.left)>.5||Math.abs(now.top-rect.top)>.5)closeDuelPreview();
},true);
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){closeDuelPreview(true);return;}
  if(event.defaultPrevented||event.isComposing||event.target.closest('input,textarea,select,[contenteditable=true]')||document.querySelector('dialog[open]'))return;
  const action=TutorialBindings.actionFor(duelUI.bindings,event);
  if(action&&moduleUI.current==='duel'&&duelState().stage===duelStages.tutorial&&duelState().enabled){event.preventDefault();duelNavigate(action);}
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
    const bindings=TutorialBindings.normalize(Object.fromEntries([...$('#duel-shortcut-fields').querySelectorAll('input')].map(i=>[i.dataset.duelBinding,i.value])));
    const saved=window.trainerDesktop?.tutorialSaveSettings?await window.trainerDesktop.tutorialSaveSettings(bindings):{bindings};
    duelUI.bindings=saved.bindings;
    await closeDuelShortcuts();if(moduleUI.current==='duel')renderDuel();
  }catch(error){$('#duel-shortcut-error').textContent=error.message;}finally{button.disabled=false;}
};
window.trainerDesktop?.onTutorialAction(event=>{const s=duelState();if(event.session===s.session&&s.enabled)duelNavigate(event.action);});
window.trainerDesktop?.onTutorialStatus(status=>{if(status.session===duelState().session){duelUI.shortcutStatus=status;paintDuelShortcutStatus();}});

$('#toggle-duel-card-mark').onclick=()=>{
  const key=reviewUI.selected?.duel_mark_key,s=duelState();if(!key||duelUI.busy||s.stage!==duelStages.deck)return;
  const marks=duelPreviewMarks();marks.has(key)?marks.delete(key):marks.add(key);
  $('#duel-body').querySelectorAll('[data-duel-mark-key]').forEach(el=>el.classList.toggle('is-marked',marks.has(el.dataset.duelMarkKey)));
  updateDuelMarkButton();
};
$('#duel-preview').addEventListener('click',event=>{
  const button=event.target.closest('[data-duel-preview-mode]');if(!button)return;
  duelUI.detailPreview=button.dataset.duelPreviewMode==='detailed';paintDuelPreview();
});
$('#duel').addEventListener('contextmenu',event=>{
  if(duelUI.busy||duelState().stage!==duelStages.hand)return;
  const slot=event.target.closest('[data-duel-slot]'),candidate=event.target.closest('[data-duel-add]');
  if(!slot&&!candidate)return;event.preventDefault();event.stopPropagation();
  const s=duelState(),index=slot?Number(slot.dataset.duelSlot):s.hand.lastIndexOf(Number(candidate.dataset.duelAdd));
  if(index<0||!s.hand[index])return;
  s.hand[index]=null;s.target=null;invalidateDuel(duelStages.hand);closeReviewDetail();renderDuel();
});
$('#duel').addEventListener('keydown',event=>{
  const node=event.target.closest('[data-duel-node]');
  if(node&&['Enter',' '].includes(event.key)){event.preventDefault();node.click();}
});
function showDuelZone(key) {
  const s=duelState(),current=s.graph.nodes.find(n=>n.key===s.position.key),{report,node}=duelNodeSource(current),[side,zone]=key.split(':').map(Number),cards=boardCards(node,side,zone);
  const panel=$('#duel-zone-content');panel.hidden=false;
  panel.innerHTML=`<section class="zone-contents"><button data-duel-close-zone aria-label="关闭区域">×</button><h3>${escape(reviewPlace({controller:side,location:zone}))} · ${cards.length} 张</h3><div>${cards.map(c=>reviewCard(c,node.id,{report,name:true,face:reviewKnown(c)})).join('')||'当前区域为空'}</div></section>`;
}

$('#app-settings').onclick=run(openAppSettings);
$('#app-settings-cancel').onclick=run(closeAppSettings);
$('#app-settings-dialog').oncancel=event=>{event.preventDefault();void closeAppSettings();};
$('#app-settings-shortcuts').onclick=run(async()=>{
  // Keep the general settings dialog open underneath, including unsaved input.
  await openDuelShortcuts();
});
$('#app-settings-form').onsubmit=async event=>{
  event.preventDefault();const button=$('#app-settings-save');button.disabled=true;
  try {
    const count=Number($('#duel-default-count').value);
    if(!Number.isInteger(count)||count<1||count>60)throw new Error('先攻起手张数必须是 1–60 之间的整数');
    const saved=await api('/api/duel/settings',{hand_count:count});duelUI.handCount=saved.hand_count;
    const s=duelState();if(s.deck&&s.stage<=duelStages.order&&s.count!==saved.hand_count){s.count=saved.hand_count;s.hand=Array(s.count).fill(null);s.target=null;invalidateDuel(duelStages.order);}
    await closeAppSettings();if(moduleUI.current==='duel')renderDuel();
  }catch(error){$('#app-settings-error').textContent=error.message;}finally{button.disabled=false;}
};

document.addEventListener('pointermove',event=>{
  const suppressed=duelUI.handHoverSuppressed;if(!suppressed)return;
  const r=suppressed.rect;if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)duelUI.handHoverSuppressed=null;
});
