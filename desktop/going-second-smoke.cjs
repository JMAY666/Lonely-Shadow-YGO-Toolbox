'use strict';
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs'),crypto=require('node:crypto');
module.exports=async({page,application,root,evidence,pass})=>{
  const enter=async name=>{await page.locator('#module-'+name).click();await page.waitForFunction(n=>moduleUI.current===n&&!moduleUI.switching,name);};
  const click=async name=>{await page.locator(`[data-duel-action="${name}"]`).click();await page.waitForFunction(()=>!duelUI.busy);};
  const hand=[23434538,94145021,91800273,54693926,24224830];
  const deck=await page.evaluate(async hand=>{
    const deck={main:[...hand,65681983,...Array(34).fill(1184620)],extra:[],side:[]};
    return api('/api/decks',{name:'后攻起手隔离验收 '+Date.now(),deck});
  },hand);
  const catalog=await page.evaluate(async hand=>Object.fromEntries(await Promise.all(hand.map(async code=>[code,await card(code)]))),hand);
  const actor={code:hand[0],controller:0,location:2,sequence:0,instance_id:1,name:catalog[hand[0]].name};
  const state={cards:[actor]},identifier=crypto.randomUUID();
  const plan={id:identifier,name:'隔离合成路线 '+identifier,deck:deck.deck,catalog,initial_hand:[actor],
    expansion:{turn_order:'first',notes:'仅用于界面与资料合同验收，不代表实际合法展开。'},
    requirements:{opening:[{code:hand[0],count:1}],main:[{code:hand[0],count:1}],extra:[],warnings:[]},
    events:[70,72,73].map((message,i)=>({id:`${i+2}:0`,native_seq:i+2,time_ms:i,message,chain:1,cards:message===70?[actor]:[]})),
    review:{complete:true,nodes:[{id:'initial',kind:'initial',state_ref:1,state},{id:'step',kind:'step',number:1,state},{id:'final',kind:'final',state}],
      module_graph:{modules:[{id:'a',player:0,seq:1,state}],connections:[{from:'a',decision:{selection:[]}}]}},
    final_state:state,annotations:{final_marks:{'1':{marked:true,effects:{'0':{note:'合成展示标记'}}}}},branches:[]};
  const planRoot=path.join(root,'runtime','_trainer','plans');fs.mkdirSync(planRoot,{recursive:true});
  fs.writeFileSync(path.join(planRoot,identifier+'.json'),JSON.stringify(plan));
  const copy=crypto.randomUUID();fs.writeFileSync(path.join(planRoot,copy+'.json'),JSON.stringify({...plan,id:copy,name:plan.name+'复制'}));
  await enter('duel');await click('bo1');await click('manual');
  await page.locator(`[data-duel-deck="${deck.id}"]`).click();await page.waitForFunction(()=>!duelUI.busy);
  await click('start-duel');await click('second');
  for(const code of hand)await page.locator(`[data-duel-add="${code}"]`).click();
  await page.locator('[data-opening-analyze]').click();await page.waitForFunction(()=>openingDuelState().result&&!openingDuelState().busy);
  let result=await page.evaluate(()=>openingDuelState().result);
  assert.equal(result.hand_count,5);assert.equal(result.handtrap_count,3);assert(result.warnings.length>=4);
  assert.match(await page.locator('.opening-results').innerText(),/护航/);assert.match(await page.locator('.opening-results').innerText(),/基本展开与补点/);
  assert(result.analysis.groups>=1);const recorded=result.analysis.routes.find(r=>r.sources.some(s=>s.plan_id===identifier));
  assert.equal(recorded.sources.length,2);assert.equal(recorded.effects[0].attempts,1);
  const routeCard=page.locator('.opening-route-card').filter({hasText:plan.name}).first();
  await routeCard.locator('.opening-route > summary').click();
  assert.match(await routeCard.innerText(),/来源标记/);
  pass('Recorded route UI: copied source deduplication, local effect evidence, conditional resource check and sourced terminal items use synthetic isolated records');
  assert.equal(await page.locator('[data-opening-panel="participation"]').getAttribute('open'),null);
  assert.equal(await page.locator('[data-opening-panel="knowledge"]').getAttribute('open'),null);
  assert.equal(await page.locator('.duel-opening-picker').getAttribute('open'),null);
  await page.locator('[data-opening-panel="knowledge"] > summary').click();
  await page.locator('[data-opening-panel="knowledge"] .opening-card [data-review-card]').first().click();await page.waitForFunction(()=>!document.querySelector('#review-card-popover').hidden);
  assert.match(await page.locator('#review-card-detail').innerText(),/增殖|锁鸟|吸引者|结界波|指名者/);await page.locator('#review-detail-close').click();
  await page.locator('.opening-resource-tools > summary').click();
  await page.locator('[data-opening-supplement]').selectOption('65681983');await page.locator('[data-opening-add]').click();
  assert.equal(await page.evaluate(()=>openingDuelState().result),null);
  await page.locator('[data-opening-analyze]').click();await page.waitForFunction(()=>openingDuelState().result);
  assert.equal(await page.evaluate(()=>openingDuelState().result.frozen.length),5);assert.equal(await page.evaluate(()=>openingDuelState().result.hand_count),6);
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(960,800));
  await page.waitForFunction(()=>innerWidth===960);assert(await page.locator('#duel').evaluate(e=>e.scrollWidth===e.clientWidth));
  await page.screenshot({path:path.join(evidence,'going-second-narrow.png')});
  // Real late HTTP response: leave the view before releasing it.
  let release;const gate=new Promise(resolve=>release=resolve);let started=false;
  await page.route('**/api/opening/analyze',async route=>{const response=await route.fetch();started=true;await gate;await route.fulfill({response});});
  await page.locator('[data-opening-analyze]').click();await page.waitForFunction(()=>openingDuelState().busy);
  while(!started)await new Promise(resolve=>setTimeout(resolve,20));
  await page.locator('#duel-steps [data-duel-stage="3"]').click();release();await page.waitForTimeout(200);
  assert.equal(await page.evaluate(()=>openingDuelState().result),null);await page.unroute('**/api/opening/analyze');
  await click('first');assert.equal(await page.locator('[data-duel-action="match"]').count(),1);
  assert.equal(await page.locator('[data-opening-analyze]').count(),0);
  pass('Manual second opening: physical hand counts, conditional conflicts, protection, card detail, separate supplement, narrow layout, late response rejection and first-player regression');
  await enter('intelligence');await page.locator('[data-intel-tab="opening"]').click();
  await page.locator('[data-opening-deck]').selectOption(deck.id);await page.waitForFunction(()=>openingIntel.result&&!openingIntel.busy);
  const revision=await page.evaluate(()=>openingIntel.result.revision);
  const form=page.locator('[data-opening-form="override"]').first();
  const key=await form.getAttribute('data-key');
  await form.locator('textarea').fill('人工说明 <保留>');await form.locator('select[name="priority"]').selectOption('secondary');
  await form.locator('button[type="submit"]').click();await page.waitForFunction(r=>!openingIntel.busy&&openingIntel.result.revision===r,revision+1);
  await page.locator(`[data-opening-command="suggest"][data-key="${key}"]`).click();await page.waitForFunction(r=>!openingIntel.busy&&openingIntel.result.revision===r,revision+2);
  assert.equal(await page.locator(`[data-opening-form="override"][data-key="${key}"] textarea`).inputValue(),'人工说明 <保留>');
  await page.route('**/api/opening/save',route=>route.fulfill({status:400,json:{error:'隔离测试：磁盘不可写'}}));
  await page.locator(`[data-opening-form="override"][data-key="${key}"] textarea`).fill('保存失败保留');
  await page.locator(`[data-opening-form="override"][data-key="${key}"] button[type="submit"]`).click();
  await page.waitForFunction(()=>document.querySelector('.opening-error').textContent.includes('保存失败'));
  assert.equal(await page.locator(`[data-opening-form="override"][data-key="${key}"] textarea`).inputValue(),'保存失败保留');
  await page.unroute('**/api/opening/save');await page.locator(`[data-opening-form="override"][data-key="${key}"] button[type="submit"]`).click();
  await page.waitForFunction(r=>!openingIntel.busy&&openingIntel.result.revision===r,revision+3);
  assert(await page.locator('#intelligence').evaluate(e=>e.scrollWidth===e.clientWidth));
  await page.screenshot({path:path.join(evidence,'going-second-intelligence.png')});
  const input={deck_id:deck.id,revision:deck.revision,hand:[]};
  const persisted=await page.evaluate(input=>api('/api/opening/analyze',input),input);
  await page.locator('[data-intel-tab="handtraps"]').click();assert(await page.locator('#intel-controls').isVisible());
  pass('Intelligence opening workspace: read-only local derivation, controlled save, preserved human override, candidate generation, failed-save draft retention, existing library navigation');
  // Smart second-player navigation consumes the same view, with a transport fixture.
  await enter('duel');
  const automaticResult={...result,source:{kind:'automatic',round_id:'second-fixture',snapshot_id:'five'}};
  await page.route('**/api/opening/analyze',route=>route.fulfill({json:automaticResult}));
  await page.evaluate(async ({deck,hand})=>{
    const s=duelState();s.operationMode='automatic';s.stage=duelStages.function;
    const run={id:'second-fixture',cancelled:false,entered:false,cycle:0,previous:DuelAutomatic.create(),navigation:{stage:1,reached:1}};
    s.automatic=DuelAutomatic.create();s.automatic.smartRun=run;
    await acceptSmartRecognition(run,{id:run.id,stage:'second',cycle:0,construction:{deck:deck.deck},tag_result:{tag_names:{},selection:{tag_ids:[],primary_ids:[]}},
      frame:{monitor_id:'fixture',round_id:'second-fixture',phase:'detected',confirmed:{order:'second'},opening:{status:'ready',snapshot_id:'five',cards:hand}}});
  },{deck,hand});
  await page.waitForFunction(()=>duelState().stage===4&&openingDuelState().result);
  assert.equal(await page.locator('.duel-opening-card').count(),5);
  assert.equal(await page.locator('.opening-workspace h2').textContent(),'后攻起手分析');
  await page.evaluate(async()=>{const run=smartRun();await acceptSmartRecognition(run,{id:run.id,stage:'waiting',cycle:1,events:[],frame:null});});
  assert.equal(await page.evaluate(()=>openingDuelState().result),null);
  await page.evaluate(()=>{duelState().automatic.smartRun.cancelled=true;duelState().automatic.smartRun=null;$('#duel-capture-dialog').close();});
  await page.unroute('**/api/opening/analyze');
  pass('Automatic frozen second opening shares the analysis view; new-round transition clears results and never opens first-player planning');
  return {input,persisted};
};
