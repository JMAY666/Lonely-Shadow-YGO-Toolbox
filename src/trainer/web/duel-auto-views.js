'use strict';
// Automatic-mode views own their DOM and state; card/report renderers are data-only utilities.

function autoDuelMatchesPage() {
  const s=autoDuelState(),result=s.result;if(!result)return '';
  // Score against the full matched set so a favorite filter never changes scores.
  const ranked=DuelModel.rankPlans(result.matches,s.planSort,duelPlanStepCount).filter(r=>!s.favoritesOnly||r.plan.favorite);
  return `<div class="auto-duel-section-heading"><h2>方案选择</h2><div class="auto-duel-actions">${autoDuelButton('modular','生成临时方案')}${autoDuelButton('rematch','刷新')}</div></div><div class="auto-duel-plan-filters"><label>方案排序 <select id="auto-duel-plan-sort">${[['shortest','步骤最少'],['largest','终场最大'],['balanced','平均值（均衡）']].map(([value,label])=>`<option value="${value}" ${s.planSort===value?'selected':''}>${label}</option>`).join('')}</select></label><button data-auto-duel-action="favorites-only" aria-pressed="${s.favoritesOnly}">★ 只看收藏</button><small>${ranked.length} / ${result.matches.length} 个方案</small></div><p class="auto-duel-sort-basis">终场只比较已标记卡牌数，再比较标记效果数。平均值为步骤得分与终场排名得分各占 50%，仅用于当前方案比较。</p><div class="auto-duel-plan-grid">${ranked.map(({plan,cards,effects,average})=>`<article class="auto-duel-plan-tile ${plan.favorite?'is-favorite':''}"><button class="auto-duel-plan" data-auto-duel-plan="${escape(plan.id)}"><span class="auto-duel-plan-heading"><strong>${escape(plan.name)}</strong>${duelPlanCounts(plan)}</span><small>${cards?`标记终场 ${cards} 张 · 效果 ${effects} 项`:'未标记有效终场'}${s.planSort==='balanced'?` · 平均 ${average.toFixed(1)}`:''}</small>${plan.expansion?.notes?`<span class="auto-duel-plan-note">${escape(plan.expansion.notes)}</span>`:''}<span class="auto-duel-tile-cards">${duelSummaryCards(plan,'opening',3)}</span><span class="auto-duel-tile-arrow" aria-hidden="true">↓</span><span class="auto-duel-tile-cards">${duelSummaryCards(plan,'final',4)||'<small>未标记终场卡牌</small>'}</span></button>${autoDuelFavoriteButton(plan)}</article>`).join('')||`<div class="auto-duel-empty"><h3>${escape(s.favoritesOnly?'当前匹配结果中没有收藏方案':result.reason||'暂无可用方案')}</h3>${s.favoritesOnly?autoDuelButton('favorites-only','查看全部方案'):autoDuelButton('opening','查看已确认起手')}</div>`}</div>`;
}

function autoDuelNodeSource(node) {
  const s=autoDuelState(),report=node.route==='main'?s.plan:s.plan.branches.find(b=>b.id===node.route)?.report;
  const nodes=reviewNodes(report);
  const recorded=nodes.find(n=>n.id===node.id)||nodes.find(n=>n.kind===node.id);
  return {report,node:recorded||{id:node.id,kind:node.id,action_ids:[],state:null}};
}

function autoDuelNodeDetail(node,mode='detailed') {
  const source=autoDuelNodeSource(node),edit=source.report.annotations?.nodes?.[source.node.id];
  return `<h3>${escape(node.label)} · ${escape(edit?.name||node.title||(node.id==='initial'?'起手':node.id==='final'?'终场':`Step ${node.number}`))}</h3>${edit?.notes?`<p class="preserve-lines">${escape(edit.notes)}</p>`:''}${renderRecordedStep(source.report,source.node,mode)}`;
}

function autoDuelGraphHtml() {
  const s=autoDuelState();
  return `<div id="auto-duel-graph-scroll" class="auto-duel-graph-scroll"><div class="auto-duel-graph-surface"><div class="auto-duel-graph"><svg aria-hidden="true"></svg>${s.graph.nodes.map(n=>`<article role="button" tabindex="0" data-auto-duel-node="${escape(n.key)}" class="auto-duel-node" aria-label="${escape(n.label)} ${n.id==='initial'?'起手':n.id==='final'?'终场':`Step ${n.number}`}"><small>${escape(n.label)} · ${n.id==='initial'?'起手':n.id==='final'?'终场':`Step ${n.number}`}</small><div class="auto-duel-node-log">${autoDuelNodeDetail(n,'compact')}</div><span class="auto-duel-current-dot" aria-hidden="true"></span></article>`).join('')}</div></div></div>`;
}

function layoutAutoDuelGraph() {
  const s=autoDuelState(),viewport=$('#auto-duel-graph-scroll'),canvas=viewport?.querySelector('.auto-duel-graph');if(!canvas)return;
  const available=Math.max(160,viewport.clientHeight-28),columns=[];
  const maximumWidth=Math.max(480,Math.min(900,viewport.clientWidth-32));
  for(const n of s.graph.nodes) {
    const el=canvas.querySelector(`[data-auto-duel-node="${CSS.escape(n.key)}"]`),actions=el.querySelectorAll('.auto-duel-node-log > .log-action').length;
    el.style.width='316px';el.style.setProperty('--node-action-columns','1');
    // Give a tall step more horizontal space before scaling the whole diagram.
    for(let width=416;el.offsetHeight>available&&width<=maximumWidth;width+=100) {
      el.style.width=width+'px';
      if(actions>1&&width>=516)el.style.setProperty('--node-action-columns',String(Math.min(actions,2)));
    }
    columns[n.column]=Math.max(columns[n.column]||0,el.offsetWidth+36);
  }
  const rows=s.routes.map((_,row)=>Math.max(120,...s.graph.nodes.filter(n=>n.row===row).map(n=>canvas.querySelector(`[data-auto-duel-node="${CSS.escape(n.key)}"]`).offsetHeight))+28);
  const scale=Math.min(1,(viewport.clientHeight-8)/Math.max(...rows));autoDuelView.graphScale=scale;
  const points=new Map();
  s.graph.nodes.forEach(n=>{
    const b=canvas.querySelector(`[data-auto-duel-node="${CSS.escape(n.key)}"]`),x=columns.slice(0,n.column).reduce((a,b)=>a+b,14),y=rows.slice(0,n.row).reduce((a,b)=>a+b,12);
    b.style.left=x+'px';b.style.top=y+'px';points.set(n.key,{x,y:y+36,width:b.offsetWidth});
  });
  const width=columns.reduce((a,b)=>a+b,14),height=rows.reduce((a,b)=>a+b,12),svg=canvas.querySelector('svg');
  canvas.style.width=width+'px';canvas.style.height=height+'px';svg.setAttribute('width',width);svg.setAttribute('height',height);
  canvas.style.transform=`scale(${scale})`;
  canvas.parentElement.style.width=width*scale+'px';canvas.parentElement.style.height=height*scale+'px';
  svg.innerHTML=`<defs><marker id="auto-duel-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10" fill="var(--accent)"/></marker></defs>`+s.graph.edges.map(e=>{const a=points.get(e.from),b=points.get(e.to);return `<path d="M${a.x+a.width} ${a.y}H${a.x+a.width+18}V${b.y}H${b.x-4}" fill="none" stroke="var(--accent)" stroke-width="1.5" ${e.branch?'stroke-dasharray="5 4"':''} marker-end="url(#auto-duel-arrow)"/>`;}).join('');
  const separator=$('#auto-duel-graph-resize');separator?.setAttribute('aria-valuenow',String(Math.round(viewport.offsetHeight)));
}

function resizeAutoDuelGraph(height) {
  const viewport=$('#auto-duel-graph-scroll');if(!viewport)return;
  autoDuelView.graphHeight=Math.max(200,Math.min(Math.max(1200,innerHeight*2),height));
  viewport.style.height=autoDuelView.graphHeight+'px';layoutAutoDuelGraph();
  focusAutoDuelPosition();
}

function mountAutoDuelGraphResize() {
  const viewport=$('#auto-duel-graph-scroll'),separator=$('#auto-duel-graph-resize');
  viewport.style.height=(autoDuelView.graphHeight||Math.max(300,Math.round(innerHeight*.45)))+'px';
  separator.setAttribute('aria-valuemax',String(Math.max(1200,innerHeight*2)));
  let drag;
  separator.onpointerdown=event=>{
    if(event.button!==0)return;event.preventDefault();closeAutoDuelPreview();closeReviewDetail();
    drag={id:event.pointerId,y:event.clientY,height:viewport.offsetHeight};separator.setPointerCapture(event.pointerId);
    document.body.classList.add('auto-duel-resizing');
  };
  separator.onpointermove=event=>{if(drag)resizeAutoDuelGraph(drag.height+event.clientY-drag.y);};
  const finish=()=>{drag=null;document.body.classList.remove('auto-duel-resizing');};
  separator.onpointerup=event=>{if(drag)resizeAutoDuelGraph(drag.height+event.clientY-drag.y);finish();};
  separator.onpointercancel=finish;separator.onlostpointercapture=finish;
  separator.ondblclick=()=>{autoDuelView.graphHeight=null;resizeAutoDuelGraph(Math.max(300,Math.round(innerHeight*.45)));};
  separator.onkeydown=event=>{
    if(!['ArrowUp','ArrowDown','Home','End'].includes(event.key))return;
    event.preventDefault();event.stopPropagation();
    resizeAutoDuelGraph(event.key==='Home'?200:event.key==='End'?Math.max(1200,innerHeight*2):viewport.offsetHeight+(event.key==='ArrowDown'?24:-24));
  };
}

function autoDuelTutorialPage() {
  const s=autoDuelState();
  return `<div class="auto-duel-section-heading"><h2>${escape(s.plan.name)}</h2><div class="auto-duel-actions">${autoDuelButton('toggle-shortcuts',s.enabled?'暂停快捷键':'启用快捷键')}${autoDuelButton('shortcuts','快捷键设置')}${autoDuelButton('modular',s.plan?.temporary?'重新生成后续':'生成展开后续')}</div></div><p id="auto-duel-shortcut-status" role="status"></p>${autoDuelGraphHtml()}<div id="auto-duel-graph-resize" class="auto-duel-graph-resize" role="separator" tabindex="0" aria-label="调整教程图高度" aria-orientation="horizontal" aria-valuemin="200" aria-valuemax="1800" title="拖动调整教程图高度；双击恢复默认"><span></span></div><div id="auto-duel-route-choice" class="auto-duel-route-choice"></div><article id="auto-duel-current-detail" class="auto-duel-current-detail"></article><div id="auto-duel-zone-content" class="review-zone-popover" role="dialog" aria-label="区域卡牌" hidden></div>`;
}

function focusAutoDuelPosition() {
  const viewport=$('#auto-duel-graph-scroll'),current=viewport?.querySelector('.auto-duel-node.current');if(!current)return;
  const scale=autoDuelView.graphScale||1;
  viewport.scrollLeft=Math.max(0,current.offsetLeft*scale-(viewport.clientWidth-current.offsetWidth*scale)/2);
  viewport.scrollTop=Math.max(0,current.offsetTop*scale-8);
}

function paintAutoDuelPosition(scroll=true) {
  const s=autoDuelState();if(s.stage!==duelStages.tutorial||!s.position)return;
  const graph=$('#auto-duel-graph-scroll');
  graph.querySelectorAll('[data-auto-duel-node]').forEach(button=>{
    const active=button.dataset.autoDuelNode===s.position.key;button.classList.toggle('current',active);button.setAttribute('aria-current',active?'step':'false');
  });
  if(scroll)focusAutoDuelPosition();
  const outgoing=s.graph.edges.filter(e=>e.from===s.position.key);
  $('#auto-duel-route-choice').hidden=outgoing.length<2;
  $('#auto-duel-route-choice').innerHTML=outgoing.length>1?outgoing.map((edge,i)=>`<button data-auto-duel-choice="${i}" aria-pressed="${i===(s.position.choice||0)}">${escape(edge.label)}</button>`).join(''):'';
  const current=s.graph.nodes.find(n=>n.key===s.position.key),source=autoDuelNodeSource(current),edit=source.report.annotations?.nodes?.[source.node.id];
  $('#auto-duel-current-detail').innerHTML=`<header><h3>${escape(current.label)} · ${escape(edit?.name||(current.id==='initial'?'初始手牌':current.id==='final'?'终场':`Step ${current.number}`))}</h3>${edit?.notes?`<p>${escape(edit.notes)}</p>`:''}</header><div class="review-board">${renderBoard(source.node,source.report)}</div>`;
  $('#auto-duel-zone-content').hidden=true;
  const edges=s.graph.edges;
  $('[data-auto-duel-action="back-step"]').disabled=!edges.some(e=>e.to===s.position.key);
  $('[data-auto-duel-action="forward-step"]').disabled=!outgoing.length;
  paintAutoDuelShortcutStatus();pruneReviewCards();
}

function showAutoDuelZone(key) {
  const s=autoDuelState(),current=s.graph.nodes.find(n=>n.key===s.position.key),{report,node}=autoDuelNodeSource(current),[side,zone]=key.split(':').map(Number),cards=boardCards(node,side,zone);
  const panel=$('#auto-duel-zone-content');panel.hidden=false;
  panel.innerHTML=`<section class="zone-contents"><button data-auto-duel-close-zone aria-label="关闭区域">×</button><h3>${escape(reviewPlace({controller:side,location:zone}))} · ${cards.length} 张</h3><div>${cards.map(c=>reviewCard(c,node.id,{report,name:true,face:reviewKnown(c)})).join('')||'当前区域为空'}</div></section>`;
}
