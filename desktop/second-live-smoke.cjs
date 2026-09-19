'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
// External resource replies here are synthetic UI fixtures. Binary reads and
// state reconciliation have separate tests; this never connects to a real game.
module.exports=async({page,application,evidence,pass})=>{
 const original=await page.evaluate(async()=>{
  const deck=await api('/api/decks',{name:'TEST ONLY public-resource UI '+crypto.randomUUID().slice(0,8),deck:{main:Array(40).fill(1184620),extra:[],side:[]}});
  return api('/api/second-duel/start',{request_id:crypto.randomUUID().replaceAll('-',''),deck_id:deck.id,deck_revision:deck.revision,opening:Array(5).fill(1184620)});
 });
 let doc=structuredClone(original);doc.input.platform='ygopro';doc.live_panel={supported:true,history_count:0};
 const counts=[{'1':35,'2':4,'4':0,'8':0,'16':1,'32':0,'64':0},{'1':35,'2':5,'4':0,'8':1,'16':0,'32':0,'64':0}];
 const cards=Array.from({length:4},(_,i)=>({id:'known-'+i,code:1184620,owner:0,controller:0,location:2,position:10,sequence:i}));
 cards.push({id:'grave',code:1184620,owner:0,controller:0,location:16,position:5,sequence:0},
   {id:'unknown',code:null,owner:1,controller:1,location:8,position:10,sequence:0});
 const snapshot={turn:2,lp:[6000,8000],cards,counts,missing:['完整连锁','效果次数'],rules_complete:false};
 const handle=async route=>{
  const action=route.request().url().split('/').at(-1),body=route.request().postDataJSON();
  if(action==='live-preview')doc.live_panel.preview={id:'preview-'+doc.revision,revision:doc.revision,created_ms:Date.now(),snapshot:structuredClone(snapshot),current:true,can_apply:true};
  if(action==='live-apply'){
   assert(body.confirmed);assert.equal(body.preview_id,doc.live_panel.preview.id);
   const before=structuredClone(doc.current);doc.revision++;
   const currentCards=structuredClone(cards).map(c=>({...c,position:c.position===10?8:c.position===5?1:c.position}));
   for(const c of currentCards)if(c.material_host)c.host_id=currentCards.find(h=>h.location===4&&h.controller===c.material_host[0]&&h.sequence===c.material_host[1]).id;
   doc.current={...doc.current,cards:currentCards,lp:[6000,8000],phase:snapshot.phase||'unknown',turn:2,turn_player:snapshot.turn_player??null};
   doc.live_link={snapshot_id:body.preview_id};doc.live_history=[...(doc.live_history||[]),{confirmed_ms:Date.now(),snapshot:structuredClone(snapshot)}];doc.live_panel={supported:true,history_count:doc.live_history.length};
   doc.events.push({id:'event',source:'readonly_public_snapshot',summary:'核对公开资源',time_ms:Date.now(),revision:doc.revision,before,payload:{}});
   doc.status_reason='未读取的时点、完整连锁与规则仍待核对';
  }
  if(action==='close')doc.closed=true;
  return route.fulfill({json:doc});
 };
 await page.route('**/api/second-duel/*',handle);
 try{
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.evaluate(async value=>{await switchModule('duel');duelUI.state=newDuel();duelState().mode='BO1';duelState().operationMode='manual';
   secondUI.view=null;setSecondWorkspace({doc:value,generation:0});duelState().stage=duelStages.plans;duelState().reached=duelStages.plans;renderDuel();},doc);
  await page.locator('#second-live>summary').click();await page.locator('#second-live-read').click();
  await page.waitForFunction(()=>!!secondDoc().live_panel.preview&&!secondUI.busy);
  assert.equal(await page.locator('#second-hand .second-card').count(),5);
  assert.match(await page.locator('#second-live').textContent(),/未知卡牌/);
  await page.locator('#second-live-apply input').check();await page.locator('#second-live-apply button').click();
  await page.waitForFunction(()=>!!secondDoc().live_link&&!secondUI.busy);
  assert.equal(await page.locator('#second-hand .second-card').count(),4);
  assert.match(await page.locator('.second-overview').textContent(),/回合玩家待核对/);
  assert.equal(await page.locator('#second-move-form').count(),0);
  assert.equal(await page.locator('#second-routes').count(),0);
  assert.equal(await page.evaluate(()=>secondDoc().input.opening.cards.length),5);
  assert.match(await page.locator('.second-journal').textContent(),/只读资源核对/);
  snapshot.phase='main2';snapshot.turn_player=0;snapshot.turn_player_basis='observed_new_turn';
  counts[0]['4']=1;counts[0]['128']=2;
  cards.push({id:'host',code:1184620,owner:0,controller:0,location:4,position:1,sequence:0},
   ...[0,1].map(i=>({id:'material-'+i,code:1184620,owner:0,controller:0,location:128,position:1,sequence:i,material_host:[0,0]})));
  await page.locator('#second-live-read').click();await page.waitForFunction(()=>secondDoc().live_panel.preview?.snapshot.phase==='main2'&&!secondUI.busy);
  assert.match(await page.locator('#second-live').textContent(),/主要阶段 2/);
  assert.match(await page.locator('#second-live').textContent(),/归属我方怪兽区第 1 格/);
  await page.locator('#second-live-apply input').check();await page.locator('#second-live-apply button').click();
  await page.waitForFunction(()=>secondDoc().current.phase==='main2'&&!secondUI.busy);
  assert.match(await page.locator('.second-overview').textContent(),/我方回合.*主要阶段 2/);
  assert.equal(await page.locator('.second-card small').filter({hasText:'素材 ·'}).count(),2);
  assert.equal(await page.evaluate(()=>secondDoc().live_history[0].snapshot.cards.filter(c=>c.location===128).length),0);
  await page.locator('.second-public').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(evidence,'second-live-materials.png'),preserveScroll:true});
  await page.locator('#second-live').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(evidence,'second-live.png'),preserveScroll:true});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(900,650));
  await page.waitForFunction(()=>innerWidth===900);
  assert(await page.locator('#second-workspace').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.screenshot({path:path.join(evidence,'second-live-narrow.png'),preserveScroll:true});
  doc.status_reason='客户端资源已变化，当前记录尚未同步';
  await page.waitForFunction(()=>document.querySelector('#second-status').textContent.includes('客户端资源已变化'));
  assert.equal(await page.locator('#second-hand .second-card').count(),4);
  pass('Synthetic public-resource UI preserves original history, unknown turn fallback, observed phase/player, material hosts and stale-state protection');
 }finally{
  await page.unroute('**/api/second-duel/*',handle);
  await page.evaluate(async value=>{clearTimeout(secondUI.timer);setSecondWorkspace(null);await api('/api/second-duel/close',{id:value.id,round_id:value.input.round_id});},original);
 }
};
