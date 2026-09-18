'use strict';

const DuelAutomatic = (() => {
  const create = () => ({platform:null,page:'recognition',deck:null,name:'',marks:new Set(),
    tagIds:[],primaryIds:[],tags:[],suggestions:null,query:'',pending:null,notice:'',
    connection:null,fresh:false,captureError:'',order:null,workspace:null,navigation:null});
  function setRole(draft,id,role) {
    if(!draft.tags.some(tag=>tag.id===id))return;
    if(role&&!draft.tagIds.includes(id)&&draft.tagIds.length>=30){draft.notice='最多选择 30 个 TAG。';return;}
    draft.tagIds=draft.tagIds.filter(value=>value!==id);
    draft.primaryIds=draft.primaryIds.filter(value=>value!==id);
    if(role==='primary'||role==='secondary')draft.tagIds.push(id);
    if(role==='primary')draft.primaryIds.push(id);
    draft.pending=null;
  }
  function payload(draft) {
    if(!draft.deck||!draft.fresh)return {error:'请先成功获取当前卡组。'};
    const name=draft.name.trim();
    if(!name)return {error:'请输入卡组名称。'};
    if(name.length>80||/[<>:"/\\|?*\u0000-\u001f]/.test(name)||/[. ]$/.test(name)||/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name))return {error:'名称请使用 1–80 个字符，且不要包含文件名禁用字符、保留名称或以句点结尾。'};
    return {name,deck:structuredClone(draft.deck.deck),tag_selection:{tag_ids:[...draft.tagIds],primary_ids:[...draft.primaryIds]}};
  }
  function accept(draft,result) {
    if(JSON.stringify(draft.deck?.deck)!==JSON.stringify(result.deck))draft.marks.clear();
    draft.deck={...result,name:draft.name||'YGOPro 捕捉卡组'};
    if(!draft.name)draft.name=draft.deck.name;
    draft.fresh=true;draft.captureError='';draft.pending=null;draft.notice='';
    draft.order=null;
  }
  return {create,setRole,payload,accept};
})();
if(typeof module!=='undefined')module.exports=DuelAutomatic;

function duelPlatformPage() {
  return '<div class="duel-mode-grid duel-platform-grid"><button data-duel-action="platform-ygopro" class="duel-mode duel-platform"><strong>YGOPro</strong><span>初代原版游戏</span></button><button data-duel-action="platform-ygopro2" class="duel-mode duel-platform duel-platform-ygopro2"><strong>YGOPRO2</strong><span>新一代原版游戏</span></button><button data-duel-action="platform-mdpro3" class="duel-mode duel-platform duel-platform-mdpro3"><strong>MDPRO3</strong><span>仿官方作品 Master Duel</span></button></div>';
}
function duelPlatformLabel(){return {ygopro:'YGOPro',ygopro2:'YGOPRO2',mdpro3:'MDPRO3'}[duelState().automatic.platform]||'YGOPro';}
function duelProcessText(process) {
  return process?`${process.name} · PID ${process.pid} · ${process.title||process.version||''}`:'尚未捕捉进程';
}
async function captureDuelProcess(pid,platform=duelState().automatic.platform||'ygopro') {
  if(typeof cancelSmartRecognition==='function')await cancelSmartRecognition();
  duelState().automatic.platform=platform;
  if(typeof resetCaptureDialog==='function')resetCaptureDialog();
  if(typeof disposeAutoDuel==='function')await disposeAutoDuel();
  const dialog=$('#duel-capture-dialog'),draft=duelState().automatic;
  draft.fresh=false;draft.connection=null;draft.pending=null;
  draft.order=null;if(typeof stopDuelOrderWatch==='function')stopDuelOrderWatch();
  duelState().reached=Math.min(duelState().reached,duelStages.deck);
  if(duelState().stage>duelStages.deck){duelReach(duelStages.deck);draft.page='recognition';}
  $('#duel-capture-status').textContent=`正在捕捉 ${duelPlatformLabel()}.exe…`;
  $('#duel-capture-processes').replaceChildren();
  $('#duel-capture-next').hidden=true;
  $('#duel-capture-smart').hidden=true;
  $('#duel-capture-retry').disabled=true;
  $('#duel-capture-close').disabled=true;
  dialog.dataset.busy='true';
  if(!dialog.open)dialog.showModal();
  try {
    const result=await api('/api/ygopro/attach',{platform,...(pid===undefined?{}:{pid})});
    $('#duel-capture-status').textContent=result.connected?(platform!=='ygopro'?'捕捉成功，可以开始智能化识别。':'捕捉成功，可以进入卡组识别。'):result.error;
    const processes=result.processes||[result.process];
    $('#duel-capture-processes').innerHTML=processes.filter(Boolean).map(process=>`<article><strong>${escape(duelProcessText(process))}</strong><p>${escape(process.path||'无法读取进程路径')}</p><small>${escape(process.version||process.error||'')}</small>${!result.connected&&process.supported?`<button type="button" data-capture-pid="${process.pid}">捕捉此进程</button>`:''}</article>`).join('');
    if(result.connected){draft.connection=result.process;$('#duel-capture-next').hidden=platform!=='ygopro';$('#duel-capture-smart').hidden=false;}
  } catch(error) {$('#duel-capture-status').textContent=`捕捉失败：${error.message}`;}
  finally {
    dialog.dataset.busy='false';$('#duel-capture-retry').disabled=false;$('#duel-capture-close').disabled=false;
    if(moduleUI.current==='duel')renderDuel();
  }
}
function duelRecognitionPage() {
  const draft=duelState().automatic,ready=draft.deck&&draft.fresh;
  return `<div class="duel-section-heading"><h2>卡组识别</h2><span class="duel-platform-label">YGOPro · 当前编辑卡组</span></div>
    <p class="duel-capture-summary">${escape(duelProcessText(draft.connection))}</p>
    <div class="duel-recognition-layout"><section class="duel-recognition-panel" aria-label="卡组识别缩略图">
      <header><h3>识别效果</h3><small>${ready?'已读取当前编辑器':draft.deck?'上次快照 · 请重新获取':'等待获取卡组'}</small></header>
      ${draft.deck?zones.map(zone=>`<section class="duel-recognition-zone"><h4>${zoneNames[zone]} <small>${draft.deck.deck[zone].length} 张</small></h4><div class="duel-recognition-cards">${draft.deck.deck[zone].map(code=>`<img src="/pics/${code}.jpg" alt="${escape(duelName(code))}" loading="lazy">`).join('')||'<small>暂无卡牌</small>'}</div></section>`).join(''):
        '<div class="duel-recognition-empty"><img src="/brand/duel-automatic.svg" alt=""><h3>获取你的卡组</h3><p>在 YGOPro 中打开「编辑卡组」，再点击「获取卡组」。</p></div>'}
    </section><aside class="duel-recognition-controls"><span class="duel-eyebrow">YGOPro</span><h3>${ready?'核对卡组，继续预览':'准备识别卡组'}</h3><p class="duel-capture-help">请先在 YGOPro 主菜单点击「编辑卡组」，打开要识别的卡组并停留在该页面，再点击「获取卡组」。</p><p>支持读取尚未保存的修改。修改卡牌或切换卡组后，请重新获取。</p>
      ${duelButton('get-deck',draft.deck?'重新获取卡组':'获取卡组',!draft.connection,!ready)}${duelButton('recognition-next','下一步',!ready,!!ready)}${duelButton('recapture-process','重新捕捉进程')}
      <p class="duel-recognition-status" role="status">${escape(draft.captureError||(ready?`读取成功 · ${new Date(draft.deck.captured_ms).toLocaleTimeString()}`:'尚未获取当前卡组'))}</p></aside></div>`;
}
function duelAutomaticTags() {
  const draft=duelState().automatic,query=draft.query.trim().toLocaleLowerCase();
  const selected=draft.tags.filter(tag=>draft.tagIds.includes(tag.id));
  const matches=draft.tags.filter(tag=>[tag.name,...(tag.aliases||[])].some(name=>name.toLocaleLowerCase().includes(query)));
  return `<div class="duel-auto-tag-selected">${selected.map(tag=>`<button type="button" class="deck-tag-chip ${draft.primaryIds.includes(tag.id)?'primary':'secondary'}" data-duel-auto-tag="${escape(tag.id)}" data-role="" aria-label="移除 ${escape(tag.name)} TAG">${draft.primaryIds.includes(tag.id)?'主':'副'} · ${escape(tag.name)} ×</button>`).join('')||'<small>尚未选择 TAG</small>'}</div>
    <div class="duel-auto-tag-options">${matches.slice(0,100).map(tag=>`<div><span>${escape(tag.name)}</span><div>${[['primary','主 TAG'],['secondary','副 TAG']].map(([role,label])=>{
      const current=draft.primaryIds.includes(tag.id)?'primary':draft.tagIds.includes(tag.id)?'secondary':'';
      return `<button type="button" data-duel-auto-tag="${escape(tag.id)}" data-role="${role}" aria-label="${escape(tag.name)}：${label}" aria-pressed="${current===role}">${label}</button>`;
    }).join('')}</div></div>`).join('')||'<p>没有匹配的 TAG。</p>'}</div>${matches.length>100?'<small>显示前 100 个结果，可输入名称缩小范围。</small>':''}`;
}
function duelAutomaticSaveFeedback() {
  const draft=duelState().automatic;
  if(!$('#duel-auto-save-status'))return;
  $('#duel-auto-save-status').textContent=draft.notice;
  $('#duel-auto-overwrite').hidden=!draft.pending;
  $('#duel-auto-overwrite-name').textContent=draft.pending?`已存在同名卡组「${draft.pending.name}」。覆盖更新将替换卡牌和 TAG，原版本会保留备份。`:'';
  $('#duel-auto-save').disabled=duelUI.busy||!draft.name.trim()||!draft.fresh;
}
function duelAutomaticPreview() {
  const draft=duelState().automatic;
  return `<div class="duel-auto-preview-layout"><section class="duel-auto-cards">${duelDeckPreview(draft.deck,draft.marks)}</section>
    <aside class="duel-auto-save-panel"><form id="duel-auto-save-form"><h2>保存卡组</h2><label for="duel-auto-name">卡组名称</label><input id="duel-auto-name" name="deck-name" maxlength="80" autocomplete="off" placeholder="输入卡组名称" value="${escape(draft.name)}">
      <div class="duel-auto-tag-heading"><h3>TAG 选择</h3><button type="button" data-duel-action="auto-tags">自动识别 TAG</button></div><p class="duel-auto-tag-help">按本地卡牌系列与已有 TAG 推荐，可手动调整主／副 TAG。</p>
      <label class="duel-auto-tag-search" for="duel-auto-tag-search">搜索 TAG</label><input id="duel-auto-tag-search" type="search" placeholder="搜索 TAG 名称 / 别名" value="${escape(draft.query)}">
      <div id="duel-auto-tags">${duelAutomaticTags()}</div><button id="duel-auto-save" class="primary" type="submit">保存卡组</button>
      <div id="duel-auto-overwrite" class="duel-auto-overwrite" hidden><p id="duel-auto-overwrite-name"></p><div>${duelButton('cancel-auto-overwrite','取消')}${duelButton('confirm-auto-overwrite','覆盖更新',false,true)}</div></div><p id="duel-auto-save-status" role="status" aria-live="polite"></p>
      <small>卡组和 TAG 保存到本地卡组库。卡牌标记用于本次预览。</small></form></aside></div>`;
}
async function saveDuelAutomatic(overwrite=false) {
  const draft=duelState().automatic,values=DuelAutomatic.payload(draft),pending=draft.pending;
  if(values.error){draft.notice=values.error;duelAutomaticSaveFeedback();return;}
  if(overwrite&&!pending)return;
  await duelWork(async()=>{
    try {
      const result=await api('/api/ygopro/save',{...values,...(overwrite?{overwrite:true,id:pending.id,revision:pending.revision}:{})});
      draft.pending=result.confirmation?result:null;
      draft.notice=result.saved?`已${result.overwritten?'覆盖更新':'保存'}「${result.name}」到本地卡组库。`:'';
      if(result.saved){draft.deck.name=result.name;draft.name=result.name;duelState().decks=await api('/api/decks');}
    } catch(error){draft.pending=null;draft.notice=error.message;}
  });
}
function mountDuelAutomaticPreview() {
  const draft=duelState().automatic;
  $('#duel-auto-name').oninput=event=>{draft.name=event.target.value;draft.pending=null;draft.notice='';duelAutomaticSaveFeedback();};
  $('#duel-auto-tag-search').oninput=event=>{draft.query=event.target.value;$('#duel-auto-tags').innerHTML=duelAutomaticTags();};
  $('#duel-auto-save-form').onsubmit=event=>{event.preventDefault();void saveDuelAutomatic();};
  duelAutomaticSaveFeedback();
}
async function duelAutomaticAction(action) {
  const s=duelState(),draft=s.automatic;
  if(typeof duelOrderAction==='function'&&await duelOrderAction(action))return true;
  if(action==='automatic') {
    await duelWork(async()=>{
      s.decks=await api('/api/decks');
      if(s.operationMode!=='automatic'){s.manualReached=s.reached;s.reached=Math.max(s.automatic.navigation?.reached||duelStages.function,s.automatic.workspace?.reached||0);}
      s.operationMode='automatic';s.functionPage='platform';duelReach(duelStages.function);duelTell('');
    });return true;
  }
  if(s.operationMode!=='automatic')return false;
  if(['platform-ygopro','platform-ygopro2','platform-mdpro3','recapture-process'].includes(action)) {await captureDuelProcess(undefined,action==='recapture-process'?draft.platform:action.slice(9));return true;}
  if(action==='get-deck') {
    if(typeof disposeAutoDuel==='function')await disposeAutoDuel();
    draft.fresh=false;draft.pending=null;
    await duelWork(async()=>{
      try {
        const result=await api('/api/ygopro/deck',{capture_id:draft.connection?.capture_id});
        const [options]=await Promise.all([api('/api/decks/tag-options',{deck:result.deck}),
          ...[...new Set(zones.flatMap(zone=>result.deck[zone]))].map(code=>card(code))]);
        DuelAutomatic.accept(draft,result);draft.tags=options.tags;draft.suggestions=options.suggestions;
        const available=new Set(draft.tags.map(tag=>tag.id));draft.tagIds=draft.tagIds.filter(id=>available.has(id));draft.primaryIds=draft.primaryIds.filter(id=>available.has(id));
        duelTell('');
      } catch(error){draft.captureError=`获取失败：${error.message}`;duelTell(draft.captureError);}
    });return true;
  }
  if(action==='recognition-next') {if(draft.deck&&draft.fresh){draft.page='preview';duelTell('');renderDuel();}return true;}
  if(action==='auto-tags') {
    if(draft.suggestions){draft.tagIds=[...draft.suggestions.tag_ids];draft.primaryIds=[...draft.suggestions.primary_ids];draft.pending=null;
      draft.notice=draft.tagIds.length?'已按当前卡组识别 TAG，可继续手动调整后保存。':'当前卡组未命中已有 TAG，可手动选择。';}
    $('#duel-auto-tags').innerHTML=duelAutomaticTags();duelAutomaticSaveFeedback();return true;
  }
  if(action==='cancel-auto-overwrite'){draft.pending=null;duelAutomaticSaveFeedback();return true;}
  if(action==='confirm-auto-overwrite'){await saveDuelAutomatic(true);return true;}
  return false;
}
if(typeof document!=='undefined') {
  $('#duel-capture-retry').onclick=()=>void captureDuelProcess();
  $('#duel-capture-close').onclick=()=>{if(typeof smartRun==='function'&&smartRun())void cancelSmartRecognition();else $('#duel-capture-dialog').close();};
  $('#duel-capture-dialog').addEventListener('cancel',event=>{if(typeof smartRun==='function'&&smartRun()){event.preventDefault();void cancelSmartRecognition();}else if($('#duel-capture-dialog').dataset.busy==='true')event.preventDefault();});
  $('#duel-capture-processes').onclick=event=>{const button=event.target.closest('[data-capture-pid]');if(button&&$('#duel-capture-dialog').dataset.busy!=='true')void captureDuelProcess(Number(button.dataset.capturePid));};
  $('#duel-capture-next').onclick=()=>{if(!duelState().automatic.connection||duelState().automatic.platform!=='ygopro')return;$('#duel-capture-dialog').close();duelState().automatic.page='recognition';duelReach(duelStages.deck);duelTell('');renderDuel();};
}
