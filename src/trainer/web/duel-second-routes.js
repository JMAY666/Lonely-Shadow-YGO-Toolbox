'use strict';

const SecondRouteModel={
  available:doc=>!!doc.route_panel?.current&&!doc.status_reason&&!doc.closed,
  step(step,doc){
    const s=step.bound_decision?.selection?.[0]||{},kind=step.automatic?'自动通过空响应':step.operation_label||
      ({summon:'通常召唤',special:'特殊召唤',activate:'发动',yes:'发动／确认',no:'不发动',card:'选择卡牌',material:'选择素材',select:'选择素材',unselect:'取消素材选择',place:'选择区域',option:'选择效果',finish_selection:'完成选择',spell_set:'盖放',pass:'放弃响应'}[s.kind]||'规则选择');
    const place=s.place?`${s.place[0]?'对手':'我方'}${s.place[1]===4&&s.place[2]>=5?`额外怪兽区（${s.place[2]===5?'左':'右'}）`:s.place[1]===8&&s.place[2]===5?'场地区':`${s.place[1]===4?'怪兽区':'魔陷区'}第 ${s.place[2]+1} 格`}`:'';
    const name=s.card?.code?secondName(doc,s.card.code):place;
    return `${kind} ${name}${step.effect_label?.text?' · '+step.effect_label.text:''}`;
  }
};
if(typeof module!=='undefined')module.exports=SecondRouteModel;

function secondRouteCards(doc,result,interactive){
  return `<div class="second-hint-items">${(result?.candidates||[]).map((c,i)=>`<article class="second-hint-item"><strong>路线 ${i+1} · ${c.remaining} 次剩余决策</strong><p>${escape(c.assumption)}</p>
    <p>预计投入：手牌 ${c.resource_cost?.hand??'未评估'}，主卡组 ${c.resource_cost?.main??'未评估'}，额外 ${c.resource_cost?.extra??'未评估'}。此前实际消耗不重复计入。</p>
    <p>预期终场：我方场上 ${c.evaluation?.board??'未评估'} 张，手牌 ${c.evaluation?.hand??'未评估'} 张。标记终场与后续能力按来源比较，阻抗次数未完整评价。</p>
    <small>隔离规则推演 · ${c.observation_required?'有随机结果待实际确认':'条件成立时的候选'} · ${escape(c.battle)}</small>
    <details><summary>操作顺序与来源</summary><ol>${c.steps.map(s=>`<li>${escape(SecondRouteModel.step(s,doc))}<small>${escape(s.source?.name||'')} / ${escape(s.source?.route_name||'')}</small></li>`).join('')}</ol></details>
    ${interactive?`<button type="button" data-second-route-choice="${c.id}" ${SecondRouteModel.available(doc)?'':'disabled'}>记录计划采用</button>`:''}</article>`).join('')||'<p>当前没有可展示路线。来源未覆盖、搜索未完成或存在未确认结果，都不等于规则上无解。</p>'}</div>`;
}

function secondRoutesPage(doc,readonly=false){
  const panel=doc.route_panel;if(!panel)return '';
  const sources=secondUI.nativeSources?.id===doc.id?secondUI.nativeSources:null;
  return `<section class="second-panel second-routes" id="second-routes"><h3>我方首回合 · 后攻路线续算</h3>
    <p id="second-route-status">${escape(panel.reason)}</p><p>本期接入有完整原生日志的本机内置后攻练习。实际出牌仍在原练习中操作；这里的方案选择只记录计划。外部平台和单独手填场面尚不能重建完整规则。</p>
    ${panel.linked&&panel.source_running===false?'<p>原练习已结束；当前以其最后记录的节点进行复盘规划，候选后续尚未实际发生。</p>':''}
    ${readonly?'':`<details ${panel.linked?'':'open'}><summary>关联或同步同一练习</summary><button type="button" data-second-route-action="sources" ${panel.supported?'':'disabled'}>查找匹配的内置后攻练习</button>
      ${sources?`<p>${escape(sources.notice)}</p><form id="second-route-sync-form"><label>相同构筑与原始起手<select name="source_id">${secondSelectOptions(sources.records.map(r=>[r.id,`${r.name} · 当前手牌 ${r.hand_count} 张 · 节点 ${r.checkpoint}`]),doc.native_link?.source)}</select></label><label><input type="checkbox" name="confirmed" required> 确认这是本局内置练习，导入其已发生的公开记录</label><button type="submit" ${sources.records.length?'':'disabled'}>重建并同步实际局面</button></form>`:''}
      ${panel.linked?'<button type="button" data-second-route-action="sync">同步原练习当前实际局面</button>':''}</details>
    ${panel.sources?`<form id="second-route-generate-form"><fieldset><legend>已有正式方案与妥协来源</legend>${panel.sources.map(s=>`<label><input type="checkbox" name="sources" value="${s.id}" ${panel.selected.includes(s.id)?'checked':''}>${escape(s.name)}</label>`).join('')||'<p>当前卡组没有 TAG 匹配的可用来源，请在原方案库补充并保存后重新同步。</p>'}</fieldset><label>本次目标<select name="goal">${secondSelectOptions([['clear','处理初始公开怪兽并建立来源终场'],['develop','仅比较来源展开终场']],panel.goal||'clear')}</select></label><label>比较偏好<select name="preference">${secondSelectOptions([['largest','终场最大'],['cheapest','花费最少'],['shortest','步骤最少'],['balanced','平均比较']],panel.preference)}</select></label><button type="submit" ${SecondRouteModel.available(doc)&&panel.status!=='running'?'':'disabled'}>从实际局面计算剩余路线</button></form>`:''}`}
    <div id="second-route-results">${panel.result?`<p>搜索 ${panel.result.complete?'在所选来源和预算内完成':'未完整完成'} · ${panel.result.seconds} 秒。${escape(panel.result.notice)}</p>${secondRouteCards(doc,panel.result,!readonly)}`:''}</div>
    <details><summary>已执行记录与规则状态</summary><p>已保留 ${doc.native_history?.length||0} 个按当时可知信息记录的原生边界。当前已用通常召唤：${doc.current.native_rules?.normal_summons_used?.[0]??'未重建'}；具体效果次数、费用与持续限制由重放核心检查。</p>
      <ol>${(doc.events||[]).filter(e=>e.kind==='native_sync').map(e=>`<li>${escape(e.summary)} · 节点 ${e.payload.checkpoint} · 观察版本 ${e.revision}</li>`).join('')}</ol></details>
    <details><summary>路线比较与计划历史 · ${panel.history.length} 次</summary>${panel.history.map(h=>`<details><summary>${new Date(h.created_ms).toLocaleString()} · 观察版本 ${h.revision}</summary><p>当时的推演比较，实际结果以观察记录为准。已记录计划 ${h.choices.length} 次。</p>${secondRouteCards(doc,h.result,false)}</details>`).join('')}</details></section>`;
}

async function secondRouteRequest(action,extra={}){
  const workspace=secondWorkspace();if(!workspace||secondUI.busy||secondUI.view||workspace.readonly)return;
  const generation=workspace.generation,doc=workspace.doc;
  secondUI.busy=true;$('#second-error').textContent='正在核对本机规则历史…';
  try{
    const value=await api('/api/second-duel/route-'+action,{id:doc.id,round_id:doc.input.round_id,revision:doc.revision,...extra});
    if(workspace!==secondWorkspace()||generation!==workspace.generation||secondUI.view)return;
    if(action==='sources')secondUI.nativeSources={id:doc.id,...value};else if(SecondDuelModel.accept(workspace.doc,value))workspace.doc=value;
    renderDuel();
  }catch(error){if(workspace===secondWorkspace()&&$('#second-error'))$('#second-error').textContent=error.message;}
  finally{secondUI.busy=false;}
}

function paintSecondRouteStatus(){
  const doc=secondDoc(),node=$('#second-route-status');if(!doc?.route_panel||!node)return;
  node.textContent=doc.route_panel.reason;
  for(const button of document.querySelectorAll('[data-second-route-choice],#second-route-generate-form button'))button.disabled=!SecondRouteModel.available(doc)||doc.route_panel.status==='running'||!!secondUI.view;
}

function mountSecondRoutes(){
  const doc=secondDoc();if(!doc?.route_panel)return;
  for(const button of document.querySelectorAll('[data-second-route-action]'))button.onclick=()=>void secondRouteRequest(button.dataset.secondRouteAction,button.dataset.secondRouteAction==='sync'?{source_id:doc.native_link.source,confirmed:true}:{});
  const sync=$('#second-route-sync-form');if(sync)sync.onsubmit=event=>{event.preventDefault();const d=new FormData(sync),source=secondUI.nativeSources.records.find(r=>r.id===d.get('source_id'));void secondRouteRequest('sync',{source_id:d.get('source_id'),stamp:source?.stamp,confirmed:d.has('confirmed')});};
  const generate=$('#second-route-generate-form');if(generate)generate.onsubmit=event=>{event.preventDefault();const d=new FormData(generate);void secondRouteRequest('generate',{sources:d.getAll('sources'),preference:d.get('preference'),goal:d.get('goal')});};
  for(const button of document.querySelectorAll('[data-second-route-choice]'))button.onclick=()=>void secondRouteRequest('choose',{candidate:button.dataset.secondRouteChoice});
  paintSecondRouteStatus();
}
