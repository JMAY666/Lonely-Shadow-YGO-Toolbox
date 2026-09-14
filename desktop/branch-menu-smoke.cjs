'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');

module.exports=async function({page,application,main,point,pass,evidence}) {
  const target=()=>page.locator(`#review-steps [data-review-node="${point.node_id}"]`);
  const popup=page.locator('#branch-context-menu');
  const open=async()=>{
    await target().click({button:'right',position:{x:15,y:15}});
    await popup.waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>reviewUI.node),point.node_id);
    assert.equal(await page.evaluate(()=>branchMenu.context.nodeId),point.node_id);
  };
  const inViewport=async()=>{
    const box=await popup.boundingBox(),view=await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    assert(box.x>=7&&box.y>=7);assert(box.x+box.width<=view.width-7);assert(box.y+box.height<=view.height-7);
  };
  assert.equal(await page.locator('#draft-editor .branch-create').count(),0,'No distant creation block below the timeline');
  await page.evaluate(()=>selectReviewNode('initial'));
  await open();await inViewport();
  assert((await page.locator('#branch-context-operation').innerText()).includes('贪欲之壶'));
  assert.equal(await page.locator('#create-compromise').isEnabled(),true);
  assert.equal((await page.evaluate(id=>api('/api/report/'+id),main.id)).branches.length,0,'Opening the context popup is not a mutation');
  await page.waitForFunction(()=>document.querySelector('#notice').hidden,null,{timeout:10000});
  await page.screenshot({path:path.join(evidence,'branch-context-menu.png'),preserveScroll:true});
  // Keyboard and pointer events are scoped to this hidden Chromium renderer.
  await page.keyboard.press('Escape');await popup.waitFor({state:'hidden'});
  assert.equal(await target().evaluate(el=>el===document.activeElement),true);
  await target().press('Shift+F10');await popup.waitFor({state:'visible'});
  assert.equal(await page.locator('#branch-point').evaluate(el=>el===document.activeElement),true);
  await page.mouse.click(2,2);await popup.waitFor({state:'hidden'});
  await page.locator('#review-steps [data-review-node="final"]').click({button:'right'});
  assert.equal(await page.locator('#create-compromise').isDisabled(),true);
  assert((await page.locator('#branch-context-status').innerText()).includes('没有可准确恢复'));
  await page.locator('#branch-context-cancel').click();

  // A long sidebar verifies the menu stays beside the clicked row, independently
  // of list height. These view-only nodes never enter a report or an API request.
  await page.evaluate(nodeId=>{
    globalThis.menuOriginalNodes=reviewUI.nodes;
    const extra=Array.from({length:24},(_,i)=>({id:'layout-only-'+i,number:i+30,kind:'step',state:null,action_ids:[]}));
    reviewUI.nodes=[...reviewUI.nodes.filter(n=>n.id!==nodeId),...extra,reviewUI.nodes.find(n=>n.id===nodeId)];renderReviewSidebar();
  },point.node_id);
  try {
    await open();await inViewport();
    const contextBox=await popup.boundingBox(),nodeBox=await target().boundingBox();
    assert(contextBox.y<=nodeBox.y+nodeBox.height+20,'Menu must not appear below the entire timeline');
    await page.screenshot({path:path.join(evidence,'branch-context-long-timeline.png'),preserveScroll:true});
    await page.locator('#branch-context-cancel').click();
  } finally {
    await page.evaluate(()=>{closeBranchMenu(false);reviewUI.nodes=globalThis.menuOriginalNodes;delete globalThis.menuOriginalNodes;renderReviewSidebar();});
  }
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(980,660));
  await page.waitForFunction(()=>innerWidth===980&&innerHeight===660);
  await open();await inViewport();
  await page.keyboard.press('Escape');
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.waitForFunction(()=>innerWidth===1280&&innerHeight===900);
  await open();await page.evaluate(()=>switchView('plans'));
  assert.equal(await popup.isVisible(),false,'Navigation discards the old menu context');
  await page.evaluate(id=>showReport(id),main.id);
  assert.deepEqual((await page.evaluate(id=>api('/api/report/'+id),main.id)).actions,main.actions);
  pass('Timeline context popup: exact right-clicked node, long-list proximity, viewport bounds, keyboard access, focus restoration, dismissal and disabled reasons; opening/canceling never creates a branch');
};
