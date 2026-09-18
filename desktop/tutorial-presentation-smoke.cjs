'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');

module.exports=async({page,application,evidence,pass})=>{
  const report=require('../tests/fixtures/opponent-hand-reveal.cjs')(),before=JSON.stringify(report);
  await page.evaluate(async report=>{
    await switchModule('expansion');reviewUI.report=null;mountReview(report);switchView('history');
    selectReviewNode('long');setReviewDrawer(true);
  },report);
  for(const mode of ['compact','detailed']){
    await page.evaluate(mode=>setReviewLogMode(mode),mode);
    const action=page.locator('#review-log [data-review-action="20:0"]');
    assert.equal(await action.locator('.random-card').count(),5);
    assert.equal(await action.locator('img[src="/pics/1184620.jpg"],img[src="/pics/14558127.jpg"]').count(),0);
    assert.equal(await action.locator('img[src="/pics/14442329.jpg"]').count(),2,'The own searched/revealed card stays specified');
    await action.locator('.random-card').first().click();
    assert.match(await page.locator('#review-card-detail').innerText(),/随机手牌/);
    assert.doesNotMatch(await page.locator('#review-card-detail').innerText(),/魔物狩人|灰流丽|1184620|14558127/);
    await page.evaluate(()=>closeReviewDetail());
  }
  await page.evaluate(report=>openPlanTutorial(report),report);
  const canvas=page.locator('#plan-tutorial-canvas');
  assert.equal(await canvas.locator('[data-tutorial-role*="展示对方手牌"] .tutorial-flow-card').count(),5);
  assert.equal(await canvas.locator('[data-tutorial-role*="展示对方手牌"] image[href="/review-back.svg"]').count(),5);
  assert.doesNotMatch(await canvas.textContent(),/魔物狩人|灰流丽/);
  const geometry=await page.evaluate(()=>{
    const boxes=planTutorialUI.layout.boxes;
    const clipped=[...document.querySelectorAll('#plan-tutorial-canvas .tutorial-step')].flatMap(step=>{
      const rect=step.querySelector('rect').getBBox();
      return [...step.querySelectorAll('text,image')].filter(item=>{const b=item.getBBox();return b.width&&b.height&&(b.x<rect.x-1||b.y<rect.y-1||b.x+b.width>rect.x+rect.width+1||b.y+b.height>rect.y+rect.height+1);}).map(item=>item.textContent);
    });
    return {long:boxes.find(b=>b.id==='long'),short:boxes.find(b=>b.id==='short'),clipped};
  });
  assert(geometry.long.width>geometry.short.width);assert(geometry.long.height<560);assert(geometry.short.height<300);
  assert.deepEqual(geometry.clipped,[]);assert.equal(await canvas.locator('.tutorial-connector').count(),1);
  for(const format of ['svg','png']){
    const target=path.join(evidence,'opponent-hand-tutorial.'+format);
    await application.evaluate(({BrowserWindow},target)=>{
      globalThis.presentationDownload='pending';
      BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents.session.once('will-download',(_event,item)=>{
        item.setSavePath(target);item.once('done',(_event,state)=>{globalThis.presentationDownload=state;});
      });
    },target);
    await page.locator(`[data-tutorial-export="${format}"]`).click();
    for(let i=0;i<100;i++){
      const state=await application.evaluate(()=>globalThis.presentationDownload);
      if(state!=='pending'){assert.equal(state,'completed');break;}
      assert(i<99,'Export must complete');await page.waitForTimeout(100);
    }
    assert(fs.statSync(target).size>1000);
    if(format==='svg'){
      const svg=fs.readFileSync(target,'utf8');assert.doesNotMatch(svg,/魔物狩人|灰流丽/);assert.match(svg,/随机手牌/);assert.match(svg,/data:image/);
    }
  }
  await canvas.locator('[data-tutorial-node="long"]').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(evidence,'opponent-hand-preview.png'),preserveScroll:true});
  await page.locator('#plan-tutorial-close').click();
  assert.equal(await page.evaluate(()=>JSON.stringify(reviewUI.report)),before);
  await page.evaluate(()=>{flow.draft=null;reviewUI.report=null;switchView('plans');});
  pass('Opponent reveal: five generic backs and safe popovers; own reveal preserved; compact long/short Steps, bounded content, SVG/PNG export and frozen report unchanged');
};
