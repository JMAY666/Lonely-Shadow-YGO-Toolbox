'use strict';

const SecondHintModel=(()=>{
  const outcomes={pending:'已发动，尚未处理',resolved:'已结算',not_applied:'已结算但未适用',activation_negated:'发动被无效',effect_negated:'效果被无效'};
  const current=(doc,now=Date.now())=>!!doc.advice?.current&&!doc.status_reason&&!doc.closed&&
    doc.advice.revision===doc.revision&&doc.advice.window_id===doc.current.window?.id&&doc.advice.expires_ms>now;
  const select=(doc,cardId)=>doc.hint_options?.effects?.filter(e=>e.code===doc.current.cards.find(c=>c.id===cardId)?.code)||[];
  const effectStatus=(doc,effect,card)=>effect.limit==='none'?'无同名每回合次数限制':
    ({used:'已使用',unused:'尚未使用',unknown:'未核对'}[(doc.current.effect_counts?.[`${card.controller}:${effect.group}`]?.turn===doc.current.turn?
      doc.current.effect_counts[`${card.controller}:${effect.group}`].status:'unknown')])||'未核对';
  return {current,select,effectStatus,outcomes};
})();
if(typeof module!=='undefined')module.exports=SecondHintModel;

function secondHintItems(doc,hint,interactive){
  const labels={use:'现在使用（条件成立时）',hold:'暂时保留',information:'信息不足'};
  const conditions={met:'已满足所列规则条件',blocked:'当前指定响应不满足条件',unknown:'规则条件待核对'};
  return `<div class="second-hint-items">${hint.items.map(row=>`<article class="second-hint-item" data-hint-recommendation="${row.recommendation}">
    <strong>${escape(labels[row.recommendation])} · ${escape(secondName(doc,row.code))}</strong><p>${escape(row.reason)}</p>
    <small>${escape(conditions[row.conditions])} · ${row.example==='passed'?'有限本地案例已通过':'案例未验证'} · 本局引擎状态未重建</small>
    <details><summary>交与不交、费用及依据</summary><p>具体效果：${escape(row.label)}；${row.targeted?'取对象':'不取对象'}。所选动作／来源：${escape(hint.effect?.label||'待核对')}。</p>
      <p>效果属性：${row.attributes.map(a=>escape(doc.hint_options.attributes[a]||a)).join('＋')}。费用／投入：${escape(row.cost)}</p>
      <p>交：${escape(row.if_use)}</p><p>不交：${escape(row.if_hold)}</p>
      <p>生成提示时的实际交换：${escape(row.exchange.actual)}。</p><p>基准案例预计投入手牌 ${row.exchange.expected_hand_committed??'未评估'} 张，预计移除对手本体 ${row.exchange.expected_opponent_removed??'未评估'} 张；${row.exchange.prevented_deck_gain==null?(row.example==='passed'?'本次收益不折算为加牌张数':'阻止的潜在收益尚未评估'):`预计阻止牌组加牌 ${row.exchange.prevented_deck_gain} 张`}。各项分列，不累加为卡差。</p>
      <p>我方后攻资源：${escape(doc.hint_options.roles[row.role.role])}${row.role.note?'；'+escape(row.role.note):''}。投入后减少一张当前手牌；具体后攻路线和墓地再利用尚未验证。</p>
      <p>次数：${escape(row.limit)}。当前同名手牌 ${row.copies} 张；这里只列一个响应选择，不能将多张同名或互斥选项相加为可用阻抗。</p>
      ${row.blocked.length?`<ul>${row.blocked.map(t=>`<li>${escape(t)}</li>`).join('')}</ul>`:''}${row.missing.length?`<p>缺少或未覆盖：</p><ul>${row.missing.map(t=>`<li>${escape(t)}</li>`).join('')}</ul>`:''}
      <p>${row.sources.map((url,i)=>`<a href="${escape(url)}" target="_blank" rel="noreferrer">官方规则依据 ${i+1}</a>`).join(' · ')}</p>
    </details>
    ${interactive?`<div class="second-hint-actions"><button type="button" data-second-hint-choice="use" data-card="${row.instance_id}" ${row.conditions!=='met'||row.recommendation==='information'?'disabled':''}>记录计划使用</button><button type="button" data-second-hint-choice="hold" data-card="${row.instance_id}" ${row.recommendation==='information'?'disabled':''}>记录计划保留</button></div>`:''}
  </article>`).join('')||'<p>当前手牌没有本期覆盖的响应卡；其他效果尚未检查，不表示没有合法响应。</p>'}</div>`;
}

function secondHintsPage(doc,readonly=false){
  if(!doc.hint_options)return '';
  const hint=doc.advice,active=hint&&SecondHintModel.current(doc),options=doc.hint_options;
  const sourceCards=doc.current.cards.filter(c=>c.controller===1&&c.code&&options.effects.some(e=>e.code===c.code&&!e.responder));
  const knownCards=doc.current.cards.filter(c=>c.code&&![1,64].includes(c.location)&&options.effects.some(e=>e.code===c.code));
  const own=doc.current.cards.filter(c=>c.controller===0&&c.location===2&&options.responders.includes(c.code));
  const chosen=knownCards.find(c=>c.id===secondUI.selectedCard)||knownCards[0];
  const summaries=knownCards.filter((c,i,a)=>a.findIndex(other=>other.code===c.code&&other.controller===c.controller)===i);
  return `<section class="second-panel second-hints" id="second-hints"><div class="second-hint-heading"><h3>条件化交康提示</h3>${readonly?'':secondButton('generate-hint','生成／刷新提示',!doc.current.window?.analysis||!!doc.status_reason||doc.closed)}</div>
    <p id="second-hint-freshness">${hint?(active?'基于当前人工核对窗口':'提示已过期或属于历史窗口，不能继续采用'):'先核对次数、手牌用途及结构化窗口。只支持对手首回合主要阶段 1 的有限案例。'}</p>
    ${hint?`<p>${escape(hint.scope)}</p>${hint.missing.length?`<ul>${hint.missing.map(t=>`<li>${escape(t)}</li>`).join('')}</ul>`:''}${secondHintItems(doc,hint,!readonly&&active)}
    <details><summary>候选卡组与假设边界</summary><p>候选：${escape(hint.opponent_candidates.join('／')||'尚未确定')}。${escape(hint.candidate_basis)}。</p><ul>${hint.assumptions.map(t=>`<li>${escape(t)}</li>`).join('')}</ul><p>${escape(hint.coverage)}</p></details>
    <p>已记录的计划：${hint.decisions.map(d=>d.choice==='use'?'计划使用':'计划保留').join(' → ')||'尚未选择'}。记录计划不会扣牌或操作游戏；实际费用和结果仍需单独填报。</p>`:''}
    ${readonly?'':`<details class="second-hint-setup"><summary>核对次数和后攻保留用途</summary><ul>${summaries.map(c=>`<li>${c.controller?'对手':'我方'} ${escape(secondName(doc,c.code))}：${SecondHintModel.select(doc,c.id).map(e=>`${e.number}效果 ${escape(SecondHintModel.effectStatus(doc,e,c))}`).join('；')}</li>`).join('')}</ul>
      <form id="second-count-form"><label>已知卡片<select name="card_id">${secondSelectOptions(secondCardOptions(doc,knownCards),chosen?.id)}</select></label><label>具体效果<select name="effect_id">${secondSelectOptions(SecondHintModel.select(doc,chosen?.id).map(e=>[e.id,e.label]),null)}</select></label><label>本回合次数<select name="status">${secondSelectOptions([['unknown','尚未核对'],['unused','已核对尚未使用'],['used','已核对已经使用']],'unknown')}</select></label><label>说明／更正依据<input name="note" maxlength="500"></label><button type="submit">保存次数核对</button></form>
      <form id="second-role-form"><label>当前我方手牌<select name="card_id">${secondSelectOptions(secondCardOptions(doc,own),own[0]?.id)}</select></label><label>后攻保留用途<select name="role">${secondSelectOptions(Object.entries(options.roles),'unknown')}</select></label><label>具体起动、素材或费用用途<input name="note" maxlength="500"></label><button type="submit">保存保留用途</button></form>
      <form id="second-effect-observed-form"><label>本次实际发动的卡片<select name="card_id">${secondSelectOptions(secondCardOptions(doc,knownCards),chosen?.id)}</select></label><label>效果<select name="effect_id">${secondSelectOptions(SecondHintModel.select(doc,chosen?.id).map(e=>[e.id,e.label]),null)}</select></label><label>本次处理状态<select name="outcome">${secondSelectOptions(Object.entries(SecondHintModel.outcomes),'pending')}</select></label><label><input type="checkbox" name="confirmed" required> 已在游戏中实际发动；费用和区域变化另行记录。补录此前结果请使用下方关联入口</label><button type="submit">记录本次实际发动与次数</button></form>
      ${(doc.current.effect_actions||[]).length?`<form id="second-effect-outcome-form"><label>补充哪次发动的结果<select name="action_id">${secondSelectOptions(doc.current.effect_actions.map((a,i)=>[a.id,`${i+1}. 第 ${a.turn} 回合 · ${options.effects.find(e=>e.id===a.effect_id)?.label||a.effect_id} · ${SecondHintModel.outcomes[a.outcome]||'待核对'}`]),null)}</select></label><label>实际结果<select name="outcome">${secondSelectOptions(Object.entries(SecondHintModel.outcomes).filter(([key])=>key!=='pending'),'resolved')}</select></label><label>更正已有结果的依据<input name="note" maxlength="500"></label><button type="submit">关联并补充处理结果</button></form>`:''}
    </details>
    <details class="second-hint-setup"><summary>填写结构化响应窗口</summary><p>先在原“核对当前局面”保存手牌、公开区域和阶段，再提交此窗口。未核对项保留未知。</p>
      <form id="second-hint-window-form"><label>对手公开来源<select name="card_id">${secondSelectOptions(secondCardOptions(doc,sourceCards),sourceCards[0]?.id)}</select></label><label>具体发动效果<select name="effect_id">${secondSelectOptions(SecondHintModel.select(doc,sourceCards[0]?.id).filter(e=>!e.responder).map(e=>[e.id,e.label]),null)}</select></label>
      <label>所选效果是连锁几<input type="number" name="link" min="1" max="32" placeholder="未知留空"></label><label>当前最后连锁是几<input type="number" name="top" min="1" max="32" placeholder="未知留空"></label><label>最后连锁咒文速度<select name="speed">${secondSelectOptions([['','未知'],[1,'1：普通发动／诱发等'],[2,'2：速攻效果／普通陷阱等'],[3,'3：反击陷阱']],'')}</select></label>
      <label>其他影响响应的公开规则<select name="other_rules">${secondSelectOptions([['unknown','未完整核对'],['none','已核对没有其他影响'],['present','还有其他影响，超出本期范围']],'unknown')}</select></label><label>怪兽送墓<select name="grave_rule">${secondSelectOptions([['unknown','未核对'],['normal','已核对正常送墓'],['monster_banish','会改为除外']],'unknown')}</select></label>
      <fieldset><legend>已知保护（可多选，未知不要猜测）</legend>${Object.entries(options.protections).map(([key,label])=>`<label><input type="checkbox" name="protection" value="${key}">${escape(label)}</label>`).join('')}<label><input type="checkbox" name="protections_checked"> 已核对以上保护／无效状态；未勾选的项目确实不适用</label></fieldset>
      <label>比较目标<select name="objective">${secondSelectOptions([['balanced','综合比较'],['stop_effect','优先阻止当前效果处理'],['remove_body','优先移除当前本体'],['preserve','优先保留我方资源']],'balanced')}</select></label>
      <label>本局规则环境<select name="environment">${secondSelectOptions(doc.input.platform==='manual'?[['unknown','尚未核对'],['local','工具箱固定本地练习规则'],['external','外部平台：仅作本地案例参考']]:[['external','外部平台：仅作本地案例参考']],'unknown')}</select></label>
      <label><input type="checkbox" name="confirmed" required> 对手已实际发动所选效果，当前正在等待我方响应</label><button type="submit">确认结构化窗口</button></form>
    </details>`}
    <details><summary>提示与计划历史 · ${doc.advice_history?.length||0} 条</summary>${(doc.advice_history||[]).map(h=>`<details class="second-hint-history"><summary>${new Date(h.created_ms).toLocaleString()} · ${escape(h.effect?.label||'信息不足')}</summary><p>仅使用当时已知信息的条件比较，不是实际发生结果。</p>${secondHintItems(doc,h,false)}<p>当时计划：${h.decisions.map(d=>d.choice==='use'?'使用':'保留').join(' → ')||'未选择'}</p></details>`).join('')}</details>
  </section>`;
}

function paintSecondHintFreshness(){
  const doc=secondDoc(),target=$('#second-hint-freshness');if(!doc?.advice||!target)return;
  const active=SecondHintModel.current(doc)&&!secondUI.view&&!secondWorkspace()?.readonly;
  target.textContent=active?'基于当前人工核对窗口':'提示已过期或属于历史窗口，不能继续采用';
  for(const button of document.querySelectorAll('[data-second-hint-choice]')){
    const row=doc.advice.items.find(r=>r.instance_id===button.dataset.card);
    button.disabled=!active||!row||row.recommendation==='information'||button.dataset.secondHintChoice==='use'&&row.conditions!=='met';
  }
}

async function secondHintRequest(action,extra={}){
  const workspace=secondWorkspace();if(!workspace||secondUI.busy||secondUI.view)return;
  const generation=workspace.generation,doc=workspace.doc;
  const body={id:doc.id,round_id:doc.input.round_id,revision:doc.revision,request_id:crypto.randomUUID().replaceAll('-',''),...extra};
  secondUI.busy=true;$('#second-error').textContent=action==='advice'?'正在核对本地规则资源与案例…':'';
  try{const value=await api('/api/second-duel/'+action,body);if(workspace!==secondWorkspace()||generation!==workspace.generation)return;
    if(SecondDuelModel.accept(workspace.doc,value)){workspace.doc=value;renderDuel();}
  }catch(error){if(workspace===secondWorkspace()&&$('#second-error'))$('#second-error').textContent=error.message;}
  finally{secondUI.busy=false;paintSecondHintFreshness();}
}

function mountSecondHints(){
  const doc=secondDoc();if(!doc?.hint_options)return;
  const form=(selector,handler)=>{const node=$(selector);if(node)node.onsubmit=event=>{event.preventDefault();void handler(new FormData(node));};};
  form('#second-count-form',data=>secondSubmit('effect_count',Object.fromEntries(data)));
  form('#second-role-form',data=>secondSubmit('resource_role',Object.fromEntries(data)));
  form('#second-effect-observed-form',data=>secondSubmit('effect_observed',{...Object.fromEntries(data),confirmed:data.has('confirmed')}));
  form('#second-effect-outcome-form',data=>secondSubmit('effect_outcome',Object.fromEntries(data)));
  form('#second-hint-window-form',data=>secondSubmit('hint_window',{...Object.fromEntries(data),
    link:data.get('link')===''?null:Number(data.get('link')),top:data.get('top')===''?null:Number(data.get('top')),
    speed:data.get('speed')===''?null:Number(data.get('speed')),protections:data.getAll('protection'),
    protections_checked:data.has('protections_checked'),confirmed:data.has('confirmed')}));
  for(const selector of ['#second-count-form','#second-effect-observed-form','#second-hint-window-form']){
    const node=$(selector);if(!node)continue;
    node.elements.card_id.onchange=()=>{node.elements.effect_id.innerHTML=secondSelectOptions(SecondHintModel.select(doc,node.elements.card_id.value).map(e=>[e.id,e.label]),null);if(node.elements.confirmed)node.elements.confirmed.checked=false;};
  }
  const generate=$('[data-second-action="generate-hint"]');if(generate)generate.onclick=()=>void secondHintRequest('advice');
  for(const button of document.querySelectorAll('[data-second-hint-choice]'))button.onclick=()=>void secondHintRequest('advice-choice',{advice_id:doc.advice.id,card_id:button.dataset.card,choice:button.dataset.secondHintChoice});
  paintSecondHintFreshness();
}
