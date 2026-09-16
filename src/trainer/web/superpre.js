'use strict';
const superpreUI = {state:null, timer:null, request:false, applied:undefined};
function renderSuperpre(state) {
  superpreUI.state=state;
  const {installed,latest,job}=state,busy=job.busy||superpreUI.request;
  $('#superpre-state').textContent=job.busy?'处理中':!installed?'未安装':state.update_available?'有更新':'已安装';
  $('#superpre-installed').textContent=installed?`${installed.version} · ${installed.card_count} 张补丁卡 · ${dt(installed.updated_ms)}`:'未安装';
  $('#superpre-latest').textContent=latest?latest.version:'尚未检查';
  $('#superpre-updated').textContent=latest?dt(latest.updated_ms):'尚未检查';
  $('#superpre-checked').textContent=latest?dt(latest.checked_ms):'尚未检查';
  const link=$('#superpre-download');link.hidden=!latest;$('#superpre-no-download').hidden=!!latest;
  if(latest){link.href=latest.download_url;link.textContent=latest.download_url;}
  $('#superpre-check').disabled=busy;
  $('#superpre-install').disabled=busy||!!installed;
  $('#superpre-update').disabled=busy||!installed||!!latest&&!state.update_available;
  $('#superpre-uninstall').disabled=busy||!installed;
  $('#superpre-status').textContent=job.message||'';
  $('#superpre-error').textContent=job.error||'';
  const progress=$('#superpre-progress');progress.hidden=!job.busy;
  if(job.total){progress.max=job.total;progress.value=job.loaded;$('#superpre-status').textContent+=` · ${(job.loaded/1048576).toFixed(1)} / ${(job.total/1048576).toFixed(1)} MB`;}
  else progress.removeAttribute('value');
}
async function refreshSuperpreCatalog(state) {
  const identity=state.installed?.sha256||null;
  if(superpreUI.applied===undefined){superpreUI.applied=identity;return;}
  if(superpreUI.applied===identity)return;
  app.catalogEpoch=(app.catalogEpoch||0)+1;app.cache.clear();app.pendingCards.clear();
  app.searchGeneration++;app.renderGeneration++;app.detailGeneration++;
  const boot=await api('/api/bootstrap');$('#resource-count').textContent=`${boot.cards.toLocaleString()} 张卡牌`;
  // Keep every editor buffer and frozen report. Fresh lookups use the changed catalog.
  if(app.view==='decks'&&typeof search==='function') {
    await search();await renderDeck();
    if(app.selected) {
      try {await showCard(app.selected,app.targetZone);}
      catch {$('#card-detail').innerHTML='<p>当前卡牌不在已启用的卡库中。构筑已保留，可重新安装补丁后继续编辑。</p>';}
    }
  }
  superpreUI.applied=identity;
  notice('补丁资源已刷新。已有卡组和方案保留，后续展开会使用当前卡库重新校验。');
}
async function loadSuperpreSettings(checkFresh=false) {
  clearTimeout(superpreUI.timer);
  try {
    const state=await api('/api/superpre');renderSuperpre(state);
    if(!state.job.busy)await refreshSuperpreCatalog(state);
    if(state.job.busy)superpreUI.timer=setTimeout(loadSuperpreSettings,700);
    else if(checkFresh&&(!state.latest||Date.now()-state.latest.checked_ms>300000))void superpreAction('check');
  } catch(error){$('#superpre-error').textContent=error.message;$('#superpre-check').disabled=false;}
}
async function superpreAction(action) {
  if(superpreUI.request||superpreUI.state?.job.busy)return;
  superpreUI.request=true;
  if(superpreUI.state)renderSuperpre(superpreUI.state);
  let submitted=false;
  try {renderSuperpre(await api('/api/superpre',{action}));submitted=true;}
  catch(error){$('#superpre-error').textContent=error.message;}
  finally {
    superpreUI.request=false;
    if(submitted)void loadSuperpreSettings();
    else if(superpreUI.state){const error=$('#superpre-error').textContent;renderSuperpre(superpreUI.state);$('#superpre-error').textContent=error;}
  }
}
for(const action of ['check','install','update','uninstall'])$('#superpre-'+action).onclick=()=>void superpreAction(action);
for(const id of ['superpre-source','superpre-download'])$('#'+id).onclick=async event=>{
  if(window.trainerDesktop?.openPatchLink){event.preventDefault();try{await window.trainerDesktop.openPatchLink(event.currentTarget.href);}catch(error){$('#superpre-error').textContent=error.message;}}
};
// A cold launch can open settings before this final script has loaded.
if($('#app-settings-dialog').open)void loadSuperpreSettings(true);
