'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async function({page,plan,pass,evidence}) {
  const before=JSON.stringify(plan);
  const node=plan.review.nodes.find(n=>n.state?.cards.some(c=>c.overlay_target!=null));
  assert(node,'Inspection acceptance needs a saved route with Xyz materials');
  const material=node.state.cards.find(c=>c.overlay_target!=null),host=node.state.cards.find(c=>c.instance_id===material.overlay_target);
  const materials=node.state.cards.filter(c=>c.overlay_target===host.instance_id);
  await page.evaluate(async({id,node})=>{await showReport(id);selectReviewNode(node);setReviewDrawer(false);}, {id:plan.id,node:node.id});
  await page.evaluate(id=>{const b=[...document.querySelectorAll('.review-board [data-review-card]')].find(b=>reviewUI.cards.get(b.dataset.reviewCard)?.card.instance_id===id);b.dataset.inspectionHost='true';},host.instance_id);
  const trigger=page.locator('[data-inspection-host]'),panel=page.locator('#review-card-popover');
  await trigger.hover();await page.waitForTimeout(100);assert(await panel.isHidden());
  await page.locator('#current-node-title').hover();await page.waitForTimeout(450);assert(await panel.isHidden(),'Passing quickly over a card must not open a late preview');
  const focus=await page.evaluate(()=>document.activeElement?.outerHTML);
  await trigger.hover();await panel.waitFor({state:'visible'});
  assert.equal(await page.evaluate(()=>document.activeElement?.outerHTML),focus,'Hover must not steal keyboard focus');
  assert.equal(await page.locator('#review-detail-mode').textContent(),'悬停预览');
  await page.locator('.detail-name').hover();await page.waitForTimeout(300);assert(await panel.isVisible());
  await page.locator('#review-material-tab').click();assert.equal(await page.locator('.material-list .review-card').count(),materials.length);
  const anchor=await page.evaluate(()=>reviewUI.anchor.element.dataset.reviewCard);
  for(let i=0;i<Math.min(materials.length,2);i++) {
    const card=page.locator('.material-list .review-card').nth(i);
    const name=await card.locator('small').last().textContent();
    await card.click();await page.waitForTimeout(500);assert(await panel.isVisible(),'Clicking a material keeps its information open');
    assert.equal(await page.locator('.detail-name h3').textContent(),name);
    assert.equal(await page.evaluate(()=>reviewUI.anchor.element.dataset.reviewCard),anchor);
    assert.equal(await page.evaluate(()=>reviewUI.detailHistory.length),1);
    await page.screenshot({path:path.join(evidence,'material-card-detail.png'),preserveScroll:true});
    await page.locator('#review-detail-back').click();assert.equal(await page.locator('.detail-name h3').textContent(),host.name);
    assert.equal(await page.locator('.material-list .review-card').count(),materials.length);
  }
  await page.locator('#review-body-tab').click();await page.locator('#current-node-title').hover();await page.waitForTimeout(300);assert(await panel.isVisible(),'Clicked information stays pinned');
  await page.keyboard.press('Escape');await page.waitForTimeout(450);assert(await panel.isHidden());
  await trigger.hover();await page.waitForTimeout(100);await page.evaluate(()=>selectReviewNode('final'));await page.waitForTimeout(500);assert(await panel.isHidden(),'Changing steps cancels pending hover');
  assert.equal(JSON.stringify(await page.evaluate(id=>api(`/api/plan/${id}`),plan.id)),before);
  await page.evaluate(id=>showPlan(id),plan.id);
  pass('Card details: delayed/cancelable hover, interactive preview, pinned click, Xyz material navigation with stable parent and back button, no source mutation');
};
