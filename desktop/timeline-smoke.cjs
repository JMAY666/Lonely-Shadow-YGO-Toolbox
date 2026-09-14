'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

module.exports = async function({page, sid, sessionPath, nativeWait, nativeState, pass, evidence}) {
  const apiCall = (url,body) => page.evaluate(([u,b])=>api(u,b),[url,body]);
  const report = () => apiCall(`/api/report/${sid}`);
  async function timeline() {
    for(let i=0;i<80;i++) {
      const data=await apiCall(`/api/timeline/${sid}`);
      if(data.at_node && data.nodes.some(n=>n.id===data.cursor))return data;
      await new Promise(r=>setTimeout(r,100));
    }
    throw new Error('Timeline did not settle');
  }
  async function restore(node, failure=false) {
    const before=await report(), data=await timeline();
    await page.evaluate(()=>refreshTimeline());
    await page.locator(`[data-rewind="${node}"]`).click();
    await page.waitForFunction(()=>!rewindState.busy && rewindState.operation, null,{timeout:30000});
    const after=await apiCall(`/api/timeline/${sid}`);
    if(failure) {
      assert.equal(after.operation.status,'error');
      assert.deepEqual((await report()).final_state,before.final_state);
    } else {
      assert.equal(after.operation.status,'done',JSON.stringify(after.operation));
      assert.equal(after.cursor,node);
      await nativeWait(sid,s=>s.prompt===11);
    }
    return after;
  }
  async function summon(sequence=0) {
    let state=await nativeWait(sid,s=>s.prompt===11);
    const target=state.targets.find(t=>t.location===2&&t.code===1184620);
    assert(target);
    await nativeState(sid,'click',target);
    state=await nativeWait(sid,s=>s.buttons.some(b=>b.text==='召唤'));
    await nativeState(sid,'click',state.buttons.find(b=>b.text==='召唤'));
    state=await nativeWait(sid,s=>s.prompt===18);
    await nativeState(sid,'click',state.targets.find(t=>t.location===4&&t.sequence===sequence));
    await nativeWait(sid,s=>s.prompt===11);
  }
  let data=await timeline();
  assert.equal(data.nodes.flatMap(n=>n.steps).length,2);
  const [initial,pot,oldSummon]=data.nodes.filter(n=>n.initial||n.steps.length);
  const original=await report();
  fs.writeFileSync(path.join(evidence,'timeline-before.json'),JSON.stringify({data,original},null,2));
  await restore(pot.id);
  const afterPot=await report();
  assert.equal(afterPot.actions.length,1);
  assert.equal(afterPot.statistics['效果抽卡'],2);
  assert.equal(afterPot.final_state.cards.filter(c=>c.controller===0&&c.location===4).length,0);
  data=await restore(initial.id);
  const restoredInitial=(await report()).final_state;
  assert.equal((await report()).actions.length,0);
  assert.equal(restoredInitial.cards.filter(c=>c.controller===0&&c.location===2).length,5);
  data=await restore(pot.id); // Forward through the retained route before branching.
  assert.deepEqual((await report()).final_state,afterPot.final_state);
  fs.writeFileSync(path.join(sessionPath,'test-rewind-fail'),'1');
  try {await restore(initial.id,true);} finally {fs.unlinkSync(path.join(sessionPath,'test-rewind-fail'));}
  await summon(2); // Take a different legal placement from the recovered state.
  data=await timeline();
  assert(!data.nodes.some(n=>n.id===oldSummon.id),'Old suffix must leave the effective route');
  const branched=await report();
  assert.equal(branched.actions.length,2);
  assert(branched.final_state.cards.some(c=>c.controller===0&&c.location===4&&c.sequence===2));
  assert.equal(branched.statistics['通常召唤成功'],1);
  assert.equal(branched.statistics['效果抽卡'],2);
  assert.deepEqual(branched.final_state.cards.filter(c=>c.location===1),original.final_state.cards.filter(c=>c.location===1));
  // Stale requests cannot mutate the route or silently run after a timeout.
  await assert.rejects(apiCall('/api/rewind',{id:sid,node:initial.id,revision:data.revision-1}));
  await assert.rejects(apiCall('/api/rewind',{id:sid,node:oldSummon.id,revision:data.revision}));
  await page.screenshot({path:path.join(evidence,'timeline-restored.png')});
  fs.writeFileSync(path.join(evidence,'timeline-after.json'),JSON.stringify({data,branched,restoredInitial},null,2));
  pass('Timeline: initial/multiple/middle/forward restoration, full state and deck order, atomic failure, new legal branch and stale-request rejection');
};
