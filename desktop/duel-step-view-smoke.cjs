'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');

module.exports=async function({page,application,evidence,pass,automatic=false}) {
  const prefix=automatic?'auto-duel':'duel';
  const original=await page.evaluateHandle(automatic=>{
    const {plan,routes,graph}=automatic?autoDuelState():duelState();return {plan,routes,graph};
  },automatic);
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
  const measure=async()=>{
    await page.waitForFunction(prefix=>{
      const viewport=document.querySelector('#'+prefix+'-graph-scroll'),canvas=viewport.querySelector('.'+prefix+'-graph');
      return viewport.dataset.fitSize===duelStepSize(viewport,canvas);
    },prefix);
    return page.evaluate(prefix=>{
    const viewport=document.querySelector('#'+prefix+'-graph-scroll'),node=viewport.querySelector('.'+prefix+'-node');
    const art=node.querySelector('.review-art img'),box=viewport.getBoundingClientRect(),nav=document.querySelector('#'+prefix+'-step-nav');
    const fits=element=>{const r=element.getBoundingClientRect();return !r.width||!r.height||r.left>=box.left-1&&r.right<=box.right+1&&r.top>=box.top-1&&r.bottom<=box.bottom+1;};
    return {count:viewport.querySelectorAll('.'+prefix+'-node').length,key:node.dataset.currentNode,
      scale:(prefix==='duel'?duelUI:autoDuelView).graphScale,art:art?.getBoundingClientRect().width,
      horizontal:viewport.scrollWidth-viewport.clientWidth,scrolls:viewport.scrollHeight>viewport.clientHeight,
      clipped:[...node.querySelectorAll('.review-card,.review-art img,.review-card>small,.log-action,.effect-description,h3,p,details,.chain-stage,.chain-arrow,.log-role')].filter(el=>el.checkVisibility()&&!fits(el)).map(el=>el.className||el.tagName),
      navFits:nav.scrollWidth<=nav.clientWidth&&[...nav.children].every(el=>{const r=el.getBoundingClientRect(),n=nav.getBoundingClientRect();return r.left>=n.left&&r.right<=n.right+1&&r.bottom<=n.bottom+1;}),
      hasLaterNote:node.textContent.includes('后续说明'),viewportHeight:viewport.clientHeight,bottom:box.bottom,
      footer:document.querySelector('#duel-footer').getBoundingClientRect().top};
    },prefix);
  };
  const ready=()=>page.waitForFunction(prefix=>[...document.querySelectorAll('#'+prefix+'-graph-scroll .review-art img')].every(img=>img.loading==='eager'&&img.complete&&img.naturalWidth>0),prefix,{polling:50,timeout:10000});
  const assertFits=bounds=>{
    assert.equal(bounds.count,1);assert(bounds.scale>0&&bounds.scale<=1);assert(bounds.horizontal<=1);
    assert(!bounds.scrolls,'The complete current Step fits without scrolling');assert.deepEqual(bounds.clipped,[]);
    assert(bounds.navFits,'All step buttons fit without horizontal scrolling');
  };
  try {
    await ready();
    let bounds=await measure();assertFits(bounds);assert.equal(bounds.key,saved.first);assert(!bounds.hasLaterNote);
    const firstScale=bounds.scale;
    await page.locator(`[data-${prefix}-node="${saved.second}"]`).click();
    await ready();
    bounds=await measure();assertFits(bounds);assert.equal(bounds.key,saved.second);assert(bounds.scale<firstScale);
    await page.locator(`[data-${prefix}-node="${saved.first}"]`).click();await ready();
    assert(Math.abs((await measure()).scale-firstScale)<.001,'Returning to a short Step restores its own scale');
    const rotations=await page.evaluate(prefix=>{
      const card=document.querySelector('#'+prefix+'-graph-scroll .review-card'),image=card.querySelector('img'),frame=card.querySelector('.review-art');
      const saved=card.classList.contains('is-defense');card.classList.remove('is-defense');const upright=image.getBoundingClientRect();
      card.classList.add('is-defense');const sideways=image.getBoundingClientRect(),box=frame.getBoundingClientRect();
      card.classList.toggle('is-defense',saved);
      return {upright:[upright.width,upright.height],sideways:[sideways.width,sideways.height],fits:sideways.left>=box.left-1&&sideways.right<=box.right+1};
    },prefix);
    assert(Math.abs(rotations.upright[0]-rotations.sideways[1])<.01);assert(Math.abs(rotations.upright[1]-rotations.sideways[0])<.01);assert(rotations.fits,'Sideways artwork stays fully inside its frame');
    const report=require('../tests/fixtures/opponent-hand-reveal.cjs')();
    // Reproduce a long route with a two-action Step and five revealed cards.
    const short=report.review.nodes.find(n=>n.id==='short');
    report.review.nodes.splice(3,0,...Array.from({length:13},(_,i)=>({...short,id:'extra-'+i,number:i+7})));
    await page.evaluate(({automatic,report})=>{
      const state=automatic?autoDuelState():duelState();state.plan=report;state.routes=duelPlanRoutes(report);state.graph=DuelModel.graph(state.routes);
      state.position={key:'main/long',choice:0};renderDuel();window.scrollTo(0,0);
    },{automatic,report});
    for(const [width,height] of [[1440,970],[960,900],[900,650],[1440,650],[1440,970]]){
      await application.evaluate(({BrowserWindow},{width,height})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(width,height),{width,height});
      await page.waitForFunction(({width,height})=>innerWidth===width&&innerHeight===height,{width,height});await ready();
      bounds=await measure();assertFits(bounds);assert(bounds.bottom<bounds.footer,'Automatic height leaves the footer clear');
      assert.equal(await page.locator('#'+prefix+'-graph-scroll .random-card').count(),5);
      await page.screenshot({path:path.join(evidence,`${prefix}-fit-${width}x${height}.png`)});
    }
    // Expanding record details and toggling the side rail both change layout
    // without a window resize; the observer must refit the same Step.
    await page.locator('#'+prefix+'-graph-scroll details summary').first().click();
    assertFits(await measure());
    await page.locator('#navigation-toggle').click();assertFits(await measure());
    await page.locator('#navigation-toggle').click();assertFits(await measure());
    await page.evaluate(prefix=>{const resize=prefix==='duel'?resizeDuelGraph:resizeAutoDuelGraph;resize(240);},prefix);
    assertFits(await measure());assert.equal((await measure()).viewportHeight,238);
    await page.locator('#'+prefix+'-graph-resize').dblclick();assertFits(await measure());
    pass(prefix+' complete Step fits at 1440/960/900px widths and 970/900/650px heights; all navigation, five revealed cards, expanded records, side rail and manual splitter verified');
  } finally {
    await page.evaluate(({automatic,saved,original})=>{
      const state=automatic?autoDuelState():duelState(),view=automatic?autoDuelView:duelUI;
      Object.assign(state,original);state.position=saved.position;view.graphHeight=saved.height;renderDuel();
    },{automatic,saved,original});
    await original.dispose();
    await application.evaluate(({BrowserWindow},saved)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(saved.width,saved.heightWindow),saved);
  }
};
