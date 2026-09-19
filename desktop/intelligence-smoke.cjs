'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

module.exports=async({page,application,root,evidence,pass})=>{
  page.setDefaultTimeout(25000);
  const enter=async name=>{await page.locator('#module-'+name).click();await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const action=name=>page.locator(`[data-intel-action="${name}"]`).click();
  const field=name=>page.locator(name==='note'?'[data-intel-field="note"],[data-intel-field="notes.0.text"]':`[data-intel-field="${name.startsWith('effects.')?name.replace(/\.note$/,'.notes.0.text'):name}"]`);
  const tab=async name=>{await page.locator(`[data-intel-tab="${name}"]`).click();await page.waitForFunction(name=>intelUI.tab===name,name);};
  const save=async()=>{await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.draft&&document.querySelector('#intel-status').textContent==='已保存。');};
  const queryPicker=async code=>{await page.locator('#intel-pick-q').fill(String(code));await page.locator(`[data-intel-choose="${code}"]`).waitFor();};
  const pick=async code=>{await queryPicker(code);await page.locator(`[data-intel-choose="${code}"]`).click();};
  await enter('intelligence');
  const nav=await page.locator('#module-intelligence').boundingBox(),settings=await page.locator('#app-settings').boundingBox();
  assert(settings.y>nav.y&&settings.y-nav.y-nav.height<=12);
  assert.match(await page.locator('#intel-list').textContent(),/没有匹配/);

  await action('add');await pick(14558127);await field('note').fill('通用用途验收');
  await page.locator('[data-intel-effect="0"]').check();await field('effects.0.note').fill('效果用途验收');await save();
  await page.locator('[data-intel-edit="14558127"]').click();await field('note').fill('失败时保留的输入');
  await page.route('**/api/intelligence',route=>route.request().method()==='POST'?route.fulfill({status:500,json:{error:'isolated save failure'}}):route.continue(),{times:1});
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.includes('保存失败'));
  assert.equal(await field('note').inputValue(),'失败时保留的输入');
  await enter('home');await enter('intelligence');assert.equal(await field('note').inputValue(),'失败时保留的输入');await save();
  await page.locator('[data-intel-edit="14558127"]').click();await field('note').fill('失败时保留的输入');
  await page.evaluate(async()=>{const d=await api('/api/intelligence');await api('/api/intelligence',{revision:d.revision,op:'endboard.save',value:{...d.endboards[14558127],note:'其他入口的新版本'}});});
  await action('save');await page.locator('[data-intel-action="reload-keep"]').waitFor();await action('reload-keep');await page.locator('#intel-conflict').waitFor();
  assert.match(await page.locator('#intel-conflict').textContent(),/其他入口的新版本/);assert.equal(await field('note').inputValue(),'失败时保留的输入');
  await action('accept-latest');await save();
  const catalog=await page.evaluate(async()=>Object.fromEntries(await Promise.all([14558127,23995346,55144522,1184620].map(async id=>[id,await card(id)]))));
  const report=id=>{const c={code:14558127,name:catalog[14558127].name,instance_id:1,controller:0,location:4,sequence:2,position:1};const state={cards:[c],lp:[8000,8000]};return {id,name:'情报站合成来源 '+id.slice(0,4),plan_stage:'saved',status:'completed',edit_revision:0,saved_ms:1,deck_name:'合成构筑',deck:{main:[14558127],extra:[],side:[]},events:[],actions:[],initial_hand:[],final_state:state,catalog,branches:[],annotations:{nodes:{},cards:{'1':'历史实例备注'},effects:{},final_marks:{'1':{marked:true,effects:{'0':{note:'历史效果'}}}}},review:{nodes:[{id:'initial',kind:'initial',number:1,action_ids:[],state},{id:'final',kind:'final',number:2,action_ids:[],state}]}};};
  const first=report(crypto.randomUUID()),second=report(crypto.randomUUID());
  second.annotations.cards['1']='另一方案的备注';
  const plans=[first,second].map(r=>({file:path.join(root,'runtime/_trainer/plans',r.id+'.json'),bytes:JSON.stringify(r)}));
  plans.forEach(p=>fs.writeFileSync(p.file,p.bytes));
  const mount=async r=>{await enter('expansion');await page.evaluate(r=>{reviewUI.report=null;mountReview(r);switchView('history');selectReviewNode('final');},r);await page.locator('#review-final-marks .review-card').click();await page.locator('#intel-review-apply').waitFor();};
  await mount(first);await page.locator('#intel-review-apply').click();await page.locator('#review-card-note').fill('仅方案 A');
  assert.equal(await page.evaluate(()=>reviewEdits().cards['1']),'仅方案 A');
  await page.locator('#intel-review-scope').selectOption('local');await page.locator('#intel-review-save').click();
  assert.equal(await page.evaluate(async()=>(await api('/api/intelligence')).endboards[14558127].note),'失败时保留的输入');
  await page.locator('#intel-review-scope').selectOption('shared');await page.locator('#intel-review-save').click();
  await page.waitForFunction(()=>document.querySelector('#intel-review-status').textContent.includes('通用标注已合并保存'));
  await page.evaluate(()=>closeReviewDetail());await mount(second);await page.locator('#intel-review-apply').click();
  assert.equal(await page.evaluate(()=>reviewEdits().cards['1']),'失败时保留的输入\n\n仅方案 A');
  await page.locator('#review-card-note').fill('仅方案 B');
  assert.equal(await page.evaluate(async()=>(await api('/api/intelligence')).endboards[14558127].note),'失败时保留的输入\n\n仅方案 A');
  await page.evaluate(()=>{closeReviewDetail();flow.draft=null;});await enter('intelligence');
  await page.locator('[data-intel-edit="14558127"]').click();assert.equal(await page.locator('[data-intel-field="notes.1.text"]').inputValue(),'仅方案 A');await action('cancel');
  await action('sources');await page.locator('#intel-sources summary').waitFor();assert.equal(await page.locator('#intel-sources details').count(),1);
  await page.locator('#intel-sources summary').click();assert.equal(await page.locator('[data-intel-import]').count(),2);
  await page.locator('[data-intel-import]').first().click();await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.startsWith('已合并'));
  await action('cancel');plans.forEach(p=>assert.equal(fs.readFileSync(p.file,'utf8'),p.bytes));
  pass('General marks copy into distinct instances, save from either entry, preserve plan-only edits and historical files, and import conflicting sources separately');

  await tab('handtraps');await action('folder-new');await field('name').fill('常用手坑');await save();
  const folder=await page.evaluate(()=>Object.keys(intelUI.data.folders)[0]);await page.locator('#intel-folder').selectOption(folder);
  await action('add');await page.locator('#intel-pick-q').fill('23995346');
  await page.waitForFunction(()=>document.querySelector('#intel-picker-status').textContent.includes('没有匹配'));
  await pick(14558127);await field('note').fill('手坑用途');await field('condition').fill('按效果规定的时点');
  await page.locator('[data-intel-effect="1"]').check();await field('effects.1.note').fill('对应检索、特召或送墓效果');
  await page.locator('[data-intel-note-add="effects.1.notes"]').click();await field('effects.1.notes.1.text').fill('分别核对发动时点');
  await page.locator('[data-intel-effect="0"]').check();await field('effects.0.note').fill('临时文本备注');await save();
  await action('add');await pick(14558127);assert.equal(await field('note').inputValue(),'手坑用途');
  assert(await page.locator('[data-intel-effect="1"]').isChecked());assert.equal(await field('effects.1.notes.1.text').inputValue(),'分别核对发动时点');
  await page.locator('[data-intel-effect="0"]').uncheck();assert.equal(await field('effects.0.note').count(),0);
  await page.locator('[data-intel-note-remove="effects.1.notes.0"]').click();assert.equal(await field('effects.1.note').inputValue(),'分别核对发动时点');
  await field('effects.1.note').fill('手坑效果独立备注');
  await page.locator('[data-intel-note-add="effects.1.notes"]').click();await field('effects.1.notes.1.text').fill('另一条适用条件');
  await page.route('**/api/intelligence',route=>route.request().method()==='POST'?route.fulfill({status:500,json:{error:'isolated handtrap save failure'}}):route.continue(),{times:1});
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.includes('保存失败'));
  await enter('home');await enter('intelligence');assert.equal(await field('effects.1.note').inputValue(),'手坑效果独立备注');await save();
  assert.deepEqual(await page.evaluate(()=>Object.keys(intelUI.data.handtraps[14558127].effects)),['1']);
  assert.equal(await page.evaluate(()=>intelUI.data.handtraps[14558127].effects['1'].note),'手坑效果独立备注\n\n另一条适用条件');
  assert.match(await page.locator('[data-intel-edit="14558127"]').textContent(),/1 个效果 · 2 条效果备注/);
  assert.doesNotMatch(await page.evaluate(()=>JSON.stringify(intelUI.data.endboards[14558127])),/手坑效果独立备注/);
  assert.equal(await page.evaluate(()=>Object.keys(intelUI.data.handtraps).length),1);
  assert.equal((await page.evaluate(()=>api('/api/tag-members/purpose%3Ahandtrap'))).cards.length,1);
  await page.locator('.intel-filter-more summary').click();await page.locator('#intel-filter-kind').selectOption('spell');assert.match(await page.locator('#intel-list').textContent(),/没有匹配/);
  await page.locator('[data-intel-clear="intel-filter"]').click();await page.locator('#intel-filter-tag').selectOption('purpose:handtrap');await page.locator('#intel-filter-q').fill('14558127');assert.equal(await page.locator('[data-intel-edit="14558127"]').count(),1);
  await page.locator('[data-intel-clear="intel-filter"]').click();await page.locator('#intel-folder').selectOption(folder);await action('folder-remove');await page.locator('#flow-confirm').click();await page.waitForFunction(()=>!intelUI.busy&&!Object.keys(intelUI.data.folders).length);
  await page.locator('#intel-folder').selectOption('ungrouped');await page.locator('[data-intel-edit="14558127"]').click();assert.equal(await field('note').inputValue(),'手坑用途');
  assert.equal(await field('effects.1.note').inputValue(),'手坑效果独立备注');await action('cancel');
  await enter('tags');await page.waitForFunction(()=>tagManagerUI.loaded);await page.locator('#tag-manager-search').fill('手坑');await page.locator('[data-managed-tag="purpose:handtrap"]').click();
  await page.waitForFunction(()=>tagManagerUI.selected==='purpose:handtrap'&&!tagManagerUI.busy);
  assert(await page.locator('#tag-manager-name').getAttribute('readonly')!==null);
  await page.locator('#tag-add-search').fill('55144522');await page.locator('#tag-add-results [data-member-add="55144522"]').click();await page.locator('#tag-manager-save').click();await page.waitForFunction(()=>!tagManagerUI.busy&&!tagManagerUI.dirty);
  await enter('intelligence');assert.equal(await page.evaluate(()=>Object.keys(intelUI.data.handtraps).length),2);
  await page.locator('[data-intel-edit="14558127"]').click();assert.equal(await field('effects.1.notes.1.text').inputValue(),'另一条适用条件');
  await field('effects.1.note').fill('将取消的修改');await action('cancel');await page.locator('#flow-confirm').click();
  await page.locator('[data-intel-edit="14558127"]').click();assert.equal(await field('effects.1.note').inputValue(),'手坑效果独立备注');await action('cancel');
  pass('Hand-trap effects and parallel notes support selection, removal, editing, cancellation and failed-save recovery, remain independent from endboard notes and survive folder/TAG edits');
  pass('Hand-trap picker rejects extra-deck cards, accepts main-deck spells through TAG management, deduplicates members, composes filters and preserves notes when deleting folders');

  await tab('records');await action('topic-new');await field('name').fill('对局时点验收');await field('tag_ids').selectOption('purpose:handtrap');await save();
  await action('add');await field('title').fill('对手操作与多个选项');await page.locator('[data-intel-pick="steps.0.opponent"]').click();await pick(23995346);
  await field('steps.0.action').fill('对手发动效果');await field('steps.0.timing').fill('效果发动时');await field('steps.0.condition').fill('已核对局面条件');
  await page.locator('[data-intel-response-add="0"]').click();await page.locator('[data-intel-pick="steps.0.responses.0.cards"]').click();await pick(14558127);
  await field('steps.0.responses.0.method').fill('可选方式 A');await field('steps.0.responses.0.condition').fill('满足该卡条件');await field('steps.0.responses.0.expected').fill('用户预期作用');
  await page.locator('[data-intel-response-add="0"]').click();await field('steps.0.responses.1.mode').selectOption('combination');
  for(const code of [55144522,1184620]){await page.locator('[data-intel-pick="steps.0.responses.1.cards"]').click();await page.locator('#intel-picker-scope').selectOption('all');await pick(code);}
  await field('steps.0.responses.1.method').fill('组合方式 B');await field('steps.0.responses.1.condition').fill('需要两张配合');await field('steps.0.responses.1.expected').fill('用户预期组合作用');
  await action('step-add');await field('steps.1.action').fill('后续操作待补充');await page.locator('[data-intel-step-up="1"]').click();
  assert.equal(await field('steps.0.action').inputValue(),'后续操作待补充');await field('note').fill('记录备注');await save();
  const id=await page.evaluate(()=>Object.keys(intelUI.data.records)[0]);await page.locator(`[data-intel-edit="${id}"]`).click();
  assert.equal(await field('steps.1.responses.1.mode').inputValue(),'combination');assert.equal(await page.locator('.intel-step').count(),2);assert.match(await page.locator('#intel-editor').textContent(),/待补充.*手动策略/s);
  assert.equal(await page.evaluate(()=>Object.keys(intelUI.data.handtraps).length),2,'Breakpoint selection never adds unrelated cards to the hand-trap library');
  for(const [width,height] of [[900,700],[1440,1000]]){
    await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(size.width,size.height),{width,height});
    await page.waitForFunction(s=>innerWidth===s.width&&innerHeight===s.height,{width,height});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(evidence,`intelligence-timeline-${width}.png`)});
  }
  await action('cancel');await page.locator('#intel-filter-q').fill('23995346');assert.equal(await page.locator(`[data-intel-edit="${id}"]`).count(),1);
  await page.locator('#intel-filter-tag').selectOption('purpose:handtrap');assert.equal(await page.locator(`[data-intel-edit="${id}"]`).count(),1);
  pass('Breakpoint timeline preserves ordered opponent operations, independent options, explicit combinations, conditions, notes, theme/TAG/card search and pending status at 900px and 1440px');
  await tab('handtraps');await page.locator('[data-intel-edit="55144522"]').click();await action('remove');await page.locator('#flow-confirm').click();await page.waitForFunction(()=>!intelUI.busy&&!intelUI.data.handtraps[55144522]);
  assert(!(await page.evaluate(()=>api('/api/tag-members/purpose%3Ahandtrap'))).cards.some(c=>c.id===55144522));
  await tab('endboards');await page.locator('[data-intel-edit="14558127"]').click();await action('remove');await page.locator('#flow-confirm').click();await page.waitForFunction(()=>!intelUI.busy&&!intelUI.data.endboards[14558127]);
  plans.forEach(p=>assert.equal(fs.readFileSync(p.file,'utf8'),p.bytes));
  pass('Removing general marks leaves historical files unchanged; removing hand-trap membership updates its dedicated TAG');
};

module.exports.identity=async({page,pass})=>{
  let reads=0;
  page.on('request',r=>{if(r.url().includes('/api/intelligence/endboard/'))reads++;});
  const card=await page.evaluate(async()=>{
    const c=await api('/api/card/14558127'),d=await api('/api/intelligence');
    await api('/api/intelligence',{revision:d.revision,op:'endboard.save',value:{code:c.id,desc:c.desc,note:'只向明确身份的卡牌展示的通用说明',effects:{}}});
    return c;
  });
  for(const [identity_known,drawn,expected] of [[false,false,0],[true,true,0],[true,false,1]]){
    await page.evaluate(({card,identity_known,drawn})=>{
      closeReviewDetail();
      const c={code:card.id,name:card.name,instance_id:1,identity_known,controller:0,location:4,sequence:0,position:1};
      const state={cards:[c],lp:[8000,8000]},report={id:'identity-'+identity_known+'-'+drawn,name:'身份隔离合成验收',plan_stage:'deleted',status:'completed',catalog:{[card.id]:card},final_state:state,actions:[],initial_hand:[],branches:[],
        annotations:{nodes:{},cards:{},effects:{},final_marks:{'1':{marked:true,effects:{}}}},
        events:drawn?[{id:'2:0',native_seq:2,message:90,cards:[{...c,location:2}]}]:[],
        review:{nodes:[{id:'initial',kind:'initial',number:1,action_ids:[],state},{id:'final',kind:'final',number:2,action_ids:[],state}]}};
      reviewUI.report=null;mountReview(report);switchView('history');selectReviewNode('final');
    },{card,identity_known,drawn});
    const before=reads;await page.locator('#review-final-marks .review-card').click();
    if(expected){await page.locator('#intel-review-apply').waitFor();assert.match(await page.locator('#intel-review-template').textContent(),/只向明确身份/);}
    else {assert(await page.locator('#intel-review-template').isHidden());assert.doesNotMatch(await page.locator('#review-card-detail').textContent(),/只向明确身份/);}
    if(expected)assert(reads>before);else assert.equal(reads,before);
  }
  pass('Final known cards read shared annotations; unknown and random cards neither request nor reveal their underlying card annotations');
};
