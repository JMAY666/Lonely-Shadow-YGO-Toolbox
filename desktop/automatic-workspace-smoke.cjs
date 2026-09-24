'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const stable=value=>Array.isArray(value)?value.map(stable):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])])):value;
module.exports=async({page,application,root,evidence,pass})=>{
  page.setDefaultTimeout(20000);
  const id=crypto.randomUUID().replaceAll('-',''),hand=[55144522,55144522,1184620,1184620,1184620];
  const data=await page.evaluate(async id=>{
    const tags=await api('/api/tags'),tag=(await api('/api/tags/save',{name:'自动工作区验收 '+id,aliases:[],card_ids:[55144522],revision:tags.revision})).tag;
    const deck=await api('/api/decks',{name:'自动工作区来源 '+id,deck:{main:[...Array(20).fill(55144522),...Array(20).fill(1184620)],extra:[23995346],side:[]},tag_selection:{tag_ids:[tag.id],primary_ids:[tag.id]}});
    const catalog=Object.fromEntries(await Promise.all([55144522,1184620,23995346].map(async c=>[c,await card(c)])));
    const suffix=await window.trainerDesktop.tutorialSaveSettings({back:'Control+Alt+Shift+F9',forward:'Control+Alt+Shift+F10',up:'Control+Alt+Shift+F11',down:'Control+Alt+Shift+F12',end:''});duelUI.bindings=suffix.bindings;
    return {deck,tag,catalog};
  },id);
  const state={cards:[{instance_id:1,code:1184620,name:data.catalog[1184620].name,controller:0,owner:0,location:4,sequence:0,position:1,identity_known:true}],lp:[8000,8000],phase:4,turn:1};
  const row=(code,count)=>({code,count,name:data.catalog[code]?.name,constraint:''});
  const action={id:'10:0',kind:'operation',message:61,cards:state.cards,evidence_refs:['10:0'],summary:'合成测试通常召唤',results:[]};
  const plan={id:crypto.randomUUID(),name:'自动区域教程 '+id,plan_stage:'saved',saved_ms:Date.now(),edit_revision:0,deck:data.deck.deck,deck_name:data.deck.name,
    classification:{mode:'manual',tag_ids:[data.tag.id],primary_ids:[data.tag.id]},catalog:data.catalog,
    expansion:{notes:'自动区域的合成显示验收；不代表规则引擎验证过的展开。'},
    requirements:{main:[row(55144522,2)],extra:[],opening:[row(55144522,2)],warnings:[],final:{notes:'独立自动教程终场'}},
    events:[action],actions:[action],review:{complete:true,nodes:[{id:'initial',kind:'initial',action_ids:[],state},{id:'s1',kind:'step',number:1,action_ids:['10:0'],seq_end:10,state},{id:'s2',kind:'step',number:2,action_ids:['10:0'],seq_end:20,state},{id:'final',kind:'final',action_ids:[],state}]},
    branches:[],annotations:{nodes:{s1:{name:'自动步骤一',notes:'自动区域备注'}},cards:{},effects:{},final_marks:{1:{marked:true,effects:{}}}},final_state:state};
  const branch={...structuredClone(plan),id:'branch-report',name:'自动分支'};
  branch.actions=[{...action,id:'30:0',evidence_refs:['30:0']}];branch.events=branch.actions;
  branch.review.nodes=[branch.review.nodes[0],{...branch.review.nodes[1],id:'b1',number:3,seq_end:30,action_ids:['30:0']},branch.review.nodes.at(-1)];
  plan.branches=[{id:'branch',name:'自动可用分支',valid:true,source:{node_id:'s1',seq:10,timing:'结算后'},report:branch,conditions:{hand:[]}}];
  for(const p of [plan,branch]){
    const nodes=p.review.nodes;nodes.forEach(n=>{n.module_id='fixture:'+n.id;});
    p.review.module_graph={schema:1,modules:nodes.map((n,i)=>({id:n.module_id,seq:i,player:0,state:n.state})),
      connections:nodes.slice(1).map((n,i)=>({from:nodes[i].module_id,to:n.module_id,response_refs:[i],decision:{selection:[]}})),step_order:nodes.map(n=>n.id),step_links:nodes.slice(1).map((n,i)=>({from:nodes[i].id,to:n.id,from_module:nodes[i].module_id,to_module:n.module_id,module_path:[nodes[i].module_id,n.module_id],status:'recorded'}))};
  }
  const planPath=path.join(root,'runtime/_trainer/plans',plan.id+'.json');fs.writeFileSync(planPath,JSON.stringify(plan));const original=fs.readFileSync(planPath);
  const input={name:data.deck.name,deck:data.deck.deck,tag_selection:data.deck.tag_selection,hand,round_id:'round-'+id,snapshot_id:'snapshot-'+id,turn_order:'first'};
  const revision=crypto.createHash('sha256').update(JSON.stringify(stable(input))).digest('hex');
  const folder=path.join(root,'runtime/_trainer/automatic-contexts');fs.mkdirSync(folder,{recursive:true});
  fs.writeFileSync(path.join(folder,id+'.json'),JSON.stringify({id,schema:1,created_ms:Date.now(),input,revision,planner_ids:[],closed:false,selected_plan:null}));
  const deck=await page.evaluate(id=>api('/api/deck?id=automatic/'+id),id);
  const frame={monitor_id:'monitor-'+id,round_id:input.round_id,revision:1,phase:'detected',detected_order:'first',confirmed:{order:'first',source:'automatic'},opening:{status:'ready',cards:hand,snapshot_id:input.snapshot_id,confirmed:null}};
  const manualBefore=await page.evaluate(async({data,frame,hand})=>{
    await switchModule('duel');await startNewDuel();const s=duelState();
    s.deck=data.deck;s.hand=[1184620,55144522];s.count=2;s.result={matches:[],reason:'手动独立结果'};s.plan={id:'manual-preserved'};s.position={key:'manual-position',choice:1};s.planSort='largest';s.favoritesOnly=true;s.manualReached=6;s.session='manual-sentinel';
    s.operationMode='automatic';s.mode='BO1';s.stage=4;s.reached=4;
    Object.assign(s.automatic,{deck:{name:data.deck.name,deck:data.deck.deck},name:data.deck.name,fresh:true,tagIds:[data.tag.id],primaryIds:[data.tag.id],order:DuelOrder.create(frame)});renderDuel();
    return JSON.stringify([s.deck,s.hand,s.count,s.result,s.plan,s.position,s.planSort,s.favoritesOnly,s.session]);
  },{data,frame,hand});
  await page.route('**/api/ygopro/order/poll',route=>route.fulfill({json:frame}));
  await page.route('**/api/ygopro/opening/confirm',route=>{frame.opening.confirmed={snapshot_id:input.snapshot_id,cards:hand};return route.fulfill({json:frame});});
  await page.route('**/api/automatic-duel/context',route=>route.fulfill({json:{context_id:id,round_id:input.round_id,snapshot_id:input.snapshot_id,deck,hand}}));
  const click=async action=>{await page.locator(`[data-auto-duel-action="${action}"]`).click();await page.waitForFunction(()=>!autoDuelState()?.busy);};
  try {
    await page.locator('[data-duel-action="confirm-opening"]').click();await page.waitForFunction(()=>duelState().stage===5&&!duelUI.busy&&!!autoDuelState()?.result);
    assert.equal(await page.locator('#auto-duel-plans').count(),1);assert.equal(await page.locator('[data-duel-plan]').count(),0);
    assert.equal(await page.locator('[data-auto-duel-plan]').count(),1);assert.equal(await page.evaluate(()=>autoDuelState().plan),null);
    await page.locator('#auto-duel-plan-sort').selectOption('balanced');assert.equal(await page.evaluate(()=>duelState().planSort),'largest');
    await page.locator('[data-auto-plan-favorite]').click();await page.waitForFunction(()=>!autoDuelState().busy);
    await click('favorites-only');assert.equal(await page.locator('.auto-duel-plan-tile.is-favorite').count(),1);
    await page.locator('[data-auto-duel-plan]').hover();await page.waitForFunction(()=>!document.querySelector('#auto-duel-preview').hidden);
    await page.locator('[data-auto-preview-mode="detailed"]').click();assert.match(await page.locator('#auto-duel-preview-content').textContent(),/自动可用分支/);
    await page.locator('#auto-duel-preview-close').click();await page.screenshot({path:path.join(evidence,'automatic-plan-workspace.png')});
    await page.locator('[data-auto-duel-plan]').press('Enter');await page.waitForFunction(()=>duelState().stage===6&&!autoDuelState().busy);
    assert.equal(await page.locator('#auto-duel-tutorial').count(),1);assert.equal(await page.locator('#duel-graph-scroll').count(),0);
    assert.equal(await page.evaluate(()=>autoDuelState().position.key),'main/s1');
    assert.equal(await page.locator('.auto-duel-node.current').getAttribute('data-current-node'),'main/s1');
    await require('./duel-step-view-smoke.cjs')({page,application,evidence,pass,automatic:true});
    await click('forward-step');assert.equal(await page.evaluate(()=>autoDuelState().position.key),'main/s2');await click('back-step');
    await page.locator('[data-auto-duel-choice="1"]').click();await click('forward-step');assert.equal(await page.evaluate(()=>autoDuelState().position.key),'branch/b1');
    await page.locator('[data-auto-duel-node="main/s1"]').click();
    await page.evaluate(()=>syncAutoDuelShortcuts());
    const shortcut=await application.evaluate(()=>globalThis.tutorialAcceptance.status());assert.equal(shortcut.registered.length,4,JSON.stringify(shortcut));
    await application.evaluate(()=>globalThis.tutorialAcceptance.invoke('forward'));
    await page.waitForFunction(()=>autoDuelState().position.key==='main/s2',null,{timeout:5000});
    await page.locator('#duel-substeps').hover();await page.locator('[data-auto-duel-node="main/s1"]').hover();await page.waitForFunction(()=>!document.querySelector('#auto-duel-preview').hidden);
    assert(await page.locator('#auto-duel-preview .duel-step-peek-row').count()>0);
    assert.equal(await page.locator('#auto-duel-preview .log-action').count(),0);
    assert(await page.locator('#auto-duel-preview').evaluate(el=>el.scrollHeight<=el.clientHeight+1));
    await page.screenshot({path:path.join(evidence,'automatic-step-preview.png'),preserveScroll:true});
    await page.locator('#auto-duel-preview-close').click();
    const separator=page.locator('#auto-duel-graph-resize');await separator.focus();await page.keyboard.press('ArrowDown');
    assert((await page.locator('#auto-duel-graph-scroll').boundingBox()).height>=300);
    await page.screenshot({path:path.join(evidence,'automatic-tutorial-workspace.png')});
    await click('toggle-shortcuts');assert.equal(await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered.length),0);await click('toggle-shortcuts');
    await page.evaluate(()=>switchModule('home'));
    assert.equal(await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered.length),0);
    assert.equal(await page.evaluate(()=>{const event=new KeyboardEvent('keydown',{key:'F10',ctrlKey:true,altKey:true,shiftKey:true,bubbles:true,cancelable:true});document.body.dispatchEvent(event);return event.defaultPrevented;}),false,'Inactive automatic tutorial does not intercept another module keyboard');
    await page.evaluate(()=>switchModule('duel'));assert.equal(await page.evaluate(()=>autoDuelState().position.key),'main/s2');
    await page.locator('#duel-steps [data-duel-stage="1"]').click();await page.locator('[data-duel-function-page="choice"]').click();await page.locator('[data-duel-action="manual"]').click();await page.waitForFunction(()=>!duelUI.busy);
    assert.equal(await page.evaluate(()=>JSON.stringify([duelState().deck,duelState().hand,duelState().count,duelState().result,duelState().plan,duelState().position,duelState().planSort,duelState().favoritesOnly,duelState().session])),manualBefore);
    await page.locator('#duel-steps [data-duel-stage="1"]').click();await page.locator('[data-duel-action="automatic"]').click();await page.waitForFunction(()=>!duelUI.busy);
    await page.locator('#duel-steps [data-duel-stage="4"]').click();await page.locator('[data-duel-stage="6"]').click();
    assert.equal(await page.evaluate(()=>autoDuelState().position.key),'main/s2');
    await require('./duel-follow-smoke.cjs')({page,application,evidence,pass});
    await click('end');await page.waitForFunction(()=>duelState().stage===7);assert.equal(await application.evaluate(()=>globalThis.tutorialAcceptance.status().registered.length),0);
    assert(fs.readFileSync(planPath).equals(original),'Original saved plan stays byte-identical');
    assert.equal(await page.evaluate(()=>duelState().position.key),'manual-position');
    pass('Independent automatic plan/tutorial regions: real matching/select API, sorting/favorites, detailed preview, branches, graph resize, IPC shortcuts, mode roundtrip, source preservation and isolated progress');
  }catch(error){await page.screenshot({path:path.join(evidence,'automatic-workspace-failure.png'),preserveScroll:true});throw error;}finally{
    await page.unroute('**/api/ygopro/order/poll');await page.unroute('**/api/ygopro/opening/confirm');await page.unroute('**/api/automatic-duel/context');
    await page.evaluate(()=>startNewDuel());
  }
};
