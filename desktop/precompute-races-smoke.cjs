'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
module.exports=async({page,evidence,pass})=>{
  const source=JSON.parse(fs.readFileSync(path.join(evidence,'planning-preferences-source.json'),'utf8'));
  await page.evaluate(async source=>{
    await refreshHistory();await switchModule('duel');duelUI.state=newDuel();const s=duelState();
    s.deck=await api('/api/deck?id='+encodeURIComponent(source.deck));s.mode='BO1';s.operationMode='manual';s.first=true;s.count=5;s.hand=source.hand;
    s.result={matches:[]};s.stage=duelStages.plans;s.reached=duelStages.plans;
    const sources=(await api('/api/modular/library')).sources.filter(p=>Object.values(source.plans).includes(p.id));
    s.forecast={sources,selected:sources.map(p=>p.id),preference:'shortest',precise:false,goal:[],generation:0,slot:'opening'};
    s.plan=await api('/api/plan/'+source.plans.largest);s.plan.confirmed=2;window.preservedRaceTutorial=s.plan;
    renderDuel();
  },source);
  const history=await page.evaluate(()=>api('/api/history'));
  await page.waitForFunction(()=>duelState().forecast?.busy&&!!duelState().forecast?.id,null,{timeout:60000});
  const old=await page.evaluate(()=>{const f=duelState().forecast;return {job:f.job,version:f.version,id:f.id,candidate:f.data?.result?.candidates[0]?.id||'unused',slot:f.slot,preference:f.preference};});
  await page.evaluate(async source=>{
    const f=duelState().forecast;f.precise=true;await searchDuelBrain();
    f.precise=false;f.selected=[source.plans.shortest];await searchDuelBrain();
  },source);
  await page.waitForFunction(()=>!duelState().forecast.busy,null,{timeout:120000});
  const latest=await page.evaluate(()=>({data:duelState().forecast.data,error:duelState().forecast.error,id:duelState().forecast.id,job:duelState().forecast.job}));
  assert(latest.data?.result?.candidates?.length,JSON.stringify(latest));
  assert.notEqual(latest.id,old.id);assert.notEqual(latest.job,old.job);assert.equal(latest.data.result.coverage.total,1);assert.equal(latest.data.result.precise,false);
  const refusal=await page.evaluate(async old=>{try{await forecastRequest(duelState(),'plan-adopt',old);return '';}catch(error){return error.message;}},old);
  assert.match(refusal,/未完成|失效|释放|版本|变化/);
  await page.evaluate(async()=>{const f=duelState().forecast;f.selected=[];await searchDuelBrain();f.preference='cheapest';await searchDuelBrain();});
  const failed=await page.evaluate(()=>({data:duelState().forecast.data,job:duelState().forecast.job,error:duelState().forecast.error}));
  assert.equal(failed.data,null);assert.equal(failed.job,null);assert.match(failed.error,/来源/);
  await page.evaluate(async source=>{duelState().forecast.selected=[source.plans.shortest];await searchDuelBrain({refresh:true});},source);
  await page.waitForFunction(()=>!duelState().forecast.busy,null,{timeout:120000});
  assert(await page.evaluate(()=>!!duelState().forecast.data?.result?.candidates.length),await page.evaluate(()=>duelState().forecast.error));
  assert(await page.evaluate(()=>duelState().plan===preservedRaceTutorial&&duelState().plan.confirmed===2));
  const sid=await page.evaluate(()=>duelState().forecast.id);await page.evaluate(()=>endDuel());
  await page.waitForFunction(id=>api('/api/native/status?id='+id).then(s=>!s.ready),sid,{timeout:20000});
  assert.deepEqual(await page.evaluate(()=>api('/api/history')),history);
  fs.writeFileSync(path.join(evidence,'precompute-races.json'),JSON.stringify({old_job_rejected:true,restarted_native_session:true,source_count:1,retry_succeeded:true,tutorial_preserved:true,history_preserved:true},null,2));
  pass('Real precompute: in-flight setting changes, late-job rejection, failed-input preference switching, retry and cleanup preserve the existing tutorial');
};
