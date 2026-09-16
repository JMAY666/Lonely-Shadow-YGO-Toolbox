'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async({page,application,evidence,pass})=>{
  let frame={monitor_id:'fixture-monitor',round_id:null,revision:1,phase:'waiting_start',detected_order:null,evidence:{turn:0},confirmed:null};
  const confirmations=[];let polls=0;
  await page.route('**/api/ygopro/order/*',async route=>{
    const action=route.request().url().split('/').pop();
    if(action==='poll')polls++;
    if(action==='confirm'){
      const body=route.request().postDataJSON();confirmations.push(body);
      frame={...frame,confirmed:{order:body.order,detected_order:frame.detected_order,source:body.manual?'manual':'automatic'}};
    }
    await route.fulfill({json:frame});
  });
  const click=async action=>{await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);};
  const state=async(phase,order=null,round=frame.round_id)=>{
    frame={...frame,phase,detected_order:order,round_id:round,revision:frame.revision+1,confirmed:null};
    await page.waitForFunction(rev=>duelState().automatic.order.frame.revision===rev,frame.revision);
  };
  try {
    await click('start-duel');assert.equal(await page.evaluate(()=>duelState().stage),3);
    assert(await page.locator('[data-duel-action="confirm-order"]').isDisabled());
    await page.screenshot({path:path.join(evidence,'order-waiting.png')});
    await state('rps',null,'first-round');assert.match(await page.locator('#duel-order-phase').textContent(),/猜拳/);
    await state('choose_order');assert(await page.locator('[data-duel-action="confirm-order"]').isDisabled());
    await state('detected','first');assert.equal(await page.locator('#duel-order-result').textContent(),'先攻');
    assert(await page.locator('#duel-steps [data-duel-stage="4"]').isDisabled());
    await page.screenshot({path:path.join(evidence,'order-first.png')});
    await click('order-manual-second');assert.equal(await page.locator('#duel-order-result').textContent(),'后攻');
    await click('confirm-order');assert.equal(await page.evaluate(()=>duelState().stage),4);
    assert.equal(confirmations[0].manual,true);assert.equal(confirmations[0].order,'second');
    assert.match(await page.locator('#duel-body').textContent(),/后攻展开功能尚未开发/);
    const before=polls;await page.waitForTimeout(800);assert.equal(polls,before,'Polling stops after confirmation');
    await click('order-return');await state('waiting_start');assert(await page.locator('[data-duel-action="confirm-order"]').isDisabled());
    assert(await page.locator('#duel-steps [data-duel-stage="4"]').isDisabled());
    assert.equal(await page.locator('#duel-order-result').textContent(),'等待确定');
    await state('rps',null,'second-round');await state('waiting_choice');await state('detected','second');
    assert.equal(await page.locator('#duel-order-result').textContent(),'后攻');assert.equal(await page.evaluate(()=>duelState().automatic.order.manual),null);
    await page.screenshot({path:path.join(evidence,'order-second.png')});
    await click('confirm-order');assert.equal(confirmations[1].manual,false);assert.equal(confirmations[1].order,'second');
    await click('order-return');await state('disconnected');assert(await page.locator('[data-duel-action="confirm-order"]').isDisabled());
    await state('detected','second');
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(960,800));
    await page.waitForFunction(()=>innerWidth===960);assert(await page.locator('#duel').evaluate(e=>e.scrollWidth===e.clientWidth));
    await page.screenshot({path:path.join(evidence,'order-narrow.png')});
    await page.locator('#duel-steps [data-duel-stage="2"]').click();
    const ended=polls;await page.waitForTimeout(800);assert(polls<=ended+1,'Leaving order step stops the polling loop');
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
    await page.waitForFunction(()=>innerWidth===1280);
    pass('Automatic order: waiting/RPS/choice gates, first/second results, explicit manual correction, confirmation persistence payload, round reset, disconnected gating, polling lifecycle and narrow layout');
  } finally {await page.unroute('**/api/ygopro/order/*');}
};
