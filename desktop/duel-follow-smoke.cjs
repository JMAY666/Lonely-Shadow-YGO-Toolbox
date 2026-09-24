'use strict';
// Renderer-only simulated transport. Real-game acceptance is a separate harness.
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async({page,application,evidence,pass})=>{
  const context=await page.evaluate(()=>autoDuelState().context);
  let value={id:'synthetic-follow',context_id:context.context_id,round_id:context.round_id,revision:'synthetic',
    status:'following',reason:'等待执行下一步',connected:true,sampled_ms:Date.now(),completed:[],next_key:'main/s1',
    steps:[{key:'main/s1',status:'pending',reason:''},{key:'main/s2',status:'pending',reason:''}],
    live_state:{source:'mdpro3-read-only',cards:[],counts:{}},kind:'formal',requires_sync:false};
  const calls=[];
  await page.route('**/api/automatic-duel/follow/start',route=>route.fulfill({json:value}));
  await page.route('**/api/automatic-duel/follow/poll',route=>{
    const body=route.request().postDataJSON();calls.push(body);
    if(body.action==='pause')value={...value,status:'paused',reason:'已暂停'};
    if(['resume','resync'].includes(body.action))value={...value,status:'following',reason:'已重新核对',requires_sync:false,connected:true};
    return route.fulfill({json:value});
  });
  const click=async action=>{await page.locator(`[data-auto-follow="${action}"]`).click();await page.waitForFunction(()=>!autoDuelState().follow?.busy);};
  try{
    await page.evaluate(()=>{const s=autoDuelState();s.smart=true;duelState().automatic.platform='mdpro3';renderAutoDuel();return startAutoFollow(s);});
    await page.waitForFunction(()=>autoDuelState().position.key==='main/s1');
    assert.match(await page.locator('#auto-duel-follow').innerText(),/尚未执行/);
    value={...value,status:'executing',reason:'连锁处理中'};
    await page.waitForFunction(()=>autoDuelState().follow?.value?.status==='executing');
    assert.equal(await page.evaluate(()=>autoDuelState().follow.value.completed.length),0);
    value={...value,status:'following',completed:[{key:'main/s1',source:'mdpro3-read-only'}],next_key:'main/s2',steps:[{key:'main/s1',status:'completed'},{key:'main/s2',status:'pending'}]};
    await page.waitForFunction(()=>autoDuelState().position.key==='main/s2');
    await page.locator('[data-auto-duel-node="main/s1"]').click();
    assert.equal(await page.evaluate(()=>autoDuelState().follow.viewLive),false);
    value={...value,status:'completed',completed:[...value.completed,{key:'main/s2',source:'mdpro3-read-only'}],next_key:'main/final',steps:value.steps.map(s=>({...s,status:'completed'}))};
    await page.waitForFunction(()=>autoDuelState().follow.value.completed.length===2);
    assert.equal(await page.evaluate(()=>autoDuelState().position.key),'main/s1');
    assert.match(await page.locator('#auto-duel-follow').innerText(),/正在手动浏览/);
    await click('return');assert.equal(await page.evaluate(()=>autoDuelState().position.key),'main/final');
    await application.evaluate(()=>globalThis.tutorialAcceptance.invoke('back'));
    await page.waitForFunction(()=>autoDuelState().position.key==='main/s2');
    assert.equal(await page.evaluate(()=>autoDuelState().follow.value.completed.length),2);
    value={...value,status:'needs_confirmation',reason:'读取中断，等待重新同步',connected:false,requires_sync:true};
    await page.waitForFunction(()=>autoDuelState().follow.value.requires_sync);
    await click('resync');assert(calls.some(c=>c.action==='resync'));
    await click('pause');assert.equal(await page.evaluate(()=>autoDuelState().follow.value.status),'paused');
    await click('resume');assert(calls.some(c=>c.action==='resume'));
    await page.locator('#auto-duel-follow summary').click();
    assert.match(await page.locator('#auto-duel-follow').innerText(),/实时场面/);
    assert.match(await page.locator('#auto-duel-current-detail').innerText(),/方案预期场面/);
    await page.screenshot({path:path.join(evidence,'mdpro3-follow-simulated.png')});
    pass('SIMULATED MDPRO3 follow UI: chain waiting, automatic progress, manual review without viewport theft, return-to-live, IPC shortcuts, pause/resync and live/expected scene separation');
  }finally{
    await page.evaluate(()=>{stopAutoFollow(autoDuelState());autoDuelState().smart=false;duelState().automatic.platform='ygopro';renderAutoDuel();});
    await page.unroute('**/api/automatic-duel/follow/start');await page.unroute('**/api/automatic-duel/follow/poll');
  }
};
