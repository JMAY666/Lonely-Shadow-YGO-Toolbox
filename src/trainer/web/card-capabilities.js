'use strict';

const CapabilityView = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function html(value, {frozen=false, purpose='', adopt=false}={}) {
    if (!value) return '<p class="capability-empty">这份旧记录没有保存标注版本；原卡文与人工标记保持不变。</p>';
    const code=Number(value.code), effects=value.effects||[];
    const badge=tag=>`<span class="capability-tag">${esc(tag.name)}</span>`;
    return `<details class="capability-panel" data-capability-card="${code}" ${frozen?'data-capability-frozen="1"':''}><summary><span>${frozen?'保存时的卡片能力':'卡片能力'} · ${esc(value.status_label)}</span><small>${effects.length} 个已标注分段</small></summary><div class="capability-content">
      ${!value.trusted?'<p class="capability-notice">资料尚未核对或当前版本不可用，仅供查阅，不生成用途候选。</p>':''}
      ${effects.length?`<div class="capability-tags">${(value.tags||[]).map(badge).join('')}</div>`:`<p>${value.no_effect&&value.trusted?'已明确标注为无效果卡。':'尚无可用于此版本的效果资料；不代表这张卡没有能力。'}</p>`}
      ${effects.map(effect=>`<details class="capability-effect" data-capability-effect="${esc(effect.key)}"><summary>${esc(effect.label)} ${(effect.tags||[]).map(badge).join('')}</summary><p class="capability-original">${esc(effect.text)}</p><dl>${(effect.facts||[]).map(row=>`<dt>${esc(row.label)}</dt><dd>${esc(row.text)}</dd>`).join('')}</dl>${(effect.notes||[]).map(note=>`<p>${esc(note.text)}</p>`).join('')}
        ${(effect.candidates||[]).filter(row=>!purpose||row.role===purpose).map(row=>`<p class="capability-candidate"><strong>${esc(row.label)}</strong> · ${esc(row.reason)}</p>`).join('')}
        ${adopt&&value.trusted&&effect.legacy_key!==null&&(effect.candidates||[]).some(row=>row.role===purpose)?`<button type="button" data-capability-select="${esc(effect.legacy_key)}">选中此效果用于${{handtraps:'手坑',breakers:'解场',endboards:'终场'}[purpose]}</button>`:''}
        <button type="button" data-capability-open="${code}" data-capability-key="${esc(effect.key)}">查看完整标注</button></details>`).join('')}
      ${(value.relations||[]).length?`<div class="capability-relations"><strong>共享次数、分支与依赖</strong>${value.relations.map(row=>`<p>${esc(row.text||row.kind)}</p>`).join('')}</div>`:''}
      <p class="capability-boundary">${esc(value.boundary)}</p><button type="button" data-capability-open="${code}">打开当前卡片标注</button><small>资料版本 ${esc(value.version?.slice(0,10)||'未知')}${frozen?' · 已冻结':''}</small></div></details>`;
  }
  function comparison(value) {
    if (!value) return '';
    return `<details class="capability-comparison"><summary>终场能力构成${value.tags.length?' · '+value.tags.map(esc).join('、'):''}</summary><p>${esc(value.basis)}</p>${value.unknown_cards?`<p>${value.unknown_cards} 张标记卡缺少可对应的已核对能力，不按零能力处理。</p>`:''}${value.effects.map(row=>`<div><strong>${esc(row.code)} · ${esc(row.key)}</strong><p>${row.facts.filter(f=>['条件','费用','次数'].includes(f.label)).map(f=>`${esc(f.label)}：${esc(f.text)}`).join('；')}</p>${row.relations.map(r=>`<p>${esc(r.text)}</p>`).join('')}</div>`).join('')}</details>`;
  }
  return {html, comparison};
})();
if(typeof module!=='undefined')module.exports=CapabilityView;

const capabilityHosts = new WeakMap();
let capabilityOptions = {tags:[]};
async function mountCapabilities(host, code, options={}) {
  if(!host)return;
  host.classList.add('capability-host');
  const token={code,options};capabilityHosts.set(host,token);
  if(options.historical){host.innerHTML=CapabilityView.html(options.snapshot,{frozen:true});return;}
  host.innerHTML='<p class="capability-loading" role="status">正在读取卡片能力…</p>';
  try {
    const value=await api('/api/capabilities',{op:'card',code:Number(code),...(options.text!==undefined?{text:options.text}:{})});
    if(!host.isConnected||capabilityHosts.get(host)!==token)return;
    host.innerHTML=CapabilityView.html(value,options);
    if(options.adopt)host.querySelectorAll('[data-capability-select]').forEach(button=>button.addEventListener('click',()=>{
      options.onSelect?.(button.dataset.capabilitySelect);
    }));
  } catch(error) {
    if(host.isConnected&&capabilityHosts.get(host)===token)host.innerHTML=`<p role="status">能力资料暂不可用：${escape(error.message)}。原有操作仍可使用。</p>`;
  }
}
function refreshCapabilities() {
  document.querySelectorAll('.capability-host').forEach(host=>{
    const value=capabilityHosts.get(host);
    if(value&&!value.options.historical)void mountCapabilities(host,value.code,value.options);
  });
  document.querySelectorAll('[data-capability-card]:not([data-capability-frozen])').forEach(panel=>{
    if(panel.closest('.capability-host')&&capabilityHosts.has(panel.closest('.capability-host')))return;
    const host=document.createElement('div');panel.replaceWith(host);
    void mountCapabilities(host,Number(panel.dataset.capabilityCard));
  });
}
function capabilityFilterOptions() {
  return '<option value="">全部效果能力</option>'+capabilityOptions.tags.map(tag=>`<option value="${escape(tag.id)}">${escape(tag.name)}</option>`).join('');
}
async function initCapabilityFilters() {
  capabilityOptions=await api('/api/capabilities');
  const select=$('#filter-effect');if(select)select.innerHTML=capabilityFilterOptions();
  const tagSelect=$('#tag-add-effect');if(tagSelect)tagSelect.innerHTML=capabilityFilterOptions();
}
async function openCapabilityAnnotation(code,key) {
  await switchModule('cardanno');
  if(moduleUI.current!=='cardanno')return;
  annoUI.tags.clear();annoUI.mode='cards';annoUI.folder=null;
  annoRenderShell();
  $('#anno-q').value=String(code);
  await annoRunQuery(0);
  const effect=key&&Array.from(document.querySelectorAll('#anno-detail [data-effect-key]')).find(el=>el.dataset.effectKey===key);
  effect?.scrollIntoView({block:'nearest'});
}
if(typeof document!=='undefined'){
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-capability-open]');
    if(button){event.preventDefault();void openCapabilityAnnotation(Number(button.dataset.capabilityOpen),button.dataset.capabilityKey).catch(error=>notice(error.message));}
  });
  document.addEventListener('card-annotations-changed',refreshCapabilities);
}
