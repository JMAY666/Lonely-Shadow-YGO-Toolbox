'use strict';
const assert=require('node:assert/strict'),path=require('node:path');
module.exports=async({page,application,evidence,pass})=>{
  const hand=[14558127,97268402,10045474,16387555,54693926];
  const deck=await page.evaluate(hand=>api('/api/decks',{name:'实战辅助隔离验收 '+Date.now(),deck:{main:[...hand,...Array(35).fill(1184620)],extra:[42781164,15665977],side:[]}}),hand);
  await page.locator('#module-duel').click();await page.waitForFunction(()=>moduleUI.current==='duel'&&!moduleUI.switching);
  for(const action of ['bo1','manual']){await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);}
  await page.locator(`[data-duel-deck="${deck.id}"]`).click();await page.waitForFunction(()=>!duelUI.busy);
  for(const action of ['start-duel','second']){await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);}
  for(const code of hand)await page.locator(`[data-duel-add="${code}"]`).click();
  await page.locator('[data-live-start]').click();await page.waitForFunction(()=>liveAssistanceActive()&&!liveAssistanceState().busy);
  assert.equal(await page.locator('.duel-candidates').count(),0);
  const snapshot=()=>page.locator('[data-live-form="snapshot"]');
  await snapshot().locator('[name="phase"]').selectOption('main1');
  await snapshot().locator('[name="normal_used"]').fill('0');await snapshot().locator('[name="spell_trap_used"]').fill('0');
  await snapshot().locator('[name="enemy_query"]').fill('杀手级调整曲·提示员');
  await page.locator('[data-live-search]').click();await page.waitForFunction(()=>liveAssistanceState().search.length>0);
  await snapshot().locator('[name="enemy_add"]').selectOption('16387555');
  await page.locator('[data-live-add-enemy]').click();
  const enemy=await page.evaluate(()=>liveAssistanceState().draft.cards.find(c=>c.controller===1));
  await page.locator(`[data-live-card="${enemy.id}"] [name="disabled"]`).selectOption('false');
  for(const key of ['board','hand','usage','limits'])await snapshot().locator(`[name="known_${key}"]`).check();
  await snapshot().locator('button[type="submit"]').click();await page.waitForFunction(()=>!liveAssistanceState().busy&&!liveAssistanceState().dirty);
  const action=()=>page.locator('[data-live-form="action"]');
  await action().locator('[name="card_id"]').selectOption(enemy.id);await action().locator('[name="effect"]').fill('1');
  await action().locator('button').click();await page.waitForFunction(()=>!liveAssistanceState().busy&&liveAssistanceState().value.session.events.some(e=>e.kind==='activate'));
  await page.locator('[data-live-form="window"] [name="confirmed"]').check();await page.locator('[data-live-form="window"] button').click();
  await page.waitForFunction(()=>!liveAssistanceState().busy&&liveAssistanceState().value.analysis.primary.kind==='response');
  assert.match(await page.locator('[data-live-primary]').innerText(),/灰流丽/);
  assert.equal((await page.evaluate(()=>liveAssistanceState().value.session.state.cards.filter(c=>c.zone==='hand'))).length,5);
  pass('Live workspace: separate current resources, public opponent action, sourced route candidate, explicitly confirmed window, no resource spending on viewing advice');
  for(const [width,height] of [[1440,960],[960,800]]){
    await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(...size),[width,height]);
    await page.waitForFunction(width=>innerWidth===width,width);
    assert(await page.locator('#duel').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
    await page.screenshot({path:path.join(evidence,`live-assistance-${width}.png`)});
  }
  const ash=await page.evaluate(()=>liveAssistanceState().value.session.state.cards.find(c=>c.code===14558127));
  await action().locator('[name="card_id"]').selectOption(ash.id);await action().locator('[name="cost_id"]').selectOption(ash.id);
  await action().locator('button').click();await page.waitForFunction(()=>!liveAssistanceState().busy);
  const actual=await page.evaluate(()=>liveAssistanceState().value.session.events.at(-1).id);
  await page.locator('[data-live-form="result"] [name="event_id"]').selectOption(actual);
  await page.locator('[data-live-form="result"] [name="outcome"]').selectOption('negated_activation');
  await page.locator('[data-live-form="result"] button').click();await page.waitForFunction(()=>!liveAssistanceState().busy);
  assert.equal(await page.evaluate(id=>liveAssistanceState().value.session.state.cards.find(c=>c.id===id).zone,ash.id),'grave');
  assert.deepEqual(await page.evaluate(()=>liveAssistanceState().value.session.frozen),hand);
  // Snapshot correction and persisted usage references must not undo the paid cost.
  const fold=page.locator('.opening-fold').filter({has:page.locator('[data-live-form="snapshot"]')});
  if(await fold.getAttribute('open')===null)await fold.locator(':scope > summary').click();
  await snapshot().locator('[name="turn"]').fill('2');await snapshot().locator('[name="player"]').selectOption('0');
  await snapshot().locator('[name="normal_used"]').fill('0');
  await snapshot().locator('button[type="submit"]').click();await page.waitForFunction(()=>!liveAssistanceState().busy&&liveAssistanceState().value.session.state.turn===2);
  assert(await page.locator('.live-workspace').getByText('通常召唤提示员作为入口',{exact:true}).count()>0);
  const cue=await page.evaluate(()=>liveAssistanceState().value.session.state.cards.find(c=>c.code===16387555&&c.controller===0));
  await action().locator('[name="card_id"]').selectOption(cue.id);await action().locator('[name="kind"]').selectOption('normal');
  await action().locator('button').click();await page.waitForFunction(()=>!liveAssistanceState().busy&&liveAssistanceState().value.session.state.normal_used===1);
  assert.equal(await page.locator('.live-workspace').getByText('通常召唤提示员作为入口',{exact:true}).count(),0);
  pass('Actual use and negated activation retain costs; own turn starts from four remaining hand cards; normal summon is recorded once and continuation preserves history');
  const fold2=page.locator('.opening-fold').filter({has:page.locator('[data-live-form="snapshot"]')});
  if(await fold2.getAttribute('open')===null)await fold2.locator(':scope > summary').click();
  const veiler=await page.evaluate(()=>liveAssistanceState().value.session.state.cards.find(c=>c.code===97268402));
  for(const [material,level] of [[cue,3],[veiler,1]]){
    const row=page.locator(`[data-live-card="${material.id}"]`);
    await row.locator('details > summary').click();await row.locator('[name="level"]').fill(String(level));await row.locator('[name="tuner"]').selectOption('true');
  }
  await page.locator(`[data-live-card="${cue.id}"] [name="disabled"]`).selectOption('true');
  await snapshot().locator('button[type="submit"]').click();await page.waitForFunction(()=>!liveAssistanceState().busy&&liveAssistanceState().value.analysis.own.candidates.some(c=>c.synchro));
  await page.locator('[data-live-record-synchro]').first().click();await page.waitForFunction(()=>!liveAssistanceState().busy&&liveAssistanceState().value.session.state.cards.some(c=>c.code===42781164&&c.zone==='monster'));
  assert.equal(await page.evaluate(()=>liveAssistanceState().value.session.state.normal_used),1);
  assert.equal(await page.evaluate(id=>liveAssistanceState().value.session.state.cards.find(c=>c.id===id).zone,veiler.id),'grave');
  pass('A negated on-field Cue still supplies its non-effect hand-material procedure; confirmed two-material continuation consumes the actual material without restoring the normal summon');
  const afterSynchro=page.locator('.opening-fold').filter({has:page.locator('[data-live-form="snapshot"]')});
  if(await afterSynchro.getAttribute('open')===null)await afterSynchro.locator(':scope > summary').click();
  await snapshot().locator('[name="lp0"]').fill('7000');
  await page.route('**/api/duel/live',route=>route.fulfill({status:400,json:{error:'隔离测试：保存失败'}}));
  await snapshot().locator('button[type="submit"]').click();await page.waitForFunction(()=>!liveAssistanceState().busy&&liveAssistanceState().error.includes('保存失败'));
  assert.equal(await snapshot().locator('[name="lp0"]').inputValue(),'7000');await page.unroute('**/api/duel/live');
  await snapshot().locator('button[type="submit"]').click();await page.waitForFunction(()=>!liveAssistanceState().busy&&!liveAssistanceState().dirty);
  await page.evaluate(()=>liveCommand('window',{kind:'open',confirmed:true}));
  await page.waitForFunction(()=>document.querySelector('[data-live-primary]').textContent.includes('窗口需要重新确认'),null,{timeout:20000});
  pass('A real 15-second manual response-window expiry removes the old actionable presentation');
  const beforeWatch=await page.evaluate(()=>structuredClone(liveAssistanceState().value));let observed=0;
  await page.route('**/api/duel/live',async route=>{
    if(route.request().postDataJSON().action!=='observe'){await route.continue();return;}
    observed++;const value=structuredClone(beforeWatch);
    value.session.capture_id='isolated-ui-observer';value.session.revision++;value.session.needs_sync=true;
    value.session.state.known.usage=false;value.session.state.opponent_hand=4;value.session.state.window=null;
    value.analysis={...value.analysis,expires_at:null,window_id:null,primary:{kind:'sync',text:'先核对当前局面',reason:'隔离快照：缺少连续次数记录'}};
    await route.fulfill({json:value});
  });
  await page.evaluate(()=>{const v=liveAssistanceState();v.value.session.capture_id='isolated-ui-observer';v.watch=true;renderDuel();liveScheduleWatch();});
  await page.waitForFunction(()=>liveAssistanceState().value.session.state.opponent_hand===4);
  assert.match(await page.locator('[data-live-primary]').innerText(),/核对/);
  const observedFold=page.locator('.opening-fold').filter({has:page.locator('[data-live-form="snapshot"]')});
  if(await observedFold.getAttribute('open')===null)await observedFold.locator(':scope > summary').click();
  await snapshot().locator('[name="lp0"]').fill('6500');const count=observed;
  await page.waitForTimeout(1300);assert.equal(observed,count);assert.equal(await snapshot().locator('[name="lp0"]').inputValue(),'6500');
  await page.evaluate(value=>{const v=liveAssistanceState();v.watch=false;clearTimeout(v.watchTimer);v.value=value;v.draft=structuredClone(value.session.state);v.dirty=false;renderDuel();},beforeWatch);
  await page.unroute('**/api/duel/live');
  pass('Automatic observation transport fixture refreshes partial facts and clears advice; editing pauses observation without replacing a human draft');
  const id=await page.evaluate(()=>liveAssistanceState().value.session.id);
  const state=await page.evaluate(()=>liveAssistanceState().value.session);
  // Deliver a late mutation only after leaving the module. It cannot revive
  // the old view, and revision races cannot leave that abandoned session open.
  let release,started=false;const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/duel/live',async route=>{
    const data=route.request().postDataJSON();
    if(data.operation!=='preference'){await route.continue();return;}
    const response=await route.fetch();started=true;await gate;await route.fulfill({response});
  });
  await page.evaluate(()=>{void liveCommand('preference',{goal:'followup',preserve:[]});});
  await page.waitForFunction(()=>liveAssistanceState().busy);
  while(!started)await new Promise(resolve=>setTimeout(resolve,20));
  await page.locator('#module-home').click();release();
  await page.waitForFunction(()=>moduleUI.current==='home'&&!moduleUI.switching);
  await page.waitForFunction(async id=>(await api('/api/duel/live',{action:'read',id})).session.closed,id);
  assert.equal(await page.evaluate(()=>liveAssistanceActive()),false);await page.unroute('**/api/duel/live');
  const closed=await page.evaluate(id=>api('/api/duel/live',{action:'read',id}),id);
  pass('Leaving during a delayed response rejects the old view and closes the correct private session even after a revision race');
  pass('Failed save keeps the editable draft; corrected facts and immutable opening survive; wide and narrow renderer layouts have no horizontal overflow');
  return {id,state:closed.session};
};
