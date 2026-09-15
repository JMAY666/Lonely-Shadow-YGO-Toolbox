'use strict';
const assert=require('node:assert/strict');
const path=require('node:path');

module.exports=async function({page,application,evidence,pass}) {
  const saved=await page.evaluate(()=>api('/api/decks',{name:`卡组预览验收 ${Date.now()}`,deck:{main:[...Array(3).fill(55144522),...Array(37).fill(1184620)],extra:[],side:[1184620]}}));
  await page.evaluate(()=>deckList());
  await page.locator('[data-select-deck='+JSON.stringify(saved.id)+']').click();
  await page.waitForFunction(()=>!deckSelection.loading&&!!deckSelection.selected);
  for (const key of ['main:0','side:0']) {
    await page.locator(`[data-selection-key="${key}"] [data-review-card]`).click();
    await page.locator('#toggle-preview-card-mark').click();
    assert.equal(await page.locator('#toggle-preview-card-mark').getAttribute('aria-pressed'),'true');
    assert.equal(await page.locator(`[data-selection-key="${key}"]`).evaluate(item=>item.classList.contains('is-marked')),true);
    await page.locator('#review-detail-close').click();
  }
  assert.equal(await page.locator('#selection-cards input').count(),0);
  const borders=await page.evaluate(()=>['main:0','main:1'].map(key=>getComputedStyle(document.querySelector(`[data-selection-key="${key}"] button`)).borderColor));
  assert.notEqual(borders[0],borders[1],'Marked cards have a visible border while unmarked artwork stays unchanged');
  assert.equal(await page.locator('#editor').isVisible(),false);
  assert.equal(await page.locator('.selection-detail-panel').count(),0);
  await page.screenshot({path:path.join(evidence,'selection-final-preview.png')});
  const art=page.locator('#selection-cards [data-review-card]').first();
  await art.hover();
  await page.waitForFunction(()=>!!reviewUI.selected&&!reviewUI.detailPinned);
  await page.screenshot({path:path.join(evidence,'selection-final-hover.png')});
  const darkSurfaces=async selector=>page.evaluate(selector=>[...document.querySelectorAll(selector)].filter(el=>el.getClientRects().length).map(el=>({name:el.id||el.tagName,color:getComputedStyle(el).backgroundColor})),selector);
  const dark=colors=>colors.every(item=>item.color.match(/[\d.]+/g).slice(0,3).every(value=>Number(value)<110));
  const popupColors=await darkSurfaces('#review-card-popover, #review-card-popover>header, #review-card-popover>header button');
  assert(dark(popupColors),JSON.stringify(popupColors));
  await art.click();await page.locator('#selection-name').hover();
  assert.equal(await page.evaluate(()=>reviewUI.detailPinned),true);
  await page.screenshot({path:path.join(evidence,'selection-final-pinned.png')});
  await page.locator('#review-detail-close').click();
  await page.locator('#selection-next').click();
  await page.waitForFunction(()=>app.view==='design');
  assert.deepEqual(await page.evaluate(()=>flow.design.conditions.slots),[null,null,null,null,null]);
  assert.deepEqual(await page.evaluate(()=>mainQuickCodes()),[55144522]);
  await page.locator('#plan-name').fill('起手快捷候选');
  const contrast=await page.evaluate(()=>{
    const luminance=value=>{
      const rgb=value.match(/[\d.]+/g).slice(0,3).map(n=>{const v=Number(n)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});
      return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
    };
    return [...document.querySelectorAll('#design-card-shortcuts button')].map(button=>{
      const style=getComputedStyle(button),a=luminance(style.color),b=luminance(style.backgroundColor);
      return {text:button.textContent,ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
    });
  });
  assert(contrast.length>=2&&contrast.every(item=>item.ratio>=4.5),JSON.stringify(contrast));
  assert(dark(await darkSurfaces('#design-card-shortcuts button')));
  await page.locator('[data-opening-shortcut="55144522"]').click();
  await page.screenshot({path:path.join(evidence,'selection-final-shortcuts.png')});
  assert.equal(await page.evaluate(()=>flow.design.conditions.slots[0]),55144522);
  await page.locator('[data-slot="1"]').click();
  const pickerColors=await darkSurfaces('#opening-dialog, #opening-dialog button:not(.primary)');
  assert(dark(pickerColors),JSON.stringify(pickerColors));
  await page.screenshot({path:path.join(evidence,'selection-final-slot-picker.png')});
  await page.locator('[data-shortcut-choice="55144522"]').click();
  assert.equal(await page.evaluate(()=>flow.design.conditions.slots[1]),55144522);
  await page.evaluate(()=>{globalThis.openingDragTrace=[];for(const type of ['pointerdown','pointermove','pointerup'])document.addEventListener(type,event=>{if(globalThis.openingDragTrace.length<30)globalThis.openingDragTrace.push({type,x:event.clientX,y:event.clientY,slot:document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-slot]')?.dataset.slot,drag:deckSelection.drag?.code,active:deckSelection.drag?.active});});});
  await page.locator('[data-opening-shortcut="55144522"]').dragTo(page.locator('[data-slot="3"]'));
  assert.deepEqual(await page.evaluate(()=>flow.design.conditions.slots),[55144522,55144522,null,55144522,null],JSON.stringify(await page.evaluate(()=>globalThis.openingDragTrace)));
  await page.locator('[data-opening-shortcut="55144522"]').dragTo(page.locator('[data-slot="4"]'));
  assert.equal(await page.evaluate(()=>flow.design.conditions.slots[4]),null);
  const names=await page.evaluate(()=>[55144522,1184620].map(code=>app.cache.get(code).name));
  await application.evaluate(({clipboard})=>{globalThis.previewClipboardWriter=clipboard.writeText;clipboard.writeText=text=>{globalThis.previewCopied=text;};});
  try {
    await page.locator('#copy-design-card-names').click();
    await page.waitForFunction(()=>!deckSelection.copying);
    assert.equal(await application.evaluate(()=>globalThis.previewCopied),names.join(' + '));
  } finally {await application.evaluate(({clipboard})=>{clipboard.writeText=globalThis.previewClipboardWriter;});}
  assert.deepEqual((await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),saved.id)).deck,saved.deck);
  pass('Final preview: clean card artwork, popup marks, dark hover/pinned panels and slot picker, 4.5:1 button contrast, click/drag candidates with stock checks and isolated clipboard IPC; source deck preserved');
};
