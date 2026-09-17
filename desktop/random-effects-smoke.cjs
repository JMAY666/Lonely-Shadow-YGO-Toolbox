'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
const fixture=require('../tests/fixtures/random-reveal.cjs');
module.exports=async function({page,plan,pass,evidence}) {
  const original=JSON.stringify(await page.evaluate(id=>api('/api/plan/'+id),plan.id));
  try {
    await page.evaluate(report=>{
      reviewUI.report=null;mountReview(report);switchView('history');selectReviewNode('reveal');setReviewDrawer(true);setReviewLogMode('compact');
    },fixture());
    const action=page.locator('#review-log [data-review-action="10:0"]');
    for(const mode of ['compact','detailed']) {
      await page.evaluate(mode=>setReviewLogMode(mode),mode);
      assert.match(await action.locator('.log-effect-description').innerText(),/②效果[\s\S]*作为同调素材送去墓地/);
      const flow=action.locator(mode==='compact'?'.compact-chain':'.log-operation');
      assert.match((await flow.allTextContents()).join(' '),/放回对方卡组最下面/);
      assert.equal(await action.locator('.random-card').count(),4);
      assert.equal(await action.locator('img[src="/pics/52155219.jpg"],img[src="/pics/56003780.jpg"]').count(),0);
      const random=action.locator('.random-card').first();
      await random.click();
      assert.equal(await page.locator('.detail-name h3').textContent(),'随机牌');
      assert.match(await page.locator('.detail-effect').innerText(),/来自对方卡组顶部/);
      assert.match(await page.locator('.detail-effect').innerText(),/翻开后仍按效果选择/);
      await page.evaluate(()=>closeReviewDetail());
      await action.scrollIntoViewIfNeeded();
      await page.screenshot({path:path.join(evidence,`random-reveal-${mode}.png`),preserveScroll:true});
    }
    const tutorial=await page.evaluate(()=>renderPlanTutorialSvg(buildPlanTutorial(reviewUI.report)));
    assert(tutorial.includes('随机牌'));assert(tutorial.includes('作为同调素材送去墓地'));
    assert(!tutorial.includes('/pics/52155219'));
  } finally {await page.evaluate(id=>showPlan(id),plan.id);}
  assert.equal(JSON.stringify(await page.evaluate(id=>api('/api/plan/'+id),plan.id)),original);
  pass('Random deck-top cards, identified effect text and opponent top/bottom destination across compact/detail logs, popovers and tutorial; saved source unchanged');
};
