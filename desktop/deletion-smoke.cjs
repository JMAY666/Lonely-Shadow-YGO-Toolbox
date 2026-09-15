'use strict';
const {_electron} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {once} = require('node:events');
const workspace = path.resolve(__dirname, '..');
const packaged = process.argv.includes('--packaged');
const label = packaged ? 'packaged' : 'development';
const env = {...process.env, YGO_DESKTOP_BACKGROUND:'1'};
delete env.ELECTRON_RUN_AS_NODE;
let application;
(async () => {
  const executablePath = packaged ? path.join(workspace, require('../package.json').build.directories.output, 'win-unpacked', require('../package.json').build.win.executableName + '.exe') : require('electron');
  application = await _electron.launch({executablePath,env,args:[...(packaged?[]:[workspace]),'--data-dir',path.join(workspace,'.local',`desktop-check-${label}`)]});
  const page = await application.firstWindow();
  let systemDialogs = 0;
  page.on('dialog', async dialog => {systemDialogs++;await dialog.dismiss();});
  await page.waitForFunction(()=>document.querySelector('#resource-count')?.textContent.includes('张卡牌'),null,{timeout:120000});
  await page.waitForFunction(()=>app.history.length>0);
  await page.locator('#module-decks').click();
  await page.waitForFunction(()=>moduleUI.current==='decks'&&!moduleUI.switching);
  const fixtures = await page.evaluate(async () => {
    const decks=await api('/api/decks'); let template;
    for(const item of decks.filter(d=>d.source==='existing')) {
      const d=await api('/api/deck?id='+encodeURIComponent(item.id));
      if(new Set(Object.values(d.deck).flat()).size>20){template=d;break;}
    }
    if(!template)throw Error('A varied fixture deck is required');
    const name='Delete-regression-'+Date.now();
    const a=await api('/api/decks',{name:name+'-A',deck:template.deck});
    const b=await api('/api/decks',{name:name+'-B',deck:template.deck});
    await deckList();return {a:a.id,b:b.id,deck:template.deck,unique:new Set(Object.values(template.deck).flat()).size};
  });
  await page.locator('[data-open-deck='+JSON.stringify(fixtures.a)+']').click();
  await page.waitForFunction(id=>app.id===id&&!app.busy,fixtures.a);
  if (await page.locator('#deck-workbench').isVisible()) await page.locator('#back-to-decks').click();
  await page.locator('[data-open-deck='+JSON.stringify(fixtures.a)+']').click({button:'right'});
  await page.locator('[data-deck-command="delete"]').click();
  await page.locator('#delete-dialog').waitFor({state:'visible'});
  const ticks=await page.evaluate(async()=>{
    let frames=0;const start=performance.now();
    while(performance.now()-start<180){await new Promise(resolve=>setTimeout(resolve,10));frames++;}
    return frames;
  });
  assert(ticks>1,'Page events must continue while confirmation is open');
  await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!app.busy&&!document.querySelector('#delete-dialog').open);
  assert.equal(await page.evaluate(()=>app.id),null);
  assert.equal(await page.evaluate(()=>document.activeElement.id),'refresh-decks');
  if (await page.locator('#deck-workbench').isVisible()) await page.locator('#back-to-decks').click();
  await page.locator('[data-open-deck='+JSON.stringify(fixtures.a)+']').click({button:'right'});
  await page.locator('[data-deck-command="delete"]').click();
  await page.locator('#delete-confirm').waitFor({state:'visible'});
  const times=await page.evaluate(async next=>{
    const start=performance.now();document.querySelector('#delete-confirm').click();
    while(app.busy)await new Promise(resolve=>setTimeout(resolve,0));
    const removed=performance.now();const focused=document.activeElement.id;
    app.cache.clear();await openDeck(next);
    return {deleteMs:removed-start,nextOpenMs:performance.now()-removed,focus:focused};
  },fixtures.b);
  assert.equal(times.focus,'refresh-decks');
  assert.equal(await page.evaluate(()=>app.id),fixtures.b);
  assert.deepEqual(await page.evaluate(()=>app.deck),fixtures.deck);
  assert.equal(systemDialogs,0);
  // Remove only the second synthetic fixture; real decks and training reports are untouched.
  await page.locator('#back-to-decks').click();
  await page.locator('[data-open-deck='+JSON.stringify(fixtures.b)+']').click({button:'right'});
  await page.locator('[data-deck-command="delete"]').click();await page.locator('#delete-confirm').click();
  await page.waitForFunction(()=>!app.busy&&!app.id);
  const result={label,...times,timerTicksDuringConfirmation:ticks,systemDialogs,uniqueCards:fixtures.unique};
  fs.mkdirSync(path.join(workspace,'.local/evidence'),{recursive:true});
  fs.writeFileSync(path.join(workspace,'.local/evidence',`deletion-${label}.json`),JSON.stringify(result,null,2));
  const done=once(application.process(),'exit');
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].close());await done;
  console.log(JSON.stringify(result));
})().catch(async error=>{console.error(error);if(application)await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(w=>w.destroy())).catch(()=>{});process.exitCode=1;});
