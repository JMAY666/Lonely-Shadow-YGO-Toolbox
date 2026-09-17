'use strict';

const DuelOpening=(()=>{
  const ready=frame=>frame?.phase==='detected'&&frame.opening?.status==='ready'&&!!frame.opening.snapshot_id;
  const first=frame=>frame?.confirmed?.order==='first';
  const confirmed=frame=>ready(frame)&&first(frame)&&frame.opening.confirmed?.snapshot_id===frame.opening.snapshot_id;
  function confirmation(frame){
    if(!ready(frame)||!first(frame))throw Error('请先核对先攻起手快照。');
    return {monitor_id:frame.monitor_id,round_id:frame.round_id,snapshot_id:frame.opening.snapshot_id};
  }
  return {ready,first,confirmed,confirmation};
})();
if(typeof module!=='undefined')module.exports=DuelOpening;

function duelOpeningCards(frame) {
  return `<div class="duel-opening-cards">${frame.opening.cards.map((code,index)=>`<article class="duel-opening-card">${duelReadCard(code)}<span>${index+1}. ${escape(duelName(code))}</span></article>`).join('')}</div>`;
}
function duelAutomaticOpeningPage() {
  const frame=duelState().automatic.order?.frame,opening=frame?.opening,second=frame?.confirmed?.order==='second',ready=DuelOpening.ready(frame);
  const status=opening?.status==='missed'?'未能确认本局初始起手':ready?`已获取 ${opening.cards.length} 张起手`:'正在等待起手发放';
  return `<section class="duel-opening-panel"><div class="duel-section-heading"><h2>${second?'后攻起手留存':'准备起手'}</h2><span>${orderLabel(frame?.confirmed?.order)}</span></div>
    <p id="duel-opening-status" role="status" aria-live="polite">${status}</p>
    ${ready?duelOpeningCards(frame):'<div class="duel-opening-wait">正在观察本局发牌，请保持游戏运行。</div>'}
    <p class="duel-opening-help">${ready?'这是本局最初发出的起手快照；后续抽牌、使用卡牌或调整手牌顺序不会替换它。':'请在游戏选择先后攻之前开启监测，工具箱会自动捕捉发牌。'}</p>
    ${second?'<p class="duel-order-note">后攻起手独立留存供后续开发；后攻不会进入先攻的准备起手与方案流程。</p>':''}
    <p class="duel-order-error" role="alert">${escape(duelState().automatic.order?.error||opening?.error||'')}</p>
    ${duelButton('order-return','返回先后攻监测')}</section>`;
}
function duelAutomaticOpeningNextPage() {
  const frame=duelState().automatic.order?.frame;
  return `<section class="duel-opening-panel"><div class="duel-section-heading"><h2>方案选择</h2><span>起手已确认</span></div>
    <p>已确认本局 ${frame.opening.cards.length} 张起手，后续方案选择将使用这份快照。</p>${duelOpeningCards(frame)}
    <p class="duel-opening-help">自动流程的方案匹配将在后续接入。当前起手与确认记录已保存。</p>${duelButton('opening-return','返回起手预览')}</section>`;
}
async function duelOpeningAction(action) {
  const s=duelState(),state=s.automatic.order;
  if(s.operationMode!=='automatic')return false;
  if(action==='opening-return'){duelReach(duelStages.hand);renderDuel();return true;}
  if(action==='confirm-opening'){
    if(!DuelOpening.ready(state?.frame)||!DuelOpening.first(state.frame))return true;
    const body=DuelOpening.confirmation(state.frame);stopDuelOrderWatch();
    await duelWork(async()=>{
      try {const frame=await api('/api/ygopro/opening/confirm',body);DuelOrder.accept(state,frame);duelReach(duelStages.plans);duelTell('');}
      catch(error){state.error=error.message;}
    });return true;
  }
  return false;
}
