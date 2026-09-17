'use strict';
// Public card text + synthetic event ids reproduce the legacy delayed-disable
// schema. This fixture is rendered read-only and is never saved to the service.
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async function({page,plan,pass,evidence}) {
  const original=JSON.stringify(await page.evaluate(id=>api('/api/plan/'+id),plan.id));
  try {
    await page.evaluate(base=>{
      const monster={code:2772337,name:'赐炎之咎姬',instance_id:49,controller:0,location:4,sequence:5,position:1};
      const trap={code:10045474,name:'无限泡影',instance_id:97,controller:1,location:8,sequence:0,position:5};
      const lynx={code:14812471,name:'转生炎兽 烽火猞猁',instance_id:54,controller:0,location:16,position:5};
      const own={id:'1:0',activation_ref:'1:0',kind:'effect',chain_group:1,chain_link:1,status:'disabled',cards:[monster],evidence_refs:['1:0','9:0'],results:[]};
      const response={id:'3:0',activation_ref:'3:0',kind:'effect',chain_group:1,chain_link:2,status:'resolved',cards:[trap],engine_effect:{owner_code:10045474,effect_type:26},targets:[],results:[],evidence_refs:['3:0','7:0']};
      const target={id:'4:0',kind:'target',cards:[monster],evidence_refs:['4:0']};
      const replacement={id:'10:0',kind:'action',cards:[lynx],evidence_refs:['10:0']};
      const events=[{id:'1:0',message:70},{id:'2:0',message:71,activation_ref:'1:0'},{id:'3:0',message:70},
        {id:'4:0',message:83,targets:[monster]},{id:'5:0',message:71,activation_ref:'3:0'},
        {id:'6:0',message:72,activation_ref:'3:0'},{id:'7:0',message:73,activation_ref:'3:0'},
        {id:'8:0',message:72,activation_ref:'1:0'},{id:'9:0',message:76,activation_ref:'1:0',resolution_source_ref:'1:0'},
        {id:'10:0',message:50,cards:[lynx],origin:{controller:0,location:16},destination:{controller:0,location:32,position:5},reason:64,
          cause:{owner_code:14812471,handler_code:14812471,handler_instance:54,event_code:50,effect_type:2058,range:16}}].map(e=>({cards:[],...e}));
      const report={...base,id:'display-only-fixture',name:'卡片效果展示验收',plan_stage:'deleted',annotations:emptyEdits(),branches:[],branch_points:[],actions:[own,response,target,replacement],events,
        catalog:{2772337:{type:1},10045474:{type:4},14812471:{desc:'①：检索。\n②：自己场上的「转生炎兽」卡被战斗·效果破坏的场合，可以作为代替把墓地的这张卡除外。'}},
        review:{nodes:[{id:'initial',kind:'initial',number:1,state:null,action_ids:[]},{id:'step:response',kind:'step',number:2,state:null,action_ids:['1:0','3:0','4:0']},{id:'step:replacement',kind:'step',number:3,state:null,action_ids:['10:0']},{id:'final',kind:'final',number:4,state:null,action_ids:[]}]}};
      reviewUI.report=null;mountReview(report);switchView('history');setReviewLogMode('compact');selectReviewNode('step:response');setReviewDrawer(true);
    },plan);
    const response=page.locator('#review-log [data-log-node="step:response"]');
    assert.equal(await response.locator('.log-action').count(),1);
    assert.match(await response.innerText(),/对方 发动陷阱卡/);
    assert.match(await response.innerText(),/随后 我方怪兽效果被无效/);
    assert(!(await response.innerText()).includes('处理结果未记录'));
    assert(await response.locator('.compact-chain').evaluate(el=>el.scrollWidth<=el.clientWidth+1),'The three connected stages fit inside the log drawer');
    await page.locator('#review-log img').evaluateAll(images=>Promise.all(images.map(async img=>{img.loading='eager';await img.decode();})));
    await page.screenshot({path:path.join(evidence,'impermanence-connected-log.png')});
    await page.evaluate(()=>selectReviewNode('step:replacement'));
    const applied=page.locator('#review-log [data-log-node="step:replacement"]');
    assert.match(await applied.innerText(),/②效果代替破坏/);
    assert.match(await applied.innerText(),/代替我方「转生炎兽」卡被破坏/);
    await page.screenshot({path:path.join(evidence,'balelynx-second-effect.png')});
    await page.evaluate(()=>setReviewDrawer(false));
    await page.locator('#review-sidebar-toggle').click();
    assert.equal(await page.locator('#review-timeline-drawer').isVisible(),false);
    await page.locator('#review-sidebar-toggle').click();
    const confirmation=page.evaluate(()=>confirmFlow('删除展示验收方案？','仅检查按钮颜色。','删除方案'));
    await page.locator('#flow-dialog').waitFor({state:'visible'});
    const colors=await page.locator('#flow-confirm').evaluate(el=>({bg:getComputedStyle(el).backgroundColor,fg:getComputedStyle(el).color}));
    assert.notEqual(colors.bg,'rgb(255, 255, 255)');assert.notEqual(colors.bg,colors.fg);
    await page.screenshot({path:path.join(evidence,'plan-confirmation-colors.png')});
    await page.locator('#flow-cancel').click();assert.equal(await confirmation,false);
  } finally {await page.evaluate(id=>showPlan(id),plan.id);}
  assert.equal(JSON.stringify(await page.evaluate(id=>api('/api/plan/'+id),plan.id)),original);
  pass('Read-only legacy display: Balelynx effect two, connected opponent Impermanence/target/delayed negation, top drawer and colored confirmation; frozen source unchanged');
  await require('./random-effects-smoke.cjs')({page,plan,pass,evidence});
};
