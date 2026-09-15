'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

module.exports=async function({page,nativeState,nativeWait,hostWait,waitHistory,pass,evidence}) {
  const request=(url,body)=>page.evaluate(([u,b])=>api(u,b),[url,body]);
  const desires=35261759,rota=32807846,foolish=81439173,instant=1845204,warrior=1184620;
  const hand=[desires,desires,rota,foolish,instant,warrior];
  const deck={main:[...hand,...Array(30).fill(warrior),...Array(4).fill(91152256)],extra:[63519819],side:[]};
  const source=await request('/api/decks',{name:`回退卡效验收-${Date.now()}`,deck});
  await page.evaluate(async()=>{switchView('training');await syncNativeHost();});
  const started=await request('/api/start',{deck_id:source.id,design:{name:'回退卡效完整验收',notes:'仅隔离测试数据',deck,
    deck_name:source.name,conditions:{hand_count:6,slots:hand,banned:[]},opponent_ai:false}});
  const sid=started.id;
  await page.evaluate(()=>refreshHistory());
  await hostWait(sid,s=>s.frame_ready&&s.timeline_accessible);
  await nativeWait(sid,s=>s.prompt===11);
  const expanded=await page.locator('#native-stage').boundingBox();
  await page.locator('#navigation-toggle').click();
  await hostWait(sid,s=>s.visible&&s.bounds.width>expanded.width&&s.owns_stage_hit_test&&s.composition_compatible);
  const handle=await page.locator('#navigation-toggle').boundingBox(),stage=await page.locator('#native-stage').boundingBox();
  const height=await page.evaluate(()=>innerHeight);
  assert(Math.abs(handle.y+handle.height/2-height/2)<1,'Navigation handle stays vertically centered');
  assert(handle.x>=0&&handle.x+handle.width<=stage.x,'Collapsed handle stays outside the native field');
  await page.screenshot({path:path.join(evidence,'centered-navigation-native.png')});
  await page.locator('#navigation-toggle').click();
  await hostWait(sid,s=>s.visible&&Math.abs(s.bounds.width-expanded.width)<3&&s.owns_stage_hit_test&&s.composition_compatible);
  pass('Centered edge arrow expands/collapses outside the live native field and restores its original bounds');
  const report=()=>request(`/api/report/${sid}`);
  async function settled() {
    for(let i=0;i<60;i++) {
      const data=await request(`/api/timeline/${sid}`);
      if(data.at_node&&data.nodes.some(n=>n.id===data.cursor))return data;
      await new Promise(r=>setTimeout(r,100));
    }
    throw new Error('Effects timeline did not settle');
  }
  async function restore(node) {
    await page.evaluate(()=>refreshTimeline());
    await page.locator(`[data-rewind="${node}"]`).click();
    await page.waitForFunction(()=>!rewindState.busy,null,{timeout:30000});
    const data=await request(`/api/timeline/${sid}`);
    assert.equal(data.operation.status,'done',JSON.stringify(data.operation));assert.equal(data.cursor,node);
    await nativeWait(sid,s=>s.prompt===11);
  }
  async function begin(code,place=true) {
    let state=await nativeWait(sid,s=>s.prompt===11&&s.activatable.includes(code));
    await nativeState(sid,'click',state.targets.find(t=>t.location===2&&t.code===code));
    state=await nativeWait(sid,s=>s.buttons.some(b=>b.text==='发动'));
    await nativeState(sid,'click',state.buttons.find(b=>b.text==='发动'));
    state=await nativeWait(sid,s=>s.prompt===18);
    if(place)await nativeState(sid,'click',state.targets.find(t=>t.location===8&&t.code===0));
  }
  async function finishEffect() {
    for(let i=0;i<55;i++) {
      let s=await nativeState(sid);
      const data=await request(`/api/timeline/${sid}`);
      if(s.prompt===11&&data.at_node)return;
      if(s.choices.length)await nativeState(sid,'click',s.choices[0]);
      else if(s.prompt===18)await nativeState(sid,'click',s.targets.find(t=>t.location===4&&t.code===0));
      else if(s.prompt===19) {
        const button=s.buttons.find(b=>!b.text&&b.x>350);
        if(button)await nativeState(sid,'click',button);
        else await new Promise(r=>setTimeout(r,150));
      } else {
        const ok=s.buttons.find(b=>b.text==='确定');
        if(ok)await nativeState(sid,'click',ok);
        else await new Promise(r=>setTimeout(r,130));
      }
    }
    throw new Error('Effect did not finish');
  }
  const initial=(await settled()).cursor, startState=(await report()).final_state;
  await begin(desires,false); // Undo the latest node while a place selection is open.
  await page.waitForFunction(()=>rewindState.data?.at_node===false);
  await restore(initial);
  assert.deepEqual((await report()).final_state,startState);
  await begin(desires);await finishEffect();
  const afterDesires=await report(), nodeA=(await settled()).cursor;
  assert.equal(afterDesires.final_state.cards.filter(c=>c.location===32).length,10);
  assert.equal(afterDesires.statistics['效果抽卡'],2);
  assert(!(await nativeState(sid)).activatable.includes(desires),'The second copy must be prohibited by the real once-per-turn limit');
  await begin(rota);await nativeWait(sid,s=>s.prompt===15&&s.choices.length);
  const duringSearch=await request(`/api/timeline/${sid}`);
  assert(duringSearch.pending.length>0,'An unfinished chain is displayed without an independent restore target');
  await restore(nodeA); // Restore from the middle of a resolving chain.
  assert.deepEqual((await report()).final_state,afterDesires.final_state);
  await begin(rota);await finishEffect();
  const afterSearch=await report(), nodeB=(await settled()).cursor;
  assert(afterSearch.events.some(e=>e.message===50&&e.origin?.location===1&&e.destination?.location===2));
  assert(afterSearch.events.some(e=>e.message===32),'Search must include a real shuffle');
  await begin(foolish);await finishEffect();
  const afterGrave=await report();
  assert(afterGrave.events.some(e=>e.message===50&&e.origin?.location===1&&e.destination?.location===16));
  await begin(instant);await finishEffect();
  const afterFusion=await report();
  assert.equal(afterFusion.final_state.lp[0],7000);
  assert(afterFusion.final_state.cards.some(c=>c.code===63519819&&c.location===4));
  await restore(nodeB);
  assert.deepEqual((await report()).final_state,afterSearch.final_state);
  assert(!(await nativeState(sid)).activatable.includes(desires),'Used effect stays used after a later rollback');
  await begin(instant);await finishEffect();
  const alternative=await report();
  assert.equal(alternative.final_state.lp[0],7000);
  assert(!alternative.actions.some(a=>a.cards.some(c=>c.code===foolish)),'Abandoned Foolish Burial must not appear in the alternative route');
  await restore(nodeA);assert.deepEqual((await report()).final_state,afterDesires.final_state);
  await restore(initial);assert.deepEqual((await report()).final_state,startState);
  assert((await nativeState(sid)).activatable.includes(desires),'Going before activation restores the real count limit');
  await begin(desires);await finishEffect();
  const repeated=await report();
  assert.deepEqual(repeated.final_state,afterDesires.final_state,'Exact same banished copies, draw cards, deck order and engine card identities');
  await page.screenshot({path:path.join(evidence,'timeline-effects.png')});
  await page.locator('#finish-training').click();await waitHistory('completed');
  await page.waitForFunction(()=>!!flow.draft);
  await page.locator('#save-plan').click();await page.locator('#confirm-save-plan').click();await page.waitForFunction(id=>flow.selectedPlan===id&&!flow.busy,sid);
  const saved=await request(`/api/plan/${sid}`);
  assert.equal(saved.actions.length,1);assert.deepEqual(saved.final_state,repeated.final_state);
  assert.equal(saved.statistics['效果抽卡'],2);
  fs.writeFileSync(path.join(evidence,'timeline-effects.json'),JSON.stringify({sid,startState,afterDesires,afterSearch,afterGrave,afterFusion,alternative,saved},null,2));
  pass('Real rewind: mid-selection/chain, search and shuffle, send-to-grave, facedown banish, draw determinism, LP cost/fusion, count limits, alternative route and saved-plan consistency');
};
