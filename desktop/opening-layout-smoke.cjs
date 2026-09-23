'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

// Optional local-only reproduction of the user-provided opening. Never reads or
// changes a running personal profile; only the explicitly supplied local copies.
module.exports=async({page,application,root,evidence,pass})=>{
  const folder=process.env.YGO_OPENING_LAYOUT_CASE;
  if(!folder)return;
  const input=JSON.parse(fs.readFileSync(path.join(folder,'case-inputs.json'),'utf8'));
  const hand=JSON.parse(fs.readFileSync(path.join(folder,'case-hand.json'),'utf8'));
  const report=JSON.parse(fs.readFileSync(path.join(folder,'user-route.json'),'utf8'));
  const snapshot=JSON.stringify(report),identifier=crypto.randomUUID();
  assert(path.resolve(root).startsWith(path.resolve(__dirname,'../.local')+path.sep)&&root.includes('desktop-check-'),'Only isolated desktop profiles may receive this fixture');
  const deck=await page.evaluate(async deck=>api('/api/decks',{name:'后攻阅读验收 · '+Date.now(),deck}),input.decks[0].deck);
  const plan={...report,id:identifier,name:'提示员开局 · 本地复制样例'};
  const planRoot=path.join(root,'runtime','_trainer','plans'),held=[];
  for(const name of fs.readdirSync(planRoot).filter(n=>n.endsWith('.json'))){
    const file=path.join(planRoot,name),existing=JSON.parse(fs.readFileSync(file,'utf8'));
    if(existing.name?.startsWith('隔离合成路线 ')){fs.renameSync(file,file+'.fixture-hold');held.push(file);}
  }
  const copied=path.join(planRoot,identifier+'.json');
  try{
  fs.writeFileSync(copied,JSON.stringify(plan));
  await page.locator('#module-duel').click();await page.waitForFunction(()=>moduleUI.current==='duel'&&!moduleUI.switching);
  await page.evaluate(()=>startNewDuel());
  for(const action of ['bo1','manual']){await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);}
  await page.locator(`[data-duel-deck="${deck.id}"]`).click();await page.waitForFunction(()=>!duelUI.busy);
  for(const action of ['start-duel','second']){await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);}
  for(const code of hand)await page.locator(`[data-duel-add="${code}"]`).click();
  await page.locator('[data-opening-analyze]').click();await page.waitForFunction(()=>openingDuelState().result&&!openingDuelState().busy);
  const result=await page.evaluate(()=>openingDuelState().result);
  assert.equal(result.analysis.groups,1);
  assert.equal(result.handtrap_count,2);assert.equal(result.guide.active,true);
  assert.equal(result.cards.filter(c=>!c.roles.length&&!c.context).length,0);
  assert(!result.concentration.groups.some(g=>['set:17','set:46'].includes(g.id)));
  assert.equal(result.concentration.support_tags.length,2);
  assert.match(await page.locator('.opening-key-points').innerText(),/上手不等于废件/);
  assert.match(await page.locator('.opening-hand-roles').innerText(),/启动入口/);
  assert.match(await page.locator('.opening-route-section').innerText(),/含随机结果/);
  for(const key of ['composition','guide','participation','knowledge','gaps'])assert.equal(await page.locator(`[data-opening-panel="${key}"]`).getAttribute('open'),null);
  const visible=await page.locator('.opening-results').innerText();
  assert(!visible.includes('处理完成'));assert(!visible.includes('不足 3 组'));assert(!visible.includes('来源版本'));
  for(const [width,height] of [[1440,960],[960,800]]){
    await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(...size),[width,height]);
    await page.waitForFunction(width=>innerWidth===width,width);
    assert(await page.locator('#duel').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await page.locator('.opening-overview').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(evidence,`opening-review-${width}.png`),preserveScroll:true});
  }
  await page.locator('[data-opening-panel="participation"] > summary').click();
  assert(await page.locator('.opening-evidence-card').count()>0);
  await page.locator('.opening-effect-detail').first().locator('summary').click();
  assert(await page.locator('.opening-effect-detail').first().locator('.opening-stat-list').isVisible());
  await page.screenshot({path:path.join(evidence,'opening-review-evidence.png'),preserveScroll:true});
  assert.equal(JSON.stringify(JSON.parse(fs.readFileSync(path.join(folder,'user-route.json'),'utf8'))),snapshot);
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  pass('Copied user opening: five cards explained, source-random condition retained, support labels separated, details collapsed by default, 1440/960 layouts and expandable evidence; source copy unchanged');
  }finally{
    if(fs.existsSync(copied))fs.unlinkSync(copied);
    for(const file of held)fs.renameSync(file+'.fixture-hold',file);
  }
};
