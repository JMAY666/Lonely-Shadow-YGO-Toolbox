'use strict';
const SecondBattleModel={current:(doc,h)=>!!doc.route_panel?.current&&!doc.closed&&!doc.status_reason&&h.revision===doc.revision&&h.origin.stamp===doc.native_link?.stamp};
if(typeof module!=='undefined')module.exports=SecondBattleModel;

function secondBattlePage(doc,readonly){
  const history=doc.battle_history||[];
  if(!doc.native_link&&!history.length)return '';
  const attackers=doc.current.cards.filter(c=>c.controller===0&&c.location===4&&c.code&&c.native_instance);
  const targets=doc.current.cards.filter(c=>c.controller===1&&c.location===4&&c.code&&c.native_instance&&[1,4].includes(c.position));
  if(secondUI.battleDraft?.id!==doc.id||secondUI.battleDraft?.revision!==doc.revision)secondUI.battleDraft={id:doc.id,revision:doc.revision,rows:[{attacker:attackers[0]?.id||'',target:'direct'}]};
  const ready=doc.route_panel?.current&&doc.route_panel?.battle_ready&&!doc.status_reason&&!readonly;
  const rows=secondUI.battleDraft.rows;
  return `<details class="second-panel second-battle" id="second-battle"><summary>指定攻击顺序的条件化验证</summary>
    <p>仅在隔离核心中演练指定顺序，假设双方不追加其他可选效果或响应。伤害、攻击资格及次数由核心处理；不操作原练习、不扣实际资源，不代表必胜或最优路线。</p>
    ${readonly?'':`<form id="second-battle-form">${rows.map((row,i)=>`<fieldset><legend>第 ${i+1} 次攻击尝试</legend><label>我方怪兽<select name="attacker-${i}">${secondSelectOptions(secondCardOptions(doc,attackers),row.attacker)}</select></label><label>目标<select name="target-${i}">${secondSelectOptions([['direct','直接攻击（仍须核心允许）'],...secondCardOptions(doc,targets)],row.target)}</select></label></fieldset>`).join('')}
      <div class="second-actions"><button type="button" data-battle-add ${rows.length>=12?'disabled':''}>增加下一次攻击</button><button type="button" data-battle-remove ${rows.length<=1?'disabled':''}>移除最后一项</button><button type="submit" ${ready&&attackers.length?'':'disabled'}>隔离验证指定顺序</button></div></form>`}
    <p id="second-battle-freshness">${ready?'基于当前已同步规则状态；未公开目标和无法确定的选择会停止验证':'请同步我方主要阶段 1 或战斗操作点；旧结果只供回看'}</p>
    <div>${[...history].reverse().map(h=>`<article class="second-hint-item" data-battle-history="${h.id}"><strong>${h.result.conditional_lethal?'条件分支中核心确认我方获胜':h.result.status==='validated'?'指定攻击顺序验证通过':'指定顺序未完整通过'}</strong><p><span class="second-battle-validity">${SecondBattleModel.current(doc,h)?'基于当前节点':'历史／过期节点'}</span> · ${new Date(h.created_ms).toLocaleString()}。${escape(h.result.reason)}</p>
      <p>演练 LP：我方 ${h.result.lp_before[0]} → ${h.result.lp_after[0]}，对手 ${h.result.lp_before[1]} → ${h.result.lp_after[1]}。已验证 ${h.result.steps.length} / ${h.result.requested} 次攻击尝试。</p>
      <details><summary>顺序、核心事件及前提</summary><ol>${h.result.steps.map(s=>`<li>${escape(secondName(doc,s.attacker_code))} → ${s.target_code?escape(secondName(doc,s.target_code)):'直接攻击'}<ul>${s.events.filter(e=>['damage','recovery','lp_cost'].includes(e.kind)).map(e=>`<li>${e.player?'对手':'我方'}${{damage:'受到伤害',recovery:'回复 LP',lp_cost:'支付 LP 费用'}[e.kind]} ${e.amount}</li>`).join('')||'<li>没有伤害／回复／LP 费用事件</li>'}</ul></li>`).join('')}</ol><ul>${h.result.assumptions.map(a=>`<li>${escape(a)}</li>`).join('')}</ul><p>${escape(h.result.notice)}。伤害事件本身不额外推断为战斗或效果伤害。</p></details></article>`).join('')}</div>
  </details>`;
}

function mountSecondBattle(){
  const form=$('#second-battle-form');if(!form)return;
  const save=()=>{for(let i=0;i<secondUI.battleDraft.rows.length;i++)secondUI.battleDraft.rows[i]={attacker:form.elements['attacker-'+i].value,target:form.elements['target-'+i].value};};
  form.onchange=save;
  form.querySelector('[data-battle-add]').onclick=()=>{save();if(secondUI.battleDraft.rows.length<12)secondUI.battleDraft.rows.push({...secondUI.battleDraft.rows.at(-1)});renderDuel();$('#second-battle').open=true;};
  form.querySelector('[data-battle-remove]').onclick=()=>{save();if(secondUI.battleDraft.rows.length>1)secondUI.battleDraft.rows.pop();renderDuel();$('#second-battle').open=true;};
  form.onsubmit=async event=>{event.preventDefault();save();await secondRouteRequest('battle',{request_id:crypto.randomUUID().replaceAll('-',''),order:secondUI.battleDraft.rows});if($('#second-battle'))$('#second-battle').open=true;};
}

function paintSecondBattle(){
  const doc=secondDoc(),form=$('#second-battle-form'),status=$('#second-battle-freshness');if(!doc||!form)return;
  const ready=doc.route_panel?.current&&doc.route_panel.battle_ready&&!doc.status_reason&&!doc.closed&&!secondUI.view;
  form.querySelector('button[type="submit"]').disabled=!ready||!doc.current.cards.some(c=>c.controller===0&&c.location===4&&c.code);
  for(const h of doc.battle_history||[]){const tag=$(`[data-battle-history="${h.id}"] .second-battle-validity`);if(tag)tag.textContent=SecondBattleModel.current(doc,h)?'基于当前节点':'历史／过期节点';}
  if(status&&!ready)status.textContent='当前规则节点已变化或不支持，旧演练仅供回看；请同步实际局面';
}
