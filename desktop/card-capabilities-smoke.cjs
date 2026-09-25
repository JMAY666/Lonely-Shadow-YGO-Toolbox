'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

module.exports=async({page,application,root,evidence,pass})=>{
  const enter=async name=>{await require('./navigation-test.cjs')(page,name);await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const codes=Object.keys(JSON.parse(fs.readFileSync(path.join(__dirname,'../src/trainer/card-annotations.json'),'utf8')).cards).map(Number);
  let projected=0;
  for(let offset=0;offset<codes.length;offset+=100){
    const result=await page.evaluate(cards=>api('/api/capabilities',{cards:cards.map(code=>({code}))}),codes.slice(offset,offset+100));
    projected+=Object.keys(result.cards).length;
    assert(Object.values(result.cards).every(row=>row.trusted&&row.version.length===64));
  }
  assert.equal(projected,codes.length);
  pass(`All ${projected} current annotations project through the shared API without mutating personal data`);

  await enter('decks');
  await page.locator('[data-create-deck]').click();
  await page.locator('#create-blank-mode').click();
  await page.locator('#import-name').fill('统一卡片能力隔离验收');
  await page.locator('#import-apply').click();
  await page.waitForFunction(()=>app.deckPage==='editor'&&!app.busy);
  await page.evaluate(async()=>{setLibraryOpen(true);await showCard(14558127);});
  await page.waitForSelector('#deck-card-capabilities [data-capability-card="14558127"]');
  await page.locator('#deck-card-capabilities > details > summary').click();
  assert.match(await page.locator('#deck-card-capabilities').textContent(),/次数|费用/);
  await page.locator('#filter-effect').selectOption('etag:negate-effect');
  await page.waitForFunction(()=>document.querySelector('#search-results').getAttribute('aria-busy')==='false');
  assert(await page.locator('#search-results [data-detail]').count()>0);
  const hits=await page.evaluate(()=>api('/api/cards?effect_tag=etag%3Anegate-effect&purpose_candidate=handtraps'));
  assert(hits.cards.some(card=>card.id===14558127));
  await page.screenshot({path:path.join(evidence,'capability-deck.png')});
  pass('Deck editor displays shared effect facts and filters by reviewed abilities');

  await page.evaluate(async()=>{
    const data=await api('/api/intelligence');
    await api('/api/intelligence',{revision:data.revision,op:'handtrap.save',value:{code:14558127,note:'保留个人用途',condition:'保留个人条件',effects:{}}});
  });
  await enter('intelligence');
  await page.locator('[data-intel-tab="handtraps"]').click();
  await page.locator('[data-intel-edit="14558127"]').click();
  await page.waitForSelector('#intel-editor [data-capability-card="14558127"]');
  await page.locator('#intel-editor .capability-panel > summary').click();
  const adopt=page.locator('#intel-editor [data-capability-select]').first();
  await adopt.locator('xpath=ancestor::details[1]/summary').click();
  const legacy=await adopt.getAttribute('data-capability-select');
  await adopt.click();
  assert.equal(await page.evaluate(key=>!!intelUI.draft.effects[key],legacy),true);
  assert.equal(await page.locator('[data-intel-field="note"]').inputValue(),'保留个人用途');
  await page.locator('[data-intel-action="save"]').click();
  await page.waitForFunction(()=>!intelUI.busy&&!intelUI.dirty);
  const personal=await page.evaluate(()=>api('/api/intelligence'));
  assert.equal(personal.handtraps['14558127'].note,'保留个人用途');
  assert.equal(Object.keys(personal.handtraps['14558127'].effects).length,1);

  await page.locator('[data-intel-edit="14558127"]').click();
  await page.waitForSelector('#intel-editor .capability-panel');
  await page.locator('#intel-editor .capability-panel > summary').click();
  await page.locator('#intel-editor [data-capability-open="14558127"]').last().click();
  await page.waitForFunction(()=>annoUI.detail?.code===14558127&&!annoUI.busy);
  await page.locator('#anno-edit-toggle').click();
  await page.locator('[data-anno-note-input="m1"]').fill('跨模块同步验收备注');
  await page.locator('[data-anno-note="m1"]').click();
  await page.waitForFunction(()=>!annoUI.busy&&annoUI.detail.effects.some(e=>e.notes?.some(n=>n.text==='跨模块同步验收备注')));
  await enter('intelligence');
  await page.locator('[data-intel-edit="14558127"]').click();
  await page.waitForFunction(()=>document.querySelector('#intel-editor .capability-panel')?.textContent.includes('跨模块同步验收备注'));
  assert.equal(await page.locator('[data-intel-field="note"]').inputValue(),'保留个人用途');
  await page.locator('#intel-editor .capability-panel > summary').click();
  await page.locator('#intel-editor .capability-effect').filter({has:page.locator('[data-capability-key="m1"]')}).locator('summary').click();
  await page.screenshot({path:path.join(evidence,'capability-intelligence.png')});
  pass('Explicit purpose adoption preserves personal notes; an annotation edited once refreshes the other module');

  await enter('tags');
  await page.locator('[data-managed-tag]').first().click();
  await page.locator('#tag-add-effect').selectOption('etag:negate-effect');
  await page.waitForFunction(()=>tagManagerUI.results.length>0);
  assert(await page.locator('#tag-add-results .tag-card-tile').count()>0);
  pass('TAG management searches reviewed effects without changing membership');

  const saved=await page.evaluate(async()=>api('/api/decks',{name:'能力起手隔离验收',deck:{main:[14558127,...Array(39).fill(1184620)],extra:[],side:[]}}));
  const input={deck_id:saved.id,revision:saved.revision,hand:[14558127,1184620,1184620,1184620,1184620]};
  const opening=await page.evaluate(input=>api('/api/opening/analyze',input),input);
  assert(opening.capabilities['14558127'].trusted);
  assert.match(JSON.stringify(opening.capabilities['14558127']),/跨模块同步验收备注/);
  assert.equal(opening.handtrap_count,1);
  const old=await page.evaluate(()=>api('/api/capabilities',{op:'card',code:14558127,text:'历史不同卡文'}));
  assert.equal(old.status,'mismatch');assert.equal(old.effects.length,0);
  const unknown=await page.evaluate(()=>api('/api/capabilities',{op:'card',code:483}));
  assert.equal(unknown.status,'none');assert.equal(unknown.trusted,false);
  const snapshot=opening.capabilities['14558127'];
  await page.evaluate(snapshot=>{
    const node=document.createElement('div');node.id='capability-frozen-check';document.body.append(node);
    return mountCapabilities(node,snapshot.code,{historical:true,snapshot});
  },snapshot);
  const before=await page.locator('#capability-frozen-check').innerHTML();
  await page.evaluate(()=>document.dispatchEvent(new CustomEvent('card-annotations-changed')));
  assert.equal(await page.locator('#capability-frozen-check').innerHTML(),before);
  await page.locator('#capability-frozen-check').evaluate(el=>el.remove());
  pass('Opening analysis uses shared facts; changed card text, unknown cards and frozen historical references stay distinct');
  return {input,version:snapshot.version};
};
