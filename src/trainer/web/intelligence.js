'use strict';
const intelUI={data:null,tab:'endboards',draft:null,kind:null,dirty:false,busy:false,serial:0,picker:null,pickerSerial:0,pickerTimer:null,sources:null,decks:[]};
const intelNames={endboards:'终场标记',handtraps:'手坑标记',records:'断点管理'};
const intelCopy=value=>structuredClone(value);
const intelCard=code=>intelUI.data?.cards[code]||app.cache.get(Number(code))||{id:Number(code),name:`卡库缺失 · ${code}`,desc:'',missing:true,type:0};
const intelBadge=text=>`<span class="intel-badge">${escape(text)}</span>`;
function intelStatus(message,error=false){const el=$('#intel-status');el.textContent=message;el.classList.toggle('intel-error',error);}
function intelDirty(){intelUI.dirty=true;intelStatus('有未保存的修改，切换模块后仍可回来继续。');}
async function intelDiscard(){return !intelUI.dirty||await confirmFlow('放弃当前情报站的未保存内容？','已保存的卡牌标注与断点资料保持不变。','放弃修改');}
function intelTagOptions(value=''){return `<option value="">全部 TAG</option>`+(intelUI.data?.tags||[]).map(t=>`<option value="${escape(t.id)}" ${t.id===value?'selected':''}>${escape(t.name)}${t.kind==='purpose'?' · 用途':''}</option>`).join('');}
function intelFilters(prefix){return `<div class="intel-filters" id="${prefix}-filters"><input id="${prefix}-q" aria-label="搜索卡名或卡号" placeholder="卡名／卡号"><select id="${prefix}-tag" aria-label="TAG 筛选">${intelTagOptions()}</select>${['kind','attribute','race','level'].map(key=>`<select id="${prefix}-${key}" aria-label="${{kind:'卡牌类型',attribute:'属性',race:'种族',level:'等级／阶级／LINK'}[key]}">${$(key==='kind'?'#filter':'#filter-'+key).innerHTML}</select>`).join('')}<button type="button" data-intel-clear="${prefix}">清空筛选</button></div>`;}
function intelFilterValues(prefix){return Object.fromEntries(['q','tag','kind','attribute','race','level'].map(k=>[k,$(`#${prefix}-${k}`)?.value||'']));}
function intelMatchesCard(code,f){const c=intelCard(code),q=tagSearchKey(f.q);return (!q||tagSearchKey(c.name).includes(q)||String(code).includes(q))&&(!f.tag||intelUI.data.card_tags?.[code]?.includes(f.tag))&&(!f.kind||({monster:c.type&1,spell:c.type&2,trap:c.type&4,extra:c.extra})[f.kind])&&(!f.attribute||c.attribute===Number(f.attribute))&&(!f.race||c.race===Number(f.race))&&(f.level===''||!!(c.type&1)&&(c.level&255)===Number(f.level));}
function intelShell(){
  $('#intelligence').innerHTML=`<header class="intel-heading"><div><div class="eyebrow">PERSONAL KNOWLEDGE</div><h1>情报站</h1><p>管理可复用的卡牌标注，记录对手操作与对应的应对方式。</p></div><button id="intel-refresh">刷新资料</button></header><nav class="intel-tabs" aria-label="情报站分类">${Object.entries(intelNames).map(([key,name])=>`<button data-intel-tab="${key}" aria-pressed="${intelUI.tab===key}">${key==='records'?'':'卡牌标注 · '}${name}</button>`).join('')}</nav><p id="intel-status" class="intel-status" role="status"></p><div id="intel-controls"></div><section id="intel-picker" class="intel-picker" hidden></section><section id="intel-sources" class="intel-sources" hidden></section><div class="intel-layout"><section id="intel-list" class="intel-list" aria-label="资料列表"></section><section id="intel-editor" class="intel-editor" aria-label="资料编辑"></section></div>`;
  intelControls();intelList();intelEditor();
}
async function enterIntelligence(){
  if(intelUI.dirty){intelStatus('当前未保存内容已保留。其他入口如有更新，保存时会提示核对。');return;}
  const serial=++intelUI.serial;
  try{const [value,decks]=await Promise.all([api('/api/intelligence'),api('/api/decks')]);if(serial!==intelUI.serial)return;intelUI.data=value;intelUI.decks=decks;intelUI.draft=null;intelUI.kind=null;intelShell();}
  catch(e){if(!$('#intel-status'))intelShell();intelStatus(`读取失败：${e.message}。可点击刷新重试。`,true);}
}
function intelControls(){
  const d=intelUI.data;if(!d)return;
  const hand=intelUI.tab==='handtraps',records=intelUI.tab==='records';
  $('#intel-controls').innerHTML=`<div class="intel-toolbar"><div>${hand?`<select id="intel-folder" aria-label="手坑文件夹"><option value="">全部手坑</option><option value="ungrouped">未分组</option>${Object.values(d.folders).map(f=>`<option value="${escape(f.id)}">${escape(f.name)}</option>`).join('')}</select> <button data-intel-action="folder-new">新建文件夹</button> <button data-intel-action="folder-edit">重命名</button> <button data-intel-action="folder-remove">删除文件夹</button>`:records?`<select id="intel-topic" aria-label="断点主题"><option value="">全部主题</option>${Object.values(d.topics).map(t=>`<option value="${escape(t.id)}">${escape(t.name)}</option>`).join('')}</select> <button data-intel-action="topic-new">新建主题</button> <button data-intel-action="topic-edit">编辑主题</button>`:`<span class="intel-help">通用用途由你维护；应用到方案后可单独调整。</span>`}</div><div>${!hand&&!records?'<button data-intel-action="sources">汇总方案标记</button> ':''}<button class="primary" data-intel-action="add">${records?'新增断点':'添加卡牌'}</button></div></div>${records?`<div class="intel-filters" id="intel-filter-filters"><input id="intel-filter-q" aria-label="搜索断点" placeholder="标题、主题、TAG、卡名／卡号"><select id="intel-filter-tag" aria-label="TAG 筛选">${intelTagOptions()}</select><button data-intel-clear="intel-filter">清空筛选</button></div>`:intelFilters('intel-filter')}`;
}
function intelList(){
  if(!intelUI.data)return;
  const d=intelUI.data,f=intelFilterValues('intel-filter'),records=intelUI.tab==='records';
  let entries=Object.values(d[intelUI.tab]);
  if(records){const topic=$('#intel-topic').value,q=tagSearchKey(f.q);entries=entries.filter(r=>{const t=d.topics[r.topic_id],codes=r.steps.flatMap(s=>[s.opponent,...s.responses.flatMap(o=>o.cards)]).filter(Boolean),tagIds=[...(t?.tag_ids||[]),...codes.flatMap(c=>d.card_tags?.[c]||[])];return (!topic||r.topic_id===topic)&&(!f.tag||tagIds.includes(f.tag))&&(!q||[r.title,t?.name,...tagIds.map(id=>d.tags.find(t=>t.id===id)?.name),...codes.flatMap(code=>[String(code),intelCard(code).name])].some(s=>tagSearchKey(s).includes(q)));});}
  else {entries=entries.filter(item=>intelMatchesCard(item.code,f));if(intelUI.tab==='handtraps'){const folder=$('#intel-folder').value;entries=entries.filter(item=>!folder||(folder==='ungrouped'?!item.folder_id:item.folder_id===folder));}}
  $('#intel-list').innerHTML=`<p>${entries.length} ${records?'条记录':'张卡牌'}</p>`+entries.map(item=>records?`<article class="intel-source"><strong>${escape(item.title)}</strong><p>${escape(d.topics[item.topic_id]?.name||'缺失主题')} · ${item.steps.length} 个步骤</p>${intelBadge(item.status)}<p><button data-intel-edit="${escape(item.id)}">查看与编辑</button></p></article>`:`<article class="intel-list-row">${tagCatalogueCard(intelCard(item.code))}<div><strong>${escape(intelCard(item.code).name)}</strong><small>${item.code}</small>${intelCard(item.code).missing?intelBadge('卡库缺失，资料保留'):''}<p>${escape(item.note||'尚未填写用途')}</p>${(d.card_tags?.[item.code]||[]).map(id=>intelBadge(d.tags.find(t=>t.id===id)?.name||id)).join('')}<div><button data-intel-edit="${item.code}">编辑标注</button></div></div></article>`).join('')+(entries.length?'':'<p>没有匹配的资料。可以清空筛选或添加新资料。</p>');
  pruneReviewCards();
}
const intelField=(label,path,value,{area=false,max=4000}={})=>`<label class="intel-field">${escape(label)}${area?`<textarea data-intel-field="${path}" maxlength="${max}" rows="2">${escape(value||'')}</textarea>`:`<input data-intel-field="${path}" maxlength="${max}" value="${escape(value||'')}">`}</label>`;
function intelTopicOptions(selected){return Object.values(intelUI.data.topics).map(t=>`<option value="${t.id}" ${selected===t.id?'selected':''}>${escape(t.name)}</option>`).join('');}
function intelRef(code,remove){return `<div>${tagCatalogueCard(intelCard(code))}${intelCard(code).missing?intelBadge('卡库缺失'):''}${remove?`<button data-intel-ref-remove="${remove}">移除引用</button>`:''}</div>`;}
function intelEditor(){
  const draft=intelUI.draft,kind=intelUI.kind,d=intelUI.data;
  if(!draft||!d){$('#intel-editor').innerHTML='<h2>选择一份资料</h2><p>从左侧选择标注或断点，也可以添加新资料。</p>';return;}
  let html='';
  if(kind==='endboards'||kind==='handtraps'){
    const c=intelCard(draft.code);
    html=`<div class="intel-editor-heading"><h2>${escape(c.name)}</h2><small>${draft.code}</small></div><div class="intel-card-refs">${intelRef(draft.code)}</div>`;
    if(c.missing)html+='<p>卡库暂时缺少这张卡；已保存的编号、备注和效果文本仍保留。</p>';
    if(kind==='endboards'){
      html+=`<p>这里只描述通用用途。加入通用库不会增加路线评分或阻抗次数。</p><label class="intel-label"><input type="checkbox" data-intel-field="candidate" ${draft.candidate?'checked':''}> 作为终场候选卡牌</label>${intelField('卡牌通用用途','note',draft.note,{area:true})}<h3>关注的效果</h3>${!c.missing&&draft.desc!==c.desc?'<p class="intel-error">保存的效果文本与当前卡库不同，应用前需要核对。</p><button data-intel-action="reset-effects">采用当前卡库文本并重新选择效果</button>':''}${reviewEffectParts(draft.desc).map(p=>`<div class="effect-mark"><label><input type="checkbox" data-intel-effect="${p.key}" ${draft.effects[p.key]?'checked':''}><span>${escape(p.text)}</span></label>${draft.effects[p.key]?intelField(`${p.label}效果的用途或阻抗备注`,`effects.${p.key}.note`,draft.effects[p.key].note,{area:true}):''}</div>`).join('')}<details><summary>关联来源方案 · ${draft.sources?.length||0}</summary>${(draft.sources||[]).map(s=>`<div class="intel-source"><strong>${escape(s.plan_name)}</strong><p>${s.branch_id?'分支 '+escape(s.branch_id):'主线'} · 实例 ${escape(s.instance_id)} · 区域 ${escape(zoneNames[s.location]||s.location)}</p><p>${escape(s.annotation.note||'无卡牌备注')}</p>${Object.entries(s.annotation.effects).map(([key,v])=>`<p>效果 ${Number(key)+1}：${escape(v.note||'已选择')}</p>`).join('')}</div>`).join('')||'<p>手动维护的通用标注。可通过“汇总方案标记”选择来源导入。</p>'}</details>`;
    }else html+=`<p>此卡已由你确认为手坑用途。专用 TAG 与其他 TAG 可以同时保留。</p>${intelField('用途说明','note',draft.note,{area:true})}${intelField('使用条件','condition',draft.condition,{area:true})}<label class="intel-field">文件夹<select data-intel-field="folder_id"><option value="">未分组</option>${Object.values(d.folders).map(f=>`<option value="${f.id}" ${f.id===draft.folder_id?'selected':''}>${escape(f.name)}</option>`).join('')}</select></label>`;
  }else if(kind==='folder')html=`<h2>${draft.id?'重命名文件夹':'新建文件夹'}</h2>${intelField('文件夹名称','name',draft.name,{max:80})}<p>文件夹为单层分类，移动或删除文件夹会保留卡牌标注。</p>`;
  else if(kind==='topic'){
    html=`<h2>${draft.id?'编辑主题':'新建主题'}</h2>${intelField('主题名称','name',draft.name,{max:80})}<label class="intel-field">关联已有卡组（可选）<select data-intel-field="deck_id"><option value="">不绑定卡组</option>${draft.deck_id&&!intelUI.decks.some(deck=>deck.id===draft.deck_id)?`<option selected value="${escape(draft.deck_id)}">原卡组暂不可用（保留引用）</option>`:''}${intelUI.decks.map(deck=>`<option value="${escape(deck.id)}" ${draft.deck_id===deck.id?'selected':''}>${escape(deck.name)}</option>`).join('')}</select></label><label class="intel-field">关联 TAG（可多选）<select multiple size="6" data-intel-field="tag_ids">${d.tags.map(t=>`<option value="${escape(t.id)}" ${draft.tag_ids.includes(t.id)?'selected':''}>${escape(t.name)}</option>`).join('')}</select></label>${intelField('主题说明','note',draft.note,{area:true})}`;
  }else if(kind==='records'){
    const topic=d.topics[draft.topic_id];
    html=`<div class="intel-topic-head"><h2>${escape(topic?.name||'选择适用主题')}</h2>${(topic?.tag_ids||[]).map(id=>intelBadge(d.tags.find(t=>t.id===id)?.name||id)).join('')}<p>${escape(topic?.note||'')} ${topic?.deck_id?`· 关联卡组：${escape(intelUI.decks.find(deck=>deck.id===topic.deck_id)?.name||'原卡组暂不可用')}`:''}</p></div><p>${intelBadge(draft.status||'待补充')} 手动策略资料，尚未经规则引擎验证。每步的应对选项分别选择；多卡配合请标为组合。</p>${intelField('记录标题','title',draft.title,{max:120})}<label class="intel-field">适用主题<select data-intel-field="topic_id">${intelTopicOptions(draft.topic_id)}</select></label>${draft.steps.map((step,i)=>intelStep(step,i)).join('')}<button data-intel-action="step-add">＋ 添加断点步骤</button>${intelField('记录补充备注','note',draft.note,{area:true})}`;
  }
  $('#intel-editor').innerHTML=html+`<div class="intel-editor-actions"><button class="primary" data-intel-action="save">保存${kind==='folder'?'文件夹':kind==='topic'?'主题':'资料'}</button><button data-intel-action="cancel">取消编辑</button>${(draft.id||d[kind]?.[draft.code])?`<button class="danger" data-intel-action="remove">${kind==='handtraps'?'移除手坑标记':kind==='endboards'?'移除通用标注':'删除'}</button>`:''}</div>`;
  if(kind==='endboards')document.querySelectorAll('#intel-editor details .intel-source').forEach((el,i)=>el.insertAdjacentHTML('beforeend',`<button data-intel-source-plan="${escape(draft.sources[i].plan_id)}">打开来源方案</button>`));
  if(kind==='handtraps'&&draft.folder_id&&!d.folders[draft.folder_id]){
    const select=$('#intel-editor [data-intel-field="folder_id"]');select.insertAdjacentHTML('afterbegin',`<option value="${escape(draft.folder_id)}">原文件夹已被删除，请重新选择</option>`);select.value=draft.folder_id;
  }
  if(kind==='records'&&!d.topics[draft.topic_id]){
    const select=$('#intel-editor [data-intel-field="topic_id"]');select.insertAdjacentHTML('afterbegin',`<option value="${escape(draft.topic_id)}">原主题已被删除，请重新选择</option>`);select.value=draft.topic_id;
  }
  pruneReviewCards();
}
function intelStep(step,i){return `<article class="intel-step"><header class="intel-editor-heading"><h3>Step ${i+1} · 对手操作</h3><div><button data-intel-step-up="${i}" ${i===0?'disabled':''}>上移</button> <button data-intel-step-down="${i}" ${i===intelUI.draft.steps.length-1?'disabled':''}>下移</button> <button data-intel-step-remove="${i}">删除步骤</button></div></header><div class="intel-card-refs">${step.opponent?intelRef(step.opponent,`steps.${i}.opponent`):'<p>尚未选择对手卡牌</p>'}<button data-intel-pick="steps.${i}.opponent">选择对手卡牌</button></div>${intelField('具体操作／效果',`steps.${i}.action`,step.action)}<div class="intel-fields">${intelField('发动／干扰时点',`steps.${i}.timing`,step.timing)}${intelField('适用条件',`steps.${i}.condition`,step.condition)}</div>${intelField('步骤备注',`steps.${i}.note`,step.note,{area:true})}<h4>此操作的应对选项</h4>${step.responses.map((r,j)=>`<section class="intel-response"><header class="intel-editor-heading"><strong>选项 ${j+1}</strong><button data-intel-response-remove="${i}:${j}">删除选项</button></header><label class="intel-field">选项性质<select data-intel-field="steps.${i}.responses.${j}.mode"><option value="alternative" ${r.mode==='alternative'?'selected':''}>单独可选方式</option><option value="combination" ${r.mode==='combination'?'selected':''}>组合 · 多张卡配合</option></select></label><div class="intel-card-refs">${r.cards.map((c,k)=>intelRef(c,`steps.${i}.responses.${j}.cards.${k}`)).join('')}<button data-intel-pick="steps.${i}.responses.${j}.cards" data-handtrap-shortcut="1">＋ 选择应对卡牌</button></div>${intelField('应对方式／操作',`steps.${i}.responses.${j}.method`,r.method)}<div class="intel-fields">${intelField('使用条件',`steps.${i}.responses.${j}.condition`,r.condition)}${intelField('预期作用',`steps.${i}.responses.${j}.expected`,r.expected)}</div>${intelField('补充备注',`steps.${i}.responses.${j}.note`,r.note,{area:true})}</section>`).join('')||'<p>尚未添加应对方式。</p>'}<button data-intel-response-add="${i}">＋ 添加可选应对方式</button></article>`;}
function intelPath(path){const keys=path.split('.'),key=keys.pop();return {parent:keys.reduce((v,k)=>v[k],intelUI.draft),key};}
function intelNewStep(){return {opponent:null,action:'',timing:'',condition:'',note:'',responses:[]};}
function intelNewResponse(){return {cards:[],mode:'alternative',method:'',condition:'',expected:'',note:''};}
async function intelSelect(key){if(!await intelDiscard())return;intelClosePicker();intelUI.kind=intelUI.tab;intelUI.draft=intelCopy(intelUI.data[intelUI.tab][key]);intelUI.dirty=false;intelEditor();intelStatus('已载入资料。');}
async function intelWrite(op,value,{keep=false}={}){
  if(intelUI.busy)return false;
  intelUI.busy=true;$('#intelligence').inert=true;
  try{const result=await api('/api/intelligence',{revision:intelUI.data.revision,op,value});intelUI.data=result;if(!keep){intelUI.draft=null;intelUI.kind=null;intelUI.dirty=false;}const folder=$('#intel-folder')?.value,topic=$('#intel-topic')?.value,filters=intelFilterValues('intel-filter');intelControls();for(const [k,v] of Object.entries(filters)){const el=$(`#intel-filter-${k}`);if(el)el.value=v;}if($('#intel-folder'))$('#intel-folder').value=result.folders[folder]?folder:folder==='ungrouped'?folder:'';if($('#intel-topic'))$('#intel-topic').value=result.topics[topic]?topic:'';intelList();intelEditor();intelStatus('已保存。');return true;}
  catch(e){intelStatus(`保存失败：${e.message}。未保存内容仍保留，可重试。`,true);if(e.message.includes('其他入口'))$('#intel-status').insertAdjacentHTML('beforeend',' <button data-intel-action="reload-keep">读取新版并保留当前输入</button>');return false;}
  finally{intelUI.busy=false;$('#intelligence').inert=false;}
}
function intelClosePicker(){intelUI.picker=null;intelUI.pickerSerial++;clearTimeout(intelUI.pickerTimer);if($('#intel-picker'))$('#intel-picker').hidden=true;}
function intelOpenPicker(callback,{main=false,shortcut=false}={}){
  closeReviewDetail();intelUI.picker={callback,main,shortcut,cards:[],total:0};
  $('#intel-picker').hidden=false;$('#intel-picker').innerHTML=`<header class="intel-editor-heading"><h2>${main?'从完整主卡组卡库选择手坑':'选择卡牌'}</h2><button data-intel-action="picker-close">关闭选卡</button></header>${shortcut?'<label>选择范围 <select id="intel-picker-scope"><option value="handtraps">手坑库快捷选择</option><option value="all">完整卡库</option></select></label>':''}<p>${main?'由你确认这张卡从手牌干扰的用途；不按怪兽类型自动推断。':'选择断点应对卡牌不会自动加入手坑库。'}</p>${intelFilters('intel-pick')}<p id="intel-picker-status" role="status"></p><div id="intel-picker-cards" class="tag-card-grid"></div><button data-intel-action="picker-more" id="intel-picker-more" hidden>加载更多</button>`;
  void intelSearchPicker();$('#intel-picker').scrollIntoView({block:'start'});
}
async function intelSearchPicker(more=false){
  const picker=intelUI.picker;if(!picker)return;const serial=++intelUI.pickerSerial,params=new URLSearchParams(intelFilterValues('intel-pick'));params.set('offset',more?picker.cards.length:0);if(picker.main)params.set('main_only','1');if($('#intel-picker-scope')?.value==='handtraps')params.set('handtraps','1');$('#intel-picker-status').textContent='正在查找…';$('#intel-picker-more').disabled=true;
  try{const result=await api('/api/cards?'+params);if(serial!==intelUI.pickerSerial||picker!==intelUI.picker)return;picker.cards=more?[...picker.cards,...result.cards]:result.cards;picker.total=result.total;picker.cards.forEach(c=>app.cache.set(c.id,c));$('#intel-picker-cards').innerHTML=picker.cards.map(c=>`<div class="tag-card-tile">${tagCatalogueCard(c)}<button data-intel-choose="${c.id}">${picker.main?'确认手坑用途并编辑':'选择'}</button></div>`).join('');$('#intel-picker-status').textContent=result.total?`找到 ${result.total} 张 · 已显示 ${picker.cards.length} 张`:'没有匹配的卡牌，可清空筛选或切换范围。';$('#intel-picker-more').hidden=picker.cards.length>=result.total;pruneReviewCards();}
  catch(e){if(serial===intelUI.pickerSerial)$('#intel-picker-status').textContent=`查找失败：${e.message}。修改筛选可重试。`;}
  finally{if(serial===intelUI.pickerSerial)$('#intel-picker-more').disabled=false;}
}
async function intelShowSources(){
  $('#intel-sources').hidden=false;$('#intel-sources').innerHTML='<p>正在读取已有方案和分支的终场标记…</p>';
  try{const result=await api('/api/intelligence/sources');intelUI.sources=result;$('#intel-sources').innerHTML=`<header class="intel-editor-heading"><h2>已有方案 · 按卡牌汇总</h2><button data-intel-action="sources-close">收起</button></header><p>每个来源保留独立的实例、区域、效果与备注。选择其中一份作为通用标注，不合并不同结论。</p>${result.warnings.map(w=>`<p class="intel-error">${escape(w)}</p>`).join('')}${result.groups.map(g=>`<details><summary>${escape(g.card.name)} · ${g.code} · ${g.sources.length} 个来源</summary>${g.sources.map(s=>`<article class="intel-source"><strong>${escape(s.plan_name)} · ${s.branch_id?'分支':'主线'} · 实例 ${escape(s.instance_id)} · ${escape(zoneNames[s.location]||s.location)}</strong><p>${escape(s.annotation.note||'无卡牌备注')}</p>${Object.entries(s.annotation.effects).map(([key,v])=>`<p>${escape(reviewEffectParts(s.annotation.desc).find(p=>p.key===key)?.text||'原效果 '+key)}<br>用途：${escape(v.note||'未填')}</p>`).join('')}<button data-intel-import="${escape(s.key)}">选用此来源导入通用库</button></article>`).join('')}</details>`).join('')||'<p>没有已保存的终场标记。</p>'}`;}
  catch(e){$('#intel-sources').innerHTML=`<p class="intel-error">读取来源失败：${escape(e.message)}</p>`;}
}
function intelConflictHtml(value,kind,latest){
  if(!value)return '<p>此资料当前尚未保存或已被移除。</p>';
  const name=code=>code?escape(latest.cards[code]?.name||String(code)):'尚未选择卡牌';
  if(kind==='records'){
    const steps=value.steps.map((s,i)=>{
      const responses=s.responses.map(r=>`<p>${r.mode==='combination'?'组合':'可选'}：${r.cards.map(name).join(' + ')} ${escape(r.method)}<br>条件：${escape(r.condition)}<br>预期：${escape(r.expected)}<br>${escape(r.note)}</p>`).join('');
      return `<p>Step ${i+1} · ${name(s.opponent)} · ${escape(s.action)}<br>时点：${escape(s.timing)}<br>条件：${escape(s.condition)}<br>${escape(s.note)}</p>${responses}`;
    }).join('');
    return `<strong>${escape(value.title)}</strong><p>${escape(value.note)}</p>${steps}`;
  }
  return `<p>${value.name?escape(value.name):name(value.code)}</p><p>${escape(value.note||'无用途备注')}</p><p>${escape(value.condition||'')}</p>${Object.entries(value.effects||{}).map(([k,v])=>`<p>效果 ${Number(k)+1}：${escape(v.note)}</p>`).join('')}`;
}
async function intelAction(action){
  if(action==='reload-keep'){
    const latest=await api('/api/intelligence'),draft=intelUI.draft,kind=intelUI.kind;
    const saved=latest[kind==='folder'?'folders':kind==='topic'?'topics':kind]?.[draft?.id||draft?.code];
    // Keep both versions visible before accepting an overwrite. Nothing is saved here.
    intelUI.conflict={latest};
    $('#intel-conflict')?.remove();$('#intel-editor').insertAdjacentHTML('afterbegin',`<section id="intel-conflict" class="intel-source"><h3>其他入口已保存的新版</h3>${intelConflictHtml(saved,kind,latest)}<p>下方仍是你的未保存输入。核对后，点击继续编辑，再自行决定是否保存覆盖。</p><button data-intel-action="accept-latest">已核对，保留我的输入继续编辑</button></section>`);
    intelStatus('已读取新版，尚未覆盖任何资料。');return;
  }
  if(action==='accept-latest'){
    if(!intelUI.conflict)return;
    intelUI.data=intelUI.conflict.latest;intelUI.conflict=null;
    if(intelUI.draft?.id&&!intelUI.data[intelUI.kind==='topic'?'topics':intelUI.kind==='folder'?'folders':intelUI.kind]?.[intelUI.draft.id])delete intelUI.draft.id;
    intelControls();intelList();intelEditor();intelStatus('输入已保留。点击保存将用当前输入更新该资料。');return;
  }
  if(action==='picker-close')return intelClosePicker();
  if(action==='picker-more')return intelSearchPicker(true);
  if(action==='sources')return intelShowSources();
  if(action==='sources-close'){$('#intel-sources').hidden=true;return;}
  if(action==='save'){const op={endboards:'endboard',handtraps:'handtrap',records:'record',folder:'folder',topic:'topic'}[intelUI.kind];return intelWrite(op+'.save',intelUI.draft);}
  if(action==='cancel'){if(!await intelDiscard())return;intelUI.draft=null;intelUI.kind=null;intelUI.dirty=false;intelClosePicker();intelEditor();intelStatus('已取消编辑。');return;}
  if(action==='remove'){const kind=intelUI.kind;if(!await confirmFlow('删除这份资料？',kind==='endboards'?'历史方案的实例、效果选择和备注保持原样。':kind==='handtraps'?'解除手坑 TAG 和文件夹归属，其他标注及 TAG 保留。':'此操作会删除当前资料。','确认删除'))return;return intelWrite(({endboards:'endboard',handtraps:'handtrap',records:'record',topic:'topic'})[kind]+'.remove',intelUI.draft);}
  if(action==='reset-effects'){if(!await confirmFlow('按当前文本重新选择效果？','当前通用标注中的效果选择将清空，卡牌用途说明保留。','重新选择'))return;intelUI.draft.desc=intelCard(intelUI.draft.code).desc;intelUI.draft.effects={};intelDirty();intelEditor();return;}
  if(action==='step-add'){intelUI.draft.steps.push(intelNewStep());intelDirty();intelEditor();return;}
  if(action==='folder-remove'){const id=$('#intel-folder').value;if(!intelUI.data.folders[id])return intelStatus('请先选择一个自建文件夹。');if(!await intelDiscard()||!await confirmFlow('删除文件夹？','其中的卡牌转入“未分组”，备注与 TAG 保留。','删除文件夹'))return;return intelWrite('folder.remove',{id});}
  if(action==='folder-edit'||action==='topic-edit'){const id=$(action==='folder-edit'?'#intel-folder':'#intel-topic').value;if(!id||id==='ungrouped')return intelStatus('请先选择需要编辑的文件夹或主题。');if(!await intelDiscard())return;intelUI.kind=action==='folder-edit'?'folder':'topic';intelUI.draft=intelCopy(intelUI.data[intelUI.kind==='folder'?'folders':'topics'][id]);intelUI.dirty=false;intelClosePicker();intelEditor();return;}
  if(['folder-new','topic-new','add'].includes(action)){
    if(!await intelDiscard())return;intelClosePicker();intelUI.dirty=false;
    if(action==='folder-new'||action==='topic-new'){intelUI.kind=action==='folder-new'?'folder':'topic';intelUI.draft={name:'',tag_ids:[],deck_id:null,note:''};intelEditor();return;}
    if(intelUI.tab==='records'){const topic=$('#intel-topic').value||Object.keys(intelUI.data.topics)[0];if(!topic)return intelStatus('请先新建一个适用主题。');intelUI.kind='records';intelUI.draft={title:'',topic_id:topic,note:'',steps:[intelNewStep()],status:'待补充'};intelEditor();return;}
    intelOpenPicker(c=>{const old=intelUI.data[intelUI.tab][c.id];intelUI.kind=intelUI.tab;intelUI.draft=intelCopy(old||(intelUI.tab==='endboards'?{code:c.id,candidate:true,desc:c.desc,note:'',effects:{},sources:[]}:{code:c.id,note:'',condition:'',folder_id:intelUI.data.folders[$('#intel-folder')?.value]?$('#intel-folder').value:null}));intelUI.dirty=!old;intelEditor();intelStatus(old?'已打开已有标注，重复选择不会重复建档。':'请填写用途后保存。');},{main:intelUI.tab==='handtraps'});
  }
}
$('#intelligence').addEventListener('click',run(async e=>{
  const b=e.target.closest('button');if(!b||b.disabled||intelUI.busy)return;
  if(b.id==='intel-refresh'){if(!await intelDiscard())return;intelUI.dirty=false;return enterIntelligence();}
  if(b.dataset.intelTab){if(!await intelDiscard())return;intelClosePicker();intelUI.tab=b.dataset.intelTab;intelUI.draft=null;intelUI.kind=null;intelUI.dirty=false;intelShell();return;}
  if(b.dataset.intelClear){const prefix=b.dataset.intelClear;document.querySelectorAll(`#${prefix}-filters input,#${prefix}-filters select`).forEach(el=>el.value='');if(prefix==='intel-filter'){if($('#intel-folder'))$('#intel-folder').value='';if($('#intel-topic'))$('#intel-topic').value='';intelList();}else void intelSearchPicker();return;}
  if(b.dataset.intelAction)return intelAction(b.dataset.intelAction);
  if(b.dataset.intelSourcePlan){await switchModule('expansion');return showPlan(b.dataset.intelSourcePlan);}
  if(b.dataset.intelEdit)return intelSelect(b.dataset.intelEdit);
  if(b.dataset.intelChoose){const picker=intelUI.picker,c=picker?.cards.find(c=>c.id===Number(b.dataset.intelChoose));if(c){intelClosePicker();picker.callback(c);}return;}
  if(b.dataset.intelPick){const path=b.dataset.intelPick;intelOpenPicker(c=>{const {parent,key}=intelPath(path);if(Array.isArray(parent[key])){if(parent.mode!=='combination'&&parent[key].length&&!parent[key].includes(c.id)){intelStatus('多张卡配合请先将该选项设为“组合”；不同应对请添加新选项。',true);return;}if(!parent[key].includes(c.id))parent[key].push(c.id);}else parent[key]=c.id;intelDirty();intelEditor();},{shortcut:!!b.dataset.handtrapShortcut});return;}
  if(b.dataset.intelRefRemove){const {parent,key}=intelPath(b.dataset.intelRefRemove);if(Array.isArray(parent))parent.splice(Number(key),1);else parent[key]=null;intelDirty();intelEditor();return;}
  if(b.dataset.intelImport){if(!await intelDiscard())return;const source=intelUI.sources.groups.flatMap(g=>g.sources).find(s=>s.key===b.dataset.intelImport);if(!source)return;if(intelUI.data.endboards[source.annotation.code]&&!await confirmFlow('用此来源替换当前通用标注？','其他来源仍可查看，历史方案不会改变。当前通用版本会保留在本地备份。','选用此来源'))return;await intelWrite('endboard.import',{source_key:source.key,fingerprint:source.fingerprint});return;}
  const steps=intelUI.draft?.steps;
  if(b.dataset.intelStepRemove!==undefined){if(steps.length===1)return intelStatus('一条记录至少保留一个步骤。');steps.splice(Number(b.dataset.intelStepRemove),1);}
  else if(b.dataset.intelStepUp!==undefined||b.dataset.intelStepDown!==undefined){const up=b.dataset.intelStepUp!==undefined,i=Number(up?b.dataset.intelStepUp:b.dataset.intelStepDown),j=i+(up?-1:1);[steps[i],steps[j]]=[steps[j],steps[i]];}
  else if(b.dataset.intelResponseAdd!==undefined)steps[Number(b.dataset.intelResponseAdd)].responses.push(intelNewResponse());
  else if(b.dataset.intelResponseRemove){const [i,j]=b.dataset.intelResponseRemove.split(':').map(Number);steps[i].responses.splice(j,1);}
  else return;
  intelDirty();intelEditor();
}));
function intelInput(e){
  const el=e.target,path=el.dataset.intelField;
  if(path){const {parent,key}=intelPath(path);parent[key]=el.type==='checkbox'?el.checked:el.multiple?[...el.selectedOptions].map(o=>o.value):['folder_id','deck_id'].includes(key)?el.value||null:el.value;intelDirty();if(key==='topic_id')intelEditor();return;}
  if(el.dataset.intelEffect!==undefined){const key=el.dataset.intelEffect;if(el.checked)intelUI.draft.effects[key]={note:''};else delete intelUI.draft.effects[key];intelDirty();intelEditor();return;}
  if(el.closest('#intel-filter-filters')||['intel-folder','intel-topic'].includes(el.id))return intelList();
  if(el.closest('#intel-pick-filters')||el.id==='intel-picker-scope'){clearTimeout(intelUI.pickerTimer);intelUI.pickerSerial++;intelUI.pickerTimer=setTimeout(()=>intelSearchPicker(),180);}
}
$('#intelligence').addEventListener('input',intelInput);

// Refresh on every opening. Applying takes a copy into the existing instance format.
let intelReviewSerial=0;
async function mountIntelReview(c,d,edits,editable){
  const host=$('#intel-review-template');if(!host)return;const serial=++intelReviewSerial;
  host.innerHTML='<p>正在读取通用标注…</p>';
  try{
    const result=await api('/api/intelligence/endboard/'+c.code);if(serial!==intelReviewSerial||host!==$('#intel-review-template'))return;
    const annotation=result.annotation,compatible=!annotation||annotation.desc===d.desc;
    host.innerHTML=`<strong>通用终场标注</strong>${annotation?`<p>${escape(annotation.note||'已保存通用标注')} · ${annotation.candidate?'终场候选':'非候选'}</p>${Object.entries(annotation.effects).map(([key,v])=>`<p>✓ ${escape(reviewEffectParts(annotation.desc).find(p=>p.key===key)?.label||key)}效果：${escape(v.note||'已关注')}</p>`).join('')}${!compatible?'<p>通用标注与本方案效果文本不同，请到情报站核对。</p>':''}<button id="intel-review-apply" ${editable&&compatible?'':'disabled'}>一键应用到本方案</button>`:'<p>此卡暂无通用标注。</p>'}${editable?`<label class="intel-field">保存范围<select id="intel-review-scope"><option value="local">仅用于本方案</option><option value="shared">同时保存为通用标注</option></select></label><button id="intel-review-save">确认标注范围</button><p id="intel-review-status">方案内调整仍通过原有方案保存流程保存。</p>`:''}`;
    if($('#intel-review-apply'))$('#intel-review-apply').onclick=()=>{edits.final_marks||={};edits.cards||={};edits.final_marks[String(c.instance_id)]={marked:annotation.candidate,effects:intelCopy(annotation.effects)};edits.cards[String(c.instance_id)]=annotation.note;reviewUI.pending=null;refreshFinalMarks();renderReviewDetail();};
    if($('#intel-review-save'))$('#intel-review-save').onclick=async()=>{
      if($('#intel-review-scope').value==='local'){$('#intel-review-status').textContent='当前标注仅用于本方案，请继续按原流程保存方案。';return;}
      const button=$('#intel-review-save'),status=$('#intel-review-status');button.disabled=true;
      try{const mark=edits.final_marks?.[String(c.instance_id)]||{marked:false,effects:{}};await api('/api/intelligence',{revision:result.revision,op:'endboard.save',value:{code:c.code,candidate:mark.marked,effects:intelCopy(mark.effects),note:edits.cards?.[String(c.instance_id)]||'',desc:d.desc}});status.textContent='通用标注已保存；本方案的实例选择仍需保存方案。';button.textContent='已保存通用标注';}
      catch(e){status.textContent=`保存失败：${e.message}。本方案输入仍保留，可重新打开通用标注后重试。`;button.disabled=false;}
    };
    positionReviewDetail();
  }catch(e){if(host===$('#intel-review-template'))host.innerHTML=`<p>通用标注读取失败：${escape(e.message)}。本方案编辑仍可使用，重新打开可重试。</p>`;}
}
