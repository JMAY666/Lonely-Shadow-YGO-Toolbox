'use strict';
const SecondLiveModel={canApply:(doc,p)=>!!p?.can_apply&&!doc.closed&&p.revision===doc.revision,
  fresh:(p,now=Date.now())=>!!p?.current&&now-p.created_ms<=2000};
if(typeof module!=='undefined')module.exports=SecondLiveModel;

function secondLivePage(doc,readonly){
 const panel=doc.live_panel;if(!panel?.supported&&!doc.live_link)return '';
 const p=panel?.preview,s=p?.snapshot;
 const groups=s?[0,1].map(player=>`<section><strong>${player?'对手':'我方'}区域张数</strong><p>${Object.entries(s.counts[player]).map(([zone,n])=>`${SecondDuelModel.zones[zone]} ${n}`).join(' · ')}</p></section>`).join(''):'';
 return `<details class="second-panel" id="second-live"><summary>YGOPro 公开资源只读核对${doc.live_link?' · 已接入':''}</summary>
 <p>读取手牌、可见区域、LP、可见阶段及素材。回合玩家仅在观察到对应回合切换后显示，错过则保持待核对；完整连锁、响应时点与规则次数仍缺失。两次快照之间的动作不会被猜成费用或无效。</p>
 ${readonly?'':`<button type="button" id="second-live-read">读取公开资源</button>`}
 ${s?`<p id="second-live-freshness"></p><p>第 ${s.turn} 回合 · ${s.turn_player==null?'回合玩家待核对':s.turn_player?'对手回合':'我方回合'} · ${escape(SecondDuelModel.phases[s.phase]||'阶段待核对')} · LP ${s.lp[0]} / ${s.lp[1]}。我方手牌：${s.cards.filter(c=>c.controller===0&&c.location===2).map(c=>escape(secondName(doc,c.code))).join('、')||'无'}</p>${groups}
 <details><summary>本次可见卡牌与范围</summary><ul>${s.cards.map(c=>`<li>${c.controller?'对手':'我方'}${SecondDuelModel.zones[c.location]} · ${escape(secondName(doc,c.code))}${[4,8].includes(c.location)?` · 第 ${c.sequence+1} 格 · ${c.position&5?'表侧':'里侧'}`:c.material_host?` · 归属${c.material_host[0]?'对手':'我方'}怪兽区第 ${c.material_host[1]+1} 格`:''}</li>`).join('')}</ul><p>缺失：${s.missing.map(escape).join('；')}。</p></details>
 ${readonly?'':`<form id="second-live-apply"><label><input type="checkbox" name="confirmed" required> 已核对；更新已覆盖字段，保留起手及旧历史。未读取项、卡片用途与实例次数需重新核对。</label><button type="submit" ${SecondLiveModel.canApply(doc,p)?'':'disabled'}>再次读取核对并采用</button></form>`}`:'<p>先读取，再与当前记录核对；不会直接覆盖人工填报。</p>'}
 <p>已采用 ${panel?.history_count||0} 次资源快照。${doc.live_link?'当前资源变化请重新读取，避免重复手工扣牌。':''}</p>
 ${!readonly&&doc.live_link?'<details><summary>补充未读取的规则备注</summary><form id="second-live-rule"><label>记录类别<select name="category"><option value="usage">效果次数</option><option value="restrictions">持续限制</option></select></label><label>具体效果、范围与到期条件<textarea name="label" maxlength="500" required></textarea></label><label>状态<select name="status"><option value="unknown">尚不确定</option><option value="confirmed">人工确认</option></select></label><button type="submit">保存人工备注</button></form></details>':''}
 ${doc.live_history?.length?`<details><summary>已采用的快照历史</summary><ol>${doc.live_history.map(h=>`<li>${new Date(h.confirmed_ms).toLocaleString()} · 第 ${h.snapshot.turn} 回合 · 手牌 ${h.snapshot.counts[0]['2']} 张 · LP ${h.snapshot.lp.join(' / ')}。当时的已知状态，不是当前建议。</li>`).join('')}</ol></details>`:''}</details>`;
}
async function secondLiveRequest(action,extra={}){
 const workspace=secondWorkspace();if(!workspace||secondUI.busy||secondUI.view||workspace.readonly)return;
 const generation=workspace.generation,doc=workspace.doc;secondUI.busy=true;$('#second-error').textContent='正在只读核对当前客户端…';
 try{const value=await api('/api/second-duel/live-'+action,{id:doc.id,round_id:doc.input.round_id,revision:doc.revision,...extra});
   if(workspace!==secondWorkspace()||generation!==workspace.generation||secondUI.view)return;
   if(SecondDuelModel.accept(workspace.doc,value)){workspace.doc=value;renderDuel();$('#second-live').open=true;}
 }catch(error){if(workspace===secondWorkspace()&&$('#second-error'))$('#second-error').textContent=error.message;}
 finally{secondUI.busy=false;}
}
function mountSecondLive(){
 const read=$('#second-live-read');if(read)read.onclick=()=>void secondLiveRequest('preview');
 const form=$('#second-live-apply');if(form)form.onsubmit=e=>{e.preventDefault();void secondLiveRequest('apply',{preview_id:secondDoc().live_panel.preview.id,confirmed:new FormData(form).has('confirmed'),event_id:crypto.randomUUID().replaceAll('-','')});};
 const note=$('#second-live-rule');if(note)note.onsubmit=e=>{e.preventDefault();void secondSubmit('rule',Object.fromEntries(new FormData(note)));};
 paintSecondLive();
}
function paintSecondLive(){
 const doc=secondDoc(),p=doc?.live_panel?.preview,node=$('#second-live-freshness');
 if(node)node.textContent=SecondLiveModel.fresh(p)?'刚刚读取的一致快照；采用前还会重新核对':'历史读取结果，不能当作当前响应窗口；采用前将重新读取并比较';
 const button=$('#second-live-apply button');if(button)button.disabled=!SecondLiveModel.canApply(doc,p)||!!secondUI.view;
}
