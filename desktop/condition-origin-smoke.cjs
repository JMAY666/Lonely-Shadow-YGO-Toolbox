'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async({page,evidence,pass})=>{
  // Synthetic rendering trace; native condition-hand allocation has its own suite.
  const report=await page.evaluate(async()=>{
    const catalog=Object.fromEntries(await Promise.all([59438930,1184620,23995346].map(async c=>[c,await card(c)])));
    const condition={code:59438930,name:catalog[59438930].name,instance_id:1,controller:0,location:2,position:1};
    const exact={code:1184620,name:catalog[1184620].name,instance_id:2,controller:0,location:2,position:1};
    const result={code:23995346,name:'合成召唤结果',instance_id:3,controller:0,location:4,sequence:0,position:1,summon_method:'同调召唤',materials:[condition,exact]};
    const event={id:'2:0',native_seq:2,message:63,cards:[result]},action={...event,kind:'operation',summary:'同调召唤',evidence_refs:['2:0']};
    const opening={cards:[condition,exact],lp:[8000,8000]},state={cards:[{...condition,location:16},{...exact,location:16},result],lp:[8000,8000]};
    return {id:'synthetic-condition-origin',name:'条件实例显示验收',status:'completed',plan_stage:'deleted',catalog,
      initial_hand:[condition,exact],initial_hand_ref:'1:0',final_state:state,
      expansion:{conditions:{slots:[OpeningRules.tuner(3),1184620],banned:[]},actual_opening:[59438930,1184620]},
      events:[event],actions:[action],annotations:{nodes:{},cards:{},effects:{},final_marks:{1:{marked:true,effects:{}}}},
      review:{nodes:[{id:'initial',kind:'initial',number:1,state:opening,action_ids:[]},{id:'step',kind:'step',number:2,state_ref:3,state,action_ids:['2:0']},{id:'final',kind:'final',number:3,state,action_ids:[]}]}};
  });
  await page.evaluate(report=>{reviewUI.report=null;mountReview(report);switchView('history');selectReviewNode('step');setReviewDrawer(true);setReviewLogMode('compact');},report);
  for(const mode of ['compact','detailed']){
    await page.evaluate(mode=>setReviewLogMode(mode),mode);
    assert.equal(await page.locator('#review-log img[src="/pics/59438930.jpg"]').count(),0);
    assert.equal(await page.locator('#review-log [data-log-node="initial"] .condition-origin-card').count(),1);
    const actor=page.locator('#review-log [data-review-action="2:0"] .condition-origin-card').first();
    assert(await actor.isVisible());assert.match(await actor.innerText(),/任意等级 3 调整/);
    await actor.click();assert.match(await page.locator('.detail-name h3').innerText(),/任意等级 3 调整/);
    assert.equal(await page.locator('#review-card-detail img[src="/pics/59438930.jpg"]').count(),0);
    assert.match(await page.locator('.detail-effect').innerText(),/沿同一张起手实例/);
    await page.evaluate(()=>closeReviewDetail());await actor.scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(evidence,'condition-origin-'+mode+'.png'),preserveScroll:true});
  }
  const snapshot=await page.evaluate(()=>({report:reviewUI.report,svg:renderPlanTutorialSvg(buildPlanTutorial(reviewUI.report)),final:duelSummaryCards(reviewUI.report,'final')}));
  assert.deepEqual(snapshot.report,report);assert(!snapshot.svg.includes('/pics/59438930'));assert(snapshot.svg.includes('/condition-card.svg'));
  assert(snapshot.final.includes('/condition-card.svg'));assert(!snapshot.final.includes('/pics/59438930'));
  await page.evaluate(()=>{flow.draft=null;reviewUI.report=null;switchView('plans');});
  pass('Condition-origin display in initial hand, later materials, detailed/compact log, card detail, final summary and exported tutorial; original instances preserved');
};
