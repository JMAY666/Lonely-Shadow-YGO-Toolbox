'use strict';
// Real rules-engine acceptance over isolated, recorded sources from the pipeline suite.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const stable=value=>Array.isArray(value)?value.map(stable):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])])):value;
module.exports=async({page,root,evidence,pass})=>{
  const source=JSON.parse(fs.readFileSync(path.join(evidence,'pipeline-source.json'),'utf8'));
  const requests=[],observe=request=>{if(request.url().endsWith('/api/automatic-duel/dispatch'))requests.push(request.postDataJSON());};
  page.on('request',observe);
  const setup=async(seed,hand,tutorial=false)=>{
    const deck=await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),seed.deck),id=crypto.randomUUID().replaceAll('-','');
    const input={name:deck.name,deck:deck.deck,tag_selection:deck.tag_selection,hand,round_id:'engine-'+id,snapshot_id:'opening-'+id,turn_order:'first'};
    const revision=crypto.createHash('sha256').update(JSON.stringify(stable(input))).digest('hex'),folder=path.join(root,'runtime/_trainer/automatic-contexts');fs.mkdirSync(folder,{recursive:true});
    fs.writeFileSync(path.join(folder,id+'.json'),JSON.stringify({id,schema:1,created_ms:Date.now(),input,revision,planner_ids:[],closed:false,selected_plan:null}));
    await page.evaluate(async({id,input,seed,tutorial})=>{
      await switchModule('duel');await startNewDuel();const s=duelState();
      const context={context_id:id,round_id:input.round_id,snapshot_id:input.snapshot_id,deck:await api('/api/deck?id=automatic/'+id),hand:input.hand};
      s.operationMode='automatic';s.mode='BO1';s.automatic.workspace=AutoDuelModel.create(context);
      s.automatic.order=DuelOrder.create({monitor_id:'engine-test',round_id:input.round_id,phase:'detected',detected_order:'first',confirmed:{order:'first',source:'automatic'},opening:{status:'ready',snapshot_id:input.snapshot_id,cards:input.hand,confirmed:{snapshot_id:input.snapshot_id,cards:input.hand}}});
      const a=autoDuelState();a.result=await api('/api/automatic-duel/match',{context_id:id});
      if(tutorial){a.plan=await api('/api/plan/'+seed.plan);a.routes=duelPlanRoutes(a.plan);a.graph=DuelModel.graph(a.routes);a.position={key:a.graph.start,choice:0};}
      s.stage=tutorial?6:5;s.reached=s.stage;a.stage=s.stage;a.reached=s.stage;renderDuel();
    },{id,input,seed,tutorial});
    return id;
  };
  const generate=async()=>{
    await page.locator('[data-auto-duel-action="modular"]').click();
    await page.waitForFunction(()=>autoDuelState().forecast&&!autoDuelState().forecast.busy,null,{timeout:90000});
    const value=await page.evaluate(()=>({data:autoDuelState().forecast.data,error:autoDuelState().forecast.error}));
    assert(value.data?.result?.candidates?.length,JSON.stringify(value));return value.data;
  };
  const history=await page.evaluate(()=>api('/api/history'));
  const sourcePaths=[source.plan,source.followup.plan].map(id=>path.join(root,'runtime/_trainer/plans',id+'.json'));
  const before=sourcePaths.map(p=>fs.readFileSync(p));
  try{
    const id=await setup(source,Array(5).fill(1184620));
    const opening=await generate();assert.equal(opening.confirmed,0);assert.equal(opening.anchor,null);
    await require('./forecast-source-tags-smoke.cjs').verify({page,evidence,automatic:true});
    assert.equal((await page.evaluate(id=>api('/api/native/status?id='+id),opening.id)).visible,false);
    const journal=path.join(root,'runtime/_trainer/sessions',opening.id,'native.jsonl'),nativeBefore=fs.readFileSync(journal);
    const refusal=await page.evaluate(async id=>{try{await modularDispatch('duel','plan-close',{id});return '';}catch(e){return e.message;}},opening.id);
    assert.match(refusal,/其他流程/,'Manual workflow cannot close an automatic forecast');
    await page.locator('#auto-duel-brain-preference').selectOption('balanced');await page.waitForFunction(()=>!autoDuelState().forecast.busy&&autoDuelState().forecast.data?.result?.preference==='balanced');
    assert.equal(await page.evaluate(()=>autoDuelState().forecast.data.result.cache.prepared_hit),true);
    await page.locator('[data-auto-duel-adopt]').first().click();await page.waitForFunction(()=>autoDuelState().plan?.temporary&&duelState().stage===6);
    assert(await page.locator('#auto-duel-tutorial .forecast-step .location-icon').count()>0);
    await page.locator('[data-auto-duel-node="main/final"]').click();await page.waitForFunction(()=>autoDuelState().plan.confirmed===1);
    assert(fs.readFileSync(journal).equals(nativeBefore),'Tutorial confirmation never sends live engine inputs');
    await page.locator('[data-auto-duel-action="back-step"]').click();
    await page.locator('[data-auto-duel-action="report-outcome"]').click();
    await page.locator('#auto-duel-observation-kind').selectOption('mill');await page.locator('#auto-duel-observation-query').fill('1184620');
    await page.locator('#auto-duel-observation [data-observation-code="1184620"]').click();await page.locator('#auto-duel-observation-submit').click();
    await page.waitForFunction(()=>document.querySelector('#auto-duel-observation-error').textContent.includes('不符'));
    assert.equal(await page.evaluate(()=>autoDuelState().plan.confirmed),1);await page.locator('#auto-duel-observation-cancel').click();
    await page.screenshot({path:path.join(evidence,'automatic-temporary-plan.png')});
    await page.locator('[data-auto-duel-action="end"]').click();await page.waitForFunction(()=>duelState().stage===7);
    await page.waitForFunction(id=>api('/api/native/status?id='+id).then(s=>!s.ready),opening.id,{timeout:20000});
    assert.equal(JSON.parse(fs.readFileSync(path.join(root,'runtime/_trainer/automatic-contexts',id+'.json'))).closed,true);
    await setup(source.followup,[1184620,55144522,55144522,1184620,1184620],true);
    const anchor=await page.evaluate(()=>autoDuelNodeSource(autoDuelState().graph.nodes.find(n=>n.key===autoDuelState().position.key)).node.id);
    const continuation=await generate();assert.equal(continuation.anchor.node,anchor);assert(continuation.confirmed>0);
    assert(!continuation.result.candidates[0].steps.some(s=>(s.bound_decision||s.decision).selection.some(c=>c.kind==='summon')));
    await page.locator('[data-auto-duel-adopt]').first().click();await page.waitForFunction(()=>autoDuelState().plan?.temporary);
    assert.equal(await page.evaluate(()=>autoDuelState().plan.confirmed),1);
    await page.locator('#duel-substeps [data-duel-stage="5"]').click();assert.equal(await page.locator('#auto-duel-modular-status').count(),0);
    await page.locator('#duel-substeps [data-duel-stage="6"]').click();const preserved=await generate();assert.equal(preserved.id,continuation.id);
    await page.locator('#duel-substeps [data-duel-stage="5"]').click();const restarted=await generate();
    assert.notEqual(restarted.id,continuation.id);assert.equal(restarted.confirmed,0);assert.equal(restarted.prefix.length,0);assert.equal(restarted.anchor,null);
    assert(restarted.result.candidates.some(c=>c.steps.some(s=>(s.bound_decision||s.decision).selection.some(c=>c.kind==='summon'))));
    assert.equal((await page.evaluate(id=>api('/api/native/status?id='+id),continuation.id)).ready,true,'Opening preparation preserves the confirmed tutorial');
    await page.screenshot({path:path.join(evidence,'automatic-opening-regeneration.png')});
    await page.evaluate(()=>endAutoDuel());
    await page.waitForFunction(id=>api('/api/native/status?id='+id).then(s=>!s.ready),restarted.id,{timeout:20000});
    assert.deepEqual(await page.evaluate(()=>api('/api/history')),history);
    sourcePaths.forEach((p,i)=>assert(fs.readFileSync(p).equals(before[i])));
    assert(!requests.some(r=>['auto','execute'].includes(r.intent)));
    pass('Automatic five-card snapshot: real background engine generation, preference search, independent adoption/confirmation/observation, owned-session boundary, saved-step continuation and opening regeneration; sources and journals preserved');
  }finally{page.off('request',observe);await page.evaluate(()=>startNewDuel());}
};
