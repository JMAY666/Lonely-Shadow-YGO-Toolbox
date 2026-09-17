'use strict';
// Only the harness-owned renderer/native bridge and isolated profile are used.
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
module.exports=async function({page,nativeWait,hostWait,waitHistory,pass,evidence}){
  const request=(url,body)=>page.evaluate(({url,body})=>api(url,body),{url,body});
  const deck={main:[55144522,55144522,55144522,9742784,33420078,14558127,59438930,...Array(33).fill(1184620)],extra:[],side:[14558127]};
  const saved=await request('/api/decks',{name:`条件牌验收-${Date.now()}`,deck});
  for(const [code,level] of [[9742784,1],[33420078,2],[14558127,3],[59438930,3]]){
    const card=await request('/api/card/'+code);assert(card.type&0x1000);assert.equal(card.level&255,level);
  }
  await page.evaluate(async saved=>{
    flow.draft=null;flow.design=null;await switchModule('expansion');
    const opponent=await api('/api/opponent');
    await mountDesign({...saved,deck_name:saved.name,name:'条件牌验收',notes:'隔离测试',conditions:{hand_count:2,slots:[55144522,null],banned:[]},opponent_ai:false,opponent_responses:false,opponent_config:{...opponent,deck:saved.deck,conditions:{hand_count:1,slots:[null],banned:[]}},turn_order:'first',player_lp:8000,opponent_lp:8000,timer:{mode:'off',seconds:0}});
  },saved);
  async function edit(level){
    await page.locator('[data-slot="1"]').click();
    if(await page.locator('#condition-card-editor').isHidden())await page.locator('#choose-condition').click();
    await page.locator(`[data-condition-template="${level-1}"]`).click();
    await page.waitForFunction(()=>conditionEditor.valid&&!document.querySelector('#condition-apply').disabled);
  }
  async function apply(){await page.locator('#condition-apply').click();await page.waitForFunction(()=>flow.design&&!conditionError(flow.design));}
  async function start(){await page.locator('#begin-expansion').click();await page.waitForFunction(()=>app.active&&!flow.busy);const id=await page.evaluate(()=>app.active.id);await hostWait(id,s=>s.frame_ready);await nativeWait(id,s=>s.prompt===11);return id;}
  async function finish(){await page.locator('#finish-training').click();await waitHistory('completed');await page.waitForFunction(()=>flow.draft&&!flow.busy);}
  async function back(){await page.locator('#return-conditions').click();await page.locator('#flow-confirm').click();await page.waitForFunction(()=>flow.design&&!app.active&&!flow.busy);}
  const ids=[];
  for(const [level,code] of [[1,9742784],[2,33420078]]){
    await edit(level);assert.match(await page.locator('#condition-preview-result').innerText(),/原始匹配 1 种 \/ 1 张/);await apply();
    const id=await start();ids.push(id);const r=await request('/api/report/'+id);
    assert.deepEqual(r.expansion.actual_opening,[55144522,code]);assert.deepEqual(r.initial_hand.map(c=>c.code),r.expansion.actual_opening);
    if(level===1){
      // Exercise the old manual-condition panel before reopening the new editor.
      // Both used to share an ID; an editor-only smoke cannot catch that collision.
      await finish();await page.locator('#save-plan').click();
      await page.locator('#confirm-save-plan').waitFor({state:'visible'});
      assert.equal(await page.locator('#condition-editor').count(),1);
      assert.equal(await page.locator('#condition-card-editor').count(),1);
      await page.locator('#confirm-save-plan').click();await page.waitForFunction(id=>flow.selectedPlan===id&&!flow.busy,id);
      await page.locator('#plan-conditions').click();await page.waitForFunction(()=>flow.design&&app.view==='design');
    }else await back();
  }
  await edit(3);assert.match(await page.locator('#condition-preview-result').innerText(),/原始匹配 2 种 \/ 2 张/);
  await page.locator('[data-condition-group=""]').selectOption('any');
  await page.waitForFunction(()=>document.querySelector('#condition-preview-result').textContent.includes('原始匹配 4 种 / 4 张'));
  await page.locator('[data-condition-group=""]').selectOption('all');
  await page.locator('[data-condition-add=""][data-node-kind="not"]').click();
  await page.waitForFunction(()=>document.querySelector('#condition-preview-result').textContent.includes('没有候选'));
  await page.locator('[data-condition-field="2.0"]').selectOption('code');
  await page.locator('[data-condition-values="2.0"]').selectOption(['14558127']);
  await page.waitForFunction(()=>document.querySelector('#condition-preview-result').textContent.includes('原始匹配 1 种 / 1 张'));
  await page.screenshot({path:path.join(evidence,'condition-editor.png')});await apply();
  await page.locator('#add-opening-ban').click();await page.locator('[data-choice="59438930"]').click();
  await page.waitForFunction(()=>document.querySelector('#design-error').textContent.includes('全部排除'));
  assert(await page.locator('#begin-expansion').isDisabled());await page.locator('[data-unban="59438930"]').click();
  await page.locator('#hand-count').fill('1');await page.waitForFunction(()=>document.querySelector('#design-error').textContent.includes('超出数量'));
  await page.locator('#hand-count').fill('2');await page.waitForFunction(()=>!conditionError(flow.design));
  // A banned condition is editable and does not consume a slot.
  await page.locator('#add-opening-ban').click();await page.locator('#choose-condition').click();await page.locator('[data-condition-template="0"]').click();
  await page.waitForFunction(()=>conditionEditor.valid);await apply();
  assert.equal(await page.locator('#opening-slots [data-slot]').count(),2);assert.equal(await page.locator('[data-edit-condition-ban="0"]').count(),1);
  await page.locator('[data-edit-condition-ban="0"]').click();assert.match(await page.locator('#condition-purpose').innerText(),/禁止上手/);await page.locator('#opening-close').click();
  // Opponent gets its own condition, deck stock and real native initial hand.
  await page.locator('#opponent-ai').setChecked(true);await page.locator('[data-opponent-slot="0"]').click();await page.locator('#choose-condition').click();
  await page.locator('[data-condition-template="1"]').click();await page.waitForFunction(()=>conditionEditor.valid);await apply();
  const rules=await page.evaluate(()=>structuredClone(flow.design.conditions));
  await page.screenshot({path:path.join(evidence,'condition-design.png')});
  let id=await start();ids.push(id);let r=await request('/api/report/'+id);
  assert.deepEqual(r.expansion.actual_opening,[55144522,59438930]);assert.deepEqual(r.expansion.opponent_config.actual_opening,[33420078]);
  assert.equal(r.final_state.cards.filter(c=>c.controller===0&&c.location===1&&c.code===9742784).length,1);
  const actual=r.expansion.actual_opening;
  await page.locator('#restart-expansion').click();await page.locator('#flow-confirm').click();
  await page.waitForFunction(old=>app.active&&app.active.id!==old&&!flow.busy,id);id=await page.evaluate(()=>app.active.id);
  await hostWait(id,s=>s.frame_ready);await nativeWait(id,s=>s.prompt===11);r=await request('/api/report/'+id);
  assert.deepEqual(r.expansion.actual_opening,actual);assert.deepEqual(r.expansion.conditions,rules);
  await finish();await page.locator('#save-plan').click();await page.locator('#confirm-save-plan').click();
  await page.waitForFunction(id=>flow.selectedPlan===id&&!flow.busy,id);
  assert.match(await page.locator('#plan-report').innerText(),/条件集合/);assert.match(await page.locator('#plan-report').innerText(),/实例/);
  const exported=await request('/api/plan-export/'+id),preview=await request('/api/plans/import-preview',{document:exported});
  const imported=await request('/api/plans/import',{document:exported,fingerprint:preview.fingerprint});
  const restored=await request('/api/design/'+imported.id);assert.deepEqual(restored.conditions,rules);
  const tutorial=await page.evaluate(id=>api('/api/plan/'+id).then(plan=>{const model=buildPlanTutorial(plan);return {svg:renderPlanTutorialSvg(model),opening:model.opening,warnings:model.warnings};}),imported.id);
  assert(tutorial.opening.some(c=>c.src==='/condition-card.svg'));assert(tutorial.svg.includes('实例'));assert(tutorial.warnings.some(w=>w.includes('尚未证明可替换')));
  fs.writeFileSync(path.join(evidence,'condition-tutorial.svg'),tutorial.svg);
  await page.locator('#plan-conditions').click();await page.waitForFunction(()=>flow.design&&app.view==='design');
  assert.deepEqual(await page.evaluate(()=>flow.design.conditions),rules);
  await page.evaluate(()=>{flow.design.deck.main=flow.design.deck.main.map(c=>c===59438930?1184620:c);renderDesign();});
  await page.waitForFunction(()=>document.querySelector('#design-error').textContent.includes('没有候选'));assert(await page.locator('#begin-expansion').isDisabled());
  assert.deepEqual((await request('/api/plan/'+id)).expansion.conditions,rules);
  await page.evaluate(()=>{flow.design=null;flow.draft=null;switchView('plans');});
  fs.writeFileSync(path.join(evidence,'condition-result.json'),JSON.stringify({ids,id,imported:imported.id,actual,conditions:rules},null,2));
  pass('Condition cards: UI AND/OR/exclusion preview, level 1/2/3 tuners, bans, overflow, opponent, native real hands, frozen retry, save/share/import/tutorial and deck invalidation');
};
