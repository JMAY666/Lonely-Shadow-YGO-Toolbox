'use strict';

const DuelOrder = (()=>{
  const create=frame=>({frame,manual:null,error:''});
  function accept(state,frame) {
    if(state.frame?.round_id!==frame.round_id||frame.phase!=='detected')state.manual=null;
    state.frame=frame;state.error='';return state;
  }
  const selected=state=>state?.manual||state?.frame?.detected_order||null;
  const ready=state=>state?.frame?.phase==='detected'&&['first','second'].includes(selected(state));
  const confirmed=state=>ready(state)&&state.frame.confirmed?.order===selected(state)&&
    state.frame.confirmed.source===(state.manual!==null?'manual':'automatic');
  function confirmation(state) {
    if(!ready(state))throw Error('请等待本局先后攻识别完成。');
    const {monitor_id,round_id,revision}=state.frame;
    return {monitor_id,round_id,revision,order:selected(state),manual:state.manual!==null};
  }
  return {create,accept,selected,ready,confirmed,confirmation};
})();
if(typeof module!=='undefined')module.exports=DuelOrder;

const orderPhaseText={waiting_start:'等待游戏开始对局',rps:'正在猜拳',choose_order:'轮到你选择先攻或后攻',
  waiting_choice:'等待双方完成猜拳或先后攻选择',detected:'先后攻识别完成',ended:'本局已结束，等待下一局',
  disconnected:'暂时无法读取游戏，正在重试',unsupported:'当前游戏模式尚不支持识别'};
const orderLabel=value=>value==='first'?'先攻':value==='second'?'后攻':'等待确定';
let duelOrderTimer=null,duelOrderEpoch=0,duelOrderWatching=null;
function stopDuelOrderWatch() {clearTimeout(duelOrderTimer);duelOrderTimer=null;duelOrderWatching=null;++duelOrderEpoch;}
function syncDuelOrderWatch() {
  const s=duelState(),watch=!duelUI.busy&&s.operationMode==='automatic'&&s.stage===duelStages.order&&moduleUI.current==='duel'?s.automatic.order:null;
  if(watch===duelOrderWatching)return;
  stopDuelOrderWatch();if(!watch?.frame?.monitor_id)return;
  duelOrderWatching=watch;const epoch=duelOrderEpoch;
  const tick=async()=>{
    if(epoch!==duelOrderEpoch)return;
    try {
      const frame=await api('/api/ygopro/order/poll',{monitor_id:watch.frame.monitor_id});
      if(epoch!==duelOrderEpoch)return;
      const changed=JSON.stringify(watch.frame)!==JSON.stringify(frame);
      DuelOrder.accept(watch,frame);
      if(changed)renderDuel();
      const stamp=$('#duel-order-last-check');if(stamp)stamp.textContent=`持续监测中 · ${new Date().toLocaleTimeString()}`;
    } catch(error) {
      if(epoch!==duelOrderEpoch)return;
      const changed=watch.error!==error.message;
      watch.error=error.message;watch.frame={...watch.frame,phase:'disconnected',detected_order:null};watch.manual=null;
      if(changed)renderDuel();
    } finally {if(epoch===duelOrderEpoch)duelOrderTimer=setTimeout(tick,350);}
  };
  duelOrderTimer=setTimeout(tick,350);
}
function duelAutomaticOrderPage() {
  const state=duelState().automatic.order,frame=state?.frame||{},ready=DuelOrder.ready(state),selected=DuelOrder.selected(state);
  return `<section class="duel-order-panel" aria-labelledby="duel-order-title"><span class="duel-eyebrow">YGOPro · 自动识别</span><h2 id="duel-order-title">决定先／后攻</h2>
    <p class="duel-order-process">${escape(duelProcessText(duelState().automatic.connection))}</p>
    <div class="duel-order-status" role="status" aria-live="polite"><span class="duel-order-dot ${ready?'ready':''}"></span><strong id="duel-order-phase">${escape(orderPhaseText[frame.phase]||'正在连接监测')}</strong></div>
    <p>${frame.phase==='choose_order'?'请在 YGOPro 中选择先攻或后攻，工具箱会自动读取最终结果。':frame.phase==='rps'?'请在游戏中完成猜拳；平局会继续等待，不会提前判断。':'在游戏中开始对局并完成双方选择。此页面会持续监测，无需反复点击读取。'}</p>
    <div class="duel-order-result ${ready?'resolved':''}"><small>我方本局顺序</small><strong id="duel-order-result">${orderLabel(selected)}</strong><span>${ready?state.manual?`已手动更正 · 自动识别为${orderLabel(frame.detected_order)}`:'根据游戏本局开局数据识别':'等待正式开局后确定'}</span></div>
    <div class="duel-order-adjust" role="group" aria-label="手动更正先后攻"><span>更改结果</span>${duelButton('order-manual-first','先攻',!ready)}${duelButton('order-manual-second','后攻',!ready)}${duelButton('order-use-detected','使用自动结果',!ready||!state.manual)}</div>
    <p class="duel-order-error" role="alert">${escape(state?.error||frame.error||'')}</p><small id="duel-order-last-check">持续监测中</small>
    ${selected==='second'?'<p class="duel-order-note">后攻顺序会正常记录；后攻展开功能尚未开发。</p>':''}
    <div class="duel-order-links">${duelButton('recapture-process','重新连接进程')}</div></section>`;
}
function duelAutomaticConfirmedPage() {
  const confirmed=duelState().automatic.order?.frame?.confirmed;
  return `<section class="duel-order-panel"><span class="duel-eyebrow">先后攻已确认</span><h2>${orderLabel(confirmed?.order)} · 卡组展开</h2>
    <p>本局${orderLabel(confirmed?.order)}结果已记录${confirmed?.source==='manual'?'（手动更正）':''}。</p>
    <p>${confirmed?.order==='second'?'后攻展开功能尚未开发，当前保留本局判断与确认记录。':'已进入下一步；自动起手读取与展开流程将在后续接入。'}</p>
    ${duelButton('order-return','返回先后攻监测',false,true)}</section>`;
}
async function beginDuelOrder() {
  const draft=duelState().automatic;
  if(!draft.connection||!draft.deck||!draft.fresh)return duelTell('请先完成进程连接与卡组获取。');
  await duelWork(async()=>{
    const frame=await api('/api/ygopro/order/start',{capture_id:draft.connection.capture_id});
    draft.order=DuelOrder.create(frame);duelReach(duelStages.order);duelTell('');
  });
}
async function duelOrderAction(action) {
  const s=duelState(),state=s.automatic.order;
  if(s.operationMode!=='automatic')return false;
  if(action==='start-duel'){await beginDuelOrder();return true;}
  if(action==='order-return'){duelReach(duelStages.order);renderDuel();return true;}
  if(action.startsWith('order-manual-')){
    if(DuelOrder.ready(state))state.manual=action.endsWith('first')?'first':'second';renderDuel();return true;
  }
  if(action==='order-use-detected'){if(state)state.manual=null;renderDuel();return true;}
  if(action==='confirm-order'){
    if(!DuelOrder.ready(state))return true;
    const body=DuelOrder.confirmation(state);stopDuelOrderWatch();
    await duelWork(async()=>{
      try {const frame=await api('/api/ygopro/order/confirm',body);DuelOrder.accept(state,frame);duelReach(duelStages.hand);duelTell('');}
      catch(error){state.error=error.message;}
    });return true;
  }
  return false;
}
