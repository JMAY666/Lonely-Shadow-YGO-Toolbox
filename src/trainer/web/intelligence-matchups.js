'use strict';
function intelTopicRows(data){
  const rows=Object.entries(data.topics).map(([id,topic])=>({id,name:topic.name,formats:[]})),byId=new Map(rows.map(row=>[row.id,row]));
  for(const record of Object.values(data.records||{})){
    const row=byId.get(record.topic_id),format=['OCG','Master Duel'].includes(record.research?.format)?record.research.format:'personal';
    if(row&&!row.formats.includes(format))row.formats.push(format);
  }
  for(const row of rows)if(!row.formats.length)row.formats.push('personal');
  return rows;
}
function intelTopicOptionsHtml(data,selected='',format=''){
  const rows=intelTopicRows(data),option=(row,group)=>{
    const prefix=group==='OCG'?'OCG · ':group==='Master Duel'?'Master Duel · ':'';
    const label=prefix&&row.name.startsWith(prefix)?row.name.slice(prefix.length):row.name;
    return `<option value="${escape(row.id)}" ${selected===row.id?'selected':''}>${escape(label)}</option>`;
  };
  if(format)return rows.filter(row=>row.formats.includes(format)).map(row=>option(row,format)).join('');
  return [['OCG','OCG'],['Master Duel','Master Duel'],['personal','个人与跨环境主题']].map(([key,label])=>{
    const members=rows.filter(row=>(row.formats.length===1?row.formats[0]:'personal')===key);
    return members.length?`<optgroup label="${label}">${members.map(row=>option(row,key)).join('')}</optgroup>`:'';
  }).join('');
}
function intelTopicNavigation(){
  const rows=intelTopicRows(intelUI.data),count=format=>rows.filter(row=>row.formats.includes(format)).length;
  const button=(format,label,main=false)=>`<button type="button" data-intel-topic-format="${format}" aria-pressed="${intelUI.topicFormat===format}" ${main&&!count(format)?'disabled':''}>${main?`<strong>${label}</strong><small>${count(format)} 个卡组主题</small>`:label}</button>`;
  return `<div class="intel-group intel-topic-navigation"><div class="intel-topic-navigation-heading"><span>大主题</span>${button('','全部')}${count('personal')?button('personal','个人主题'):''}</div><div class="intel-primary-topics" role="group" aria-label="大主题">${button('OCG','OCG',true)}${button('Master Duel','Master Duel',true)}</div><label class="intel-filter intel-subtopic-label">卡组主题<select id="intel-topic" aria-label="断点主题"></select></label><div class="intel-group-actions"><button data-intel-action="topic-new">新建主题</button><button data-intel-action="topic-edit">编辑主题</button></div></div>`;
}
function intelTopicScope(){
  const select=$('#intel-topic');if(!select)return;
  select.innerHTML=`<option value="">${intelUI.topicFormat==='personal'?'全部个人主题':'全部卡组主题'}</option>${intelTopicOptionsHtml(intelUI.data,'',intelUI.topicFormat)}`;
  document.querySelectorAll('#intel-controls [data-intel-topic-format]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.intelTopicFormat===intelUI.topicFormat)));
}
function intelBrowseTopics(){
  intelList();
  if(intelUI.dirty){intelStatus('主题筛选已更新，右侧未保存的内容仍保留。');return;}
  const visible=[...document.querySelectorAll('#intel-list [data-intel-edit]')];
  if(visible.length&&!visible.some(button=>button.dataset.intelEdit===intelUI.draft?.id))return intelSelect(visible[0].dataset.intelEdit);
}
// Reading and filtering share the same persisted record/step/response structure.
function intelMatchupMatches(record,filters,data,cardForCode=intelCard){
  const research=record.research,format=filters.format||'',topic=data.topics[record.topic_id];
  if(format&&(format==='personal'?!!research:research?.format!==format))return false;
  if(filters.topic&&record.topic_id!==filters.topic)return false;
  const codes=[...new Set([...record.steps.flatMap(step=>[step.opponent,...step.responses.flatMap(response=>response.cards)]),...(research?.walkthrough?.sequence||[]).map(item=>item.card)].filter(Boolean))];
  const tagIds=[...(topic?.tag_ids||[]),...codes.flatMap(code=>data.card_tags?.[code]||[])];
  if(filters.tag&&!tagIds.includes(filters.tag))return false;
  const query=tagSearchKey(filters.q);if(!query)return true;
  const text=[record.title,record.note,topic?.name,...tagIds.map(id=>data.tags.find(tag=>tag.id===id)?.name),
    ...codes.flatMap(code=>[String(code),cardForCode(code).name]),
    ...['summary','recognition','priorities','warnings','metagame'].map(key=>research?.[key]),research?.walkthrough?.premise,research?.walkthrough?.conclusion,
    ...(research?.walkthrough?.sequence||[]).flatMap(item=>[item.action,item.result,item.card?cardForCode(item.card).name:'']),
    ...record.steps.flatMap(step=>[step.action,step.timing,step.condition,step.note,...step.responses.flatMap(response=>[response.method,response.condition,response.expected,response.note])])];
  return text.some(value=>tagSearchKey(value).includes(query));
}
function intelMatchupDetachResearch(record){
  const research=record.research;if(!research)return;
  const labels={format:'环境',period:'采样时期',reviewed_at:'核对日期',summary:'概要',recognition:'识别线索',priorities:'优先打断',warnings:'常见误区',metagame:'样本依据'};
  const lines=['原导入资料的个人参考副本（与当前步骤不再自动关联）',...Object.entries(labels).filter(([key])=>research[key]).map(([key,label])=>`${label}：${research[key]}`)];
  const walk=research.walkthrough;
  if(walk){lines.push(`原路线前提：${walk.premise}`);for(const [i,item] of (walk.sequence||[]).entries())lines.push(`第 ${i+1} 步（卡号 ${item.card||'无'}）：${item.action}\n得到什么：${item.result}`);for(const branch of walk.branches||[])lines.push(`${branch.label}：${branch.body}`);lines.push(`推演结论：${walk.conclusion}`);}
  for(const source of research.sources||[])lines.push(`${source.title}\n${source.url}\n${[source.published_at,source.period,source.note].filter(Boolean).join(' · ')}`);
  record.reference_copy=[record.reference_copy,lines.join('\n\n')].filter(Boolean).join('\n\n');delete record.research;
}
function intelMatchupReferenceCopy(record){return record.reference_copy?`<details class="intel-matchup-reference-copy"><summary>个人保留的参考副本</summary><p>原导入记录已在其他入口删除；以下内容完整保留供查阅，当前步骤按个人资料维护。</p><pre>${escape(record.reference_copy)}</pre></details>`:'';}
function intelMatchupUrl(value){
  try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)?url.href:'';}catch{return '';}
}
function intelMatchupSources(research){
  const sources=research?.sources||[];if(!sources.length)return '';
  const names={metagame:'环境证据',strategy:'对策参考',card_text:'卡文核对'};
  return `<details class="intel-matchup-sources"><summary>查看参考来源 · ${sources.length}</summary><p>环境证据说明样本中的使用情况；对策参考与卡文核对用于判断具体时点及适用条件。</p><ol>${sources.map(source=>{
    const url=intelMatchupUrl(source.url),title=escape(source.title||source.id||'参考资料');
    return `<li><div class="intel-matchup-source-heading">${intelBadge(names[source.kind]||'参考资料')}${url?`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${title}<span aria-hidden="true"> ↗</span></a>`:`<span>${title}</span>`}</div>${source.published_at||source.period?`<small>${escape([source.published_at&&`发布：${source.published_at}`,source.period&&`样本：${source.period}`].filter(Boolean).join(' · '))}</small>`:''}${source.note?`<p>${escape(source.note)}</p>`:''}${!url?'<small>未提供有效的 http(s) 来源链接</small>':''}</li>`;
  }).join('')}</ol></details>`;
}
function intelMatchupMetadata(research){
  if(!research)return `<div class="intel-matchup-meta">${intelBadge('个人资料')}</div>`;
  return `<div class="intel-matchup-meta">${intelBadge(research.format)}${research.edited?intelBadge('已个人编辑'):''}<span>采样时期：${escape(research.period||'未注明')}</span><span>核对日期：${escape(research.reviewed_at||'未注明')}</span></div>`;
}
function intelMatchupEvidence(research,ids){
  const sources=(ids||[]).map(id=>(research?.sources||[]).find(source=>source.id===id)).filter(Boolean);
  if(!sources.length)return '';
  const kinds={metagame:'环境',strategy:'策略',card_text:'卡文'};
  return `<p class="intel-matchup-evidence"><span>依据：</span>${sources.map(source=>{const url=intelMatchupUrl(source.url),label=escape(`${kinds[source.kind]||'参考'} · ${source.title}`);return url?`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`:`<span>${label}</span>`;}).join('<span aria-hidden="true"> / </span>')}</p>`;
}
function intelMatchupStepsEdited(record){
  const saved=intelUI.data.records?.[record.id];
  return !!record.research?.steps_edited||!!saved&&JSON.stringify(record.steps)!==JSON.stringify(saved.steps);
}
function intelMatchupWalkthrough(record){
  const research=record.research,walkthrough=research?.walkthrough;if(!walkthrough)return '';
  const stepsEdited=intelMatchupStepsEdited(record);
  return `<section class="intel-walkthrough" aria-label="典型路线配图"><h3>${stepsEdited?'原始导入路线（当前断点已手动调整）':'跟着卡图看一遍'}</h3><p class="intel-walkthrough-premise"><strong>推演前提</strong>${escape(walkthrough.premise)}</p><ol class="intel-walkthrough-sequence">${(walkthrough.sequence||[]).map((item,i)=>`<li><span class="intel-kicker">第 ${i+1} 步</span>${item.card?`<div class="intel-card-refs">${intelRef(item.card)}</div>`:''}<h4>${escape(item.action)}</h4><p><span>得到什么</span>${escape(item.result)}</p>${!stepsEdited&&Number.isInteger(item.step_index)&&item.step_index>=0&&item.step_index<record.steps.length?`<button data-intel-breakpoint="${item.step_index}">查看断点 ${item.step_index+1} ↓</button>`:''}</li>`).join('')}</ol><div class="intel-walkthrough-branches">${(walkthrough.branches||[]).map(branch=>`<section><h4>${escape(branch.label)}</h4><p>${escape(branch.body)}</p></section>`).join('')}</div><p class="intel-walkthrough-conclusion">${escape(walkthrough.conclusion)}</p><small class="intel-walkthrough-boundary">手工卡文推演，尚未经规则引擎验收；实际展开仍取决于手牌、前置状态与对手后续选择。</small><details class="intel-walkthrough-evidence"><summary>展开本图依据</summary>${intelMatchupEvidence(research,walkthrough.source_ids)}</details></section>`;
}
function intelMatchupFacts(rows){return `<dl class="intel-matchup-facts">${rows.filter(([,value])=>value).map(([label,value])=>`<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('')}</dl>`;}
function intelMatchupReader(record){
  const research=record.research,topic=intelUI.data.topics[record.topic_id],stepSources=intelMatchupStepsEdited(record)?[]:research?.step_sources;
  const overview=research?[['识别线索',research.recognition],['优先打断',research.priorities],['常见误区',research.warnings],['样本依据',research.metagame]].filter(([,text])=>text):[];
  return `<article class="intel-matchup-reader">
    <header class="intel-matchup-heading">${intelMatchupMetadata(research)}<span class="intel-kicker">${escape(topic?.name||'缺失主题')}</span><h2>${escape(record.title||'未命名断点')}</h2>${research?.summary?`<p class="intel-matchup-summary">${escape(research.summary)}</p>`:''}<p class="intel-matchup-validation">${intelBadge(record.status||'待补充')} 策略资料，尚未经规则引擎验证。请结合当前禁限、卡文与已确认局面判断。</p></header>
    ${intelMatchupWalkthrough(record)}${overview.length?`<div class="intel-matchup-overview">${overview.map(([label,text])=>`<section><h3>${label}</h3><p>${escape(text)}</p></section>`).join('')}</div>`:''}
    <section class="intel-matchup-breakpoints"><h3>关键断点</h3><p class="intel-matchup-guidance">以下断点按当前局面选择，不要求依次使用。每个断点内的单独选项分别选择；“组合”表示多张卡配合。</p>${record.steps.map((step,i)=>`<article class="intel-matchup-step" id="intel-matchup-step-${i}" tabindex="-1"><header><span class="intel-matchup-number">${i+1}</span><div><span class="intel-kicker">看到对手做什么</span><h4>${escape(step.action||'待补充对手操作')}</h4></div></header><div class="intel-matchup-opponent">${step.opponent?`<div class="intel-card-refs">${intelRef(step.opponent)}</div>`:''}${intelMatchupFacts([['何时交',step.timing||'待核对时点'],['前提',step.condition||'待核对条件'],['补充判断',step.note]])}</div><div class="intel-matchup-responses">${step.responses.map((response,j)=>`<section class="intel-matchup-response ${response.mode==='combination'?'is-combination':''}"><header><strong>应对 ${j+1}</strong>${intelBadge(response.mode==='combination'?'组合 · 多卡配合':'单独可选')}</header><div class="intel-card-refs">${response.cards.map(code=>intelRef(code)).join('')||'<p>待补充应对卡牌</p>'}</div>${intelMatchupFacts([['应对方式',response.method||'待补充应对方式'],['使用条件',response.condition||'待核对条件'],['预期作用',response.expected||'待核对作用'],['补充备注',response.note]])}</section>`).join('')||'<p>尚未补充应对方式。</p>'}</div>${intelMatchupEvidence(research,stepSources?.[i])}</article>`).join('')}</section>
    ${record.note?`<section class="intel-matchup-note"><h3>补充备注</h3><p>${escape(record.note)}</p></section>`:''}${intelMatchupSources(research)}</article>`;
}
function intelMatchupResearchEditor(research){
  if(!research)return '';
  return `<section class="intel-matchup-research-editor"><h3>对策概要</h3>${intelMatchupMetadata(research)}<p>环境、采样时期、核对日期和来源保留导入记录；下方内容可按个人经验补充。</p>${[['一句概要','summary'],['识别线索','recognition'],['优先打断','priorities'],['常见误区','warnings'],['样本依据','metagame']].map(([label,key])=>intelField(label,`research.${key}`,research[key],{area:true})).join('')}${intelMatchupSources(research)}</section>`;
}
