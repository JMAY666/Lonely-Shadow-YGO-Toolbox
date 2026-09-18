'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

// UI/service-contract simulation. Real YGOPro rounds are a separate user-run check.
module.exports=async({page,evidence,pass})=>{
  let cycle=0,contextId='synthetic-smart',mode='waiting',requestId='',starts=0,prepares=0,matches=0,holdStart=null,holdPoll=null,calculated=false;
  const cancelled=[],dispatches=[];
  const hand=[55144522,55144522,1184620,1184620,1184620];
  const deck={id:'automatic/synthetic-smart',name:'智能识别合成构筑',revision:'fixture',deck:{main:[...hand,...Array(35).fill(1184620)],extra:[],side:[14558127]},tag_selection:{tag_ids:[],primary_ids:[]},tag_names:{}};
  const frame={phase:'detected',monitor_id:'synthetic-smart',round_id:'synthetic-round',detected_order:'first',confirmed:{order:'first',source:'software-audit'},opening:{status:'ready',snapshot_id:'synthetic-opening',cards:hand,confirmed:{snapshot_id:'synthetic-opening'}}};
  const snapshot=()=>({id:requestId,capture_id:'synthetic',cycle,stage:mode,message:mode==='waiting'?'等待对局开始':mode==='second'?'已识别为后攻，后攻展开暂未支持':mode==='failed'?'自动识别未完成':'自动校验通过',
    events:[{stage:'waiting'},{stage:'deck'},{stage:'tags'},{stage:'opening'},{stage:'audit'}],error:mode==='failed'?'未完整捕捉到本局初始发牌':'',failed_stage:mode==='failed'?'opening':null,
    frame,construction:{deck:deck.deck},tag_result:{tag_names:{},selection:deck.tag_selection},context:mode==='ready'?{context_id:contextId,round_id:frame.round_id,snapshot_id:frame.opening.snapshot_id,deck,hand}:null});
  await page.route('**/api/ygopro/attach',route=>route.fulfill({json:{connected:true,process:{capture_id:'synthetic',name:'YGOPro.exe',pid:123,path:'synthetic/YGOPro.exe'}}}));
  await page.route('**/api/ygopro/smart/*',async route=>{
    const body=route.request().postDataJSON(),action=route.request().url().split('/').at(-1);
    if(action==='cancel'){cancelled.push(body.request_id);return route.fulfill({json:{stage:'cancelled'}});}
    if(action==='poll'&&mode==='transport-failure')return route.fulfill({status:500,json:{error:'合成测试：第二局连接中断'}});
    if(action==='start'){++starts;requestId=body.request_id;if(mode==='start-failure')return route.fulfill({status:400,json:{error:'合成测试：进程连接已失效'}});if(holdStart){await holdStart.promise;}}
    if(action==='poll'&&holdPoll){const pending=holdPoll;holdPoll=null;await pending.promise;return route.fulfill({json:pending.value});}
    return route.fulfill({json:snapshot()});
  });
  await page.route('**/api/automatic-duel/*',route=>{
    const body=route.request().postDataJSON(),action=route.request().url().split('/').at(-1);
    if(action==='match'){++matches;return route.fulfill({json:{matches:[],reason:'没有关联 Tag 的方案',excluded:[]}});}
    if(action==='dispatch'){
      dispatches.push(body);
      if(body.intent==='plan-prepare')++prepares;
      return route.fulfill({json:{job:'synthetic-job-'+cycle,version:'synthetic-version-'+cycle,id:null,status:calculated?'ready':'running',progress:{nodes:7,candidates:0},
        ...(calculated?{data:{result:{candidates:[],complete:true,status:'no_route',seconds:.1,coverage:{checked:1,total:1}}}}:{})}});
    }
    return route.fulfill({json:{closed:true}});
  });
  await page.route('**/api/modular/library',route=>route.fulfill({json:{sources:[{id:'synthetic-source',name:'合成来源',status:'ready'}]}}));
  const begin=async()=>{
    await page.locator('[data-duel-action="platform-ygopro"]').click();await page.waitForFunction(()=>!!duelState().automatic.connection);
    assert(await page.locator('#duel-capture-next').isVisible());assert(await page.locator('#duel-capture-smart').isVisible());
    await page.locator('#duel-capture-smart').click();
  };
  const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
  try{
    await page.evaluate(async()=>{
      await switchModule('duel');await startNewDuel();const s=duelState();
      s.mode='BO1';s.operationMode='automatic';s.stage=s.reached=duelStages.function;s.functionPage='platform';
      s.hand=[123,123];s.plan={id:'manual-sentinel'};s.automatic.name='逐步流程保留';renderDuel();
    });
    holdStart=deferred();await begin();await page.waitForFunction(()=>!!smartRun());
    await page.evaluate(()=>beginSmartRecognition());assert.equal(starts,1);
    await page.locator('#duel-capture-close').click();assert(await page.locator('#duel-capture-dialog').isHidden());
    holdStart.resolve();holdStart=null;await page.waitForFunction(()=>!smartRun());
    assert.equal(await page.evaluate(()=>duelState().automatic.name),'逐步流程保留');assert.equal(prepares,0);
    await begin();mode='ready';
    await page.waitForFunction(()=>duelState().stage===duelStages.plans&&!!autoDuelState()?.result);
    assert(await page.locator('#duel-capture-dialog').isHidden());
    await page.waitForFunction(()=>autoDuelState()?.forecast?.jobState?.progress?.nodes===7);
    assert.equal(prepares,1);assert.equal(matches,1);assert.match(await page.locator('#auto-duel-brain-summary').innerText(),/后台准备.*7/);
    assert.equal(await page.evaluate(()=>autoDuelState().plan),null);
    assert.deepEqual(await page.evaluate(()=>autoDuelState().hand),hand);
    assert.deepEqual(await page.evaluate(()=>[duelState().hand,duelState().plan.id]),[[123,123],'manual-sentinel']);
    assert(dispatches.every(body=>body.context_id==='synthetic-smart'));
    await page.screenshot({path:path.join(evidence,'smart-plans-calculating.png')});
    // A result arriving after selection must never reset selection/progress.
    await page.evaluate(()=>{autoDuelState().plan={id:'chosen-sentinel'};autoDuelState().position={key:'chosen-step',choice:2};});
    calculated=true;await page.waitForFunction(()=>autoDuelState()?.forecast?.data?.result?.complete===true);
    assert.deepEqual(await page.evaluate(()=>[autoDuelState().plan.id,autoDuelState().position.key]),['chosen-sentinel','chosen-step']);assert.equal(prepares,1);
    await page.evaluate(()=>{autoDuelState().plan=null;autoDuelState().position=null;});
    await page.locator('[data-duel-stage="4"]').first().click();assert.match(await page.locator('#duel-body').innerText(),/本局自动校验结果/);
    assert.equal(await page.locator('[data-duel-action="confirm-opening"]').count(),0);
    await page.locator('[data-auto-duel-action="smart-plans"]').click();
    const oldCycle=structuredClone(snapshot());
    cycle=1;mode='waiting';contextId='synthetic-next-round';frame.round_id='synthetic-next-round';
    frame.opening.snapshot_id='synthetic-next-opening';frame.opening.confirmed.snapshot_id=frame.opening.snapshot_id;deck.id='automatic/'+contextId;
    await page.waitForFunction(()=>smartRun()?.value?.cycle===1&&document.querySelector('#duel-capture-dialog').open);
    assert.equal(await page.evaluate(()=>autoDuelState()),null);
    await page.evaluate(old=>acceptSmartRecognition(smartRun(),old),oldCycle);
    assert.equal(await page.evaluate(()=>smartRun().value.cycle),1);assert.equal(await page.evaluate(()=>duelState().stage),1);
    mode='ready';calculated=false;
    await page.waitForFunction(()=>autoDuelState()?.context.context_id==='synthetic-next-round'&&autoDuelState()?.forecast?.job);
    assert.equal(starts,2);assert.equal(prepares,2);assert.equal(matches,2);
    await page.evaluate(()=>autoDuelObservationDialog.showModal());mode='transport-failure';
    await page.waitForFunction(()=>smartRun()?.value?.stage==='invalidated'&&document.querySelector('#duel-capture-dialog').open);
    assert.equal(await page.evaluate(()=>autoDuelObservationDialog.open),false);assert.equal(await page.evaluate(()=>autoDuelState().ended),true);
    await page.evaluate(()=>cancelSmartRecognition());mode='waiting';await begin();
    holdPoll=deferred();holdPoll.value={...snapshot(),stage:'ready',context:{context_id:contextId,round_id:frame.round_id,snapshot_id:frame.opening.snapshot_id,deck,hand}};
    const pending=holdPoll;
    await page.waitForRequest(request=>request.url().endsWith('/ygopro/smart/poll'));
    await page.locator('#duel-capture-close').click();pending.resolve();
    await page.waitForFunction(()=>!smartRun());assert.equal(await page.evaluate(()=>duelState().stage),1);assert.equal(prepares,2);
    mode='second';await begin();await page.waitForFunction(()=>smartRun()?.value?.stage==='second');
    assert.match(await page.locator('#duel-capture-status').textContent(),/后攻展开暂未支持/);assert.equal(prepares,2);
    await page.locator('#duel-capture-close').click();mode='failed';await begin();await page.waitForFunction(()=>smartRun()?.value?.stage==='failed');
    assert.match(await page.locator('#duel-capture-processes').innerText(),/初始发牌/);assert(await page.locator('#duel-smart-restart').isVisible());assert.equal(prepares,2);
    await page.locator('#duel-capture-close').click();mode='start-failure';await begin();
    await page.waitForFunction(()=>smartRun()?.value?.stage==='invalidated');
    assert.match(await page.locator('#duel-capture-processes').innerText(),/进程连接已失效/);
    assert.equal(await page.locator('#duel-capture-status').textContent(),'启动监测失败');
    await page.locator('#duel-capture-close').click();assert(cancelled.length>=4);
    pass('Smart recognition simulated UI: cancellation including late start/poll, duplicate entry, automatic next-round monitoring and old-cycle rejection, frozen input, automatic matching/computation, selection preservation, second player and missed deal; no manual confirmation');
  }finally{
    holdStart?.resolve();holdPoll?.resolve();await page.evaluate(()=>cancelSmartRecognition());
    for(const route of ['**/api/ygopro/attach','**/api/ygopro/smart/*','**/api/automatic-duel/*','**/api/modular/library'])await page.unroute(route);
    await page.evaluate(()=>startNewDuel());
  }
};
