'use strict';
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
const fs=require('node:fs');
module.exports=async({page,root,evidence,pass})=>{
  await page.evaluate(async()=>{flow.restarting=true;displayView('training');await syncNativeHost();});
  const service=require(path.join(root,'runtime','_trainer','service.json'));
  const layoutRequest=path.join(evidence,'modular-layout.request');
  const previewRequest=path.join(evidence,'modular-preview.request');
  let layoutBusy=false;
  const layoutTimer=setInterval(async()=>{
    if(layoutBusy||(!fs.existsSync(layoutRequest)&&!fs.existsSync(previewRequest)))return;layoutBusy=true;
    try{
      if(fs.existsSync(previewRequest)) {
        await page.evaluate(async()=>{await refreshHistory();await switchModule('modular');await refreshModular(true);});
        assert(await page.locator('.modular-route').count()>0);
        await page.screenshot({path:path.join(evidence,'modular-candidates.png')});
        await page.locator('#modular-field').scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(evidence,'modular-live-field.png'),preserveScroll:true});
        await page.evaluate(async()=>{await switchModule('expansion');displayView('training');await syncNativeHost();});
        fs.unlinkSync(previewRequest);
      }
      if(fs.existsSync(layoutRequest)) {
        await page.evaluate(async()=>{await refreshHistory();displayView('training');await syncNativeHost();});fs.unlinkSync(layoutRequest);
      }
    }catch(error){if(!page.isClosed())console.error('Modular test layout:',error.message);}finally{layoutBusy=false;}
  },100);
  const python=spawn('python',['-u',path.resolve(__dirname,'../tests/modular_engine_acceptance.py'),path.join(root,'runtime'),service.url,evidence],{windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  let output='';python.stdout.on('data',data=>{output+=data;process.stdout.write(data);});python.stderr.on('data',data=>{output+=data;process.stderr.write(data);});
  const code=await new Promise(resolve=>python.once('exit',resolve));
  clearInterval(layoutTimer);
  assert.equal(code,0,output.slice(-7000));
  const continuationFile=path.join(evidence,'modular-step9-continuation.json');
  if(fs.existsSync(continuationFile)) {
    const data=JSON.parse(fs.readFileSync(continuationFile,'utf8'));
    await page.evaluate(async data=>{
      await switchModule('duel');duelUI.state=newDuel();const s=duelState();
      s.hand=data.initial.cards.filter(c=>c.controller===0&&c.location===2).map(c=>c.code);
      s.plan=temporaryDuelPlan(data,data.result.candidates[0]);s.routes=duelPlanRoutes(s.plan);s.graph=DuelModel.graph(s.routes);
      const next=reviewNodes(s.plan).find(n=>n.kind==='step'&&n.forecast_index===0);
      s.position={key:'main/'+next.id,choice:0};s.stage=5;s.reached=5;s.forecast={showResults:false};renderDuel();
    },data);
    assert(await page.locator('.forecast-step .compact-summon').count()>0);
    assert(await page.locator('.forecast-step .chain-arrow').count()>0);
    assert(await page.locator('.forecast-step .location-icon svg').count()>0);
    await page.screenshot({path:path.join(evidence,'duel-combo3-step9-continuation.png')});
    await page.evaluate(()=>{duelUI.state=newDuel();});
    pass('Combo 3 continuation uses material pictures, summon and effect arrows, location maps and frozen prefix labels');
  }
  if(process.env.YGO_MODULAR_PIPELINE_ONLY==='1')await require('./duel-forecast-smoke.cjs')({page,root,evidence,pass});
  if(process.env.YGO_MODULAR_PLANNING_ONLY==='1')await require('./planning-preferences-smoke.cjs')({page,root,evidence,pass});
  if(process.env.YGO_MODULAR_FORECAST_ONLY==='1')await require('./duel-forecast-outcome-smoke.cjs')({page,evidence,pass});
  await page.evaluate(async()=>{await refreshHistory();flow.restarting=false;await switchModule('modular');});
  assert(await page.locator('#modular').isVisible());
  await page.screenshot({path:path.join(evidence,'modular.png')});
  pass('Modular routes use actual native decisions, disposable simulation and an isolated source library');
};
