'use strict';

// Card popovers keep their own recorded node, so reading the log does not move
// the selected board. Live rewinding remains confined to timeline.js / the field.
const reviewUI = {report:null, nodes:[], node:null, selected:null, detailNode:null, detailReport:null, anchor:null, materialTab:false, detailHistory:[], detailPinned:false, zone:null, drawer:false, logMode:'compact', pending:null, cards:new Map(), serial:0};
const reviewHover = {openTimer:null,closeTimer:null,target:null,generation:0,suppressed:null};
const emptyEdits = () => ({version:1,nodes:{},cards:{},effects:{},costs:{},final_marks:{},conditions_note:'',extra_conditions:[]});
const reviewEdits = () => flow.draft?.annotations || reviewUI.report?.annotations || emptyEdits();
const reviewTitle = n => reviewEdits().nodes[n.id]?.name || (n.kind==='initial'?'初始手牌':n.kind==='final'?'终场结果':`Step ${n.number}`);
const reviewNode = () => reviewUI.nodes.find(n=>n.id===reviewUI.node);
const reviewMaterials = (n,c) => c.instance_id==null?[]:(n?.state?.cards||[]).filter(x=>x.overlay_target!=null&&x.overlay_target===c.instance_id);
const reviewDefinition = c => reviewUI.report?.catalog?.[c?.code] || {};
const reviewKnown = c => !!c?.code && c.identity_known!==false;
// Derive a display-only identity from draw evidence, never from card names.
// Frozen reports (including older saved plans) and their annotations stay intact.
const reviewDrawCache = new WeakMap();
function reviewRandomDraw(c,node=reviewNode(),report=reviewUI.report) {
  if(!report||c?.instance_id==null||!reviewKnown(c))return null;
  if(!reviewDrawCache.has(report)) {
    const draws=new Map(), initial=Number(String(report.initial_hand_ref||'0:0').split(':')[0]);
    for(const e of report.events||[]) {
      const seq=e.native_seq??Number(String(e.id).split(':')[0]);
      if(e.message!==90||e.id===report.initial_hand_ref||seq<=initial)continue;
      for(const card of e.cards||[])if(card.instance_id!=null&&card.controller===0) {
        const key=String(card.instance_id);if(!draws.has(key))draws.set(key,[]);
        draws.get(key).push({seq,event:e.id});
      }
    }
    reviewDrawCache.set(report,draws);
  }
  const n=node==='final'?{kind:'final'}:typeof node==='string'?(report.review?.nodes||reviewUI.nodes).find(n=>n.id===node):node;
  const refs=(n?.action_ids||[]).flatMap(id=>(report.actions||[]).find(a=>a.id===id)?.evidence_refs||[id]);
  const end=n?.kind==='final'?Infinity:n?.state_ref??n?.range?.[1]??Math.max(0,...refs.map(id=>Number(String(id).split(':')[0])||0));
  return reviewDrawCache.get(report).get(String(c.instance_id))?.find(d=>d.seq<=end)||null;
}
function reviewCardLabel(c,node,report=reviewUI.report) {
  return reviewRandomDraw(c,node,report)?'随机抽牌':reviewKnown(c)?c.name||report?.catalog?.[c.code]?.name||String(c.code):'未知卡牌';
}
function reviewDisplayText(text,cards,node) {
  for(const c of cards||[])if(c.name&&reviewRandomDraw(c,node))text=String(text||'').replaceAll(c.name,'随机抽牌');
  return text||'';
}
const reviewPlace = l => {
  if(!l)return '来源未记录';
  const who=l.controller===0?'我方':l.controller===1?'对方':'未知方';
  if(l.location&128)return `${who}素材`;
  if(l.location===4)return !Number.isInteger(l.sequence)||l.sequence<0?`${who}怪兽区（位置未记录）`:`${who} ${l.sequence>=5?`额外怪兽区 ${l.sequence-4}`:`${l.sequence+1} 号主怪兽区`}`;
  if(l.location===8&&l.sequence===5)return `${who}场地区`;
  if(l.location===8&&l.sequence>=6)return `${who}${l.sequence===6?'左':'右'}灵摆区`;
  return who+({1:'主卡组',2:'手牌',8:'魔法／陷阱区',16:'墓地',32:'除外区',64:'EX 额外卡组'}[l.location]||'未知区域');
};
function reviewFallback(r) {
  const nodes=[{id:'initial',kind:'initial',state:r.initial_hand?{partial:true,cards:r.initial_hand.map((c,i)=>({...c,controller:0,location:2,sequence:i}))}:null,action_ids:[]}];
  for(const a of r.actions||[])nodes.push({id:`step:${a.id}`,kind:'step',state:null,action_ids:[a.id]});
  const final=structuredClone(r.final_state);
  for(const c of final?.cards||[]) {
    if(c.controller===1&&(c.location===1||c.location===2||c.location===64&&!(c.position&5)||[4,8,32].includes(c.location)&&!!(c.position&10)))Object.assign(c,{code:null,name:'未知卡牌',identity_known:false});
  }
  nodes.push({id:'final',kind:'final',state:final,state_ref:r.final_state_ref,action_ids:[]});
  return nodes.map((n,i)=>({...n,number:i+1}));
}
function mountReview(r) {
  if(typeof adoptBranchRoot==='function' && !r._route)adoptBranchRoot(r);
  const changed=reviewUI.report?.id!==r.id;
  if(changed)closeReviewDetail();
  const editable=['draft','saved'].includes(r.plan_stage);
  if(editable && flow.draft?.id!==r.id) {
    const annotations={...emptyEdits(),...structuredClone(r.annotations||{})};
    flow.draft={id:r.id,saved:r.plan_stage==='saved',name:r.expansion?.name||r.name,notes:r.expansion?.notes||'',
      originalName:r.expansion?.name||r.name,originalNotes:r.expansion?.notes||'',annotations,
      originalAnnotations:JSON.stringify(annotations),originalRevision:r.edit_revision||0};
  } else if(!editable)flow.draft=null;
  const same=reviewUI.report?.record_count===r.record_count && reviewUI.report?.status===r.status && reviewUI.report?.edit_revision===r.edit_revision && reviewUI.report?.plan_stage===r.plan_stage && !changed;
  reviewUI.report=r;
  reviewUI.nodes=r.review?.nodes || reviewFallback(r);
  if(changed || !reviewUI.nodes.some(n=>n.id===reviewUI.node)) {
    reviewUI.node=reviewUI.nodes[0].id;reviewUI.selected=null;reviewUI.zone=null;reviewUI.pending=null;
  }
  $('#review-workspace').hidden=false;$('#report').hidden=true;$('#draft-editor').hidden=false;
  if(same && $('#review-steps'))return;
  renderReviewSidebar();renderReviewNode();renderReviewLog();pruneReviewCards();
}
function pruneReviewCards() {
  // Hidden plan summaries still have working card buttons when returning to
  // that page. Drop only entries whose buttons have actually been replaced.
  const live=new Set([...document.querySelectorAll('[data-review-card]')].map(b=>b.dataset.reviewCard));
  for(const key of reviewUI.cards.keys())if(!live.has(key))reviewUI.cards.delete(key);
}
function renderReviewSidebar() {
  const d=flow.draft, r=reviewUI.report;
  $('#draft-editor').innerHTML=`<div class="review-sidebar-head"><div class="eyebrow">CURRENT ROUTE</div><label for="draft-name">方案名称</label><input id="draft-name" maxlength="80" value="${escape(d?.name||r.name)}" ${d?'':'disabled'}><p class="review-stage">${escape(stageNames[r.plan_stage]||'原训练历史')}</p></div>
    <ol id="review-steps" class="review-steps">${reviewUI.nodes.map(n=>`<li><button data-review-node="${escape(n.id)}" ${n.id===reviewUI.node?'aria-current="step"':''}><small>Step ${n.number}</small><strong class="review-step-title">${escape(reviewTitle(n))}</strong><span>${n.kind==='initial'?'实际起手':n.kind==='final'?'展开结束时的状态':`${n.action_ids.length} 项操作`}</span></button></li>`).join('')}</ol>
    <label for="draft-notes">方案备注</label><textarea id="draft-notes" rows="3" maxlength="4000" ${d?'':'disabled'}>${escape(d?.notes||r.expansion?.notes||'')}</textarea>
    <p id="draft-message" role="status">${d?(d.saved?'正式方案的说明可继续编辑。':'确认存入前，当前内容仍为草稿。'):'此记录只读，原始数据保留。'}</p>
    <div class="review-sidebar-actions">${d?`<button id="save-plan" class="primary" ${r.status!=='completed'&&!d.saved?'disabled':''}>${d.saved?'保存修改':'保存方案'}</button><button id="delete-draft" class="danger">${d.saved?'删除方案':'放弃草稿'}</button>`:''}${r.expansion?'<button id="draft-conditions">以此条件再次展开</button>':''}</div>`;
  $('#review-workspace').classList.toggle('sidebar-collapsed',!!reviewUI.collapsed);
  if(!$('#review-sidebar-toggle'))$('#review-workspace').insertAdjacentHTML('beforeend','<button id="review-sidebar-toggle" class="review-sidebar-edge" aria-controls="draft-editor"></button>');
  const toggle=$('#review-sidebar-toggle'),label=reviewUI.collapsed?'展开步骤栏':'收起步骤栏';
  toggle.innerHTML=`<svg viewBox="0 0 16 24" aria-hidden="true"><path d="${reviewUI.collapsed?'M5 6l6 6-6 6':'M11 6l-6 6 6 6'}"/></svg>`;
  toggle.setAttribute('aria-expanded',String(!reviewUI.collapsed));toggle.setAttribute('aria-label',label);toggle.title=label;
  $('#review-sidebar-toggle').onclick=()=>{reviewUI.collapsed=!reviewUI.collapsed;renderReviewSidebar();};
  if(d) {
    $('#draft-name').oninput=e=>{d.name=e.target.value;$('#save-plan').disabled=!d.name.trim()||(r.status!=='completed'&&!d.saved);reviewUI.pending=null;};
    $('#draft-notes').oninput=e=>{d.notes=e.target.value;reviewUI.pending=null;};
    $('#save-plan').onclick=run(savePlan);$('#delete-draft').onclick=run(deleteDraft);
  }
  if($('#draft-conditions'))$('#draft-conditions').onclick=run(()=>reopenConditions(r.id));
  if(typeof mountBranchSidebar==='function')mountBranchSidebar();
}
function reviewCard(c, node=reviewUI.node, options={}) {
  const report=options.report||reviewUI.report;
  const key=String(++reviewUI.serial);reviewUI.cards.set(key,{card:c,node,report});
  const random=!!reviewRandomDraw(c,node,report), known=reviewKnown(c)&&!random, definition=known?report?.catalog?.[c.code]||{}:{}, location=options.location||c;
  const label=reviewCardLabel(c,node,report);
  const badLink=!!(definition.type&0x4000000) && !!(c.position&12);
  const defense=location.location===4&&!badLink&&!!(c.position&12), down=[4,8,32,64].includes(location.location)&&!!(c.position&10);
  const materials=options.materials;
  const position=location.location===4?(badLink?'状态待核对':![1,2,4,8].includes(c.position)?'表示未记录':down?'里侧':defense?'守备':'攻击'):'';
  return `<button class="review-card ${defense?'is-defense':''} ${materials?'has-materials':''} ${random?'random-card':known?'':'unknown-card'}" data-review-card="${key}" aria-haspopup="dialog" aria-label="${escape(label)}${options.catalogue?'':' · '+escape(reviewPlace(location))}">
    <span class="review-art"><img src="${known&&(!down||options.face)?`/pics/${Number(c.code)}.jpg`:'/review-back.svg'}" alt="${escape(label)}" loading="lazy">${down?'<span class="face-label">里侧</span>':''}${!known?`<span class="unknown-mark">${random?'随机':'?'}</span>`:''}</span>
    ${options.zone!==false?`<span class="region-badge side-${location.controller===1?'opponent':'self'}">${escape(reviewPlace(location))}</span>`:''}
    ${options.miniLocation&&[4,8].includes(location.location)?`<span class="compact-card-location">${reviewLocationIcon(location)}</span>`:''}
    ${position&&options.position!==false?`<span class="position-badge">${position}</span>`:''}${materials?`<span class="material-count">素材 ×${materials}</span>`:''}
    ${options.name?`<small>${escape(label)}</small>`:''}</button>`;
}
function selectReviewNode(id) {
  if(!reviewUI.nodes.some(n=>n.id===id))return;
  if(typeof closeBranchMenu==='function')closeBranchMenu(false);
  closeReviewDetail();
  reviewUI.node=id;reviewUI.selected=null;reviewUI.materialTab=false;reviewUI.zone=null;
  renderReviewSidebar();
  renderReviewNode();
  document.querySelectorAll('[data-review-node]').forEach(b=>{
    if(b.dataset.reviewNode===id)b.setAttribute('aria-current','step');else b.removeAttribute('aria-current');
  });
  scrollReviewLogTo(id);
  pruneReviewCards();
}
function boardCards(n, side, zone, seq) {
  return (n.state?.cards||[]).filter(c=>c.controller===side&&c.location===zone&&!c.overlay_target&&(seq===undefined||c.sequence===seq)).sort((a,b)=>a.sequence-b.sequence);
}
function boardSlot(n, side, zone, seq, label) {
  const cards=boardCards(n,side,zone,seq);
  return `<div class="board-slot ${zone===4?'monster-slot':'spell-slot'}"><span class="slot-label">${escape(label)}</span>${cards.map(c=>reviewCard(c,n.id,{zone:false,materials:reviewMaterials(n,c).length})).join('')||'<span class="vacant">—</span>'}</div>`;
}
function zoneStack(n, side, zone, label) {
  const cards=boardCards(n,side,zone);
  return `<button class="zone-stack side-${side===1?'opponent':'self'}" data-review-zone="${side}:${zone}"><span>${escape(label)}</span><span class="stack-art">${cards.length?`<img src="${zone===1||!reviewKnown(cards.at(-1))||reviewRandomDraw(cards.at(-1),n)?'/review-back.svg':`/pics/${Number(cards.at(-1).code)}.jpg`}" alt="">`:''}<strong>${n.state?.partial?'?':cards.length}</strong></span><small>查看区域</small></button>`;
}
function boardSide(n, side) {
  const opponent=side===1, related=n.opponent?.zones||[], show=z=>!opponent||related.includes(z);
  if(opponent && !related.some(z=>boardCards(n,side,z).length))return `<div class="opponent-board"><div class="board-side-label side-opponent">对方相关状态 <span>LP ${n.state?.lp?.[1]??'未知'}</span></div><p>已记录的相关区域为空。</p></div>`;
  return `<div class="board-side ${opponent?'opponent-board':'own-board'}"><div class="board-side-label side-${opponent?'opponent':'self'}">${opponent?'对方相关区域':'我方场面'} ${n.state?.lp?`<span>LP ${n.state.lp[side]}</span>`:''}</div>
    ${show(4)||show(8)?`<div class="board-row">${boardSlot(n,side,8,5,'场地区')}${Array.from({length:5},(_,i)=>boardSlot(n,side,4,i,`主怪兽 ${i+1}`)).join('')}${zoneStack(n,side,16,'墓地')}</div>
    <div class="board-row">${zoneStack(n,side,64,'EX 额外')}${Array.from({length:5},(_,i)=>boardSlot(n,side,8,i,i===0?'魔陷 1 / 左灵摆':i===4?'魔陷 5 / 右灵摆':`魔陷 ${i+1}`)).join('')}${zoneStack(n,side,1,'主卡组')}</div>`:''}
    <div class="board-resources">${show(32)?zoneStack(n,side,32,'除外区'):''}${!show(4)&&!show(8)?[16,64,1].filter(show).map(z=>zoneStack(n,side,z,zoneNames[z])).join(''):''}
    ${show(2)?`<div class="review-hand"><strong>${opponent?'对方':'当前'}手牌 · ${boardCards(n,side,2).length}</strong><div>${boardCards(n,side,2).map(c=>reviewCard(c,n.id,{zone:false,name:true,face:!opponent})).join('')||'<span class="vacant">空</span>'}</div></div>`:''}</div>
    ${boardCards(n,side,8).some(c=>c.sequence>=6)?`<div class="legacy-pendulum">${[6,7].map(i=>boardSlot(n,side,8,i,i===6?'记录中的左灵摆位':'记录中的右灵摆位')).join('')}</div>`:''}</div>`;
}
function renderBoard(n) {
  if(!n.state)return '<div class="review-unavailable">此节点未记录完整状态。原始动作仍可查看，不能用终场代替本步场面。</div>';
  const extra=(n.state.cards||[]).filter(c=>c.location===4&&c.sequence>=5&&!c.overlay_target);
  const shared=[0,1].map(i=>`<div class="board-slot shared-slot"><span class="slot-label">共享额外怪兽区 ${i+1}</span>${extra.filter(c=>(c.controller===0?c.sequence-5:6-c.sequence)===i).map(c=>reviewCard(c,n.id,{materials:reviewMaterials(n,c).length})).join('')||'<span class="vacant">—</span>'}</div>`).join('');
  const before=n.opponent?.before;
  return `${n.state.partial?'<p class="review-warning">旧记录只保存了初始手牌，其他区域数量未知。</p>':''}${n.opponent?.visible?`<div class="opponent-context">${n.opponent.reasons.map(escape).join('；')}${before?`<details><summary>本步动作前的对方状态 · 快照 ${before.state_ref}</summary><p>LP ${before.lp??'未知'}</p><div class="opponent-before-cards">${before.cards.map(c=>`<span>${reviewKnown(c)?`<img src="/pics/${Number(c.code)}.jpg" alt="">`:''}${escape(c.name)} · ${escape(reviewPlace(c))}</span>`).join('')||'相关区域当时为空。'}</div></details>`:''}</div>${boardSide(n,1)}`:''}<div class="shared-zones">${shared}</div>${boardSide(n,0)}`;
}
function renderReviewNode() {
  const n=reviewNode();if(!n)return;
  const editable=!!flow.draft, edit=reviewEdits().nodes[n.id]||{};
  const index=reviewUI.nodes.indexOf(n);
  $('#review-center').innerHTML=`<header class="review-node-header"><div><small>Step ${n.number} / ${reviewUI.nodes.length}</small><h2 id="current-node-title">${escape(reviewTitle(n))}</h2></div><div><button data-review-node="${escape(reviewUI.nodes[Math.max(0,index-1)].id)}" ${index===0?'disabled':''} aria-label="上一步">←</button><button data-review-node="${escape(reviewUI.nodes[Math.min(reviewUI.nodes.length-1,index+1)].id)}" ${index===reviewUI.nodes.length-1?'disabled':''} aria-label="下一步">→</button><button id="review-log-toggle" aria-controls="review-log" aria-expanded="${reviewUI.drawer}">${reviewUI.drawer?'收起':'展开'}日志</button></div></header>
    <p class="review-detail-help">悬停卡牌查看信息，点击可固定；素材详情可返回上一级。</p>
    <div class="review-board">${renderBoard(n)}</div><div id="review-zone-content" class="review-zone-popover" role="dialog" aria-label="区域卡牌" hidden></div>${n.kind==='final'?`<section id="review-final-marks" class="node-explanation">${reviewFinalCards(n)}</section>`:''}
    <div class="node-explanation"><label for="review-step-name">步骤名称 <small>留空使用默认名称</small></label><input id="review-step-name" maxlength="80" value="${escape(edit.name||'')}" ${editable?'':'disabled'}><label for="review-step-notes">${n.kind==='final'?'终场整体说明':'步骤备注'}</label><textarea id="review-step-notes" maxlength="4000" rows="3" ${editable?'':'disabled'} placeholder="操作目的、关键选择或注意事项">${escape(edit.notes||'')}</textarea>
    <p class="review-range">${n.range?`记录范围 ${n.range[0]??'?'}—${n.range[1]??'?'} · `:''}${escape(reviewUI.report.review?.boundary_note||'旧方案未保存逐步快照；缺失内容明确标为未知。')}</p></div>`;
  $('#review-log-toggle').onclick=()=>setReviewDrawer(!reviewUI.drawer);
  if(editable)for(const [id,field] of [['review-step-name','name'],['review-step-notes','notes']])$('#'+id).oninput=e=>{
    const edits=reviewEdits();edits.nodes[n.id]||={name:'',notes:''};edits.nodes[n.id][field]=e.target.value;reviewUI.pending=null;
    if(field==='name'){
      $('#current-node-title').textContent=reviewTitle(n);
      document.querySelector(`[data-review-node="${CSS.escape(n.id)}"] .review-step-title`).textContent=reviewTitle(n);
      document.querySelector(`[data-log-node="${CSS.escape(n.id)}"] .log-node-title`).textContent=reviewTitle(n);
    }
  };
}
function provenance(card,n,r=reviewUI.report) {
  if(!reviewKnown(card)||card.instance_id===undefined||card.instance_id===null)return [];
  const nodes=r.review?.nodes||(r===reviewUI.report?reviewUI.nodes:reviewFallback(r)), id=card.instance_id, end=n.state_ref??(n.kind==='final'?Infinity:0), result=[];
  if((r.initial_hand||[]).some(c=>c.instance_id===id))result.push({node:nodes[0]||n,text:'本次实际初始手牌'});
  for(const e of r.events||[]) {
    if(e.native_seq>end || !(e.cards||[]).some(c=>c.instance_id===id))continue;
    const owner=(r.actions||[]).find(a=>(a.evidence_refs||[]).includes(e.id));
    const ownerNode=nodes.find(x=>x.action_ids.includes(owner?.id))||nodes.find(x=>x.state_ref>=e.native_seq)||n;
    let text='';
    if(e.message===50) {
      const d=e.destination||{},o=e.origin||{};
      const verb=d.location&128?'成为素材':o.location&128?'取除／转移素材':d.location===16?'送墓':d.location===32?'除外':d.location===2&&o.location===1?'检索／加入手牌':d.location===2?'回收':'移动';
      text=`${e.cost?'费用：':''}从${reviewPlace(o)}${verb}至${reviewPlace(d)}`;
    } else if([61,63,65].includes(e.message)) {
      const c=owner?.cards?.find(c=>c.instance_id===id)||(e.cards||[]).find(c=>c.instance_id===id);
      text=`${c.summon_origin?`从${reviewPlace(c.summon_origin)}`:'来源未记录；'}${c.summon_method||({61:'通常召唤',63:'特殊召唤',65:'反转召唤'}[e.message])}至${reviewPlace(c)}`;
    } else if(e.message===90&&e.id!==r.initial_hand_ref)text=`从主卡组抽到手牌（${e.draw_kind==='effect'?'效果抽卡':e.draw_kind==='rule'?'规则抽卡':'原因未记录'}）`;
    if(text)result.push({node:ownerNode,text});
  }
  return result;
}
function renderReviewDetail() {
  const n=reviewUI.detailNode||reviewNode(), r=reviewUI.detailReport||reviewUI.report, c=reviewUI.selected;if(!c)return;
  const random=!!reviewRandomDraw(c,n,r), known=reviewKnown(c)&&!random, d=known?r.catalog?.[c.code]||{}:{}, materials=reviewMaterials(n,c), sources=provenance(c,n,r);
  const editable=app.view==='history'&&flow.draft?.id===r.id;
  const edits=flow.draft?.id===r.id&&['history','confirmation'].includes(app.view)?reviewEdits():r.annotations||emptyEdits();
  const annotation=n.kind==='final'&&c.instance_id!=null?edits.cards[String(c.instance_id)]||'':null;
  const stats=[];
  const attribute={1:'地',2:'水',4:'炎',8:'风',16:'光',32:'暗',64:'神'}[d.attribute];
  if(attribute)stats.push(attribute+'属性');
  if(known&&typeof cardType==='function')stats.push(cardType(d));
  const races=['战士','魔法使','天使','恶魔','不死','机械','水','炎','岩石','鸟兽','植物','昆虫','雷','龙','兽','兽战士','恐龙','鱼','海龙','爬虫类','念动力','幻神兽','创造神','幻龙','电子界','幻想魔'];
  if(d.type&1){const race=races.find((_,i)=>d.race===2**i);if(race)stats.push(race+'族');}
  if(d.type&1){stats.push(d.type&0x4000000?`LINK-${d.level&255}`:`${d.type&0x800000?'阶级':'等级'} ${d.level&255}`);stats.push(`ATK ${d.atk??'?'}`);if(!(d.type&0x4000000))stats.push(`DEF ${d.def??'?'}`);}
  if(d.type&0x1000000)stats.push(`灵摆刻度 ${(d.level>>>24)&255} / ${(d.level>>>16)&255}`);
  const parent=reviewUI.detailHistory.at(-1);
  if($('#review-detail-back')){$('#review-detail-back').hidden=!parent;$('#review-detail-back').textContent=parent?`← 返回${reviewCardLabel(parent.selected,parent.detailNode,parent.detailReport)}`:'返回上一级';}
  if($('#review-detail-mode'))$('#review-detail-mode').textContent=reviewUI.detailPinned?'已固定':'悬停预览';
  if($('#review-detail-pin'))$('#review-detail-pin').hidden=reviewUI.detailPinned;
  $('#review-card-detail').innerHTML=`<img class="detail-card-art" src="${known?`/pics/${Number(c.code)}.jpg`:'/review-back.svg'}" alt="${escape(reviewCardLabel(c,n,r))}"><div class="detail-card-copy"><div class="detail-name"><h3>${escape(reviewCardLabel(c,n,r))}</h3><small>${known?`卡号 ${c.code}`:random?'随机抽到的 1 张牌':'身份未记录'}</small></div><p>${escape(stats.join(' · '))}</p>
    ${materials.length||d.type&0x800000?`<div class="detail-tabs"><button id="review-body-tab" aria-pressed="${!reviewUI.materialTab}">本体</button><button id="review-material-tab" aria-pressed="${reviewUI.materialTab}">素材 ×${materials.length}</button></div>`:''}
    ${reviewUI.materialTab?`<div class="material-list">${materials.map(m=>reviewCard(m,n.id,{name:true,face:reviewKnown(m),report:r})).join('')||'<p>当前没有素材。</p>'}</div>`:`<p class="detail-effect">${escape(known?d.desc||'本次记录未保存完整效果文本。':random?'本次由抽卡获得，路线中以随机卡背表示，不作为指定检索结果。实际使用的指定随机命中仍会列入随机依赖。':'当前节点未记录可公开的卡牌身份。')}</p><div class="card-provenance"><strong>截至本步的来源与移动</strong>${sources.length?sources.map(s=>`<p>${app.view==='history'&&r===reviewUI.report?`<button data-review-node="${escape(s.node.id)}">Step ${s.node.number}</button>`:`Step ${s.node.number}`} ${escape(s.text)}</p>`).join(''):'<p>来源未记录</p>'}</div>`}
    ${annotation!==null?reviewMarkEditor(c,d,edits,editable):''}${annotation!==null?`<label for="review-card-note">终场此卡说明 <small>关联本次卡牌实例</small></label><textarea id="review-card-note" rows="2" maxlength="4000" ${editable?'':'disabled'}>${escape(annotation)}</textarea>`:''}</div>`;
  if($('#review-body-tab'))$('#review-body-tab').onclick=()=>{reviewUI.materialTab=false;renderReviewDetail();};
  if($('#review-material-tab'))$('#review-material-tab').onclick=()=>{reviewUI.materialTab=true;renderReviewDetail();};
  if($('#review-card-detail .card-provenance'))$('#review-card-detail .card-provenance').hidden=n.kind==='catalog';
  bindReviewMarks(c,edits,editable);
  if($('#review-card-note')&&editable)$('#review-card-note').oninput=e=>{edits.cards[String(c.instance_id)]=e.target.value;reviewUI.pending=null;refreshFinalMarks();};
  $('#review-card-popover').hidden=false;positionReviewDetail();
}
function cancelReviewHover() {
  clearTimeout(reviewHover.openTimer);clearTimeout(reviewHover.closeTimer);
  reviewHover.openTimer=reviewHover.closeTimer=null;reviewHover.target=null;reviewHover.generation++;
}
function pinReviewDetail() {
  cancelReviewHover();reviewUI.detailPinned=true;
  if($('#review-detail-mode'))$('#review-detail-mode').textContent='已固定';
  if($('#review-detail-pin'))$('#review-detail-pin').hidden=true;
}
function openReviewDetail(button,{hover=false}={}) {
  const item=reviewUI.cards.get(button.dataset.reviewCard);if(!item)return;
  const inside=!!button.closest('#review-card-popover');
  if(hover&&reviewUI.detailPinned&&!inside)return;
  const r=(app.view==='history'&&item.report?.id===reviewUI.report?.id?reviewUI.report:item.report)||reviewUI.report;
  const nodes=r.review?.nodes||(r===reviewUI.report?reviewUI.nodes:reviewFallback(r));
  const n=nodes.find(n=>n.id===item.node);if(!n)return;
  const current=(n.state?.cards||[]).find(c=>c.instance_id!=null&&c.instance_id===item.card.instance_id)||item.card;
  cancelReviewHover();
  reviewHover.suppressed=null;
  if(inside&&reviewUI.selected) {
    // Keep the original board/log anchor. The clicked material button is about
    // to be replaced and must never become the anchor for scroll/dismiss logic.
    reviewUI.detailHistory.push({selected:reviewUI.selected,detailNode:reviewUI.detailNode,detailReport:reviewUI.detailReport,materialTab:reviewUI.materialTab});
    reviewUI.detailPinned=true;
  } else {
    reviewUI.detailHistory=[];reviewUI.detailPinned=!hover;
    reviewUI.anchor={element:button,rect:button.getBoundingClientRect()};
  }
  reviewUI.selected=current;reviewUI.detailNode=n;reviewUI.detailReport=r;reviewUI.materialTab=false;
  renderReviewDetail();
  if(!hover)$('#review-card-popover').focus({preventScroll:true});
}
function backReviewDetail() {
  const parent=reviewUI.detailHistory.pop();if(!parent)return;
  pinReviewDetail();Object.assign(reviewUI,parent);renderReviewDetail();
  $('#review-card-popover').focus({preventScroll:true});
}
function scheduleReviewHover(button) {
  if(reviewHover.suppressed===button)return;
  if(reviewUI.detailPinned&&!button.closest('#review-card-popover'))return;
  if(reviewHover.target===button)return;
  cancelReviewHover();reviewHover.target=button;
  const generation=reviewHover.generation;
  reviewHover.openTimer=setTimeout(()=>{
    if(generation!==reviewHover.generation||!button.isConnected||!button.matches(':hover'))return;
    openReviewDetail(button,{hover:true});
  },400);
}
function scheduleReviewDetailClose() {
  clearTimeout(reviewHover.openTimer);reviewHover.openTimer=null;reviewHover.target=null;reviewHover.generation++;
  if(reviewUI.detailPinned)return;
  clearTimeout(reviewHover.closeTimer);
  reviewHover.closeTimer=setTimeout(()=>{
    if(!reviewUI.detailPinned&&!$('#review-card-popover')?.matches(':hover')&&!reviewUI.anchor?.element?.matches(':hover'))closeReviewDetail();
  },220);
}
function positionReviewDetail() {
  const panel=$('#review-card-popover'), a=reviewUI.anchor?.rect;if(!panel||panel.hidden||!a)return;
  const gap=12, width=panel.offsetWidth, height=panel.offsetHeight;
  let left=a.right+gap, top=a.top;
  if(left+width>innerWidth-gap)left=a.left-width-gap;
  if(left<gap){left=a.left;top=a.bottom+gap;if(top+height>innerHeight-gap)top=a.top-height-gap;}
  panel.style.left=`${Math.max(gap,Math.min(left,innerWidth-width-gap))}px`;
  panel.style.top=`${Math.max(gap,Math.min(top,innerHeight-height-gap))}px`;
}
function closeReviewDetail(focus=false) {
  if(focus)reviewHover.suppressed=reviewUI.anchor?.element;
  cancelReviewHover();
  const panel=$('#review-card-popover');if(panel)panel.hidden=true;
  if(focus&&reviewUI.anchor?.element?.isConnected)reviewUI.anchor.element.focus({preventScroll:true});
  reviewUI.selected=null;reviewUI.anchor=null;reviewUI.detailNode=null;reviewUI.detailReport=null;reviewUI.detailHistory=[];reviewUI.detailPinned=false;
}
function reviewOperation(item,node,role='处理结果') {
  const e=(reviewUI.report.events||[]).find(e=>e.id===(item.event_ref||item.id))||item;
  const cards=item.cards||e.cards||[], dest=e.destination, origin=e.origin;
  const names={50:dest?.location===16?'送墓':dest?.location===32?'除外':dest?.location&128?'成为素材':dest?.location===2&&origin?.location===1?'检索':dest?.location===2?'回收':'移动',53:'改变表示',54:'盖放',61:'通常召唤',63:'特殊召唤',65:'反转召唤',90:'抽卡',100:'支付 LP'};
  const method=cards.find(c=>c.summon_method)?.summon_method||names[e.message]||'操作';
  const materials=cards.flatMap(c=>c.materials||[]);
  return `<div class="log-operation"><small class="log-role">${escape(role)}</small><div class="log-flow">${materials.length?materials.map(c=>reviewLogCard(c,node,{name:true})).join('<b>＋</b>'):cards.map(c=>reviewLogCard(c,node,{name:true,location:origin||c.summon_origin||c})).join('')}<span class="log-arrow">→<em>${escape(method)}</em>→</span>${materials.length?cards.map(c=>reviewLogCard(c,node,{name:true,materials:reviewMaterials(reviewUI.nodes.find(n=>n.id===node),c).length})).join(''):`<span class="log-destination">${escape(dest?reviewPlace(dest):[61,63,65].includes(e.message)&&cards[0]?reviewPlace(cards[0]):e.message===90?'手牌':reviewDisplayText(item.text||e.result,cards,node)||'见实际记录')}</span>`}</div>
    <p class="log-summary">${escape(reviewDisplayText(item.text||eventSummary({...e,cards}),[...cards,...materials],node))}</p>${materials.length?`<p class="log-summary">${method==='超量召唤'?'参与卡牌成为结果怪兽的素材；当前数量以本步场面为准。':'参与卡牌的去向依下方记录，不能视作叠放素材。'}</p>`:''}</div>`;
}
function reviewLogCard(c,node,options={}) { return reviewCard(c,node,{name:true,face:reviewKnown(c),...options}); }
function compactLocation(l) {
  return l&&![4,8].includes(l.location)?`<span class="compact-location">${escape(reviewPlace(l))}</span>`:'';
}
function compactOperation(item,node,role='') {
  const e=(reviewUI.report.events||[]).find(e=>e.id===(item.event_ref||item.id))||item;
  const cards=item.cards||e.cards||[], dest=e.destination, origin=e.origin;
  const method=cards.find(c=>c.summon_method)?.summon_method||({50:dest?.location===16?'送墓':dest?.location===32?'除外':dest?.location&128?'成为素材':dest?.location===2&&origin?.location===1?'检索':dest?.location===2?'回收':'移动',53:'改变表示',54:'盖放',61:'通常召唤',63:'特殊召唤',65:'反转召唤',90:'抽卡',100:'支付 LP'}[e.message])||'处理结果';
  const materials=cards.flatMap(c=>c.materials||[]), opts={name:true,zone:false,position:false,miniLocation:true};
  const pictures=cs=>cs.map(c=>reviewLogCard(c,node,opts)).join('<b>＋</b>');
  const destination=dest?reviewPlace(dest):[61,63,65,54].includes(e.message)&&cards[0]?reviewPlace(cards[0]):e.message===90?'我方手牌':'';
  if(materials.length)return `<div class="compact-summon"><div class="compact-cards">${pictures(materials)}</div><span class="chain-arrow">→</span><div class="chain-stage"><small class="log-role">${escape(method)}</small><div class="compact-cards">${cards.map(c=>reviewLogCard(c,node,{...opts,materials:reviewMaterials(reviewUI.nodes.find(n=>n.id===node),c).length})).join('')}</div>${cards.map(c=>compactLocation(c)).join('')}</div></div>`;
  const places=destination?[compactLocation(origin),compactLocation(dest||cards[0]||{controller:0,location:2})].filter(Boolean):[];
  return `<div class="chain-stage"><small class="log-role">${escape(role?`${role} · ${method}`:method)}</small><div class="compact-cards">${pictures(cards)}</div>${places.length?`<small class="compact-destination">${places.join('<span class="chain-arrow">→</span>')}</small>`:''}${!cards.length?`<p>${escape(item.text||e.result||eventSummary(e)||'处理结果未记录')}</p>`:''}</div>`;
}
function compactLogAction(a,n) {
  const stages=[], opts={name:true,zone:false,position:false,miniLocation:true};
  if(a.kind==='effect') {
    stages.push(`<div class="chain-stage"><small class="log-role">${escape(cardActivation(a,reviewUI.report)||`发动效果${a.effect_number?` ${Number(a.effect_number)}`:''}`)}</small><div class="compact-cards">${(a.cards||[]).map(c=>reviewLogCard(c,n.id,opts)).join('')}</div></div>`);
    stages.push(...(a.costs||[]).map(s=>compactOperation(s,n.id,'Cost')));
    if(a.targets?.length)stages.push(`<div class="chain-stage"><small class="log-role">对象</small><div class="compact-cards">${a.targets.map(c=>reviewLogCard(c,n.id,opts)).join('')}</div></div>`);
    stages.push(...(a.results||[]).map(s=>compactOperation(s,n.id)));
    return `<div class="compact-chain">${stages.join('<span class="chain-arrow">→</span>')}</div>${a.status!=='resolved'?`<p class="effect-status status-${escape(a.status)}">${escape(({pending:'已发动 · 尚未确认结算',negated:'发动被无效',disabled:'效果被无效'}[a.status])||a.status_label||'状态未记录')}</p>`:''}${activationResultMissing(a,reviewUI.report)?'<p>处理结果未记录；不能由发动推断成功生效。</p>':''}${reviewEdits().effects[a.id]?`<p class="preserve-lines">用户说明：${escape(reviewEdits().effects[a.id])}</p>`:''}`;
  }
  const e=(reviewUI.report.events||[]).find(e=>e.id===a.id)||{};
  return `<div class="compact-chain">${compactOperation({...e,cards:a.cards,text:a.summary},n.id,a.kind==='cost'?'Cost':'')}</div>`;
}
function reviewLogAction(a,n) {
  const events=(a.evidence_refs||[]).map(id=>(reviewUI.report.events||[]).find(e=>e.id===id)).filter(Boolean);
  const activation=cardActivation(a,reviewUI.report);
  const title=a.kind==='effect'?(activation?`${activation}－${(a.cards||[]).map(c=>reviewCardLabel(c,n,reviewUI.report)).join('、')}`:'效果发动'):a.cards?.find(c=>c.summon_method)?.summon_method||a.summary;
  let body='';
  if(reviewUI.logMode==='compact'&&compactCleanup(a))return '';
  if(reviewUI.logMode==='compact')body=compactLogAction(a,n);
  else if(a.kind==='effect') {
    const specific=!activation&&a.selected_effect_text&&a.effect_text_source!=='unknown';
    const effectLabel=activation|| (specific?`${a.effect_number?`效果 ${a.effect_number} · `:''}${a.selected_effect_text.slice(0,48)}`:'具体效果待补充');
    const tip=`effect-tip-${n.number}-${String(a.id).replaceAll(':','-')}`;
    body=`<div class="log-flow">${(a.cards||[]).map(c=>reviewLogCard(c,n.id,{name:true})).join('')}<span class="effect-hint"><button type="button" aria-describedby="${tip}">${escape(effectLabel)}</button><span id="${tip}" role="tooltip">${escape(specific?a.selected_effect_text:(activation?'卡片本身的发动。完整卡片文本：\n':'具体发动效果尚未核实。完整卡片文本：\n')+(a.effect_text||'未记录'))}</span></span></div>
      <p class="effect-status status-${escape(a.status)}">${escape(({pending:'已发动 · 尚未确认结算',negated:'发动被无效',disabled:'效果被无效',resolved:'结算已完成 · 实际结果见下方'}[a.status])||a.status_label||'状态未记录')}</p>
      ${(a.costs||[]).map(s=>reviewOperation(s,n.id,'费用 Cost')).join('')}
      ${a.targets?.length?`<div class="log-operation"><small class="log-role">对象</small><div class="log-flow">${a.targets.map(c=>reviewLogCard(c,n.id,{name:true})).join('')}</div></div>`:''}
      ${(a.results||[]).map(s=>reviewOperation(s,n.id)).join('')||(activationResultMissing(a,reviewUI.report)?'<p>处理结果未记录；不能由发动推断成功生效。</p>':'<p>卡片发动已结算，未记录额外动作。</p>')}
      ${!specific?`<label class="log-user-note">用户补充说明<textarea data-effect-note="${escape(a.id)}" maxlength="4000" rows="2" ${flow.draft?'':'disabled'}>${escape(reviewEdits().effects[a.id]||'')}</textarea></label>`:reviewEdits().effects[a.id]?`<p>用户说明：${escape(reviewEdits().effects[a.id])}</p>`:''}`;
  } else {
    const e=events.find(e=>e.id===a.id)||events.at(-1)||{};
    body=reviewOperation({...e,cards:a.cards,text:a.summary},n.id,a.kind==='cost'?'费用 Cost':'操作');
    // XYZ already shows material transfer on the summon itself. Other summon
    // methods expose their individual destinations only in detailed mode.
    const xyz=a.cards?.some(c=>c.summon_method==='超量召唤');
    const materials=xyz?[]:events.filter(e=>e.material_method || ((e.reason||0)&8));
    if(materials.length)body+=`<div class="log-materials"><small class="log-role">素材去向</small>${materials.map(e=>reviewOperation(e,n.id,'')).join('')}</div>`;
  }
  return `<article class="log-action ${reviewUI.logMode==='compact'?'log-compact':''}" data-review-action="${escape(a.id)}"><h4>${escape(reviewDisplayText(title,a.cards,n))}</h4>${body}<details><summary>查看记录依据 · ${events.length} 条</summary>${events.map(e=>`<p>${escape(e.id)} · ${escape(eventSummary(e))}</p>`).join('')}</details></article>`;
}
function renderReviewLog() {
  const actions=new Map((reviewUI.report.actions||[]).map(a=>[a.id,a]));
  $('#review-log').innerHTML=`<header><h3>展开日志</h3><div class="log-mode" role="group" aria-label="日志显示方式"><button data-log-mode="compact" aria-pressed="${reviewUI.logMode==='compact'}">简略</button><button data-log-mode="detailed" aria-pressed="${reviewUI.logMode==='detailed'}">详细</button></div><button id="review-log-close">收起</button></header><div class="log-scroll">${reviewUI.nodes.map(n=>`<section class="log-node" data-log-node="${escape(n.id)}"><button class="log-node-heading" data-review-node="${escape(n.id)}"><small>Step ${n.number}</small><strong class="log-node-title">${escape(reviewTitle(n))}</strong></button>${n.kind==='initial'?`<div class="compact-cards">${(reviewUI.report.initial_hand||boardCards(n,0,2)).map(c=>reviewLogCard(c,n.id,{zone:false})).join('')}</div>`:n.kind==='final'?reviewFinalCards(n,reviewUI.report,reviewEdits(),{compact:reviewUI.logMode==='compact'}):''}${n.action_ids.map(id=>actions.get(id)).filter(Boolean).map(a=>reviewLogAction(a,n)).join('')||`<p>${n.kind==='initial'?'开始展开时的实际手牌。':n.kind==='final'?'结束后的最终状态与逐卡说明。':'本节点无额外操作。'}</p>`}</section>`).join('')}
    <details class="review-evidence"><summary>完整报告与原始事件</summary><label><input id="all-events" type="checkbox">查看原始事件</label><a href="/api/raw/${escape(reviewUI.report.id)}" target="_blank">原始记录 JSONL</a><div id="review-raw-events"></div></details></div>`;
  $('#review-log-close').onclick=()=>setReviewDrawer(false);
  $('#review-log-edge-toggle').onclick=()=>setReviewDrawer(!reviewUI.drawer);
  $('#review-log').querySelectorAll('[data-log-mode]').forEach(b=>b.onclick=()=>setReviewLogMode(b.dataset.logMode));
  $('#all-events').onchange=e=>{$('#review-raw-events').innerHTML=e.target.checked?(reviewUI.report.events||[]).map(e=>`<details><summary>${escape(e.type)}</summary><pre>${escape(JSON.stringify(e,null,2))}</pre></details>`).join(''):'';};
  $('#review-log').querySelectorAll('[data-effect-note]').forEach(t=>t.oninput=e=>{reviewEdits().effects[t.dataset.effectNote]=e.target.value;reviewUI.pending=null;});
  setReviewDrawer(reviewUI.drawer,false);
  pruneReviewCards();
}
function setReviewDrawer(open,focus=true) {
  if(!reviewUI.refreshingMarks)closeReviewDetail();
  reviewUI.drawer=open;$('#review-log').hidden=!open;$('#review-workspace').classList.toggle('log-open',open);
  const b=$('#review-log-toggle');if(b){b.textContent=open?'收起日志':'展开日志';b.setAttribute('aria-expanded',String(open));}
  const edge=$('#review-log-edge-toggle');if(edge){edge.textContent=open?'收起日志':'展开日志';edge.setAttribute('aria-expanded',String(open));}
  if(open)scrollReviewLogTo(reviewUI.node);
  if(!open&&focus)edge?.focus({preventScroll:true});
}
function scrollReviewLogTo(id) {
  const scroller=$('#review-log .log-scroll'), node=document.querySelector(`[data-log-node="${CSS.escape(id)}"]`);
  if(!scroller||!node||!reviewUI.drawer)return;
  const top=node.getBoundingClientRect().top-scroller.getBoundingClientRect().top;
  if(top<0||top>scroller.clientHeight-60)scroller.scrollTop+=top;
}
function setReviewLogMode(mode) {
  if(!['compact','detailed'].includes(mode)||mode===reviewUI.logMode)return;
  const scroll=$('#review-log .log-scroll'), top=scroll.getBoundingClientRect().top;
  const anchor=[...scroll.querySelectorAll('.log-action')].find(a=>a.getBoundingClientRect().bottom>top);
  const offset=anchor?anchor.getBoundingClientRect().top-top:0, id=anchor?.dataset.reviewAction;
  reviewUI.logMode=mode;renderReviewLog();
  if(id){const next=document.querySelector(`[data-review-action="${CSS.escape(id)}"]`), s=$('#review-log .log-scroll');if(next)s.scrollTop+=next.getBoundingClientRect().top-s.getBoundingClientRect().top-offset;}
}
function requirementRows(items=[], nodes=reviewUI.nodes) {
  return items.length?`<div class="requirement-grid">${items.map(item=>`<div class="requirement-card"><span class="requirement-art"><img src="${item.code?`/pics/${Number(item.code)}.jpg`:'/review-back.svg'}" alt="">${item.code?'':'<b>?</b>'}</span><div><strong>${escape(item.name)} ×${item.count}</strong><small>${escape(item.status||'已记录使用')}</small><p>${(item.nodes||[]).map(id=>{const n=nodes.find(n=>n.id===id);return n?`Step ${n.number}`:'步骤待核对';}).join('、')}</p><details><summary>用途与依据</summary>${(item.uses||[]).map(s=>`<p>${escape(s)}</p>`).join('')}</details></div></div>`).join('')}</div>`:'<p class="requirement-empty">未识别到指定资源；请核对记录及补充条件。</p>';
}
function summaryHtml(summary, savedPlan=null) {
  const edits=savedPlan?.annotations||reviewEdits();
  const nodes=savedPlan?.review?.nodes||reviewUI.nodes;
  return `<section class="confirmation-section"><h2>起手条件</h2>${requirementRows(summary.opening,nodes)}<p>任意牌的必要数量必须满足；身份不限不代表可以省略。</p></section>
    <section class="confirmation-section"><h2>展开使用资源</h2><h3>主卡组</h3>${requirementRows(summary.main,nodes)}<h3>EX 额外卡组</h3>${requirementRows(summary.extra,nodes)}</section>
    <section class="confirmation-section"><h2>随机依赖</h2>${summary.random?.length?`${requirementRows(summary.random,nodes)}<p class="review-warning">本路线依赖途中抽到指定卡牌，不属于已验证的稳定展开。</p>`:'<p>未识别到已使用的指定随机命中。</p>'}</section>
    <section class="confirmation-section"><h2>终场摘要</h2>${reviewFinalCards({id:'final',state:(savedPlan||reviewUI.report).review?.nodes?.find(n=>n.kind==='final')?.state||(savedPlan||reviewUI.report).final_state},savedPlan||reviewUI.report,edits,{compact:!savedPlan})}${summary.final?.notes?`<p class="preserve-lines">${escape(summary.final.notes)}</p>`:''}</section>
    <p class="review-warning">${escape(summary.basis||'按本次实际记录统计')}${(summary.warnings||[]).map(w=>'<br>'+escape(w)).join('')}</p>${summary.note?`<p class="preserve-lines">用户核对说明：${escape(summary.note)}</p>`:''}`;
}
async function previewReview() {
  if(typeof prepareBranchSave==='function' && !await prepareBranchSave())return;
  if(flow.busy||!flow.draft)return;
  flow.busy=true;$('#save-plan').disabled=true;
  const d=flow.draft;
  try {
    const payload={id:d.id,name:d.name,notes:d.notes,annotations:structuredClone(d.annotations),original_name:d.originalName,original_notes:d.originalNotes,original_revision:d.originalRevision};
    const preview=await api('/api/plans/preview',payload);
    if(flow.draft!==d)return;
    if(d.name!==payload.name||d.notes!==payload.notes||JSON.stringify(d.annotations)!==JSON.stringify(payload.annotations)) {
      $('#draft-message').textContent='编辑内容已更新，请再次点击保存生成最新摘要。';return;
    }
    // A previous save may have committed even though its response was lost.
    // Re-entering confirmation then updates that plan instead of dropping edits
    // through the create endpoint's idempotent response.
    if(preview.saved&&!d.saved) {
      d.saved=true;d.originalName=preview.original_name;d.originalNotes=preview.original_notes;d.originalRevision=preview.edit_revision;
      Object.assign(payload,{original_name:d.originalName,original_notes:d.originalNotes,original_revision:d.originalRevision});
    }
    reviewUI.pending={...preview,payload:{...payload,name:preview.name,notes:preview.notes,annotations:preview.annotations,confirmation:preview.confirmation},saved:d.saved};
    renderConfirmation();switchView('confirmation');
  } catch(e){$('#draft-message').textContent=`无法进入保存确认：${e.message}。当前内容已保留。`;throw e;}
  finally {flow.busy=false;if($('#save-plan'))$('#save-plan').disabled=!flow.draft?.name.trim();}
}
function renderConfirmation() {
  const p=reviewUI.pending;if(!p)return;
  const costs=p.requirements.cost_candidates||{};
  $('#save-confirmation').innerHTML=`<header><div class="eyebrow">04 / CONFIRM & SAVE</div><h1>保存前确认</h1><h2>${escape(p.name)}</h2><p>核对路线资源、起手条件和终场。确认成功后存入展开管理。</p></header>${summaryHtml(p.requirements)}
    <details class="confirmation-section" id="condition-editor"><summary>人工核对费用与补充条件</summary><p>用户核对内容单独保存，不修改本次实际卡牌身份。</p>
      ${Object.entries(costs).map(([key,c])=>`<div class="cost-check"><img src="/pics/${Number(c.card.code)}.jpg" alt=""><div><strong>${escape(c.card.name)}</strong><p>${escape(c.text)}</p><label>费用身份<select data-cost-mode="${escape(key)}" ${c.replaceable?'':'disabled'}><option value="specific" ${!(reviewEdits().costs[key]?.mode==='any'||!reviewEdits().costs[key]&&c.automatic)?'selected':''}>指定此卡</option><option value="any" ${reviewEdits().costs[key]?.mode==='any'||!reviewEdits().costs[key]&&c.automatic?'selected':''}>任意符合费用条件的牌</option></select></label><label>限制说明<input data-cost-constraint="${escape(key)}" maxlength="300" value="${escape(reviewEdits().costs[key]?.constraint||c.constraint)}" ${c.replaceable?'':'disabled'}></label>${c.replaceable?'':'<p>此卡身份在路线中仍有其他用途，不能简化为任意牌。</p>'}</div></div>`).join('')}
      <label for="condition-note">条件核对说明</label><textarea id="condition-note" rows="3" maxlength="4000">${escape(reviewEdits().conditions_note||'')}</textarea>
      <div class="extra-conditions">${reviewEdits().extra_conditions.map((c,i)=>`<p>用户补充：${escape(c.constraint)} ×${c.count} <button data-remove-condition="${i}">移除</button></p>`).join('')}</div>
      <div class="condition-add"><label>类型<select id="condition-kind"><option value="opening">起手条件</option><option value="resource">展开使用资源</option><option value="random">随机依赖</option></select></label><label>卡牌<select id="condition-card"><option value="">任意符合条件的牌</option>${Object.entries(reviewUI.report.catalog||{}).map(([code,c])=>`<option value="${Number(code)}">${escape(c.name)}</option>`).join('')}</select></label><label>数量<input id="condition-count" type="number" min="1" max="60" value="1"></label><label>关联步骤<select id="condition-node">${reviewUI.nodes.map(n=>`<option value="${escape(n.id)}">Step ${n.number} · ${escape(reviewTitle(n))}</option>`).join('')}</select></label><label>条件及用途<input id="condition-text" maxlength="300"></label><button id="add-condition">添加补充条件</button></div>
      <button id="refresh-confirmation">重新生成确认摘要</button><p id="condition-status" role="status"></p></details>
    <footer class="confirmation-footer"><p id="confirmation-message" role="status">取消确认不会产生正式方案。</p><button id="back-to-review">返回修改</button><button id="confirm-save-plan" class="primary">${p.saved?'确认保存修改':'确认存入展开管理'}</button></footer>`;
  $('#back-to-review').onclick=()=>{if(flow.saving)return;reviewUI.pending=null;switchView('history');renderReviewSidebar();renderReviewNode();renderReviewLog();};
  $('#confirm-save-plan').onclick=run(confirmReviewSave);
  if(p.branches?.length && typeof branchPremises==='function')$('#save-confirmation .confirmation-footer').insertAdjacentHTML('beforebegin',
    `<section class="confirmation-section"><h2>随主线保存的妥协分支 · ${p.branches.length} 条</h2><p>默认资源仍按主线统计；分支条件、记录、说明和各自终场将一并保存。</p>${p.branches.map(b=>`<details><summary>${escape(b.name)} · ${b.report?'已记录终场':'仅预设条件'}</summary>${branchPremises(b)}${b.report?.requirements?summaryHtml(b.report.requirements,b.report):''}</details>`).join('')}</section>`);
  const invalidate=()=>{p.dirty=true;$('#confirm-save-plan').disabled=true;$('#condition-status').textContent='核对内容已修改，请重新生成确认摘要。';};
  $('#condition-note').oninput=e=>{reviewEdits().conditions_note=e.target.value;invalidate();};
  document.querySelectorAll('[data-cost-mode],[data-cost-constraint]').forEach(el=>el.oninput=()=>{
    const key=el.dataset.costMode||el.dataset.costConstraint;
    reviewEdits().costs[key]={mode:document.querySelector(`[data-cost-mode="${CSS.escape(key)}"]`).value,constraint:document.querySelector(`[data-cost-constraint="${CSS.escape(key)}"]`).value};invalidate();
  });
  $('#add-condition').onclick=()=>{
    const count=Number($('#condition-count').value),constraint=$('#condition-text').value.trim();
    if(!Number.isInteger(count)||count<1||count>60||!constraint){$('#condition-status').textContent='请填写有效数量和条件用途。';return;}
    reviewEdits().extra_conditions.push({kind:$('#condition-kind').value,code:$('#condition-card').value?Number($('#condition-card').value):null,count,node:$('#condition-node').value,constraint});
    renderConfirmation();invalidate();
  };
  document.querySelectorAll('[data-remove-condition]').forEach(b=>b.onclick=()=>{reviewEdits().extra_conditions.splice(Number(b.dataset.removeCondition),1);renderConfirmation();invalidate();});
  $('#refresh-confirmation').onclick=run(previewReview);
}
async function confirmReviewSave() {
  const p=reviewUI.pending;if(!p||p.dirty||flow.saving||flow.busy)return;
  flow.saving=true;flow.busy=true;flow.savingId=p.id;
  $('#save-confirmation').querySelectorAll('button,input,select,textarea').forEach(b=>b.disabled=true);
  $('#confirmation-message').textContent='正在保存……';
  let failure='';
  try {
    const saved=await api(p.saved?'/api/plans/update':'/api/plans/save',p.payload);
    if(saved.name!==p.payload.name || saved.expansion?.notes!==p.payload.notes || JSON.stringify(saved.annotations)!==JSON.stringify(p.payload.annotations)) {
      throw new Error('此尝试已有不同内容的正式方案。请返回修改后重新生成摘要，当前编辑仍保留');
    }
    flow.draft=null;reviewUI.pending=null;reviewUI.report=null;app.reportKey=null;
    if(typeof branchUI!=='undefined'){branchUI.drafts.clear();branchUI.key=null;branchUI.config=null;branchUI.viewing=false;}
    $('#review-workspace').hidden=true;
    await showPlan(saved.id);notice(`方案“${saved.name}”已存入展开管理。`);
    await refreshHistory().catch(e=>notice(`方案已保存，历史列表刷新失败：${e.message}`));
  } catch(e) {
    if(reviewUI.pending)failure=`保存失败：${e.message}。编辑内容已保留，可重试或返回修改。`;
    else notice(`方案已保存，可从展开管理重新打开：${e.message}`);
  } finally {
    flow.saving=false;flow.busy=false;flow.savingId=null;
    if(reviewUI.pending){renderConfirmation();$('#confirmation-message').textContent=failure;}
  }
}
function renderSavedPlan(plan) {
  $('#plan-report').innerHTML=`<div class="plan-actions"><span>保存于 ${dt(plan.saved_ms)}</span><button id="generate-plan-tutorial" class="primary">生成一图流</button><button id="edit-plan">查看步骤与调整说明</button><button id="plan-conditions">以此条件再次展开</button><button id="delete-plan" class="danger">删除方案</button></div><h2>${escape(plan.name)}</h2><p class="preserve-lines">${escape(plan.expansion?.notes||'')}</p><div id="saved-route-summary">${plan.requirements?summaryHtml(plan.requirements,plan):'<p>旧方案未保存条件摘要，原始报告仍完整保留。</p>'}</div><details><summary>原始冻结报告</summary><div id="saved-raw-report"></div></details>`;
  $('#generate-plan-tutorial').onclick=()=>openPlanTutorial(plan);
  const rawView=raw=>{
    $('#saved-raw-report').innerHTML=renderTrainingReport(plan,{raw}).replaceAll('all-events','plan-all-events');
    $('#plan-all-events').onchange=e=>rawView(e.target.checked);
  };
  rawView(false);
  if(typeof mountPlanLibrary==='function')mountPlanLibrary(plan);
  if(typeof mountSavedBranches==='function')mountSavedBranches(plan);
  $('#edit-plan').onclick=run(async()=>{
    if(flow.draft?.id===plan.id&&flow.draft.originalRevision!==(plan.edit_revision||0)) {
      if(draftDirty()&&!await confirmFlow('重新载入已更新的方案？','当前未保存的说明会被已保存版本替换。取消可继续保留当前编辑。','载入已保存版本'))return;
      flow.draft=null;
    }
    reviewUI.report=null;return showReport(plan.id);
  });
  $('#plan-conditions').onclick=run(()=>reopenConditions(plan.id));
  $('#delete-plan').onclick=run(async()=>{
    if(flow.busy||!await confirmFlow(`删除方案“${plan.name}”？`,'仅删除此方案，来源卡组和原始记录保留。','删除方案'))return;
    flow.busy=true;flow.deleting=true;
    try {await api('/api/plans/delete',{id:plan.id,name:plan.name});flow.selectedPlan=null;if(flow.draft?.id===plan.id)flow.draft=null;$('#plan-report').innerHTML='<p>方案已删除。</p>';await refreshPlans();await refreshHistory();}
    finally {flow.busy=false;flow.deleting=false;}
  });
}
document.addEventListener('click',e=>{
  // Tab buttons replace the detail body during this same click. Its original
  // event path still identifies an inside click even after the button detaches.
  const inDetail=e.composedPath().some(el=>el.id==='review-card-popover'||el.dataset?.reviewCard);
  if(reviewUI.selected&&e.composedPath().some(el=>el.id==='review-card-popover'))pinReviewDetail();
  if(reviewUI.selected&&!inDetail)closeReviewDetail();
  const zonePanel=$('#review-zone-content');
  if(zonePanel&&!zonePanel.hidden&&!inDetail&&!e.target.closest('#review-zone-content,[data-review-zone]'))zonePanel.hidden=true;
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if(b.id==='review-detail-close'){closeReviewDetail(true);return;}
  if(b.id==='review-detail-back'){backReviewDetail();return;}
  if(b.id==='review-detail-pin'){pinReviewDetail();return;}
  if(b.dataset.reviewNode){selectReviewNode(b.dataset.reviewNode);return;}
  if(b.dataset.reviewCard){
    openReviewDetail(b);return;
  }
  if(b.id==='review-zone-close'){$('#review-zone-content').hidden=true;return;}
  if(b.dataset.reviewZone){
    const [side,zone]=b.dataset.reviewZone.split(':').map(Number),n=reviewNode();
    $('#review-zone-content').hidden=false;
    $('#review-zone-content').innerHTML=`<section class="zone-contents"><button id="review-zone-close" aria-label="关闭区域">×</button><h3>${escape(reviewPlace({controller:side,location:zone}))} · ${boardCards(n,side,zone).length} 张</h3><div>${boardCards(n,side,zone).map(c=>reviewCard(c,n.id,{name:true,face:reviewKnown(c)})).join('')||'<p>当前区域为空。</p>'}</div></section>`;
  }
});
document.addEventListener('pointerover',e=>{
  if(e.pointerType==='touch'||e.buttons)return;
  if(e.target.closest('#review-card-popover')){clearTimeout(reviewHover.closeTimer);reviewHover.closeTimer=null;}
  const card=e.target.closest('[data-review-card]');
  if(card&&!card.disabled&&!card.contains(e.relatedTarget))scheduleReviewHover(card);
});
document.addEventListener('pointerout',e=>{
  const card=e.target.closest('[data-review-card]'),panel=e.target.closest('#review-card-popover');
  if(card===reviewHover.suppressed&&!card?.contains(e.relatedTarget))reviewHover.suppressed=null;
  if(!card&&!panel)return;
  if(card?.contains(e.relatedTarget)||e.relatedTarget?.closest?.('#review-card-popover'))return;
  scheduleReviewDetailClose();
});
document.addEventListener('keydown',e=>{
  if(app.view==='history'&&['ArrowLeft','ArrowRight'].includes(e.key)&&!e.altKey&&!e.ctrlKey&&!e.metaKey&&!e.shiftKey&&!e.target.closest('input,textarea,select,[contenteditable=true],[role=dialog]')&&!reviewUI.selected&&$('#review-zone-content')?.hidden!==false) {
    const i=reviewUI.nodes.indexOf(reviewNode()),n=reviewUI.nodes[i+(e.key==='ArrowLeft'?-1:1)];
    if(n){e.preventDefault();selectReviewNode(n.id);}return;
  }
  if(e.key!=='Escape')return;
  if(reviewUI.selected){e.preventDefault();closeReviewDetail(true);}
  else if($('#review-zone-content')?.hidden===false){e.preventDefault();$('#review-zone-content').hidden=true;}
  else if(reviewUI.drawer&&app.view==='history'){e.preventDefault();setReviewDrawer(false);}
});
document.addEventListener('scroll',e=>{
  if(!reviewUI.selected||e.target.closest?.('#review-card-popover'))return;
  // Ignore a queued scroll notification from bringing the trigger into view
  // before the click. Close only when the anchor has actually moved afterward.
  const anchor=reviewUI.anchor, now=anchor?.element?.getBoundingClientRect();
  if(!now||Math.abs(now.top-anchor.rect.top)>.5||Math.abs(now.left-anchor.rect.left)>.5)closeReviewDetail();
},true);
globalThis.addEventListener?.('resize',()=>closeReviewDetail());


function reviewFieldSlots(l) {
  const slots=[[4,5,1],[4,6,3],...Array.from({length:5},(_,i)=>[4,i,i+5]),...Array.from({length:5},(_,i)=>[8,i,i+10]),[8,5,0],[8,6,15],[8,7,19]];
  return slots.map(([zone,sequence,pos])=>({x:pos%5*11+1,y:Math.floor(pos/5)*11+1,active:zone===l.location&&sequence===l.sequence}));
}
function reviewLocationIcon(l) {
  if(!l)return '';
  const label=reviewPlace(l);
  if([4,8].includes(l.location)) {
    return `<span class="location-icon side-${l.controller===1?'opponent':'self'}" role="img" aria-label="${escape(label)}" title="${escape(label)}"><svg viewBox="0 0 55 44">${reviewFieldSlots(l).map(s=>`<rect x="${s.x}" y="${s.y}" width="8" height="9" rx="1" fill="${s.active?'currentColor':'none'}" stroke="currentColor"/>`).join('')}</svg></span>`;
  }
  return `<span class="location-icon zone-icon" role="img" aria-label="${escape(label)}" title="${escape(label)}">${({1:'▤',2:'▱',16:'墓',32:'⊘',64:'EX',128:'▣'}[l.location&128?128:l.location])||'?'}<small>${escape(({1:'卡组',2:'手牌',16:'墓地',32:'除外',64:'额外',128:'素材'}[l.location&128?128:l.location])||'未知')}</small></span>`;
}
// Only explicit rule cleanup (including lost overlay target) is omitted. Costs, effect
// movements and uncertain reasons remain visible; detailed evidence is intact.
function compactCleanup(a,report=reviewUI.report) {
  if(a.kind==='effect'||a.kind==='cost')return false;
  const events=(a.evidence_refs||[a.id]).map(id=>(report.events||[]).find(e=>e.id===id)).filter(Boolean);
  return events.length>0&&events.every(e=>e.message===50&&(e.origin?.location&128)&&e.destination?.location===16&&[0x400,0x20000400].includes(e.reason)&&!e.cost&&!e.cause);
}
function reviewEffectParts(desc='') {
  return String(desc).split(/(?=[①②③④⑤⑥⑦⑧⑨⑩][：:])/).filter(Boolean).map((text,i)=>({key:String(i),text,label:/^[①②③④⑤⑥⑦⑧⑨⑩][：:]/.test(text)?text[0]:'文本'}));
}
function reviewMarkEditor(c,d,edits,editable) {
  const mark=edits.final_marks?.[String(c.instance_id)]||{};
  return `<label><input type="checkbox" id="review-final-mark" ${mark.marked?'checked':''} ${editable?'':'disabled'}>标记为终场有效卡牌</label><div class="effect-marks">${reviewEffectParts(d.desc).map(p=>`<div class="effect-mark ${mark.effects?.[p.key]?'is-marked':''}"><label><input type="checkbox" data-final-effect="${p.key}" ${mark.effects?.[p.key]?'checked':''} ${editable?'':'disabled'}><span>${escape(p.text)}</span></label>${mark.effects?.[p.key]?`<input data-final-effect-note="${p.key}" aria-label="${p.label}效果备注" placeholder="用途或阻抗说明（可留空）" maxlength="4000" value="${escape(mark.effects[p.key].note||'')}" ${editable?'':'disabled'}>`:''}</div>`).join('')}</div>`;
}
function bindReviewMarks(c,edits,editable) {
  const box=$('#review-final-mark');if(!box||!editable)return;
  const get=()=>{edits.final_marks||={};return edits.final_marks[String(c.instance_id)]||={marked:false,effects:{}};};
  box.onchange=()=>{get().marked=box.checked;reviewUI.pending=null;refreshFinalMarks();};
  document.querySelectorAll('[data-final-effect]').forEach(b=>b.onchange=()=>{const mark=get();if(b.checked){mark.effects[b.dataset.finalEffect]={note:''};mark.marked=true;}else delete mark.effects[b.dataset.finalEffect];reviewUI.pending=null;refreshFinalMarks();renderReviewDetail();});
  document.querySelectorAll('[data-final-effect-note]').forEach(b=>b.oninput=()=>{get().effects[b.dataset.finalEffectNote].note=b.value;reviewUI.pending=null;refreshFinalMarks();});
}
function reviewFinalCards(n,report=reviewUI.report,edits=reviewEdits(),{compact=true}={}) {
  const cards=(n.state?.cards||[]).filter(c=>edits.final_marks?.[String(c.instance_id)]?.marked).sort((a,b)=>a.controller-b.controller||a.location-b.location||a.sequence-b.sequence);
  return `<h3>终场有效卡牌</h3><div class="marked-final-cards">${cards.map(c=>{const mark=edits.final_marks[String(c.instance_id)],parts=reviewEffectParts(report.catalog?.[c.code]?.desc);return `<article>${reviewCard(c,n.id,{report,name:true,face:true,zone:false})}${!compact?reviewLocationIcon(c):''}${!compact||![4,8].includes(c.location)?`<small class="marked-location">${escape(reviewPlace(c))}</small>`:''}${edits.cards?.[String(c.instance_id)]?.trim()?`<p class="marked-note">${escape(edits.cards[String(c.instance_id)])}</p>`:''}${parts.filter(p=>mark.effects?.[p.key]).map(p=>`<div class="marked-effect"><strong>✓ ${escape(p.label)}效果</strong>${!compact?`<p class="marked-effect-original">${escape(p.text)}</p>`:''}${mark.effects[p.key].note?.trim()?`<p class="marked-note">${escape(mark.effects[p.key].note)}</p>`:''}</div>`).join('')}</article>`;}).join('')||'<p>点击终场卡牌（含墓地、除外区）勾选标记与有效效果。</p>'}</div>`;
}
function refreshFinalMarks() {
  const n=reviewUI.nodes.find(n=>n.kind==='final');if(!n)return;
  const anchorScope=reviewUI.anchor?.element?.closest('#review-log,#review-final-marks')?.id;
  if($('#review-final-marks'))$('#review-final-marks').innerHTML=reviewFinalCards(n);
  const scroll=$('#review-log .log-scroll')?.scrollTop||0;
  reviewUI.refreshingMarks=true;renderReviewLog();reviewUI.refreshingMarks=false;
  if($('#review-log .log-scroll'))$('#review-log .log-scroll').scrollTop=scroll;
  // Rebind the popover to the replacement of its original card button. A log
  // refresh must not make the next queued scroll event close an active editor.
  if(anchorScope&&reviewUI.selected) {
    const replacement=[...document.querySelectorAll(`#${anchorScope} [data-review-card]`)].find(b=>{
      const item=reviewUI.cards.get(b.dataset.reviewCard);
      return item?.card.instance_id===reviewUI.selected.instance_id&&item.node===reviewUI.detailNode?.id;
    });
    if(replacement)reviewUI.anchor={element:replacement,rect:replacement.getBoundingClientRect()};
  }
}
