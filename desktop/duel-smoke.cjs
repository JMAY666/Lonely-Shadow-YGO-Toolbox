'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

module.exports=async function({page,application,root,evidence,pass}) {
  const enter=async name=>{await require('./navigation-test.cjs')(page, name);await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const click=async action=>{await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);};
  const stage=async value=>page.waitForFunction(value=>duelState().stage===duelStages[value]&&!duelUI.busy,value);
  await enter('home');
  assert.deepEqual(await page.locator('.home-shortcut').evaluateAll(nodes=>nodes.map(node=>node.dataset.moduleTarget)),['decks','expansion','duel','cardanno']);
  await page.screenshot({path:path.join(evidence,'home-four-entries.png')});
  for(const name of ['decks','expansion','duel','tags']) {
    await page.locator('#home-'+name).click();await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name==='tags'?'cardanno':name);
    await enter('home');
  }
  const key=crypto.randomUUID();
  const globalMods='Control+Alt+Shift';
  const globalKeys=await application.evaluate(({app})=>app.isPackaged?{back:'F5',forward:'F6',up:'F7',down:'F8',custom:'F10'}:{back:'F1',forward:'F2',up:'F3',down:'F4',custom:'F9'});
  const data=await page.evaluate(async ({key,globalMods,globalKeys})=>{
    // Keep this hidden acceptance instance on uncommon bindings, leaving ordinary
    // user arrow keys available while testing foreground/background parity.
    await window.trainerDesktop.tutorialSaveSettings({back:globalMods+'+'+globalKeys.back,forward:globalMods+'+'+globalKeys.forward,up:globalMods+'+'+globalKeys.up,down:globalMods+'+'+globalKeys.down,end:''});
    await api('/api/duel/settings',{hand_count:5});
    const tags=await api('/api/tags');const tag=(await api('/api/tags/save',{name:'决斗验收 '+key,aliases:[],card_ids:[55144522],revision:tags.revision})).tag;
    const deck=await api('/api/decks',{name:'决斗合成卡组 '+key,deck:{main:[55144522,55144522,1184620,1184620,1184620,1184620],extra:[23995346],side:[55144522]},tag_selection:{tag_ids:[tag.id],primary_ids:[tag.id]}});
    const catalog=Object.fromEntries(await Promise.all([55144522,1184620,23995346].map(async code=>[code,await card(code)])));
    return {tag,deck,catalog};
  },{key,globalMods,globalKeys});
  const row=(code,count=1)=>({code,count,name:data.catalog[code]?.name||'任意手牌',constraint:code?'':'任意手牌',instances:[],nodes:[],uses:[],status:'已记录使用'});
  const state={cards:[{instance_id:1,code:1184620,name:data.catalog[1184620].name,controller:0,owner:0,location:4,sequence:0,position:1,identity_known:true},{instance_id:2,code:55144522,name:data.catalog[55144522].name,controller:0,owner:0,location:2,sequence:0,identity_known:true},{instance_id:3,code:23995346,name:data.catalog[23995346].name,controller:0,owner:0,location:16,sequence:0,identity_known:true}],lp:[8000,8000],phase:4,turn:1};
  const node=(id,number,action)=>({id,kind:'step',number,action_ids:[action],state,seq_end:Number(action.split(':')[0])});
  const action=(id)=>({id,kind:'operation',message:61,cards:[{code:1184620,name:data.catalog[1184620].name,controller:0,owner:0,identity_known:true,location:4,sequence:0,position:1}],evidence_refs:[id],summary:'合成测试：通常召唤',results:[]});
  const makePlan=()=>{const p=({id:crypto.randomUUID(),name:'合成决斗主线 '+key,deck_name:data.deck.name,deck:data.deck.deck,plan_stage:'saved',saved_ms:Date.now(),edit_revision:0,
    expansion:{name:'合成教程',notes:'隔离验收数据，不代表真实合法展开。',conditions:{slots:[55144522,55144522,null,null,null],banned:[]}},
    classification:{tag_ids:[data.tag.id],primary_ids:[data.tag.id],mode:'manual'},catalog:data.catalog,
    requirements:{main:[row(55144522,2),row(1184620)],extra:[],opening:[row(55144522,2),row(null)],random:[],warnings:[],final:{cards:[],notes:'合成终场说明'}},
    review:{complete:true,revision:'synthetic',nodes:[{id:'initial',kind:'initial',action_ids:[],state},node('s1',1,'10:0'),node('s2',2,'20:0'),node('s3',3,'30:0'),{id:'final',kind:'final',action_ids:[],state}]},
    initial_hand:[state.cards[1]],events:[action('10:0'),action('20:0'),action('30:0')],actions:[action('10:0'),action('20:0'),action('30:0')],annotations:{nodes:{s1:{name:'开始展开',notes:'逐步说明 <保持原文>'}},effects:{},cards:{1:'终场卡牌备注 <保持原文>\n'+'完整备注不得截断。'.repeat(24)},final_marks:{1:{marked:true,effects:{0:{note:'终场效果备注：保留此效果作为后续资源。'}}},2:{marked:true,effects:{}},3:{marked:true,effects:{}}}},branches:[],final_state:state});
    // Synthetic layout fixture explicitly records empty resource decisions;
    // legacy missing-evidence rejection has separate real-core coverage.
    const nodes=p.review.nodes;nodes.forEach(n=>{n.module_id='fixture:'+n.id;});
    p.review.module_graph={schema:1,modules:nodes.map((n,i)=>({id:n.module_id,seq:i,player:0,state:n.state})),
      connections:nodes.slice(1).map((n,i)=>({from:nodes[i].module_id,to:n.module_id,response_refs:[i],decision:{selection:[]}})),
      step_order:nodes.map(n=>n.id),step_links:nodes.slice(1).map((n,i)=>({from:nodes[i].id,to:n.id,from_module:nodes[i].module_id,to_module:n.module_id,module_path:[nodes[i].module_id,n.module_id],status:'recorded'}))};return p;};
  const plan=makePlan();
  for(const [id,count] of [['allowed',1],['blocked',2],['alternative',1]]) {
    const report=makePlan();report.requirements.extra=[row(23995346,count)];
    report.requirements.final.notes='分支终场说明 '+id;
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
  await enter('decks');await page.evaluate(()=>setDeckPage('manager'));await page.evaluate(()=>deckList());
  await page.locator(`[data-open-deck="${data.deck.id}"]`).click();await page.waitForFunction(()=>!app.busy);
  await page.locator('#deck-representatives-button').click();
  for(const code of [55144522,1184620,23995346])await page.locator(`[data-representative-card="${code}"]`).click();
  await page.locator('#representative-apply').click();assert(await page.evaluate(()=>app.dirty));
  await page.locator('#save-deck').click();await page.waitForFunction(()=>!app.busy&&!app.dirty);
  data.deck=await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),data.deck.id);
  assert.deepEqual(data.deck.representatives,[55144522,1184620,23995346]);
  await page.locator('#back-to-decks').click();await page.waitForFunction(()=>!app.busy);
  const managerTile=page.locator(`[data-open-deck="${data.deck.id}"]`);
  assert.equal(await managerTile.locator('.deck-representatives img').count(),3);
  assert.equal(await managerTile.locator('.shared-deck-tags').count(),0);
  assert((await managerTile.boundingBox()).height<=185);
  await managerTile.hover();await page.waitForFunction(()=>!document.querySelector('#deck-preview').hidden&&document.querySelector('#deck-preview').textContent.includes('决斗验收'));
  await page.evaluate(()=>closeDeckPreview());await page.screenshot({path:path.join(evidence,'compact-deck-boxes.png')});
  await enter('expansion');await page.evaluate(()=>switchView('decks'));await page.evaluate(()=>deckList());
  const selectionTile=page.locator(`[data-select-deck="${data.deck.id}"]`);
  assert.equal(await selectionTile.locator('.deck-representatives img').count(),3);
  assert.equal(await selectionTile.locator('.shared-deck-tags').count(),0);
  assert.equal(await page.locator('#expansion-navigation .module-caption').count(),0);
  await enter('duel');await page.evaluate(()=>startNewDuel());await stage('mode');
  assert.equal(await page.locator('#duel-new,.duel-header').count(),0);
  const mode=await page.locator('[data-duel-action="bo1"]').boundingBox();assert(Math.abs(mode.width-mode.height)<2);assert(mode.width>=210);
  const lobby=await page.locator('.duel-mode-grid').boundingBox(),modes=await page.locator('.duel-mode').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,cy:r.y+r.height/2};}));
  assert(Math.abs((modes[0].left+modes[1].right)/2-(lobby.x+lobby.width/2))<2);assert(Math.abs(modes[0].cy-(lobby.y+lobby.height/2))<2);
  assert(await page.evaluate(async()=>{const image=new Image();image.src='/brand/duel-bo1.svg';await image.decode();return image.naturalWidth===600;}));
  assert.equal(await page.locator('.duel-mode-grid').evaluate(el=>getComputedStyle(el).backgroundImage),'none');assert((await page.locator('.duel-mode').first().evaluate(el=>getComputedStyle(el).backgroundImage)).includes('duel-bo1.svg'));
  assert((await page.locator('#duel-steps').boundingBox()).height<50);
  assert(await page.getByRole('button',{name:/BO3/}).isDisabled());
  await page.screenshot({path:path.join(evidence,'duel-mode.png')});
  assert.deepEqual(await page.locator('#duel-steps button').evaluateAll(nodes=>nodes.map(n=>n.lastChild.textContent)),['模式选择','功能选择','卡组选择','决定先/后攻','卡组展开']);
  await click('bo1');await stage('function');
  assert.equal(await page.locator('#duel-steps [aria-current="step"]').getAttribute('data-duel-stage'),'1');
  assert(await page.locator('#duel-steps [data-duel-stage="2"]').isDisabled());
  assert.deepEqual(await page.locator('#duel-substeps button').allTextContents(),['1. 手动或自动','2. 平台选择']);
  assert(await page.locator('[data-duel-function-page="platform"]').isDisabled());
  assert(await page.locator('#duel-footer').isHidden());
  const automatic=page.locator('[data-duel-action="automatic"]');
  assert(await automatic.isEnabled());assert((await automatic.textContent()).includes('从游戏平台识别卡组'));
  assert.equal(await page.evaluate(()=>duelState().operationMode),null);
  const verifyFunctionLayout=async()=>{
    await page.locator('#duel-steps').hover();
    await page.waitForFunction(()=>!document.querySelector('.duel-mode').getAnimations().some(a=>a.playState==='running'));
    const box=await page.locator('.duel-mode-grid').boundingBox();
    const tiles=await page.locator('.duel-mode').evaluateAll(nodes=>nodes.map(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,width:r.width,height:r.height,cy:r.y+r.height/2};}));
    assert(tiles.every(r=>Math.abs(r.width-r.height)<2&&r.left>=box.x&&r.right<=box.x+box.width));
    assert(Math.abs((tiles[0].left+tiles[1].right)/2-(box.x+box.width/2))<2);
    assert(Math.abs(tiles[0].cy-(box.y+box.height/2))<2);assert(Math.abs(tiles[0].top-tiles[1].top)<1);
    assert(await page.locator('#duel-steps').evaluate(el=>el.scrollWidth===el.clientWidth));
    for(const name of ['manual','automatic'])assert(await page.evaluate(async name=>{const image=new Image();image.src='/brand/duel-'+name+'.svg';await image.decode();return image.naturalWidth===600;},name));
    assert((await page.locator('[data-duel-action="manual"]').evaluate(el=>getComputedStyle(el).backgroundImage)).includes('duel-manual.svg'));
  };
  await verifyFunctionLayout();await page.screenshot({path:path.join(evidence,'duel-function.png')});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(960,800));
  await page.waitForFunction(()=>innerWidth===960);await verifyFunctionLayout();await page.screenshot({path:path.join(evidence,'duel-function-narrow.png')});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.waitForFunction(()=>innerWidth===1280);
  await require('./automatic-selection-smoke.cjs')({page,application,evidence,pass,existing:data.deck});
  await page.locator('#duel-steps [data-duel-stage="0"]').click();await stage('mode');
  await click('bo1');await stage('function');await click('manual');await stage('deck');
  assert.equal(await page.evaluate(()=>duelState().operationMode),'manual');
  const deckTile=page.locator(`[data-duel-deck="${data.deck.id}"]`);
  assert(!(await deckTile.textContent()).includes(data.tag.name));assert.equal(await deckTile.locator('.deck-representatives img').count(),3);
  await deckTile.hover();await page.waitForFunction(()=>!document.querySelector('#deck-preview').hidden&&document.querySelector('#deck-preview').textContent.includes('决斗验收'));
  await deckTile.click();await page.waitForFunction(()=>duelState().deckPage==='preview'&&!duelUI.busy);
  assert.deepEqual(await page.locator('#duel-substeps button').allTextContents(),['1. 选择卡组','2. 卡牌预览']);
  assert.equal(await page.locator('[data-duel-mark]').count(),0);
  for(const marker of ['main:0','extra:0','side:0']){
    await page.locator(`[data-duel-mark-key="${marker}"] .review-card`).hover();
    await page.waitForFunction(()=>!document.querySelector('#toggle-duel-card-mark').hidden);
    await page.locator('#toggle-duel-card-mark').click();await page.locator('#review-detail-close').click();
  }
  assert.equal(await page.locator('.duel-card.is-marked').count(),3);
  assert.equal(await page.locator('#duel-footer').evaluate(el=>getComputedStyle(el).position),'fixed');
  assert((await page.locator('#duel-footer').boundingBox()).width<200);
  await page.screenshot({path:path.join(evidence,'duel-deck.png')});
  await page.locator('#duel-steps [data-duel-stage="1"]').click();await stage('function');
  await page.route('**/api/ygopro/attach',route=>route.fulfill({json:{connected:false,processes:[],error:'隔离测试：尚未启动游戏'}}));
  try {
    await click('automatic');await click('platform-ygopro');await stage('function');
    assert(await page.locator('#duel-capture-dialog').isVisible());
    assert.equal(await page.evaluate(()=>duelState().deck.id),data.deck.id);
    assert.equal(await page.evaluate(()=>duelState().marks.size),3);
    await page.locator('#duel-capture-close').click();
  } finally {await page.unroute('**/api/ygopro/attach');}
  await page.locator('#duel-steps [data-duel-stage="1"]').click();await stage('function');
  await page.locator('[data-duel-function-page="choice"]').click();
  await click('manual');await stage('deck');
  assert.equal(await page.evaluate(()=>duelState().deck.id),data.deck.id);
  assert.equal(await page.evaluate(()=>duelState().deckPage),'preview');
  assert.equal(await page.locator('.duel-card.is-marked').count(),3);
  await click('start-duel');await stage('order');
  assert((await page.locator('[data-duel-action="first"]').evaluate(el=>getComputedStyle(el).backgroundImage)).includes('duel-first.svg'));
  assert.equal(await page.locator('#duel-count,[data-duel-action="manual-order"],[data-duel-action="prepare"]').count(),0);
  await click('first');await stage('hand');
  assert.equal(await page.locator('.duel-slot').count(),5);
  const substeps=await page.locator('#duel-substeps').evaluate(el=>({width:el.clientWidth,buttons:[...el.children].map(b=>({width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height}))}));
  assert(substeps.buttons.every(b=>b.height>=38&&b.width>substeps.width*.3));assert(Math.abs(substeps.buttons[0].width-substeps.buttons[2].width)<1);
  assert.equal(await page.locator('.duel-candidates aside').count(),0);
  assert(!(await page.locator('#duel-body').textContent()).match(/等待选牌|加入起手|投入|已选/));
  assert.equal(await page.locator('.duel-candidate.is-marked').count(),1);
  assert.deepEqual(await page.locator('[data-duel-add]').evaluateAll(nodes=>nodes.map(el=>Number(el.dataset.duelAdd))),[1184620,55144522]);
  // A presentation-only 40-card fixture checks wrapping, centering and order;
  // it never replaces the saved deck or the active match fixture.
  await page.evaluate(async()=>{
    const candidates=(await api('/api/cards?kind=monster')).cards.filter(c=>!c.extra&&!(c.type&0x4000)).slice(0,12);
    for(const kind of ['spell','trap'])candidates.push(...(await api('/api/cards?kind='+kind)).cards.slice(0,6));
    candidates.forEach(c=>app.cache.set(c.id,c));
    const main=candidates.map(c=>c.id);main.push(...main.slice(0,16));main.reverse();
    const s=duelState(),saved=s.deck;
    try{s.deck={...saved,deck:{...saved.deck,main}};document.querySelector('#duel-body').innerHTML=duelHandPage();}
    finally{s.deck=saved;}
  });
  const verifyHandLayout=async()=>{
    const result=await page.evaluate(()=>{
      const box=document.querySelector('.duel-candidates').getBoundingClientRect(),page=document.querySelector('#duel-body').getBoundingClientRect();
      const slots=[...document.querySelectorAll('.duel-slot')].map(el=>el.getBoundingClientRect());
      const cards=[...document.querySelectorAll('[data-duel-add]')];
      return {center:Math.abs((slots[0].left+slots.at(-1).right)/2-(page.left+page.width/2)),deckCenter:Math.abs(box.left+box.width/2-(page.left+page.width/2)),width:box.width,pageWidth:page.width,
        fits:cards.every(el=>{const r=el.getBoundingClientRect();return r.left>=box.left&&r.right<=box.right;}),
        sorted:cards.every((el,i)=>!i||compareDeckCards(Number(cards[i-1].dataset.duelAdd),Number(el.dataset.duelAdd))<=0)};
    });
    assert(result.center<2&&result.deckCenter<2);assert(result.width<=940&&result.width<=result.pageWidth);assert(result.fits&&result.sorted);
  };
  await verifyHandLayout();await page.screenshot({path:path.join(evidence,'duel-hand-layout.png')});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(960,800));
  await page.waitForFunction(()=>innerWidth===960);await verifyHandLayout();await page.screenshot({path:path.join(evidence,'duel-hand-narrow.png')});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.waitForFunction(()=>innerWidth===1280);await page.evaluate(()=>renderDuel());
  assert(await page.locator('[data-duel-action="match"]').isDisabled());
  const add=async code=>page.locator(`[data-duel-add="${code}"]`).click();
  await add(55144522);assert.equal(await page.locator('.duel-candidate.is-marked .duel-stock').textContent(),'1');
  await add(55144522);assert.equal(await page.locator('.duel-candidate.is-marked .duel-stock').textContent(),'0');
  assert.equal(await page.locator('.duel-candidate.is-exhausted').count(),1);
  await add(1184620);await add(1184620);await add(1184620);
  assert.equal(await page.locator('[data-duel-add="1184620"]').getAttribute('aria-disabled'),'true');
  await page.locator('[data-duel-slot="4"]').click({button:'right'});assert(await page.locator('[data-duel-action="match"]').isDisabled());await add(1184620);
  await page.locator('[data-duel-add="55144522"]').dispatchEvent('contextmenu');assert.equal(await page.locator('.duel-candidate.is-marked .duel-stock').textContent(),'1');await add(55144522);
  await page.screenshot({path:path.join(evidence,'duel-hand.png')});
  await click('match');await stage('plans');
  const result=await page.evaluate(()=>duelState().result);
  assert.equal(result.matches.length,1);assert.equal(result.matches[0].branches.length,2);
  assert.equal(result.counts.resources,1);assert.equal(result.counts.opening,1);assert.equal(result.counts.incomplete,1);assert.equal(result.counts.turn_order,1);
  assert(!(await page.locator('.duel-plan-grid').textContent()).match(/Tag ID|妥协分支|资源不足|可选.*个/));
  assert.match(await page.locator('.duel-condition-results').textContent(),/资源不足/,'Excluded routes now explain the failed condition');
  const tile=page.locator(`[data-duel-plan="${plan.id}"]`);assert(await tile.locator('img').count()>3);
  assert.equal(await tile.locator('.duel-plan-step-count').textContent(),'主线 3 步');
  assert.equal(await tile.locator('.duel-plan-branch-count').textContent(),'可用分支 2');
  assert(!(await tile.textContent()).includes('可用分支 A'));assert(!(await tile.textContent()).includes('互斥分支 C'));
  // The HTML dialog must stay below Windows caption buttons, including zoom.
  await page.evaluate(()=>openPlanTutorial(duelState().result.matches[0]));
  for(const [width,height,zoom] of [[1440,915,1],[900,650,1],[1100,800,1.25]]) {
    await application.evaluate(({BrowserWindow},{width,height,zoom})=>{const window=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());window.setContentSize(width,height);window.webContents.setZoomFactor(zoom);},{width,height,zoom});
    await page.waitForFunction(({width,zoom})=>Math.abs(innerWidth-width/zoom)<2,{width,zoom});
    await page.waitForFunction(()=>{
      const area=navigator.windowControlsOverlay?.getTitlebarAreaRect(),dialog=document.querySelector('#plan-tutorial-dialog').getBoundingClientRect();
      return !area||dialog.top>=area.bottom+8&&dialog.bottom<=innerHeight;
    });
    assert(await page.locator('#plan-tutorial-dialog header button').evaluateAll(buttons=>buttons.every(button=>{const r=button.getBoundingClientRect();return r.right<=innerWidth&&r.top>=navigator.windowControlsOverlay.getTitlebarAreaRect().bottom;})));
  }
  await application.evaluate(({BrowserWindow})=>{const window=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());window.webContents.setZoomFactor(1);window.setContentSize(1280,900);});
  await page.waitForFunction(()=>innerWidth===1280&&innerHeight===900);
  await page.screenshot({path:path.join(evidence,'tutorial-titlebar-clear.png')});
  await page.locator('#plan-tutorial-close').click();
  await tile.hover();await page.waitForFunction(()=>!document.querySelector('#duel-preview').hidden);
  assert.equal(await page.locator('#duel-preview svg').count(),0);assert(await page.locator('#duel-preview img').count()>3);
  assert((await page.locator('#duel-preview').textContent()).includes('手牌区'));
  assert((await page.locator('#duel-preview').textContent()).includes('墓地'));
  const compactText=await page.locator('#duel-preview').textContent();
  const tileBox=await tile.boundingBox(),planBox=await page.locator('#duel-preview').boundingBox();
  assert(planBox.x>=tileBox.x+tileBox.width||planBox.x+planBox.width<=tileBox.x||planBox.y>=tileBox.y+tileBox.height||planBox.y+planBox.height<=tileBox.y);
  assert(compactText.includes('合成终场说明'));assert(compactText.includes('终场卡牌备注 <保持原文>'));
  assert(compactText.includes('完整备注不得截断。'.repeat(24)));assert(compactText.includes('终场效果备注：保留此效果作为后续资源。'));
  assert(compactText.includes('可用分支 2'));assert(!compactText.includes('分支终场说明'));assert(!compactText.includes('可用分支 A'));
  await page.screenshot({path:path.join(evidence,'duel-plan-preview.png')});
  await page.locator('[data-duel-preview-mode="detailed"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('#duel-preview [data-tutorial-route]').length===3);
  assert.equal(await page.locator('#duel-preview [data-tutorial-route="blocked"]').count(),0);
  assert.equal(await page.locator('#duel-preview [data-duel-branch-detail]').count(),2);
  assert((await page.locator('#duel-preview [data-duel-branch-detail="allowed"]').textContent()).includes('分支终场说明 allowed'));
  assert((await page.locator('#duel-preview [data-duel-branch-detail="allowed"]').textContent()).includes('主线 Step 1'));
  await page.screenshot({path:path.join(evidence,'duel-branch-details.png')});
  await page.locator('[data-duel-preview-mode="compact"]').click();assert.equal(await page.locator('#duel-preview svg').count(),0);
  await page.locator('#duel-preview-close').click();await tile.click();await stage('tutorial');
  const originalReview=await page.evaluate(()=>({id:reviewUI.report?.id,node:reviewUI.node,draft:JSON.stringify(flow.draft)}));
  assert.equal(await page.evaluate(()=>duelState().position.key),'main/s1');
  assert(await page.locator('.duel-node .compact-chain img').count()>0);
  assert(await page.locator('#duel-current-detail .board-slot').count()>10);
  await require('./duel-step-view-smoke.cjs')({page,application,evidence,pass});
  const resize=page.locator('#duel-graph-resize'),heightBefore=await page.locator('#duel-graph-scroll').evaluate(el=>el.clientHeight),positionBefore=await page.evaluate(()=>duelState().position.key);
  const handle=await resize.boundingBox();await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down();await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2+90,{steps:6});await page.mouse.up();
  assert((await page.locator('#duel-graph-scroll').evaluate(el=>el.clientHeight))>heightBefore+80);
  await resize.focus();await resize.press('ArrowUp');assert.equal(await page.evaluate(()=>duelState().position.key),positionBefore);
  await resize.dblclick();
  assert(await page.locator('#duel-graph-scroll').evaluate(el=>[...el.querySelectorAll('.duel-node')].every(node=>node.getBoundingClientRect().height<=el.clientHeight-10)));

  await page.locator('[data-duel-node="main/s1"]').hover();await page.waitForFunction(()=>!document.querySelector('#duel-preview').hidden);
  assert(await page.locator('#duel-preview .duel-step-peek-row').count()>0);assert.equal(await page.locator('#duel-preview .log-action').count(),0);
  assert.match(await page.locator('#duel-preview').textContent(),/点击步骤查看完整内容/);
  const cardInPreview=page.locator('#duel-preview [data-review-card]').first();
  await cardInPreview.hover();await page.waitForFunction(()=>!document.querySelector('#review-card-popover').hidden);
  await page.locator('#review-card-popover').hover();await page.waitForTimeout(500);
  assert(await page.locator('#duel-preview').isVisible());assert(await page.locator('#review-card-popover').isVisible());
  // Both hover panels may naturally dismiss when leaving the nested card;
  // close the verified preview before testing the next hover interaction.
  await page.evaluate(()=>{closeReviewDetail();closeDuelPreview(true);});
  // Repeated child movement must not restart the step's opening delay or leave
  // an old close timer that dismisses a newer step preview.
  for(const key of ['main/s2','main/s1','main/s2','main/s1']) {
    await page.locator('#duel-substeps').hover();
    await page.locator(`[data-duel-node="${key}"]`).hover();
    await page.waitForFunction(key=>!document.querySelector('#duel-preview').hidden&&duelUI.previewId===key,key,{timeout:1500});
    await page.locator('#duel-preview').hover();await page.waitForTimeout(300);
    assert.equal(await page.evaluate(()=>duelUI.previewId),key);assert(await page.locator('#duel-preview').isVisible());
    await page.locator('#duel-preview-close').click();
  }
  // A slow, real coordinate click must hit the next step even after a very
  // tall detail has opened. Locator.click() could otherwise hide interception
  // by retrying until the popup goes away.
  const savedNodeNotes=await page.evaluate(()=>{
    const notes=structuredClone(duelState().plan.annotations.nodes);
    duelState().plan.annotations.nodes.s2={notes:'长步骤详情，点击下一步必须仍然可用。\n'.repeat(50)};
    return notes;
  });
  const step=page.locator('[data-duel-node="main/s2"]'),bounds=await step.boundingBox();
  const point={x:bounds.x+24,y:bounds.y+32};
  await page.mouse.move(point.x,point.y);await page.waitForFunction(()=>duelUI.previewId==='main/s2'&&!document.querySelector('#duel-preview').hidden);
  const previewBounds=await page.locator('#duel-preview').boundingBox(),graphBounds=await page.locator('#duel-graph-scroll').boundingBox();
  assert(previewBounds.y>=graphBounds.y+graphBounds.height||previewBounds.y+previewBounds.height<=graphBounds.y);
  assert(await page.locator('#duel-preview').evaluate(el=>el.scrollHeight<=el.clientHeight+1));
  assert.doesNotMatch(await page.locator('#duel-preview').textContent(),/长步骤详情，点击下一步/);
  await page.screenshot({path:path.join(evidence,'duel-hover-click-safe.png'),preserveScroll:true});
  await page.mouse.click(point.x,point.y);assert.equal(await page.evaluate(()=>duelState().position.key),'main/s2');
  await page.waitForTimeout(450);assert(await page.locator('#duel-preview').isHidden());
  await page.locator('#duel-substeps').hover();await step.hover();
  await page.waitForFunction(()=>duelUI.previewId==='main/s2'&&!document.querySelector('#duel-preview').hidden);
  const forward=await page.locator('[data-duel-action="forward-step"]').boundingBox();
  const forwardPoint={x:forward.x+forward.width/2,y:forward.y+forward.height/2};
  await page.mouse.move(forwardPoint.x,forwardPoint.y);assert(await page.locator('#duel-preview').isHidden());
  await page.mouse.click(forwardPoint.x,forwardPoint.y);assert.equal(await page.evaluate(()=>duelState().position.key),'main/s3');
  await page.mouse.click(forwardPoint.x,forwardPoint.y);assert.equal(await page.evaluate(()=>duelState().position.key),'main/final');
  await page.evaluate(notes=>{duelState().plan.annotations.nodes=notes;duelState().position={key:'main/s1',choice:0};paintDuelPosition();},savedNodeNotes);
  await page.locator('#duel-substeps').hover();
  const held=await page.locator('[data-duel-node="main/s2"]').boundingBox();
  await page.mouse.move(held.x+24,held.y+32);await page.mouse.down();await page.waitForTimeout(450);
  assert(await page.locator('#duel-preview').isHidden());await page.mouse.up();assert.equal(await page.evaluate(()=>duelState().position.key),'main/s2');
  await page.evaluate(()=>{duelState().position={key:'main/s1',choice:0};paintDuelPosition();});
  await page.locator('#duel-substeps').hover();
  pass('Slow coordinate clicks and held presses survive long step previews; footer navigation stays reachable and repeats; tiles show main-route step counts');
  pass('Four working home entries; tutorial dialog clears native window controls at narrow widths and zoom; full final notes and counts survive compact/detail switching with branch details only in detailed mode');
  await page.keyboard.press(globalMods+'+'+globalKeys.down);assert.equal(await page.evaluate(()=>duelState().position.choice),1);
  await page.keyboard.press(globalMods+'+'+globalKeys.forward);assert.match(await page.evaluate(()=>duelState().position.key),/^allowed\//);
  await page.keyboard.press(globalMods+'+'+globalKeys.back);assert.equal(await page.evaluate(()=>duelState().position.key),'main/s1');
  const verifyGraphFocus=async()=>assert(await page.evaluate(()=>{
    const viewport=document.querySelector('#duel-graph-scroll'),node=viewport.querySelector('.current'),scale=duelUI.graphScale;
    const left=Math.max(0,Math.min(viewport.scrollWidth-viewport.clientWidth,node.offsetLeft*scale-(viewport.clientWidth-node.offsetWidth*scale)/2));
    return Math.abs(viewport.scrollLeft-left)<2&&node.getBoundingClientRect().top>=viewport.getBoundingClientRect().top;
  }),'The clicked step is centered within the graph scroll range');
  await page.locator('[data-duel-node="main/s2"]').click();await verifyGraphFocus();
  const pageY=await page.evaluate(()=>scrollY);await page.keyboard.press(globalMods+'+'+globalKeys.forward);assert.equal(await page.evaluate(()=>duelState().position.key),'main/s3');await verifyGraphFocus();assert.equal(await page.evaluate(()=>scrollY),pageY);
  assert.equal(await page.locator('.duel-node.current').count(),1);assert.equal(await page.locator('.duel-node:focus').count(),0);
  // CDP key repeats stay within this application's renderer.
  await page.keyboard.down('Control');await page.keyboard.down('Alt');await page.keyboard.down('Shift');await page.keyboard.down(globalKeys.back);await page.keyboard.down(globalKeys.back);await page.keyboard.up(globalKeys.back);await page.keyboard.up('Shift');await page.keyboard.up('Alt');await page.keyboard.up('Control');assert.equal(await page.evaluate(()=>duelState().position.key),'main/s1');
  await page.screenshot({path:path.join(evidence,'duel-tutorial.png')});
  await page.locator('#duel-current-detail [data-review-zone="0:16"]').click();assert(await page.locator('#duel-zone-content img').count()>0);
  await page.locator('[data-duel-close-zone]').click();
  assert.deepEqual(await page.evaluate(()=>({id:reviewUI.report?.id,node:reviewUI.node,draft:JSON.stringify(flow.draft)})),originalReview);
  await click('shortcuts');await page.waitForFunction(()=>document.querySelector('#duel-shortcut-dialog').open&&duelUI.shortcutStatus?.registered?.length===0);assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  assert.equal(await page.locator('#duel-shortcut-title').textContent(),'教程快捷键');
  assert.equal(await page.locator('#duel-shortcut-dialog select,#duel-shortcut-dialog input[type="number"]').count(),0);
  await page.locator('[data-duel-binding="forward"]').focus();await page.keyboard.press(globalMods+'+'+globalKeys.custom);
  await page.locator('[data-duel-binding="end"]').focus();await page.keyboard.press(globalMods+'+'+globalKeys.custom);
  await page.locator('#duel-shortcut-save').click();await page.waitForFunction(()=>document.querySelector('#duel-shortcut-error').textContent.includes('相同快捷键'));
  await page.locator('[data-duel-clear-binding="end"]').click();await page.locator('#duel-shortcut-save').click();await page.waitForFunction(()=>!document.querySelector('#duel-shortcut-dialog').open);
  await page.waitForFunction(()=>duelUI.shortcutStatus?.registered?.length===4);
  const savedBindings=await page.evaluate(()=>({...duelUI.bindings}));
  const handCount=await page.evaluate(async()=>(await api('/api/duel/settings')).hand_count);assert.equal(handCount,5);
  await page.locator('#app-settings').click();await page.waitForFunction(()=>duelUI.shortcutStatus?.registered?.length===0);
  await page.locator('#duel-default-count').fill('6');await page.locator('#app-settings-shortcuts').click();
  assert.deepEqual(await page.locator('#duel-shortcut-fields input').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.dataset.duelBinding,n.value]))),savedBindings);
  await page.screenshot({path:path.join(evidence,'duel-shortcuts.png')});
  await page.locator('#duel-shortcut-save').click();await page.waitForFunction(()=>!document.querySelector('#duel-shortcut-dialog').open);
  assert(await page.locator('#app-settings-dialog').isVisible());assert.equal(await page.locator('#duel-default-count').inputValue(),'6');
  assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  assert.equal(await page.evaluate(async()=>(await api('/api/duel/settings')).hand_count),5);
  await page.locator('#app-settings-cancel').click();await page.waitForFunction(()=>duelUI.shortcutStatus?.registered?.length===4);
  const keys=await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered);assert.equal(keys.length,4);
  await page.keyboard.press('ArrowRight');assert.equal(await page.evaluate(()=>duelState().position.key),'main/s1');
  await page.keyboard.press(globalMods+'+'+globalKeys.custom);assert.equal(await page.evaluate(()=>duelState().position.key),'main/s2');
  assert(await application.evaluate(({globalShortcut},binding)=>globalShortcut.isRegistered(binding),globalMods+'+'+globalKeys.custom));
  await application.evaluate(()=>globalThis.tutorialAcceptance.invoke('forward'));await page.waitForFunction(()=>duelState().position.key==='main/s3');
  await page.locator('#duel-substeps [data-duel-stage="5"]').click();await stage('plans');assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  await tile.click();await stage('tutorial');assert.equal(await page.evaluate(()=>duelState().position.key),'main/s3');
  await enter('home');assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  await enter('duel');await stage('tutorial');await click('end');await stage('complete');assert.equal((await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered)).length,0);
  await click('new');await stage('mode');
  assert.equal(await page.evaluate(()=>duelState().operationMode),null);
  await page.locator('#app-settings').click();await page.locator('#duel-default-count').fill('4');await page.locator('#app-settings-save').click();await page.waitForFunction(()=>!document.querySelector('#app-settings-dialog').open);
  await click('bo1');await stage('function');await click('manual');await page.locator(`[data-duel-deck="${data.deck.id}"]`).click();await page.waitForFunction(()=>!duelUI.busy);await click('start-duel');await click('first');await stage('hand');assert.equal(await page.locator('.duel-slot').count(),4);
  await add(55144522);await add(55144522);await add(1184620);await add(1184620);await click('match');await tile.click();await stage('tutorial');
  await page.locator('#duel-substeps [data-duel-stage="4"]').click();await stage('hand');await page.locator('[data-duel-slot="0"]').click({button:'right'});assert.equal(await page.evaluate(()=>duelState().plan),null);
  await add(1184620);await click('match');await stage('plans');assert.equal(await page.locator('[data-duel-plan]').count(),0);
  await page.evaluate(async id=>{const saved=await api('/api/deck?id='+encodeURIComponent(id));await api('/api/decks',{...saved,tag_selection:{tag_ids:[],primary_ids:[]}});},data.deck.id);
  await enter('home');await enter('duel');await stage('deck');assert.equal(await page.evaluate(()=>duelState().result),null);
  for(const [file,bytes] of originals)assert(fs.readFileSync(file).equals(bytes),'Frozen plan unchanged: '+path.basename(file));
  const after=await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),data.deck.id);assert.deepEqual(after.deck,data.deck.deck);assert.deepEqual(after.representatives,data.deck.representatives);
  await enter('home');
  pass('Compact deck cases: three representatives saved/reopened/shared; tags only in hover; BO1 compact navigation, floating actions, direct order selection, marked card popover, right-click removal and remaining badges');
  pass('Visual duel tutorial: compact recorded actions, bounded step summaries with card details, immutable per-node board and zones, image plan previews with in-popover modes, mouse/keyboard highlight and key repeat, one shortcut binding in foreground/background and lifecycle release');
};
