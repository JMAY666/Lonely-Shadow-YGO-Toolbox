'use strict';
// Real official package acceptance, isolated app profile and native test interface only.
const {_electron:electron}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {once}=require('node:events');
const workspace=path.resolve(__dirname,'..'),packaged=process.argv.includes('--packaged');
const kind=packaged?'packaged':'development';
const root=path.join(workspace,'.local','superpre-acceptance-'+kind);
const evidence=path.join(workspace,'.local','evidence','superpre-'+kind);
fs.mkdirSync(evidence,{recursive:true});
const config=require('../package.json');
const executable=packaged?path.resolve(workspace,process.env.YGO_PACKAGE_DIR||config.build.directories.output,'win-unpacked',config.build.win.executableName+'.exe'):require('electron');
const env={...process.env,YGO_DESKTOP_TEST:'1',YGO_DESKTOP_BACKGROUND:'1'};delete env.ELECTRON_RUN_AS_NODE;
let application,page;
const errors=[],checks=[];
const pass=message=>{checks.push(message);console.log('PASS '+message);};
const request=(url,body)=>page.evaluate(({url,body})=>api(url,body),{url,body});
async function launch() {
  application=await electron.launch({executablePath:executable,args:[...(packaged?[]:[workspace]),'--data-dir',root],env,timeout:120000});
  page=await application.firstWindow();page.on('pageerror',error=>errors.push(error.message));
  await page.waitForFunction(()=>document.querySelector('#resource-count')?.textContent.includes('张卡牌'),null,{timeout:300000});
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.waitForFunction(()=>innerWidth===1280);
}
async function close() {
  const exited=once(application.process(),'exit');
  await application.evaluate(({dialog,BrowserWindow})=>{
    dialog.showMessageBox=async()=>({response:1});
    BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).close();
  });
  await exited;application=null;
}
async function screenshot(name) {
  await page.evaluate(()=>document.getAnimations().forEach(a=>{if(Number.isFinite(a.effect?.getComputedTiming().endTime))a.finish();}));
  const data=await application.evaluate(async({BrowserWindow})=>{
    const web=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents;
    await web.capturePage(undefined,{stayHidden:true});
    await new Promise(resolve=>setTimeout(resolve,150));
    return (await web.capturePage(undefined,{stayHidden:true})).toPNG().toString('base64');
  });
  fs.writeFileSync(path.join(evidence,name+'.png'),Buffer.from(data,'base64'));
}
async function settled() {
  await page.waitForFunction(()=>superpreUI.state,null,{timeout:15000}).catch(async()=>{
    throw new Error('Patch panel did not load: '+await page.locator('#notice').textContent());
  });
  await page.waitForFunction(()=>superpreUI.state&&!superpreUI.state.job.busy&&!superpreUI.request,null,{timeout:180000});
  const state=await request('/api/superpre');assert.equal(state.job.error,'',state.job.error);return state;
}
async function action(name) {
  await page.locator('#superpre-'+name).click();
  return settled();
}
async function native(id,kind='capture',point={}) {
  const state=await request('/api/native/test',{id,kind,...point});
  fs.writeFileSync(path.join(evidence,'native-latest.json'),JSON.stringify(state,null,2));
  return state;
}
async function nativeWait(id,predicate) {
  for(let attempt=0;attempt<100;attempt++){
    if(!(await request('/api/native/status?id='+id)).frame_ready){await page.waitForTimeout(150);continue;}
    const state=await native(id);if(predicate(state))return state;
    await page.waitForTimeout(150);
  }
  throw new Error('Native prompt did not settle; see native-latest.json');
}
async function run() {
  await launch();
  assert.equal(await page.locator('#app-settings').count(),1);
  assert.equal(await page.locator('.app-bar #app-settings').count(),0);
  const a=await page.locator('#app-settings').boundingBox(),b=await page.locator('#module-tags').boundingBox();
  assert(b.y>=a.y+a.height&&b.y-a.y-a.height<=12);
  await page.locator('#app-settings').click();await settled();
  let state=await request('/api/superpre');
  if(state.installed)await action('uninstall');
  const before=await request('/api/bootstrap');
  state=await action('install');
  assert(state.installed&&state.latest.updated_ms&&state.latest.download_url.endsWith('.ypk'));
  assert((await request('/api/bootstrap')).cards>before.cards);
  assert(await page.locator('#superpre-update').isDisabled());
  assert(!(await page.locator('#superpre-uninstall').isDisabled()));
  const code=100267031;
  const card=await request('/api/card/'+code);assert(card.script_available&&card.name);
  const found=await request('/api/cards?q='+code);assert(found.cards.some(c=>c.id===code));
  const image=await page.evaluate(async code=>{const r=await fetch('/pics/'+code+'.jpg');return {type:r.headers.get('content-type'),size:(await r.arrayBuffer()).byteLength};},code);
  assert.match(image.type,/image\/jpeg/);assert(image.size>1000);
  await screenshot('settings-installed');
  pass('Settings sits immediately above TAG management; official metadata, install, searchable cards, scripts and images are live');
  // Preserve an unsaved setting and deck edit while inspecting the patch controls.
  await page.locator('#duel-default-count').fill('6');await action('check');
  assert.equal(await page.locator('#duel-default-count').inputValue(),'6');
  await page.locator('#app-settings-cancel').click();
  const deck=await request('/api/decks',{name:'超先行隔离验收-'+Date.now(),deck:{main:[code,...Array(39).fill(1184620)],extra:[],side:[]}});
  const originalDeck=fs.readFileSync(path.join(root,'runtime','_trainer','decks',deck.id.split('/').slice(1).join('/')));
  await close();await launch();
  assert.equal((await request('/api/card/'+code)).name,card.name);
  pass('Restart preserves the installed patch and both native/web resources');
  await page.evaluate(()=>switchModule('expansion'));
  await page.evaluate(()=>{switchView('training');return syncNativeHost();});
  const session=await request('/api/start',{deck_id:deck.id,design:{name:'超先行脚本验收',revision:deck.revision,conditions:{hand_count:5,slots:[code,1184620,1184620,1184620,1184620],banned:[]},opponent_ai:false}});
  await page.evaluate(session=>{app.active=session;app.reportId=session.id;switchView('training');return syncNativeHost();},session);
  let ui=await nativeWait(session.id,s=>s.prompt===11&&s.targets.some(c=>c.code===code&&c.location===2));
  let target=ui.targets.find(c=>c.code===code&&c.location===2);
  await native(session.id,'click',{x:target.x,y:target.y});
  ui=await nativeWait(session.id,s=>s.buttons.some(b=>b.text==='发动'));target=ui.buttons.find(b=>b.text==='发动');
  await native(session.id,'click',{x:target.x,y:target.y});
  ui=await nativeWait(session.id,s=>s.prompt===18);target=ui.targets.find(c=>c.location===4&&c.sequence===0);
  await native(session.id,'click',{x:target.x,y:target.y});
  ui=await nativeWait(session.id,s=>s.prompt===11||s.prompt===19&&s.buttons.some(b=>b.text===''));
  if(ui.prompt===19){target=ui.buttons.find(b=>b.text==='');assert(target,'Face-up position button is available');await native(session.id,'click',{x:target.x,y:target.y});}
  await nativeWait(session.id,s=>s.prompt===11&&s.targets.some(c=>c.code===code&&c.location===4));
  const report=await request('/api/report/'+session.id);
  assert(report.final_state.cards.some(c=>c.code===code&&c.location===4));
  assert(report.final_state.cards.some(c=>c.location===32),'Official summon trigger banishes one deck card');
  await page.locator('#app-settings').click();await settled();
  await page.locator('#superpre-uninstall').click();
  await page.waitForFunction(()=>document.querySelector('#superpre-error').textContent.includes('先结束'));
  assert.equal((await request('/api/native/status?id='+session.id)).visible,false,'Native child cannot cover settings');
  assert((await request('/api/superpre')).installed);
  await page.locator('#app-settings-cancel').click();
  await nativeWait(session.id,s=>s.prompt===11);
  pass('Official Lua effect special summons the new card and resolves its banish trigger; running engine blocks uninstall');
  await request('/api/stop',{id:session.id});
  for(let i=0;i<100;i++){
    const history=await request('/api/history');if(history.find(h=>h.id===session.id)?.status==='completed')break;
    await page.waitForTimeout(150);
  }
  await page.locator('#app-settings').click();await settled();await action('uninstall');
  await assert.rejects(request('/api/card/'+code));
  assert.equal((await request('/api/bootstrap')).cards,before.cards);
  assert.deepEqual(fs.readFileSync(path.join(root,'runtime','_trainer','decks',deck.id.split('/').slice(1).join('/'))),originalDeck);
  assert.equal((await request('/api/report/'+session.id)).catalog[String(code)].name,card.name);
  await screenshot('settings-uninstalled');
  pass('Uninstall removes the live patch while preserving deck bytes and the recorded card snapshot');
  await close();await launch();
  assert.equal((await request('/api/superpre')).installed,null);
  assert.equal((await request('/api/bootstrap')).cards,before.cards);
  await close();assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(evidence,'result.json'),JSON.stringify({kind,checks,errors,release:state.latest},null,2));
}
run().catch(async error=>{
  fs.writeFileSync(path.join(evidence,'failure.txt'),error.stack||String(error));
  console.error(error);
  if(application){
    await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(w=>w.destroy())).catch(()=>{});
    await application.close().catch(()=>{});
  }
  process.exitCode=1;
});
