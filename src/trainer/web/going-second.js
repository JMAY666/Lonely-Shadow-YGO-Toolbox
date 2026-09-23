'use strict';

// Every request is bound to both an input fingerprint and a view generation.
const OpeningView=(()=>{
  const create=()=>({serial:0,result:null,error:'',busy:false,supplemental:[],inputKey:null});
  const invalidate=s=>{++s.serial;s.result=null;s.error='';s.busy=false;};
  const accepts=(s,serial,key,current)=>s.serial===serial&&key===current;
  return {create,invalidate,accepts};
})();
if(typeof module!=='undefined')module.exports=OpeningView;
const openingIntel=OpeningView.create();
let openingIntelDeck=null;
const openingDuelState=()=>duelState().secondOpening||(duelState().secondOpening=OpeningView.create());
const openingIsSecond=()=>duelState().operationMode==='automatic'?duelState().automatic.order?.frame?.confirmed?.order==='second':!duelState().first;
function openingInput(scope){
  if(scope==='intel')return openingIntelDeck?{deck_id:openingIntelDeck.id,revision:openingIntelDeck.revision,hand:[]}:null;
  const s=duelState(),v=openingDuelState();
  if(s.operationMode==='manual')return s.deck?{deck_id:s.deck.id,revision:s.deck.revision,hand:s.hand,supplemental:v.supplemental}:null;
  const frame=s.automatic.order?.frame;
  if(!DuelOpening.ready(frame))return null;
  return {source:'automatic',monitor_id:frame.monitor_id,recognition_id:s.automatic.smartRun?.id,
    round_id:frame.round_id,snapshot_id:frame.opening.snapshot_id,deck_context:automaticDeckContext(),supplemental:v.supplemental};
}
function openingKey(scope){
  const s=duelState();
  return JSON.stringify([openingInput(scope),scope==='intel'?intelUI.tab:[s.session,s.stage,s.operationMode,openingIsSecond(),s.automatic.smartRun?.cycle,s.automatic.smartRun?.value?.reading_error],moduleUI.current]);
}
function clearSecondOpening(){
  if(!duelState().secondOpening)return;
  OpeningView.invalidate(duelState().secondOpening);duelState().secondOpening.supplemental=[];
}
function openingPaint(scope){if(scope==='intel')openingIntelRender();else if(moduleUI.current==='duel')renderDuel();}
async function openingAnalyze(scope){
  const state=scope==='intel'?openingIntel:openingDuelState(),input=openingInput(scope);
  if(!input)return;
  const serial=++state.serial,key=openingKey(scope);state.result=null;state.error='';state.busy=true;openingPaint(scope);
  try{
    const result=await api('/api/opening/analyze',input);
    if(!OpeningView.accepts(state,serial,key,openingKey(scope)))return;
    state.result=result;state.inputKey=key;
  }catch(error){if(OpeningView.accepts(state,serial,key,openingKey(scope)))state.error=error.message;}
  finally{if(state.serial===serial){state.busy=false;openingPaint(scope);}}
}
const openingName=code=>app.cache.get(Number(code))?.name||`卡号 ${code}`;
function openingCard(code){
  const report={id:'opening-catalog',catalog:Object.fromEntries(app.cache),events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  return `<div class="opening-card">${reviewCard({code,name:openingName(code),identity_known:true},'catalog',{report,face:true,zone:false,position:false,catalogue:true})}<span>${escape(openingName(code))}</span></div>`;
}
function openingResult(result,editable=false){return renderOpeningOverview(result,editable);}
function openingNote(key,result,editable){
  const note=result.notes[key];
  return editable?`<form data-opening-form="note" data-key="${escape(key)}"><label>局部备注（只供阅读，不参与计算）<textarea name="note" maxlength="4000">${escape(note?.text||'')}</textarea></label>${note&&note.version!==result.source_version?'<p>备注来源版本已变化，请重新核对。</p>':''}<button type="submit">保存备注</button></form>`:note?`<p>个人备注：${escape(note.text)}</p>`:'';
}
function secondOpeningPage(){
  const s=duelState(),state=openingDuelState(),automatic=s.operationMode==='automatic',frame=s.automatic.order?.frame;
  const frozen=automatic?frame?.opening?.cards||[]:s.hand;
  const deck=automatic?s.automatic.deck?.deck:s.deck?.deck;
  const ready=automatic?DuelOpening.ready(frame):!DuelModel.handError(deck,s.count,s.hand);
  if(state.result&&state.inputKey!==openingKey('duel'))OpeningView.invalidate(state);
  return `<section class="opening-workspace" data-opening-scope="duel"><div class="opening-toolbar"><h2>后攻起手分析</h2><button class="primary" data-opening-analyze ${!ready||state.busy?'disabled':''}>${state.busy?'正在本地分析…':state.result?'重新分析':'分析后攻起手'}</button></div>${automatic?`<div class="duel-opening-panel">${duelOpeningCards(frame)}<p>本局冻结起手</p></div>`:!state.result?'<p class="opening-muted">选好上方手牌后开始分析，修改手牌会清除旧结果。</p>':''}
    <details class="opening-resource-tools"><summary>人工补充资源 · ${state.supplemental.length} 张</summary><p>用于额外已知手牌的资源评估，不自动扣除已经用掉的牌，也不修改初始快照。</p><div class="opening-supplement">${state.supplemental.map((code,i)=>`<span>${escape(openingName(code))}<button data-opening-remove="${i}" aria-label="移除补充的${escape(openingName(code))}">×</button></span>`).join('')}</div><select aria-label="人工补充卡牌" data-opening-supplement>${[...new Set(deck?.main||[])].map(code=>`<option value="${code}">${escape(openingName(code))}</option>`).join('')}</select><button data-opening-add ${!ready?'disabled':''}>添加已知手牌</button></details><p role="alert" class="opening-error">${escape(state.error)}</p>${state.result?openingResult(state.result):''}</section>`;
}
async function openingIntelLoad(){
  OpeningView.invalidate(openingIntel);openingIntelDeck=null;openingIntelRender();
}
function openingIntelRender(){
  if(intelUI.tab!=='opening')return;
  $('[data-intel-count="opening"]').textContent='本地';
  $('#intel-actions').innerHTML='';$('#intel-controls').innerHTML='';$('#intel-list').innerHTML='';
  $('#intelligence .intel-layout').classList.add('opening-intel-layout');
  $('#intel-editor').innerHTML=`<section class="opening-workspace" data-opening-scope="intel"><h2>起手分析工作区</h2><p>从本地正式方案归纳基本思路与效果分工；只在本机处理。先选择构筑，再查看或维护通用展示选择。</p><label>构筑<select data-opening-deck><option value="">请选择构筑</option>${intelUI.decks.map(d=>`<option value="${escape(d.id)}" ${d.id===openingIntelDeck?.id?'selected':''}>${escape(d.name)}</option>`).join('')}</select></label><button data-opening-analyze ${!openingIntelDeck||openingIntel.busy?'disabled':''}>${openingIntel.busy?'正在归纳…':'重新归纳'}</button><p class="opening-error" role="alert">${escape(openingIntel.error)}</p>${openingIntel.result?`<form data-opening-form="settings"><fieldset><legend>分析参数</legend><label>双主相对比例<input type="number" name="dual_ratio" min="0.01" max="1" step="0.01" value="${openingIntel.result.settings.dual_ratio}"></label><label>第二系列最低浓度<input type="number" name="dual_minimum" min="0.01" max="1" step="0.01" value="${openingIntel.result.settings.dual_minimum}"></label><label>代表方案上限<input type="number" name="representatives" min="1" max="10" value="${openingIntel.result.settings.representatives}"></label></fieldset><button>保存参数</button></form>${openingResult(openingIntel.result,true)}`:''}</section>`;
}
async function openingSave(action,key,value){
  const result=openingIntel.result;if(!result||openingIntel.busy)return;
  const input=openingInput('intel'),effect=result.knowledge.find(e=>e.key===key),serial=++openingIntel.serial,identity=openingKey('intel');
  openingIntel.busy=true;intelUI.busy=true;
  const controls=[...document.querySelectorAll('[data-opening-scope="intel"] input,[data-opening-scope="intel"] select,[data-opening-scope="intel"] textarea,[data-opening-scope="intel"] button')].map(el=>[el,el.disabled]);
  for(const [el] of controls)el.disabled=true;
  try{
    await api('/api/opening/save',{action,key,value,input,revision:result.revision,source_version:result.source_version,version:effect?.version});
    if(!OpeningView.accepts(openingIntel,serial,identity,openingKey('intel')))return;
    intelUI.dirty=false;openingIntel.busy=false;await openingAnalyze('intel');
  }catch(error){if(OpeningView.accepts(openingIntel,serial,identity,openingKey('intel'))){openingIntel.error=error.message;const el=$('[data-opening-scope="intel"] .opening-error');if(el)el.textContent='保存失败：'+error.message+'；输入已保留。';}}
  finally{intelUI.busy=false;for(const [el,disabled] of controls)if(el.isConnected)el.disabled=disabled;if(openingIntel.serial===serial)openingIntel.busy=false;}
}
if(typeof document!=='undefined'){
  document.addEventListener('click',run(async event=>{
    const link=event.target.closest('[data-opening-reference]');if(link&&window.trainerDesktop?.openReferenceLink){event.preventDefault();await window.trainerDesktop.openReferenceLink(link.href);return;}
    const button=event.target.closest('button'),host=button?.closest('[data-opening-scope]');if(!host||button.disabled)return;
    const scope=host.dataset.openingScope,state=scope==='intel'?openingIntel:openingDuelState();
    if(button.hasAttribute('data-opening-analyze')){if(scope==='intel'&&!await intelDiscard())return;intelUI.dirty=false;await openingAnalyze(scope);return;}
    if(button.hasAttribute('data-opening-add')){
      const code=Number(host.querySelector('[data-opening-supplement]').value),input=openingInput(scope),s=duelState(),deck=s.operationMode==='automatic'?s.automatic.deck.deck:s.deck.deck;
      const hand=[...(input.hand||s.automatic.order.frame.opening.cards),...state.supplemental,code];
      if((DuelModel.counts(hand).get(code)||0)>(DuelModel.counts(deck.main).get(code)||0)){state.error='补充后数量超过构筑实际副本数';openingPaint(scope);return;}
      state.supplemental.push(code);OpeningView.invalidate(state);openingPaint(scope);return;
    }
    if(button.hasAttribute('data-opening-remove')){state.supplemental.splice(Number(button.dataset.openingRemove),1);OpeningView.invalidate(state);openingPaint(scope);return;}
    if(button.dataset.openingCommand)await openingSave(button.dataset.openingCommand,button.dataset.key);
  }));
  document.addEventListener('change',run(async event=>{
    if(event.target.matches('[data-opening-deck]')){
      const id=event.target.value;if(!await intelDiscard()){event.target.value=openingIntelDeck?.id||'';return;}
      intelUI.dirty=false;const serial=++openingIntel.serial;openingIntel.result=null;openingIntelDeck=null;
      if(!id){openingIntelRender();return;}
      try{const saved=await api('/api/deck?id='+encodeURIComponent(id));if(openingIntel.serial!==serial||intelUI.tab!=='opening')return;openingIntelDeck=saved;await Promise.all([...new Set([...saved.deck.main,...saved.deck.extra])].map(c=>card(c)));await openingAnalyze('intel');}
      catch(error){openingIntel.error=error.message;openingIntelRender();}
    }
  }));
  document.addEventListener('input',event=>{if(event.target.closest('[data-opening-form]'))intelUI.dirty=true;});
  document.addEventListener('submit',run(async event=>{
    const form=event.target.closest('[data-opening-form]');if(!form)return;event.preventDefault();
    const data=new FormData(form),action=form.dataset.openingForm;
    let value=action==='note'?data.get('note'):action==='settings'?Object.fromEntries(['dual_ratio','dual_minimum','representatives'].map(k=>[k,Number(data.get(k))])):{roles:data.getAll('role'),priority:data.get('priority'),note:data.get('note')};
    if(action==='override'&&data.get('order')==='reverse')value.roles.reverse();
    await openingSave(action,form.dataset.key,value);
  }));
}
