'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');

async function open(page,id){
  await page.evaluate(async id=>{await switchModule('duel');duelUI.state=newDuel();const s=duelState();s.mode='BO1';s.operationMode='manual';
    const doc=await api('/api/second-duel/state',{id});setSecondWorkspace({doc,generation:0});s.stage=duelStages.plans;s.reached=duelStages.plans;renderDuel();},id);
}

exports.window=async({page,evidence,pass},data)=>{
  await open(page,data.id);
  const submit=async selector=>{const revision=await page.evaluate(()=>secondWorkspace().doc.revision);await page.locator(selector+' button[type="submit"]').click();await page.waitForFunction(n=>secondWorkspace().doc.revision>n&&!secondUI.busy,revision);};
  assert.equal(await page.evaluate(()=>secondWorkspace().doc.current.turn_player),1);
  assert.equal(await page.locator('#second-move-form').count(),0);
  await page.locator('.second-hint-setup>summary').filter({hasText:'核对次数和后攻'}).click();
  assert(!await page.locator('#second-count-form').isVisible());
  await page.locator('#second-role-form [name="role"]').selectOption('free');await submit('#second-role-form');
  await page.locator('#second-verify-form [name="confirmed"]').check();await submit('#second-verify-form');
  await page.locator('.second-hint-setup>summary').filter({hasText:'填写结构化'}).click();
  const form=page.locator('#second-hint-window-form');assert.equal(await form.locator('[name="effect_id"]').inputValue(),'aluber.search');
  await form.locator('[name="other_rules"]').selectOption('none');await form.locator('[name="grave_rule"]').selectOption('normal');
  await form.locator('[name="protections_checked"]').check();await form.locator('[name="objective"]').selectOption('stop_effect');
  await form.locator('[name="confirmed"]').check();await submit('#second-hint-window-form');
  await page.locator('[data-second-action="generate-hint"]').click();await page.waitForFunction(()=>!!secondWorkspace().doc.advice&&!secondUI.busy,null,{timeout:60000});
  assert.equal(await page.evaluate(()=>secondWorkspace().doc.advice.items[0].recommendation),'use');
  const before=await page.evaluate(()=>structuredClone(secondWorkspace().doc.current));
  await page.locator('[data-second-hint-choice="use"]').first().click();await page.waitForFunction(()=>secondWorkspace().doc.advice.decisions.length===1&&!secondUI.busy);
  assert.deepEqual(await page.evaluate(()=>secondWorkspace().doc.current),before);
  await page.screenshot({path:path.join(evidence,'second-flow-opponent.png')});
  pass('Same native second-player record recognizes the opponent window, retains human conditions and records a plan without spending the hand trap');
  await page.evaluate(async()=>{await switchModule('expansion');displayView('training');await syncNativeHost();});
};

exports.review=async({page,application,evidence,pass})=>{
  const fixture=JSON.parse(fs.readFileSync(path.join(evidence,'second-flow-ui.json'),'utf8'));
  await open(page,fixture.id);
  await page.locator('#second-workspace>details>summary').filter({hasText:'对手回合交康记录'}).click();
  await page.locator('#second-hints>details>summary').filter({hasText:'提示与计划历史'}).click();
  await page.locator('.second-hint-history>summary').first().click();
  await page.locator('[data-second-review]').first().click();await page.waitForSelector('.second-window-review');
  const review=await page.locator('.second-window-review').textContent();assert.match(review,/手牌 5 张/);assert.match(review,/效果被无效/);
  assert.match(review,/当时/);assert.match(review,/随后实际/);
  await page.locator('.second-window-review').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(evidence,'second-flow-review.png'),preserveScroll:true});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(900,650));
  await page.waitForFunction(()=>innerWidth===900);assert(await page.locator('#second-workspace').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.screenshot({path:path.join(evidence,'second-flow-review-narrow.png'),preserveScroll:true});
  await page.evaluate(async()=>{await secondSubmit('close',{});});
  pass('Historical response review separates original knowledge, planned choices, actual use, exact negation events and later hidden information; narrow layout fits');
};
