'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
module.exports = async function ({page,application,deckId,deck,pass,evidence}) {
  const selectModule = async name => {
    await page.locator(`#module-${name}`).click();
    await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);
  };
  const open = async () => {
    if (await page.locator('#deck-workbench').isVisible()) await page.locator('#back-to-decks').click();
    await page.locator('[data-open-deck='+JSON.stringify(deckId)+']').click();
    await page.waitForFunction(id=>app.id===id&&!app.busy,deckId);
  };
  const originalName = await page.locator('#deck-name').inputValue();
  assert.equal(await page.locator('#start-training').isVisible(),false);
  assert.equal(await page.locator('#expansion-navigation').isVisible(),false);
  await page.locator('#deck-name').fill(originalName+' 独立未保存');
  await page.evaluate(()=>addCard(55144522,'side'));
  const standalone = await page.evaluate(()=>({deck:structuredClone(app.deck),undo:structuredClone(app.undo)}));
  await selectModule('tags');
  assert.equal(await page.locator('#module-tags').getAttribute('aria-current'),'page');
  assert.equal(await page.locator('#tags').isVisible(),true);
  assert.equal(await page.locator('#expansion-navigation').isVisible(),false);
  await selectModule('home');
  assert.match(await page.evaluate(()=>unsavedSummary()),/独立卡组编辑有未保存/);
  assert.equal(await page.locator('#editor').isVisible(),false);
  await page.locator('#home-expansion').click();
  await page.waitForFunction(()=>moduleUI.current==='expansion'&&!moduleUI.switching);
  assert.equal(await page.locator('#module-expansion').getAttribute('aria-current'),'page');
  assert.equal(await page.locator('#deck-manager').isVisible(),true);
  assert.equal(await page.locator('#nav-design').isDisabled(),true);
  assert.equal(await page.locator('#nav-training').isDisabled(),true);
  assert.deepEqual(await page.evaluate(()=>app.deck),{main:[],extra:[],side:[]});
  await open();
  assert.deepEqual(await page.evaluate(()=>app.deck),deck);
  await page.evaluate(()=>addCard(1184620,'side'));
  const expansion = await page.evaluate(()=>({deck:structuredClone(app.deck),undo:structuredClone(app.undo)}));
  await selectModule('decks');
  assert.equal(await page.locator('#deck-name').inputValue(),originalName+' 独立未保存');
  assert.deepEqual(await page.evaluate(()=>({deck:app.deck,undo:app.undo})),standalone);
  assert.match(await page.evaluate(()=>unsavedSummary()),/展开内卡组编辑有未保存/);
  await page.locator('#deck-name').fill(originalName);
  await page.locator('#save-deck').click();
  await page.waitForFunction(()=>!app.busy&&!app.dirty);
  await selectModule('expansion');
  assert.deepEqual(await page.evaluate(()=>({deck:app.deck,undo:app.undo})),expansion);
  await page.locator('#save-deck').click();
  await page.waitForFunction(()=>!app.busy&&document.querySelector('#notice').textContent.includes('已被修改'));
  assert.equal(await page.evaluate(()=>app.dirty),true);
  assert.deepEqual(await page.evaluate(()=>app.deck),expansion.deck);
  await page.locator('#back-to-decks').click();
  await page.locator('#leave-deck-dialog [value="cancel"]').click();
  assert.deepEqual(await page.evaluate(()=>app.deck),expansion.deck);
  await page.locator('#back-to-decks').click();
  await page.locator('#leave-deck-dialog [value="discard"]').click();
  await page.waitForFunction(()=>!app.busy&&!app.dirty);
  await open();
  assert.deepEqual(await page.evaluate(()=>app.deck),standalone.deck);
  // Restore the shared fixture before running the original complete expansion flow.
  await page.evaluate(()=>removeCard(55144522,'side'));
  await page.locator('#save-deck').click();
  await page.waitForFunction(()=>!app.busy&&!app.dirty);
  assert.deepEqual(await page.evaluate(()=>app.deck),deck);
  pass('Independent editor retains all controls; separate unsaved decks/undo, shared saves, conflict refusal and cancel/confirm reopening');

  await page.locator('#start-training').click();
  await page.waitForFunction(()=>!!flow.design&&app.view==='design');
  await page.locator('#plan-name').fill('模块切换前置设计');
  await page.locator('#plan-notes').fill('前置内容保留');
  await page.locator('#design-back').click();
  await page.waitForFunction(()=>!!flow.deckEdit&&app.view==='decks');
  await page.evaluate(()=>addCard(1184620,'side'));
  const temporary = await page.evaluate(()=>({deck:structuredClone(app.deck),design:structuredClone(flow.design)}));
  await selectModule('decks');
  assert.equal(await page.locator('#save-deck').textContent(),'保存构筑');
  assert.equal(await page.locator('#design-deck-edit').isVisible(),false);
  await page.locator('#deck-name').fill(originalName+' 保留草稿');
  await selectModule('home');
  await selectModule('expansion');
  assert.deepEqual(await page.evaluate(()=>({deck:app.deck,design:flow.design})),temporary);
  assert.equal(await page.locator('#save-deck').textContent(),'应用卡组并返回条件');
  await page.locator('#cancel-design-deck-edit').click();
  await page.locator('#flow-cancel').click();
  assert.equal(await page.evaluate(()=>!!flow.deckEdit),true);
  await page.locator('#cancel-design-deck-edit').click();
  await page.locator('#flow-confirm').click();
  await page.waitForFunction(()=>!flow.deckEdit&&app.view==='design'&&!app.busy);
  assert.equal(await page.locator('#plan-name').inputValue(),'模块切换前置设计');
  await selectModule('decks');
  assert.equal(await page.locator('#deck-name').inputValue(),originalName+' 保留草稿');
  await page.locator('#deck-name').fill(originalName);
  await selectModule('expansion');
  await page.locator('#plan-name').fill('');
  await page.locator('#plan-notes').fill('');
  await page.locator('#nav-decks').click();
  pass('Preparation, temporary design deck edit, explicit discard confirmation and the independent draft survive round-trip navigation');

  for (const [width,height] of [[900,650],[1100,800],[1600,1000]]) {
    await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(...size),[width,height]);
    await page.waitForFunction(width=>innerWidth===width,width);
    await page.screenshot({path:path.join(evidence,`module-editor-${width}.png`)});
    const layout = await page.evaluate(()=>{
      const rail=document.querySelector('.primary-rail').getBoundingClientRect();
      const drawer=document.querySelector('#card-library').getBoundingClientRect();
      return {rail:{left:rail.left,right:rail.right},drawer:{left:drawer.left,right:drawer.right,top:drawer.top,bottom:drawer.bottom},
        overflow:document.documentElement.scrollWidth>innerWidth, width:innerWidth,height:innerHeight,
        allZones:['main','extra','side'].every(z=>!!document.querySelector('#cards-'+z))};
    });
    assert.equal(layout.overflow,false,JSON.stringify(layout));
    assert(layout.drawer.left>=layout.rail.right&&layout.drawer.right<=width&&layout.drawer.top>=0&&layout.drawer.bottom<=height,JSON.stringify(layout));
    assert.equal(layout.rail.left,0);
    assert(layout.allZones);
    const compact=await page.evaluate(()=>{
      const panels=[...document.querySelectorAll('.workspace>.panel')].map(p=>p.getBoundingClientRect());
      const back=document.querySelector('#back-to-decks').getBoundingClientRect();
      const header=parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-bar-height'));
      return {aligned:panels.every(p=>Math.abs(p.top-panels[0].top)<1),top:panels[0].top,header,
        inline:back.top>=panels[1].top&&back.left>=panels[1].left&&back.right<=panels[1].right,
        buttonsFit:[...document.querySelectorAll('.editor-tools button')].every(b=>b.scrollWidth<=b.clientWidth+1)};
    });
    assert(compact.aligned&&compact.inline&&compact.buttonsFit&&compact.top<=compact.header+16,JSON.stringify(compact));
    const editor=await page.locator('#editor').boundingBox();
    const state=await page.evaluate(()=>JSON.stringify({deck:app.deck,undo:app.undo,design:flow.design}));
    await page.locator('#navigation-toggle').click();
    assert.equal(await page.locator('#primary-navigation').isVisible(),false);
    assert.equal(await page.locator('#navigation-toggle').getAttribute('aria-expanded'),'false');
    assert((await page.locator('#editor').boundingBox()).width>editor.width);
    assert.equal(await page.evaluate(()=>JSON.stringify({deck:app.deck,undo:app.undo,design:flow.design})),state);
    await page.screenshot({path:path.join(evidence,`module-collapsed-${width}.png`)});
    await page.locator('#navigation-toggle').click();
    assert.equal(await page.locator('#primary-navigation').isVisible(),true);
  }
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.waitForFunction(()=>innerWidth===1280&&innerHeight===900);
  pass('900/1100/1600 px editor layouts retain all zones and card library; left navigation collapses to release width without changing edits');
};
