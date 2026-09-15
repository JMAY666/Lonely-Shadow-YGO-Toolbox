'use strict';
const tagManagerUI={loaded:false,tags:[],revision:0,selected:null,draft:null,members:new Map(),dirty:false,busy:false,serial:0,searchSerial:0,searchTimer:null,results:[],offset:0,total:0};
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
  const value=id?await api(`/api/tag-members/${encodeURIComponent(id)}`):{tag:{name:'',aliases:[],source:'用户自定义'},cards:[],revision:tagManagerUI.revision};
  if(serial!==tagManagerUI.serial)return;
  tagManagerUI.selected=id;tagManagerUI.draft=value.tag;tagManagerUI.revision=value.revision;tagManagerUI.members=new Map(value.cards.map(c=>[c.id,c]));tagManagerUI.dirty=false;
  $('#tag-manager-empty').hidden=true;$('#tag-manager-form').hidden=false;
  $('#tag-manager-title').textContent=id?value.tag.name:'新增 TAG';$('#tag-manager-source').textContent=value.tag.source;
  $('#tag-manager-name').value=value.tag.name;$('#tag-manager-aliases').value=value.tag.aliases.join('\n');$('#tag-member-filter').value='';
  $('#tag-manager-status').textContent='卡牌范围用于自动识别；手动给方案设置的标签会保留。';
  renderTagManagerList();renderTagMembers();
  $('#tag-add-search').value='';tagManagerUI.results=[];tagManagerUI.total=0;tagManagerUI.searchSerial++;renderTagSearchResults();
}
function markTagDirty() {
  tagManagerUI.dirty=true;$('#tag-manager-status').textContent='有未保存的修改。切换页面会保留，保存后参与自动识别。';
}
function tagCatalogueCard(card) {
  const report={id:'catalog:'+card.id,catalog:{[card.id]:card},events:[],review:{nodes:[{id:'catalog',kind:'catalog',action_ids:[]}]}};
  return reviewCard({code:card.id,name:card.name,identity_known:true},'catalog',{report,name:true,face:true,zone:false,position:false,catalogue:true});
}
function renderTagMembers() {
  const q=tagSearchKey($('#tag-member-filter').value),cards=[...tagManagerUI.members.values()].filter(c=>tagSearchKey(c.name).includes(q)||String(c.id).includes(q));
  $('#tag-member-count').textContent=`${tagManagerUI.members.size} 张`;
  $('#tag-member-cards').innerHTML=cards.map(c=>`<div class="tag-card-tile">${tagCatalogueCard(c)}<button type="button" data-member-remove="${c.id}">移除</button></div>`).join('')||'<p>没有包含的匹配卡牌，可在下方搜索添加。</p>';
  pruneReviewCards();
}
function renderTagSearchResults() {
  $('#tag-add-results').innerHTML=tagManagerUI.results.map(c=>`<div class="tag-card-tile">${tagCatalogueCard(c)}<button type="button" data-member-add="${c.id}" ${tagManagerUI.members.has(c.id)?'disabled':''}>${tagManagerUI.members.has(c.id)?'已包含':'添加'}</button></div>`).join('');
  $('#tag-add-more').hidden=tagManagerUI.results.length>=tagManagerUI.total;
  $('#tag-add-status').textContent=tagManagerUI.total?`找到 ${tagManagerUI.total} 张，已显示 ${tagManagerUI.results.length} 张`:'输入卡牌信息查找，悬停卡图可查看效果。';
  pruneReviewCards();
}
async function searchTagCards(more=false) {
  const q=$('#tag-add-search').value.trim();if(!q){tagManagerUI.results=[];tagManagerUI.total=0;renderTagSearchResults();return;}
  const serial=++tagManagerUI.searchSerial,selected=tagManagerUI.serial,offset=more?tagManagerUI.results.length:0;
  $('#tag-add-status').textContent='正在查找卡牌…';$('#tag-add-more').disabled=true;
  try {
    const result=await api(`/api/cards?q=${encodeURIComponent(q)}&offset=${offset}`);
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
    $('#tag-manager-name').value=result.tag.name;$('#tag-manager-aliases').value=result.tag.aliases.join('\n');$('#tag-manager-title').textContent=result.tag.name;
    renderTagManagerList();await refreshPlans();$('#tag-manager-status').textContent='已保存名称、别名和卡牌范围，自动识别已使用最新设置。';
  }catch(error){$('#tag-manager-status').textContent=`保存失败：${error.message}。输入与卡牌选择仍保留。`;}
  finally{tagManagerUI.busy=false;$('#tag-manager-form').inert=false;}
}
$('#tag-manager-new').onclick=run(()=>selectManagedTag());$('#tag-manager-refresh').onclick=run(refreshTagManager);
$('#tag-manager-search').oninput=renderTagManagerList;$('#tag-member-filter').oninput=()=>{closeReviewDetail();renderTagMembers();};
$('#tag-manager-name').oninput=$('#tag-manager-aliases').oninput=markTagDirty;$('#tag-manager-form').onsubmit=saveManagedTag;
$('#tag-add-search').oninput=()=>{clearTimeout(tagManagerUI.searchTimer);tagManagerUI.searchSerial++;tagManagerUI.searchTimer=setTimeout(()=>searchTagCards(),250);};
$('#tag-add-more').onclick=()=>searchTagCards(true);
$('#tags').addEventListener('click',run(async e=>{
  const b=e.target.closest('button');if(!b||b.disabled)return;
  if(b.dataset.managedTag)return selectManagedTag(b.dataset.managedTag);
  if(b.dataset.memberRemove){closeReviewDetail();tagManagerUI.members.delete(Number(b.dataset.memberRemove));markTagDirty();renderTagMembers();renderTagSearchResults();}
  if(b.dataset.memberAdd){const card=tagManagerUI.results.find(c=>c.id===Number(b.dataset.memberAdd));if(card){closeReviewDetail();tagManagerUI.members.set(card.id,card);markTagDirty();renderTagMembers();renderTagSearchResults();}}
}));
