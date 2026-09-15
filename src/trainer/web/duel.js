'use strict';

const duelDefaults = {back:'Left',forward:'Right',up:'Up',down:'Down',end:''};
const duelLabels = {back:'后退',forward:'前进',up:'上一条路线',down:'下一条路线',end:'展开结束'};
const newDuel = () => ({stage:0,reached:0,mode:null,deck:null,deckPage:'list',decks:[],first:false,count:5,hand:Array(5).fill(null),
  marks:new Set(),target:null,result:null,plan:null,routes:null,graph:null,position:null,ended:false,enabled:false,session:crypto.randomUUID()});
const duelUI = {state:newDuel(),busy:false,generation:0,message:'',detailPreview:false,handCount:5,bindings:{...duelDefaults},shortcutStatus:null,shortcutQueue:Promise.resolve(),hoverTimer:null,closeTimer:null,previewAnchor:null,previewKind:null,previewId:null,handHoverSuppressed:null};
const duelState = () => duelUI.state;
const duelHandCount = () => duelUI.handCount;
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
    duelUI.handCount=(await api('/api/duel/settings')).hand_count;
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
  s.enabled=stage===5;
  renderDuel();void syncDuelShortcuts();
}
function duelReach(stage) {const s=duelState();s.stage=stage;s.reached=Math.max(s.reached,stage);}
function duelButton(action,label,disabled=false,primary=false) {
  return `<button ${['back-step','forward-step'].includes(action)?`aria-label="${action==='back-step'?'后退':'前进'}"`:''} data-duel-action="${action}" ${disabled||duelUI.busy?'disabled':''} class="${primary?'primary':''}">${label}</button>`;
}
function duelReadCard(code,extra={}) {
  const report={id:'duel-catalog',catalog:Object.fromEntries(app.cache),events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  return reviewCard({code,name:duelName(code),identity_known:true,...extra},'catalog',{report,face:true,zone:false,position:false,catalogue:true});
}
function duelDeckPreview() {
  const s=duelState();
  return `<div class="duel-section-heading"><h2>${escape(s.deck.name)}</h2></div>`+
    zones.map(zone=>`<section class="duel-zone"><h3>${zoneNames[zone]} <small>${s.deck.deck[zone].length} 张</small></h3><div class="duel-card-grid">${s.deck.deck[zone].map((code,i)=>{
      const key=`${zone}:${i}`;
      return `<article class="duel-card ${s.marks.has(key)?'is-marked':''}" data-duel-mark-key="${key}">${duelReadCard(code,{duel_mark_key:key})}</article>`;
    }).join('')||'<p>暂无卡牌</p>'}</div></section>`).join('');
}
function updateDuelMarkButton() {
  const key=reviewUI.selected?.duel_mark_key,s=duelState(),button=$('#toggle-duel-card-mark');
  button.hidden=moduleUI.current!=='duel'||s.stage!==1||s.deckPage!=='preview'||!key;
  button.disabled=duelUI.busy;button.textContent=s.marks.has(key)?'取消标记':'添加标记';
  button.setAttribute('aria-pressed',String(s.marks.has(key)));
}
function duelCandidate(code) {
  const s=duelState(),stock=DuelModel.counts(s.deck.deck.main).get(code),used=DuelModel.counts(s.hand).get(code)||0,remaining=stock-used;
  const marked=[...s.marks].some(k=>k.startsWith('main:')&&s.deck.deck.main[Number(k.split(':')[1])]===code);
  const disabled=!DuelModel.place(s.deck.deck,s.count,s.hand,code,s.target??s.hand.indexOf(null));
  return `<article class="duel-candidate ${marked?'is-marked':''} ${remaining===0?'is-exhausted':''}">${duelReadCard(code).replace('<button ',`<button data-duel-add="${code}" aria-disabled="${disabled||duelUI.busy}" `)}<span class="duel-stock" aria-label="剩余 ${remaining} 张">${remaining}</span></article>`;
}
function duelHandPage() {
  const s=duelState(),main=s.deck.deck.main;
  return `<div class="duel-section-heading"><h2>准备起手 <small>${s.hand.filter(Boolean).length} / ${s.count}</small></h2></div>
    <div class="duel-hand">${s.hand.map((code,i)=>`<article class="duel-slot ${s.target===i?'selected':''}">${code?duelReadCard(code).replace('<button ',`<button data-duel-slot="${i}" aria-pressed="${s.target===i}" `):`<button data-duel-slot="${i}" aria-label="起手 ${i+1} 空槽位" aria-pressed="${s.target===i}"><span class="duel-slot-plus">＋</span></button>`}</article>`).join('')}</div>
    <section class="duel-candidates"><h3>主卡组 <small>${main.length} 张</small></h3><div class="duel-candidate-grid">${[...new Set(main)].map(duelCandidate).join('')}</div></section>`;
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
  const final=plan.review?.nodes?.find(n=>n.kind==='final')||{id:'final',state:plan.final_state};
  const marks=plan.annotations?.final_marks||{};
  const marked=(final.state?.cards||[]).filter(c=>marks[String(c.instance_id)]?.marked);
  const cards=kind==='opening'?plan.requirements?.opening||[]:marked.length?marked:plan.requirements?.final?.cards||[];
  return cards.slice(0,limit).map(c=>{
    const node=kind==='opening'?'initial':final.id,random=kind==='final'&&reviewRandomDraw(c,final,plan),known=c.code&&!random;
    const label=random?'随机抽牌':c.name||c.constraint||plan.catalog?.[c.code]?.name||'任意手牌';
    return `<figure><img src="${known?`/pics/${Number(c.code)}.jpg`:'/review-back.svg'}" alt="${escape(label)}" loading="lazy"><figcaption>${escape(label)}</figcaption>${kind==='opening'?`<small>×${c.count||1}</small>`:`<small class="duel-region">${escape(duelRegion(c))}</small>`}</figure>`;
  }).join('');
}
function duelPlanSummary(plan,detailed=false) {
  return `<h3>${escape(plan.name)}</h3>${plan.expansion?.notes?`<p class="preserve-lines">${escape(plan.expansion.notes)}</p>`:''}<section><h4>起手</h4><div class="duel-summary-cards">${duelSummaryCards(plan,'opening')||'<span>无指定起手</span>'}</div></section><section><h4>终场</h4><div class="duel-summary-cards">${duelSummaryCards(plan,'final')||'<span>未记录终场卡牌</span>'}</div></section>${detailed?renderPlanTutorialSvg(buildPlanTutorial(plan,true)):''}`;
}
function duelMatchesPage() {
  const result=duelState().result;if(!result)return '';
  return `<div class="duel-section-heading"><h2>方案选择</h2>${duelButton('rematch','刷新')}</div><div class="duel-plan-grid">${result.matches.map(plan=>`<button class="duel-plan" data-duel-plan="${escape(plan.id)}"><strong>${escape(plan.name)}</strong>${plan.expansion?.notes?`<span class="duel-plan-note">${escape(plan.expansion.notes)}</span>`:''}<span class="duel-tile-cards">${duelSummaryCards(plan,'opening',3)}</span><span class="duel-tile-arrow" aria-hidden="true">↓</span><span class="duel-tile-cards">${duelSummaryCards(plan,'final',4)}</span></button>`).join('')||`<div class="duel-empty"><h3>${escape(result.reason||'暂无可用方案')}</h3>${duelButton('edit-hand','调整起手')}</div>`}</div>`;
}
function duelNodeSource(node) {
  const s=duelState(),report=node.route==='main'?s.plan:s.plan.branches.find(b=>b.id===node.route)?.report;
  const nodes=report.review?.nodes||reviewFallback(report);
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
  const current=viewport.querySelector('.duel-node.current'),scale=duelUI.graphScale||1;
  if(current){viewport.scrollLeft=Math.max(0,current.offsetLeft*scale-(viewport.clientWidth-current.offsetWidth*scale)/2);viewport.scrollTop=current.offsetTop*scale-8;}
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
  return `<div class="duel-section-heading"><h2>${escape(s.plan.name)}</h2><div class="duel-actions">${duelButton('toggle-shortcuts',s.enabled?'暂停快捷键':'启用快捷键')}${duelButton('shortcuts','快捷键设置')}</div></div><p id="duel-shortcut-status" role="status"></p>${duelGraphHtml()}<div id="duel-graph-resize" class="duel-graph-resize" role="separator" tabindex="0" aria-label="调整教程图高度" aria-orientation="horizontal" aria-valuemin="200" aria-valuemax="1800" title="拖动调整教程图高度；双击恢复默认"><span></span></div><div id="duel-route-choice" class="duel-route-choice"></div><article id="duel-current-detail" class="duel-current-detail"></article><div id="duel-zone-content" class="review-zone-popover" role="dialog" aria-label="区域卡牌" hidden></div>`;
}
function renderDuel() {
  const s=duelState(),mainStage=Math.min(s.stage,3),stages=['模式选择','卡组选择','决定先/后攻','卡组展开'];
  $('#duel').dataset.stage=String(s.stage);
  $('#duel-steps').innerHTML=stages.map((name,i)=>`<button data-duel-stage="${i}" ${i>s.reached||duelUI.busy?'disabled':''} ${i===mainStage?'aria-current="step"':''}><span>${i<mainStage?'✓':i+1}</span>${name}</button>`).join('');
  $('#duel-substeps').hidden=s.stage!==1&&s.stage<3||s.stage>5;
  $('#duel-substeps').setAttribute('aria-label',s.stage===1?'卡组选择流程':'卡组展开流程');
  $('#duel-substeps').innerHTML=s.stage===1?['选择卡组','卡牌预览'].map((name,i)=>`<button data-duel-deck-page="${i?'preview':'list'}" ${i&&!s.deck?'disabled':''} ${s.deckPage===(i?'preview':'list')?'aria-current="step"':''}>${i+1}. ${name}</button>`).join(''):['准备起手','方案选择','展开教程'].map((name,i)=>`<button data-duel-stage="${i+3}" ${i+3>s.reached||duelUI.busy?'disabled':''} ${s.stage===i+3?'aria-current="step"':''}>${i+1}. ${name}</button>`).join('');
  let body='',footer='';
  if(s.stage===0) {
    body=`<div class="duel-mode-grid"><button data-duel-action="bo1" class="duel-mode"><span class="duel-mode-symbol" aria-hidden="true">◇</span><strong>BO1</strong><span>单局模式</span></button><button class="duel-mode" disabled><span class="duel-mode-symbol" aria-hidden="true">◇◇</span><strong>BO3</strong><span>三局两胜</span><small>待开发</small></button></div>`;
  } else if(s.stage===1) {
    if(s.deckPage==='preview'&&s.deck){body=duelDeckPreview();footer=duelButton('start-duel','开始决斗',false,true);}
    else body=`<div class="duel-section-heading"><h2>选择卡组</h2>${duelButton('refresh-decks','刷新列表')}</div><div class="duel-deck-grid">${s.decks.map(d=>`<button class="duel-deck-box" data-duel-deck="${escape(d.id)}" aria-label="选择卡组：${escape(d.name)}">${deckBoxArt(d)}<strong>${escape(d.name)}</strong></button>`).join('')||'<p>暂无已保存卡组</p>'}</div>`;
  } else if(s.stage===2) {
    body=`<div class="duel-mode-grid"><button class="duel-mode" data-duel-action="first"><strong>先手</strong></button><button class="duel-mode" disabled><strong>后手</strong><small>待开发</small></button></div>`;
  } else if(s.stage===3) {
    body=duelHandPage();footer=duelButton('match','方案选择',!!DuelModel.handError(s.deck.deck,s.count,s.hand),true);
  } else if(s.stage===4) body=duelMatchesPage();
  else if(s.stage===5) {
    body=duelTutorialPage();footer=`${duelButton('back-step','←')}${duelButton('forward-step','→')}${duelButton('end','展开结束',false,true)}`;
  } else {
    body=`<div class="duel-complete"><span>✓</span><h2>展开已结束</h2><p>${escape(s.deck.name)} · ${escape(s.plan?.name||'')}</p></div>`;
    footer=duelButton('new','再来一场',false,true);
  }
  $('#duel-body').innerHTML=body;$('#duel-footer').innerHTML=footer;$('#duel-footer').hidden=!footer;duelTell(duelUI.message);
  if(duelUI.busy)$('#duel-body').querySelectorAll('button,input').forEach(el=>el.disabled=true);
  if(s.stage===5){
    $('#duel-graph-scroll').querySelectorAll('button,input,textarea').forEach(el=>el.tabIndex=-1);
    mountDuelGraphResize();layoutDuelGraph();paintDuelPosition();
  }
  pruneReviewCards();
}
function paintDuelPosition(scroll=true) {
  const s=duelState();if(s.stage!==5||!s.position)return;
  const graph=$('#duel-graph-scroll');
  graph.querySelectorAll('[data-duel-node]').forEach(button=>{
    const active=button.dataset.duelNode===s.position.key;button.classList.toggle('current',active);button.setAttribute('aria-current',active?'step':'false');
    if(active&&scroll){const scale=duelUI.graphScale||1;graph.scrollLeft=Math.max(0,button.offsetLeft*scale-(graph.clientWidth-button.offsetWidth*scale)/2);graph.scrollTop=button.offsetTop*scale-8;}
  });
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
  const s=duelState();if(s.stage!==5||s.ended||duelUI.busy||$('#duel-shortcut-dialog').open||moduleUI.current!=='duel')return;
  if(action==='end'){void endDuel();return;}
  closeDuelPreview();closeReviewDetail();
  if(document.activeElement?.closest('.duel-node'))document.activeElement.blur();
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
    s.deck=saved;s.count=duelHandCount();s.hand=Array(s.count).fill(null);s.marks.clear();s.first=false;s.target=null;invalidateDuel(1);
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
  s.enabled=true;closeDuelPreview();duelReach(5);renderDuel();void syncDuelShortcuts();
}
function closeDuelPreview() {
  clearTimeout(duelUI.hoverTimer);clearTimeout(duelUI.closeTimer);
  const panel=$('#duel-preview');
  if(panel.contains(document.activeElement))document.activeElement.blur();
  duelUI.previewAnchor=null;panel.hidden=true;
}
function paintDuelPreview() {
  const s=duelState(),plan=duelUI.previewKind==='plan'?s.result?.matches.find(p=>p.id===duelUI.previewId):null,node=duelUI.previewKind==='node'?s.graph?.nodes.find(n=>n.key===duelUI.previewId):null;
  if(!plan&&!node)return;
  $('#duel-preview-content').innerHTML=plan?`<div class="duel-preview-modes" role="group" aria-label="预览方式"><button data-duel-preview-mode="compact" aria-pressed="${!duelUI.detailPreview}">简略</button><button data-duel-preview-mode="detailed" aria-pressed="${duelUI.detailPreview}">详细</button></div>${duelPlanSummary(plan,duelUI.detailPreview)}`:duelNodeDetail(node);
  const p=$('#duel-preview');p.hidden=false;
  const box=duelUI.previewAnchor.getBoundingClientRect();
  p.style.left=`${Math.max(12,Math.min(box.left,window.innerWidth-p.offsetWidth-12))}px`;
  p.style.top=`${Math.max(70,Math.min(box.bottom+8,window.innerHeight-p.offsetHeight-12))}px`;
  pruneReviewCards();
}
function showDuelPreview(anchor) {
  clearTimeout(duelUI.hoverTimer);clearTimeout(duelUI.closeTimer);duelUI.previewAnchor=anchor;
  duelUI.hoverTimer=setTimeout(()=>{
    if(!anchor.isConnected)return;
    closeReviewDetail();duelUI.previewKind=anchor.dataset.duelPlan?'plan':'node';duelUI.previewId=anchor.dataset.duelPlan||anchor.dataset.duelNode;
    paintDuelPreview();
  },280);
}
function paintDuelShortcutStatus() {
  const el=$('#duel-shortcut-status');if(!el)return;
  el.textContent=duelUI.shortcutStatus?.error||'';
  el.hidden=!el.textContent;
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
  const settings=await api('/api/duel/settings');duelUI.handCount=settings.hand_count;
  $('#duel-default-count').value=settings.hand_count;
  if(window.trainerDesktop?.tutorialSettings)duelUI.bindings=(await window.trainerDesktop.tutorialSettings()).bindings;
  $('#duel-shortcut-fields').innerHTML=Object.entries(duelLabels).map(([key,label])=>`<label>${label}<input data-duel-binding="${key}" value="${escape(duelUI.bindings[key])}" aria-label="${label}快捷键" maxlength="80"><button type="button" data-duel-clear-binding="${key}">清除</button></label>`).join('');
  $('#duel-shortcut-error').textContent='';dialog.showModal();await syncDuelShortcuts();
}
async function closeDuelShortcuts() {$('#duel-shortcut-dialog').close();await syncDuelShortcuts();}

$('#duel').addEventListener('click',run(async event=>{
  if(duelUI.busy)return;const s=duelState(),node=event.target.closest('[data-duel-node]'),button=event.target.closest('button');
  if(node){event.stopPropagation();closeDuelPreview();closeReviewDetail();s.position={key:node.dataset.duelNode,choice:0};paintDuelPosition(false);return;}
  if(!button||button.disabled)return;
  if(button.dataset.duelDeckPage){s.deckPage=button.dataset.duelDeckPage;closeReviewDetail();closeDeckPreview();renderDuel();return;}
  if(button.dataset.reviewZone){event.stopPropagation();showDuelZone(button.dataset.reviewZone);return;}
  if(button.dataset.duelCloseZone!==undefined){$('#duel-zone-content').hidden=true;return;}
  if(button.dataset.duelStage!==undefined){duelGo(Number(button.dataset.duelStage));return;}
  if(button.dataset.duelDeck){await duelWork(()=>chooseDuelDeck(button.dataset.duelDeck));return;}
    if(button.dataset.duelSlot!==undefined){event.stopPropagation();s.target=s.target===Number(button.dataset.duelSlot)?null:Number(button.dataset.duelSlot);closeReviewDetail();renderDuel();return;}
  if(button.dataset.duelRemove!==undefined){s.hand[Number(button.dataset.duelRemove)]=null;s.target=null;invalidateDuel(3);renderDuel();return;}
  const candidate=button.closest('.duel-candidate');
  if(button.dataset.duelAdd||candidate&&button.dataset.reviewCard) {
    event.stopPropagation();
    const code=Number(button.dataset.duelAdd||candidate.querySelector('[data-duel-add]').dataset.duelAdd);
    if(button.getAttribute('aria-disabled')==='true')return;
    const hand=DuelModel.place(s.deck.deck,s.count,s.hand,code,s.target??s.hand.indexOf(null));
    if(hand&&JSON.stringify(hand)!==JSON.stringify(s.hand)){duelUI.handHoverSuppressed={code,rect:button.getBoundingClientRect()};s.hand=hand;s.target=null;invalidateDuel(3);closeReviewDetail();renderDuel();}
    return;
  }
  if(button.dataset.duelPlan){chooseDuelPlan(button.dataset.duelPlan);return;}
  if(button.dataset.duelNode){s.position={key:button.dataset.duelNode,choice:0};paintDuelPosition(false);return;}
  if(button.dataset.duelChoice!==undefined){s.position.choice=Number(button.dataset.duelChoice);paintDuelPosition(false);return;}
  const action=button.dataset.duelAction;if(!action)return;
  if(action==='back'){duelGo(s.stage-1);return;}
  if(action==='bo1'){await duelWork(async()=>{s.decks=await api('/api/decks');s.mode='BO1';duelReach(1);});return;}
  if(action==='deck-list'){await duelWork(async()=>{s.decks=await api('/api/decks');s.deckPage='list';});return;}
  if(action==='refresh-decks'){await duelWork(async()=>{s.decks=await api('/api/decks');});return;}
  if(action==='start-duel'){await duelWork(async()=>{if(await refreshDuelDeck())duelReach(2);});return;}
  if(action==='first'){if(s.count>s.deck.deck.main.length)return duelTell('起手张数超过主卡组张数，请在全局设置中调整。');s.first=true;duelReach(3);duelTell('');renderDuel();return;}
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
window.addEventListener('resize',()=>{closeDuelPreview();if(duelState().stage===5)layoutDuelGraph();});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){closeDuelPreview();return;}
  if(event.defaultPrevented||event.isComposing||event.target.closest('input,textarea,select,[contenteditable=true]')||document.querySelector('dialog[open]'))return;
  const action=Object.entries(duelUI.bindings).find(([,key])=>key&&key.toUpperCase()===duelAccelerator(event))?.[0];
  if(action&&moduleUI.current==='duel'&&duelState().stage===5&&duelState().enabled){event.preventDefault();duelNavigate(action);}
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
    const count=Number($('#duel-default-count').value);
    if(!Number.isInteger(count)||count<1||count>60)throw new Error('先攻起手张数必须是 1–60 之间的整数');
    const saved=window.trainerDesktop?.tutorialSaveSettings?await window.trainerDesktop.tutorialSaveSettings(bindings):{bindings};
    duelUI.bindings=saved.bindings;
    await api('/api/duel/settings',{hand_count:count});duelUI.handCount=count;
    const s=duelState();if(s.deck&&s.stage<=2&&s.count!==count){s.count=count;s.hand=Array(count).fill(null);s.target=null;invalidateDuel(2);}
    await closeDuelShortcuts();if(moduleUI.current==='duel')renderDuel();
  }catch(error){$('#duel-shortcut-error').textContent=error.message;}finally{button.disabled=false;}
};
window.trainerDesktop?.onTutorialAction(event=>{const s=duelState();if(event.session===s.session&&s.enabled)duelNavigate(event.action);});
window.trainerDesktop?.onTutorialStatus(status=>{if(status.session===duelState().session){duelUI.shortcutStatus=status;paintDuelShortcutStatus();}});

$('#toggle-duel-card-mark').onclick=()=>{
  const key=reviewUI.selected?.duel_mark_key,s=duelState();if(!key||duelUI.busy||s.stage!==1)return;
  s.marks.has(key)?s.marks.delete(key):s.marks.add(key);
  $('#duel-body').querySelectorAll('[data-duel-mark-key]').forEach(el=>el.classList.toggle('is-marked',s.marks.has(el.dataset.duelMarkKey)));
  updateDuelMarkButton();
};
$('#duel-preview').addEventListener('click',event=>{
  const button=event.target.closest('[data-duel-preview-mode]');if(!button)return;
  duelUI.detailPreview=button.dataset.duelPreviewMode==='detailed';paintDuelPreview();
});
$('#duel').addEventListener('contextmenu',event=>{
  if(duelUI.busy||duelState().stage!==3)return;
  const slot=event.target.closest('[data-duel-slot]'),candidate=event.target.closest('[data-duel-add]');
  if(!slot&&!candidate)return;event.preventDefault();event.stopPropagation();
  const s=duelState(),index=slot?Number(slot.dataset.duelSlot):s.hand.lastIndexOf(Number(candidate.dataset.duelAdd));
  if(index<0||!s.hand[index])return;
  s.hand[index]=null;s.target=null;invalidateDuel(3);closeReviewDetail();renderDuel();
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

$('#app-settings').onclick=run(openDuelShortcuts);

document.addEventListener('pointermove',event=>{
  const suppressed=duelUI.handHoverSuppressed;if(!suppressed)return;
  const r=suppressed.rect;if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)duelUI.handHoverSuppressed=null;
});
