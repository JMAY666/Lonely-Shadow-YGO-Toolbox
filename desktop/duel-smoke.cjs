'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

module.exports=async function({page,application,root,evidence,pass}) {
  const enter=async name=>{await page.locator('#module-'+name).click();await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const click=async action=>{await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);};
  const stage=async value=>page.waitForFunction(value=>duelState().stage===value&&!duelUI.busy,value);
  const key=crypto.randomUUID();
  const data=await page.evaluate(async key=>{
    // Keep the acceptance profile independent of settings saved by earlier runs.
    await window.trainerDesktop.tutorialSaveSettings({back:'Control+Shift+Left',forward:'Control+Shift+Right',up:'Control+Shift+Up',down:'Control+Shift+Down',end:''});
    const tags=await api('/api/tags');const tag=(await api('/api/tags/save',{name:'决斗验收 '+key,aliases:[],card_ids:[55144522],revision:tags.revision})).tag;
    const deck=await api('/api/decks',{name:'决斗合成卡组 '+key,deck:{main:[55144522,55144522,1184620,1184620,1184620,1184620],extra:[23995346],side:[55144522]},tag_selection:{tag_ids:[tag.id],primary_ids:[tag.id]}});
    const catalog=Object.fromEntries(await Promise.all([55144522,1184620,23995346].map(async code=>[code,await card(code)])));
    return {tag,deck,catalog};
  },key);
  const row=(code,count=1)=>({code,count,name:data.catalog[code]?.name||'任意手牌',constraint:code?'':'任意手牌',instances:[],nodes:[],uses:[],status:'已记录使用'});
  const state={cards:[],lp:[8000,8000],phase:4,turn:1};
  const node=(id,number,action)=>({id,kind:'step',number,action_ids:[action],state,seq_end:Number(action.split(':')[0])});
  const action=(id)=>({id,kind:'operation',message:61,cards:[{code:1184620,name:data.catalog[1184620].name,controller:0,owner:0,identity_known:true,location:4,sequence:0,position:1}],evidence_refs:[id],summary:'合成测试：通常召唤',results:[]});
  const makePlan=()=>({id:crypto.randomUUID(),name:'合成决斗主线 '+key,deck_name:data.deck.name,deck:data.deck.deck,plan_stage:'saved',saved_ms:Date.now(),edit_revision:0,
    expansion:{name:'合成教程',notes:'隔离验收数据，不代表真实合法展开。',conditions:{slots:[55144522,55144522,null,null,null],banned:[]}},
    classification:{tag_ids:[data.tag.id],primary_ids:[data.tag.id],mode:'manual'},catalog:data.catalog,
    requirements:{main:[row(55144522,2),row(1184620)],extra:[],opening:[row(55144522,2),row(null)],random:[],warnings:[],final:{cards:[],notes:'合成终场说明'}},
    review:{complete:true,revision:'synthetic',nodes:[{id:'initial',kind:'initial',action_ids:[],state},node('s1',1,'10:0'),node('s2',2,'20:0'),node('s3',3,'30:0'),{id:'final',kind:'final',action_ids:[],state}]},
    initial_hand:[],events:[],actions:[action('10:0'),action('20:0'),action('30:0')],annotations:{nodes:{s1:{name:'开始展开',notes:'逐步说明 <保持原文>'}},effects:{},cards:{},final_marks:{}},branches:[],final_state:state});
  const plan=makePlan();
  for(const [id,count] of [['allowed',1],['blocked',2],['alternative',1]]) {
    const report=makePlan();report.requirements.extra=[row(23995346,count)];
    plan.branches.push({id,name:id==='blocked'?'资源不足分支':id==='allowed'?'可用分支 A':'互斥分支 C',valid:true,source:{node_id:'s1',action_id:'10:0',seq:10,checkpoint:1,timing:'结算后',cards:[]},conditions:{hand:[]},premises:[],report});
  }
  const noResource=makePlan();noResource.name='主线资源不足';noResource.requirements.main=[row(55144522,3)];
  const noOpening=makePlan();noOpening.name='起手数量不足';noOpening.requirements.opening=[row(55144522,3)];
  const legacy=makePlan();legacy.name='缺少条件旧方案';delete legacy.requirements;
  const second=makePlan();second.name='后手方案不适用';second.expansion.turn_order='second';
  // Every write is scoped to the smoke harness's isolated profile.
  const plansDir=path.join(root,'runtime','_trainer','plans');
  assert(fs.existsSync(plansDir),'Expected isolated plan library');
  const originals=new Map();
  for(const p of [plan,noResource,noOpening,legacy,second]){const file=path.join(plansDir,p.id+'.json');fs.writeFileSync(file,JSON.stringify(p));originals.set(file,fs.readFileSync(file));}
  await enter('duel');await page.locator('#duel-new').click();await stage(0);
  assert.equal(await page.locator('[data-module-target]').evaluateAll(nodes=>nodes.filter(n=>n.closest('#primary-navigation')).map(n=>n.dataset.moduleTarget)).then(v=>v.join(',')),'home,decks,expansion,duel,tags');
  assert(await page.getByRole('button',{name:/BO3/}).isDisabled());
  await click('bo1');await stage(1);await click('deck-list');
  const deckTile=page.locator(`[data-duel-deck="${data.deck.id}"]`);assert((await deckTile.textContent()).includes(data.tag.name));
  await deckTile.hover();await page.waitForFunction(()=>!document.querySelector('#deck-preview').hidden&&document.querySelector('#deck-preview').textContent.includes('决斗验收'));
  await deckTile.click();await page.waitForFunction(()=>duelState().deckPage==='preview'&&!duelUI.busy);
  for(const marker of ['main:0','extra:0','side:0'])await page.locator(`[data-duel-mark="${marker}"]`).click();
  await page.locator('.duel-zone .review-card').first().hover();await page.waitForFunction(()=>!document.querySelector('#review-card-popover').hidden);
  await page.locator('#review-detail-close').click();
  await page.screenshot({path:path.join(evidence,'duel-deck.png')});
  await click('start-duel');await stage(2);await click('manual-order');await click('first');await click('prepare');await stage(3);
  assert.equal(await page.locator('.duel-slot').count(),5);
  assert.equal(await page.locator('.duel-candidates aside [data-duel-add]').count(),1);
  assert(await page.locator('[data-duel-action="match"]').isDisabled());
  const add=async(code,quick=false)=>page.locator(`${quick?'.duel-candidates aside':'.duel-candidates>section'} [data-duel-add="${code}"]`).click();
  await add(55144522);await add(55144522,true);
  assert(await page.locator('.duel-candidates aside [data-duel-add="55144522"]').isDisabled());
  await add(1184620);await add(1184620);await add(1184620);
  assert(await page.locator('.duel-candidates>section [data-duel-add="1184620"]').isDisabled());
  await page.locator('[data-duel-remove="4"]').click();assert(await page.locator('[data-duel-action="match"]').isDisabled());await add(1184620);
  await page.screenshot({path:path.join(evidence,'duel-hand.png')});
  await click('match');await stage(4);
  const result=await page.evaluate(()=>duelState().result);
  assert.equal(result.matches.length,1);assert.equal(result.matches[0].branches.length,2);
  assert.equal(result.counts.resources,1);assert.equal(result.counts.opening,1);assert.equal(result.counts.incomplete,1);
  assert.equal(result.counts.turn_order,1);
  const tile=page.locator(`[data-duel-plan="${plan.id}"]`);
  await tile.hover();await page.waitForFunction(()=>!document.querySelector('#duel-preview').hidden);
  assert.equal(await page.locator('#duel-preview svg').count(),0);
  await page.locator('#duel-preview-close').click();await page.locator('#duel-detailed-preview').check();await tile.hover();
  await page.waitForFunction(()=>document.querySelectorAll('#duel-preview [data-tutorial-route]').length===3);
  assert.equal(await page.locator('#duel-preview [data-tutorial-route="blocked"]').count(),0);
  await page.locator('#duel-preview-close').click();await tile.click();await stage(5);
  assert.equal(await page.evaluate(()=>duelState().position.key),'main/s1');
  await page.keyboard.press('ArrowDown');assert.equal(await page.evaluate(()=>duelState().position.choice),1);
  await page.keyboard.press('ArrowRight');assert.match(await page.evaluate(()=>duelState().position.key),/^allowed\//);
  await page.keyboard.press('ArrowLeft');assert.equal(await page.evaluate(()=>duelState().position.key),'main/s1');
  await page.locator('[data-duel-node="main/s2"]').click();await page.keyboard.press('ArrowRight');assert.equal(await page.evaluate(()=>duelState().position.key),'main/s3');
  await page.screenshot({path:path.join(evidence,'duel-tutorial.png')});
  await click('shortcuts');const savedPosition=await page.evaluate(()=>duelState().position.key);
  await page.locator('[data-duel-binding="forward"]').focus();await page.keyboard.press('Control+Alt+F8');
  await page.locator('[data-duel-binding="end"]').focus();await page.keyboard.press('Control+Alt+F8');
  await page.locator('#duel-shortcut-save').click();await page.waitForFunction(()=>document.querySelector('#duel-shortcut-error').textContent.includes('相同快捷键'));
  await page.locator('[data-duel-clear-binding="end"]').click();await page.locator('#duel-shortcut-save').click();
  await page.waitForFunction(()=>!document.querySelector('#duel-shortcut-dialog').open);
  assert.equal(await page.evaluate(()=>duelState().position.key),savedPosition);
  await click('toggle-shortcuts');
  const keys=await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered);assert.equal(keys.length,4);
  assert(await application.evaluate(({globalShortcut})=>globalShortcut.isRegistered('Control+Alt+F8')));
  // Invoke the actual main-process callback via a test-only handle. Never send a
  // system key or focus another window during desktop acceptance.
  await application.evaluate(()=>globalThis.tutorialAcceptance.invoke('forward'));
  await page.waitForFunction(()=>duelState().position.key==='main/final');
  await click('back');await stage(4);assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  await tile.click();await stage(5);assert.equal(await page.evaluate(()=>duelState().position.key),'main/final');
  await click('toggle-shortcuts');await enter('home');assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  await enter('duel');await stage(5);await click('toggle-shortcuts');await click('end');await stage(6);
  assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  await page.screenshot({path:path.join(evidence,'duel-complete.png')});
  await page.locator('#duel-new').click();await stage(0);assert.deepEqual(await page.evaluate(()=>duelState().hand),[null,null,null,null,null]);
  await click('bo1');await click('deck-list');
  // New duel starts fresh; refresh reads the same shared saved list.
  await click('refresh-decks');await page.locator(`[data-duel-deck="${data.deck.id}"]`).click();await page.waitForFunction(()=>!duelUI.busy);await click('start-duel');await click('manual-order');await click('first');
  await page.locator('#duel-count').fill('0');assert(await page.locator('[data-duel-action="prepare"]').isDisabled());
  await page.locator('#duel-count').fill('7');assert(await page.locator('[data-duel-action="prepare"]').isDisabled());
  await page.locator('#duel-count').fill('4');await click('prepare');assert.equal(await page.locator('.duel-slot').count(),4);
  await add(55144522);await add(55144522);await add(1184620);await add(1184620);await click('match');await tile.click();await stage(5);
  await page.locator('#duel-substeps [data-duel-stage="3"]').click();await stage(3);await page.locator('[data-duel-remove="0"]').click();assert.equal(await page.evaluate(()=>duelState().plan),null);
  await add(1184620);await click('match');await stage(4);assert.equal(await page.locator('[data-duel-plan]').count(),0);
  await page.evaluate(async id=>{const saved=await api('/api/deck?id='+encodeURIComponent(id));await api('/api/decks',{...saved,tag_selection:{tag_ids:[],primary_ids:[]}});},data.deck.id);
  await enter('home');await enter('duel');await stage(1);assert((await page.locator('#duel-body').textContent()).includes('尚未设置 Tag'));
  assert.equal(await page.evaluate(()=>duelState().result),null);
  // List/hover/detail API all use the same updated Tag data, including empty state.
  await enter('decks');await page.evaluate(()=>setDeckPage('manager'));await page.evaluate(()=>deckList());
  assert((await page.locator(`[data-open-deck="${data.deck.id}"]`).textContent()).includes('尚未设置 Tag'));
  await enter('expansion');await page.evaluate(()=>switchView('decks'));await page.evaluate(()=>deckList());
  assert((await page.locator(`[data-select-deck="${data.deck.id}"]`).textContent()).includes('尚未设置 Tag'));
  for(const [file,bytes] of originals)assert(fs.readFileSync(file).equals(bytes),'Frozen plan unchanged: '+path.basename(file));
  const after=await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),data.deck.id);assert.deepEqual(after.deck,data.deck.deck);
  await enter('home');
  pass('BO1 duel: full flow, 5/custom hands, shared marked counts, Tag sync, three-stage matching, branch projection, hover previews, graph navigation, configurable shortcuts with real registration/callback/release, stale-state reset and immutable source plans');
};
