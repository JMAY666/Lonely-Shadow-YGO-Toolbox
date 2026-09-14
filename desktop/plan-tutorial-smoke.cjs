'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

module.exports=async function({page,application,plan,pass,evidence}) {
  const before=JSON.stringify(plan);
  await page.locator('#generate-plan-tutorial').click();
  assert(await page.locator('#plan-tutorial-dialog').isVisible());
  const svg=page.locator('#plan-tutorial-canvas > svg');
  const shown=await svg.textContent();
  assert.match(shown,/起手条件/);assert.match(shown,/终场展示/);assert.match(shown,/展开流程/);
  assert(!shown.includes('展开使用资源'));
  const count=await page.locator('.tutorial-step').count();assert(count>0);
  assert.equal(await page.locator('.tutorial-connector').count(),count-1);
  const expected=await page.evaluate(()=>planTutorialUI.model.steps.flatMap(s=>s.actions).reduce((counts,a)=>({cards:counts.cards+a.stages.reduce((sum,s)=>sum+s.cards.length,0),arrows:counts.arrows+Math.max(0,a.stages.length-1)}),{cards:0,arrows:0}));
  assert.equal(await page.locator('.tutorial-flow-card image').count(),expected.cards);
  assert.equal(await page.locator('.tutorial-flow-arrow').count(),expected.arrows);
  assert(expected.cards>count,'Steps picture the individual operations rather than just a lead card');
  const longTitleLayout=await page.evaluate(()=>{
    const model=structuredClone(planTutorialUI.model),base=model.steps[0];
    const card=base.actions.flatMap(a=>a.stages.flatMap(s=>s.cards))[0];
    const many={id:'many-materials',stages:[{label:'素材',cards:Array.from({length:7},()=>({...card,name:'用于检验完整排版的很长卡牌名称',location:'对方墓地'}))},{label:'连接召唤',cards:[card]}],notes:[]};
    model.steps=Array.from({length:25},(_,i)=>({...base,id:'layout:'+i,number:i+2,title:'自定义步骤名称'.repeat(11),actions:[...base.actions,many]}));
    model.opening=[];model.conditionsNote='测试条件备注';
    document.querySelector('#plan-tutorial-canvas').innerHTML=renderPlanTutorialSvg(model);
    const bounds=[...document.querySelectorAll('.tutorial-step,.tutorial-stage')].every(step=>{
      const box=step.querySelector('rect').getBBox();
      return [...step.querySelectorAll('text,image')].every(el=>{const r=el.getBBox();return !(r.width||r.height)||(r.x>=box.x&&r.x+r.width<=box.x+box.width+1&&r.y>=box.y&&r.y+r.height<=box.y+box.height+1);});
    });
    const texts=[...document.querySelectorAll('#plan-tutorial-canvas text')];
    const empty=texts.find(el=>el.textContent.includes('未识别到指定起手')||el.textContent==='起手未记录').getBBox();
    const note=texts.find(el=>el.textContent==='测试条件备注').getBBox();
    openPlanTutorial(planTutorialUI.plan);
    return {bounds,notesBelowEmpty:note.y>empty.y+empty.height+8};
  });
  assert.deepEqual(longTitleLayout,{bounds:true,notesBelowEmpty:true});
  const overflow=await page.locator('.tutorial-step,.tutorial-stage').evaluateAll(steps=>steps.flatMap(step=>{
    const box=step.querySelector('rect').getBBox();
    return [...step.querySelectorAll('text,image')].filter(el=>{
      const r=el.getBBox();return (r.width>0||r.height>0)&&(r.x<box.x||r.x+r.width>box.x+box.width+1||r.y<box.y||r.y+r.height>box.y+box.height+1);
    }).map(el=>({step:step.dataset.tutorialNode,text:el.textContent}));
  }));
  assert.deepEqual(overflow,[],'Tutorial content must fit inside its step boxes');
  await page.screenshot({path:path.join(evidence,'plan-tutorial-preview.png'),preserveScroll:true});
  await page.locator('#plan-tutorial-zoom').click();
  assert.equal(Math.round((await svg.boundingBox()).width),1440);
  await page.locator('#plan-tutorial-zoom').click();

  for(const format of ['svg','png']) {
    const target=path.join(evidence,`plan-tutorial.${format}`);
    await application.evaluate(({BrowserWindow},target)=>{
      globalThis.tutorialExportCheck={state:'waiting'};
      BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents.session.once('will-download',(_event,item)=>{
        item.setSavePath(target);
        item.once('done',(_event,state)=>{globalThis.tutorialExportCheck={state,path:item.getSavePath()};});
      });
    },target);
    await page.locator(`[data-tutorial-export="${format}"]`).click();
    for(let i=0;i<200;i++) {
      const status=await application.evaluate(()=>globalThis.tutorialExportCheck);
      if(status.state!=='waiting') {assert.equal(status.state,'completed');break;}
      const message=await page.locator('#plan-tutorial-status').textContent();
      assert(!message.includes('导出失败'),message);
      if(i===199)throw new Error('Tutorial export did not finish');
      await page.waitForTimeout(100);
    }
    assert(fs.statSync(target).size>1000);
    if(format==='svg') {
      const data=fs.readFileSync(target,'utf8');
      assert.match(data,/href="data:image\//);assert(!data.includes('href="/pics/'));
      assert(!data.includes('href="/review-back.svg'));
      // The exported document is valid XML and contains embedded image assets.
      const validation=await page.evaluate(data=>{
        const doc=new DOMParser().parseFromString(data,'image/svg+xml');
        return {errors:doc.querySelectorAll('parsererror').length,images:doc.querySelectorAll('image').length};
      },data);assert.equal(validation.errors,0);assert(validation.images>0);
    } else {
      const png=fs.readFileSync(target);assert.equal(png.readUInt32BE(16),2880);assert(png.readUInt32BE(20)>600);
    }
  }
  // Exercise export failure without changing source data, then reopen the
  // generator. Only the test renderer's asset request is intercepted.
  await page.evaluate(()=>{planTutorialUI.assets=null;});
  await page.route('**/pics/*.jpg',route=>route.fulfill({status:503,body:'isolated failure'}),{times:1});
  await page.locator('[data-tutorial-export="svg"]').click();
  await page.waitForFunction(()=>document.querySelector('#plan-tutorial-status').textContent.includes('导出失败'));
  assert(!(await page.locator('[data-tutorial-export="svg"]').isDisabled()));
  await page.locator('#plan-tutorial-close').click();
  await page.locator('#generate-plan-tutorial').click();
  const node=await page.locator('.tutorial-step').first().getAttribute('data-tutorial-node');
  await page.locator('.tutorial-step').first().focus();await page.keyboard.press('Enter');
  await page.waitForFunction(id=>app.view==='history'&&reviewUI.node===id,node);
  assert(await page.locator('#plan-tutorial-dialog').isHidden());
  await page.evaluate(id=>showPlan(id),plan.id);
  assert.equal(JSON.stringify(await page.evaluate(id=>api(`/api/plan/${id}`),plan.id)),before);
  pass('One-image tutorial: card flows for each operation, wrapped materials, readable step and stage bounds, embedded SVG and PNG downloads, recoverable export failure and keyboard step navigation; frozen plan unchanged');
};
