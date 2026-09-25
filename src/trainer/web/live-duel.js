'use strict';

const LiveView=(()=>{
  const create=()=>({generation:0,value:null,draft:null,dirty:false,busy:false,error:'',search:[],timer:null,watchTimer:null,watch:false,muted:false});
  const current=(state,generation)=>state.generation===generation;
  const expired=(result,now=Date.now())=>!!result?.expires_at&&now>=result.expires_at;
  return {create,current,expired};
})();
if(typeof module!=='undefined')module.exports=LiveView;
const liveAssistanceState=()=>duelState().liveAssistance||(duelState().liveAssistance=LiveView.create());
const liveAssistanceActive=()=>!!duelState().liveAssistance?.value;
async function closeLiveRecord(session){
  const close=s=>api('/api/duel/live',{action:'update',operation:'close',id:s.id,revision:s.revision,request_id:crypto.randomUUID()});
  try{await close(session);}catch{
    try{const latest=await api('/api/duel/live',{action:'read',id:session.id});if(!latest.session.closed)await close(latest.session);}catch{}
  }
}
function clearLiveAssistance(){
  const v=duelState().liveAssistance;if(!v)return;
  ++v.generation;clearTimeout(v.timer);clearTimeout(v.watchTimer);v.watch=false;
  const session=v.value?.session;v.value=null;v.draft=null;v.busy=false;
  if(session&&!session.closed)void closeLiveRecord(session);
}
async function startLiveAssistance(){
  const v=liveAssistanceState();if(v.busy)return;
  const generation=++v.generation,input={...openingInput('duel'),supplemental:[]},key=openingKey('duel');
  v.busy=true;v.error='';
  try{
    const value=await api('/api/duel/live',{action:'start',format:'OCG',input});
    if(!LiveView.current(v,generation)||key!==openingKey('duel')){
      void closeLiveRecord(value.session);return;
    }
    v.value=value;v.draft=structuredClone(value.session.state);v.dirty=false;v.search=[];v.watch=!!value.session.capture_id;renderDuel();liveScheduleExpiry();liveScheduleWatch();
  }catch(error){duelTell(error.message);}
  finally{if(LiveView.current(v,generation))v.busy=false;}
}
async function liveCommand(operation,detail={},action='update'){
  const v=liveAssistanceState(),s=v.value?.session;if(!s||v.busy)return;
  if(v.dirty&&!['snapshot','close'].includes(operation)){v.error='请先保存当前局面，避免把新输入和旧建议混用。';const el=document.querySelector('[data-live-error]');if(el)el.textContent=v.error;return;}
  const generation=++v.generation;v.busy=true;v.error='';
  const primary=document.querySelector('[data-live-primary]');if(primary)primary.innerHTML='<h3>正在核对实际信息</h3><p>本次提交完成前，旧建议暂不可用。</p>';
  const controls=[...document.querySelectorAll('[data-live-workspace] button')].map(el=>[el,el.disabled]);controls.forEach(([el])=>el.disabled=true);
  try{
    const value=await api('/api/duel/live',{action,operation,id:s.id,revision:s.revision,request_id:crypto.randomUUID(),...detail});
    if(!LiveView.current(v,generation)||!v.value||v.value.session.id!==s.id)return;
    v.value=value;v.draft=structuredClone(value.session.state);v.dirty=false;
    if(operation==='close'){v.value=null;v.draft=null;}
    renderDuel();liveScheduleExpiry();
  }catch(error){
    if(LiveView.current(v,generation)){v.error=error.message;const el=document.querySelector('[data-live-error]');if(el)el.textContent=error.message+'；当前输入已保留。';}
  }finally{if(LiveView.current(v,generation)){v.busy=false;liveScheduleExpiry();liveScheduleWatch();}controls.forEach(([el,disabled])=>{if(el.isConnected)el.disabled=disabled;});}
}
function liveScheduleWatch(){
  const v=liveAssistanceState();clearTimeout(v.watchTimer);
  if(!v.watch||!v.value?.session.capture_id)return;
  const id=v.value.session.id;
  v.watchTimer=setTimeout(async()=>{
    if(!v.watch||v.value?.session.id!==id||moduleUI.current!=='duel')return;
    if(v.busy||v.dirty){liveScheduleWatch();return;}
    const generation=v.generation,revision=v.value.session.revision;
    try{
      const value=await api('/api/duel/live',{action:'observe',id,revision,request_id:crypto.randomUUID()});
      if(!LiveView.current(v,generation)||v.value?.session.id!==id)return;
      if(value.session.revision!==revision||value.analysis.knowledge_version!==v.value.analysis.knowledge_version){v.value=value;v.draft=structuredClone(value.session.state);v.error=value.session.observation_error||'';if(v.error)v.watch=false;renderDuel();liveScheduleExpiry();}
    }catch(error){if(LiveView.current(v,generation)){v.error=error.message;v.watch=false;const el=document.querySelector('[data-live-error]');if(el)el.textContent=error.message+'；自动观察已暂停，请刷新核对。';const primary=document.querySelector('[data-live-primary]');if(primary)primary.innerHTML='<h3>当前信息需要重新核对</h3>';}}
    finally{if(v.value?.session.id===id)liveScheduleWatch();}
  },1000);
}
async function liveRefresh(){
  const v=liveAssistanceState();if(!v.value||v.busy)return;
  const generation=++v.generation,id=v.value.session.id;v.busy=true;
  try{
    const value=await api('/api/duel/live',{action:'read',id});
    if(!LiveView.current(v,generation)||v.value?.session.id!==id)return;
    v.value=value;
    if(!v.dirty)v.draft=structuredClone(value.session.state);
    else{Object.keys(v.draft.known).forEach(k=>v.draft.known[k]=false);v.error='已刷新最新记录；你的输入仍保留，请重新核对后保存。';}
    renderDuel();
  }catch(error){v.error=error.message;const el=document.querySelector('[data-live-error]');if(el)el.textContent=error.message;}
  finally{if(LiveView.current(v,generation)){v.busy=false;liveScheduleExpiry();liveScheduleWatch();}}
}
function liveScheduleExpiry(){
  const v=liveAssistanceState();clearTimeout(v.timer);
  const expiry=v.value?.analysis.expires_at;if(!expiry)return;
  const generation=v.generation;
  v.timer=setTimeout(()=>{
    if(!LiveView.current(v,generation)||!v.value||moduleUI.current!=='duel')return;
    const summary=document.querySelector('[data-live-primary]');
    if(summary)summary.innerHTML='<h3>响应窗口需要重新确认</h3><p>旧建议已过期；请按游戏中的实际窗口核对。</p>';
    document.querySelectorAll('[data-live-choice]').forEach(el=>el.setAttribute('data-expired','true'));
  },Math.max(0,expiry-Date.now())+20);
}
const liveSelect=(name,values,selected,attrs='')=>`<select name="${name}" ${attrs}>${Object.entries(values).map(([value,label])=>`<option value="${escape(value)}" ${String(selected)===value?'selected':''}>${escape(label)}</option>`).join('')}</select>`;
const liveCardName=card=>card.name||openingName(card.code);
function liveCardRow(card,options){
  return `<article class="live-card-row" data-live-card="${escape(card.id)}"><strong>${escape(liveCardName(card))}</strong>
    <label>控制者${liveSelect('controller',{'0':'我方','1':'对方'},card.controller)}</label><label>区域${liveSelect('zone',options.zones,card.zone)}</label>
    <label>表示${liveSelect('faceup',{'true':'表侧／已知','false':'里侧'},card.faceup)}</label><label>效果状态${liveSelect('disabled',{'unknown':'未确认','false':'未被无效','true':'已被无效'},card.disabled==null?'unknown':card.disabled)}</label>
    <details><summary>等级、控制权与战斗</summary><label>当前等级<input name="level" type="number" min="0" max="255" value="${card.level??''}"></label><label>当前调整身份${liveSelect('tuner',{'unknown':'待确认','true':'调整','false':'非调整'},card.tuner==null?'unknown':card.tuner)}</label><label>原持有者${liveSelect('owner',{'0':'我方','1':'对方'},card.owner)}</label><label>实际攻击力<input name="attack" type="number" min="0" max="999999" value="${card.attack??''}"></label><label>确认剩余攻击次数<input name="attacks_left" type="number" min="0" max="20" value="${card.attacks_left??''}"></label><label><input name="attack_position" type="checkbox" ${card.attack_position?'checked':''}>攻击表示</label><label><input name="direct_attack_confirmed" type="checkbox" ${card.direct_attack_confirmed?'checked':''}>已核对可以直接攻击</label><label><input name="revealed" type="checkbox" ${card.revealed?'checked':''}>对方手牌身份当前仍公开可确认</label></details>
    <button type="button" data-live-remove="${escape(card.id)}">移除记录</button></article>`;
}
function liveSnapshotForm(v){
  const {session:s,options:o}=v.value,d=v.draft||s.state;
  const codeChoices=Object.fromEntries([...new Set([...s.deck.main,...s.deck.extra])].map(c=>[c,openingName(c)]));
  return `<details class="opening-fold" ${s.needs_sync||v.dirty?'open':''}><summary>核对当前资源 <small>原始起手始终保留</small></summary><div class="opening-fold-body"><form data-live-form="snapshot">
    <div class="live-form-grid"><label>当前回合<input name="turn" type="number" min="${s.state.turn}" max="100000" value="${d.turn}"></label><label>回合玩家${liveSelect('player',{'0':'我方','1':'对方'},d.player)}</label><label>阶段${liveSelect('phase',o.phases,d.phase)}</label><label>我方 LP<input name="lp0" type="number" min="0" value="${d.lp[0]}"></label><label>对方 LP<input name="lp1" type="number" min="0" value="${d.lp[1]}"></label><label>已用通常召唤<input name="normal_used" type="number" min="0" max="20" value="${d.normal_used??''}" placeholder="未确认"></label><label>已发动魔陷卡<input name="spell_trap_used" type="number" min="0" max="200" value="${d.spell_trap_used??''}" placeholder="未确认"></label><label>对方手牌张数<input name="opponent_hand" type="number" min="0" max="80" value="${d.opponent_hand??''}" placeholder="未确认"></label></div>
    <p class="opening-muted">按实际区域核对。检索或抽牌不自动补成某张卡；里侧对方卡和未公开手牌保留未知。</p>
    <div class="live-card-list">${d.cards.filter(c=>c.zone!=='extra'&&c.zone!=='deck').map(c=>liveCardRow(c,o)).join('')}</div>
    <details><summary>我方额外与已知回卡组记录 · ${d.cards.filter(c=>['extra','deck'].includes(c.zone)).length}</summary><div class="live-card-list">${d.cards.filter(c=>['extra','deck'].includes(c.zone)).map(c=>liveCardRow(c,o)).join('')}</div></details>
    <div class="live-add"><label>补入我方已知卡${liveSelect('own_add',codeChoices,'')}</label><label>去向${liveSelect('own_zone',o.zones,'hand')}</label><button type="button" data-live-add-own>添加实体卡</button></div>
    <div class="live-add"><label>对方已公开卡<input name="enemy_query" placeholder="输入卡名或卡号"></label><button type="button" data-live-search>搜索</button><label>结果${liveSelect('enemy_add',Object.fromEntries(v.search.map(c=>[c.code,c.name])),v.search[0]?.code||'')}</label><label>区域${liveSelect('enemy_zone',o.zones,'monster')}</label><button type="button" data-live-add-enemy>添加公开卡</button><button type="button" data-live-add-unknown>添加未知盖卡</button></div>
    <details><summary>已用效果与持续限制 · ${d.used.length} / ${d.limits.length}</summary><p>这里只补记已经发生的事实，不修改卡文或次数规则。</p><div class="live-log">${d.used.map((u,i)=>`<p>${escape(o.effects.find(e=>e.key===u.key)?.name||u.key)} · 效果 ${escape(u.key.split(':')[1])} · 第 ${u.turn} 回合 · ${u.player?'对方':'我方'} <button type="button" data-live-remove-used="${i}">更正移除</button></p>`).join('')}${d.limits.map((u,i)=>`<p>限制：${escape(o.effects.find(e=>e.key===u.key)?.label||u.key)} · 第 ${u.turn} 回合起 · ${u.player?'对方':'我方'} <button type="button" data-live-remove-limit="${i}">更正移除</button></p>`).join('')}</div><div class="live-add"><label>已发生的效果${liveSelect('fact_effect',Object.fromEntries(o.effects.map(e=>[e.key,e.name+' · '+e.label])),o.effects[0]?.key)}</label><label>玩家${liveSelect('fact_player',{'0':'我方','1':'对方'},0)}</label><label>发生回合<input name="fact_turn" type="number" min="1" max="${d.turn}" value="${d.turn}"></label><label>同名无效对应卡${liveSelect('fact_affected',codeChoices,'')}</label><button type="button" data-live-add-used>补记使用</button><button type="button" data-live-add-limit>补记已适用限制</button></div></details>
    <div class="live-confirm">${Object.entries({board:'双方当前场面已核对',hand:'当前手牌已核对',usage:'已用次数已核对',limits:'持续限制已核对'}).map(([k,label])=>`<label><input type="checkbox" name="known_${k}" ${d.known[k]?'checked':''}>${label}</label>`).join('')}</div><button class="primary" type="submit">保存当前局面</button></form></div></details>`;
}
function liveCollectDraft(){
  const v=liveAssistanceState(),form=document.querySelector('[data-live-form="snapshot"]');if(!form)return v.draft;
  const data=new FormData(form),d=structuredClone(v.draft||v.value.session.state);
  for(const field of ['turn','player'])d[field]=Number(data.get(field));d.phase=data.get('phase');d.lp=[Number(data.get('lp0')),Number(data.get('lp1'))];
  for(const field of ['normal_used','spell_trap_used','opponent_hand'])d[field]=data.get(field)===''?null:Number(data.get(field));
  for(const key of Object.keys(d.known))d.known[key]=data.has('known_'+key);
  for(const row of form.querySelectorAll('[data-live-card]')){
    const c=d.cards.find(c=>c.id===row.dataset.liveCard);if(!c)continue;
    for(const field of ['controller','owner'])c[field]=Number(row.querySelector(`[name="${field}"]`).value);
    c.zone=row.querySelector('[name="zone"]').value;c.faceup=row.querySelector('[name="faceup"]').value==='true';
    const disabled=row.querySelector('[name="disabled"]').value;c.disabled=disabled==='unknown'?null:disabled==='true';const tuner=row.querySelector('[name="tuner"]').value;c.tuner=tuner==='unknown'?null:tuner==='true';
    for(const field of ['attack','attacks_left','level']){const n=row.querySelector(`[name="${field}"]`).value;c[field]=n===''?null:Number(n);}
    for(const field of ['attack_position','direct_attack_confirmed','revealed'])c[field]=row.querySelector(`[name="${field}"]`).checked;
  }
  v.draft=d;return d;
}
function liveAssistancePage(){
  const v=liveAssistanceState(),{session:s,analysis:a,options:o}=v.value;
  const pending=s.events.filter(e=>e.kind==='activate'&&e.outcome==='pending');
  const eventChoices=Object.fromEntries(pending.map(e=>[e.id,(e.card.controller?'对方':'我方')+' · '+openingName(e.card.code)+' · 效果 '+e.effect]));
  const snapshotEvent=s.events.filter(e=>e.operation==='snapshot').at(-1);
  const cardChoices=Object.fromEntries(s.state.cards.filter(c=>c.code&&!['deck','extra'].includes(c.zone)).sort((a,b)=>({hand:0,monster:1,spell:2,grave:3,banished:4}[a.zone]-{hand:0,monster:1,spell:2,grave:3,banished:4}[b.zone])).map(c=>[c.id,(c.controller?'对方':'我方')+' · '+o.zones[c.zone]+' · '+liveCardName(c)]));
  const defaultActor=s.state.cards.find(c=>c.id===Object.keys(cardChoices)[0]),defaultCost=defaultActor&&o.effects.find(e=>e.code===defaultActor.code&&e.number===1)?.cost?defaultActor.id:'';
  const enabled=s.state.window&&!LiveView.expired(a),primary=enabled||!a.expires_at?a.primary:{text:'响应窗口需要重新确认',reason:'旧建议已过期；按当前游戏重新核对。'};
  return `<section class="opening-workspace live-workspace" data-live-workspace><div class="opening-toolbar"><div><h2>后攻实战辅助</h2><p class="opening-muted">OCG · 第 ${s.state.turn} 回合 · ${s.state.player?'对方':'我方'} · ${escape(o.phases[s.state.phase])}</p></div><div><button data-live-command="mute">${v.muted?'恢复建议':'静音建议'}</button><button data-live-command="refresh">刷新记录</button><button data-live-command="watch" ${!s.capture_id?'disabled':''}>${v.watch?'暂停自动观察':'启用自动观察'}</button><button data-live-command="observe" ${!s.capture_id?'disabled':''}>读取 YGOPro 公开局面</button><button data-live-command="close">结束辅助，返回起手</button></div></div><p class="opening-error" role="alert" data-live-error>${escape(v.error||s.observation_error||'')}</p>
    ${s.observation?`<section class="live-notice"><strong>已读取当前公开局面</strong><p>${escape(s.observation.note)}</p><button data-live-command="apply-observation">填入待核对表格</button></section>`:''}
    <div class="live-dashboard"><section class="opening-surface live-primary" data-live-primary>${v.muted?'<h3>建议已静音</h3><p>仍可核对局面和记录实际操作。</p>':`<span class="opening-eyebrow">当前建议 · ${a.window_id?'人工确认窗口':'参考'}</span><h3>${escape(primary.text)}</h3><p>${escape(primary.reason)}</p>${primary.choice?`<p class="opening-muted">${primary.choice.responding_to?'响应：'+escape(primary.choice.responding_to)+' · ':''}代价：${escape(primary.choice.cost)}</p>`:''}`}</section><section class="opening-surface"><h3>当前资源</h3><p>${s.state.cards.filter(c=>c.controller===0&&c.zone==='hand').map(c=>escape(liveCardName(c))).join('、')||'暂无已知手牌'}</p><small>起手 ${s.frozen.length} 张保留 · 已记录 ${s.events.length} 项事实</small><label>本局目标${liveSelect('goal',o.goals,s.goal,'data-live-goal')}</label></section></div>
    <div class="live-dashboard"><section class="opening-surface"><h3>对方意图</h3>${a.routes.map(r=>`<article class="live-route"><strong>${escape(r.title)}</strong>${openingPill(r.status)}<p>已见：${r.evidence.map(escape).join('、')}</p><p>${escape(r.summary)}</p><details><summary>可能后续与前提</summary>${r.next.map(n=>`<p>${escape(n.action)} → ${escape(n.result)}</p>`).join('')||'<p>当前路线受阻或缺少后续资料。</p>'}<p>${escape(r.condition)}</p><p>${escape(r.warnings)}</p></details></article>`).join('')||'<p>信息不足，继续观察公开动作；单张通用牌不确定牌型。</p>'}</section><section class="opening-surface"><h3>优先留意</h3>${a.threats.slice(0,3).map(t=>`<article class="live-route"><strong>${escape(t.name)}</strong>${openingPill(t.status)}<p>${escape(t.reason)}</p>${t.answers.map(x=>`<p>${escape(x)}</p>`).join('')}</article>`).join('')||'<p>当前资料中尚未识别具体威胁，不能据此认定场面安全。</p>'}</section></div>
    ${s.state.player===0?`<section class="opening-surface"><h3>我方回合的短段思路</h3><p class="opening-muted">${escape(a.own.note)}</p>${a.own.candidates.map((c,i)=>`<article class="live-route"><strong>${escape(c.label)}</strong>${openingPill('条件参考')}<ol>${c.steps.map(t=>`<li>${escape(t)}</li>`).join('')}</ol><p>${escape(c.reason)}</p><details><summary>被阻止／被放行后的衔接</summary><p>${escape(c.if_stopped)}</p><p>${escape(c.if_allowed)}</p><small>${escape(c.basis)}</small></details>${c.synchro?`<button data-live-record-synchro="${i}">记录游戏中已完成的这次同调</button>`:''}</article>`).join('')}${a.own.damage?`<p>条件伤害上限：${a.own.damage.amount}。${escape(a.own.damage.condition)}</p>`:''}</section>`:''}
    ${a.references?.length?`<details class="opening-fold"><summary>已保存方案的相关参考 <small>${a.references.length} 组</small></summary><div class="opening-fold-body">${a.references.map(r=>`<article class="live-route"><strong>${escape(r.title)}</strong><p>${escape(r.state_fit)} · ${escape(r.condition.reason)}</p><ol>${r.steps.map(step=>`<li>${escape(step)}</li>`).join('')}</ol><small>${escape(r.note)}</small></article>`).join('')}</div></details>`:''}
    <details class="opening-fold"><summary>使用与保留的比较 <small>${a.choices.length} 份手牌资源</small></summary><div class="opening-fold-body">${a.choices.map(c=>`<article class="live-route" data-live-choice><strong>${escape(c.name)}</strong>${openingPill({available:'已覆盖条件满足',conditional:'条件待核对',unavailable:'当前不适用'}[c.status])}<p>${escape(c.label)}${c.target_name?' · 对象：'+escape(c.target_name):''}</p><p>${c.reasons.map(escape).join('；')||'当前已覆盖条件满足；实际处理仍受对方响应影响。'}</p><p>代价：${escape(c.cost)}。${escape(c.consequence)}</p><small>${escape(c.basis)}</small><p><a href="${escape(c.source.url)}" data-opening-reference>官方卡文</a></p></article>`).join('')||'<p>当前手牌没有已覆盖的响应卡。</p>'}<p>保留：等待更关键的已知威胁或信息；当前放行可能让对方获得额外资源。</p></div></details>
    ${a.capabilities&&typeof CapabilityView!=='undefined'?`<details class="opening-fold"><summary>已知卡片的统一能力资料</summary><div class="opening-fold-body capability-grid">${Object.values(a.capabilities).map(card=>`<article><strong>${escape(card.name)}</strong>${CapabilityView.html(card)}</article>`).join('')}</div></details>`:''}
    ${liveSnapshotForm(v)}
    <div class="live-dashboard"><section class="opening-surface"><h3>确认当前响应窗口</h3><form data-live-form="window"><label>窗口${liveSelect('kind',{'chain':'正在连锁（选择最上方发动）','after_add':'对方实际从卡组加手后的窗口','open':'当前允许我方使用快速效果','none':'窗口已关闭'},'chain')}</label><label>连锁最上方${liveSelect('event_id',eventChoices,pending.at(-1)?.id||'')}</label><label><input type="checkbox" name="confirmed" required>我已核对游戏当前轮到自己响应</label><p class="opening-muted">确认有效期最多 15 秒；游戏变化时立即更新。自动快照不能证明完整连锁。</p><button class="primary">确认窗口</button><input type="hidden" name="snapshot_event" value="${escape(snapshotEvent?.id||'')}"></form></section>
    <section class="opening-surface"><h3>记录实际操作</h3><form data-live-form="action"><label>实际使用的卡${liveSelect('card_id',cardChoices,Object.keys(cardChoices)[0]||'')}</label><div class="live-form-grid"><label>动作${liveSelect('kind',{'activate':'发动效果','normal':'通常召唤','special':'特殊召唤','reveal':'公开确认','attack':'已经攻击'},'activate')}</label><label>效果编号<input name="effect" type="number" min="0" max="20" value="1"></label></div><label>实际支付的费用${liveSelect('cost_id',{'':'无／尚未支付',...cardChoices},defaultCost)}</label><label>费用实际去向${liveSelect('cost_zone',{'grave':'墓地','banished':'除外','deck':'卡组'},'grave')}</label><label><input type="checkbox" name="card_activation">本次是魔陷卡的发动（盖放后发动时勾选）</label><button>记录已发生动作</button></form>
    ${pending.length?`<form data-live-form="result"><label>待处理发动${liveSelect('event_id',eventChoices,pending[0].id)}</label><label>实际结果${liveSelect('outcome',{'resolved':'已成功处理','negated_activation':'发动被无效','negated_effect':'效果被无效','no_result':'没有取得结果'},'resolved')}</label><button>记录处理结果</button><p class="opening-muted">取得新牌或区域改变后，继续在资源表核对；不会自动恢复费用。</p></form>`:''}</section></div>
    <details class="opening-fold"><summary>保留资源与记录依据</summary><div class="opening-fold-body"><form data-live-form="preserve"><p>只改变本局策略偏好，不改效果规则。</p>${s.state.cards.filter(c=>c.controller===0&&c.zone==='hand').map(c=>`<label><input type="checkbox" name="preserve" value="${escape(c.id)}" ${s.preserve.includes(c.id)?'checked':''}>保留 ${escape(liveCardName(c))}</label>`).join('')}<button>保存保留偏好</button></form><ol class="live-history">${s.events.map(e=>`<li>${e.turn} 回合 · ${escape(e.card?openingName(e.card.code):'局面核对')} · ${escape(e.kind||e.operation)}${e.outcome?' · '+escape(e.outcome):''}${e.note?' · '+escape(e.note):''}</li>`).join('')}</ol><p>${a.gaps.map(escape).join('；')}</p><small>本地分析 ${a.elapsed_ms} ms · 状态 ${s.revision} · 资料 ${escape(a.knowledge_version.slice(0,10))}</small></div></details></section>`;
}
if(typeof document!=='undefined'){
  document.addEventListener('input',event=>{if(event.target.closest('[data-live-form="snapshot"]')){liveAssistanceState().dirty=true;liveCollectDraft();const el=document.querySelector('[data-live-primary]');if(el)el.innerHTML='<h3>当前有未保存的局面输入</h3><p>保存核对后再更新建议；编辑期间暂停自动观察。</p>';}});
  document.addEventListener('change',run(async event=>{if(event.target.matches('[data-live-goal]'))await liveCommand('preference',{goal:event.target.value,preserve:liveAssistanceState().value.session.preserve});else if(event.target.closest('[data-live-form="action"]')&&['card_id','effect','kind'].includes(event.target.name)){const form=event.target.closest('form'),v=liveAssistanceState(),c=v.value.session.state.cards.find(c=>c.id===form.elements.card_id.value),rule=v.value.options.effects.find(e=>e.code===c?.code&&e.number===Number(form.elements.effect.value));form.elements.cost_id.value=form.elements.kind.value==='activate'&&rule?.cost?c.id:'';form.elements.cost_zone.value='grave';}}));
  document.addEventListener('click',run(async event=>{
    const button=event.target.closest('button');if(!button||button.disabled)return;
    if(button.hasAttribute('data-live-start')){await startLiveAssistance();return;}
    if(!button.closest('[data-live-workspace]'))return;
    const v=liveAssistanceState(),command=button.dataset.liveCommand;
    if(command==='mute'){v.muted=!v.muted;liveCollectDraft();renderDuel();return;}
    if(command==='watch'){v.watch=!v.watch;liveCollectDraft();renderDuel();liveScheduleWatch();return;}
    if(command==='refresh'){await liveRefresh();return;}
    if(button.hasAttribute('data-live-record-synchro')){const route=v.value.analysis.own.candidates[Number(button.dataset.liveRecordSynchro)];if(route?.synchro)await liveCommand('synchro',{target_id:route.synchro.target_id,materials:route.synchro.materials,confirmed:true});return;}
    if(command==='observe'){if(v.dirty){v.error='请先保存或核对当前表格，再读取新局面。';renderDuel();return;}await liveCommand(null,{},'observe');return;}
    if(command==='apply-observation'){
      const x=v.value.session.observation;v.draft={...structuredClone(v.value.session.state),turn:x.turn,player:x.player,lp:x.lp,cards:structuredClone(x.cards),opponent_hand:x.opponent_hand,known:{board:false,hand:false,usage:false,limits:false}};v.dirty=true;renderDuel();return;
    }
    if(command==='close'){await liveCommand('close');return;}
    const d=liveCollectDraft(),form=document.querySelector('[data-live-form="snapshot"]');
    if(button.dataset.liveRemove){d.cards=d.cards.filter(c=>c.id!==button.dataset.liveRemove);v.dirty=true;renderDuel();return;}
    if(button.hasAttribute('data-live-search')){
      const query=form.elements.enemy_query.value.trim();if(!query)return;
      const generation=v.generation;const result=await api('/api/cards?'+(/^\d+$/.test(query)?'':'scope=name&')+'q='+encodeURIComponent(query));
      if(LiveView.current(v,generation)&&v.value){v.search=result.cards.slice(0,30).map(c=>({code:c.id,name:c.name}));renderDuel();}return;
    }
    for(const [attr,field] of [['data-live-remove-used','used'],['data-live-remove-limit','limits']])if(button.hasAttribute(attr)){d[field].splice(Number(button.getAttribute(attr)),1);v.dirty=true;renderDuel();return;}
    if(button.hasAttribute('data-live-add-used')||button.hasAttribute('data-live-add-limit')){
      const key=form.elements.fact_effect.value,definition=v.value.options.effects.find(e=>e.key===key),isLimit=button.hasAttribute('data-live-add-limit');
      if(isLimit&&!definition?.locks.length){v.error='这个效果没有已覆盖的持续限制。';renderDuel();return;}
      d[isLimit?'limits':'used'].push({key,player:Number(form.elements.fact_player.value),turn:Number(form.elements.fact_turn.value),...(!isLimit?{outcome:'resolved'}:definition.locks.includes('named_negation')?{affected_code:Number(form.elements.fact_affected.value)}:{})});v.dirty=true;renderDuel();return;
    }
    const own=button.hasAttribute('data-live-add-own'),enemy=button.hasAttribute('data-live-add-enemy'),unknown=button.hasAttribute('data-live-add-unknown');
    if(own||enemy||unknown){
      const code=unknown?0:Number(form.elements[own?'own_add':'enemy_add'].value);if(!unknown&&!code)return;
      const cardName=unknown?'未知盖卡':own?openingName(code):v.search.find(c=>c.code===code)?.name||openingName(code);
      d.cards.push({id:crypto.randomUUID().replaceAll('-',''),code,name:cardName,owner:own?0:1,controller:own?0:1,zone:unknown?'spell':form.elements[own?'own_zone':'enemy_zone'].value,faceup:!unknown,disabled:null,attack:null,attacks_left:null,attack_position:false,revealed:false});v.dirty=true;renderDuel();
    }
  }));
  document.addEventListener('submit',run(async event=>{
    const form=event.target.closest('[data-live-form]');if(!form)return;event.preventDefault();
    const v=liveAssistanceState(),data=new FormData(form),type=form.dataset.liveForm;
    if(type==='snapshot'){
      const draft=liveCollectDraft(),state=Object.fromEntries(['turn','player','phase','lp','cards','normal_used','spell_trap_used','opponent_hand','known','used','limits'].map(k=>[k,draft[k]]));await liveCommand('snapshot',{state});
    }else if(type==='action'){
      await liveCommand('action',{card_id:data.get('card_id'),kind:data.get('kind'),effect:Number(data.get('effect')),card_activation:data.has('card_activation'),costs:data.get('cost_id')?[{id:data.get('cost_id'),zone:data.get('cost_zone')}]:[]});
    }else if(type==='result')await liveCommand('result',{event_id:data.get('event_id'),outcome:data.get('outcome')});
    else if(type==='window')await liveCommand('window',{kind:data.get('kind'),event_id:data.get('kind')==='after_add'?data.get('snapshot_event'):data.get('event_id'),confirmed:data.has('confirmed')});
    else if(type==='preserve')await liveCommand('preference',{goal:v.value.session.goal,preserve:data.getAll('preserve')});
  }));
}
