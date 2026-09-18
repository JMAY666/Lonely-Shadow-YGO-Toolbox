'use strict';
// Three independent live rounds, armed only after the user explicitly is ready.
// All game actions stay with the player; only our isolated Electron UI is driven.
const {_electron:electron}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const workspace=path.resolve(__dirname,'..'),label=process.env.YGO_TEST_RUN;
assert(label&&/^[a-z0-9-]+$/.test(label),'Set an explicit isolated run label');
const platform=process.env.YGO_SMART_PLATFORM||'ygopro';
assert(['ygopro','ygopro2'].includes(platform),'Unsupported platform');
const root=path.join(workspace,'.local',platform+'-smart-live-'+label),evidence=path.join(root,'evidence');
fs.mkdirSync(evidence,{recursive:true});
let application,page,timer,busy=false,previous='',closed=false;
const errors=[];
async function capture(name){
  await page.evaluate(async()=>{
    const images=[...document.images].filter(image=>image.getBoundingClientRect().width>0);
    for(const image of images)image.loading='eager';
    await Promise.all(images.map(image=>image.decode().catch(()=>{})));
    for(const animation of document.getAnimations())if(Number.isFinite(animation.effect?.getComputedTiming().endTime))animation.finish();
  });
  const png=await application.evaluate(async({BrowserWindow})=>{
    const contents=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents;
    await contents.capturePage(undefined,{stayHidden:true});
    await new Promise(resolve=>setTimeout(resolve,150));
    return(await contents.capturePage(undefined,{stayHidden:true})).toPNG().toString('base64');
  });
  fs.writeFileSync(path.join(evidence,name+'.png'),Buffer.from(png,'base64'));
}
async function finish(){
  closed=true;clearInterval(timer);
  if(page)await page.evaluate(()=>cancelSmartRecognition()).catch(()=>{});
  if(application){await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(w=>w.destroy()));await application.close();}
}
async function observe(){
  if(busy||closed)return;busy=true;
  try{
    const state=await page.evaluate(()=>({recognition:smartRun()?.value||null,stage:duelState().stage,
      workspace:autoDuelState()?{context:autoDuelState().context,matching:autoDuelState().matching,
        matchError:autoDuelState().matchError,result:autoDuelState().result?{reason:autoDuelState().result.reason,
          matches:autoDuelState().result.matches.map(p=>({id:p.id,revision:p.automatic_revision}))}:null,
        compute:autoDuelState().openingForecast?{job:autoDuelState().openingForecast.job,status:{status:autoDuelState().openingForecast.jobState?.status,
          progress:autoDuelState().openingForecast.jobState?.progress,version:autoDuelState().openingForecast.jobState?.version},
          busy:autoDuelState().openingForecast.busy,error:autoDuelState().openingForecast.error,
          inputs:autoDuelState().openingForecast.data?.inputs,
          candidates:autoDuelState().openingForecast.data?.result?.candidates?.length}:null}:null}));
    const key=JSON.stringify(state);
    if(key!==previous){
      previous=key;const record={time:new Date().toISOString(),...state};
      fs.writeFileSync(path.join(evidence,'latest.json'),JSON.stringify(record,null,2));
      fs.appendFileSync(path.join(evidence,'observations.jsonl'),JSON.stringify(record)+'\n');
      // Console deliberately omits card ids, deck names, paths and process identity.
      console.log(JSON.stringify({stage:state.recognition?.stage||'idle',page:state.stage,
        hand_count:state.recognition?.frame?.opening?.cards?.length,
        matches:state.workspace?.result?.matches?.length,compute:state.workspace?.compute?.status?.status,error:state.recognition?.error||state.workspace?.compute?.error||''}));
    }
    const control=path.join(root,'control.json');
    if(!fs.existsSync(control))return;
    const command=JSON.parse(fs.readFileSync(control,'utf8'));fs.renameSync(control,path.join(evidence,'control-'+Date.now()+'.json'));
    if(command.action==='arm'){
      await page.evaluate(async()=>{await switchModule('duel');await startNewDuel();const s=duelState();s.mode='BO1';s.operationMode='automatic';s.functionPage='platform';s.stage=s.reached=duelStages.function;renderDuel();});
      await page.locator(`[data-duel-action="platform-${platform}"]`).click();
      await page.waitForFunction(()=>document.querySelector('#duel-capture-dialog').dataset.busy==='false');
      if(!await page.evaluate(()=>!!duelState().automatic.connection)){
        const choices=page.locator('#duel-capture-processes [data-capture-pid]');
        if(await choices.count()===1)await choices.click();
      }
      await page.waitForFunction(()=>!!duelState().automatic.connection,null,{timeout:15000});
      await page.locator('#duel-capture-smart').click();
      await page.waitForFunction(()=>!!smartRun()?.value);
      await capture('armed-'+Date.now());console.log('ARMED: waiting for operator go-ahead.');
    }
    if(command.action==='cancel'){await page.locator('#duel-capture-close').click();await capture('cancelled-'+Date.now());console.log('CANCELLED');}
    if(command.action==='inspect-input'){
      assert.equal(await page.evaluate(()=>smartRun()?.value?.stage),'ready');
      await page.locator('[data-duel-stage="4"]').first().click();await capture('verified-input-'+Date.now());
      await page.locator('[data-auto-duel-action="smart-plans"]').click();await capture('plan-selection-'+Date.now());
    }
    if(command.action==='snapshot')await capture('snapshot-'+Date.now());
    if(command.action==='close')await finish();
  }catch(error){errors.push(error.message);fs.writeFileSync(path.join(evidence,'errors.json'),JSON.stringify(errors,null,2));console.error(error.message);}
  finally{busy=false;}
}
(async()=>{
  const env={...process.env,YGO_DESKTOP_TEST:'1',YGO_DESKTOP_BACKGROUND:'1'};delete env.ELECTRON_RUN_AS_NODE;
  application=await electron.launch({executablePath:require('electron'),args:[workspace,'--data-dir',root,'--import-from',process.env.YGO_SMART_IMPORT||path.join(workspace,'.local/YGOPro-Lite')],env,timeout:120000});
  page=await application.firstWindow();page.on('pageerror',error=>{errors.push(error.message);console.error(error.message);});
  await page.waitForFunction(()=>document.querySelector('#resource-count')?.textContent.includes('张卡牌'),null,{timeout:300000});
  await application.evaluate(({BrowserWindow})=>{const window=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());window.webContents.setZoomFactor(1);window.setContentSize(1280,900);});
  console.log(JSON.stringify({status:'WAITING_FOR_USER_READY',root,evidence}));
  timer=setInterval(()=>void observe(),250);
})().catch(async error=>{console.error(error.stack);await finish().catch(()=>{});process.exitCode=1;});
