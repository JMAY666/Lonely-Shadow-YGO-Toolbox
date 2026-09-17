'use strict';
// Explicit live acceptance: YGOPro actions are always performed by the user.
const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path');
const assert=require('node:assert/strict'),workspace=path.resolve(__dirname,'..');
const label=process.env.YGO_TEST_RUN||String(Date.now());assert(/^[a-z0-9-]+$/.test(label));
const openingMode=process.argv.includes('--opening');
const root=path.join(workspace,'.local',(openingMode?'ygopro-opening-live-':'ygopro-order-live-')+label),evidence=path.join(root,'evidence');
fs.mkdirSync(evidence,{recursive:true});
const deck=JSON.parse(fs.readFileSync(process.env.YGO_ORDER_LIVE_DECK,'utf8'));
const errors=[];let application,page,observer;
async function capture(name) {
  const png=await application.evaluate(async({BrowserWindow})=>{
    const contents=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents;
    await contents.capturePage(undefined,{stayHidden:true});await new Promise(r=>setTimeout(r,150));
    return(await contents.capturePage(undefined,{stayHidden:true})).toPNG().toString('base64');
  });
  fs.writeFileSync(path.join(evidence,name+'.png'),Buffer.from(png,'base64'));
}
(async()=>{
  const env={...process.env,YGO_DESKTOP_TEST:'1',YGO_DESKTOP_BACKGROUND:'1'};delete env.ELECTRON_RUN_AS_NODE;
  application=await electron.launch({executablePath:require('electron'),args:[workspace,'--data-dir',root,'--import-from',path.join(workspace,'.local/YGOPro-Lite')],env,timeout:120000});
  page=await application.firstWindow();page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
  await page.waitForFunction(()=>document.querySelector('#resource-count')?.textContent.includes('张卡牌'),null,{timeout:300000});
  await application.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.webContents.setZoomFactor(1);w.setContentSize(1280,900);});
  await page.locator('#module-duel').click();await page.waitForFunction(()=>moduleUI.current==='duel'&&!moduleUI.switching);
  // The preceding deck flow was separately validated; seed its isolated snapshot.
  await page.evaluate(async deck=>{
    const attached=await api('/api/ygopro/attach',{});if(!attached.connected)throw Error(attached.error);
    const s=duelState();s.mode='BO1';s.operationMode='automatic';s.stage=s.reached=duelStages.deck;
    const draft=s.automatic;draft.connection=attached.process;draft.platform='ygopro';draft.page='preview';
    DuelAutomatic.accept(draft,{deck,captured_ms:Date.now(),method:'acceptance-baseline'});renderDuel();
  },deck);
  await page.locator('[data-duel-action="start-duel"]').click();await page.waitForFunction(()=>duelState().stage===duelStages.order&&!duelUI.busy);
  await capture('waiting-start');
  console.log(JSON.stringify({status:'READY',root,evidence,frame:await page.evaluate(()=>duelState().automatic.order.frame)}));
  let previous='',writing=false;
  observer=setInterval(async()=>{
    if(writing)return;writing=true;
    try {
      const frame=await page.evaluate(()=>duelState().automatic.order?.frame);const key=JSON.stringify(frame);
      if(frame&&key!==previous){previous=key;const value={time:new Date().toISOString(),...frame};fs.appendFileSync(path.join(evidence,'observations.jsonl'),JSON.stringify(value)+'\n');
        fs.writeFileSync(path.join(evidence,'latest.json'),JSON.stringify(value,null,2));console.log(JSON.stringify(value));
        if(frame.phase==='choose_order'||frame.phase==='detected')await capture(frame.round_id+'-'+frame.phase);
        if(openingMode&&frame.opening?.status==='ready')await capture(frame.round_id+'-opening');
      }
      const control=path.join(root,'control.json');
      if(fs.existsSync(control)){
        const command=JSON.parse(fs.readFileSync(control,'utf8'));fs.renameSync(control,path.join(evidence,'command-'+Date.now()+'.json'));
        if(command.action==='confirm'){
          if(command.manual)await page.locator(`[data-duel-action="order-manual-${command.order}"]`).click();
          else if(await page.locator('[data-duel-action="order-use-detected"]').isEnabled())await page.locator('[data-duel-action="order-use-detected"]').click();
          await page.locator('[data-duel-action="confirm-order"]').click();await page.waitForFunction(()=>!duelUI.busy);
          assert.equal(await page.evaluate(()=>duelState().stage),duelStageHand);
          await capture('confirmed-'+Date.now());
        }
        if(command.action==='confirm-opening'){
          await page.locator('[data-duel-action="confirm-opening"]').click();await page.waitForFunction(()=>!duelUI.busy&&duelState().stage===5);
          await capture('opening-confirmed-'+Date.now());
        }
        if(command.action==='return'){
          if(await page.evaluate(()=>duelState().stage===5))await page.locator('[data-duel-action="opening-return"]').click();
          await page.locator('[data-duel-action="order-return"]').click();
        }
        if(command.action==='close'){clearInterval(observer);await application.close();}
      }
    }catch(error){console.error(error.stack);fs.writeFileSync(path.join(evidence,'observer-error.json'),JSON.stringify({error:error.message,errors}));}
    finally{writing=false;}
  },250);
})().catch(async error=>{console.error(error.stack);clearInterval(observer);await application?.close().catch(()=>{});process.exitCode=1;});
const duelStageHand=4;
