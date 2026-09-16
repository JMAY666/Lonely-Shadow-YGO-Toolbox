'use strict';

// Frontend preview data only. No recognition, AI, deck writes or engine calls.
const DuelAutomatic = (() => {
  const tags = [{id:'demo-blue-eyes',name:'青眼'}, {id:'demo-dragon',name:'龙族'},
    {id:'demo-fusion',name:'融合'}, {id:'demo-synchro',name:'同调'}, {id:'demo-ritual',name:'仪式'}];
  const create = () => ({platform:null,page:'recognition',deck:null,name:'',marks:new Set(),
    tagIds:[],primaryIds:[],query:'',saved:[],pending:null,notice:''});
  const nameKey = name => String(name).trim().normalize('NFKC').toLocaleLowerCase('en-US');
  function sample() {
    const main = [89631139,71039903,38517737,17985575,55410871,70095154,79814787,
      55144522,83764718,5318639,12580477,44095762,97077563].flatMap(code=>[code,code,code]);
    return {name:'青眼示例卡组',deck:{main:[...main,10045474],extra:[23995346,59822133,89604813,45010690],
      side:[14558127,23434538,24224830].flatMap(code=>[code,code,code])}};
  }
  function setRole(draft,id,role) {
    if(!tags.some(tag=>tag.id===id))return;
    draft.tagIds=draft.tagIds.filter(value=>value!==id);
    draft.primaryIds=draft.primaryIds.filter(value=>value!==id);
    if(role==='primary'||role==='secondary')draft.tagIds.push(id);
    if(role==='primary')draft.primaryIds.push(id);
    draft.pending=null;
  }
  function save(draft,existing=[],overwrite=false) {
    const name=draft.name.trim(),key=nameKey(name);
    if(!draft.deck)return {error:'请先获取卡组。'};
    if(!name)return {error:'请输入卡组名称。'};
    if(name.length>80||/[<>:"/\\|?*\u0000-\u001f]/.test(name)||/[. ]$/.test(name)||/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name))return {error:'名称请使用 1–80 个字符，且不要包含文件名禁用字符、保留名称或以句点结尾。'};
    const collision=draft.saved.find(item=>nameKey(item.name)===key)||existing.find(item=>nameKey(item.name)===key);
    if(collision&&(!overwrite||draft.pending!==key)) {
      draft.pending=key;
      return {confirmation:true,name:collision.name};
    }
    // Replace one in-memory preview entry. Never mutate an actual saved deck.
    const entry={name,deck:structuredClone(draft.deck.deck),tag_selection:{tag_ids:[...draft.tagIds],primary_ids:[...draft.primaryIds]}};
    draft.saved=draft.saved.filter(item=>nameKey(item.name)!==key);
    draft.saved.push(entry);draft.name=name;draft.pending=null;
    return {saved:true,overwritten:!!collision,name};
  }
  return {create,sample,tags,setRole,save,nameKey};
})();
if(typeof module!=='undefined')module.exports=DuelAutomatic;

function duelAutomaticNotice() {
  return '<p class="duel-demo-notice"><span>界面预览</span>当前使用示例卡组；获取、AI 识别、保存和决斗连接仅作演示。</p>';
}
function duelPlatformPage() {
  return '<div class="duel-mode-grid duel-platform-grid"><button data-duel-action="platform-ygopro" class="duel-mode duel-platform"><strong>YGOPro</strong><span>初代原版游戏</span></button></div>';
}
function duelRecognitionPage() {
  const draft=duelState().automatic;
  return `${duelAutomaticNotice()}<div class="duel-section-heading"><h2>卡组识别</h2><span class="duel-platform-label">YGOPro · 初代原版</span></div>
    <div class="duel-recognition-layout"><section class="duel-recognition-panel" aria-label="卡组识别缩略图">
      <header><h3>识别效果</h3><small>${draft.deck?'示例缩略图':'等待获取卡组'}</small></header>
      ${draft.deck?zones.map(zone=>`<section class="duel-recognition-zone"><h4>${zoneNames[zone]} <small>${draft.deck.deck[zone].length} 张</small></h4><div class="duel-recognition-cards">${draft.deck.deck[zone].map(code=>`<img src="/pics/${code}.jpg" alt="${escape(duelName(code))}" loading="lazy">`).join('')||'<small>暂无卡牌</small>'}</div></section>`).join(''):
        '<div class="duel-recognition-empty"><img src="/brand/duel-automatic.svg" alt=""><h3>获取你的卡组</h3><p>点击右侧「获取卡组」，查看示例缩略图。</p></div>'}
    </section><aside class="duel-recognition-controls"><span class="duel-eyebrow">YGOPro</span><h3>${draft.deck?'核对卡组，继续预览':'准备识别卡组'}</h3><p>${draft.deck?'下一步可查看卡牌详情、添加标记，并设置名称和 TAG。':'请在 YGOPro 中打开卡组页面。当前预览将载入一套示例卡组。'}</p>
      ${duelButton('get-deck',draft.deck?'重新获取卡组':'获取卡组',false,!draft.deck)}${duelButton('recognition-next','下一步',!draft.deck,!!draft.deck)}
      <p class="duel-recognition-status" role="status">${draft.deck?'示例已就绪 · 可进入卡牌预览':'尚未获取卡组'}</p></aside></div>`;
}
function duelAutomaticTags() {
  const draft=duelState().automatic,query=draft.query.trim().toLocaleLowerCase();
  const selected=DuelAutomatic.tags.filter(tag=>draft.tagIds.includes(tag.id));
  return `<div class="duel-auto-tag-selected">${selected.map(tag=>`<button type="button" class="deck-tag-chip ${draft.primaryIds.includes(tag.id)?'primary':'secondary'}" data-duel-auto-tag="${tag.id}" data-role="" aria-label="移除 ${tag.name} TAG">${draft.primaryIds.includes(tag.id)?'主':'副'} · ${tag.name} ×</button>`).join('')||'<small>尚未选择 TAG</small>'}</div>
    <div class="duel-auto-tag-options">${DuelAutomatic.tags.filter(tag=>tag.name.toLocaleLowerCase().includes(query)).map(tag=>`<div><span>${tag.name}</span><div>${[['primary','主 TAG'],['secondary','副 TAG']].map(([role,label])=>{
      const current=draft.primaryIds.includes(tag.id)?'primary':draft.tagIds.includes(tag.id)?'secondary':'';
      return `<button type="button" data-duel-auto-tag="${tag.id}" data-role="${role}" aria-label="${tag.name}：${label}" aria-pressed="${current===role}">${label}</button>`;
    }).join('')}</div></div>`).join('')||'<p>没有匹配的示例 TAG。</p>'}</div>`;
}
function duelAutomaticSaveFeedback(result) {
  const draft=duelState().automatic;
  if(result)draft.notice=result.error|| (result.saved?`已${result.overwritten?'覆盖更新':'保存'}「${result.name}」（本次界面演示）。`:'');
  $('#duel-auto-save-status').textContent=draft.notice;
  const collision=draft.pending;
  $('#duel-auto-overwrite').hidden=!collision;
  $('#duel-auto-overwrite-name').textContent=collision?`已存在同名卡组「${draft.name.trim()}」。覆盖更新将替换卡牌和 TAG。当前仅演示此操作。`:'';
  $('#duel-auto-save').disabled=!draft.name.trim();
}
function duelAutomaticPreview() {
  const draft=duelState().automatic;
  return `${duelAutomaticNotice()}<div class="duel-auto-preview-layout"><section class="duel-auto-cards">${duelDeckPreview(draft.deck,draft.marks)}</section>
    <aside class="duel-auto-save-panel"><form id="duel-auto-save-form"><h2>保存卡组</h2><label for="duel-auto-name">卡组名称</label><input id="duel-auto-name" name="deck-name" maxlength="80" autocomplete="off" placeholder="输入卡组名称" value="${escape(draft.name)}">
      <div class="duel-auto-tag-heading"><h3>TAG 选择</h3><button type="button" data-duel-action="auto-tags">AI 识别</button></div><p class="duel-auto-tag-help">选择主／副 TAG，也可以修改识别结果。</p>
      <label class="duel-auto-tag-search" for="duel-auto-tag-search">搜索 TAG</label><input id="duel-auto-tag-search" type="search" placeholder="搜索示例 TAG" value="${escape(draft.query)}">
      <div id="duel-auto-tags">${duelAutomaticTags()}</div><button id="duel-auto-save" class="primary" type="submit">保存卡组</button>
      <div id="duel-auto-overwrite" class="duel-auto-overwrite" hidden><p id="duel-auto-overwrite-name"></p><div>${duelButton('cancel-auto-overwrite','取消')}${duelButton('confirm-auto-overwrite','覆盖更新',false,true)}</div></div><p id="duel-auto-save-status" role="status" aria-live="polite"></p>
      <small>演示保存仅保留在本次界面会话中。</small></form></aside></div>`;
}
function mountDuelAutomaticPreview() {
  const draft=duelState().automatic;
  $('#duel-auto-name').oninput=event=>{draft.name=event.target.value;draft.pending=null;draft.notice='';duelAutomaticSaveFeedback();};
  $('#duel-auto-tag-search').oninput=event=>{draft.query=event.target.value;$('#duel-auto-tags').innerHTML=duelAutomaticTags();};
  $('#duel-auto-save-form').onsubmit=event=>{event.preventDefault();duelAutomaticSaveFeedback(DuelAutomatic.save(draft,duelState().decks));};
  duelAutomaticSaveFeedback();
}
async function duelAutomaticAction(action) {
  const s=duelState(),draft=s.automatic;
  if(action==='automatic') {
    await duelWork(async()=>{
      s.decks=await api('/api/decks');
      if(s.operationMode!=='automatic')invalidateDuel(duelStages.function);
      s.operationMode='automatic';s.functionPage='platform';duelReach(duelStages.function);duelTell('');
    });return true;
  }
  if(s.operationMode!=='automatic')return false;
  if(action==='platform-ygopro') {draft.platform='ygopro';duelReach(duelStages.deck);duelTell('');renderDuel();return true;}
  if(action==='get-deck') {
    await duelWork(async()=>{
      const sample=draft.deck||DuelAutomatic.sample();
      await Promise.all([...new Set(zones.flatMap(zone=>sample.deck[zone]))].map(code=>card(code).catch(()=>{})));
      if(!draft.deck){draft.deck=sample;draft.name=sample.name;}
      duelTell('');
    });return true;
  }
  if(action==='recognition-next') {if(draft.deck){draft.page='preview';duelTell('');renderDuel();}return true;}
  if(action==='auto-tags') {
    draft.tagIds=['demo-blue-eyes','demo-dragon','demo-fusion'];draft.primaryIds=['demo-blue-eyes'];draft.pending=null;
    draft.notice='已填入示例 TAG，可继续手动调整。';$('#duel-auto-tags').innerHTML=duelAutomaticTags();duelAutomaticSaveFeedback();return true;
  }
  if(action==='cancel-auto-overwrite'){draft.pending=null;duelAutomaticSaveFeedback();return true;}
  if(action==='confirm-auto-overwrite'){duelAutomaticSaveFeedback(DuelAutomatic.save(draft,s.decks,true));return true;}
  if(action==='start-duel') {duelTell('卡牌预览已确认。自动决斗连接将在后续接入，当前不会启动决斗。');return true;}
  return false;
}
