'use strict';
const intelOpponentUI={data:null,selected:null,format:'',period:'',tag:'',q:'',busy:false,error:'',serial:0};
function intelOpponentMatches(deck,filters,data){
  if(filters.format&&deck.format!==filters.format||filters.period&&deck.period_id!==filters.period||filters.tag&&!deck.tag_ids.includes(filters.tag))return false;
  const q=tagSearchKey(filters.q);if(!q)return true;
  const values=[deck.name,deck.archetype,...deck.aliases||[],...deck.tag_ids.flatMap(id=>{const t=data.tags.find(t=>t.id===id);return [t?.name,...t?.aliases||[]];}),...[...deck.main,...deck.extra,...deck.side||[]].flatMap(c=>[String(c.code),data.cards[c.code]?.name])];
  return values.some(value=>tagSearchKey(value).includes(q));
}
function intelOpponentSources(data,ids){
  return `<div class="opponent-source-links">${[...new Set(ids)].map(id=>data.sources.find(s=>s.id===id)).filter(Boolean).map(source=>{
    const url=intelMatchupUrl(source.url);return url?`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${escape(source.title)} ↗</a>`:`<span>${escape(source.title)}</span>`;
  }).join('')}</div>`;
}
function intelOpponentCard(row,data){
  const card=data.cards[row.code]||{id:row.code,name:`卡库缺失 · ${row.code}`,missing:true};
  return `<div class="opponent-card">${tagCatalogueCard(card)}${row.quantity!==undefined?`<span class="opponent-card-quantity">×${row.quantity}</span>`:''}${card.missing?'<small>卡库缺失</small>':''}</div>`;
}
function intelOpponentRoute(route,data,index){
  return `<section class="opponent-route" id="opponent-route-${escape(route.id)}"><header><div><span class="intel-kicker">路线 ${index+1} · 卡文条件推演</span><h3>${escape(route.title)}</h3></div></header>
    <div class="opponent-opening"><h4>起手条件</h4><div class="opponent-opening-cards">${route.opening.cards.map(row=>intelOpponentCard(row,data)).join('')}</div>${route.opening.other_cards?`<p>另需 ${route.opening.other_cards} 张符合下列条件的手牌。</p>`:''}<p>${escape(route.opening.conditions)}</p></div>
    <ol class="intel-walkthrough-sequence opponent-route-steps">${route.steps.map((step,i)=>`<li><span class="intel-kicker">第 ${i+1} 步</span><div class="opponent-step-cards">${step.cards.map(code=>intelOpponentCard({code},data)).join('')}</div><h4>${escape(step.action)}</h4><p><span>得到什么</span>${escape(step.result)}</p></li>`).join('')}</ol>
    <div class="opponent-endboard"><h4>预期终场</h4><div class="opponent-endboard-cards">${route.endboard.map(row=>`<div>${intelOpponentCard(row,data)}${row.note?`<p>${escape(row.note)}</p>`:''}</div>`).join('')}</div><p>${escape(route.notes||'')}</p></div>
    <details class="opponent-route-sources"><summary>查看本路线依据</summary>${intelOpponentSources(data,route.source_ids)}</details></section>`;
}
function intelOpponentReader(deck,data){
  const period=data.periods.find(p=>p.id===deck.period_id),percent=(deck.share*100).toFixed(1);
  return `<article class="intel-opponent-reader"><header class="opponent-heading"><div class="intel-matchup-meta">${intelBadge(deck.format)}${intelBadge('只读预览')}<span>${escape(period.label)}</span><span>核对：${escape(data.checked_at)}</span></div><h2>${escape(deck.name)}</h2><div class="intel-list-tags">${deck.tag_ids.map(id=>intelBadge(data.tags.find(t=>t.id===id)?.name||id)).join('')}</div></header>
    <section class="opponent-sample"><div><span>该牌型在来源样本中的占比</span><strong>${percent}%</strong><small>${deck.sample_count} / ${deck.sample_size} 份 · ${escape(period.metric)}</small></div><div><p>${escape(period.start)} — ${escape(period.end)}</p><p>${escape(period.note)}</p><p>下面展示的是其中一份代表构筑，不代表该牌型只有这一种组成。</p></div></section>
    <p class="opponent-date">${deck.reported_date?`来源记载日期：${escape(deck.reported_date)} · `:''}${escape(deck.date_note||'')} ${escape(deck.placement||'')}</p>${intelOpponentSources(data,[...period.source_ids,...deck.source_ids])}
    ${['main','extra','side'].map(zone=>`<section class="opponent-deck-zone"><h3>${{main:'主卡组',extra:'额外卡组',side:'副卡组'}[zone]}${deck.counts[zone]===null?'':` <span>${deck.counts[zone]} 张</span>`}</h3>${deck[zone]===null?'<p>副卡组未披露，未将缺失资料当作零张。</p>':deck[zone].length?`<div class="opponent-deck-grid">${deck[zone].map(row=>intelOpponentCard(row,data)).join('')}</div>`:`<p>${zone==='side'&&deck.format==='Master Duel'?'Master Duel 标准对局无副卡组。':'来源列为 0 张。'}</p>`}</section>`).join('')}
    <section class="opponent-routes-heading"><h2>展开路线 · ${deck.routes.length} 条</h2><p>按列出的起手、素材和前置条件阅读。路线为卡文条件推演，尚未经规则引擎验证，不等同于该玩家的比赛录像或最大终场。</p><div class="opponent-route-shortcuts">${deck.routes.map((route,i)=>`<button data-opponent-route="${escape(route.id)}">路线 ${i+1} · ${escape(route.title)}</button>`).join('')}</div></section>
    ${deck.routes.map((route,i)=>intelOpponentRoute(route,data,i)).join('')}</article>`;
}
function intelOpponentRender({controls=true}={}){
  if(intelUI.tab!=='opponents')return;
  const state=intelOpponentUI,data=state.data;
  $('#intel-actions').innerHTML='';$('#intel-status').textContent=state.error?`资料读取失败：${state.error}`:state.busy?'正在读取公开构筑资料…':'按统计期从新到旧、期内按来源样本占比从高到低排列。';
  $('#intel-status').classList.toggle('intel-error',!!state.error);
  document.querySelectorAll('[data-intel-count]').forEach(el=>el.textContent=el.dataset.intelCount==='opponents'?(data?.decks.length??'只读'):Object.keys(intelUI.data?.[el.dataset.intelCount]||{}).length);
  if(!data){$('#intel-controls').innerHTML='';$('#intel-list').innerHTML='';$('#intel-editor').innerHTML='<div class="intel-empty"><h2>对手卡组资料</h2><p>公开构筑与展开路线只供预览。</p></div>';return;}
  if(controls){
    $('#intel-controls').innerHTML=`<div class="intel-group"><div class="intel-topic-navigation-heading"><span>大主题</span><button data-opponent-format="" aria-pressed="${!state.format}">全部</button></div><div class="intel-primary-topics">${['OCG','Master Duel'].map(format=>`<button data-opponent-format="${format}" aria-pressed="${state.format===format}"><strong>${format}</strong><small>${data.decks.filter(d=>d.format===format).length} 份构筑</small></button>`).join('')}</div></div>
      <div class="intel-filters"><label class="intel-filter intel-filter-search">统计期<select id="intel-opponent-period"><option value="">全部统计期</option>${data.periods.filter(p=>!state.format||p.format===state.format).map(p=>`<option value="${escape(p.id)}" ${state.period===p.id?'selected':''}>${escape(p.format+' · '+p.label)}</option>`).join('')}</select></label><label class="intel-filter intel-filter-search">搜索构筑／卡名／卡号<input id="intel-opponent-q" type="search" value="${escape(state.q)}"></label><label class="intel-filter intel-filter-tag">TAG<select id="intel-opponent-tag"><option value="">全部 TAG</option>${data.tags.map(tag=>`<option value="${escape(tag.id)}" ${state.tag===tag.id?'selected':''}>${escape(tag.name)}</option>`).join('')}</select></label><button class="intel-filter-reset" data-opponent-clear>清空筛选</button></div>`;
  }
  const decks=data.decks.filter(deck=>intelOpponentMatches(deck,state,data));
  if(!decks.some(deck=>deck.id===state.selected))state.selected=decks[0]?.id||null;
  $('#intel-list').innerHTML=`<header class="intel-list-heading"><h2>对手构筑</h2><small>${decks.length} / ${data.decks.length} 份</small></header>${data.periods.map(period=>{
    const rows=decks.filter(deck=>deck.period_id===period.id);return rows.length?`<section class="opponent-period-group"><h3>${escape(period.format)} · ${escape(period.label)}</h3>${rows.map(deck=>`<button class="opponent-list-item" data-opponent-select="${escape(deck.id)}" aria-pressed="${deck.id===state.selected}"><strong>${escape(deck.name)}</strong><span>${deck.tag_ids.map(id=>intelBadge(data.tags.find(t=>t.id===id)?.name||id)).join('')}</span><small><b>${(deck.share*100).toFixed(1)}%</b> · ${deck.sample_count} / ${deck.sample_size} 份来源样本</small></button>`).join('')}</section>`:'';
  }).join('')}${decks.length?'':'<p class="intel-list-empty">没有匹配的构筑。</p>'}`;
  const editor=$('#intel-editor'),selected=decks.find(deck=>deck.id===state.selected);
  if(editor.dataset.opponent!==state.selected){editor.dataset.opponent=state.selected||'';editor.innerHTML=selected?`<div class="intel-editor-body">${intelOpponentReader(selected,data)}</div>`:'<div class="intel-empty"><h2>没有匹配的构筑</h2></div>';}
  pruneReviewCards();
}
async function intelOpponentLoad(){
  const serial=++intelOpponentUI.serial;intelOpponentUI.busy=true;intelOpponentUI.error='';intelOpponentRender();
  try{const data=await api('/api/intelligence/opponents');if(serial!==intelOpponentUI.serial)return;intelOpponentUI.data=data;delete $('#intel-editor')?.dataset.opponent;}
  catch(error){if(serial===intelOpponentUI.serial)intelOpponentUI.error=error.message;}
  finally{if(serial===intelOpponentUI.serial){intelOpponentUI.busy=false;intelOpponentRender();}}
}
function intelOpponentClick(button){
  const state=intelOpponentUI;
  if(button.dataset.opponentFormat!==undefined){state.format=button.dataset.opponentFormat;state.period='';intelOpponentRender();return true;}
  if(button.dataset.opponentSelect){state.selected=button.dataset.opponentSelect;intelOpponentRender({controls:false});return true;}
  if(button.hasAttribute('data-opponent-clear')){Object.assign(state,{format:'',period:'',tag:'',q:''});intelOpponentRender();return true;}
  if(button.dataset.opponentRoute){document.getElementById('opponent-route-'+button.dataset.opponentRoute)?.scrollIntoView({block:'start'});return true;}
  return false;
}
function intelOpponentInput(element){
  const key={'intel-opponent-period':'period','intel-opponent-tag':'tag','intel-opponent-q':'q'}[element.id];
  if(!key)return false;intelOpponentUI[key]=element.value;intelOpponentRender({controls:false});return true;
}
