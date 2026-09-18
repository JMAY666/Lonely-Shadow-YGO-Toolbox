'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
module.exports=async({page,root,evidence,pass})=>{
  assert(path.basename(root).startsWith('desktop-check-')&&root.includes('-modular'));
  const seed=JSON.parse(fs.readFileSync(path.join(evidence,'pipeline-source.json'),'utf8'));
  const original=JSON.parse(fs.readFileSync(path.join(root,'runtime/_trainer/plans',seed.plan+'.json'),'utf8'));
  const tags=await page.evaluate(async()=>{
    const result=[];
    for(const name of ['TEST ONLY secondary source','TEST ONLY unrelated source']){
      const all=await api('/api/tags');
      result.push(all.tags.find(t=>t.name===name)?.id||(await api('/api/tags/save',{name,revision:all.revision})).tag.id);
    }
    return result;
  });
  const fixture={secondary:crypto.randomUUID(),unrelated:crypto.randomUUID(),untagged:crypto.randomUUID()};
  for(const [name,id] of Object.entries(fixture)){
    const tag_ids=name==='untagged'?[]:[tags[name==='secondary'?0:1]];
    fs.writeFileSync(path.join(root,'runtime/_trainer/plans',id+'.json'),JSON.stringify({...original,id,
      name:'TEST ONLY '+name,classification:{mode:'manual',tag_ids,primary_ids:[]}}));
  }
  for(const id of [seed.deck,seed.followup.deck])await page.evaluate(async({id,tag})=>{
    const deck=await api('/api/deck?id='+encodeURIComponent(id));
    deck.tag_selection.tag_ids.push(tag);await api('/api/decks',deck);
  },{id,tag:tags[0]});
  const result=await page.evaluate(async({id,fixture})=>{
    const deck=await api('/api/deck?id='+encodeURIComponent(id));
    const library=await api('/api/modular/library?deck_id='+encodeURIComponent(id)+'&revision='+encodeURIComponent(deck.revision));
    const refused=[];
    for(const source of [fixture.unrelated,fixture.untagged]){
      try{await modularDispatch('duel','plan-prepare',{session:'TEST ONLY source filtering',slot:'opening',
        deck_id:id,revision:deck.revision,hand_count:3,hand:[1184620,1184620,1184620],sources:[source]});refused.push('');}
      catch(error){refused.push(error.message);}
    }
    return {ids:library.sources.map(s=>s.id),refused};
  },{id:seed.deck,fixture});
  assert(result.ids.includes(seed.plan));assert(result.ids.includes(fixture.secondary));
  assert(!result.ids.includes(fixture.unrelated));assert(!result.ids.includes(fixture.untagged));
  assert(result.refused.every(message=>message.includes('Tag')));
  fs.writeFileSync(path.join(evidence,'forecast-source-tags.json'),JSON.stringify(fixture,null,2));
  pass('Deck-scoped API includes primary and secondary sources, rejects unrelated and untagged real recorded sources before calculation');
};

module.exports.verify=async({page,evidence,automatic=false})=>{
  const prefix=automatic?'auto-duel':'duel',panel='#'+prefix+'-brain-routes';
  assert.deepEqual(await page.locator('#'+prefix+'-brain-preference option').allTextContents(),['花费最少','终场最大','步骤最少','平均']);
  assert.equal(await page.locator('#'+prefix+'-brain-preference').inputValue(),'largest');
  const fixture=JSON.parse(fs.readFileSync(path.join(evidence,'forecast-source-tags.json'),'utf8'));
  const selected=await page.evaluate(automatic=>{
    const f=(automatic?autoDuelState():duelState()).forecast;
    return {sources:f.sources.map(s=>s.id),selected:f.selected,cost:f.data.result.candidates[0].resource_cost};
  },automatic);
  assert.equal(selected.cost.status,'complete');assert.equal(selected.cost.hand,1);
  assert.equal(selected.cost.main,0);assert.equal(selected.cost.extra,0);
  for(const ids of [selected.sources,selected.selected]){
    assert(ids.includes(fixture.secondary));assert(!ids.includes(fixture.unrelated));assert(!ids.includes(fixture.untagged));
  }
  const cards=page.locator(panel+' .forecast-route');assert(await cards.count()>0);
  const sizes=await cards.evaluateAll(rows=>rows.map(row=>({height:row.getBoundingClientRect().height,width:row.getBoundingClientRect().width})));
  assert(sizes.every(({height,width})=>height<=360&&width<=380),'Routes use compact parallel tiles: '+JSON.stringify(sizes));
  assert(await cards.first().locator('.forecast-terminal-cards img').first().isVisible(),'Terminal pictures are visible without expanding details');
  assert.equal(await page.locator(panel+' .forecast-route-details[open]').count(),0);
  const first=page.locator(panel+' .forecast-route-details').first();
  await first.locator('summary').first().click();
  await page.waitForFunction(automatic=>(automatic?autoDuelState():duelState()).forecast.expandedCandidates?.length===1,automatic);
  await page.evaluate(automatic=>automatic?autoPaintForecastResults():paintForecastResults(),automatic);
  assert.equal(await first.getAttribute('open'),'');
  assert(await first.locator('.duel-summary-cards').isVisible());
  await first.locator('summary').first().click();
  await page.waitForFunction(automatic=>(automatic?autoDuelState():duelState()).forecast.expandedCandidates?.length===0,automatic);
  await page.locator(panel).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(evidence,prefix+'-compact-routes.png'),preserveScroll:true});
};
