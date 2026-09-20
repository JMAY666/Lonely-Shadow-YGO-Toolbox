'use strict';
const tagManagerUI={loaded:false,tags:[],revision:0,selected:null,draft:null,members:new Map(),excluded:new Map(),memberVisible:60,dirty:false,busy:false,serial:0,searchSerial:0,searchTimer:null,results:[],offset:0,total:0,
  related:[],relatedTotal:0,relatedSerial:0,relatedTimer:null,relatedBusy:false,seedId:null,seedName:''};
async function confirmTagChange() {
  return !tagManagerUI.dirty||await confirmFlow('放弃当前标签的未保存修改？','已保存的名称、别名和卡牌范围保持不变。','放弃修改');
}
async function refreshTagManager() {
  if(tagManagerUI.busy||!await confirmTagChange())return;
  const result=await api('/api/tags');tagManagerUI.tags=result.tags;tagManagerUI.revision=result.revision;tagManagerUI.loaded=true;tagManagerUI.dirty=false;
  renderTagManagerList();
  if(tagManagerUI.selected)await selectManagedTag(tagManagerUI.selected);
}
function renderTagManagerList() {
  const q=$('#tag-manager-search').value;
  $('#tag-manager-list').innerHTML=tagManagerUI.tags.filter(t=>tagMatches(t,q)).sort((a,b)=>a.name.localeCompare(b.name,'zh-CN')).map(t=>`<button type="button" data-managed-tag="${escape(t.id)}" class="${t.id===tagManagerUI.selected?'current':''}"><strong>${escape(t.name)}</strong><small>${escape(t.aliases.slice(0,3).join(' / '))}</small></button>`).join('')||'<p>没有匹配的标签，可新增。</p>';
}
async function selectManagedTag(id=null) {
  if(tagManagerUI.busy||!await confirmTagChange())return;
  const serial=++tagManagerUI.serial;closeReviewDetail();
  tagManagerUI.busy=true;$('#tag-manager-form').inert=true;
  let value;
  try {value=id?await api(`/api/tag-members/${encodeURIComponent(id)}`):{tag:{name:'',aliases:[],source:'用户自定义'},cards:[],revision:tagManagerUI.revision};}
  finally {tagManagerUI.busy=false;$('#tag-manager-form').inert=false;}
  if(serial!==tagManagerUI.serial)return;
  tagManagerUI.relatedSerial++;clearTimeout(tagManagerUI.relatedTimer);clearTimeout(tagManagerUI.searchTimer);
  tagManagerUI.selected=id;tagManagerUI.draft=value.tag;tagManagerUI.revision=value.revision;tagManagerUI.members=new Map(value.cards.map(c=>[c.id,c]));tagManagerUI.dirty=false;
  tagManagerUI.excluded=new Map((value.excluded_cards||[]).map(c=>[c.id,c]));tagManagerUI.memberVisible=60;
  $('#tag-manager-empty').hidden=true;$('#tag-manager-form').hidden=false;
  $('#tag-manager-title').textContent=id?value.tag.name:'新增 TAG';$('#tag-manager-source').textContent=value.tag.source;
  $('#tag-manager-name').value=value.tag.name;$('#tag-manager-aliases').value=value.tag.aliases.join('\n');$('#tag-member-filter').value='';
  $('#tag-manager-name').readOnly=$('#tag-manager-aliases').readOnly=value.tag.kind==='purpose';
  $('#tag-member-kind').value='';$('#tag-related-query').value='';$('#tag-related-kind').value='';
  tagManagerUI.seedId=null;tagManagerUI.seedName='';tagManagerUI.related=[];tagManagerUI.relatedTotal=0;
  $('#tag-manager-status').textContent='卡牌范围供卡组与方案共用；已保存的卡组标签和手动方案标签会保留。';
  if(value.tag.kind==='purpose')$('#tag-manager-status').textContent=value.tag.purpose==='handtrap'?'手坑用途 TAG：仅允许主卡组卡牌；与情报站同步，不参与卡组／方案系列自动识别。移除会同时解除手坑资料和文件夹归属。':value.tag.purpose==='boardbreaker'?'解场用途 TAG：包含主卡组与额外卡组卡牌；成员与情报站解场资料同步，不参与系列自动识别。':'效果用途 TAG：用于效果筛选，不参与卡组／方案系列自动识别。';
  renderTagManagerList();renderTagMembers();
  $('#tag-add-search').value='';tagManagerUI.results=[];tagManagerUI.total=0;tagManagerUI.searchSerial++;renderTagSearchResults();
  renderTagExcluded();void searchTagRelations();
}
function markTagDirty() {
  tagManagerUI.dirty=true;$('#tag-manager-status').textContent=tagManagerUI.draft?.kind==='purpose'?'有未保存的用途 TAG 成员修改，不参与系列自动识别。':'有未保存的修改。切换页面会保留，保存后参与自动识别。';
}
function tagCatalogueCard(card) {
  const report={id:'catalog:'+card.id,catalog:{[card.id]:card},events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  return reviewCard({code:card.id,name:card.name,identity_known:true},'catalog',{report,name:true,face:true,zone:false,position:false,catalogue:true});
}
function renderTagMembers() {
  const q=tagSearchKey($('#tag-member-filter').value),kind=$('#tag-member-kind').value,cards=[...tagManagerUI.members.values()].filter(c=>(!kind||c.tag_basis===kind)&&(tagSearchKey(c.name).includes(q)||String(c.id).includes(q)));
  $('#tag-member-count').textContent=`${tagManagerUI.members.size} 张`;
  $('#tag-member-cards').innerHTML=cards.slice(0,tagManagerUI.memberVisible).map(c=>`<div class="tag-card-tile">${tagCatalogueCard(c)}<span class="tag-card-basis">${escape(c.tag_basis||'手动加入')}</span><button type="button" data-card-related="${c.id}">关联卡片</button><button type="button" data-member-remove="${c.id}">移除</button></div>`).join('')||'<p>没有包含的匹配卡牌，可在下方搜索添加。</p>';
  $('#tag-members-more').hidden=tagManagerUI.memberVisible>=cards.length;
  pruneReviewCards();
}
function renderTagSearchResults() {
  $('#tag-add-results').innerHTML=tagManagerUI.results.map(c=>`<div class="tag-card-tile">${tagCatalogueCard(c)}<button type="button" data-card-related="${c.id}">关联卡片</button><button type="button" data-member-add="${c.id}" ${tagManagerUI.members.has(c.id)?'disabled':''}>${tagManagerUI.members.has(c.id)?'已包含':'添加'}</button></div>`).join('');
  $('#tag-add-more').hidden=tagManagerUI.results.length>=tagManagerUI.total;
  $('#tag-add-status').textContent=tagManagerUI.total?`找到 ${tagManagerUI.total} 张，已显示 ${tagManagerUI.results.length} 张`:'输入卡牌信息查找，悬停卡图可查看效果。';
  pruneReviewCards();
}
async function searchTagCards(more=false) {
  const q=$('#tag-add-search').value.trim();if(!q){tagManagerUI.results=[];tagManagerUI.total=0;renderTagSearchResults();return;}
  const serial=++tagManagerUI.searchSerial,selected=tagManagerUI.serial,offset=more?tagManagerUI.results.length:0;
  $('#tag-add-status').textContent='正在查找卡牌…';$('#tag-add-more').disabled=true;
  try {
    const result=await api(`/api/cards?q=${encodeURIComponent(q)}&offset=${offset}&main_only=${tagManagerUI.draft?.purpose==='handtrap'?'1':'0'}`);
    if(serial!==tagManagerUI.searchSerial||selected!==tagManagerUI.serial)return;
    tagManagerUI.results=more?[...tagManagerUI.results,...result.cards]:result.cards;tagManagerUI.total=result.total;renderTagSearchResults();
  } catch(e){if(serial===tagManagerUI.searchSerial)$('#tag-add-status').textContent=e.message;}
  finally{if(serial===tagManagerUI.searchSerial)$('#tag-add-more').disabled=false;}
}
async function saveManagedTag(e) {
  e.preventDefault();if(tagManagerUI.busy)return;
  tagManagerUI.busy=true;$('#tag-manager-form').inert=true;
  try {
    const result=await api('/api/tags/save',{id:tagManagerUI.selected,revision:tagManagerUI.revision,name:$('#tag-manager-name').value,
      aliases:$('#tag-manager-aliases').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),card_ids:[...tagManagerUI.members.keys()]});
    tagManagerUI.selected=result.tag.id;tagManagerUI.draft=result.tag;tagManagerUI.revision=result.revision;tagManagerUI.dirty=false;
    const index=tagManagerUI.tags.findIndex(t=>t.id===result.tag.id);if(index<0)tagManagerUI.tags.push(result.tag);else tagManagerUI.tags[index]=result.tag;
    if(!tagMatches(result.tag,$('#tag-manager-search').value))$('#tag-manager-search').value='';
    if(typeof refreshDeckTagName==='function')refreshDeckTagName(result.tag);
    $('#tag-manager-name').value=result.tag.name;$('#tag-manager-aliases').value=result.tag.aliases.join('\n');$('#tag-manager-title').textContent=result.tag.name;
    tagManagerUI.members=new Map(result.cards.map(c=>[c.id,c]));tagManagerUI.excluded=new Map((result.excluded_cards||[]).map(c=>[c.id,c]));
    renderTagManagerList();renderTagMembers();renderTagExcluded();void searchTagRelations();$('#tag-manager-status').textContent=result.tag.kind==='purpose'?'已保存用途 TAG 范围；系列自动识别不受影响。':'已保存名称、别名和卡牌范围，自动识别已使用最新设置。';
    void refreshPlans().catch(error=>{$('#tag-manager-status').textContent=`TAG 已保存；方案列表刷新失败：${error.message}。可稍后刷新。`;});
  }catch(error){$('#tag-manager-status').textContent=`保存失败：${error.message}。输入与卡牌选择仍保留。`;}
  finally{tagManagerUI.busy=false;$('#tag-manager-form').inert=false;}
}
$('#tag-manager-new').onclick=run(()=>selectManagedTag());$('#tag-manager-refresh').onclick=run(refreshTagManager);
$('#tag-manager-search').oninput=renderTagManagerList;$('#tag-member-filter').oninput=$('#tag-member-kind').onchange=()=>{tagManagerUI.memberVisible=60;closeReviewDetail();renderTagMembers();};
$('#tag-members-more').onclick=()=>{tagManagerUI.memberVisible+=60;renderTagMembers();};
$('#tag-manager-name').oninput=$('#tag-manager-aliases').oninput=markTagDirty;$('#tag-manager-form').onsubmit=saveManagedTag;
$('#tag-add-search').oninput=()=>{clearTimeout(tagManagerUI.searchTimer);tagManagerUI.searchSerial++;tagManagerUI.searchTimer=setTimeout(()=>searchTagCards(),250);};
$('#tag-add-more').onclick=()=>searchTagCards(true);
function renderTagExcluded() {
  const cards=[...tagManagerUI.excluded.values()].filter(c=>!tagManagerUI.members.has(c.id));
  $('#tag-excluded-section').hidden=!cards.length;$('#tag-excluded-count').textContent=`${cards.length} 张`;
  $('#tag-excluded-cards').innerHTML=cards.map(c=>`<div class="tag-card-tile">${tagCatalogueCard(c)}<button type="button" data-member-add="${c.id}" ${c.name===`未安装卡牌 ${c.id}`?'disabled':''}>恢复到 TAG</button></div>`).join('');
  pruneReviewCards();
}
function renderTagRelations() {
  $('#tag-related-title').textContent=tagManagerUI.seedId?`关联卡片 · ${tagManagerUI.seedName}`:'TAG 关联候选';
  $('#tag-related-back').hidden=!tagManagerUI.seedId;
  $('#tag-related-cards').innerHTML=tagManagerUI.related.map(c=>`<div class="tag-card-tile">${tagCatalogueCard(c)}<div class="tag-relation-reasons">${c.relation_reasons.map(r=>`<span>${escape(r.detail)}</span>`).join('')}${c.relation_count>c.relation_reasons.length?`<small>另有 ${c.relation_count-c.relation_reasons.length} 条直接依据</small>`:''}</div><button type="button" data-card-related="${c.id}">关联卡片</button><button type="button" data-member-add="${c.id}" ${tagManagerUI.members.has(c.id)?'disabled':''}>${tagManagerUI.members.has(c.id)?'已包含':'加入 TAG'}</button></div>`).join('');
  $('#tag-related-more').hidden=tagManagerUI.related.length>=tagManagerUI.relatedTotal;
  $('#tag-related-more').disabled=tagManagerUI.relatedBusy;
  pruneReviewCards();
}
async function searchTagRelations(more=false) {
  const serial=++tagManagerUI.relatedSerial,selected=tagManagerUI.serial;
  tagManagerUI.relatedBusy=true;$('#tag-related-cards').setAttribute('aria-busy','true');$('#tag-related-status').textContent='正在查找直接关联…';
  if(!more){tagManagerUI.related=[];tagManagerUI.relatedTotal=0;}renderTagRelations();
  try {
    const result=await api('/api/tags/related',{id:tagManagerUI.selected,card_ids:[...tagManagerUI.members.keys()],seed_id:tagManagerUI.seedId,
      query:$('#tag-related-query').value,kind:$('#tag-related-kind').value,offset:more?tagManagerUI.related.length:0});
    if(serial!==tagManagerUI.relatedSerial||selected!==tagManagerUI.serial)return;
    tagManagerUI.related=more?[...tagManagerUI.related,...result.cards]:result.cards;tagManagerUI.relatedTotal=result.total;
    $('#tag-related-status').textContent=(result.total?`找到 ${result.total} 张，已显示 ${tagManagerUI.related.length} 张。候选尚未加入 TAG。`:'没有符合条件的直接关联；可清除筛选，或在下方搜索卡牌并点击「关联卡片」。')+(result.script_errors?' 部分脚本暂不可读，结果可能不完整。':'');
  } catch(error){if(serial===tagManagerUI.relatedSerial)$('#tag-related-status').textContent=`查找失败：${error.message}。可点击「重新查找」，已有修改仍保留。`;}
  finally{if(serial===tagManagerUI.relatedSerial){tagManagerUI.relatedBusy=false;$('#tag-related-cards').setAttribute('aria-busy','false');renderTagRelations();}}
}
$('#tag-related-query').oninput=()=>{clearTimeout(tagManagerUI.relatedTimer);tagManagerUI.relatedSerial++;tagManagerUI.relatedTimer=setTimeout(()=>searchTagRelations(),250);};
$('#tag-related-kind').onchange=$('#tag-related-refresh').onclick=()=>searchTagRelations();
$('#tag-related-more').onclick=()=>searchTagRelations(true);
$('#tag-related-back').onclick=()=>{tagManagerUI.seedId=null;tagManagerUI.seedName='';$('#tag-related-kind').value='';$('#tag-related-query').value='';void searchTagRelations();};
$('#tags').addEventListener('click',run(async e=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if(b.dataset.managedTag)return selectManagedTag(b.dataset.managedTag);
  const findCard=id=>tagManagerUI.members.get(id)||tagManagerUI.excluded.get(id)||tagManagerUI.results.find(c=>c.id===id)||tagManagerUI.related.find(c=>c.id===id);
  if(b.dataset.cardRelated){const card=findCard(Number(b.dataset.cardRelated));if(card){tagManagerUI.seedId=card.id;tagManagerUI.seedName=card.name;$('#tag-related-query').value='';$('#tag-related-kind').value='';void searchTagRelations();$('#tag-related-section').scrollIntoView({block:'start'});}}
  if(b.dataset.memberRemove){closeReviewDetail();const card=tagManagerUI.members.get(Number(b.dataset.memberRemove));if(card?.tag_basis==='卡库系列')tagManagerUI.excluded.set(card.id,card);tagManagerUI.members.delete(Number(b.dataset.memberRemove));markTagDirty();renderTagMembers();renderTagExcluded();renderTagSearchResults();void searchTagRelations();}
  if(b.dataset.memberAdd){const card=findCard(Number(b.dataset.memberAdd));if(card){if(tagManagerUI.draft?.purpose==='handtrap'&&(!(card.type&7)||card.type&(0x40|0x2000|0x800000|0x4000000|0x4000)))return notice('手坑只允许主卡组卡牌，不能加入额外卡组卡牌或衍生物。');if(tagManagerUI.draft?.purpose==='boardbreaker'&&(!(card.type&7)||card.type&0x4000))return notice('解场资料不能加入衍生物。');closeReviewDetail();tagManagerUI.members.set(card.id,{...card,tag_basis:card.tag_default_member?'卡库系列':'手动加入'});markTagDirty();renderTagMembers();renderTagExcluded();renderTagSearchResults();void searchTagRelations();}}
}));
