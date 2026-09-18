'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
module.exports=async({page,root,evidence,pass})=>{
  const source=JSON.parse(fs.readFileSync(path.join(evidence,'planning-preferences-source.json'),'utf8')),requests=[];
  const baseline=process.env.YGO_PRECOMPUTE_BASELINE==='1';
  const record=request=>{if(request.url().endsWith('/api/modular/dispatch')&&request.method()==='POST')requests.push(request.postDataJSON());};page.on('request',record);
  const metricsFile=path.join(evidence,'planning-resource-metrics.json');
  const sampler=spawn('python',[path.resolve(__dirname,'../scripts/planning-metrics.py'),root,metricsFile],{windowsHide:true,stdio:'inherit'});
  const finished=new Promise(resolve=>sampler.once('exit',resolve));
  const results={},timings={};
  try {
    await page.evaluate(async ({source,baseline})=>{
      await refreshHistory();await switchModule('duel');duelUI.state=newDuel();const s=duelState();
      s.deck=await api('/api/deck?id='+encodeURIComponent(source.deck));s.mode='BO1';s.operationMode='manual';s.first=true;s.count=5;s.hand=source.hand;s.planSort='shortest';
      s.result={matches:[]};s.stage=duelStages.plans;s.reached=duelStages.plans;
      const sources=(await api('/api/modular/library')).sources.filter(p=>Object.values(source.plans).includes(p.id));
      s.forecast={sources,selected:sources.map(p=>p.id),preference:'shortest',precise:false,goal:[],generation:0,showResults:baseline,slot:'opening'};
      window.planningLag=[];let last=performance.now();window.planningLagTimer=setInterval(()=>{const now=performance.now();planningLag.push(Math.max(0,now-last-100));last=now;},100);
      window.preparationStartedAt=performance.now();renderDuel();
    },{source,baseline});
    const started=Date.now();
    if(!baseline){
      await page.waitForFunction(()=>!!duelState().forecast?.jobState,null,{timeout:30000});
      assert.equal(await page.locator('#duel-brain-search').count(),0,'Preparation starts without opening the panel');
      assert.deepEqual(Object.keys(await page.evaluate(()=>duelState().forecast.jobState.preferences)).sort(),['balanced','cheapest','largest','shortest']);
      await page.waitForFunction(()=>!duelState().forecast.busy&&!!duelState().forecast.data,null,{timeout:180000});
      timings.background_ms=await page.evaluate(()=>performance.now()-window.preparationStartedAt);
      timings.background_service_seconds=await page.evaluate(()=>duelState().forecast.jobState.background_seconds);
    }
    for(const preference of ['shortest','largest','balanced','cheapest']){
      const click=Date.now();
      if(preference==='shortest'){
        if(baseline)await page.evaluate(()=>searchDuelBrain({refresh:true}));
        else await page.evaluate(()=>launchModularFromDuel());
      }else await page.locator('#duel-brain-preference').selectOption(preference);
      await page.waitForFunction(p=>!duelState().forecast.busy&&duelState().forecast.data?.result?.preference===p,preference,{timeout:180000});
      timings[preference+'_wait_ms']=Date.now()-click;
      const result=await page.evaluate(()=>duelState().forecast.data.result);results[preference]=result;
      assert.equal(result.coverage.total,3);assert.equal(result.coverage.checked,3);
      if(['shortest','largest'].includes(preference))assert.equal(result.candidates[0].terminal_source.plan,source.plans[preference],preference);
      if(preference==='cheapest')assert.equal(result.candidates[0].resource_cost.hand,1);
      if(preference==='balanced')assert.equal(result.candidates[0].ranking.average,Math.max(...result.candidates.map(c=>c.ranking.average)));
      assert(result.candidates.every(c=>c.resource_cost.status==='complete'&&c.resource_cost.main===0&&c.resource_cost.extra===0));
      assert(new Set(result.candidates.map(c=>c.terminal_source?.plan)).size>=3,'Each preference is evaluated from the full discovered pool');
      if(result.limited)assert.match(await page.locator('#duel-brain-summary').textContent(),/搜索尚未完成/);
      await page.screenshot({path:path.join(evidence,'planning-'+preference+'.png')});
      pass(`Temporary ${preference}: distinct scores and truthful search coverage`);
    }
    if(!baseline){
      assert.equal(requests.filter(r=>r.intent==='plan-prepare').length,1,'All preferences use one prepared search');
      const count=requests.filter(r=>r.intent==='plan-prepare').length;
      const repeat=Date.now();await page.locator('[data-duel-action="modular"]').click();await page.locator('#duel-brain-preference').selectOption('largest');
      await page.waitForFunction(()=>duelState().forecast.data?.result?.preference==='largest');
      timings.repeat_and_cached_switch_ms=Date.now()-repeat;
      assert.equal(requests.filter(r=>r.intent==='plan-prepare').length,count);
    }
    const refreshedAt=Date.now();await page.locator('#duel-brain-search').click();
    await page.waitForFunction(()=>!duelState().forecast.busy&&!!duelState().forecast.data,null,{timeout:180000});
    const refreshed=await page.evaluate(()=>duelState().forecast.data.result);
    timings.refresh_ms=Date.now()-refreshedAt;timings.refresh_cache=refreshed.cache;
    assert.equal(refreshed.cache.result_hit,false);assert(refreshed.cache.probe_hits>0);
    const sid=await page.evaluate(()=>duelState().forecast.id);
    const journal=fs.readFileSync(path.join(root,'runtime/_trainer/sessions',sid,'native.jsonl'),'utf8');
    assert(!journal.split(/\r?\n/).filter(Boolean).map(JSON.parse).some(r=>r.kind==='response'),'Planning never submits live responses');
    timings.renderer_lag=await page.evaluate(()=>({max_ms:Math.max(...planningLag),mean_ms:planningLag.reduce((a,b)=>a+b,0)/planningLag.length}));
    fs.writeFileSync(path.join(evidence,'planning-preferences-results.json'),JSON.stringify(results,null,2));
    fs.writeFileSync(path.join(evidence,'planning-precompute-timing.json'),JSON.stringify(timings,null,2));
    await page.evaluate(()=>dropDuelForecast(duelState()));
    await page.waitForFunction(id=>api('/api/native/status?id='+id).then(s=>!s.ready),sid,{timeout:20000});
    pass('Background preparation, cached switches and retry preserve the real input journal');
  }finally{
    fs.writeFileSync(metricsFile.replace(/\.json$/,'.stop'),'stop');await finished;
    await page.evaluate(()=>{clearInterval(window.planningLagTimer);dropDuelForecast(duelState());});page.off('request',record);
  }
};
