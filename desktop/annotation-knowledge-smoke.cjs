'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

module.exports=async({page,application,root,evidence,pass})=>{
  const enter=async name=>{await require('./navigation-test.cjs')(page,name);await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const hand=[14558127,1184620,1184620,1184620,1184620];
  const saved=await page.evaluate(async()=>api('/api/decks',{name:'标注驱动升级验收 '+Date.now(),deck:{main:[14558127,...Array(39).fill(1184620)],extra:[],side:[]}}));
  const input={deck_id:saved.id,revision:saved.revision,hand};
  const profile=path.join(root,'runtime','_trainer');
  assert(profile.startsWith(path.join(path.resolve(__dirname,'..'),'.local')+path.sep));
  const tagFile=path.join(profile,'tag-library.json');
  const previous=JSON.parse(fs.readFileSync(tagFile,'utf8'));
  delete previous.intelligence.annotation_sync;
  const old=previous.intelligence.handtraps['14558127'];
  delete old.managed_by;
  Object.assign(old,{note:'升级前个人旧用途',condition:'升级前旧条件',effects:{'0':{note:'旧效果说明'}}});
  previous.revision+=10;
  fs.writeFileSync(tagFile,JSON.stringify(previous));
  const legacy=await page.evaluate(input=>api('/api/opening/analyze',input),input);
  const effect=legacy.knowledge.find(row=>row.code===14558127);
  await page.evaluate(({input,legacy,effect})=>api('/api/opening/save',{action:'override',input,revision:legacy.revision,
    source_version:legacy.source_version,key:effect.key,version:effect.version,value:{roles:[],priority:'secondary',note:'旧个人角色覆盖'}}),{input,legacy,effect});
  assert.equal((await page.evaluate(input=>api('/api/opening/analyze',input),input)).handtrap_count,0);
  const openingFile=path.join(profile,'opening-analysis-v1.json');
  const previousOpening=JSON.parse(fs.readFileSync(openingFile,'utf8'));
  await page.reload();
  await page.waitForFunction(()=>app.token&&document.querySelector('#resource-count').textContent.includes('张卡牌'));
  const current=await page.evaluate(()=>api('/api/intelligence'));
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(profile,'backups','tags',previous.revision+'.json'),'utf8')),previous);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(profile,'backups','opening-analysis',previousOpening.revision+'.json'),'utf8')),previousOpening);
  assert.equal(current.handtraps['14558127'].managed_by,'card-annotations');
  assert.notEqual(current.handtraps['14558127'].note,'升级前个人旧用途');
  assert(!current.handtraps['14558127'].condition.includes('升级前'));
  assert.deepEqual(current.handtraps['14558127'].effect_keys,['m1']);
  const regenerated=await page.evaluate(input=>api('/api/opening/analyze',input),input);
  assert.equal(regenerated.handtrap_count,1);
  assert(regenerated.knowledge.some(row=>row.key==='14558127:m1'&&row.roles.includes('handtrap')));
  assert(!regenerated.knowledge.some(row=>row.key==='14558127:①'));
  pass(`Startup replaces legacy personal content and opening overrides with backed-up canonical libraries (${current.annotation_sync.counts.handtraps} handtraps, ${current.annotation_sync.counts.breakers} breakers, ${current.annotation_sync.counts.endboards} endboards)`);

  await enter('intelligence');
  await page.locator('[data-intel-tab="handtraps"]').click();
  await page.locator('#intel-filter-q').fill('14558127');
  await page.locator('[data-intel-edit="14558127"]').click();
  await page.waitForSelector('#intel-managed-effects .capability-panel');
  assert.equal(await page.locator('#intel-editor [data-intel-field="note"],#intel-editor .effect-mark').count(),0);
  assert.equal(await page.locator('[data-intel-action="import-staples"]').count(),0);
  assert.equal(await page.locator('[data-intel-action="sync-annotations"]').count(),1);
  await page.locator('#intel-managed-effects .capability-effect > summary').click();
  await page.screenshot({path:path.join(evidence,'annotation-driven-handtrap.png')});
  await page.locator('#intel-editor .intel-editor-actions [data-capability-open]').click();
  await page.waitForFunction(()=>annoUI.detail?.code===14558127&&!annoUI.busy);
  await page.locator('#anno-edit-toggle').click();
  await page.locator('[data-anno-note-input="m1"]').fill('统一标注直接更新旧功能');
  await page.locator('[data-anno-note="m1"]').click();
  await page.waitForFunction(()=>!annoUI.busy&&annoUI.detail.effects.some(e=>e.notes?.some(n=>n.text==='统一标注直接更新旧功能')));
  await enter('intelligence');
  await page.locator('#intel-filter-q').fill('14558127');
  await page.locator('[data-intel-edit="14558127"]').click();
  await page.waitForFunction(()=>document.querySelector('#intel-managed-effects')?.textContent.includes('统一标注直接更新旧功能'));
  const updated=await page.evaluate(()=>api('/api/intelligence'));
  assert(updated.handtraps['14558127'].effects['1'].note.includes('统一标注直接更新旧功能'));
  const updatedOpening=await page.evaluate(input=>api('/api/opening/analyze',input),input);
  assert(updatedOpening.knowledge.find(row=>row.key==='14558127:m1').explanation.some(text=>text.includes('统一标注直接更新旧功能')));
  pass('The primary purpose editor now uses canonical effects; one annotation edit changes existing purpose content and opening explanations');

  await enter('tags');
  await page.locator('[data-managed-tag="purpose:handtrap"]').click();
  await page.waitForFunction(()=>tagManagerUI.selected==='purpose:handtrap'&&!tagManagerUI.busy);
  assert.equal(await page.locator('#tag-manager-save').isDisabled(),true);
  assert.equal(await page.locator('.tag-add-section').isVisible(),false);
  assert.equal(await page.evaluate(()=>tagManagerUI.members.size),Object.keys(updated.handtraps).length);
  pass('Purpose TAG membership is generated from the same classification and cannot fork into a second list');

  await enter('duel');
  for(const action of ['bo1','manual']){await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);}
  await page.locator(`[data-duel-deck="${saved.id}"]`).click();await page.waitForFunction(()=>!duelUI.busy);
  for(const action of ['start-duel','second']){await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);}
  for(const code of hand)await page.locator(`[data-duel-add="${code}"]`).click();
  await page.locator('[data-opening-analyze]').click();
  await page.waitForFunction(()=>openingDuelState().result&&!openingDuelState().busy);
  assert.equal(await page.evaluate(()=>openingDuelState().result.handtrap_count),1);
  assert.match(await page.locator('.opening-hand-roles').innerText(),/手坑/);
  await page.screenshot({path:path.join(evidence,'annotation-driven-opening.png')});
  pass('The existing opening summary and handtrap count are driven by canonical roles, overriding the old zero-count personal selection');

  await enter('intelligence');
  for(const kind of ['endboards','breakers']){
    await page.locator(`[data-intel-tab="${kind}"]`).click();
    await page.waitForSelector('#intel-managed-effects .capability-panel');
    assert.equal(await page.locator('#intel-editor .effect-mark').count(),0);
  }
  for(const [width,height] of [[960,800],[680,800]]){
    await application.evaluate(({BrowserWindow},size)=>{const window=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());window.setMinimumSize(0,0);window.setContentSize(...size);},[width,height]);
    await page.waitForFunction(width=>innerWidth===width,width);
    assert(await page.locator('#intelligence').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
    await page.screenshot({path:path.join(evidence,`annotation-driven-layout-${width}.png`)});
  }
  await application.evaluate(({BrowserWindow})=>{const window=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());window.setMinimumSize(900,650);window.setContentSize(1280,900);});
  pass('Endboard and breaker primary editors use unified facts, including narrow 960/680 layouts');
  await page.locator('[data-intel-tab="handtraps"]').click();
  await page.locator('[data-intel-action="add"]').click();
  await page.locator('#intel-pick-q').fill('14558127');
  await page.waitForFunction(()=>document.querySelector('#intel-picker-status').textContent.includes('没有匹配'));
  await page.locator('#intel-pick-q').fill('483');
  await page.locator('[data-intel-choose="483"]').click();
  await page.locator('[data-intel-field="note"]').fill('未标注卡的人工补充');
  await page.locator('[data-intel-action="save"]').click();
  await page.waitForFunction(()=>!intelUI.busy&&!intelUI.dirty);
  assert.equal((await page.evaluate(()=>api('/api/intelligence'))).handtraps['483'].note,'未标注卡的人工补充');
  pass('Unannotated cards retain a manual fallback; the fallback picker cannot duplicate a canonically managed card');
  return {input,version:updatedOpening.capabilities['14558127'].version};
};
