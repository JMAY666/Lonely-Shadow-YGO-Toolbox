'use strict';

const DuelSmart=(()=>{
  const terminal=frame=>['cancelled','invalidated','closed'].includes(frame?.stage);
  const ready=frame=>frame?.stage==='ready'&&frame.context&&frame.frame?.confirmed?.order==='first'&&frame.context.round_id===frame.frame.round_id;
  const alive=run=>!!run&&!run.cancelled;
  return {terminal,ready,alive};
})();
if(typeof module!=='undefined')module.exports=DuelSmart;

function smartRun(){return duelState().automatic.smartRun;}
function smartAlive(run){return DuelSmart.alive(run)&&smartRun()===run;}
function paintSmartRecognition(run){
  if(!smartAlive(run))return;
  const value=run.value||{},dialog=$('#duel-capture-dialog');
  $('#duel-capture-title').textContent='智能化识别';
  $('#duel-capture-status').textContent=value.reading_error||value.message||'等待对局开始';
  $('#duel-capture-help').textContent=`在 ${duelPlatformLabel()} 中正常开始对局。TAG 沿用本地系列识别，起手已提前监测；工具箱只读取游戏数据。`;
  $('#duel-capture-close').textContent='取消并返回';$('#duel-capture-close').disabled=false;
  $('#duel-capture-next').hidden=true;$('#duel-capture-smart').hidden=true;$('#duel-capture-retry').hidden=true;
  $('#duel-smart-retry').hidden=value.stage!=='failed'||!['tags','audit'].includes(value.failed_stage);
  $('#duel-smart-restart').hidden=!['failed','invalidated','second','closed'].includes(value.stage);
  $('#duel-smart-restart').textContent=value.stage==='closed'?'重新捕捉程序':'重新监测';
  const steps=[['waiting','等待对局开始'],['deck','获取本局卡组'],['tags','识别 TAG'],['opening','等待先后攻及起手就绪'],['audit','自动校验']];
  const seen=new Set((value.events||[]).map(e=>e.stage));
  const details=value.construction?`主卡组 ${value.construction.deck.main.length} / 额外 ${value.construction.deck.extra.length} / 副卡组 ${value.construction.deck.side.length}`:'';
  const tags=value.tag_result?Object.values(value.tag_result.tag_names).join('、')||'识别成功，没有适用 TAG':'';
  $('#duel-capture-processes').innerHTML=`<p>${escape(value.note||'')}</p><ol class="duel-smart-progress">${steps.map(([key,label])=>`<li data-smart-stage="${key}" class="${seen.has(key)?'observed':''}">${label}${key===value.stage?' · 正在处理':''}</li>`).join('')}</ol><p>${escape(details)}</p><p>${escape(tags)}</p>${value.frame?.opening?.status==='ready'?`<p>已冻结本局 ${value.frame.opening.cards.length} 张完整起手</p>`:''}<p class="duel-order-error" role="alert">${escape(value.error||'')}</p>`;
  dialog.dataset.busy='false';
}
function resetCaptureDialog(){
  $('#duel-capture-title').textContent=`捕捉 ${duelPlatformLabel()} 进程`;$('#duel-capture-close').textContent='关闭';
  $('#duel-capture-help').textContent=duelState().automatic.platform==='masterduel'?'智能化识别会等待正式开局。请在 Yu-Gi-Oh! Master Duel 中正常开始对局、投硬币并完成先后攻选择；以最终对局结果确认先后攻。当前仅开放智能化识别。':duelState().automatic.platform!=='ygopro'?`智能化识别会等待正式开局。请在 ${duelPlatformLabel()} 中正常准备、猜拳并选择先后攻。当前仅开放智能化识别。`:'智能化识别会等待正式开局。逐步识别请先在 YGOPro 主菜单点击「编辑卡组」，打开要识别的卡组并停留在该页面，再点击「获取卡组」。';
  $('#duel-capture-retry').hidden=false;$('#duel-smart-retry').hidden=true;$('#duel-smart-restart').hidden=true;
}
function releaseSmartWorkspace(){
  if(typeof clearSecondOpening==='function')clearSecondOpening();
  const workspace=autoDuelState();if(!workspace)return;
  if(typeof stopAutoFollow==='function')stopAutoFollow(workspace);
  workspace.ended=true;++workspace.generation;workspace.enabled=false;dropDuelForecast(workspace);
  closeAutoDuelPreview();closeReviewDetail();
  if(autoDuelObservationDialog.open)autoDuelObservationDialog.close();
  void syncAutoDuelShortcuts(true);
}
async function cancelSmartRecognition({restore=true}={}){
  const run=smartRun();if(!run)return;
  run.cancelled=true;clearTimeout(run.timer);
  const draft=duelState().automatic,s=duelState(),workspace=draft.workspace;
  releaseSmartWorkspace();
  // Detach before any await: delayed HTTP results cannot navigate or mutate UI.
  if(restore){s.automatic=run.previous; s.stage=run.navigation.stage;s.reached=run.navigation.reached;}
  else draft.smartRun=null;
  $('#duel-capture-dialog').close();resetCaptureDialog();
  await api('/api/ygopro/smart/cancel',{request_id:run.id}).catch(()=>{});
  if(workspace)await api('/api/automatic-duel/close',{context_id:workspace.context.context_id}).catch(()=>{});
  if(moduleUI.current==='duel')renderDuel();
}
async function beginSmartRecognition(){
  if(smartRun())return;
  const state=duelState(),previous=state.automatic;if(!previous.connection)return;
  stopDuelOrderWatch();
  const run={id:crypto.randomUUID().replaceAll('-',''),previous,navigation:{stage:state.stage,reached:state.reached},cancelled:false,entered:false};
  const draft=DuelAutomatic.create();draft.connection=previous.connection;draft.platform=previous.platform;draft.smartRun=run;
  state.automatic=draft;paintSmartRecognition(run);
  if(!$('#duel-capture-dialog').open)$('#duel-capture-dialog').showModal();
  try {
    const value=await api('/api/ygopro/smart/start',{request_id:run.id,capture_id:draft.connection.capture_id});
    if(!smartAlive(run))return;
    await acceptSmartRecognition(run,value);
  }catch(error){if(smartAlive(run)){run.value={id:run.id,stage:'invalidated',message:'启动监测失败',error:error.message};paintSmartRecognition(run);}}
  if(smartAlive(run))void pollSmartRecognition(run);
}
async function acceptSmartRecognition(run,value){
  if(!smartAlive(run)||value.id!==run.id)return;
  const cycle=value.cycle??0;
  if(run.cycle!==undefined&&cycle<run.cycle)return;
  if(run.cycle!==undefined&&cycle!==run.cycle){
    releaseSmartWorkspace();
    const draft=duelState().automatic;
    draft.workspace=null;draft.order=null;draft.deck=null;draft.fresh=false;draft.tagIds=[];draft.primaryIds=[];
    run.entered=false;run.retrying=false;duelState().stage=duelStages.function;duelState().reached=duelStages.function;
    renderDuel();if(!$('#duel-capture-dialog').open)$('#duel-capture-dialog').showModal();
  }
  run.cycle=cycle;
  run.value=value;
  if(DuelSmart.terminal(value)){
    if(run.entered){
      releaseSmartWorkspace();
      duelTell(value.error||'本局已失效，请重新监测。');
      // Leave no stale result or tutorial presented as this live duel.
      duelState().stage=duelStages.function;duelState().reached=duelStages.function;
      renderDuel();if(!$('#duel-capture-dialog').open)$('#duel-capture-dialog').showModal();
    }
    paintSmartRecognition(run);return;
  }
  if(!run.entered)paintSmartRecognition(run);
  if(value.stage==='second'&&value.frame?.confirmed?.order==='second'&&value.frame?.opening?.status==='ready'&&!run.entered){
    run.entered=true;
    const draft=duelState().automatic,construction=value.construction;
    clearSecondOpening();draft.deck={name:'自动识别本局构筑',deck:structuredClone(construction.deck)};draft.name=draft.deck.name;draft.fresh=true;
    draft.tagIds=[...(value.tag_result?.selection?.tag_ids||[])];draft.primaryIds=[...(value.tag_result?.selection?.primary_ids||[])];
    draft.order=DuelOrder.create(value.frame);$('#duel-capture-dialog').close();duelReach(duelStages.hand);duelTell('');renderDuel();
    const cycle=run.cycle;
    await Promise.all([...new Set([...construction.deck.main,...construction.deck.extra])].map(code=>card(code).catch(()=>{})));
    if(smartAlive(run)&&run.cycle===cycle){renderDuel();void openingAnalyze('duel');}
  }
  if(value.stage==='second'&&run.entered&&duelState().automatic.order){
    duelState().automatic.order.frame=value.frame;
    if(value.reading_error){clearSecondOpening();duelTell(value.reading_error);renderDuel();}
  }
  if(DuelSmart.ready(value)&&!run.entered){
    run.entered=true;
    const draft=duelState().automatic,context=value.context;
    draft.deck=structuredClone(context.deck);draft.name=context.deck.name;draft.fresh=true;
    draft.tagIds=[...context.deck.tag_selection.tag_ids];draft.primaryIds=[...context.deck.tag_selection.primary_ids];
    draft.order=DuelOrder.create(value.frame);
    const workspace=AutoDuelModel.create(context);draft.workspace=workspace;workspace.smart=true;
    $('#duel-capture-dialog').close();duelReach(duelStages.plans);duelTell('');renderDuel();
    // Both consume the one immutable context. Neither completion selects a plan.
    void startSmartWorkspace(workspace);
    void Promise.all([...new Set([...context.hand,...context.deck.deck.main,...context.deck.deck.extra])].map(code=>card(code).catch(()=>{}))).then(()=>{
      if(smartAlive(run)&&autoDuelState()===workspace&&duelState().stage===duelStages.hand)renderDuel();
    });
  }
}
async function startSmartWorkspace(s){
  s.matching=true;
  const forecast=prepareDuelOpening(s);
  // prepareDuelOpening creates the controller synchronously, before the first await.
  if(s.openingForecast){s.openingForecast.showResults=true;s.openingForecast.collapsed=false;}
  renderAutoDuel();
  void forecast.then(()=>{if(s===autoDuelState()&&!s.ended)renderAutoDuel();});
  try {
    const result=await api('/api/automatic-duel/match',{context_id:s.context.context_id});
    if(s!==autoDuelState()||s.ended)return;
    s.result=result;s.matchError='';
  }catch(error){if(s===autoDuelState()&&!s.ended)s.matchError='方案匹配失败：'+error.message;}
  finally{if(s===autoDuelState()&&!s.ended){s.matching=false;renderAutoDuel();}}
}
async function pollSmartRecognition(run){
  if(!smartAlive(run)||DuelSmart.terminal(run.value))return;
  try{
    const value=await api('/api/ygopro/smart/poll',{request_id:run.id});
    if(!smartAlive(run))return;await acceptSmartRecognition(run,value);
  }catch(error){
    if(!smartAlive(run))return;
    await acceptSmartRecognition(run,{id:run.id,cycle:run.cycle??0,stage:'invalidated',message:'本局监测已失效',error:'监测连接中断：'+error.message});
    void api('/api/ygopro/smart/cancel',{request_id:run.id}).catch(()=>{});
  }
  if(smartAlive(run)&&!DuelSmart.terminal(run.value))run.timer=setTimeout(()=>void pollSmartRecognition(run),250);
}
async function retrySmartRecognition(){
  const run=smartRun();if(!run||run.retrying)return;run.retrying=true;
  const cycle=run.cycle;
  try{const value=await api('/api/ygopro/smart/retry',{request_id:run.id,cycle,round_id:run.value.frame?.round_id});if(smartAlive(run)&&run.cycle===cycle)await acceptSmartRecognition(run,value);}
  catch(error){if(smartAlive(run)&&run.cycle===cycle){run.value.error=error.message;paintSmartRecognition(run);}}
  finally{if(run.cycle===cycle)run.retrying=false;}
}
async function restartSmartRecognition(){
  const reconnect=smartRun()?.value?.stage==='closed';
  await cancelSmartRecognition();
  if(reconnect)await captureDuelProcess();
  if(duelState().automatic.connection)await beginSmartRecognition();
}
function smartOpeningPage(){
  const frame=duelState().automatic.order.frame,s=autoDuelState(),tags=s.deck.tag_selection;
  return `<section class="duel-opening-panel"><h2>本局自动校验结果</h2><p>正式开局 · 我方先攻 · 完整起手已冻结</p><p>主卡组 ${s.deck.deck.main.length} / 额外 ${s.deck.deck.extra.length} / 副卡组 ${s.deck.deck.side.length}</p><p>主 TAG：${escape(tags.primary_ids.map(id=>s.deck.tag_names[id]).join('、')||'无')}；副 TAG：${escape(tags.tag_ids.filter(id=>!tags.primary_ids.includes(id)).map(id=>s.deck.tag_names[id]).join('、')||'无')}</p>${duelOpeningCards(frame)}<p>TAG 采用现有本地系列统计。本局构筑独立保存，不覆盖卡组库。</p>${autoDuelButton('smart-plans','返回方案选择',false,true)}</section>`;
}
if(typeof document!=='undefined'){
  $('#duel-capture-smart').onclick=()=>void beginSmartRecognition();
  $('#duel-smart-retry').onclick=()=>void retrySmartRecognition();
  $('#duel-smart-restart').onclick=()=>void restartSmartRecognition();
}
