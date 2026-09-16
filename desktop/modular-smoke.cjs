'use strict';
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
const fs=require('node:fs');
module.exports=async({page,root,evidence,pass})=>{
  await page.evaluate(async()=>{flow.restarting=true;displayView('training');await syncNativeHost();});
  const service=require(path.join(root,'runtime','_trainer','service.json'));
  const layoutRequest=path.join(evidence,'modular-layout.request');
  const previewRequest=path.join(evidence,'modular-preview.request');
  let layoutBusy=false;
  const layoutTimer=setInterval(async()=>{
    if(layoutBusy||(!fs.existsSync(layoutRequest)&&!fs.existsSync(previewRequest)))return;layoutBusy=true;
    try{
      if(fs.existsSync(previewRequest)) {
        await page.evaluate(async()=>{await refreshHistory();await switchModule('modular');await refreshModular(true);});
        assert(await page.locator('.modular-route').count()>0);
        await page.screenshot({path:path.join(evidence,'modular-candidates.png')});
        await page.locator('#modular-field').scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(evidence,'modular-live-field.png'),preserveScroll:true});
        await page.evaluate(async()=>{await switchModule('expansion');displayView('training');await syncNativeHost();});
        fs.unlinkSync(previewRequest);
      }
      if(fs.existsSync(layoutRequest)) {
        await page.evaluate(async()=>{await refreshHistory();displayView('training');await syncNativeHost();});fs.unlinkSync(layoutRequest);
      }
    }catch(error){if(!page.isClosed())console.error('Modular test layout:',error.message);}finally{layoutBusy=false;}
  },100);
  const python=spawn('python',['-u',path.resolve(__dirname,'../tests/modular_engine_acceptance.py'),path.join(root,'runtime'),service.url,evidence],{windowsHide:true,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
  let output='';python.stdout.on('data',data=>{output+=data;process.stdout.write(data);});python.stderr.on('data',data=>{output+=data;process.stderr.write(data);});
  const code=await new Promise(resolve=>python.once('exit',resolve));
  clearInterval(layoutTimer);
  assert.equal(code,0,output.slice(-7000));
  if(process.env.YGO_MODULAR_PIPELINE_ONLY==='1')await require('./modular-duel-smoke.cjs')({page,root,evidence,pass});
  await page.evaluate(async()=>{await refreshHistory();flow.restarting=false;await switchModule('modular');});
  assert(await page.locator('#modular').isVisible());
  await page.screenshot({path:path.join(evidence,'modular.png')});
  pass('Modular routes use actual native decisions, disposable simulation and an isolated source library');
};
