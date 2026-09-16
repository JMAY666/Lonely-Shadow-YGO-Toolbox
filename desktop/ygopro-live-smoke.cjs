'use strict';
// Explicit opt-in live acceptance. Only read YGOPro; all writes use an isolated profile.
const {_electron:electron}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),readline=require('node:readline');
const workspace=path.resolve(__dirname,'..'),label=process.env.YGO_TEST_RUN||String(Date.now());
assert(/^[a-z0-9-]+$/.test(label));
const root=path.join(workspace,'.local','ygopro-live-'+label),evidence=path.join(root,'evidence');
fs.mkdirSync(evidence,{recursive:true});
let application,page,baseline,busy=false;
const errors=[];
const click=async action=>{await page.locator(`[data-duel-action="${action}"]`).click();await page.waitForFunction(()=>!duelUI.busy);};
const saveEvidence=(name,value)=>fs.writeFileSync(path.join(evidence,name+'.json'),JSON.stringify(value,null,2));
async function phase(number) {
  await click('get-deck');
  const current=await page.evaluate(()=>({fresh:duelState().automatic.fresh,...duelState().automatic.deck}));
  assert(current.fresh,'A failed read must never be saved');
  if(number!==1)assert.notDeepEqual(current.deck,baseline.saved.deck,'Waiting for the user to change the live deck');
  await click('recognition-next');
  if(number===3)await page.locator('#duel-auto-name').fill('实时捕捉验收-第二套');
  if(number===1||number===3)await click('auto-tags');
  await page.locator('#duel-auto-save').click();await page.waitForFunction(()=>!duelUI.busy);
  if(number!==3){assert(await page.locator('#duel-auto-overwrite').isVisible());await click('confirm-auto-overwrite');}
  const saved=await page.evaluate(async()=>{const name=duelState().automatic.name,items=(await api('/api/decks')).filter(d=>d.name===name);if(items.length!==1)throw Error('Duplicate saved deck');return api('/api/deck?id='+encodeURIComponent(items[0].id));});
  assert.deepEqual(saved.deck,current.deck);
  if(number!==3){assert.equal(saved.id,baseline.saved.id);if(number===2)assert.notEqual(saved.revision,baseline.saved.revision);}
  else {assert.notEqual(saved.id,baseline.saved.id);assert.deepEqual(await page.evaluate(async id=>(await api('/api/deck?id='+encodeURIComponent(id))).deck,baseline.saved.id),baseline.saved.deck);}
  const result={captured:current,saved,previous:baseline.saved};saveEvidence('phase-'+number,result);
  await page.screenshot({path:path.join(evidence,'phase-'+number+'.png')});
  await page.locator('[data-duel-deck-page="recognition"]').click();
  baseline=result;
  console.log(JSON.stringify({phase:number,status:'PASS',counts:Object.fromEntries(Object.entries(saved.deck).map(([z,v])=>[z,v.length])),id:saved.id,evidence}));
}
async function main() {
  const env={...process.env,YGO_DESKTOP_TEST:'1',YGO_DESKTOP_BACKGROUND:'1'};delete env.ELECTRON_RUN_AS_NODE;
  application=await electron.launch({executablePath:require('electron'),args:[workspace,'--data-dir',root,'--import-from',path.join(workspace,'.local','YGOPro-Lite')],env,timeout:120000});
  page=await application.firstWindow();page.on('pageerror',e=>errors.push(e.message));
  await page.waitForFunction(()=>document.querySelector('#resource-count')?.textContent.includes('张卡牌'),null,{timeout:300000});
  await application.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.webContents.setZoomFactor(1);w.setContentSize(1280,900);});
  page.screenshot=async({path:target})=>{
    await page.evaluate(()=>document.getAnimations().forEach(a=>{if(Number.isFinite(a.effect?.getComputedTiming().endTime))a.finish();}));
    const png=await application.evaluate(async({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());await w.webContents.capturePage(undefined,{stayHidden:true});await new Promise(resolve=>setTimeout(resolve,150));return(await w.webContents.capturePage(undefined,{stayHidden:true})).toPNG().toString('base64');});
    fs.writeFileSync(target,Buffer.from(png,'base64'));
  };
  await page.locator('#module-duel').click();await page.waitForFunction(()=>moduleUI.current==='duel'&&!moduleUI.switching);
  await click('bo1');
  baseline=await require('./automatic-selection-smoke.cjs')({page,application,evidence,pass:console.log,live:true});
  assert.deepEqual(errors,[]);saveEvidence('phase-1',baseline);
  console.log(JSON.stringify({phase:1,status:'PASS',counts:Object.fromEntries(Object.entries(baseline.saved.deck).map(([z,v])=>[z,v.length])),id:baseline.saved.id,evidence}));
  console.log('WAITING: restart / phase2 / phase3 / close');
  const input=readline.createInterface({input:process.stdin});
  input.on('line',async line=>{
    if(busy)return;busy=true;
    try {
      if(line.trim()==='close'){input.close();await application.close();process.exit(0);}
      if(line.trim()==='restart')await phase(1);
      if(/^phase[23]$/.test(line.trim()))await phase(Number(line.trim().slice(-1)));
    } catch(error){console.error(error.stack);saveEvidence('last-error',{message:error.message,errors});}
    finally{busy=false;console.log('WAITING: restart / phase2 / phase3 / close');}
  });
}
main().catch(async error=>{console.error(error.stack);saveEvidence('error',{message:error.message,errors});await application?.close().catch(()=>{});process.exitCode=1;});
