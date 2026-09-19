'use strict';

// A separate observation workspace. None of these actions call native input,
// first-player matching, or the saved-plan mutation APIs.
const SecondDuelModel=(()=>{
  const zones={1:'牌组',2:'手牌',4:'怪兽区',8:'魔陷区',16:'墓地',32:'除外',64:'额外牌组',128:'叠放素材'};
  const phases={unknown:'待核对',draw:'抽卡阶段',standby:'准备阶段',main1:'主要阶段 1',battle:'战斗阶段',main2:'主要阶段 2',end:'结束阶段'};
  const hand=doc=>doc.current.cards.filter(c=>c.controller===0&&c.location===2);
  const validWindow=(doc,now=Date.now())=>!!doc.current.window&&!doc.status_reason&&!doc.closed&&doc.current.window.expires_ms>now;
  const event=(doc,kind,payload,id)=>({id:doc.id,round_id:doc.input.round_id,revision:doc.revision,event_id:id,kind,payload});
  const accept=(current,incoming)=>current?.id===incoming?.id&&current.input.round_id===incoming.input.round_id&&incoming.revision>=current.revision;
  return {zones,phases,hand,validWindow,event,accept};
})();
if(typeof module!=='undefined')module.exports=SecondDuelModel;

const secondUI={timer:null,request:0,busy:false,view:null,history:[],selectedCard:null};
function secondWorkspace(){const s=duelState();return s.operationMode==='automatic'?s.automatic.second:s.secondManual;}
function setSecondWorkspace(value){const s=duelState();if(s.operationMode==='automatic')s.automatic.second=value;else s.secondManual=value;}
function secondActive(){return !!secondWorkspace()&&duelState().stage>=duelStages.plans;}
function secondDoc(){return secondUI.view||secondWorkspace()?.doc;}
async function enterSecondHistory(){
  const request=++secondUI.request,owner=duelState(),result=await api('/api/second-duel/history',{}),latest=result.records.find(r=>!r.damaged);
  if(!latest){duelTell('暂无可回看的后攻记录');return;}
  const doc=await api('/api/second-duel/state',{id:latest.id});if(owner!==duelState()||request!==secondUI.request)return;
  owner.operationMode='manual';setSecondWorkspace({doc,generation:0,readonly:true});secondUI.view=doc;
  duelReach(duelStages.plans);renderDuel();
}
function secondName(doc,code){return code?doc.catalog?.[code]?.name||duelName(code):'未知卡牌';}
function secondSelectOptions(items,value){return items.map(([id,name])=>`<option value="${escape(String(id))}" ${String(id)===String(value)?'selected':''}>${escape(name)}</option>`).join('');}
function secondButton(action,label,disabled=false){return `<button type="button" data-second-action="${action}" ${disabled?'disabled':''}>${label}</button>`;}

async function startSecondDuel(automatic=false,smart=null){
  const owner=duelState(),draft=owner.automatic;
  let request;
  if(automatic){
    const frame=smart?.value?.frame||draft.order?.frame;
    if(!frame?.opening?.snapshot_id)throw Error('请先完整捕获后攻起手');
    request={request_id:smart?(smart.secondRequest||=crypto.randomUUID().replaceAll('-','')):crypto.randomUUID().replaceAll('-',''),
      round_id:frame.round_id,snapshot_id:frame.opening.snapshot_id,
      ...(smart?{recognition_id:smart.id}:{monitor_id:frame.monitor_id})};
  }else{
    request={request_id:crypto.randomUUID().replaceAll('-',''),deck_id:owner.deck.id,deck_revision:owner.deck.revision,opening:[...owner.hand],platform:'manual'};
  }
  const doc=await api('/api/second-duel/start',request);
  if(duelState()!==owner||automatic&&(owner.automatic!==draft||smart&&!smartAlive(smart))){await api('/api/second-duel/close',{id:doc.id,round_id:doc.input.round_id}).catch(()=>{});return;}
  if(automatic)await disposeAutoDuel();
  await detachSecondDuel(false);
  setSecondWorkspace({doc,generation:0});secondUI.view=null;secondUI.selectedCard=null;
  // Frozen observation text belongs to this record; never seed the shared live
  // catalog cache with an older snapshot after a resource update.
  void Promise.all([...new Set(doc.input.opening.cards)].map(code=>card(code).catch(()=>{}))).then(()=>{
    if(duelState()===owner&&secondWorkspace()?.doc.id===doc.id&&owner.stage===duelStages.hand)renderDuel();
  });
  owner.enabled=false;await syncDuelShortcuts();duelReach(duelStages.plans);duelTell('');renderDuel();
}

async function detachSecondDuel(invalidate=true){
  clearTimeout(secondUI.timer);secondUI.timer=null;++secondUI.request;secondUI.view=null;
  const workspace=secondWorkspace();if(!workspace)return;
  ++workspace.generation;
  if(workspace.readonly)return;
  if(invalidate&&!workspace.doc.closed){
    const body=SecondDuelModel.event(workspace.doc,'invalidate',{note:'离开后攻工作区，请重新核对当前局面'},crypto.randomUUID().replaceAll('-',''));
    try{const value=await api('/api/second-duel/event',body);if(secondWorkspace()===workspace)workspace.doc=value;}
    catch{workspace.doc.status_reason='当前连接或局面需要重新核对';}
  }
}

async function retireSecondDuel(workspace){
  ++workspace.generation;
  const s=duelState();if(s.secondManual===workspace)s.secondManual=null;if(s.automatic.second===workspace)s.automatic.second=null;
  clearTimeout(secondUI.timer);secondUI.timer=null;secondUI.view=null;
  const doc=workspace.doc;doc.status_reason='此工作区已关闭';
  if(workspace.readonly)return;
  try{await api('/api/second-duel/close',{id:doc.id,round_id:doc.input.round_id});}
  catch(error){duelTell('后攻记录已保留，关闭状态待核对：'+error.message);}
}

function secondCardView(doc,c){
  const name=secondName(doc,c.code),selected=secondUI.selectedCard===c.id;
  const position=[4,8].includes(c.location)?`${c.sequence==null?'位置待核对':`第 ${c.sequence+1} 格`} · ${{1:'表侧',4:'守备',8:'里侧'}[c.position]||'表示待核对'}`:c.location===128?'素材':'';
  return `<button type="button" class="second-card ${selected?'selected':''}" data-second-card="${escape(c.id)}" aria-pressed="${selected}"><img src="${c.code?'/pics/'+c.code+'.jpg':'/review-back.svg'}" alt=""><span>${escape(name)}</span>${position?`<small>${escape(position)}</small>`:''}</button>`;
}
function secondCardOptions(doc,cards){return cards.map(c=>[c.id,`${c.controller?'对手':'我方'} · ${SecondDuelModel.zones[c.location]} · ${secondName(doc,c.code)}`]);}
function secondPlacement(doc,materials=false){
  return `<label>场上位置（按我方视角）<select name="sequence">${secondSelectOptions([['','未核对'],[0,'第 1 格'],[1,'第 2 格'],[2,'第 3 格'],[3,'第 4 格'],[4,'第 5 格'],[5,'左额外区／场地区'],[6,'右额外区／第 7 格'],[7,'魔陷第 8 格']],'')}</select></label><label>表示形式<select name="position">${secondSelectOptions([['','未核对'],[1,'表侧攻击／表侧'],[4,'表侧守备'],[8,'里侧守备／盖放']],'')}</select></label>${materials?`<label>素材承载怪兽<select name="host_id">${secondSelectOptions([['','不适用'],...secondCardOptions(doc,doc.current.cards.filter(c=>c.location===4))],'')}</select></label>`:''}`;
}
function secondPlacementValues(data){return {sequence:data.get('sequence')===''?null:Number(data.get('sequence')),position:data.get('position')===''?null:Number(data.get('position')),host_id:data.get('host_id')||null};}
function secondHistoryView(doc){
  return `<details class="second-panel"><summary>实际观察历史 · ${doc.events.length} 项</summary><p>这里分别保留人工确认、只读资源核对和原生观察；推演不冒充实际发生的结果。</p><ol class="second-journal">${doc.events.map(e=>`<li><details><summary>${escape(e.summary)}</summary><p>${new Date(e.time_ms).toLocaleString()} · ${e.source==='readonly_public_snapshot'?'只读资源核对':e.source==='native_public_checkpoint'?'原生公开记录':'人工确认'} · 版本 ${e.revision}</p><p>当时阶段：${e.before.turn_player==null?'回合玩家待核对 · ':e.before.turn_player?'对手':'我方'}第 ${e.before.turn} 回合 · ${escape(SecondDuelModel.phases[e.before.phase])}</p><p>当时我方手牌：${e.before.cards.filter(c=>c.controller===0&&c.location===2).map(c=>escape(secondName(doc,c.code))).join('、')||'无'}</p><p>当时响应窗口：${escape(e.before.window?.label||'未确认')}</p>${e.payload.note?`<p>${escape(e.payload.note)}</p>`:''}</details></li>`).join('')}</ol></details>`;
}
function secondWorkspacePage(){
  const doc=secondDoc();if(!doc)return '';
  const state=doc.current,readonly=!!secondUI.view||secondWorkspace()?.readonly||doc.closed;
  const own=SecondDuelModel.hand(doc),visible=state.cards.filter(c=>c.controller===1||![1,2,64].includes(c.location));
  const moving=state.cards.filter(c=>c.controller===0||![1,2,64].includes(c.location));
  const selected=moving.find(c=>c.id===secondUI.selectedCard)||own[0]||moving[0];
  const draw=state.cards.filter(c=>c.controller===0&&c.location===1);
  const rules=[...state.usage.map(r=>({...r,category:'usage'})),...state.restrictions.map(r=>({...r,category:'restrictions'}))];
  return `<section class="second-workspace" id="second-workspace">
    <div class="duel-section-heading"><h2>${secondUI.view?'后攻记录回看':'BO1 后攻局面记录'}</h2><div class="second-actions">${secondUI.view&&!secondWorkspace()?.readonly?secondButton('back-live','返回当前记录'):''}${readonly&&!doc.closed&&!doc.input.connection?secondButton('resume','核对后继续记录此局'):''}${secondButton('history','历史记录')}${!readonly?secondButton('refresh','刷新记录')+secondButton('close','结束本局'):''}${!readonly&&doc.input.platform==='manual'?`<button type="button" data-second-route-action="${doc.native_link?'sync':'sources'}">${doc.native_link?'同步实际局面':'关联内置后攻练习'}</button>`:''}${duelButton('new','开始新一局')}</div></div>
    <p class="second-status" id="second-status" role="status"></p><p id="second-error" role="alert"></p>
    <div class="second-overview"><strong>${state.turn_player==null?'回合玩家待核对':(state.turn_player?'对手':'我方')+'回合'} · 第 ${state.turn} 回合 · ${escape(SecondDuelModel.phases[state.phase])}</strong><span>我方手牌 <b id="second-hand-count">${own.length}</b> 张</span><span>LP ${state.lp[0]} / ${state.lp[1]}</span></div>
    <p class="second-scope">开局来源：${doc.input.opening.source==='readonly_opening'?'只读捕获':'人工确认'}。${doc.native_link?'当前资源按关联内置练习的原生日志同步，原始起手保持不变。':doc.live_link?'当前已覆盖资源来自玩家核对的只读快照；原始起手保持不变。':'当前资源由玩家填报。'}条件提示覆盖已列本地案例，路线重建限有完整日志的内置后攻练习；外部平台规则未验证。指定攻击顺序可单独进行条件演练，未提供全面斩杀搜索。</p>
    ${typeof secondLivePage==='function'?secondLivePage(doc,readonly):''}
    ${typeof secondHintsPage==='function'?(state.turn_player===0?`<details class="second-panel"><summary>对手回合交康记录与条件提示</summary>${secondHintsPage(doc,readonly)}</details>`:secondHintsPage(doc,readonly)):''}
    ${typeof secondRoutesPage==='function'&&!doc.live_link?(state.turn_player===1?`<details class="second-panel" ${secondUI.nativeSources?.id===doc.id?'open':''}><summary>两阶段内置练习接入与后攻路线</summary>${secondRoutesPage(doc,readonly)}</details>`:secondRoutesPage(doc,readonly)):''}
    ${typeof secondBattlePage==='function'?secondBattlePage(doc,readonly):''}
    <details class="second-panel"><summary>原始起手 · ${doc.input.opening.cards.length} 张（保持不变）</summary><div class="second-opening">${doc.input.opening.cards.map(code=>`<figure><img src="/pics/${code}.jpg" alt=""><figcaption>${escape(secondName(doc,code))}</figcaption></figure>`).join('')}</div></details>
    <section class="second-panel"><h3>当前我方手牌</h3><div class="second-cards" id="second-hand">${own.map(c=>secondCardView(doc,c)).join('')||'<p>当前手牌为空</p>'}</div></section>
    <details class="second-panel" open><summary>已记录场面、墓地、除外与素材</summary><div class="second-public">${[0,1].map(player=>[4,8,16,32,128].map(zone=>{const rows=visible.filter(c=>c.controller===player&&c.location===zone);return rows.length?`<section><h4>${player?'对手':'我方'}${SecondDuelModel.zones[zone]}</h4><div class="second-cards">${rows.map(c=>secondCardView(doc,c)).join('')}</div></section>`:'';}).join('')).join('')||'<p>尚未录入这些区域；空白不代表已经核对为空。</p>'}</div></details>
    ${readonly||doc.native_link||doc.live_link?'':`<div class="second-editors"><details class="second-panel" open><summary>记录卡牌变化</summary>
      <form id="second-move-form"><label>卡牌实例<select name="card_id">${secondSelectOptions(secondCardOptions(doc,moving),selected?.id)}</select></label><label>实际去向<select name="to">${secondSelectOptions(Object.entries(SecondDuelModel.zones),16)}</select></label><label>原因<select name="reason">${secondSelectOptions([['cost','实际支付费用'],['effect','实际效果结果'],['summon','实际召唤'],['correction','人工更正']],'cost')}</select></label>${secondPlacement(doc,true)}<label>说明<input name="note" maxlength="1000" placeholder="费用、对象或更正原因"></label><button type="submit">记录移动</button></form>
      <form id="second-draw-form"><label>实际抽到的卡<select name="card_id">${secondSelectOptions(secondCardOptions(doc,draw),draw[0]?.id)}</select></label><button type="submit" ${!draw.length?'disabled':''}>记录实际抽牌</button></form>
    </details><details class="second-panel"><summary>录入对手公开卡牌／未知盖卡</summary><form id="second-opponent-form"><label>搜索公开卡名<input name="query" id="second-card-query" autocomplete="off" placeholder="输入卡名或卡号"></label><div id="second-card-results" class="second-search-results"></div><input type="hidden" name="code"><p id="second-card-selected">未选择公开卡牌</p><label><input type="checkbox" name="unknown"> 身份未知（不录入卡号）</label><label>所在区域<select name="location">${secondSelectOptions([[4,'怪兽区'],[8,'魔陷区'],[16,'墓地'],[32,'除外']],4)}</select></label>${secondPlacement(doc)}<label>既有未知卡公开身份<select name="reveal_id">${secondSelectOptions([['','新增观察'],...secondCardOptions(doc,state.cards.filter(c=>c.controller===1&&!c.code&&[4,8,16,32].includes(c.location)))],'')}</select></label><button type="submit">记录观察</button></form></details>
    <details class="second-panel"><summary>效果次数与持续限制</summary><form id="second-rule-form"><label>记录类别<select name="category">${secondSelectOptions([['usage','效果次数'],['restrictions','持续限制']],'usage')}</select></label><label>具体效果、范围与到期条件<textarea name="label" maxlength="500" required></textarea></label><label>状态<select name="status">${secondSelectOptions([['confirmed','已确认'],['unknown','尚不确定'],['expired','已到期／更正失效']],'unknown')}</select></label><button type="submit">添加规则记录</button></form></details></div>`}
    <details class="second-panel" ${rules.length?'open':''}><summary>规则记录 · ${rules.length} 项</summary><ul>${rules.map(r=>`<li>${escape(r.category==='usage'?'次数':'限制')} · ${escape({confirmed:'已确认',unknown:'尚不确定',expired:'已到期／失效'}[r.status])}：${escape(r.label)}${!readonly&&r.status!=='expired'?` <button type="button" data-second-expire="${r.id}" data-category="${r.category}">记录到期／更正</button>`:''}</li>`).join('')||'<li>尚无规则记录；不能据此推断没有限制。</li>'}</ul><p>文字记录供核对和复盘，尚未转换为引擎权限；换回合不会擅自清空次数。</p></details>
    ${readonly?'':`<details class="second-panel" open><summary>核对当前局面</summary><form id="second-verify-form" class="second-verify"><label>第几回合<input type="number" name="turn" min="1" max="999" value="${state.turn}" required></label><label>回合玩家<select name="turn_player" required>${secondSelectOptions([['','未核对'],[1,'对手'],[0,'我方']],state.turn_player)}</select></label><label>当前阶段<select name="phase">${secondSelectOptions(Object.entries(SecondDuelModel.phases),state.phase)}</select></label><label>我方 LP<input type="number" name="own_lp" min="0" max="2147483647" value="${state.lp[0]}" required></label><label>对手 LP<input type="number" name="opponent_lp" min="0" max="2147483647" value="${state.lp[1]}" required></label><label>对手手牌数量<input type="number" name="opponent_hand_count" min="0" max="120" value="${state.opponent_hand_count??''}" placeholder="未知留空"></label><label class="second-wide"><input type="checkbox" name="confirmed" required> 已核对当前手牌、双方公开区域和规则记录；未确认的信息仍保持未知</label><button type="submit">保存核对结果</button></form></details>
    <details class="second-panel"><summary>关键响应窗口与实际选择</summary><form id="second-window-form"><label>对手公开动作、具体效果、连锁与对象<textarea name="label" maxlength="500" required placeholder="只填写当时已公开的信息"></textarea></label><label><input name="confirmed" type="checkbox" required> 当前确实是我方可以响应的窗口</label><button type="submit">记录当前窗口</button></form><p>窗口记录最多保留 30 秒的当前标记；发生其他动作或离开后必须重新核对。</p><form id="second-note-form"><label>记录类型<select name="kind">${secondSelectOptions([['choice','玩家实际选择（包括不响应）'],['result','实际观察结果'],['invalidate','状态缺失／读取中断']],'choice')}</select></label><label>实际情况<textarea name="note" maxlength="1000" required></textarea></label><button type="submit">记录实际情况</button></form></details>`}
    ${secondHistoryView(doc)}<div id="second-history-list"></div>
  </section>`;
}

function paintSecondStatus(){
  const doc=secondDoc(),target=$('#second-status');if(!doc||!target)return;
  target.textContent=secondUI.view?'历史记录，仅供回看':doc.status_reason||(doc.native_link?doc.route_panel?.reason:'')||
    (SecondDuelModel.validWindow(doc)?`当前人工确认窗口：${doc.current.window.label}`:doc.current.window?'响应窗口已过期，请重新核对':'当前局面已人工核对；响应窗口尚未确认');
  target.dataset.valid=String(!doc.status_reason&&!secondUI.view);
  if(typeof paintSecondHintFreshness==='function')paintSecondHintFreshness();
  if(typeof paintSecondRouteStatus==='function')paintSecondRouteStatus();
  if(typeof paintSecondBattle==='function')paintSecondBattle();
  if(typeof paintSecondLive==='function')paintSecondLive();
}
async function secondSubmit(kind,payload){
  const workspace=secondWorkspace();if(!workspace||secondUI.busy||secondUI.view)return;
  const generation=workspace.generation;
  const body=SecondDuelModel.event(workspace.doc,kind,payload,crypto.randomUUID().replaceAll('-',''));
  secondUI.busy=true;$('#second-error').textContent='';
  try{
    const value=await api('/api/second-duel/event',body);
    if(secondWorkspace()!==workspace||generation!==workspace.generation)return;
    if(SecondDuelModel.accept(workspace.doc,value)){workspace.doc=value;renderDuel();}
  }catch(error){if(secondWorkspace()===workspace&&$('#second-error'))$('#second-error').textContent=error.message;}
  finally{secondUI.busy=false;}
}
function mountSecondDuel(){
  paintSecondStatus();clearTimeout(secondUI.timer);
  const doc=secondDoc(),workspace=secondWorkspace(),generation=workspace?.generation;if(!doc)return;
  const form=(id,fn)=>{const node=$(id);if(node)node.onsubmit=event=>{event.preventDefault();void fn(new FormData(node));};};
  form('#second-move-form',data=>{const card=doc.current.cards.find(c=>c.id===data.get('card_id'));return secondSubmit('move',{card_id:card?.id,from:card?.location,to:Number(data.get('to')),reason:data.get('reason'),note:data.get('note'),...secondPlacementValues(data)});});
  form('#second-draw-form',data=>secondSubmit('move',{card_id:data.get('card_id'),from:1,to:2,reason:'draw'}));
  form('#second-verify-form',data=>secondSubmit('verify',{turn:Number(data.get('turn')),turn_player:data.get('turn_player')===''?null:Number(data.get('turn_player')),phase:data.get('phase'),lp:[Number(data.get('own_lp')),Number(data.get('opponent_lp'))],opponent_hand_count:data.get('opponent_hand_count')===''?null:Number(data.get('opponent_hand_count')),confirmed:data.has('confirmed')}));
  form('#second-opponent-form',data=>{
    if(data.get('reveal_id')&&data.has('unknown')){$('#second-error').textContent='公开已有卡片身份时，请取消“身份未知”并选择实际公开卡牌';return;}
    return data.get('reveal_id')?secondSubmit('reveal',{card_id:data.get('reveal_id'),code:Number(data.get('code'))}):secondSubmit('opponent_card',{known:!data.has('unknown'),code:data.has('unknown')?null:Number(data.get('code')),location:Number(data.get('location')),...secondPlacementValues(data)});
  });
  form('#second-rule-form',data=>secondSubmit('rule',Object.fromEntries(data)));
  form('#second-window-form',data=>secondSubmit('window',{label:data.get('label'),confirmed:data.has('confirmed')}));
  form('#second-note-form',data=>secondSubmit(data.get('kind'),{note:data.get('note')}));
  for(const button of document.querySelectorAll('[data-second-card]'))button.onclick=()=>{
    secondUI.selectedCard=button.dataset.secondCard;const select=$('#second-move-form select[name="card_id"]');if(select)select.value=secondUI.selectedCard;
    for(const row of document.querySelectorAll('[data-second-card]')){const selected=row===button;row.classList.toggle('selected',selected);row.setAttribute('aria-pressed',String(selected));}
  };
  for(const button of document.querySelectorAll('[data-second-expire]'))button.onclick=()=>{
    const panel=document.createElement('form');panel.className='second-rule-correction';panel.innerHTML='<label>到期或更正依据<input name="note" maxlength="1000" required placeholder="例如：已进入新回合，上一回合限制到期"></label><button type="submit">确认记录</button>';
    button.after(panel);button.disabled=true;panel.onsubmit=event=>{event.preventDefault();void secondSubmit('rule_status',{category:button.dataset.category,rule_id:button.dataset.secondExpire,status:'expired',note:new FormData(panel).get('note')});};
  };
  for(const button of document.querySelectorAll('[data-second-action]'))button.onclick=run(()=>secondAction(button.dataset.secondAction));
  if(typeof mountSecondHints==='function')mountSecondHints();
  if(typeof mountSecondRoutes==='function')mountSecondRoutes();
  if(typeof mountSecondBattle==='function')mountSecondBattle();
  if(typeof mountSecondLive==='function')mountSecondLive();
  const query=$('#second-card-query');let searchVersion=0,timer;
  if(query)query.oninput=()=>{clearTimeout(timer);const version=++searchVersion,q=query.value.trim();timer=setTimeout(async()=>{
    if(!q)return;
    try{const result=await api('/api/cards?q='+encodeURIComponent(q));if(!query.isConnected||version!==searchVersion)return;
      $('#second-card-results').innerHTML=result.cards.slice(0,12).map(c=>`<button type="button" data-second-result="${c.id}">${escape(c.name)}</button>`).join('');
      for(const button of document.querySelectorAll('[data-second-result]'))button.onclick=()=>{const card=result.cards.find(c=>String(c.id)===button.dataset.secondResult);query.form.elements.code.value=card.id;$('#second-card-selected').textContent=card.name;};
    }catch(error){if(query.isConnected)$('#second-error').textContent=error.message;}
  },180);};
  const refresh=async()=>{
    if(secondWorkspace()!==workspace||generation!==workspace.generation||!secondActive()||moduleUI.current!=='duel')return;
    paintSecondStatus();
    if(!secondUI.busy&&!secondUI.view){
      try{const value=await api('/api/second-duel/state',{id:workspace.doc.id});if(secondWorkspace()!==workspace||generation!==workspace.generation)return;
        if(SecondDuelModel.accept(workspace.doc,value)){
          const changed=value.revision!==workspace.doc.revision;
          if(changed){workspace.doc.status_reason='记录已被更新，当前输入保留；请刷新记录后重新核对';paintSecondStatus();}
          else {const routeChanged=workspace.doc.route_panel?.status!==value.route_panel?.status||workspace.doc.route_panel?.history?.length!==value.route_panel?.history?.length;workspace.doc=value;if(routeChanged)renderDuel();else paintSecondStatus();}
        }
      }catch(error){if(secondWorkspace()===workspace){workspace.doc.status_reason='无法核对当前记录：'+error.message;paintSecondStatus();}}
    }
    secondUI.timer=setTimeout(refresh,1000);
  };
  secondUI.timer=setTimeout(refresh,1000);
}
async function secondAction(action){
  if(action==='close')return secondSubmit('close',{});
  if(action==='refresh'){
    const workspace=secondWorkspace(),generation=workspace.generation,doc=await api('/api/second-duel/state',{id:workspace.doc.id});
    if(workspace===secondWorkspace()&&generation===workspace.generation&&!secondUI.view){workspace.doc=doc;renderDuel();}return;
  }
  if(action==='back-live'){++secondUI.request;secondUI.view=null;renderDuel();return;}
  if(action==='resume'){
    ++secondUI.request;const doc=secondDoc(),workspace=secondWorkspace();if(doc.closed||doc.input.connection)return;
    if(!workspace.readonly&&workspace.doc.id!==doc.id)await retireSecondDuel(workspace);
    setSecondWorkspace({doc,generation:0});secondUI.view=null;renderDuel();await secondSubmit('resume',{});return;
  }
  if(action==='history'){
    const request=++secondUI.request,owner=secondWorkspace(),data=await api('/api/second-duel/history',{});if(owner!==secondWorkspace()||request!==secondUI.request||!$('#second-history-list'))return;
    $('#second-history-list').innerHTML=`<section class="second-panel"><h3>本地后攻记录</h3>${data.records.map(row=>`<button type="button" data-second-history="${row.id}" ${row.damaged?'disabled':''}>${escape(row.name)} · ${row.events||0} 项 · ${new Date(row.updated_ms).toLocaleString()}</button>`).join('')||'<p>暂无记录</p>'}</section>`;
    for(const button of document.querySelectorAll('[data-second-history]'))button.onclick=run(async()=>{
      const request=++secondUI.request,doc=await api('/api/second-duel/state',{id:button.dataset.secondHistory});if(owner!==secondWorkspace()||request!==secondUI.request)return;secondUI.view=doc;renderDuel();
    });
  }
}
