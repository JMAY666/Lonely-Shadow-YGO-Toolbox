'use strict';

const rewindState = {id:null, data:null, busy:false, submitting:false, fetching:false, generation:0, key:null, message:'', operation:null};
const rewindErrors = {
  stale_route:'场地已有新操作，请选择节点重试。', node_unavailable:'节点已退出当前路线。',
  replay_mismatch:'重演结果与原始过程不一致。', state_mismatch:'恢复状态未通过完整校验。',
  create_failed:'无法创建恢复引擎。', replay_timeout:'恢复超过时限或展开正在退出。',
  write_failed:'恢复记录写入失败，请检查磁盘空间。', engine_closed:'场地已关闭。',
  test_validation_failed:'验收实例模拟校验失败。',
};
function resetTimelineSession(id) {
  if(rewindState.id===id)return;
  ++rewindState.generation;
  Object.assign(rewindState,{id,data:null,busy:false,submitting:false,key:null,message:'',operation:null,messageRevision:undefined});
  $('#rewind-nodes').innerHTML='<li>正在等待初始状态……</li>';
  $('#rewind-status').textContent='';
}
function timelineStep(step) {
  const title = step.kind === 'effect' ? `发动${step.cards.map(c=>c.name).filter(Boolean).join('、') || '卡片'}的效果` : step.summary;
  const code = step.cards.find(c=>Number.isInteger(c.code) && c.code>0)?.code;
  return `<div class="rewind-step">${code?`<img src="/pics/${code}.jpg" alt="">`:''}<span><small>步骤 ${step.number}</small><strong>${escape(title)}</strong>${step.observed_summary?`<small>${escape(step.observed_summary)}</small>`:''}</span></div>`;
}
function renderRewind(data) {
  const nodes = data.nodes || [], current = nodes.findIndex(n=>n.id===data.cursor);
  return nodes.map((node,index)=>{
    const active = index===current;
    const future = index>current;
    const phase = {4:'主要阶段 1',8:'战斗开始',16:'战斗阶段',128:'战斗阶段',256:'主要阶段 2'}[node.phase] || '阶段变化';
    return `<li class="${active?'rewind-current':future?'rewind-future':''}"><button type="button" data-rewind="${node.id}" ${active?'aria-current="step"':''} ${rewindState.busy || !data.available || node.restorable===false || (active && data.at_node)?'disabled':''}>
      <span class="rewind-node-label">${node.initial?'初始状态':`节点 ${node.ordinal}`}<em>${active?(data.at_node?'当前':'操作中'):future?'待替换':node.steps.length>1?'结算完成':''}</em></span>
      ${node.steps.map(timelineStep).join('') || `<strong>${node.initial?'本次起手已就绪':`第 ${node.turn} 回合 · ${phase}`}</strong>`}
      <small>第 ${node.turn} 回合 · ${phase} · LP ${node.lp[0]}</small>
      ${node.restorable===false?'<small>继承自主线 · 请从所属方案重新构建分支</small>':''}
      ${node.steps.length>1?'<small>以上步骤作为一组恢复</small>':''}</button></li>`;
  }).join('') + (data.pending?.length ? `<li class="rewind-pending"><span>正在处理 · 完成后可恢复</span>${data.pending.map(timelineStep).join('')}</li>` : '') || '<li>正在等待可恢复的初始状态……</li>';
}
async function refreshTimeline() {
  const visible=app.view==='training'||app.view==='modular'||typeof modularFieldVisible==='function'&&modularFieldVisible();
  if(rewindState.fetching || rewindState.submitting || !app.active || (!visible && !rewindState.busy)) return;
  rewindState.fetching=true;
  const id=app.active.id;
  const generation=rewindState.generation;
  try {
    const data=await api(`/api/timeline/${id}`);
    if(app.active?.id!==id || generation!==rewindState.generation)return;
    if(rewindState.id!==id)resetTimelineSession(id);
    rewindState.data=data;
    const op=data.operation;
    const busy=!!op && ['queued','running'].includes(op.status);
    if(op && !busy && rewindState.operation!==op.token) {
      rewindState.operation=op.token;
      rewindState.message=op.status==='done'?'已恢复，可从当前节点继续操作。':`恢复失败：${rewindErrors[op.error] || '恢复未完成。'}回退前的可用状态已保留。`;
      if(op.status==='done')app.reportKey=null;
      rewindState.messageRevision=data.revision;
    }
    if(!busy && rewindState.messageRevision!==undefined && data.revision!==rewindState.messageRevision)rewindState.message='';
    const changed=rewindState.busy!==busy;
    rewindState.busy=busy;
    $('#expansion-timeline').setAttribute('aria-busy',String(busy));
    $('#rewind-status').textContent=busy?'正在恢复场地，请稍候……':rewindState.message;
    if(busy){$('#native-loading').hidden=false;$('#native-loading').textContent='正在恢复场地……';}
    const key=JSON.stringify([data.nodes,data.pending,data.cursor,data.at_node,data.available,busy]);
    if(key!==rewindState.key) {
      const focused=document.activeElement?.dataset?.rewind;
      $('#rewind-nodes').innerHTML=renderRewind(data);rewindState.key=key;
      if(focused)document.querySelector(`[data-rewind="${focused}"]:not(:disabled)`)?.focus({preventScroll:true});
      if(!focused)document.querySelector('[aria-current="step"]')?.scrollIntoView({block:'nearest'});
    }
    if(changed){updateStart();await syncNativeHost();if(!busy && visible)await waitNativeFrame(id);}
  } catch(e) { $('#rewind-status').textContent=`时间轴更新失败：${e.message}`; }
  finally {rewindState.fetching=false;}
}
async function rewindTo(node) {
  if(rewindState.busy || flow.busy || !app.active || rewindState.id!==app.active.id || !rewindState.data)return;
  const id=app.active.id;
  rewindState.busy=true;rewindState.submitting=true;++rewindState.generation;rewindState.key=null;updateStart();
  $('#rewind-status').textContent='正在恢复场地，请稍候……';
  $('#rewind-nodes').innerHTML=renderRewind(rewindState.data);
  try {
    await syncNativeHost();
    await api('/api/rewind',{id,node,revision:rewindState.data.revision});
  } catch(e) {rewindState.busy=false;rewindState.message=`无法回退：${e.message}`;$('#rewind-status').textContent=rewindState.message;updateStart();await syncNativeHost();}
  finally {rewindState.submitting=false;}
  await refreshTimeline();
}
$('#rewind-nodes').addEventListener('click',run(event=>{
  const node=event.target.closest('[data-rewind]');
  if(node && !node.disabled)return rewindTo(Number(node.dataset.rewind));
}));
setInterval(()=>void refreshTimeline(),400);
