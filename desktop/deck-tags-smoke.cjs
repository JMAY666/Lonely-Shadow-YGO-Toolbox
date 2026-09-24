'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');

module.exports = async ({page,application,deckId,deck,evidence,pass}) => {
  const enter = async name => {await require('./navigation-test.cjs')(page, name);await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const open = async () => {await page.locator('#deck-tags-button').click();await page.waitForFunction(()=>!!deckTagUI.suggestions&&!deckTagUI.busy);};
  const save = async () => {await page.locator('#save-deck').click();await page.waitForFunction(()=>!app.busy&&!app.dirty);};
  const query = async text => {
    await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/decks/tag-options')&&r.request().postDataJSON().query===text),
      page.locator('#deck-tags-search').fill(text)]);
    await page.waitForFunction(()=>!deckTagUI.busy);
  };
  assert.equal(await page.evaluate(()=>app.id),deckId);
  assert.equal(await page.locator('#deck-tag-count').textContent(),'TAG 0');
  const before = await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),deckId);
  // Synthetic tags exist only in the acceptance profile.
  const keys = await page.evaluate(async () => {
    let info = await api('/api/tags');
    const suffix = Date.now(), result = [];
    for (const [name,alias,cards] of [['测试构筑甲','Alpha Key',[55144522]],['测试构筑乙','Beta Key',[1184620]],['测试构筑副','Side Key',[23995346]]]) {
      const saved = await api('/api/tags/save',{name:name+suffix,aliases:[alias+suffix],card_ids:cards,revision:info.revision});
      info.revision = saved.revision;result.push({id:saved.tag.id,name:saved.tag.name,alias:saved.tag.aliases[0]});
    }
    return result;
  });
  const vocabulary = JSON.stringify(await page.evaluate(()=>api('/api/tags')));
  await open();
  assert.equal(await page.locator('#deck-tags-dialog #tag-manager-save, #deck-tags-dialog textarea').count(),0);
  await page.locator('#deck-tags-auto').click();
  let selected = await page.evaluate(()=>deckTagUI.draft);
  assert.equal(selected.primary_ids.length,1);
  const candidates = await page.evaluate(()=>deckTagUI.suggestions.candidates);
  assert(candidates.some(t=>t.id===keys[0].id&&t.count===20&&t.eligible)&&candidates.some(t=>t.id===keys[1].id&&t.count===20&&t.eligible));
  assert(!selected.tag_ids.includes(keys[2].id),'Single extra card stays a manual candidate below the secondary threshold');
  await page.locator('#deck-tags-cancel').click();
  assert.equal(await page.evaluate(()=>app.dirty),false);
  assert.deepEqual(await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),deckId),before);

  await open(); await query(keys[0].alias);
  await page.waitForFunction(key=>deckTagUI.tags.length===1&&deckTagUI.tags[0].id===key,keys[0].id);
  await page.locator(`#deck-tags-options [data-deck-tag="${keys[0].id}"][data-role="primary"]`).click();
  await query(keys[1].alias);
  await page.waitForFunction(key=>deckTagUI.tags.length===1&&deckTagUI.tags[0].id===key,keys[1].id);
  await page.locator(`#deck-tags-options [data-deck-tag="${keys[1].id}"][data-role="primary"]`).click();
  await query('23995346');
  await page.waitForFunction(key=>deckTagUI.tags.some(t=>t.id===key),keys[2].id);
  await page.locator(`#deck-tags-options [data-deck-tag="${keys[2].id}"][data-role="secondary"]`).click();
  selected = await page.evaluate(()=>deckTagUI.draft);
  assert.deepEqual(selected.primary_ids,[keys[0].id,keys[1].id]);assert.equal(selected.tag_ids.length,3);
  await page.locator('#deck-tags-search-reset').click();await page.waitForTimeout(240);await page.waitForFunction(()=>!deckTagUI.busy);
  await page.locator('[data-deck-tag-card="1184620"]').click();await page.waitForTimeout(240);await page.waitForFunction(()=>!deckTagUI.busy);
  assert(await page.evaluate(()=>deckTagUI.tags.every(t=>t.deck_card_ids.includes(1184620))));
  assert(await page.locator(`#deck-tags-options [data-deck-tag="${keys[1].id}"]`).count());
  await page.screenshot({path:path.join(evidence,'deck-tags-selected.png')});
  for (const [width,height] of [[900,650],[1440,920]]) {
    await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(size.width,size.height),{width,height});
    await page.waitForFunction(size=>innerWidth===size.width&&innerHeight===size.height,{width,height});
    const layout = await page.evaluate(()=>{
      const dialog=document.querySelector('#deck-tags-dialog'),rect=dialog.getBoundingClientRect();
      const footer=dialog.querySelector('footer').getBoundingClientRect();
      return {fits:rect.left>=0&&rect.right<=innerWidth&&rect.top>=0&&rect.bottom<=innerHeight,
        footer:footer.bottom<=innerHeight,overflow:dialog.scrollWidth>dialog.clientWidth};
    });
    assert(layout.fits&&layout.footer&&!layout.overflow,JSON.stringify(layout));
    await page.screenshot({path:path.join(evidence,`deck-tags-${width}.png`)});
  }
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.waitForFunction(()=>innerWidth===1280&&innerHeight===900);
  await page.locator('#deck-tags-apply').click();
  assert.equal(await page.locator('#deck-tag-count').textContent(),'TAG 3');
  assert.equal(await page.evaluate(()=>app.dirty),true);
  await enter('tags');await page.waitForFunction(()=>tagManagerUI.loaded);
  await page.locator('#tag-manager-search').fill(keys[0].alias);
  await page.locator(`[data-managed-tag="${keys[0].id}"]`).click();
  await page.waitForFunction(key=>tagManagerUI.selected===key,keys[0].id);
  await page.screenshot({path:path.join(evidence,'tag-management-dark.png')});
  await enter('decks');assert.deepEqual(await page.evaluate(()=>app.deckTags),selected);
  await page.route('**/api/decks',route=>route.request().method()==='POST'?route.fulfill({status:500,contentType:'application/json',body:'{"error":"isolated tag save failure"}'}):route.continue(),{times:1});
  await page.locator('#save-deck').click();await page.waitForFunction(()=>!app.busy);
  assert.equal(await page.evaluate(()=>app.dirty),true);
  assert.deepEqual(await page.evaluate(()=>app.deckTags),selected);
  await save();
  assert.deepEqual((await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),deckId)).tag_selection,selected);
  await page.locator('#back-to-decks').click();await page.waitForFunction(()=>!app.busy);
  await page.locator(`[data-open-deck="${deckId}"]`).click();await page.waitForFunction(()=>!app.busy);
  assert.deepEqual(await page.evaluate(()=>app.deckTags),selected);
  await open();await page.locator('#deck-tags-clear').click();await page.locator('#deck-tags-apply').click();await save();
  assert.equal(await page.locator('#deck-tag-count').textContent(),'TAG 0');
  await open();await page.locator('#deck-tags-auto').click();await page.locator('#deck-tags-apply').click();await save();
  assert.deepEqual(await page.evaluate(()=>app.deck),deck);
  assert.equal(JSON.stringify(await page.evaluate(()=>api('/api/tags'))),vocabulary,'The picker never edits shared vocabulary');
  await page.screenshot({path:path.join(evidence,'deck-tags-header.png')});
  pass('Deck TAGs: shared vocabulary, copy-weighted auto suggestions, alias/card search, multiple primary/secondary tags, cancel, clear, module retention and save failure/reopen');
};
