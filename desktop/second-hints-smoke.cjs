'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

module.exports=async function({page,application,evidence,pass}){
  const seeded=await page.evaluate(async()=>{
    await startNewDuel();const owner=duelState();
    const deck=await api('/api/decks',{name:'TEST ONLY 条件提示 '+crypto.randomUUID(),
      deck:{main:[14558127,10045474,59438930,...Array(37).fill(1184620)],extra:[],side:[]}});
    owner.operationMode='manual';owner.mode='BO1';owner.secondOrder=true;owner.deck=deck;
    owner.hand=[14558127,10045474,59438930,1184620,1184620];owner.count=5;
    await startSecondDuel(false);
    let doc=secondWorkspace().doc;
    const record=async(kind,payload)=>{doc=await api('/api/second-duel/event',SecondDuelModel.event(doc,kind,payload,crypto.randomUUID().replaceAll('-','')));};
    for(const c of doc.current.cards.filter(c=>c.location===2&&[14558127,10045474,59438930].includes(c.code))){
      const effect={14558127:'ash.negate',10045474:'imperm.negate',59438930:'ogre.destroy'}[c.code];
      await record('effect_count',{card_id:c.id,effect_id:effect,status:'unused'});
      await record('resource_role',{card_id:c.id,role:'free'});
    }
    await record('opponent_card',{code:62962630,known:true,location:4,position:1,sequence:0});
    secondWorkspace().doc=doc;renderDuel();return {opening:doc.input.opening,hand:doc.current.hand};
  });
  const submit=async selector=>{const revision=await page.evaluate(()=>secondWorkspace().doc.revision);
    await page.locator(selector+' button[type="submit"]').click();
    await page.waitForFunction(n=>secondWorkspace().doc.revision>n&&!secondUI.busy,revision);
  };
  await page.locator('#second-verify-form [name="phase"]').selectOption('main1');
  await page.locator('#second-verify-form [name="confirmed"]').check();await submit('#second-verify-form');
  await page.locator('.second-hint-setup>summary').filter({hasText:'填写结构化'}).click();
  const form=page.locator('#second-hint-window-form');
  await form.locator('[name="link"]').fill('1');await form.locator('[name="top"]').fill('1');
  await form.locator('[name="speed"]').selectOption('1');await form.locator('[name="other_rules"]').selectOption('none');
  await form.locator('[name="grave_rule"]').selectOption('normal');await form.locator('[name="protections_checked"]').check();
  await form.locator('[name="environment"]').selectOption('local');await form.locator('[name="confirmed"]').check();
  await submit('#second-hint-window-form');
  await page.locator('[data-second-action="generate-hint"]').click();
  await page.waitForFunction(()=>!!secondWorkspace().doc.advice&&!secondUI.busy,null,{timeout:60000});
  const hint=await page.evaluate(()=>secondWorkspace().doc.advice);
  assert.equal(hint.engine_proof.status,'matched',JSON.stringify(hint.engine_proof));
  const item=code=>hint.items.find(r=>r.code===code);
  assert.equal(item(14558127).recommendation,'hold');assert.equal(item(10045474).recommendation,'use');assert.equal(item(59438930).recommendation,'hold');
  assert.equal(await page.locator('#second-hints>.second-hint-items>.second-hint-item').count(),3);
  const before=await page.evaluate(()=>structuredClone(secondWorkspace().doc.current));
  await page.locator(`[data-second-hint-choice="use"][data-card="${item(10045474).instance_id}"]`).click();
  await page.waitForFunction(()=>secondWorkspace().doc.advice.decisions.length===1&&!secondUI.busy);
  assert.deepEqual(await page.evaluate(()=>secondWorkspace().doc.current),before);
  assert.deepEqual(await page.evaluate(()=>secondWorkspace().doc.input.opening),seeded.opening);
  await page.screenshot({path:path.join(evidence,'second-hints-comparison.png')});
  pass('Conditional hints use matching native resources; Aluber comparisons preserve Ash when Impermanence is available; selecting a plan spends no cards');

  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(900,650));
  await page.waitForFunction(()=>innerWidth===900);
  await page.locator('#second-hints>.second-hint-items>.second-hint-item').first().locator('summary').click();
  assert(await page.locator('#second-workspace').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.screenshot({path:path.join(evidence,'second-hints-narrow.png')});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  const staleRequest=await page.evaluate(()=>({id:secondWorkspace().doc.id,round_id:secondWorkspace().doc.input.round_id,
    revision:secondWorkspace().doc.revision,request_id:crypto.randomUUID().replaceAll('-',''),advice_id:secondWorkspace().doc.advice.id,
    card_id:secondWorkspace().doc.advice.items.find(r=>r.code===10045474).instance_id,choice:'use'}));
  await page.locator('.second-hint-setup>summary').filter({hasText:'核对次数和后攻'}).click();
  const ash=await page.evaluate(()=>secondWorkspace().doc.current.cards.find(c=>c.location===2&&c.code===14558127).id);
  await page.locator('#second-effect-observed-form [name="card_id"]').selectOption(ash);
  await page.locator('#second-effect-observed-form [name="effect_id"]').selectOption('ash.negate');
  await page.locator('#second-effect-observed-form [name="confirmed"]').check();await submit('#second-effect-observed-form');
  await page.locator('.second-hint-setup>summary').filter({hasText:'核对次数和后攻'}).click();
  await page.locator('#second-effect-outcome-form [name="outcome"]').selectOption('activation_negated');await submit('#second-effect-outcome-form');
  assert.equal(await page.evaluate(()=>secondWorkspace().doc.current.effect_counts['0:ash.1'].status),'used');
  assert.equal(await page.evaluate(()=>secondWorkspace().doc.current.hand.length),5,'Effect bookkeeping does not fabricate cost movement');
  pass('UI links a later resolution to its recorded activation; Ash usage remains spent after activation negation and costs stay separately observed');
  await page.evaluate(async()=>{
    const doc=secondWorkspace().doc,c=doc.current.cards.find(c=>c.location===2&&c.code===10045474);
    await secondSubmit('move',{card_id:c.id,from:2,to:16,reason:'effect',note:'TEST ONLY actual reported result'});
  });
  assert.equal(await page.evaluate(()=>secondWorkspace().doc.advice.current),false);
  assert.equal(await page.locator('[data-second-hint-choice]').count(),0);
  const error=await page.evaluate(async body=>{try{await api('/api/second-duel/advice-choice',body);return '';}catch(error){return error.message;}},staleRequest);
  assert.match(error,/局面已变化/);
  assert.equal(await page.evaluate(()=>secondWorkspace().doc.advice_history.length),1);
  assert.equal(await page.evaluate(()=>secondWorkspace().doc.current.hand.length),4);
  pass('Actual observation invalidates earlier hints without rewriting the opening, advice, planned choice or known-at-the-time history; narrow comparisons fit');
  await page.locator('[data-second-action="close"]').click();await page.waitForFunction(()=>secondWorkspace().doc.closed&&!secondUI.busy);
};
