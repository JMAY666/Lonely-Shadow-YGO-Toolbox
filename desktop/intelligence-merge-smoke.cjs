'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

module.exports=async({page,application,root,evidence,pass})=>{
  page.setDefaultTimeout(25000);
  const enter=async name=>{await page.locator('#module-'+name).click();await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const action=name=>page.locator(`[data-intel-action="${name}"]`).click();
  const saved=()=>page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent==='已保存。');
  const merged=()=>page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.startsWith('已合并'));
  const card=await page.evaluate(()=>api('/api/card/14558127'));
  const make=(note,effectNote)=>{
    const c={code:card.id,name:card.name,instance_id:1,controller:0,location:4,sequence:0,position:1},state={cards:[c],lp:[8000,8000]};
    return {id:crypto.randomUUID(),name:note,deck_name:'合成构筑',saved_ms:1,edit_revision:0,plan_stage:'saved',status:'completed',deck:{main:[card.id],extra:[],side:[]},catalog:{[card.id]:card},actions:[],events:[],branches:[],initial_hand:[],final_state:state,
      annotations:{nodes:{},cards:{'1':note},effects:{},final_marks:{'1':{marked:true,effects:{'0':{note:effectNote}}}}},
      review:{nodes:[{id:'initial',kind:'initial',number:1,action_ids:[],state},{id:'final',kind:'final',number:2,action_ids:[],state}]}};
  };
  const a=make('用途甲','效果备注甲'),b=make('用途乙','效果备注乙'),same=make('用途甲','效果备注甲');same.name='相同备注的另一个来源';
  const third=make('第二张卡的用途','第二张卡效果备注'),other=await page.evaluate(()=>api('/api/card/55144522'));
  third.catalog={[other.id]:other};third.deck.main=[other.id];
  for(const state of [third.final_state,...third.review.nodes.map(n=>n.state)])Object.assign(state.cards[0],{code:other.id,name:other.name});
  [a,b,same,third].forEach((plan,i)=>{plan.id=`10000000-0000-4000-8000-${String(i+1).padStart(12,'0')}`;});
  const plans=[a,b,same,third].map(plan=>({plan,file:path.join(root,'runtime/_trainer/plans',plan.id+'.json'),bytes:JSON.stringify(plan)}));
  plans.forEach(p=>fs.writeFileSync(p.file,p.bytes));
  await enter('intelligence');await action('sources');await page.locator('[data-intel-merge-card="14558127"]').waitFor();
  assert.match(await page.locator('#intel-sources').textContent(),/不同备注并列保留/);
  await page.locator('[data-intel-merge-card="14558127"]').click();await merged();
  let annotation=await page.evaluate(()=>intelUI.data.endboards[14558127]);
  assert.deepEqual(annotation.notes.map(n=>n.text),['用途甲','用途乙']);
  assert.deepEqual(annotation.effects['0'].notes.map(n=>n.text),['效果备注甲','效果备注乙']);
  assert.equal(annotation.notes[0].source_refs.length,2);
  assert.equal(await page.locator('#intel-editor [data-intel-field^="notes."]').count(),2);
  assert.equal(await page.locator('#intel-editor [data-intel-field^="effects.0.notes."]').count(),2);
  assert.match(await page.locator('#intel-editor').textContent(),/相同备注的另一个来源/);
  await page.locator('[data-intel-note-add="notes"]').click();await page.locator('[data-intel-field="notes.2.text"]').fill('手动并列用途');
  await page.route('**/api/intelligence',route=>route.request().method()==='POST'?route.fulfill({status:500,json:{error:'isolated note save failure'}}):route.continue(),{times:1});
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.includes('保存失败'));
  assert.equal(await page.locator('[data-intel-field="notes.2.text"]').inputValue(),'手动并列用途');
  await action('save');await saved();
  await action('sources');await page.locator('[data-intel-action="merge-all"]').waitFor();await action('merge-all');await merged();
  assert.equal(await page.evaluate(()=>Object.keys(intelUI.data.endboards).length),2);
  const before=await page.evaluate(()=>structuredClone(intelUI.data.endboards));
  await action('sources');await page.locator('[data-intel-action="merge-all"]').waitFor();await action('merge-all');await merged();
  assert.deepEqual(await page.evaluate(()=>intelUI.data.endboards),before);
  await page.locator('[data-intel-edit="14558127"]').click();
  await page.locator('[data-intel-field="notes.2.text"]').fill('修订后的手动用途');
  await page.locator('[data-intel-note-remove="effects.0.notes.1"]').click();
  await action('save');await saved();await page.locator('[data-intel-edit="14558127"]').click();
  assert.equal(await page.locator('[data-intel-field="notes.2.text"]').inputValue(),'修订后的手动用途');
  assert.equal(await page.locator('#intel-editor [data-intel-field^="effects.0.notes."]').count(),1);
  pass('Per-card and all-card merging deduplicate cards/notes, keep multiple provenance links, retain manual notes, allow independent editing/removal and preserve failed saves');

  for(const [width,height] of [[900,760],[1440,1000]]){
    await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(size.width,size.height),{width,height});
    await page.waitForFunction(s=>innerWidth===s.width&&innerHeight===s.height,{width,height});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.locator('#intel-editor .intel-parallel-notes').first().scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(evidence,`parallel-notes-${width}.png`),preserveScroll:true});
  }
  await action('cancel');await enter('expansion');
  await page.evaluate(plan=>{reviewUI.report=null;mountReview(plan);switchView('history');selectReviewNode('final');},a);
  await page.locator('#review-final-marks .review-card').click();await page.locator('#intel-review-apply').waitFor();
  assert.match(await page.locator('#intel-review-template').textContent(),/用途甲/);assert.match(await page.locator('#intel-review-template').textContent(),/用途乙/);
  await page.locator('#intel-review-apply').click();
  const local=await page.evaluate(()=>structuredClone(reviewEdits()));
  assert.equal(local.cards['1'],'用途甲\n\n用途乙\n\n修订后的手动用途');
  assert.deepEqual(local.final_marks['1'].effects,{'0':{note:'效果备注甲'}});
  await page.locator('#review-card-note').fill('方案中新补充的用途');await page.locator('#intel-review-scope').selectOption('shared');await page.locator('#intel-review-save').click();
  await page.waitForFunction(()=>document.querySelector('#intel-review-status').textContent.includes('通用标注已合并保存'));
  await page.evaluate(()=>{closeReviewDetail();flow.draft=null;});await enter('intelligence');
  annotation=await page.evaluate(()=>intelUI.data.endboards[14558127]);
  assert.deepEqual(annotation.notes.map(n=>n.text),['用途甲','用途乙','修订后的手动用途','方案中新补充的用途']);
  plans.forEach(p=>assert.equal(fs.readFileSync(p.file,'utf8'),p.bytes));
  pass('Parallel notes display in expansion, apply through the original scalar plan format, and shared saving adds notes without overwriting other notes or historical plans');

  const changed=make('旧文本来源','需要核对的效果备注');changed.catalog[card.id]={...card,desc:'①：合成的不同版本效果文本。'};
  const changedPath=path.join(root,'runtime/_trainer/plans',changed.id+'.json');fs.writeFileSync(changedPath,JSON.stringify(changed));
  await action('sources');await page.locator('[data-intel-merge-card="14558127"]').waitFor();await page.locator('[data-intel-merge-card="14558127"]').click();await merged();
  assert.equal(await page.locator('[data-intel-resolve-effect="0"]').count(),1);
  assert.match(await page.locator('.intel-pending-effects').textContent(),/需要核对的效果备注/);
  await page.locator('#intel-effect-target-0').selectOption('0');await page.locator('[data-intel-resolve-effect="0"]').click();
  await action('save');await saved();
  const resolved=await page.evaluate(()=>structuredClone(intelUI.data.endboards[14558127]));
  assert.equal(resolved.unmatched_effects.length,0);assert(resolved.effects['0'].notes.some(n=>n.text==='需要核对的效果备注'));
  await action('sources');await page.locator('[data-intel-merge-card="14558127"]').waitFor();await page.locator('[data-intel-merge-card="14558127"]').click();await merged();
  assert.deepEqual(await page.evaluate(()=>intelUI.data.endboards[14558127]),resolved,'Repeated source merging cannot undo manual resolution or restore deleted notes');
  await action('cancel');
  pass('Different effect texts retain pending notes, can be explicitly assigned after review, and repeated merges preserve manual resolution and removals');
};
