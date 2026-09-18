'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

module.exports=async function({page,application,evidence,pass,existing,live=false}) {
  const click=async action=>{await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);};
  const before=await page.evaluate(async id=>({saved:id?await api('/api/deck?id='+encodeURIComponent(id)):null,editor:JSON.stringify(app.deck),active:app.active?.id||null}),existing?.id);
  const fixture={deck:{main:Array(40).fill(55144522),extra:[23995346],side:[14558127]},captured_ms:Date.now(),method:'test-fixture'};
  let attached=0,failRead=false;
  if(!live) {
    await page.route('**/api/ygopro/attach',route=>route.fulfill({json:++attached===1?{connected:false,processes:[],error:'未找到 YGOPro.exe，请重新捕捉。'}:
      {connected:true,process:{pid:123,name:'YGOPro.exe',path:'test/YGOPro.exe',title:'YGOPro fixture',capture_id:'test'}}}));
    await page.route('**/api/ygopro/deck',route=>route.fulfill(failRead?{status:400,json:{error:'测试：进程已退出'}}:{json:fixture}));
  }
  try {
    await click('automatic');
    assert.equal(await page.locator('#duel-substeps [aria-current="step"]').getAttribute('data-duel-function-page'),'platform');
    assert.equal(await page.locator('.duel-platform').count(),2);
    const grid=await page.locator('.duel-platform-grid').boundingBox(),platform=await page.locator('.duel-platform').first().boundingBox(),next=await page.locator('.duel-platform').nth(1).boundingBox();
    assert(Math.abs(platform.width-platform.height)<2);assert(Math.abs(next.width-platform.width)<2);
    assert(Math.abs((platform.x+next.x+next.width)/2-grid.x-grid.width/2)<2);
    assert.match(await page.locator('[data-duel-action="platform-ygopro2"]').innerText(),/YGOPRO2\s+新一代原版游戏/);
    assert.match(await page.locator('[data-duel-action="platform-ygopro2"]').evaluate(button=>getComputedStyle(button).backgroundImage),/\/brand\/duel-ygopro2\.svg/);
    await page.screenshot({path:path.join(evidence,'automatic-platforms.png')});
    await click('platform-ygopro');
    await page.waitForFunction(()=>document.querySelector('#duel-capture-dialog').dataset.busy==='false');
    assert(await page.locator('#duel-capture-dialog').isVisible());
    assert.match(await page.locator('#duel-capture-help').textContent(),/主菜单点击「编辑卡组」.*停留/);
    if(!live) {
      assert(await page.locator('#duel-capture-next').isHidden());
      await page.locator('#duel-capture-retry').click();
      await page.waitForFunction(()=>!!duelState().automatic.connection);
    }
    assert.match(await page.locator('#duel-capture-status').textContent(),/捕捉成功/);
    assert.match(await page.locator('#duel-capture-processes').textContent(),/YGOPro.exe.*PID/);
    await page.screenshot({path:path.join(evidence,'duel-process-captured.png')});
    await page.locator('#duel-capture-next').click();
    assert.match(await page.locator('.duel-recognition-controls .duel-capture-help').textContent(),/主菜单点击「编辑卡组」.*停留/);
    assert.deepEqual(await page.locator('#duel-substeps button').allTextContents(),['1. 卡组识别','2. 卡牌预览']);
    assert(await page.locator('[data-duel-action="recognition-next"]').isDisabled());
    await click('get-deck');
    const captured=await page.evaluate(()=>duelState().automatic.deck);
    assert(captured,'Real capture must succeed before preview');
    if(live)assert.equal(captured.method,'process-memory');
    else assert.deepEqual(captured.deck,fixture.deck);
    const count=Object.values(captured.deck).flat().length;
    assert.equal(await page.locator('.duel-recognition-cards img').count(),count);
    await page.locator('.duel-recognition-cards img').evaluateAll(async images=>{for(const image of images){image.loading='eager';await image.decode();}});
    await page.screenshot({path:path.join(evidence,'duel-live-recognition.png')});
    await click('recognition-next');assert.equal(await page.locator('.duel-card').count(),count);
    for(const zone of ['main','extra','side'].filter(zone=>captured.deck[zone].length)) {
      await page.locator(`[data-duel-mark-key="${zone}:0"] .review-card`).hover();
      await page.waitForFunction(()=>!document.querySelector('#toggle-duel-card-mark').hidden);
      await page.locator('#toggle-duel-card-mark').click();await page.locator('#review-detail-close').click();
    }
    const marks=Object.values(captured.deck).filter(cards=>cards.length).length;
    assert.equal(await page.locator('.duel-card.is-marked').count(),marks);
    assert.equal(await page.evaluate(()=>duelState().marks.size),0);
    await click('auto-tags');
    const tags=await page.evaluate(()=>duelState().automatic.tags.slice(0,2));assert(tags.length);
    await page.locator(`[data-duel-auto-tag="${tags[0].id}"][data-role="secondary"]`).click();
    assert.equal(await page.locator(`[data-duel-auto-tag="${tags[0].id}"][data-role="secondary"]`).getAttribute('aria-pressed'),'true');
    await page.locator(`[data-duel-auto-tag="${tags[0].id}"][data-role="primary"]`).click();
    await page.locator('#duel-auto-tag-search').fill('绝无此标签xyz');assert.equal(await page.locator('.duel-auto-tag-options button').count(),0);
    await page.locator('#duel-auto-tag-search').fill('');
    await page.locator('#duel-auto-name').fill('');assert(await page.locator('#duel-auto-save').isDisabled());
    await page.locator('#duel-auto-name').fill('CON');await page.locator('#duel-auto-save').click();
    assert.match(await page.locator('#duel-auto-save-status').textContent(),/保留名称/);
    const name=live?'实时捕捉验收-第一套':`自动捕捉验收-${Date.now()}`;
    await page.locator('#duel-auto-name').fill(name);await page.locator('#duel-auto-name').press('Enter');
    await page.waitForFunction(()=>!duelUI.busy&&duelState().automatic.notice.includes('已保存'));
    const saved=await page.evaluate(async name=>{const found=(await api('/api/decks')).find(d=>d.name===name);return api('/api/deck?id='+encodeURIComponent(found.id));},name);
    assert.deepEqual(saved.deck,captured.deck);
    assert.deepEqual(saved.tag_selection,await page.evaluate(()=>({tag_ids:duelState().automatic.tagIds,primary_ids:duelState().automatic.primaryIds})));
    await page.screenshot({path:path.join(evidence,'duel-live-preview-saved.png')});
    await page.locator('[data-duel-deck-page="recognition"]').click();
    if(live) {
      pass('Live YGOPro capture, all three zones, card detail marks, real TAG roles, named save and persisted deck readback');
      return {captured,saved};
    }
    failRead=true;await click('get-deck');
    assert(await page.locator('[data-duel-action="recognition-next"]').isDisabled());
    assert(await page.locator('[data-duel-deck-page="preview"]').isDisabled());
    assert.equal(await page.evaluate(()=>duelState().automatic.fresh),false);
    failRead=false;fixture.deck.main[0]=89631139;fixture.deck.side=[];
    await click('get-deck');await click('recognition-next');assert.equal(await page.locator('.duel-card.is-marked').count(),0);
    assert.equal(await page.locator('#duel-auto-name').inputValue(),name);
    await page.locator('#duel-auto-save').click();await page.waitForFunction(()=>!duelUI.busy&&!!duelState().automatic.pending);
    await click('cancel-auto-overwrite');
    assert.deepEqual(await page.evaluate(async id=>(await api('/api/deck?id='+encodeURIComponent(id))).deck,saved.id),saved.deck);
    await page.locator('#duel-auto-save').click();await page.waitForFunction(()=>!duelUI.busy&&!!duelState().automatic.pending);
    await click('confirm-auto-overwrite');assert.match(await page.locator('#duel-auto-save-status').textContent(),/覆盖更新/);
    assert.deepEqual(await page.evaluate(async id=>(await api('/api/deck?id='+encodeURIComponent(id))).deck,saved.id),fixture.deck);
    assert.equal(await page.evaluate(async name=>(await api('/api/decks')).filter(d=>d.name===name).length,name),1);
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(960,800));
    await page.waitForFunction(()=>innerWidth===960);
    assert(await page.locator('#duel').evaluate(el=>el.scrollWidth===el.clientWidth));
    const panel=await page.locator('.duel-auto-save-panel').boundingBox();assert(panel.x>=0&&panel.x+panel.width<=960);
    await page.screenshot({path:path.join(evidence,'duel-automatic-preview-narrow.png')});
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
    await page.waitForFunction(()=>innerWidth===1280);
    await require('./duel-order-smoke.cjs')({page,application,evidence,pass});
    await require('./duel-opening-smoke.cjs')({page,application,evidence,pass});
    const after=await page.evaluate(async id=>({saved:id?await api('/api/deck?id='+encodeURIComponent(id)):null,editor:JSON.stringify(app.deck),active:app.active?.id||null}),existing?.id);
    assert.deepEqual(after,before);
    await page.locator('#duel-steps [data-duel-stage="1"]').click();
    await page.locator('[data-duel-function-page="choice"]').click();await click('manual');
    assert.deepEqual(await page.locator('#duel-substeps button').allTextContents(),['1. 选择卡组','2. 卡牌预览']);
    await page.locator('#duel-steps [data-duel-stage="1"]').click();
    pass('Automatic capture UI: missing process/retry, snapshot/failure gating, real persistent save and confirmed overwrite, TAGs, per-copy marks, 960px layout; capture fixture isolated from external game');
  } finally {
    if(!live){await page.unroute('**/api/ygopro/attach');await page.unroute('**/api/ygopro/deck');}
  }
};
