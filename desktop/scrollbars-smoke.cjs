'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

module.exports=async ({page,application,evidence,pass})=>{
  const enter=async name=>{await require('./navigation-test.cjs')(page, name);await page.waitForFunction(name=>moduleUI.current===name&&!moduleUI.switching,name);};
  const check=async (selector,horizontal=false)=>{
    const result=await page.locator(selector).evaluate((node,horizontal)=>{
      const bar=getComputedStyle(node,'::-webkit-scrollbar'),thumb=getComputedStyle(node,'::-webkit-scrollbar-thumb');
      const track=getComputedStyle(node,'::-webkit-scrollbar-track'),arrow=getComputedStyle(node,'::-webkit-scrollbar-button');
      const overflow=horizontal?node.scrollWidth>node.clientWidth:node.scrollHeight>node.clientHeight;
      if(horizontal)node.scrollLeft=80;else node.scrollTop=80;
      return {width:bar.width,height:bar.height,radius:thumb.borderRadius,track:track.backgroundColor,arrow:arrow.display,
        overflow,scrolled:horizontal?node.scrollLeft>0:node.scrollTop>0};
    },horizontal);
    assert.deepEqual(result,{width:'8px',height:'8px',radius:'8px',track:'rgba(0, 0, 0, 0)',arrow:'none',overflow:true,scrolled:true},selector);
  };
  await enter('tags');await page.waitForFunction(()=>tagManagerUI.loaded);
  await page.evaluate(async()=>{const tag=tagManagerUI.tags.find(t=>t.name==='转生炎兽');await selectManagedTag(tag.id);});
  await check('#tag-manager-list');await check('#tag-member-cards');
  await page.screenshot({path:path.join(evidence,'scrollbars-tag-management.png')});
  const deck=await page.evaluate(async()=>{
    for(const info of await api('/api/decks')){const saved=await api('/api/deck?id='+encodeURIComponent(info.id));if(saved.deck.main.length>=40)return saved;}
  });
  assert(deck,'An isolated saved test deck is required');
  await enter('decks');await page.evaluate(id=>openDeck(id),deck.id);
  await page.locator('#deck-tags-button').click();await page.waitForFunction(()=>!!deckTagUI.suggestions&&!deckTagUI.busy);
  await check('#deck-tags-options');
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(900,650));
  await page.waitForFunction(()=>innerWidth===900&&innerHeight===650);
  await check('.deck-tags-body');
  await page.screenshot({path:path.join(evidence,'scrollbars-tag-picker-900.png'),preserveScroll:true});
  await page.keyboard.press('Escape');assert.equal(await page.locator('#deck-tags-dialog').isVisible(),false);
  assert.equal(await page.evaluate(()=>app.dirty),false);
  await enter('expansion');
  const plan=await page.evaluate(async()=>{
    for(const info of await api('/api/plans')){const saved=await api('/api/plan/'+info.id);if(saved.review?.nodes.length>6)return saved;}
  });
  assert(plan,'An isolated saved review route is required');
  await page.evaluate(id=>showReport(id),plan.id);
  await check('#draft-editor .review-steps',true);
  await page.screenshot({path:path.join(evidence,'scrollbars-review-horizontal.png')});
  assert.deepEqual(await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),deck.id),deck);
  pass('Shared 8px rounded scrollbars: transparent tracks, no arrow buttons, working vertical/horizontal scrolling and 900px dialogs; saved deck unchanged');
};
