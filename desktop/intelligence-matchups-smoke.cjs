'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

module.exports=async({page,application,evidence,pass})=>{
  page.setDefaultTimeout(30000);
  const action=name=>page.locator(`[data-intel-action="${name}"]`).click();
  const field=name=>page.locator(`[data-intel-field="${name}"]`);
  const resize=async(width,height)=>{
    await application.evaluate(({BrowserWindow},size)=>{const win=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());win.setMinimumSize(0,0);win.setContentSize(size.width,size.height);},{width,height});
    await page.waitForFunction(size=>innerWidth===size.width&&innerHeight===size.height,{width,height});
  };
  await page.evaluate(async()=>{
    let data=await api('/api/intelligence');
    data=await api('/api/intelligence',{revision:data.revision,op:'topic.save',value:{name:'验收个人主题',tag_ids:[],note:''}});
    await api('/api/intelligence',{revision:data.revision,op:'record.save',value:{topic_id:data.saved_id,title:'验收个人断点',note:'原有手写资料',steps:[{opponent:55144522,action:'对手发动效果',timing:'效果发动时',condition:'核对具体卡文',note:'',responses:[{mode:'alternative',cards:[14558127],method:'单独应对',condition:'满足发动条件',expected:'核对后使用',note:''}]}]}});
  });
  await page.locator('#module-intelligence').click();await page.waitForFunction(()=>moduleUI.current==='intelligence'&&!moduleUI.switching);
  await page.locator('[data-intel-tab="records"]').click();
  assert(await field('title').isVisible(),'Existing personal records keep their default editing workflow');
  await page.route('**/api/intelligence',route=>route.request().method()==='POST'?route.fulfill({status:500,json:{error:'isolated import failure'}}):route.continue(),{times:1});
  await action('import-matchups');await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.includes('保存失败'));
  assert.equal(await field('title').inputValue(),'验收个人断点');assert.equal(await page.evaluate(()=>Object.keys(intelUI.data.records).length),1);
  await action('import-matchups');
  await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.startsWith('已导入主流对策'));
  const imported=await page.evaluate(()=>Object.values(intelUI.data.records).filter(record=>record.research));
  assert(imported.length>0);assert(imported.some(record=>record.research.format==='OCG'));assert(imported.some(record=>record.research.format==='Master Duel'));
  assert(await page.locator('.intel-matchup-reader').isVisible());assert.equal(await field('title').count(),0);
  assert.match(await page.locator('.intel-matchup-reader').textContent(),/尚未经规则引擎验证/);
  assert.equal(await page.evaluate(()=>Object.values(intelUI.data.records).filter(record=>!record.research).length),1);
  pass('Matchup import adds both OCG and Master Duel research without replacing personal records and opens a readable strategy page');

  const topicsBefore=await page.evaluate(()=>JSON.stringify(intelUI.data.topics));
  assert.equal(await page.locator('#intel-filter-format').count(),0,'The duplicate environment filter is replaced by primary themes');
  for(const format of ['OCG','Master Duel','personal']){
    await page.locator(`[data-intel-topic-format="${format}"]`).click();
    assert.equal(await page.locator(`[data-intel-topic-format="${format}"]`).getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator('#intel-topic').inputValue(),'','Changing the primary theme clears its previous child selection');
    const visible=await page.locator('#intel-list [data-intel-edit]').evaluateAll(elements=>elements.map(el=>el.dataset.intelEdit));
    const formats=await page.evaluate(ids=>ids.map(id=>intelUI.data.records[id].research?.format||'personal'),visible);
    assert(visible.length>0);assert(formats.every(value=>value===format));
    const topicIds=await page.locator('#intel-topic option').evaluateAll(options=>options.map(option=>option.value).filter(Boolean));
    assert(topicIds.length>0);
    assert(await page.evaluate(({ids,format})=>ids.every(id=>Object.values(intelUI.data.records).some(record=>record.topic_id===id&&(record.research?.format||'personal')===format)),{ids:topicIds,format}));
    const optionLabels=await page.locator('#intel-topic option').allTextContents();
    if(format!=='personal')assert(optionLabels.every(label=>!label.startsWith(format+' · ')),'Child theme labels omit repeated environment prefixes');
    await page.locator('#intel-topic').selectOption(topicIds[0]);
    const selectedTopics=await page.locator('#intel-list [data-intel-edit]').evaluateAll(elements=>elements.map(el=>intelUI.data.records[el.dataset.intelEdit].topic_id));
    assert(selectedTopics.every(id=>id===topicIds[0]));
  }
  await page.locator('[data-intel-clear="intel-filter"]').click();
  assert.equal(await page.locator('[data-intel-topic-format=""]').getAttribute('aria-pressed'),'true');
  assert.deepEqual(await page.locator('#intel-topic optgroup').evaluateAll(groups=>groups.map(group=>group.label)),['OCG','Master Duel','个人与跨环境主题']);
  assert.equal(await page.evaluate(()=>JSON.stringify(intelUI.data.topics)),topicsBefore,'Theme navigation never renames or migrates stored topics');
  const chosen=imported.find(record=>record.research.format==='OCG'),searchTerm=chosen.research.summary.slice(0,10);
  assert(searchTerm);await page.locator('#intel-filter-q').fill(searchTerm);
  assert.equal(await page.locator(`[data-intel-edit="${chosen.id}"]`).count(),1,'Search includes the short strategy summary');
  await page.locator('#intel-filter-q').fill(String(chosen.steps.find(step=>step.opponent).opponent));
  assert.equal(await page.locator(`[data-intel-edit="${chosen.id}"]`).count(),1,'Search includes opponent card identities');
  await page.locator('[data-intel-clear="intel-filter"]').click();
  await page.locator(`[data-intel-edit="${chosen.id}"]`).click();
  const sourceDetails=page.locator('.intel-matchup-reader .intel-matchup-sources');
  assert.equal(await sourceDetails.getAttribute('open'),null);
  await sourceDetails.locator('summary').click();
  const links=await sourceDetails.locator('a').evaluateAll(elements=>elements.map(el=>({url:el.href,rel:el.rel})));
  assert(links.length>0);for(const link of links){assert(['http:','https:'].includes(new URL(link.url).protocol));assert(link.rel.includes('noopener'));}
  assert.match(await sourceDetails.textContent(),/环境证据/);assert.match(await sourceDetails.textContent(),/卡文核对/);
  await application.evaluate(({shell})=>{globalThis.matchupExternalCalls=[];globalThis.matchupOriginalOpen=shell.openExternal;shell.openExternal=async url=>{globalThis.matchupExternalCalls.push(url);};});
  const referenceUrl=await sourceDetails.locator('a').first().getAttribute('href');
  await sourceDetails.locator('a').first().click();
  assert.deepEqual(await application.evaluate(()=>globalThis.matchupExternalCalls),[referenceUrl]);
  await application.evaluate(({shell})=>{shell.openExternal=globalThis.matchupOriginalOpen;delete globalThis.matchupOriginalOpen;delete globalThis.matchupExternalCalls;});
  await sourceDetails.locator('summary').click();
  pass('Environment and personal filters compose with summary/card search, and collapsed references expose safe links with evidence types');

  assert(chosen.research.walkthrough?.sequence.length>0);
  assert.equal(await page.locator('.intel-walkthrough-sequence>li').count(),chosen.research.walkthrough.sequence.length);
  assert.equal(await page.locator('.intel-walkthrough-sequence .review-card').count(),chosen.research.walkthrough.sequence.filter(item=>item.card).length);
  const jump=page.locator('[data-intel-breakpoint]').first(),index=await jump.getAttribute('data-intel-breakpoint');
  await jump.click();assert.equal(await page.evaluate(()=>document.activeElement.id),`intel-matchup-step-${index}`);
  assert(await page.locator(`#intel-matchup-step-${index} .intel-matchup-evidence a`).count()>0);
  await page.locator('.intel-matchup-step .review-card').first().click();await page.locator('#review-card-popover').waitFor({state:'visible'});
  await page.evaluate(()=>closeReviewDetail());
  pass('Real card illustrations follow the conditional route, route links jump to the matching evidence-backed breakpoint, and card details remain available');

  await action('record-edit');assert(await field('title').isVisible());
  assert.equal(await field('research.format').count(),0);assert.equal(await field('research.reviewed_at').count(),0);
  await field('research.summary').fill('验收保留的个人概要');
  await page.locator('[data-intel-topic-format="Master Duel"]').click();
  assert.equal(await field('research.summary').inputValue(),'验收保留的个人概要','Changing primary themes retains a dirty draft');
  assert.equal(await page.evaluate(()=>intelUI.draft.id),chosen.id);
  await page.locator('[data-intel-topic-format="OCG"]').click();
  await action('record-read');assert(await page.locator('.intel-matchup-reader').isVisible());
  assert.match(await page.locator('.intel-matchup-summary').textContent(),/验收保留的个人概要/);assert(await page.evaluate(()=>intelUI.dirty));
  await action('record-edit');assert.equal(await field('research.summary').inputValue(),'验收保留的个人概要');
  const another=imported.find(record=>record.id!==chosen.id);
  await page.locator(`[data-intel-edit="${another.id}"]`).click();await page.locator('#flow-cancel').click();
  assert.equal(await field('research.summary').inputValue(),'验收保留的个人概要');
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.dirty&&!!document.querySelector('.intel-matchup-reader'));
  assert.equal(await page.evaluate(id=>intelUI.data.records[id].research.summary,chosen.id),'验收保留的个人概要');
  assert.equal(await page.evaluate(id=>intelUI.data.records[id].research.edited,chosen.id),true);
  const before=await page.evaluate(()=>({revision:intelUI.data.revision,records:JSON.stringify(intelUI.data.records)}));
  await action('import-matchups');await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.startsWith('已导入主流对策'));
  assert.deepEqual(await page.evaluate(()=>({revision:intelUI.data.revision,records:JSON.stringify(intelUI.data.records)})),before);
  pass('Read/edit toggles retain pending input, record switches protect dirty drafts, saving marks a personal edit, and repeat import preserves it without writes');

  await page.locator(`[data-intel-edit="${chosen.id}"]`).click();await action('record-edit');
  await field('research.warnings').fill('本窗口仍保留的提醒');
  await page.evaluate(async id=>{let data=await api('/api/intelligence');const record=structuredClone(data.records[id]);record.research.summary='另一个入口保存的概要';await api('/api/intelligence',{revision:data.revision,op:'record.save',value:record});},chosen.id);
  await action('save');await page.locator('[data-intel-action="reload-keep"]').waitFor();
  await action('reload-keep');assert.match(await page.locator('#intel-conflict').textContent(),/另一个入口保存的概要/);
  assert.equal(await field('research.warnings').inputValue(),'本窗口仍保留的提醒');
  await action('accept-latest');await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.dirty&&!!document.querySelector('.intel-matchup-reader'));
  assert.equal(await page.evaluate(id=>intelUI.data.records[id].research.warnings,chosen.id),'本窗口仍保留的提醒');
  pass('Research edits use the original revision conflict comparison and preserve pending fields until an explicit save');

  await action('record-edit');await field('steps.0.action').fill('验收调整后的对手操作');await action('record-read');
  assert.match(await page.locator('.intel-walkthrough h3').textContent(),/当前断点已手动调整/);
  assert.equal(await page.locator('[data-intel-breakpoint]').count(),0);assert.equal(await page.locator('.intel-matchup-step .intel-matchup-evidence').count(),0);
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.dirty);
  assert.equal(await page.evaluate(id=>intelUI.data.records[id].research.steps_edited,chosen.id),true);
  assert.equal(await page.locator('[data-intel-breakpoint]').count(),0);assert(await page.locator('.intel-walkthrough .intel-matchup-evidence a').count()>0);
  pass('Manual step edits retain the original illustrated research but remove stale breakpoint links and per-step source associations before and after save');
  await action('record-edit');await field('note').fill('记录删除后仍保留的个人修改');
  await page.evaluate(async id=>{const data=await api('/api/intelligence');await api('/api/intelligence',{revision:data.revision,op:'record.remove',value:{id}});},chosen.id);
  await action('save');await action('reload-keep');await action('accept-latest');
  assert(await page.locator('.intel-matchup-reference-copy').count()>0);
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.dirty);
  const personalCopy=await page.evaluate(()=>Object.values(intelUI.data.records).find(record=>record.note==='记录删除后仍保留的个人修改'));
  assert(personalCopy&&!personalCopy.research&&personalCopy.reference_copy.includes('https://'));
  pass('A concurrently deleted researched record can be saved as personal notes with its complete original reference copy');
  await page.locator(`[data-intel-edit="${another.id}"]`).click();

  for(const [width,height] of [[1440,950],[900,700],[390,844]]){
    await resize(width,height);
    const layout=await page.evaluate(()=>{
      const visible=el=>el.checkVisibility(),failures=[];
      if(document.documentElement.scrollWidth>innerWidth+1)failures.push('page overflow');
      const heading=document.querySelector('.intel-matchup-heading'),title=heading.querySelector('h2');
      if(title.getBoundingClientRect().width<heading.clientWidth*.8)failures.push('title is squeezed beside other heading content');
      for(const el of document.querySelectorAll('#intelligence button,#intelligence input,#intelligence select,.intel-matchup-step,.intel-matchup-response,.intel-walkthrough-sequence>li')){
        if(!visible(el))continue;const rect=el.getBoundingClientRect();if(rect.width<1||rect.left<0||rect.right>innerWidth+1)failures.push(el.className||el.id);
      }
      if(innerWidth>760){
        for(const selector of ['#intel-list','.intel-editor-body']){const el=document.querySelector(selector);if(!['auto','scroll'].includes(getComputedStyle(el).overflowY)||el.clientHeight<80)failures.push(`${selector} cannot scroll independently`);}
      }
      return failures;
    });assert.deepEqual(layout,[]);
    await page.locator('.intel-matchup-heading').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(evidence,`matchups-reading-${width}.png`),preserveScroll:true});
    await page.locator('.intel-walkthrough-sequence').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(evidence,`matchups-walkthrough-${width}.png`),preserveScroll:true});
    await page.locator('.intel-matchup-step').first().scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(evidence,`matchups-breakpoint-${width}.png`),preserveScroll:true});
  }
  await resize(1440,950);await page.evaluate(()=>{window.scrollTo(0,0);document.querySelector('.intel-editor-body').scrollTop=0;});
  pass('Reading summaries and response cards fit 1440px, 900px and 390px, with independent desktop list/detail scrolling and no horizontal overflow');
};
