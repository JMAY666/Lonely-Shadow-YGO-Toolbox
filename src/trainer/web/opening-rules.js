'use strict';
// Presentation only. All matching and copy assignment use the service evaluator.
const OpeningRules = (() => {
  const labels={category:'卡牌类别',monster_kind:'怪兽种类',level:'等级',rank:'阶级',link:'连接值',attribute:'属性',race:'种族',code:'指定卡牌',setcode:'数据库系列编号'};
  const options={category:{monster:'怪兽',spell:'魔法',trap:'陷阱'},monster_kind:{normal:'通常',effect:'效果',ritual:'仪式',fusion:'融合',synchro:'同调',xyz:'超量',pendulum:'灵摆',link:'连接',tuner:'调整',non_tuner:'非调整',spirit:'灵魂',union:'同盟',gemini:'二重',flip:'反转',toon:'卡通'},attribute:{1:'地',2:'水',4:'炎',8:'风',16:'光',32:'暗',64:'神'},race:Object.fromEntries(['战士','魔法师','天使','恶魔','不死','机械','水','炎','岩石','鸟兽','植物','昆虫','雷','龙','兽','兽战士','恐龙','鱼','海龙','爬虫类','念动力','幻神兽','创造神','幻龙','电子界','幻想魔'].map((v,i)=>[2**i,v]))};
  const is=value=>value?.kind==='condition';
  const has=conditions=>['slots','banned'].some(k=>(conditions?.[k]||[]).some(v=>v&&typeof v==='object'));
  const safe=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function describe(value,catalog={}) {
    if(value===null||value===undefined)return '随机补齐';
    if(typeof value==='number')return catalog[value]?.name||`卡号 ${value}`;
    if(!is(value)||value.version!==1)return '不支持的条件牌（请更新或重新编辑）';
    function text(n,depth=0){
      if(!n||depth>6)return '无效条件';
      if(n.op==='not')return `排除（${text(n.items?.[0],depth+1)}）`;
      if(['all','any'].includes(n.op))return `（${(n.items||[]).map(c=>text(c,depth+1)).join(n.op==='all'?' 且 ':' 或 ')}）`;
      const label=labels[n.field]||'不支持的字段';
      if(n.op==='between')return `${label} ${n.min}–${n.max}`;
      if(['eq','gte','lte'].includes(n.op))return `${label} ${{eq:'=',gte:'≥',lte:'≤'}[n.op]} ${n.value}`;
      return (n.op==='not_in'?'排除':'')+label+'：'+(n.values||[]).map(v=>n.field==='code'?describe(v,catalog):options[n.field]?.[v]||String(v)).join(' / ');
    }
    const r=value.rule;
    if(r?.op==='all'&&r.items?.length===2){
      const level=r.items.find(n=>n.field==='level'&&n.op==='eq'),tuner=r.items.find(n=>n.field==='monster_kind'&&n.op==='in'&&JSON.stringify(n.values)==='["tuner"]');
      if(level&&tuner)return `任意等级 ${level.value} 调整`;
    }
    return '任意满足 '+text(r);
  }
  const tuner=level=>({kind:'condition',version:1,rule:{op:'all',items:[{field:'level',op:'eq',value:level},{field:'monster_kind',op:'in',values:['tuner']}]}});
  function face(value,catalog={},banned=false){return `<span class="condition-face ${banned?'condition-ban':''}" title="${safe(describe(value,catalog))}"><img src="/condition-card.svg" alt=""><span class="condition-kind">${banned?'禁止集合':'条件集合'}</span><strong>${safe(describe(value,catalog))}</strong><small>${banned?'整副初始手牌排除':'由 1 张真实卡牌填充'}</small></span>`;}
  function summary(plan){
    const c=plan?.expansion?.conditions;if(!has(c))return '';
    const catalog=plan.catalog||{};
    return `<section class="opening-rule-summary"><h3>起手规则 · 条件集合</h3><div class="condition-summary-cards">${(c.slots||[]).map(v=>is(v)?face(v,catalog):`<span class="condition-exact">${v?`<img src="/pics/${Number(v)}.jpg" alt="">`:''}<strong>${safe(describe(v,catalog))}</strong></span>`).join('')}</div><p>整副起手禁止：${(c.banned||[]).map(v=>safe(describe(v,catalog))).join('；')||'无'}</p><p>记录时实际起手（实例）：${(plan.expansion.actual_opening||plan.initial_hand?.map(c=>c.code)||[]).map(v=>safe(describe(v,catalog))).join(' · ')||'未记录'}</p>${plan.opening_match?.actual_hand?`<p>当前用于匹配的实际手牌：${plan.opening_match.actual_hand.map(v=>safe(describe(v,catalog))).join(' · ')}</p>`:''}<p class="condition-boundary">满足起手集合不代表可执行同一路线；其他候选的效果、费用、素材和后续步骤仍需验证。</p></section>`;
  }
  const cache=new WeakMap();
  const key=d=>JSON.stringify([d.deck,d.conditions,typeof app==='undefined'?0:app.catalogEpoch||0]);
  function state(d){
    if(!has(d.conditions))return null;
    const identity=key(d),previous=cache.get(d);
    if(previous?.key===identity)return previous;
    const entry={key:identity,result:null};cache.set(d,entry);
    Promise.resolve().then(()=>api('/api/opening/preview',{deck:d.deck,conditions:d.conditions})).then(result=>{entry.result=result;},error=>{entry.result={valid:false,errors:['条件校验失败：'+error.message],warnings:[]};}).finally(()=>{
      if(cache.get(d)===entry&&key(d)===identity&&typeof flow!=='undefined'&&(flow.design===d||flow.design?.opponent_config===d))renderDesign();
    });
    return entry;
  }
  function error(d){const s=state(d);return s?(s.result?(s.result.errors||[]).join('；'):'正在校验条件牌与所有槽位…'):'';}
  function status(d){const r=state(d)?.result;return r?(r.warnings||[]).map(s=>`<p>${safe(s)}</p>`).join('')+(r.slots||[]).filter((_,i)=>is(d.conditions.slots[i])).map(s=>`<p>${safe(s.summary)}：原始匹配 ${s.types} 种 / ${s.copies} 张；排除禁用后 ${s.allowed_copies} 张。${r.valid?'整套起手可分配。':'整套起手不可分配，请处理校验提示。'}</p>`).join(''):'';}
  function banned(d,code){return !!state(d)?.result?.banned?.some(row=>row.codes.includes(code));}
  return {is,has,describe,face,summary,tuner,error,status,banned,safe,labels,options};
})();
