'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

module.exports=async({page,application,root,evidence,pass})=>{
  page.setDefaultTimeout(30000);
  const enter=async module=>{await require('./navigation-test.cjs')(page, module);await page.waitForFunction(module=>moduleUI.current===module&&!moduleUI.switching,module);};
  const relatedReady=()=>page.waitForFunction(()=>!tagManagerUI.relatedBusy&&document.querySelector('#tag-related-cards').getAttribute('aria-busy')==='false');
  const query=async value=>{
    await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/tags/related')&&r.request().postDataJSON().query===value),page.locator('#tag-related-query').fill(value)]);
    await relatedReady();
  };
  const save=async()=>{await page.locator('#tag-manager-save').click();await page.waitForFunction(()=>!tagManagerUI.dirty&&!tagManagerUI.busy);await relatedReady();};
  const original=await page.evaluate(()=>api('/api/tag-members/set:dd'));
  assert(original.cards.some(c=>c.id===89631139));assert(!original.cards.some(c=>c.id===79814787));
  const deck={main:[...Array(20).fill(89631139),...Array(20).fill(79814787)],extra:[],side:[]};
  const catalog=await page.evaluate(async()=>Object.fromEntries(await Promise.all([89631139,79814787].map(async id=>[id,await card(id)]))));
  const plan={id:crypto.randomUUID(),name:'关联 TAG 合成验收',deck_name:'合成构筑',saved_ms:Date.now(),edit_revision:0,deck,catalog,branches:[],
    actions:[89631139,79814787].map((code,i)=>({id:`${i+1}:0`,cards:[{code,controller:0}],evidence_refs:[]})),events:[]};
  const planPath=path.join(root,'runtime/_trainer/plans',plan.id+'.json');fs.writeFileSync(planPath,JSON.stringify(plan));const before=fs.readFileSync(planPath);
  await enter('tags');await page.waitForFunction(()=>tagManagerUI.loaded);
  await page.locator('#tag-manager-search').fill('青眼');await page.locator('[data-managed-tag="set:dd"]').click();await relatedReady();
  await query('79814787');
  assert.match(await page.locator('#tag-related-cards').textContent(),/传说的白石/);
  assert.match(await page.locator('#tag-related-cards').textContent(),/效果点名.*青眼白龙/);
  assert.equal(await page.evaluate(()=>tagManagerUI.dirty),false);
  assert.deepEqual(await page.evaluate(()=>api('/api/tag-members/set:dd')),original);
  const beforeRecognition=await page.evaluate(id=>api('/api/plan-tags/'+id),plan.id);
  assert(!beforeRecognition.suggestions.tag_ids.includes('set:dd'));
  await page.locator('#tag-related-cards [data-member-add="79814787"]').click();await relatedReady();
  await enter('home');await enter('tags');assert(await page.evaluate(()=>tagManagerUI.members.has(79814787)&&tagManagerUI.dirty));
  await page.route('**/api/tags/save',route=>route.fulfill({status:500,json:{error:'isolated save failure'}}),{times:1});
  await page.locator('#tag-manager-save').click();await page.waitForFunction(()=>!tagManagerUI.busy&&document.querySelector('#tag-manager-status').textContent.includes('保存失败'));
  assert(await page.evaluate(()=>tagManagerUI.dirty&&tagManagerUI.members.has(79814787)));
  await save();
  const afterRecognition=await page.evaluate(id=>api('/api/plan-tags/'+id),plan.id);
  assert(afterRecognition.suggestions.tag_ids.includes('set:dd'));
  const options=await page.evaluate(deck=>api('/api/decks/tag-options',{deck}),deck);
  const candidate=options.suggestions.candidates.find(t=>t.id==='set:dd');
  assert.equal(candidate.count,40);assert.equal(candidate.cards.find(c=>c.code===79814787).basis,'手动加入');
  assert.equal(Buffer.compare(fs.readFileSync(planPath),before),0,'Discovery and TAG edits never rewrite a saved plan');
  pass('Real card catalog: White Stone is found by its Blue-Eyes reference, discovery is read-only, adoption is shared by deck/plan matching and save failures retain edits');

  await page.locator('#tag-member-filter').fill('89631139');await page.locator('#tag-member-cards [data-member-remove="89631139"]').click();await save();
  await page.locator('#tag-excluded-section summary').click();await page.locator('#tag-excluded-cards [data-member-add="89631139"]').click();await save();
  assert(!(await page.evaluate(()=>api('/api/tag-members/set:dd'))).excluded_cards.some(c=>c.id===89631139));
  await page.reload();await page.waitForFunction(()=>document.querySelector('#resource-count')?.textContent.includes('张卡牌'));
  await enter('tags');await page.waitForFunction(()=>tagManagerUI.loaded);await page.locator('#tag-manager-search').fill('青眼');await page.locator('[data-managed-tag="set:dd"]').click();await relatedReady();
  await page.locator('#tag-member-kind').selectOption('手动加入');
  assert.match(await page.locator('#tag-member-cards').textContent(),/传说的白石/);
  const stone=page.locator('#tag-member-cards .review-card');await stone.hover();await page.locator('#review-card-popover').waitFor({state:'visible'});await page.keyboard.press('Escape');
  pass('Core exclusions can be restored; accepted associations, provenance and card hover survive page reload');

  await page.locator('#tag-manager-new').click();await relatedReady();await page.locator('#tag-manager-name').fill('融合关联验收 '+Date.now());
  await page.locator('#tag-add-search').fill('44362883');await page.locator('#tag-add-results [data-card-related="44362883"]').click();await relatedReady();
  await query('68468459');assert.match(await page.locator('#tag-related-cards').textContent(),/阿不思的落胤/);
  assert.match(await page.locator('#tag-related-cards').textContent(),/烙印融合.*效果点名/);
  await page.locator('#tag-related-cards [data-member-add="68468459"]').click();await relatedReady();await save();
  await page.locator('#tag-related-back').click();await relatedReady();
  await query('44362883');assert.match(await page.locator('#tag-related-cards').textContent(),/烙印融合/);
  await page.locator('#tag-related-kind').selectOption('text_card');await relatedReady();assert.match(await page.locator('#tag-related-cards').textContent(),/效果点名/);
  pass('A new custom TAG discovers Branded Fusion and Fallen of Albaz in both directions without relying on name prefixes');

  let release,interceptedResolve;
  const intercepted=new Promise(resolve=>{interceptedResolve=resolve;});
  await page.route('**/api/tags/related',async route=>{
    if(route.request().postDataJSON().query!=='过期查询')return route.continue();
    interceptedResolve();await new Promise(resolve=>{release=resolve;});
    await route.fulfill({json:{cards:[],total:0,script_errors:0}});
  });
  await page.locator('#tag-related-query').fill('过期查询');await intercepted;
  await query('44362883');release();await page.waitForResponse(r=>r.url().endsWith('/api/tags/related')&&r.request().postDataJSON().query==='过期查询');
  assert.match(await page.locator('#tag-related-cards').textContent(),/烙印融合/);await page.unroute('**/api/tags/related');
  await page.route('**/api/tags/related',route=>route.fulfill({status:500,json:{error:'isolated relation failure'}}),{times:1});
  await page.locator('#tag-related-refresh').click();await relatedReady();assert.match(await page.locator('#tag-related-status').textContent(),/查找失败/);
  await page.locator('#tag-related-refresh').click();await relatedReady();assert.match(await page.locator('#tag-related-cards').textContent(),/烙印融合/);
  pass('Delayed responses cannot replace a newer query; failed relationship reads recover without losing membership');

  for(const [width,height] of [[900,700],[1440,920]]){
    await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(size.width,size.height),{width,height});
    await page.waitForFunction(size=>innerWidth===size.width&&innerHeight===size.height,{width,height});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No horizontal page overflow');
    await page.locator('#tag-related-section').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(evidence,`tag-relations-${width}.png`),preserveScroll:true});
  }
  pass('TAG membership, relation reasons, filtering and recovery controls fit 900px and 1440px layouts without global input');
};
