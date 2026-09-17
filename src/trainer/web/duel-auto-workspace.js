'use strict';

const AutoDuelModel=(()=>{
  const key=frame=>JSON.stringify([frame?.round_id,frame?.opening?.snapshot_id]);
  const create=context=>({context:structuredClone(context),deck:structuredClone(context.deck),hand:[...context.hand],count:context.hand.length,
    stage:5,reached:5,result:null,plan:null,routes:null,graph:null,position:null,forecast:null,
    planSort:'shortest',favoritesOnly:false,enabled:true,ended:false,busy:false,message:'',generation:0,
    session:'automatic-'+crypto.randomUUID()});
  return {key,create};
})();
if(typeof module!=='undefined')module.exports=AutoDuelModel;

const autoDuelState=()=>duelState().automatic.workspace;
const autoDuelVisible=s=>s&&s===autoDuelState()&&duelState().operationMode==='automatic'&&duelState().stage>=duelStages.plans;
const autoDuelView={graphHeight:null,graphScale:1,preview:null,hoverTimer:null,closeTimer:null,detailPreview:false,shortcutStatus:null};
function autoDuelButton(action,label,disabled=false,primary=false){return `<button type="button" data-auto-duel-action="${action}" ${['back-step','forward-step'].includes(action)?`aria-label="${action==='back-step'?'后退':'前进'}"`:''} ${disabled||autoDuelState()?.busy||duelUI.busy?'disabled':''} class="${primary?'primary':''}">${label}</button>`;}
function autoDuelTell(message){const s=autoDuelState();if(s)s.message=message;const el=$('#auto-duel-message');if(el){el.textContent=message;el.hidden=!message;}}
function autoDuelReach(stage){const s=autoDuelState();s.stage=stage;s.reached=Math.max(s.reached,stage);if(autoDuelVisible(s))duelReach(stage);}
function renderAutoDuel(){if(autoDuelVisible(autoDuelState()))renderDuel();}
async function autoDuelWork(fn){const s=autoDuelState();if(!s||s.busy)return;s.busy=true;renderAutoDuel();try{await fn(s);}catch(error){if(s===autoDuelState())autoDuelTell(error.message);}finally{s.busy=false;renderAutoDuel();}}
function automaticDeckContext(){const d=duelState().automatic;return {name:d.name||d.deck?.name,deck:structuredClone(d.deck.deck),tag_selection:{tag_ids:[...d.tagIds],primary_ids:[...d.primaryIds]}};}
async function disposeAutoDuel(){
  const draft=duelState().automatic,s=draft.workspace;draft.workspace=null;closeAutoDuelPreview();
  if(!s)return;++s.generation;s.enabled=false;s.ended=true;
  if(s.forecast){++s.forecast.generation;s.forecast=null;}
  if(autoDuelObservationDialog.open)autoDuelObservationDialog.close();
  await api('/api/automatic-duel/close',{context_id:s.context.context_id}).catch(()=>{});
}
async function prepareAutoDuelWorkspace(){
  const d=duelState().automatic,frame=d.order?.frame;
  if(!DuelOpening.confirmed(frame))throw Error('请先确认本局先攻起手。');
  if(d.workspace&&d.workspace.context.round_id===frame.round_id&&d.workspace.context.snapshot_id===frame.opening.snapshot_id)return d.workspace;
  await disposeAutoDuel();
  const context=await api('/api/automatic-duel/context',{monitor_id:frame.monitor_id,round_id:frame.round_id,snapshot_id:frame.opening.snapshot_id});
  if(d!==duelState().automatic||d.order?.frame.round_id!==frame.round_id){await api('/api/automatic-duel/close',{context_id:context.context_id});return null;}
  const s=AutoDuelModel.create(context);d.workspace=s;
  try{s.result=await api('/api/automatic-duel/match',{context_id:context.context_id});}
  catch(error){s.message=error.message;}
  return s;
}
async function refreshAutoDuel(){await autoDuelWork(async s=>{
  const generation=++s.generation,result=await api('/api/automatic-duel/match',{context_id:s.context.context_id});
  if(s!==autoDuelState()||s.generation!==generation)return;
  s.result=result;s.message='';
  if(s.plan&&!s.plan.temporary&&!result.matches.some(p=>p.id===s.plan.id&&p.automatic_revision===s.plan.automatic_revision)){
    s.plan=s.routes=s.graph=s.position=null;s.reached=duelStages.plans;autoDuelReach(duelStages.plans);autoDuelTell('方案来源已变化，请重新选择。');
  }
});}
async function chooseAutoDuelPlan(id){await autoDuelWork(async s=>{
  const candidate=s.result?.matches.find(p=>p.id===id);if(!candidate)return;
  const generation=++s.generation,plan=await api('/api/automatic-duel/select',{context_id:s.context.context_id,plan_id:id,revision:candidate.automatic_revision});
  if(s!==autoDuelState()||generation!==s.generation)return;
  dropAutoDuelForecast(s);s.plan=plan;s.routes=duelPlanRoutes(plan);s.graph=DuelModel.graph(s.routes);
  s.position={key:s.graph.start,choice:0};s.enabled=true;s.ended=false;s.session='automatic-'+crypto.randomUUID();
  closeAutoDuelPreview();closeReviewDetail();autoDuelTell('');autoDuelReach(duelStages.tutorial);
});void syncAutoDuelShortcuts();}
function autoDuelFavoriteButton(plan){return `<button type="button" class="plan-favorite-toggle" data-auto-plan-favorite="${escape(plan.id)}" aria-pressed="${!!plan.favorite}" aria-label="${escape((plan.favorite?'取消收藏：':'收藏方案：')+plan.name)}">${plan.favorite?'★':'☆'}</button>`;}
async function toggleAutoDuelFavorite(id){await autoDuelWork(async s=>{
  const plan=s.result.matches.find(p=>p.id===id);if(!plan)return;
  const data=await api('/api/plan-favorites',{id,favorite:!plan.favorite});
  if(s!==autoDuelState())return;plan.favorite=data.plans.includes(id);if(s.plan?.id===id)s.plan.favorite=plan.favorite;
});}
function autoDuelWorkspacePage(){
  const s=autoDuelState();
  if(!s)return '<section id="auto-duel-workspace" class="auto-duel-workspace"><p>自动工作区尚未就绪，请返回起手确认后重试。</p></section>';
  const stage=duelState().stage;s.stage=stage;
  const content=stage===duelStages.plans?(s.result?autoDuelMatchesPage():`<p>方案列表读取未完成。</p>${autoDuelButton('rematch','重试')}`):
    stage===duelStages.tutorial&&s.plan?autoDuelTutorialPage():`<div class="auto-duel-complete"><span>✓</span><h2>展开教程已结束</h2><p>${escape(s.deck.name)} · ${escape(s.plan?.name||'')}</p>${autoDuelButton('new','再来一场',false,true)}</div>`;
  return `<section id="auto-duel-workspace" class="auto-duel-workspace" data-workspace="automatic" data-context="${escape(s.context.context_id)}"><div class="auto-duel-context"><strong>自动模式</strong><span>${escape(s.deck.name)} · 本局起手 ${s.hand.length} 张</span></div><p id="auto-duel-message" role="status" ${s.message?'':'hidden'}>${escape(s.message)}</p><section id="${stage===duelStages.plans?'auto-duel-plans':stage===duelStages.tutorial?'auto-duel-tutorial':'auto-duel-completed'}"><div id="auto-duel-content">${content}</div></section></section>`;
}
function autoDuelFooter(){const s=autoDuelState();return s?.stage===duelStages.tutorial?`${s.plan?.temporary?autoDuelButton('report-outcome','报告实际情况'):''}${autoDuelButton('back-step','←')}${autoDuelButton('forward-step','→')}${autoDuelButton('end','展开结束',false,true)}`:'';}
function mountAutoDuelWorkspace(){
  const s=autoDuelState(),root=$('#auto-duel-workspace');if(!s||!root)return;
  if(s.stage===duelStages.plans&&s.result)$('#auto-duel-plan-sort').onchange=event=>{s.planSort=event.target.value;renderAutoDuel();};
  if(s.forecast&&[duelStages.plans,duelStages.tutorial].includes(s.stage))autoRenderDuelForecast();
  root.onclick=run(handleAutoDuelClick);
  root.onpointerover=event=>{if(event.buttons||event.pointerType==='touch')return;const anchor=event.target.closest('[data-auto-duel-plan],[data-auto-duel-node]');if(anchor&&!anchor.contains(event.relatedTarget))showAutoDuelPreview(anchor);};
  root.onpointerout=event=>{if(!autoDuelView.preview?.anchor?.contains(event.relatedTarget)&&!$('#auto-duel-preview')?.contains(event.relatedTarget))scheduleAutoDuelPreviewClose();};
  root.onpointerdown=event=>{if(event.button===0&&event.target.closest('[data-auto-duel-node]'))closeAutoDuelPreview();};
  root.onkeydown=event=>{const node=event.target.closest('[data-auto-duel-node]');if(node&&['Enter',' '].includes(event.key)){event.preventDefault();node.click();}};
  if(s.stage===duelStages.tutorial&&s.plan){mountAutoDuelGraphResize();layoutAutoDuelGraph();paintAutoDuelPosition();}
  if(s.busy)root.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);
  pruneReviewCards();void syncAutoDuelShortcuts();
}
async function handleAutoDuelClick(event){
  const s=autoDuelState(),button=event.target.closest('button'),node=event.target.closest('[data-auto-duel-node]');
  if(!s||s.busy)return;
  if(node){event.stopPropagation();closeAutoDuelPreview();closeReviewDetail();if(s.plan.temporary)return autoSelectForecastNode(node.dataset.autoDuelNode);s.position={key:node.dataset.autoDuelNode,choice:0};paintAutoDuelPosition();return;}
  if(!button||button.disabled)return;
  if(button.dataset.autoDuelPlan){event.stopPropagation();return chooseAutoDuelPlan(button.dataset.autoDuelPlan);}
  if(button.dataset.autoPlanFavorite){event.stopPropagation();return toggleAutoDuelFavorite(button.dataset.autoPlanFavorite);}
  if(button.dataset.autoDuelChoice!==undefined){event.stopPropagation();s.position.choice=Number(button.dataset.autoDuelChoice);paintAutoDuelPosition(false);return;}
  if(button.dataset.reviewZone){event.stopPropagation();showAutoDuelZone(button.dataset.reviewZone);return;}
  if(button.dataset.autoDuelCloseZone!==undefined){event.stopPropagation();$('#auto-duel-zone-content').hidden=true;return;}
  const action=button.dataset.autoDuelAction;if(!action)return;
  event.stopPropagation();
  if(action==='rematch')return refreshAutoDuel();
  if(action==='favorites-only'){s.favoritesOnly=!s.favoritesOnly;renderAutoDuel();return;}
  if(action==='opening'){duelGo(duelStages.hand);return;}
  if(action==='modular')return autoLaunchModularFromDuel();
  if(action==='report-outcome')return autoOpenDuelObservation();
  if(action==='shortcuts')return openDuelShortcuts();
  if(action==='toggle-shortcuts'){s.enabled=!s.enabled;renderAutoDuel();return;}
  if(action==='back-step'||action==='forward-step')return autoDuelNavigate(action==='back-step'?'back':'forward');
  if(action==='end')return endAutoDuel();
  if(action==='new')return startNewDuel();
}
function autoDuelNavigate(action){
  const s=autoDuelState();if(!autoDuelVisible(s)||s.stage!==duelStages.tutorial||s.ended||s.busy||duelUI.busy||s.forecast?.busy||document.querySelector('dialog[open]')||moduleUI.current!=='duel')return;
  if(action==='end')return void endAutoDuel();
  if(action==='forward'&&s.plan.temporary)return void autoAdvanceDuelForecast().catch(error=>autoDuelTell(error.message));
  closeAutoDuelPreview();closeReviewDetail();s.position=DuelModel.navigate(s.graph,s.position,action);paintAutoDuelPosition();
}
async function endAutoDuel(){await autoDuelWork(async s=>{
  if(s.forecast)++s.forecast.generation;s.forecast=null;await api('/api/automatic-duel/close',{context_id:s.context.context_id});
  if(s!==autoDuelState())return;s.enabled=false;s.ended=true;s.session='automatic-'+crypto.randomUUID();autoDuelReach(duelStages.complete);closeAutoDuelPreview();
});await syncAutoDuelShortcuts();}
function dropAutoDuelForecast(s){const f=s.forecast;if(!f)return;s.forecast=null;++f.generation;if(f.id)void api('/api/automatic-duel/dispatch',{context_id:s.context.context_id,intent:'plan-close',id:f.id}).catch(()=>{});}
async function autoDuelDispatch(intent,body){const s=autoDuelState();return api('/api/automatic-duel/dispatch',{...body,context_id:s.context.context_id,intent});}
function paintAutoDuelShortcutStatus(){const el=$('#auto-duel-shortcut-status');if(el){el.textContent=autoDuelView.shortcutStatus?.error||'';el.hidden=!el.textContent;}}
function syncAutoDuelShortcuts(inactive=false){
  if(!window.trainerDesktop?.tutorialUpdate)return Promise.resolve();const s=autoDuelState();
  const payload={active:!!(!inactive&&autoDuelVisible(s)&&s.stage===duelStages.tutorial&&!s.ended&&moduleUI.current==='duel'),enabled:!!s?.enabled,suspended:!!document.querySelector('dialog[open]'),session:s?.session||'automatic-inactive',bindings:{...duelUI.bindings}};
  duelUI.shortcutQueue=duelUI.shortcutQueue.catch(()=>{}).then(()=>window.trainerDesktop.tutorialUpdate(payload)).then(status=>{if(s===autoDuelState()&&status.session===s?.session){autoDuelView.shortcutStatus=status;paintAutoDuelShortcutStatus();}}).catch(error=>{if(s===autoDuelState()){autoDuelView.shortcutStatus={error:error.message};paintAutoDuelShortcutStatus();}});
  return duelUI.shortcutQueue;
}
function closeAutoDuelPreview(){clearTimeout(autoDuelView.hoverTimer);clearTimeout(autoDuelView.closeTimer);autoDuelView.preview=null;const p=$('#auto-duel-preview');if(p)p.hidden=true;}
function scheduleAutoDuelPreviewClose(){clearTimeout(autoDuelView.closeTimer);autoDuelView.closeTimer=setTimeout(()=>{if(!autoDuelView.preview?.anchor?.matches(':hover')&&!$('#auto-duel-preview')?.matches(':hover')&&!$('#review-card-popover')?.matches(':hover'))closeAutoDuelPreview();},220);}
function paintAutoDuelPreview(){
  const preview=autoDuelView.preview,s=autoDuelState();if(!preview||!s)return;
  const plan=preview.kind==='plan'?s.result?.matches.find(p=>p.id===preview.id):null,node=preview.kind==='node'?s.graph?.nodes.find(n=>n.key===preview.id):null;
  if(!plan&&!node)return closeAutoDuelPreview();
  const panel=$('#auto-duel-preview');$('#auto-duel-preview-content').innerHTML=plan?`<div class="auto-duel-preview-modes"><button data-auto-preview-mode="compact" aria-pressed="${!autoDuelView.detailPreview}">简略</button><button data-auto-preview-mode="detailed" aria-pressed="${autoDuelView.detailPreview}">详细</button></div>${duelPlanSummary(plan,autoDuelView.detailPreview)}`:autoDuelNodeDetail(node);
  panel.hidden=false;panel.style.maxHeight='';const box=preview.anchor.getBoundingClientRect();
  const placement=duelPreviewPlacement({anchor:box,graph:node?$('#auto-duel-graph-scroll').getBoundingClientRect():box,width:panel.offsetWidth,height:panel.offsetHeight,viewport:{width:innerWidth,height:innerHeight},footer:$('#duel-footer').hidden?null:$('#duel-footer').getBoundingClientRect(),beside:!!plan});
  if(!placement){panel.hidden=true;return;}panel.style.left=placement.left+'px';panel.style.top=placement.top+'px';panel.style.maxHeight=placement.height+'px';pruneReviewCards();
}
function showAutoDuelPreview(anchor){
  if(autoDuelView.preview?.anchor===anchor)return;closeAutoDuelPreview();
  autoDuelView.preview={anchor,kind:anchor.dataset.autoDuelPlan?'plan':'node',id:anchor.dataset.autoDuelPlan||anchor.dataset.autoDuelNode,rect:anchor.getBoundingClientRect()};
  autoDuelView.hoverTimer=setTimeout(()=>{if(autoDuelView.preview?.anchor===anchor&&anchor.isConnected&&anchor.matches(':hover')&&!document.querySelector('dialog[open]')){closeReviewDetail();paintAutoDuelPreview();}},280);
}
if(typeof document!=='undefined'){
  const preview=document.createElement('aside');preview.id='auto-duel-preview';preview.className='auto-duel-preview';preview.hidden=true;preview.setAttribute('role','dialog');preview.setAttribute('aria-label','自动模式方案与步骤详情');
  preview.innerHTML='<button id="auto-duel-preview-close" aria-label="关闭预览">×</button><div id="auto-duel-preview-content"></div>';document.body.append(preview);
  $('#auto-duel-preview-close').onclick=closeAutoDuelPreview;
  preview.onclick=event=>{const mode=event.target.closest('[data-auto-preview-mode]');if(mode){autoDuelView.detailPreview=mode.dataset.autoPreviewMode==='detailed';paintAutoDuelPreview();}};
  preview.onpointerenter=()=>clearTimeout(autoDuelView.closeTimer);preview.onpointerleave=scheduleAutoDuelPreviewClose;
  $('#review-card-popover').addEventListener('pointerenter',()=>{if(autoDuelView.preview)clearTimeout(autoDuelView.closeTimer);});
  $('#review-card-popover').addEventListener('pointerleave',()=>{if(autoDuelView.preview)scheduleAutoDuelPreviewClose();});
  document.addEventListener('scroll',event=>{const p=autoDuelView.preview;if(!p||event.target.closest?.('#auto-duel-preview,#review-card-popover'))return;const r=p.anchor.getBoundingClientRect();if(Math.abs(r.left-p.rect.left)>.5||Math.abs(r.top-p.rect.top)>.5)closeAutoDuelPreview();},true);
  window.addEventListener('resize',()=>{closeAutoDuelPreview();if(autoDuelVisible(autoDuelState())&&autoDuelState().stage===duelStages.tutorial){layoutAutoDuelGraph();focusAutoDuelPosition();}});
}
