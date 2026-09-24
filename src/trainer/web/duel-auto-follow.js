'use strict';

const AutoFollowModel=(()=>{
  const create=plan=>({plan,token:crypto.randomUUID(),id:null,value:null,viewLive:true,busy:false,stopped:false,timer:null,error:''});
  const accept=(run,value)=>!run.stopped&&(!run.id||run.id===value.id);
  const browse=run=>{if(run)run.viewLive=false;};
  return {create,accept,browse};
})();
if(typeof module!=='undefined')module.exports=AutoFollowModel;

function autoFollowSupported(s){return !!s?.smart&&duelState().automatic.platform==='mdpro3';}
function autoFollowAlive(s,run){return s===autoDuelState()&&!s.ended&&s.follow===run&&!run.stopped&&s.plan===run.plan;}
function stopAutoFollow(s){
  const run=s?.follow;if(!run)return;run.stopped=true;clearTimeout(run.timer);s.follow=null;
  if(run.id)void api('/api/automatic-duel/follow/poll',{context_id:s.context.context_id,id:run.id,action:'stop'}).catch(()=>{});
}
async function startAutoFollow(s=autoDuelState()){
  if(!autoFollowSupported(s)||!s.plan)return;
  stopAutoFollow(s);const run=AutoFollowModel.create(s.plan);s.follow=run;run.busy=true;paintAutoFollow();
  const body={context_id:s.context.context_id,request_id:run.token,...(s.plan.temporary?{planner_id:s.forecast.id,route:s.plan.forecastRoute}:{revision:s.plan.automatic_revision})};
  try{
    const value=await api('/api/automatic-duel/follow/start',body);
    if(!autoFollowAlive(s,run)){void api('/api/automatic-duel/follow/poll',{context_id:body.context_id,id:value.id,action:'stop'}).catch(()=>{});return;}
    run.id=value.id;acceptAutoFollow(s,run,value);
  }catch(error){if(autoFollowAlive(s,run))run.error=error.message;}
  finally{if(autoFollowAlive(s,run)){run.busy=false;paintAutoFollow();scheduleAutoFollow(s,run);}}
}
function scheduleAutoFollow(s,run){
  clearTimeout(run.timer);
  if(autoFollowAlive(s,run)&&run.id)run.timer=setTimeout(()=>void pollAutoFollow(s,run),250);
}
async function pollAutoFollow(s,run,action='poll',key=run.value?.next_key){
  if(!autoFollowAlive(s,run)||!run.id)return;
  if(run.busy){if(action!=='poll')run.pendingAction={action,key};return;}
  clearTimeout(run.timer);run.busy=true;
  try{
    const value=await api('/api/automatic-duel/follow/poll',{context_id:s.context.context_id,id:run.id,action:action==='poll'&&run.transportLost?'pause':action,key});
    if(autoFollowAlive(s,run)){run.error='';if(['resume','resync'].includes(action))run.transportLost=false;acceptAutoFollow(s,run,value);}
  }catch(error){
    if(autoFollowAlive(s,run)){run.transportLost=true;run.error='连接中断：'+error.message;if(run.value)run.value={...run.value,connected:false,status:'needs_confirmation',requires_sync:true};}
  }finally{if(autoFollowAlive(s,run)){
    run.busy=false;paintAutoFollow();const pending=run.pendingAction;run.pendingAction=null;
    if(pending)void pollAutoFollow(s,run,pending.action,pending.key);else scheduleAutoFollow(s,run);
  }}
}
function acceptAutoFollow(s,run,value){
  if(!AutoFollowModel.accept(run,value)||value.context_id!==s.context.context_id||value.round_id!==s.context.round_id)return;
  run.value=value;
  if(s.plan.temporary&&Number.isInteger(value.temporary_confirmed)){
    s.plan.confirmed=reviewNodes(s.plan).filter(n=>n.kind==='step'&&n.forecast_absolute_end<value.temporary_confirmed).length;
    if(s.forecast?.data)s.forecast.data.confirmed=value.temporary_confirmed;
  }
  if(run.viewLive&&value.next_key&&s.graph.nodes.some(n=>n.key===value.next_key)&&s.position?.key!==value.next_key&&
    s.stage===duelStages.tutorial&&moduleUI.current==='duel'&&!document.querySelector('dialog[open]')&&!s.busy){
    s.position={key:value.next_key,choice:0};closeAutoDuelPreview();paintAutoDuelPosition();
  }
  paintAutoFollow();
}
function autoFollowBrowse(s=autoDuelState()){AutoFollowModel.browse(s?.follow);paintAutoFollow();}
function autoFollowPanel(){return '<section id="auto-duel-follow" class="auto-duel-follow" aria-label="MDPRO3 实时跟随"></section>';}
function paintAutoFollow(){
  const s=autoDuelState(),root=$('#auto-duel-follow'),run=s?.follow;if(!root||!s)return;
  const progress=$('#auto-duel-forecast-progress');
  if(progress&&s.plan?.temporary&&run)progress.textContent=`本局临时方案 · 已确认 ${s.plan.confirmed} 步。箭头仅浏览；实时完成证据或明确的手动确认写入操作历史。`;
  root.hidden=!autoFollowSupported(s);if(root.hidden)return;
  const value=run?.value,labels={syncing:'正在同步',following:'跟随中 · 尚未执行',executing:'执行中',completed:'路线已完成',paused:'已暂停',blocked:'路线受阻',needs_confirmation:'待确认'};
  if(!root.dataset.initialized){
    const actions=[['start','开始跟随'],['pause','暂停跟随'],['resume','恢复跟随'],['resync','重新同步'],['return','返回实时进度'],['manual','手动确认当前待执行步骤'],['plans','重新选择方案']];
    root.innerHTML=`<header><strong>MDPRO3 实时跟随</strong><span data-follow-status role="status"></span></header><p data-follow-reason></p><p data-follow-progress></p><div class="auto-duel-actions">${actions.map(([action,label])=>`<button type="button" data-auto-follow="${action}">${label}</button>`).join('')}</div><details class="auto-follow-live"><summary data-follow-live-title>实时场面 · 我方只读采样</summary><div data-follow-live-cards></div><p>初始起手保持冻结；下方教程棋盘显示方案预期场面。</p></details>`;
    root.dataset.initialized='true';
  }
  root.querySelector('[data-follow-status]').textContent=(labels[value?.status]||(run?.busy?'正在核对所选路线':'尚未同步'))+' · '+(value?.connected?'读取已连接':'读取未就绪');
  root.querySelector('[data-follow-reason]').textContent=run?.error||value?.reason||'进入教程后核对本局身份及已有操作；证据完整才自动推进。';
  root.querySelector('[data-follow-progress]').textContent=`实际已完成 ${value?.completed?.length||0} 步 · ${run?.viewLive?'正在查看实时进度':'正在手动浏览，自动跟随不会切换页面'}`;
  const disabled={start:!!run?.id,pause:!run?.id||value?.status==='paused',resume:!run?.id,resync:!run?.id,return:!value,manual:!value||value.status==='completed',plans:false};
  for(const button of root.querySelectorAll('[data-auto-follow]'))button.disabled=!!run?.busy||disabled[button.dataset.autoFollow];
  root.querySelector('[data-follow-live-title]').textContent='实时场面 · 我方只读采样'+(value?.sampled_ms?' · '+new Date(value.sampled_ms).toLocaleTimeString():'');
  const signature=JSON.stringify(value?.live_state||null);
  if(root.dataset.liveSignature!==signature){
    const known=value?.live_state?.cards||[],zones=[[2,'手牌'],[4,'怪兽区'],[8,'魔陷区'],[16,'墓地'],[32,'除外'],[64,'表侧额外'],[132,'叠放素材'],[192,'等待宿主入场的素材']];
    root.querySelector('[data-follow-live-cards]').innerHTML=value?.live_state?zones.map(([zone,label])=>`<p><strong>${label}</strong>：${known.filter(c=>c.location===zone).map(c=>escape(duelName(c.code))+'（'+(c.sequence+1)+'）').join('、')||'无'}</p>`).join(''):'<p>暂无经过一致性校验的实时场面。</p>';
    root.dataset.liveSignature=signature;
  }
  for(const node of document.querySelectorAll('[data-auto-duel-node]')){
    const progress=value?.steps?.find(step=>step.key===node.dataset.autoDuelNode);
    node.dataset.followState=progress?.status||'pending';
  }
}
async function handleAutoFollowClick(action){
  const s=autoDuelState(),run=s?.follow;if(!s)return;
  if(action==='start')return startAutoFollow(s);
  if(action==='plans'){if(run?.id)await pollAutoFollow(s,run,'pause');duelReach(duelStages.plans);renderDuel();return;}
  if(action==='return'&&run?.value){run.viewLive=true;acceptAutoFollow(s,run,run.value);return;}
  if(['pause','resume','resync','manual'].includes(action)&&run)return pollAutoFollow(s,run,action);
}
