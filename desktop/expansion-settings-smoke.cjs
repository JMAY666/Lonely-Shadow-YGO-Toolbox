'use strict';
// Extends the real desktop/packaged harness using only its isolated renderer and native test API.
const assert = require('node:assert/strict');
const path = require('node:path');

module.exports = async function settingsAcceptance({page, nativeWait, nativeState, hostWait, waitHistory, pass, evidence}) {
  const request = (url, body) => page.evaluate(({url,body}) => api(url,body), {url,body});
  const report = id => request(`/api/report/${id}`);
  assert.equal((await request('/api/card/26202165')).name,'三眼怪');
  const choose = async (target, slot, code) => {
    await page.locator(`[data-${target==='opponent'?'opponent-slot':'slot'}="${slot}"]`).click();
    await page.locator(code===null?'#clear-slot':`[data-choice="${code}"]`).click();
  };
  const start = async () => {
    await page.locator('#begin-expansion').click();
    await page.waitForFunction(()=>!!app.active&&!flow.busy);
    const id=await page.evaluate(()=>app.active.id);
    await hostWait(id,s=>s.frame_ready);await nativeWait(id,s=>s.prompt===11);
    await page.waitForFunction(()=>flow.timer?.mode==='off'||flow.timer?.started!==null||flow.timer?.expired);
    return id;
  };
  const back = async () => {
    await page.locator('#return-conditions').click();await page.locator('#flow-confirm').click();
    await page.waitForFunction(()=>!!flow.design&&!app.active&&!flow.busy);
  };
  const finish = async () => {
    await page.locator('#finish-training').click();await waitHistory('completed');
    await page.waitForFunction(()=>!!flow.draft&&!document.querySelector('#draft-editor').hidden);
  };
  const cast = async (id, code) => {
    let state=await nativeWait(id,s=>s.prompt===11&&s.targets.some(t=>t.location===2&&t.code===code));
    let target=state.targets.find(t=>t.location===2&&t.code===code);
    await nativeState(id,'click',{x:target.x,y:target.y});
    state=await nativeWait(id,s=>s.buttons.some(b=>b.text==='发动'));
    target=state.buttons.find(b=>b.text==='发动');await nativeState(id,'click',{x:target.x,y:target.y});
    state=await nativeWait(id,s=>s.prompt===18);target=state.targets.find(t=>t.location===8&&t.sequence===0);
    await nativeState(id,'click',{x:target.x,y:target.y});await nativeWait(id,s=>s.prompt===11);
  };
  const source=await request('/api/decks',{name:`可配置验收-${Date.now()}`,deck:{main:[...Array(3).fill(55144522),...Array(37).fill(1184620)],extra:[],side:[55144522]}});
  const opponent=await request('/api/decks',{name:`对手验收-${Date.now()}`,deck:{main:[14558127,...Array(39).fill(1184620)],extra:[],side:[55144522]}});
  const mandatory=await request('/api/decks',{name:`强制效果验收-${Date.now()}`,deck:{main:[26202165,...Array(39).fill(1184620)],extra:[],side:[]}});
  await page.locator('#nav-decks').click();await page.evaluate(()=>deckList());
  if (await page.locator('#deck-workbench').isVisible()) await page.locator('#back-to-decks').click();
  await page.locator('[data-open-deck='+JSON.stringify(source.id)+']').click();
  await page.waitForFunction(id=>app.id===id&&!app.busy,source.id);
  await page.locator('#start-training').click();await page.waitForFunction(()=>!!flow.design);
  await page.locator('#plan-name').fill('数量与条件保留验收');
  await page.locator('#hand-count').fill('0');assert(await page.locator('#begin-expansion').isDisabled());
  assert.match(await page.locator('#design-error').innerText(),/起手数量/);
  await page.locator('[data-hand-count="1"]').click();
  await page.locator('#add-opening-ban').click();await page.locator('[data-choice="55144522"]').click();
  await page.locator('#player-lp').fill('0');assert(await page.locator('#begin-expansion').isDisabled());
  assert.match(await page.locator('#design-error').innerText(),/玩家初始 LP/);
  await page.locator('#player-lp').fill('4000');await page.locator('#opponent-lp').fill('6500');
  await page.locator('#add-opening-ban').click();await page.locator('[data-choice="1184620"]').click();
  assert.match(await page.locator('#design-error').innerText(),/只剩 0 张.*需要 1 张/);
  assert(await page.locator('#begin-expansion').isDisabled());await page.locator('[data-unban="1184620"]').click();
  const ids=[];
  for(const count of [1,2,3,5]) {
    await page.locator('#hand-count').fill(String(count));
    await page.locator('#timer-mode').selectOption(count===1?'down':count===5?'off':'up');
    if(count!==5)await page.locator('#timer-seconds').fill(count===1?'1':'15');
    const id=await start();ids.push(id);const r=await report(id);
    assert.equal(r.initial_hand.length,count);assert(r.initial_hand.every(c=>c.code===1184620));
    assert.equal(r.final_state.cards.filter(c=>c.controller===0&&c.location===2).length,count);
    assert.deepEqual(r.final_state.lp,[4000,6500]);
    if(count===1) {
      await page.locator('#timer-expired').waitFor({state:'visible'});
      assert.equal(await page.evaluate(()=>flow.timer.started),null);await nativeWait(id,s=>s.prompt===11);
      await page.locator('#return-conditions').click();await page.locator('#flow-cancel').click();
      assert.equal(await page.evaluate(()=>app.active.id),id);
    } else if(count===5) {assert.equal(await page.locator('#expansion-timer').isVisible(),false);}
    else {await page.waitForFunction(()=>timerValue(flow.timer)>=16);}
    await back();
    const restored=await page.evaluate(()=>designPayload(flow.design));
    assert.equal(restored.conditions.hand_count,count);assert.deepEqual(restored.conditions.banned,[55144522]);
    assert.equal(restored.player_lp,4000);assert.equal(restored.opponent_lp,6500);
    assert.equal(await page.evaluate(()=>flow.timer.started),null);
  }
  assert.equal(new Set(ids).size,4);
  pass('Real opening hands contain exactly 1/2/3/5 cards; single-card bans, LP, timer modes and cancelable return work');

  await page.locator('#opponent-ai').check();await page.locator('#opponent-deck').selectOption(opponent.id);
  await page.waitForFunction(id=>flow.design.opponent_config.id===id&&!flow.busy,opponent.id);
  await page.locator('#edit-opponent-deck').click();await page.waitForFunction(()=>!!flow.deckEdit);
  // Use the same editor's card operations against its isolated working snapshot.
  await page.evaluate(async()=>{await removeCard(14558127,'main');await addCard(1184620,'main');});
  await page.locator('#save-deck').click();await page.waitForFunction(()=>!flow.deckEdit&&app.view==='design');
  assert.deepEqual((await request(`/api/deck?id=${encodeURIComponent(opponent.id)}`)).deck,opponent.deck);
  assert.match(await page.locator('#design-error').innerText(),/已不在当前主卡组/);
  assert(await page.locator('#begin-expansion').isDisabled());await choose('opponent',0,null);
  await page.locator('#opponent-hand-count').fill('2');assert.match(await page.locator('#design-error').innerText(),/超出数量/);
  for(const slot of [4,3,2])await choose('opponent',slot,null);
  let customId=await start();let r=await report(customId);
  assert.equal(r.expansion.opponent_config.conditions.slots[0],null);
  assert.equal(r.final_state.cards.filter(c=>c.controller===1&&c.location===2).length,2);
  assert.equal(r.final_state.cards.filter(c=>c.controller===1&&c.code===14558127).length,0);
  await back();
  pass('Opponent deck selection and shared editing change the actual engine deck, preserve source and flag stale/overflow selections');

  await page.locator('[data-unban="55144522"]').click();await page.locator('#hand-count').fill('1');await choose('player',0,55144522);
  await page.locator('#opponent-deck').selectOption(opponent.id);await page.waitForFunction(()=>!flow.busy);
  await choose('opponent',0,14558127);await choose('opponent',1,1184620);
  await page.locator('#opponent-responses').uncheck();await page.locator('#timer-mode').selectOption('up');await page.locator('#timer-seconds').fill('17');
  const silentId=await start();await cast(silentId,55144522);r=await report(silentId);
  assert.equal(r.statistics['效果抽卡'],2);assert(!r.events.some(e=>e.message===70&&e.cards.some(c=>c.code===14558127)));
  assert(r.final_state.cards.some(c=>c.controller===1&&c.location===2&&c.code===14558127));
  // Its own turn still summons with the response switch off.
  let state=await nativeWait(silentId,s=>s.prompt===11&&s.buttons.some(b=>b.text==='ＥＰ'));
  let target=state.buttons.find(b=>b.text==='ＥＰ');await nativeState(silentId,'click',{x:target.x,y:target.y});
  await nativeWait(silentId,s=>s.prompt===11&&s.buttons.some(b=>b.text==='ＢＰ'));
  assert((await report(silentId)).final_state.cards.some(c=>c.controller===1&&c.location===4));
  await finish();await page.locator('#draft-name').fill('设置保存恢复验收');await page.locator('#save-plan').click();
  await page.locator('#confirm-save-plan').click();
  await page.waitForFunction(id=>flow.selectedPlan===id&&!flow.busy,silentId);
  await page.locator('#edit-plan').click();await page.waitForFunction(()=>flow.draft?.saved);
  await page.locator('#draft-notes').fill('新增设置随正式方案保存');await page.locator('#save-plan').click();await page.locator('#confirm-save-plan').click();await page.waitForFunction(()=>!flow.busy&&!flow.draft);
  await page.locator('#plan-conditions').click();await page.waitForFunction(()=>!!flow.design&&app.view==='design');
  const savedConfig=await page.evaluate(()=>designPayload(flow.design));
  assert.equal(savedConfig.opponent_responses,false);assert.equal(savedConfig.player_lp,4000);
  assert.equal(savedConfig.conditions.hand_count,1);assert.deepEqual(savedConfig.timer,{mode:'up',seconds:17});
  assert.deepEqual(savedConfig.opponent_config.conditions.slots,[14558127,1184620]);
  await page.screenshot({path:path.join(evidence,'settings-restored.png')});
  pass('Disabled AI passes Ash Blossom, still takes its own turn; complete configuration and edited notes reopen from a saved plan');

  await page.locator('#opponent-deck').selectOption(mandatory.id);await page.waitForFunction(()=>!flow.busy);
  await choose('opponent',0,26202165);await choose('opponent',1,null);await page.locator('#opponent-hand-count').fill('1');
  await page.locator('#design-back').click();await page.waitForFunction(()=>flow.deckEdit?.target==='player');
  await page.evaluate(async()=>{while(app.deck.main.includes(55144522))await removeCard(55144522,'main');await addCard(53129443,'main');await addCard(1184620,'main');await addCard(1184620,'main');});
  await page.locator('#save-deck').click();await page.waitForFunction(()=>!flow.deckEdit);await choose('player',0,53129443);
  await page.locator('#turn-order').selectOption('second');await page.locator('#timer-mode').selectOption('off');
  const forcedId=await start();const initial=await report(forcedId);
  assert.equal(initial.initial_hand.length,1);
  assert.equal(initial.final_state.cards.filter(c=>c.controller===0&&c.location===2).length,2,'Second player draws through the actual rule flow');
  assert(initial.final_state.cards.some(c=>c.controller===1&&c.location===4&&c.code===26202165));
  const journalTurns=initial.events.filter(e=>e.message===40);assert.equal(journalTurns[0].value,1);
  await cast(forcedId,53129443);const forced=await report(forcedId);
  assert(forced.events.some(e=>e.message===70&&e.cards.some(c=>c.code===26202165)), 'Sangan mandatory trigger must still activate');
  assert(forced.final_state.cards.some(c=>c.controller===1&&c.location===2&&c.code===1184620));
  await finish();await page.locator('#delete-draft').click();await page.locator('#flow-cancel').click();assert.equal(await page.evaluate(()=>flow.draft.id),forcedId);
  await page.locator('#delete-draft').click();await page.locator('#flow-confirm').click();await page.waitForFunction(()=>!flow.draft&&!flow.busy);
  assert.equal((await report(forcedId)).plan_stage,'abandoned');
  pass('Second-player engine flow draws normally; mandatory Sangan resolves with responses disabled; draft abandonment keeps raw history');

  await page.evaluate(id=>showReport(id),silentId);await page.waitForFunction(()=>flow.draft?.saved);
  await page.locator('#delete-draft').click();assert.match(await page.locator('#flow-message').innerText(),/设置保存恢复验收/);
  await page.locator('#flow-cancel').click();assert((await request('/api/plans')).some(p=>p.id===silentId));
  await page.route('**/api/plans/delete',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'隔离删除失败'})}),{times:1});
  await page.locator('#delete-draft').click();await page.locator('#flow-confirm').click();await page.waitForFunction(()=>!flow.busy);
  assert.equal(await page.evaluate(()=>flow.draft.id),silentId);assert.match(await page.locator('#draft-message').innerText(),/当前内容已保留/);
  await page.locator('#delete-draft').click();await page.locator('#flow-confirm').click();await page.waitForFunction(()=>!flow.draft&&!flow.busy);
  assert(!(await request('/api/plans')).some(p=>p.id===silentId));
  assert.equal((await report(silentId)).plan_stage,'deleted');
  assert.deepEqual((await request(`/api/deck?id=${encodeURIComponent(source.id)}`)).deck,source.deck);
  assert((await report(forcedId)).events.length>0);
  pass('Review-page deletion confirms saved name, preserves content on failure/cancel, and deletes only the target plan');
};
