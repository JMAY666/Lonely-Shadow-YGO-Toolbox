'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

module.exports=async({page,application,evidence,pass})=>{
  page.setDefaultTimeout(30000);
  const action=name=>page.locator(`[data-intel-action="${name}"]`).click();
  const field=name=>page.locator(`[data-intel-field="${name}"]`);
  const tab=async name=>{await page.locator(`[data-intel-tab="${name}"]`).click();await page.waitForFunction(name=>intelUI.tab===name,name);};
  const save=async()=>{await action('save');await page.waitForFunction(()=>!intelUI.busy&&!intelUI.draft);};
  await page.evaluate(async()=>{
    let data=await api('/api/intelligence');
    data=await api('/api/intelligence',{revision:data.revision,op:'folder.save',value:{name:'无效'}});
    data=await api('/api/intelligence',{revision:data.revision,op:'handtrap.save',value:{code:14558127,folder_id:data.saved_id,note:'验收原有用途',condition:'验收原有条件',effects:{'1':{note:'验收原有独立备注'}}}});
    await api('/api/intelligence',{revision:data.revision,op:'endboard.save',value:{code:14558127,note:'验收终场独立资料'}});
  });
  await page.locator('#module-intelligence').click();await page.waitForFunction(()=>moduleUI.current==='intelligence'&&!moduleUI.switching);
  await tab('handtraps');
  await page.route('**/api/intelligence',route=>route.request().method()==='POST'?route.fulfill({status:500,json:{error:'isolated import failure'}}):route.continue(),{times:1});
  await action('import-staples');await page.locator('#flow-confirm').click();
  await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.includes('保存失败'));
  assert.equal(await page.evaluate(async()=>Object.keys((await api('/api/intelligence')).handtraps).length),1);
  await action('import-staples');await page.locator('#flow-confirm').click();
  await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.startsWith('已导入'));
  assert.equal(await page.locator('[data-intel-count="handtraps"]').textContent(),'28');
  assert.equal(await page.locator('[data-intel-count="breakers"]').textContent(),'39');
  assert.equal(await page.locator('#intel-folder option').count(),12);
  await page.locator('[data-intel-edit="14558127"]').click();
  assert.equal(await field('note').inputValue(),'验收原有用途');
  assert.equal(await field('condition').inputValue(),'验收原有条件');
  assert.equal(await field('effects.1.notes.0.text').inputValue(),'验收原有独立备注');
  assert.equal(await field('effects.1.notes.1.text').count(),1);
  assert.match(await page.locator('.intel-note-origin').last().textContent(),/2026-09-20/);
  assert.equal(await page.evaluate(()=>intelUI.data.endboards[14558127].note),'验收终场独立资料');
  assert.deepEqual(await page.evaluate(()=>Object.keys(intelUI.data.handtraps[34267821].effects)),['2']);
  await page.locator('.intel-catalog-source summary').click();
  assert.match(await page.locator('.intel-catalog-source a').first().getAttribute('href'),/cid=12950/);
  const revision=await page.evaluate(()=>intelUI.data.revision);
  await action('import-staples');await page.locator('#flow-confirm').click();
  await page.waitForFunction(()=>!intelUI.busy&&document.querySelector('#intel-status').textContent.startsWith('已导入'));
  assert.equal(await page.evaluate(()=>intelUI.data.revision),revision,'Reimporting the same reviewed version makes no writes');
  const drawFolder=await page.evaluate(()=>Object.values(intelUI.data.folders).find(f=>f.kind==='handtraps'&&f.name==='抽牌威慑').id);
  await page.locator('#intel-folder').selectOption(drawFolder);assert.equal(await page.locator('#intel-list [data-intel-edit]').count(),4);
  await page.locator('[data-intel-clear="intel-filter"]').click();
  const effectTag=await page.evaluate(()=>intelUI.data.tags.find(t=>t.name==='效果 · 发动无效').id);
  await page.locator('#intel-filter-tag').selectOption(effectTag);assert.equal(await page.locator('#intel-list [data-intel-edit]').count(),2);
  await page.locator('[data-intel-clear="intel-filter"]').click();
  pass('Reviewed import preserves existing notes/folders/endboard data, selects actual effects, supports effect filtering, exposes sources and is idempotent; failed import leaves the library unchanged');

  await tab('breakers');assert.equal(await page.locator('#intel-folder option').count(),10);
  await page.locator('[data-intel-edit="98127546"]').click();assert.match(await page.locator('#intel-editor').textContent(),/连接召唤/);
  const negate=await page.evaluate(()=>Object.values(intelUI.data.folders).find(f=>f.kind==='breakers'&&f.name==='效果无效').id);
  await page.locator('#intel-folder').selectOption(negate);assert.equal(await page.locator('#intel-list [data-intel-edit]').count(),4);
  await page.locator('[data-intel-edit="10045474"]').click();await field('note').fill('验收解场单独修订');await save();
  assert.notEqual(await page.evaluate(()=>intelUI.data.handtraps[10045474].note),'验收解场单独修订');
  await page.locator('[data-intel-clear="intel-filter"]').click();
  await action('add');await page.locator('#intel-pick-q').fill('23995346');await page.locator('[data-intel-choose="23995346"]').click();
  await field('note').fill('验收额外卡牌手动归档');await save();
  assert.equal(await page.evaluate(()=>Object.keys(intelUI.data.breakers).length),40);
  await page.locator('[data-intel-edit="23995346"]').click();await action('remove');await page.locator('#flow-confirm').click();
  await page.waitForFunction(()=>!intelUI.busy&&!intelUI.data.breakers[23995346]);
  assert((await page.evaluate(()=>api('/api/tag-members/purpose%3Aboardbreaker'))).cards.some(c=>c.id===98127546));
  assert(!(await page.evaluate(()=>api('/api/tag-members/purpose%3Ahandtrap'))).cards.some(c=>c.id===98127546));
  pass('Boardbreaker folders and notes are independent from handtraps, include Extra Deck cards and update their own purpose TAG on manual add/remove');

  await page.locator('#module-tags').click();await page.waitForFunction(()=>tagManagerUI.loaded);
  await page.locator('#tag-manager-search').fill('解场');await page.locator('[data-managed-tag="purpose:boardbreaker"]').click();
  await page.waitForFunction(()=>tagManagerUI.selected==='purpose:boardbreaker'&&!tagManagerUI.busy);
  await page.locator('#tag-add-search').fill('23995346');await page.locator('#tag-add-results [data-member-add="23995346"]').click();
  await page.locator('#tag-manager-save').click();await page.waitForFunction(()=>!tagManagerUI.busy&&!tagManagerUI.dirty);
  await page.locator('#module-intelligence').click();await page.waitForFunction(()=>moduleUI.current==='intelligence'&&!moduleUI.switching);
  assert(await page.locator('[data-intel-edit="23995346"]').isVisible());
  await page.locator('[data-intel-edit="23995346"]').click();await action('remove');await page.locator('#flow-confirm').click();
  await page.waitForFunction(()=>!intelUI.busy&&!intelUI.data.breakers[23995346]);
  pass('TAG management permits Extra Deck boardbreakers while keeping handtrap membership validation separate');

  for(const [width,height] of [[1440,950],[900,700],[390,844]]){
    await application.evaluate(({BrowserWindow},size)=>{const window=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());window.setMinimumSize(0,0);window.setContentSize(size.width,size.height);},{width,height});
    await page.waitForFunction(size=>innerWidth===size.width&&innerHeight===size.height,{width,height});
    for(const kind of ['handtraps','breakers']){
      await tab(kind);await page.locator(`[data-intel-edit="${kind==='handtraps'?14558127:24299458}"]`).click();
      await page.locator('#intelligence img').evaluateAll(images=>images.forEach(img=>img.loading='eager'));
      await page.waitForFunction(()=>[...document.querySelectorAll('#intelligence img')].filter(img=>img.checkVisibility()).every(img=>img.complete&&img.naturalWidth>0));
      const failures=await page.evaluate(()=>{
        const failures=[];
        if(document.documentElement.scrollWidth>innerWidth+1)failures.push('page overflow');
        if(innerWidth>760&&document.querySelector('#intel-list').clientHeight<80)failures.push('card list has no scrolling space');
        for(const el of document.querySelectorAll('#intelligence button,#intelligence input,#intelligence select,#intelligence textarea')){
          if(!el.checkVisibility())continue;const rect=el.getBoundingClientRect();
          if(rect.width<1||rect.left<0||rect.right>innerWidth+1)failures.push(el.outerHTML.slice(0,100));
        }
        return failures;
      });assert.deepEqual(failures,[]);
      await page.screenshot({path:path.join(evidence,`staples-${kind}-${width}.png`)});
    }
  }
  pass('Reviewed categories, card artwork, effect notes and four-tab navigation render at 1440px, 900px and 390px without horizontal overflow');
};
