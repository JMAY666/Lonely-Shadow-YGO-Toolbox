'use strict';
// Real old/new packaged startup on an isolated LOCALAPPDATA; no production files.
const {_electron} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {once} = require('node:events');
const workspace=path.resolve(__dirname,'..'), config=require('../package.json');
const index=process.argv.indexOf('--legacy-exe');
if(index<0||!process.argv[index+1])throw Error('Specify --legacy-exe with the retained previous packaged executable.');
const legacy=path.resolve(process.argv[index+1]);
const current=path.join(workspace,config.build.directories.output,'win-unpacked',config.build.win.executableName+'.exe');
const root=path.join(workspace,'.local','upgrade-check-'+Date.now()), data=path.join(root,'YGOTrainer');
const evidence=path.join(workspace,'.local','evidence','upgrade-1.11.0.json');
const fixtureRoot=path.join(workspace,'.local','desktop-check-development','runtime','_trainer');
const planFile=fs.readdirSync(path.join(fixtureRoot,'plans')).filter(file=>file.endsWith('.json')).find(file=>{
  const plan=JSON.parse(fs.readFileSync(path.join(fixtureRoot,'plans',file),'utf8'));
  const journal=path.join(fixtureRoot,'sessions',plan.id,'native.jsonl');
  return !plan.imported&&fs.existsSync(journal)&&JSON.parse(fs.readFileSync(journal,'utf8').split('\n')[0]).test_control===true;
});
assert(planFile,'Run desktop acceptance first to create synthetic session and plan fixtures.');
const fixture=JSON.parse(fs.readFileSync(path.join(fixtureRoot,'plans',planFile),'utf8'));
const env={...process.env,LOCALAPPDATA:root,YGO_DESKTOP_BACKGROUND:'1',YGO_DESKTOP_TEST:'0'};
delete env.ELECTRON_RUN_AS_NODE;
let application,page;
async function launch(executable) {
  application=await _electron.launch({executablePath:executable,args:[],env,timeout:180000});
  page=await application.firstWindow();
  await page.waitForFunction(()=>document.querySelector('#resource-count')?.textContent.includes('张卡牌'),null,{timeout:300000});
  assert.equal(await application.evaluate(({app})=>app.getPath('userData')),path.join(data,'electron'));
}
async function close() {
  const exited=once(application.process(),'exit');
  await application.evaluate(({BrowserWindow,dialog})=>{
    dialog.showMessageBox=async()=>({response:1});
    BrowserWindow.getAllWindows().find(window=>!window.getParentWindow()).close();
  });
  await exited; application=null;
}
function inventory() {
  const paths=['runtime/system.conf','migration-backups','runtime/_trainer/decks','runtime/_trainer/plans','runtime/_trainer/sessions','runtime/_trainer/backups'];
  const result={};
  function walk(relative) {
    const full=path.join(data,relative); if(!fs.existsSync(full))return;
    if(fs.statSync(full).isDirectory())for(const file of fs.readdirSync(full))walk(path.join(relative,file));
    else result[relative]=crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');
  }
  paths.forEach(walk);return result;
}
(async()=>{
  await launch(legacy);
  const deck=await page.evaluate(async()=>{
    const saved=await api('/api/decks',{name:'升级兼容验收',deck:{main:Array(40).fill(55144522),extra:[23995346],side:[]}});
    return api('/api/decks',{...saved,deck:{...saved.deck,side:[1184620]}});
  });
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setSize(1180,820));
  await close();
  const trainer=path.join(data,'runtime','_trainer');
  fs.mkdirSync(path.join(trainer,'plans'),{recursive:true});
  fs.copyFileSync(path.join(fixtureRoot,'plans',planFile),path.join(trainer,'plans',planFile));
  fs.cpSync(path.join(fixtureRoot,'sessions',fixture.id),path.join(trainer,'sessions',fixture.id),{recursive:true});
  fs.mkdirSync(path.join(data,'migration-backups','compatibility'),{recursive:true});
  fs.writeFileSync(path.join(data,'migration-backups','compatibility','note.txt'),'isolated prior backup');
  fs.appendFileSync(path.join(data,'runtime','system.conf'),'\n# isolated upgrade setting\n');
  await launch(legacy);
  const before=await page.evaluate(async id=>({report:await api('/api/report/'+id),plan:await api('/api/plan/'+id),history:await api('/api/history')}),fixture.id);
  await close();
  const hashes=inventory(), bounds=JSON.parse(fs.readFileSync(path.join(data,'window.json'),'utf8'));
  await launch(current);
  assert.equal(await page.title(),config.build.productName);
  const size=await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].getSize());
  assert.deepEqual(size,[bounds.width,bounds.height]);
  assert.deepEqual(await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),deck.id),deck);
  const after=await page.evaluate(async id=>({report:await api('/api/report/'+id),plan:await api('/api/plan/'+id),history:await api('/api/history')}),fixture.id);
  assert.deepEqual(after,before);
  await require('./navigation-test.cjs')(page, 'expansion');
  await page.waitForFunction(()=>moduleUI.current==='expansion'&&!moduleUI.switching);
  await page.evaluate(id=>showPlan(id),fixture.id);
  assert.equal(await page.locator('#plans').isVisible(),true);
  assert.deepEqual(inventory(),hashes);
  await close();
  assert.deepEqual(inventory(),hashes);
  fs.mkdirSync(path.dirname(evidence),{recursive:true});
  fs.writeFileSync(evidence,JSON.stringify({legacy,current,root,filesVerified:Object.keys(hashes).length,
    defaultPath:true,deck:true,plan:true,history:true,settings:true,backups:true,unchangedHashes:true},null,2));
  console.log(`PASS Actual previous/new EXEs share default YGOTrainer storage: deck, plan, report, history, window settings and ${Object.keys(hashes).length} unchanged files`);
})().catch(async error=>{
  console.error(error);
  if(application){await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(window=>window.destroy())).catch(()=>{});await application.close().catch(()=>{});}
  process.exitCode=1;
});
