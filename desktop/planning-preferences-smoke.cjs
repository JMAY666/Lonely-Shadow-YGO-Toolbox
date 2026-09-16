'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
module.exports=async({page,root,evidence,pass})=>{
  const source=JSON.parse(fs.readFileSync(path.join(evidence,'planning-preferences-source.json'),'utf8')),requests=[];
  const record=request=>{if(request.url().endsWith('/api/modular/dispatch')&&request.method()==='POST')requests.push(request.postDataJSON());};page.on('request',record);
  await page.evaluate(async source=>{
    await refreshHistory();await switchModule('duel');duelUI.state=newDuel();const s=duelState();
    s.deck=await api('/api/deck?id='+encodeURIComponent(source.deck));s.mode='BO1';s.operationMode='manual';s.first=true;s.count=5;s.hand=source.hand;
    s.result={matches:[]};s.stage=duelStages.plans;s.reached=duelStages.plans;
    const sources=(await api('/api/modular/library')).sources.filter(p=>Object.values(source.plans).includes(p.id));
    s.forecast={sources,selected:sources.map(p=>p.id),preference:'shortest',precise:false,generation:0,showResults:true};renderDuel();
  },source);
  const results={};
  for(const preference of ['shortest','largest','balanced']){
    if(preference==='shortest')await page.locator('#duel-brain-search').click();
    else await page.locator('#duel-brain-preference').selectOption(preference);
    await page.waitForFunction(p=>!duelState().forecast.busy&&duelState().forecast.data?.result?.preference===p,preference,{timeout:120000});
    const result=await page.evaluate(()=>duelState().forecast.data.result);results[preference]=result;
    assert.equal(result.cache.result_hit,false,'Changing the preference must not return another preference\'s cached answer');
    assert.equal(result.coverage.total,3);assert.equal(result.coverage.checked,3);
    assert.equal(result.candidates[0].terminal_source.plan,source.plans[preference],preference);
    assert(new Set(result.candidates.map(c=>c.terminal_source?.plan)).size>=3,'All three feasible sources must be compared');
    if(result.limited)assert.match(await page.locator('#duel-brain-summary').textContent(),/搜索尚未完成/);
    await page.screenshot({path:path.join(evidence,'planning-'+preference+'.png')});
    pass(`Temporary ${preference} ranks the correct distinct marked end board after a fresh search`);
  }
  await page.locator('#duel-brain-search').click();
  await page.waitForFunction(()=>!duelState().forecast.busy&&!!duelState().forecast.data,null,{timeout:120000});
  const refreshed=await page.evaluate(()=>duelState().forecast.data.result);
  assert.equal(refreshed.cache.result_hit,false);assert(refreshed.cache.probe_hits>0);
  assert.equal(requests.filter(r=>r.intent==='plan').at(-1).refresh,true);
  await page.evaluate(async source=>{
    const f=duelState().forecast;
    f.sources=(await api('/api/modular/library')).sources.filter(p=>p.id===source.explicit);
    f.selected=[source.explicit];f.goal=[source.goal];f.preference='largest';renderDuel();
  },source);
  await page.locator('#duel-brain-search').click();
  await page.waitForFunction(()=>!duelState().forecast.busy&&!!duelState().forecast.data,null,{timeout:120000});
  const explicit=await page.evaluate(()=>duelState().forecast.data.result);
  assert(explicit.candidates[0].goal_met,'A reached marked subset cannot stop an explicit additional target');
  assert(explicit.candidates[0].terminal.cards.some(c=>c.code===source.goal&&c.controller===0&&c.location===4));
  assert.equal(explicit.candidates[0].evaluation.marked_cards,3,'Unmarked explicit field target does not silently become a source mark');
  const sid=await page.evaluate(()=>duelState().forecast.id);
  const journal=fs.readFileSync(path.join(root,'runtime/_trainer/sessions',sid,'native.jsonl'),'utf8');
  assert(!journal.split(/\r?\n/).filter(Boolean).map(JSON.parse).some(r=>r.kind==='response'),'Planning never submits live responses');
  fs.writeFileSync(path.join(evidence,'planning-preferences-results.json'),JSON.stringify(results,null,2));
  await page.evaluate(()=>dropDuelForecast(duelState()));
  await page.waitForFunction(id=>api('/api/native/status?id='+id).then(s=>!s.ready),sid,{timeout:20000});
  page.off('request',record);pass('Manual regeneration bypasses candidate answers, reuses only verified probes and preserves the live input journal');
};
