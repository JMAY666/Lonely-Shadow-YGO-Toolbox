'use strict';
// Own hidden acceptance app only. No system pointer or global keyboard input.
const { _electron: electron } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const workspace = path.resolve(__dirname, '../..');
const base = path.join(workspace, '.local/ygo-learning/p0b-p1');
const secondary = process.argv.includes('--secondary');
const root = path.join(base, 'desktop-check-development-modular' + (secondary?'-secondary':''));
let app, child, metricsTimer;
(async () => {
  fs.mkdirSync(path.join(base, 'empty-import'), {recursive:true});
  const env = {...process.env, YGO_DESKTOP_TEST:'1', YGO_DESKTOP_BACKGROUND:'1', YGO_TRAIN_LEARNING:'1'};
  delete env.ELECTRON_RUN_AS_NODE;
  app = await electron.launch({executablePath:require('electron'),
    args:[workspace,'--data-dir',root,'--import-from',path.join(base,'empty-import')],env,timeout:120000});
  const page = await app.firstWindow();
  await page.waitForFunction(() => document.querySelector('#resource-count')?.textContent.includes('张卡牌'),null,{timeout:300000});
  await app.evaluate(({BrowserWindow}) => {
    const window = BrowserWindow.getAllWindows().find(w => !w.getParentWindow());
    window.webContents.setBackgroundThrottling(false);
    if(window.isVisible()) throw new Error('Learning acceptance window must remain hidden');
  });
  await page.evaluate(async () => {flow.restarting=true;displayView('training');await syncNativeHost();});
  const service = JSON.parse(fs.readFileSync(path.join(root,'runtime/_trainer/service.json'),'utf8'));
  async function metrics() {
    const pids=await app.evaluate(({app})=>app.getAppMetrics().map(row=>row.pid));
    fs.writeFileSync(path.join(root,'learning-processes.json'),JSON.stringify({time:Date.now(),pids:[process.pid,service.pid,...pids]}));
  }
  await metrics();metricsTimer=setInterval(()=>metrics().catch(()=>{}),1000);
  child = spawn(path.join(workspace,'.local/ygo-agent-pilot/.venv/Scripts/python.exe'),
    ['-u',path.join(__dirname,'p1_run.py'),'--runtime',path.join(root,'runtime'),'--url',service.url,...process.argv.slice(2).filter(a=>a!=='--secondary')],
    {windowsHide:true,env:{...env,PYTHONIOENCODING:'utf-8'},stdio:'inherit'});
  const timer=setTimeout(() => child.kill(), 2*60*60*1000);
  const code=await new Promise((resolve,reject)=>{child.once('error',reject);child.once('exit',resolve);}).finally(()=>clearTimeout(timer));
  if(code!==0) throw new Error(`P1 worker exited ${code}`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
  clearInterval(metricsTimer);
  if(child&&child.exitCode===null)child.kill();
  if(app){await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(w=>w.destroy())).catch(()=>{});await app.close().catch(()=>{});}
});
