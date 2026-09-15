'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

// Real engine procedure summons, Xyz detachment and a generic hand cost. All
// clicks are engine-local hit-test coordinates in an isolated acceptance run.
module.exports=async function({page,nativeState,nativeWait,hostWait,waitHistory,pass,evidence}) {
  const request=(url,body)=>page.evaluate(([u,b])=>api(u,b),[url,body]);
  const photon=65367484,warrior=1184620,utopia=84013237,gravity=23656668,twisters=43898403,pot=55144522;
  const hand=[photon,warrior,twisters,pot,warrior];
  const deck={main:[...hand,...Array(35).fill(warrior)],extra:[utopia,gravity],side:[]};
  const source=await request('/api/decks',{name:`素材关系验收-${Date.now()}`,deck});
  await page.evaluate(async()=>{flow.draft=null;switchView('training');await syncNativeHost();});
  const started=await request('/api/start',{deck_id:source.id,design:{name:'超量、取除、连接与费用验收',notes:'隔离真实引擎记录',deck,
    deck_name:source.name,conditions:{hand_count:5,slots:hand,banned:[]},opponent_ai:false}});
  const sid=started.id;await page.evaluate(()=>refreshHistory());
  await hostWait(sid,s=>s.frame_ready&&s.timeline_accessible);await nativeWait(sid,s=>s.prompt===11);
  const report=()=>request(`/api/report/${sid}`);
  const click=async target=>{assert(target,'Expected an engine-local target');return nativeState(sid,'click',target);};
  async function command(code,location,caption) {
    const state=await nativeWait(sid,s=>[10,11].includes(s.prompt)&&s.targets.some(t=>t.location===location&&(location===64||t.code===code)));
    await click(state.targets.find(t=>t.location===location&&(location===64||t.code===code)));
    const menu=await nativeWait(sid,s=>s.buttons.some(b=>b.text===caption));
    await click(menu.buttons.find(b=>b.text===caption));
  }
  async function settle({code,extra=false,placeSequence=0,chooseCode=null}={}) {
    const selected=new Set();
    for(let i=0;i<65;i++) {
      const s=await nativeState(sid),r=await report();
      if(s.prompt===11 && (!code||r.final_state.cards.some(c=>c.code===code&&c.location===4)))return r;
      if(s.choices.length) {
        const choice=s.choices.find(c=>c.code===(chooseCode||code))||s.choices[0];await click(choice);
      } else if(s.prompt===18) {
        const zone=s.targets.find(t=>t.location===4&&t.code===0&&(extra?t.sequence>=5:t.sequence===placeSequence));
        await click(zone||s.targets.find(t=>t.location===4&&t.code===0));
      } else if(s.prompt===19) {
        const position=s.buttons.find(b=>!b.text&&b.x>350);
        if(position)await click(position);else await new Promise(resolve=>setTimeout(resolve,130));
      } else {
        const yes=s.buttons.find(b=>b.text==='是'),ok=s.buttons.find(b=>b.text==='确定');
        if(yes)await click(yes);
        else if(ok)await click(ok);
        else if([15,20,23,26].includes(s.prompt)) {
          const target=s.targets.find(t=>t.location===4&&t.code&&(!selected.has(t.sequence)));
          if(target){selected.add(target.sequence);await click(target);}
          else await new Promise(resolve=>setTimeout(resolve,120));
        } else await new Promise(resolve=>setTimeout(resolve,120));
      }
    }
    throw Error('Material acceptance did not settle');
  }
  await command(photon,2,'特殊召唤');await settle({code:photon,placeSequence:1});
  await command(warrior,2,'召唤');await settle({code:warrior,placeSequence:0});
  await command(utopia,64,'特殊召唤');
  const xyz=await settle({code:utopia,extra:true});
  const host=xyz.final_state.cards.find(c=>c.code===utopia&&c.location===4);
  assert.equal(xyz.final_state.cards.filter(c=>c.overlay_target===host.instance_id).length,2);
  assert.equal(xyz.final_state.cards.filter(c=>c.location===4&&c.controller===0).length,1);
  // Move to the next player turn so battle is legal; the empty opponent skips.
  let s=await nativeWait(sid,s=>s.prompt===11&&s.buttons.some(b=>b.text==='ＥＰ'));
  await click(s.buttons.find(b=>b.text==='ＥＰ'));
  s=await nativeWait(sid,s=>s.prompt===11&&s.buttons.some(b=>b.text==='ＢＰ'));
  await click(s.buttons.find(b=>b.text==='ＢＰ'));
  await nativeWait(sid,s=>s.prompt===10);await command(utopia,4,'攻击');
  for(let i=0;i<60;i++) {
    s=await nativeState(sid);const r=await report();
    if(s.prompt===10&&r.final_state.cards.filter(c=>c.overlay_target===host.instance_id).length===1)break;
    const yes=s.buttons.find(b=>b.text==='是'),ok=s.buttons.find(b=>b.text==='确定');
    if(yes)await click(yes);
    else if(s.choices.length)await click(s.choices[0]);
    else if(ok)await click(ok);
    else if(s.activatable.includes(utopia)) {
      await click(s.targets.find(t=>t.code===utopia&&t.location===4));
      const menu=await nativeWait(sid,s=>s.buttons.some(b=>b.text==='发动'));await click(menu.buttons.find(b=>b.text==='发动'));
    } else await new Promise(resolve=>setTimeout(resolve,130));
  }
  const detached=await report();
  assert.equal(detached.final_state.cards.filter(c=>c.overlay_target===host.instance_id).length,1);
  assert(detached.final_state.cards.some(c=>c.location===16&&[photon,warrior].includes(c.code)));
  s=await nativeWait(sid,s=>s.buttons.some(b=>b.text==='ＥＰ'));await click(s.buttons.find(b=>b.text==='ＥＰ'));
  await nativeWait(sid,s=>s.prompt===11);
  await command(gravity,64,'特殊召唤');const linked=await settle({code:gravity,extra:true});
  const link=linked.final_state.cards.find(c=>c.code===gravity&&c.location===4);
  assert.equal(link.position,1);assert.equal(linked.final_state.cards.filter(c=>c.location===128).length,0);
  assert(linked.final_state.cards.some(c=>c.instance_id===host.instance_id&&c.location===16));
  await command(pot,2,'盖放');
  s=await nativeWait(sid,s=>s.prompt===18);await click(s.targets.find(t=>t.location===8&&t.sequence===0));
  await nativeWait(sid,s=>s.prompt===11);
  await command(twisters,2,'发动');
  for(let i=0;i<65;i++) {
    s=await nativeState(sid);const r=await report();
    if(s.prompt===11&&r.events.some(e=>e.cost&&e.origin?.location===2))break;
    if(s.prompt===18)await click(s.targets.find(t=>t.location===8&&t.code===0&&t.sequence===1));
    else if(s.choices.length)await click(s.choices.find(c=>c.code===warrior)||s.choices.find(c=>c.code===pot)||s.choices[0]);
    else {
      const ok=s.buttons.find(b=>b.text==='确定');
      if(ok)await click(ok);
      else if(s.prompt===15) {
        const paid=r.events.some(e=>e.cost&&e.origin?.location===2);
        await click(s.targets.find(t=>paid?t.location===8&&t.code===pot:t.location===2&&t.code===warrior));
      }
      else await new Promise(resolve=>setTimeout(resolve,120));
    }
  }
  const final=await report();assert(final.events.some(e=>e.cost&&e.origin?.location===2));
  await page.locator('#finish-training').click();await waitHistory('completed');
  await page.waitForFunction(()=>!!flow.draft&&app.view==='history');
  const review=await report();
  const xyzNode=review.review.nodes.find(n=>n.state?.cards.filter(c=>c.overlay_target===host.instance_id).length===2);
  const detachNode=review.review.nodes.find(n=>n.state?.cards.filter(c=>c.overlay_target===host.instance_id).length===1);
  assert(xyzNode&&detachNode,'Both historical material counts must survive in the review');
  await page.evaluate(id=>selectReviewNode(id),xyzNode.id);
  await page.locator('.shared-zones .review-card').click();
  await page.locator('#review-material-tab').click();assert.equal(await page.locator('.material-list .review-card').count(),2);
  await page.locator('.material-list .review-card').first().click();
  assert.match(await page.locator('.card-provenance').innerText(),/成为素材/);
  await page.locator('#review-detail-close').click();
  await page.evaluate(id=>selectReviewNode(id),detachNode.id);
  await page.locator('.shared-zones .review-card').click();
  await page.locator('#review-material-tab').click();assert.equal(await page.locator('.material-list .review-card').count(),1);
  await page.locator('#review-detail-close').click();
  for(const zone of [16,32,64]) {
    await page.locator(`[data-review-zone="0:${zone}"]`).click();
    assert.equal(await page.locator('.zone-contents .review-card').count(),detachNode.state.cards.filter(c=>c.controller===0&&c.location===zone).length);
    await page.locator('#review-zone-close').click();
  }
  await page.locator('#review-log-toggle').click();
  await page.locator('[data-log-mode="compact"]').click();
  assert.equal(await page.locator('#review-log .log-materials').count(),0);
  const cleanup=review.events.filter(e=>e.message===50&&(e.origin?.location&128)&&e.reason===0x20000400)||[];
  assert(cleanup.length>0,'Real engine must record attached material rule cleanup');
  for(const e of cleanup)assert.equal(await page.locator(`#review-log [data-review-action="${e.id}"]`).count(),0);

  assert(await page.locator('#review-log .compact-summon').count()>0);
  await page.locator('[data-log-mode="detailed"]').click();
  assert.match(await page.locator('#review-log').innerText(),/费用 Cost/);
  assert.match(await page.locator('#review-log').innerText(),/连接召唤/);
  assert.match(await page.locator('#review-log').innerText(),/素材去向/);
  const effectHint=page.locator('#review-log .effect-hint > button').first();
  await effectHint.hover();assert(await page.locator('#review-log [role="tooltip"]').first().isVisible());
  await effectHint.focus();assert(await page.locator('#review-log [role="tooltip"]').first().isVisible());
  await page.screenshot({path:path.join(evidence,'review-xyz-materials.png')});
  await page.locator('#review-log-close').click();
  await page.evaluate(()=>selectReviewNode('final'));
  await page.locator('[data-review-zone="0:16"]').click();
  await page.locator('.zone-contents .review-card').first().click();
  await page.locator('#review-final-mark').check();
  const effectBox=page.locator('[data-final-effect]').last();
  await effectBox.check();
  await page.locator('[data-final-effect-note]').fill('墓地有效效果验收');
  assert(await page.locator('.effect-mark.is-marked').count()>0);
  await page.screenshot({path:path.join(evidence,'review-final-effect-mark.png'),preserveScroll:true});
  await page.locator('#review-detail-close').click();
  await page.locator('#review-zone-close').click();
  await page.locator('#review-log-toggle').click();
  await page.locator('[data-log-mode="compact"]').click();
  assert.equal(await page.locator('[data-log-node="final"] .marked-effect-original').count(),0);
  assert.equal(await page.locator('[data-log-node="final"] .location-icon').count(),0);
  assert.match(await page.locator('[data-log-node="final"] .marked-location').innerText(),/墓地/);
  const noteColor=await page.locator('[data-log-node="final"] .marked-note').evaluate(el=>{
    const rgb=value=>value.match(/[\d.]+/g).map(Number);
    const foreground=rgb(getComputedStyle(el).color);
    let parent=el,background;
    do{background=rgb(getComputedStyle(parent).backgroundColor);parent=parent.parentElement;}
    while(parent&&background.length>3&&background[3]===0);
    const light=channels=>channels.slice(0,3).map(c=>c/255).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4)
      .reduce((sum,c,i)=>sum+c*[.2126,.7152,.0722][i],0);
    return {red:foreground[0]>foreground[1]+35&&foreground[0]>foreground[2]+35,
      contrast:(light(foreground)+.05)/(light(background)+.05)};
  });
  assert(noteColor.red&&noteColor.contrast>=4.5,JSON.stringify(noteColor));
  await page.locator('[data-log-mode="detailed"]').click();
  assert(await page.locator('[data-log-node="final"] .marked-effect-original').count()>0);
  await page.locator('[data-log-mode="compact"]').click();
  await page.locator('[data-log-node="final"] .marked-final-cards .review-card').click();
  await page.locator('[data-final-effect-note]').fill('墓地有效效果验收');
  await page.waitForTimeout(100);
  assert(await page.locator('#review-card-popover').isVisible(),'Editing a marked log card keeps its popover open');
  await page.locator('#review-detail-close').click();
  await page.locator('#review-log-close').click();
  await page.locator('#save-plan').click();await page.waitForFunction(()=>app.view==='confirmation'&&!flow.busy);
  assert.match(await page.locator('#save-confirmation').innerText(),/任意手牌 ×1/);
  assert.match(await page.locator('#save-confirmation .marked-final-cards').innerText(),/墓地有效效果验收/);
  assert.equal(await page.locator('#save-confirmation .marked-final-cards .review-card').count(),1);
  await page.route('**/api/plans/save',async route=>{
    const response=await route.fetch();assert(response.ok());
    await route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({error:'隔离测试：保存回执丢失'})});
  },{times:1});
  await page.locator('#confirm-save-plan').click();
  await page.waitForFunction(()=>!flow.busy&&document.querySelector('#confirmation-message').textContent.includes('回执丢失'));
  assert.equal((await request('/api/plans')).filter(p=>p.id===sid).length,1);
  await page.locator('#back-to-review').click();await page.locator('#draft-name').fill('  素材验收：回执丢失后修改  ');
  await page.locator('#save-plan').click();await page.waitForFunction(()=>app.view==='confirmation'&&!flow.busy);
  assert.match(await page.locator('#confirm-save-plan').innerText(),/保存修改/);
  await page.evaluate(()=>Promise.all([confirmReviewSave(),confirmReviewSave()]));
  await page.waitForFunction(()=>app.view==='plans'&&!flow.busy);
  const saved=await request(`/api/plan/${sid}`);
  assert.equal(saved.name,'素材验收：回执丢失后修改');assert.equal(saved.edit_revision,2);
  assert.equal((await request('/api/plans')).filter(p=>p.id===sid).length,1);
  const marked=Object.entries(saved.annotations.final_marks).filter(([,m])=>m.marked);
  assert.equal(marked.length,1);assert.equal(saved.requirements.final.cards[0].location,16);
  assert(Object.values(marked[0][1].effects).some(e=>e.note==='墓地有效效果验收'));
  assert.match(await page.locator('#plan-report .marked-final-cards').innerText(),/墓地有效效果验收/);
  await page.locator('#plan-report .marked-final-cards').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(evidence,'review-marked-summary.png'),preserveScroll:true});
  fs.writeFileSync(path.join(evidence,'review-materials.json'),JSON.stringify({sid,xyz,detached,linked,saved},null,2));
  pass('Real Xyz summon, two distinct materials, detachment to grave, Link material destinations, image costs and generic hand requirement');
  pass('Committed save with a lost acknowledgement, return/edit/reconfirm and duplicate UI submission keep exactly one updated plan');
};
