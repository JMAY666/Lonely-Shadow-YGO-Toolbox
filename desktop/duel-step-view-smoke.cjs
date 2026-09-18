'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');

module.exports=async function({page,application,evidence,pass,automatic=false}) {
  const prefix=automatic?'auto-duel':'duel';
  const original=await page.evaluateHandle(automatic=>(automatic?autoDuelState():duelState()).plan,automatic);
  const saved=await page.evaluate(automatic=>{
    const state=automatic?autoDuelState():duelState(),view=automatic?autoDuelView:duelUI;
    const [first,second]=state.graph.nodes.filter(n=>n.route==='main'&&!['initial','final'].includes(n.id));
    const saved={position:{...state.position},height:view.graphHeight,width:innerWidth,heightWindow:innerHeight,first:first.key,second:second.key};
    view.graphHeight=null;
    state.position={key:first.key,choice:0};
    state.plan=structuredClone(state.plan);
    // A later operation must never participate in the current step's sizing.
    state.plan.annotations.nodes[second.id]={name:'很长的后续步骤',notes:'后续说明不会缩小前一步。\n'.repeat(100)};
    renderDuel();return saved;
  },automatic);
  const measure=()=>page.evaluate(prefix=>{
    const viewport=document.querySelector('#'+prefix+'-graph-scroll'),node=viewport.querySelector('.'+prefix+'-node'),graph=viewport.querySelector('.'+prefix+'-graph');
    const art=node.querySelector('.review-art img'),name=node.querySelector('.review-card>small');
    return {count:viewport.querySelectorAll('.'+prefix+'-node').length,key:node.dataset.currentNode,
      transform:getComputedStyle(graph).transform,art:art?.getBoundingClientRect().width,font:name&&parseFloat(getComputedStyle(name).fontSize),
      horizontal:viewport.scrollWidth-viewport.clientWidth,scrolls:viewport.scrollHeight>viewport.clientHeight,
      text:node.textContent,viewportHeight:viewport.clientHeight};
  },prefix);
  const ready=()=>page.waitForFunction(prefix=>[...document.querySelectorAll('#'+prefix+'-graph-scroll .review-art img')].every(img=>img.loading==='eager'&&img.complete&&img.naturalWidth>0),prefix,{polling:50,timeout:10000});
  try {
    await ready();
    let bounds=await measure();assert.equal(bounds.count,1);assert.equal(bounds.key,saved.first);assert.equal(bounds.transform,'none');
    assert(bounds.art>=116&&bounds.font>=14,JSON.stringify(bounds));assert(!bounds.text.includes('后续说明'));assert(bounds.horizontal<=1);
    await page.locator(`[data-${prefix}-node="${saved.second}"]`).click();
    await ready();
    bounds=await measure();assert.equal(bounds.key,saved.second);assert(bounds.scrolls,'A long step scrolls instead of shrinking');
    assert.equal(bounds.transform,'none');assert(bounds.art>=116&&bounds.font>=14);
    const rotations=await page.evaluate(prefix=>{
      const card=document.querySelector('#'+prefix+'-graph-scroll .review-card'),image=card.querySelector('img'),frame=card.querySelector('.review-art');
      const saved=card.classList.contains('is-defense');card.classList.remove('is-defense');const upright=image.getBoundingClientRect();
      card.classList.add('is-defense');const sideways=image.getBoundingClientRect(),box=frame.getBoundingClientRect();
      card.classList.toggle('is-defense',saved);
      return {upright:[upright.width,upright.height],sideways:[sideways.width,sideways.height],fits:sideways.left>=box.left-1&&sideways.right<=box.right+1};
    },prefix);
    assert.deepEqual(rotations.upright,[120,175]);assert.deepEqual(rotations.sideways,[175,120]);assert(rotations.fits,'Full-size sideways artwork stays in its frame');
    await page.locator(`[data-${prefix}-node="${saved.first}"]`).click();
    await ready();
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(960,900));
    await page.waitForFunction(()=>innerWidth===960);
    await ready();
    bounds=await measure();assert(bounds.horizontal<=1);assert(bounds.art>=116&&bounds.font>=14);
    await page.screenshot({path:path.join(evidence,prefix+'-single-step-narrow.png')});
    await application.evaluate(({BrowserWindow},saved)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(saved.width,saved.heightWindow),saved);
    await page.waitForFunction(width=>innerWidth===width,saved.width);
    await page.screenshot({path:path.join(evidence,prefix+'-single-step.png')});
    pass(prefix+' single Step: later tall content cannot shrink current artwork/text; long current Step scrolls; 960px layout stays readable');
  } finally {
    await page.evaluate(({automatic,saved,original})=>{
      const state=automatic?autoDuelState():duelState(),view=automatic?autoDuelView:duelUI;
      state.plan=original;state.position=saved.position;view.graphHeight=saved.height;renderDuel();
    },{automatic,saved,original});
    await original.dispose();
    await application.evaluate(({BrowserWindow},saved)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(saved.width,saved.heightWindow),saved);
  }
};
