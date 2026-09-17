'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async({page,application,evidence,pass})=>{
  const cards=[55144522,1184620,55144522,89631139,14558127];
  let frame={monitor_id:'opening-test',round_id:'first-hand',revision:1,phase:'detected',detected_order:'first',
    evidence:{turn:1},confirmed:null,opening:{status:'dealing',cards:[],snapshot_id:null,confirmed:null,error:''}};
  let polls=0;const writes=[];
  await page.route('**/api/ygopro/order/*',async route=>{
    const action=route.request().url().split('/').pop();if(action==='poll')polls++;
    if(action==='confirm'){frame.confirmed={order:'first',detected_order:'first',source:'automatic'};}
    await route.fulfill({json:frame});
  });
  await page.route('**/api/ygopro/opening/confirm',async route=>{
    const body=route.request().postDataJSON();writes.push(body);assert.equal(body.snapshot_id,frame.opening.snapshot_id);
    frame.opening.confirmed={snapshot_id:body.snapshot_id,cards:[...cards],confirmed_ms:1};await route.fulfill({json:frame});
  });
  const click=async action=>{await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);};
  const update=async change=>{frame={...frame,...change,revision:frame.revision+1};await page.waitForFunction(r=>duelState().automatic.order.frame.revision===r,frame.revision);};
  try {
    await click('start-duel');await click('confirm-order');
    assert.equal(await page.evaluate(()=>duelState().stage),4);assert(await page.locator('[data-duel-action="confirm-opening"]').isDisabled());
    assert.equal(await page.locator('.duel-opening-card').count(),0);
    await update({opening:{status:'ready',cards:[...cards],snapshot_id:'frozen-five',confirmed:null,captured_turn:0,error:''}});
    await page.waitForFunction(()=>document.querySelectorAll('.duel-opening-card').length===5);
    assert.equal(await page.locator('.duel-opening-card img').count(),5);
    await page.locator('.duel-opening-card img').evaluateAll(async images=>{for(const i of images){i.loading='eager';await i.decode();}});
    const sizes=await page.locator('.duel-opening-card img').evaluateAll(images=>images.map(i=>i.getBoundingClientRect().width));assert(sizes.every(w=>w>=100),'Preview uses readable card artwork');
    assert(await page.locator('.duel-opening-card .review-card').evaluateAll(buttons=>buttons.every(button=>{
      const b=button.getBoundingClientRect(),a=button.querySelector('.review-art').getBoundingClientRect(),i=button.querySelector('img').getBoundingClientRect();
      return Math.abs(a.width-b.width)<2&&Math.abs(a.height-b.height)<2&&Math.abs(i.width-b.width)<2&&Math.abs(i.height-b.height)<2;
    })),'Card art fills its clickable frame without thumbnail-sized empty space');
    await page.locator('.duel-opening-card .review-card').first().hover();await page.waitForFunction(()=>!document.querySelector('#review-card-popover').hidden);
    assert.match(await page.locator('#review-card-detail').textContent(),/强欲之壶/);await page.locator('#review-detail-close').click();
    await page.screenshot({path:path.join(evidence,'opening-first-preview.png')});
    await update({evidence:{turn:2,current_hand_count:6}});assert.equal(await page.locator('.duel-opening-card').count(),5);
    await click('confirm-opening');assert.equal(await page.evaluate(()=>duelState().stage),5);assert.equal(writes.length,1);
    assert.match(await page.locator('#duel-body').textContent(),/方案选择/);
    const stopped=polls;await page.waitForTimeout(500);assert.equal(polls,stopped,'Polling stops after opening confirmation');
    await click('opening-return');await click('order-return');
    await update({phase:'waiting_start',detected_order:null,confirmed:null,opening:null});
    assert(await page.locator('#duel-steps [data-duel-stage="4"]').isDisabled());
    await update({round_id:'second-hand',phase:'detected',detected_order:'second',confirmed:{order:'second',source:'automatic'},
      opening:{status:'ready',cards:[...cards],snapshot_id:'second-five',confirmed:null,error:''}});
    // Enter the retained result using the same confirmed-stage navigation.
    await page.locator('#duel-steps [data-duel-stage="4"]').click();
    assert.match(await page.locator('.duel-opening-panel h2').textContent(),/后攻起手留存/);
    assert.equal(await page.locator('[data-duel-action="confirm-opening"]').count(),0);assert(await page.locator('#duel-substeps').isHidden());
    assert.equal(await page.locator('.duel-opening-card').count(),5);
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(960,800));
    await page.waitForFunction(()=>innerWidth===960);assert(await page.locator('#duel').evaluate(e=>e.scrollWidth===e.clientWidth));
    await page.screenshot({path:path.join(evidence,'opening-second-preview-narrow.png')});
    await page.locator('#duel-steps [data-duel-stage="2"]').click();
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
    await page.waitForFunction(()=>innerWidth===1280);
    pass('Opening UI: partial-deal gating, full five-card preview and details, duplicate copies, immutable later-turn display, explicit confirmation, next stage, new-round reset and second-player retention');
  }finally{await page.unroute('**/api/ygopro/order/*');await page.unroute('**/api/ygopro/opening/confirm');}
};
