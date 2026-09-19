'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

module.exports=async({page,application,evidence,pass})=>{
  page.setDefaultTimeout(25000);
  const action=name=>page.locator(`[data-intel-action="${name}"]`).click();
  const resize=async(width,height)=>{
    await application.evaluate(({BrowserWindow},size)=>{const window=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());window.setMinimumSize(0,0);window.setContentSize(size.width,size.height);},{width,height});
    await page.waitForFunction(size=>innerWidth===size.width&&innerHeight===size.height,{width,height});
  };
  const capture=async name=>{
    await page.waitForFunction(()=>[...document.querySelectorAll('#intelligence img')].filter(img=>img.checkVisibility()).every(img=>img.complete&&img.naturalWidth>0));
    await page.screenshot({path:path.join(evidence,name+'.png')});
  };
  const checkLayout=async()=>{
    const failures=await page.evaluate(()=>{
      const failures=[];
      if(document.documentElement.scrollWidth>innerWidth+1)failures.push('page overflow');
      for(const el of document.querySelectorAll('#intelligence button,#intelligence input,#intelligence select,#intelligence textarea,#intelligence h2')){
        if(!el.checkVisibility())continue;
        const rect=el.getBoundingClientRect();
        if(rect.width<1||rect.left<0||rect.right>innerWidth+1)failures.push(el.id||el.className||el.outerHTML.slice(0,100));
      }
      if(innerWidth>760){
        const library=document.querySelector('.intel-library').getBoundingClientRect(),editor=document.querySelector('#intel-editor').getBoundingClientRect();
        if(editor.left<library.right)failures.push('overlapping columns');
        const footer=document.querySelector('.intel-editor-actions')?.getBoundingClientRect();
        if(footer&&(footer.bottom>innerHeight||footer.top<editor.top))failures.push('save actions outside viewport');
      }
      return failures;
    });
    assert.deepEqual(failures,[],'Controls fit their columns and save actions remain reachable');
  };
  await page.locator('#module-intelligence').click();
  await page.waitForFunction(()=>moduleUI.current==='intelligence'&&!moduleUI.switching);
  assert(await page.locator('.intel-empty').isVisible());
  assert.equal(await page.locator('#intel-status').evaluate(el=>el.getBoundingClientRect().height),0);
  await capture('intelligence-empty');
  await page.evaluate(async()=>{
    let data=await api('/api/intelligence');
    const save=async(op,value)=>{data=await api('/api/intelligence',{revision:data.revision,op,value});return data.saved_id;};
    for(const code of [51339637,14558127,55144522]){
      const c=await api('/api/card/'+code);
      await save('endboard.save',{code,desc:c.desc,candidate:true,notes:[{text:'终场用途备注，保留卡牌在不同方案中的标注。',source_refs:[]},{text:'另一条独立备注，可单独补充适用条件。',source_refs:[]}],effects:{'0':{note:'效果用途与发动条件待结合具体场面核对。'}}});
    }
    const folder=await save('folder.save',{name:'常用手坑'});
    await save('handtrap.save',{code:14558127,folder_id:folder,note:'从手牌发动的干扰用途备注。',condition:'发动时点与适用范围待核对。',effects:{'1':{notes:[{text:'在对方发动包含卡组检索的效果时考虑使用。'},{text:'是否能够发动仍须核对当前效果与局面条件。'}]}}});
    const topic=await save('topic.save',{name:'对手操作与应对',tag_ids:[],note:'本地断点记录'});
    await save('record.save',{title:'效果发动时的应对记录',topic_id:topic,note:'验收用资料',steps:[{opponent:55144522,action:'对手发动效果',timing:'效果发动时',condition:'待核对具体场面',note:'记录对手操作',responses:[{mode:'alternative',cards:[14558127],method:'记录一种可选应对',condition:'满足适用条件',expected:'待核对',note:''}]}]});
    await enterIntelligence();
  });
  assert.equal(await page.locator('[data-intel-count="endboards"]').textContent(),'3');
  assert.equal(await page.locator('#intel-list [aria-pressed="true"]').count(),1);
  await page.locator('[data-intel-edit="51339637"]').click();
  assert.match(await page.locator('.intel-card-identity h2').textContent(),/转生炎兽/);
  for(const [width,height] of [[1440,950],[900,650]]){
    await resize(width,height);await checkLayout();await capture(`intelligence-endboards-${width}`);
    const before=await page.locator('.intel-editor-actions').boundingBox();
    await page.locator('.intel-editor-body').evaluate(el=>el.scrollTop=el.scrollHeight);
    const after=await page.locator('.intel-editor-actions').boundingBox();
    assert.equal(Math.round(after.y),Math.round(before.y),'Scrolling notes does not move the save bar');
    await page.locator('.intel-editor-body').evaluate(el=>el.scrollTop=0);
  }
  await page.locator('.intel-filter-more summary').click();
  await page.locator('#intel-filter-kind').selectOption('spell');
  assert.match(await page.locator('#intel-filter-active').textContent(),/1 项已选/);
  assert.equal(await page.locator('#intel-list [data-intel-edit]').count(),1);
  assert.equal(await page.locator('#intel-list [aria-pressed="true"]').count(),0);
  assert.match(await page.locator('.intel-card-identity h2').textContent(),/转生炎兽/,'Filtering preserves the open editor');
  await page.locator('[data-intel-clear="intel-filter"]').click();
  assert.equal(await page.locator('#intel-filter-active').textContent(),'');
  await page.locator('.intel-filter-more summary').click();
  assert.equal(await page.locator('#intel-list [aria-pressed="true"]').count(),1);
  await page.locator('[data-intel-field="notes.0.text"]').fill('过滤与切换时保留的输入');
  await page.locator('[data-intel-edit="14558127"]').click();
  await page.locator('#flow-dialog').waitFor({state:'visible'});
  await page.locator('#flow-cancel').click();
  assert.equal(await page.locator('[data-intel-field="notes.0.text"]').inputValue(),'过滤与切换时保留的输入');
  assert.equal(await page.locator('#intel-list [aria-pressed="true"]').getAttribute('data-intel-edit'),'51339637');
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.draft);
  assert.equal(await page.locator('#intel-list [aria-pressed="true"]').count(),0);
  await page.locator('[data-intel-edit="51339637"]').click();
  pass('Library selection, counts, compound filters, unsaved-edit protection and fixed save actions work at 1440px and 900px');

  for(const tab of ['handtraps','records']){
    await page.locator(`[data-intel-tab="${tab}"]`).click();
    assert.equal(await page.locator('#intel-list [aria-pressed="true"]').count(),1);
    for(const [width,height] of [[1440,950],[900,650]]){
      await resize(width,height);await checkLayout();await capture(`intelligence-${tab}-${width}`);
      if(tab==='handtraps'){
        await page.locator('[data-intel-field="effects.1.notes.0.text"]').scrollIntoViewIfNeeded();
        await checkLayout();await capture(`intelligence-handtrap-effects-${width}`);
        await page.locator('.intel-editor-body').evaluate(el=>el.scrollTop=0);
      }
    }
  }
  await action('step-add');
  await page.locator('[data-intel-field="steps.1.action"]').fill('后续操作');
  await page.locator('[data-intel-step-up="1"]').click();
  assert.equal(await page.locator('[data-intel-field="steps.0.action"]').inputValue(),'后续操作');
  await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.draft);
  await page.locator('[data-intel-tab="endboards"]').click();
  for(const width of [760,390]){
    await resize(width,844);await checkLayout();await capture(`intelligence-stacked-${width}`);
  }
  await page.locator('[data-intel-tab="handtraps"]').click();
  await checkLayout();await page.locator('[data-intel-field="effects.1.notes.0.text"]').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(evidence,'intelligence-handtrap-effects-390.png'),preserveScroll:true});
  await page.locator('[data-intel-tab="endboards"]').click();
  pass('Hand-trap folders and breakpoint steps use the shared layout; narrow views stack without horizontal overflow');

  await resize(1440,950);
  await action('sources');await page.locator('#intel-sources [data-intel-action="sources-close"]').waitFor();
  assert(await page.locator('.intel-layout').isHidden());await capture('intelligence-sources');await action('sources-close');
  assert(await page.locator('.intel-layout').isVisible());
  await page.route('**/api/intelligence/sources',route=>route.fulfill({status:500,json:{error:'isolated source read failure'}}),{times:1});
  await action('sources');await page.locator('#intel-sources .intel-error').waitFor();await action('sources-close');
  assert(await page.locator('.intel-layout').isVisible(),'A failed source read still provides a way back to the editor');
  await action('add');await page.locator('#intel-pick-q').fill('51339637');await page.locator('[data-intel-choose="51339637"]').waitFor();
  assert(await page.locator('.intel-layout').isHidden());await capture('intelligence-picker');
  await page.locator('[data-intel-choose="51339637"]').click();
  assert(await page.locator('.intel-layout').isVisible());assert.match(await page.locator('.intel-card-identity h2').textContent(),/转生炎兽/);
  await page.locator('#navigation-toggle').click();await checkLayout();await capture('intelligence-collapsed-navigation');
  pass('Source aggregation and card selection use the full workspace and return to the selected editor; collapsed navigation stays aligned');
};
