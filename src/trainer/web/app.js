'use strict';
const $ = (s) => document.querySelector(s);
const escape = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const zoneNames = {main:'主卡组',extra:'额外卡组',side:'副卡组',1:'卡组',2:'手牌',4:'怪兽区',8:'魔法陷阱区',16:'墓地',32:'除外',64:'额外卡组',128:'叠放素材'};
const statusNames = {starting:'正在启动',running:'训练中',stopping:'正在保存报告',completed:'手动结束',interrupted:'中断',damaged:'记录损坏'};
const reasons = {manual:'手动结束',client_closed:'关闭了模拟器窗口',engine_ended:'引擎提前结束',native_exit_without_end:'模拟器异常退出或记录未完成',deck_load_failed:'构筑载入失败',launch_failed:'启动失败'};
const app = {token:'',deck:{main:[],extra:[],side:[]},id:null,revision:null,dirty:false,zone:'main',cache:new Map(),offset:0,total:0,history:[],active:null,reportId:null,allEvents:false,searchGeneration:0};
const dt = (v) => v ? new Date(v).toLocaleString('zh-CN',{hour12:false}) : '未知';
const duration = (v) => `${Math.floor(v/60000)} 分 ${Math.floor(v/1000)%60} 秒`;
let noticeTimer;
function notice(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').hidden=true,6000);}
async function api(url, body){const result=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Trainer-Token':app.token},body:JSON.stringify(body)});const data=await result.json();if(!result.ok)throw new Error(data.error||'请求失败');return data;}
function run(fn){return async(...args)=>{try{await fn(...args);}catch(e){notice(e.message);}};}
async function card(code){if(!app.cache.has(code))app.cache.set(code,await api(`/api/card/${code}`));return app.cache.get(code);}
function switchView(view){$('#editor').hidden=view!=='decks';$('#history').hidden=view!=='history';$('#nav-decks').classList.toggle('active',view==='decks');$('#nav-history').classList.toggle('active',view==='history');}
function dirty(){app.dirty=true;$('#deck-status').textContent='有未保存的修改 · 保存后可开始训练';$('#start-training').disabled=true;}
async function deckList(){const decks=await api('/api/decks');$('#compact-deck').innerHTML='<option value="">选择已有构筑</option>'+decks.map(d=>`<option value="${escape(d.id)}" ${d.id===app.id?'selected':''}>${escape(d.name)}</option>`).join('');$('#deck-list').innerHTML=decks.map(d=>`<button data-deck="${escape(d.id)}" class="${app.id===d.id?'current':''}">${escape(d.name)}<small>${d.source==='existing'?'副本中已有构筑':'练习室构筑'}</small></button>`).join('')||'<p class="muted">还没有构筑，点击 ＋ 新建。</p>';}
async function openDeck(id){if(app.dirty && !confirm('当前修改尚未保存。打开另一构筑会放弃这些修改，是否继续？'))return;const d=await api(`/api/deck?id=${encodeURIComponent(id)}`);app.deck=d.deck;app.id=d.id;app.revision=d.revision;app.dirty=false;$('#deck-name').value=d.name;$('#deck-status').textContent=d.source==='existing'?'已有构筑 · 保存时创建练习室副本':'已保存 · YDK 格式';switchView('decks');await renderDeck();await deckList();updateStart();}
function updateStart(){$('#start-training').disabled=!app.id||app.dirty||!!app.active;}
async function renderDeck(){for(const zone of ['main','extra','side'])$(`#count-${zone}`).textContent=app.deck[zone].length;const items=[...new Set(app.deck[app.zone])];await Promise.all(items.map(code=>card(code).catch(()=>{app.cache.set(code,{id:code,name:`未知卡牌 ${code}`,type:0});})));$('#deck-cards').innerHTML=items.map(code=>{const c=app.cache.get(code);const qty=app.deck[app.zone].filter(x=>x===code).length;return `<div class="deck-row"><img src="/pics/${code}.jpg" alt=""><button class="card-name" data-detail="${code}">${escape(c.name)}<small>${String(code).padStart(8,'0')}</small></button><span class="qty">×${qty}</span><button class="minus" data-remove="${code}" aria-label="移除一张${escape(c.name)}">−</button></div>`;}).join('')||'<div class="empty">这一分区还是空的<br><small>选择左侧卡牌，加入构筑。</small></div>';}
async function showCard(code){const c=await card(code);$('#card-detail').innerHTML=`<img class="hero" src="/pics/${code}.jpg" alt="${escape(c.name)}卡图"><h2>${escape(c.name)}</h2><div class="card-meta">${String(code).padStart(8,'0')} · ${c.type&1?'怪兽':c.type&2?'魔法':'陷阱'}${c.extra?' · 额外卡组':''}<br>${c.type&1?`等级／阶级／LINK ${c.level&255}　ATK ${c.atk} ${c.type&0x4000000?'':`/ DEF ${c.def}`}`:''}</div><div class="add-actions"><button class="primary" data-add="${code}" data-to="${c.extra?'extra':'main'}">加入${c.extra?'额外':'主卡组'}</button><button data-add="${code}" data-to="side">加入副卡组</button></div><div class="effect">${escape(c.desc||'无效果说明')}</div><small>资料来源：${escape(c.source||'未知')}<br>卡牌定义与效果脚本保持原样。</small>`;}
async function search(){const generation=++app.searchGeneration;const q=$('#search').value;const result=await api(`/api/cards?q=${encodeURIComponent(q)}&kind=${$('#filter').value}&offset=${app.offset}`);if(generation!==app.searchGeneration)return;app.total=result.total;result.cards.forEach(c=>app.cache.set(c.id,c));$('#search-count').textContent=`${result.total.toLocaleString()} 张`;$('#search-results').innerHTML=result.cards.map(c=>`<button class="card-tile" data-detail="${c.id}" title="${escape(c.name)}" aria-label="查看${escape(c.name)}"><img loading="lazy" src="/pics/${c.id}.jpg" alt=""><span>${escape(c.name)}</span></button>`).join('')||'<p class="muted">未找到匹配卡牌。</p>';$('#prev-page').disabled=app.offset===0;$('#next-page').disabled=app.offset+60>=app.total;$('#page-number').textContent=`${Math.floor(app.offset/60)+1} / ${Math.max(1,Math.ceil(app.total/60))}`;}
async function saveDeck(){let name=$('#deck-name').value.trim();if(app.id?.startsWith('existing/')&&name===app.id.split('/').at(-1).replace(/\.ydk$/,'')){name+=' - 练习';$('#deck-name').value=name;}const saved=await api('/api/decks',{name,deck:app.deck,id:app.id,revision:app.revision});app.id=saved.id;app.revision=saved.revision;app.dirty=false;$('#deck-status').textContent='已保存 · YDK 格式';await deckList();updateStart();notice('构筑已保存，可重新打开核对或开始训练。');}
async function refreshHistory(){const previous=app.active;app.history=await api('/api/history');app.active=app.history.find(h=>['running','starting','stopping'].includes(h.status))||null;$('#history-count').textContent=app.history.length||'';$('#active-training').hidden=!app.active;$('#end-training').disabled=app.active?.status==='stopping';if(app.active){$('#active-title').textContent=`${app.active.name} · ${statusNames[app.active.status]}`;$('#active-info').textContent=`${dt(app.active.started_ms)} 开始 · 请在模拟器窗口手动操作，过程自动记录。`;}updateStart();const historyKey=JSON.stringify(app.history);if(app.historyKey!==historyKey){app.historyKey=historyKey;$('#history-list').innerHTML=app.history.map(h=>`<button class="history-item ${h.id===app.reportId?'current':''}" data-report="${h.id}"><strong>${escape(h.name)}</strong><small>${dt(h.started_ms)}</small><span class="badge ${h.status==='interrupted'?'warning':''}">${statusNames[h.status]||h.status}</span></button>`).join('')||'<div class="empty">还没有训练记录<br><small>保存构筑后，开始第一次训练。</small></div>';};if(previous&&!app.active){await showReport(previous.id);notice('训练记录已保存。');}else if(app.reportId && !$('#history').hidden && app.reportId===app.active?.id){await showReport(app.reportId,false);}}
function cardsHtml(cards){return `<div class="report-cards">${cards.map(c=>`<div class="mini-card"><img src="/pics/${c.code}.jpg" alt="${escape(c.name)}"><small>${escape(c.name)}<br>#${c.instance_id??'未知'}</small></div>`).join('')}</div>`;}
function loc(l) {
  if (!l) return '未知区域';
  const side = l.controller === 0 ? '我方' : l.controller === 1 ? '占位方' : '未知方';
  if (l.location & 128) return side + '叠放素材';
  if (l.location === 4) return side + (l.sequence >= 5 ? `额外怪兽区 ${l.sequence - 4}` : `主怪兽区 ${l.sequence + 1}`);
  return side + (zoneNames[l.location] || '未知区域') + (l.location === 8 ? ` ${l.sequence + 1}` : '');
}

function positions(v){return ({1:'攻击表示',2:'里侧攻击表示',4:'守备表示',8:'里侧守备表示'})[v]||'表示未知';}
function eventSummary(e){const names=e.cards.map(c=>c.name||String(c.code||'未知')).join('、');let text=names;if(e.origin)text+=`　${loc(e.origin)} → ${loc(e.destination)}`;if(e.cost)text+=`　费用：${e.cost.lp!==undefined?`${e.cost.lp} LP`:'引擎标记 COST'}`;if(e.chain)text+=`　连锁 ${e.chain}`;if(e.message===41)text+=`　${({1:'抽卡阶段',2:'准备阶段',4:'主要阶段 1',8:'战斗开始',128:'战斗结束',256:'主要阶段 2',512:'结束阶段'})[e.value]||e.value}`;if(e.amount!==undefined)text+=`　${e.player===0?'我方':'占位方'} ${e.amount} LP`;if(e.result)text+=`　${e.result}`;return text||'具体内容见原始事件；未提供的语义为未知。';}
async function showReport(id, navigate = true) {
  app.reportId = id;
  const r = await api(`/api/report/${id}`);
  if (app.reportId !== id) return;
  if (navigate) switchView('history');
  const renderKey = `${id}:${r.report_version}:${r.record_count}:${r.status}:${app.allEvents}`;
  if (app.reportKey !== renderKey) {
    app.reportKey = renderKey;
    $('#report').innerHTML = renderTrainingReport(r, {raw: app.allEvents});
    $('#all-events').onchange = run(async e => {
      app.allEvents = e.target.checked;
      await showReport(id, false);
    });
  }
  document.querySelectorAll('[data-report]').forEach(b => b.classList.toggle('current', b.dataset.report === id));
}

document.addEventListener('click',run(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.deck)return openDeck(b.dataset.deck);if(b.dataset.detail)return showCard(Number(b.dataset.detail));if(b.dataset.add){const code=Number(b.dataset.add),zone=b.dataset.to;const limit=zone==='main'?60:15;if(app.deck[zone].length>=limit)return notice('该分区已达到数量上限。');app.deck[zone].push(code);dirty();return renderDeck();}if(b.dataset.remove){const index=app.deck[app.zone].indexOf(Number(b.dataset.remove));if(index>=0)app.deck[app.zone].splice(index,1);dirty();return renderDeck();}if(b.dataset.zone){app.zone=b.dataset.zone;document.querySelectorAll('[data-zone]').forEach(t=>t.classList.toggle('selected',t===b));return renderDeck();}if(b.dataset.report)return showReport(b.dataset.report);}));
$('#nav-decks').onclick=()=>switchView('decks');$('#nav-history').onclick=run(async()=>{switchView('history');await refreshHistory();});
$('#save-deck').onclick=run(saveDeck);$('#deck-name').oninput=dirty;
$('#new-deck').onclick=run(async()=>{if(app.dirty&&!confirm('当前修改尚未保存。是否放弃并新建？'))return;app.deck={main:[],extra:[],side:[]};app.id=null;app.revision=null;$('#deck-name').value='新构筑';dirty();switchView('decks');await renderDeck();await deckList();});
let searchTimer;$('#search').oninput=()=>{clearTimeout(searchTimer);app.offset=0;searchTimer=setTimeout(run(search),200);};$('#filter').onchange=run(async()=>{app.offset=0;await search();});$('#prev-page').onclick=run(async()=>{app.offset=Math.max(0,app.offset-60);await search();});$('#next-page').onclick=run(async()=>{app.offset+=60;await search();});
$('#start-training').onclick=run(async()=>{if(app.dirty||!app.id)return notice('请先保存构筑。');$('#start-training').disabled=true;try{const session=await api('/api/start',{deck_id:app.id});app.reportId=session.id;await refreshHistory();notice('已启动模拟器。请在训练窗口手动展开，完成后点击“结束训练”。');}finally{updateStart();}});
$('#end-training').onclick=run(async()=>{if(!app.active)return;await api('/api/stop',{id:app.active.id});await refreshHistory();});$('#view-live').onclick=run(()=>showReport(app.active.id));$('#refresh-history').onclick=run(refreshHistory);
window.addEventListener('beforeunload',e=>{if(app.dirty){e.preventDefault();e.returnValue='';}});
run(async()=>{const data=await api('/api/bootstrap');app.token=data.token;$('#resource-count').textContent=`${data.cards.toLocaleString()} 张本地卡牌`;await Promise.all([deckList(),search(),refreshHistory(),renderDeck()]);updateStart();setInterval(()=>refreshHistory().catch(()=>{}),1500);})();

$('#compact-open').onclick=run(()=>{const id=$('#compact-deck').value;if(id)return openDeck(id);notice('请先选择构筑。');});
$('#compact-new').onclick=()=>$('#new-deck').click();
