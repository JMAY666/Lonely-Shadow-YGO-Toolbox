'use strict';
// Real Electron + embedded service + native engine acceptance. Test profiles remain local.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { once } = require('node:events');

const workspace = path.resolve(__dirname, '..');
const packaged = process.argv.includes('--packaged');
const label = packaged ? 'packaged' : 'development';
const onlyCompromise=process.argv.includes('--compromise-only');
const onlySelection=process.argv.includes('--selection-only');
const onlyDuel=process.argv.includes('--duel-only');
const onlySecond=process.argv.includes('--second-only');
const onlyAutomatic=process.argv.includes('--automatic-only');
const onlyAutomaticWorkspace=process.argv.includes('--automatic-workspace-only');
const onlyNative=process.argv.includes('--native-only');
const onlyModular=process.argv.includes('--modular-only');
const onlyConditions=process.argv.includes('--conditions-only');
const onlyTutorialPresentation=process.argv.includes('--tutorial-presentation-only');
const modularSuite=process.env.YGO_MODULAR_SECOND_FLOW_ONLY==='1'?'second-flow':process.env.YGO_MODULAR_SECOND_ROUTES_ONLY==='1'?'second-routes':process.env.YGO_MODULAR_SECOND_HINTS_ONLY==='1'?'second-hints':Object.entries({implicit:'YGO_MODULAR_IMPLICIT_ONLY',if:'YGO_MODULAR_IF_ONLY',mechanics:'YGO_MODULAR_MECHANICS_ONLY',rules:'YGO_MODULAR_RULES_ONLY',precision:'YGO_MODULAR_PRECISION_ONLY',preferences:'YGO_MODULAR_PREFERENCES_ONLY',routes:'YGO_MODULAR_ADDITIONAL_ONLY',cross:'YGO_MODULAR_CROSS_ONLY',planning:'YGO_MODULAR_PLANNING_ONLY',pipeline:'YGO_MODULAR_PIPELINE_ONLY',forecast:'YGO_MODULAR_FORECAST_ONLY'}).find(([,key])=>process.env[key]==='1')?.[0]||'core';
const profileSuffix=onlySecond?'-second':onlyTutorialPresentation?'-tutorial-presentation':onlyConditions?'-conditions':onlyModular?'-modular-'+modularSuite:onlyCompromise?'-compromise':onlySelection?'-selection':onlyDuel?'-duel':onlyAutomatic?'-automatic':onlyAutomaticWorkspace?'-automatic-workspace':onlyNative?'-native':'';
const runLabel=process.env.YGO_TEST_RUN||'';
assert(/^[a-z0-9-]*$/.test(runLabel),'Isolated test run label must contain only letters, digits and hyphens');
const runSuffix=profileSuffix+(runLabel?'-'+runLabel:'');
const root = path.join(workspace, '.local', `desktop-check-${label}${runSuffix}`);
const evidence = path.join(workspace, '.local', 'evidence', `electron-${label}${runSuffix}`);
const importSource=process.env.YGO_DESKTOP_TEST_SOURCE||(onlyNative||onlyTutorialPresentation||onlySecond?path.join(root,'empty-import'):path.join(workspace,'.local','YGOPro-Lite'));
if((onlyNative||onlyTutorialPresentation||onlySecond)&&!process.env.YGO_DESKTOP_TEST_SOURCE)fs.mkdirSync(importSource,{recursive:true});
fs.mkdirSync(evidence, { recursive: true });
const executable = packaged ? path.resolve(workspace, process.env.YGO_PACKAGE_DIR||require('../package.json').build.directories.output, 'win-unpacked', require('../package.json').build.win.executableName + '.exe') : require('electron');
const checks = [], errors = [];
let application, page, service, nativePid;
let compromiseSaved;
const env = { ...process.env };
env.YGO_DESKTOP_TEST = '1';
env.YGO_DESKTOP_BACKGROUND = '1';
delete env.ELECTRON_RUN_AS_NODE;
// Prove packaged startup does not resolve Python, Node or tooling from developer PATH.
if (packaged) env.PATH = path.join(process.env.SystemRoot, 'System32');
function pass(text) { checks.push(text); console.log(`PASS ${text}`); }
async function launch(first = false, testControl = true) {
  const args = [...(packaged ? [] : [workspace]), '--data-dir', root];
  if (first) args.push('--import-from', importSource);
  application = await electron.launch({ executablePath: executable, args,
    env: {...env, YGO_DESKTOP_TEST: testControl ? '1' : '0'}, timeout: 120000 });
  page = await application.firstWindow();
  // Capture the app's renderer while its window stays hidden. CDP screenshots can stall on a hidden HWND.
  page.screenshot = async ({path:target,preserveScroll=false}) => {
    await require('./theme-smoke.cjs')(page);
    if(!preserveScroll)await page.evaluate(()=>window.scrollTo(0,0));
    // Hidden compositors may suspend an entrance animation between captures.
    await page.evaluate(()=>document.getAnimations().forEach(animation=>{if(Number.isFinite(animation.effect?.getComputedTiming().endTime))animation.finish();}));
    const png = await application.evaluate(async ({BrowserWindow}) => {
      const contents=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents;
      await contents.capturePage(undefined,{stayHidden:true}); // Wake the hidden compositor before the final frame.
      await new Promise(resolve=>setTimeout(resolve,150));
      return (await contents.capturePage(undefined,{stayHidden:true})).toPNG().toString('base64');
    });
    const buffer=Buffer.from(png,'base64');fs.writeFileSync(target,buffer);return buffer;
  };
  page.on('pageerror', error => errors.push(error.message));
  await Promise.race([
    page.waitForFunction(() => document.querySelector('#resource-count')?.textContent.includes('张卡牌'), null, { timeout: 300000 }),
    page.waitForEvent('pageerror', {timeout:300000}).then(error => { throw error; }),
  ]);
  await application.evaluate(({BrowserWindow})=>{const main=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());main.webContents.setBackgroundThrottling(false);main.webContents.setZoomFactor(1);main.setContentSize(1280,900);});
  await page.waitForFunction(()=>innerWidth===1280&&innerHeight===900);
  service = JSON.parse(fs.readFileSync(path.join(root, 'runtime', '_trainer', 'service.json'), 'utf8'));
  assert.equal(await page.evaluate(() => typeof require), 'undefined');
  const brand = require('./branding.cjs');
  assert.equal(await page.title(),brand.name);
  const identity = await application.evaluate(({app,BrowserWindow})=>({name:app.getName(),title:BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).getTitle(),data:app.getPath('userData')}));
  assert.equal(identity.name,brand.name); assert.equal(identity.title,brand.name);
  assert.equal(identity.data,path.join(root,'electron'));
  if(testControl)assert.deepEqual(await application.evaluate(()=>globalThis.brandingAcceptance),{windowIconExists:true,loadingImage:true,loadingTitlebar:process.platform==='win32'});
  if(first&&!onlyDuel&&!onlyAutomatic&&!onlyAutomaticWorkspace&&!onlyTutorialPresentation&&!onlySecond)await require('./titlebar-smoke.cjs')({application,page,pass,evidence});
  assert.deepEqual(await page.locator('.primary-rail nav button>span').allTextContents(),['首页','卡组编辑','展开','决斗','模块化','全局设置','TAG 管理']);
  assert.equal(await page.locator('.app-bar #app-settings').count(),0);
  const settingsPosition=await page.locator('#app-settings').boundingBox();
  const tagsPosition=await page.locator('#module-tags').boundingBox();
  assert(tagsPosition.y-settingsPosition.y-settingsPosition.height<=12,'Settings stays directly above TAG management');
  assert.equal(await page.locator('#expansion-navigation #nav-tags, #manage-tags').count(),0);
  const tagPosition=await page.locator('#module-tags').boundingBox();
  assert(tagPosition.y>700,'TAG management stays at the bottom of the 900px primary column');
  assert.equal(await page.locator('#module-home').getAttribute('aria-current'),'page');
  assert.equal(await page.locator('#home').isVisible(),true);
  await page.locator('#navigation-toggle').click();
  assert.equal(await page.locator('#primary-navigation').isVisible(),false);
  await page.locator('#home-decks').click();
  await page.waitForFunction(()=>moduleUI.current==='decks'&&!moduleUI.switching);
  assert.equal(await page.locator('#primary-navigation').isVisible(),false);
  await page.locator('#navigation-toggle').click();
  await page.locator('#module-home').click();
  await page.waitForFunction(()=>moduleUI.current==='home'&&!moduleUI.switching);
  assert(await page.locator('.brand img').evaluate(image=>image.complete&&image.naturalWidth>0));
  await page.screenshot({path:path.join(evidence,'home.png')});
  await page.locator('#home-decks').click();
  await page.waitForFunction(()=>moduleUI.current==='decks'&&!moduleUI.switching);
  assert.equal(await page.locator('#module-decks').getAttribute('aria-current'),'page');
  await page.locator('#module-expansion').click();
  await page.waitForFunction(()=>moduleUI.current==='expansion'&&!moduleUI.switching);
  return page;
}
async function openSavedDeck(id) {
  if (await page.locator('#selection-preview-page').isVisible()) await page.locator('#selection-back').click();
  await page.locator('[data-select-deck='+JSON.stringify(id)+']').click();
  await page.waitForFunction(id=>deckSelection.selected?.id===id&&!deckSelection.loading,id);
}
async function waitHistory(status) {
  await page.waitForFunction(expected => app.history.some(h => h.id === app.reportId && h.status === expected), status, { timeout: 20000 });
}
async function nativeState(sid, kind = 'capture', point = {}) {
  const boot = await (await fetch(`${service.url}/api/bootstrap`)).json();
  const response = await fetch(`${service.url}/api/native/test`, {method:'POST',headers:{'Content-Type':'application/json','X-Trainer-Token':boot.token},body:JSON.stringify({id:sid,kind,...point})});
  const value = await response.json();
  assert(response.ok, value.error);
  fs.writeFileSync(path.join(evidence, 'native-latest.json'), JSON.stringify(value, null, 2));
  fs.writeFileSync(path.join(evidence, 'native-latest.png'), Buffer.from(await (await fetch(service.url + value.frame)).arrayBuffer()));
  return value;
}
async function nativeWait(sid, predicate) {
  for(let attempt=0;attempt<30;attempt++) {
    const state = await nativeState(sid);
    if(predicate(state)) return state;
    await new Promise(resolve=>setTimeout(resolve,150));
  }
  throw new Error('Native UI did not reach the expected state; see native-latest.png/json');
}
async function hostWait(sid, predicate) {
  let state;
  for (let attempt = 0; attempt < 100; attempt++) {
    state = await (await fetch(`${service.url}/api/native/status?id=${sid}`)).json();
    if (await predicate(state)) return state;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Native host did not reach the expected state: ${JSON.stringify(state)}`);
}
function assertComposition(host) {
  assert.equal(host.composition_compatible, true, 'Parent and sibling web surfaces must not paint over the native field');
  assert.equal(host.parent_clips_children,true);
  assert.deepEqual(host.layered_overlaps, []);
  assert.equal(host.owns_stage_hit_test, true);
}
async function close() {
  const pid = service.pid, url = service.url;
  const exited = once(application.process(), 'exit');
  // Answer only this isolated app's own close warning; never use OS keyboard or mouse input.
  await application.evaluate(({dialog}) => {dialog.showMessageBox = async (_window, options) => {
    if (!options.message.includes('是否退出')) throw new Error('Unexpected confirmation');
    return {response:1};
  };});
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(w => !w.getParentWindow()).close());
  await Promise.race([exited, new Promise((_, reject) => { const t = setTimeout(() => reject(new Error('Desktop did not exit')), 25000); t.unref(); })]);
  assert.throws(() => process.kill(pid, 0));
  if (nativePid) assert.throws(() => process.kill(nativePid, 0));
  await assert.rejects(fetch(url, { signal: AbortSignal.timeout(1500) }));
  application = null;
}

async function verifyBranchRestart() {
  nativePid=null;
  await launch(false,false);
  await page.evaluate(id=>showPlan(id),compromiseSaved.id);
  assert.equal(await page.locator('#saved-branch [data-branch-route="main"]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('#nav-compromise').isDisabled(),true);
  await page.locator(`#saved-branch [data-branch-route="${compromiseSaved.branch}"]`).click();
  assert((await page.locator('#saved-branch-panel').innerText()).includes('效果被无效'));
  const reopened=await page.evaluate(id=>api('/api/plan/'+id),compromiseSaved.id);
  assert.equal(reopened.branches.length,2);
  assert(reopened.branches.every(b=>b.report.final_state&&b.source.checkpoint));
  await close();pass('Fresh desktop/backend restart with test controls disabled preserves both branches, their premises and end boards, and opens on the mainline');
}
async function designExpansion(name, ai = false) {
  await page.locator('#selection-next').click();
  await page.waitForFunction(() => !!flow.design && !document.querySelector('#design').hidden);
  assert.equal(await page.locator('[data-slot="0"]').isDisabled(), true);
  await page.locator('#plan-name').fill(name);
  await page.locator('#plan-notes').fill('隔离验收备注');
  for (const [slot,code] of [[0,55144522],[1,1184620]]) {
    await page.locator(`[data-slot="${slot}"]`).click();
    await page.locator(`[data-choice="${code}"]`).click();
  }
  await page.locator('#opponent-ai').setChecked(ai);
  await page.screenshot({path:path.join(evidence, ai?'design-ai.png':'design.png')});
  await page.locator('#begin-expansion').click();
  await page.waitForFunction(() => !!app.active && !flow.busy);
}
async function activatePot(sid) {
  let state=await nativeWait(sid,s=>s.prompt===11&&s.targets.some(t=>t.location===2&&t.code===55144522));
  const pot=state.targets.find(t=>t.location===2&&t.code===55144522);
  await nativeState(sid,'click',{x:pot.x,y:pot.y});
  state=await nativeWait(sid,s=>s.buttons.some(b=>b.text==='发动'));
  const activate=state.buttons.find(b=>b.text==='发动');
  await nativeState(sid,'click',{x:activate.x,y:activate.y});
  state=await nativeWait(sid,s=>s.prompt===18);
  const zone=state.targets.find(t=>t.location===8&&t.sequence===0);
  await nativeState(sid,'click',{x:zone.x,y:zone.y});
  await nativeWait(sid,s=>s.prompt===11);
}

(async () => {
  await launch(true);
  if(onlySecond){
    await require('./second-duel-smoke.cjs')({page,application,root,evidence,pass});
    await require('./second-hints-smoke.cjs')({page,application,root,evidence,pass});
    await close();assert.deepEqual(errors,[]);fs.writeFileSync(path.join(evidence,'second-result.json'),JSON.stringify({checks,errors,globalInput:false},null,2));return;
  }
  if(onlyTutorialPresentation){
    await require('./tutorial-presentation-smoke.cjs')({page,application,evidence,pass});
    await close();assert.deepEqual(errors,[]);fs.writeFileSync(path.join(evidence,'result.json'),JSON.stringify({checks,errors,globalInput:false},null,2));return;
  }
  if(onlyConditions){
    await require('./condition-cards-smoke.cjs')({page,nativeWait,hostWait,waitHistory,pass,evidence});
    await close();assert.deepEqual(errors,[]);fs.writeFileSync(path.join(evidence,'conditions-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--alias-scripts-only')){
    await require('./alias-scripts-smoke.cjs')({page,nativeWait,nativeState,hostWait,waitHistory,pass,evidence});
    await close();assert.deepEqual(errors,[]);return;
  }
  if(process.argv.includes('--condition-display-only')){
    await require('./condition-origin-smoke.cjs')({page,evidence,pass});
    await close();assert.deepEqual(errors,[]);fs.writeFileSync(path.join(evidence,'condition-display-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--smart-only')){
    await require('./platform-branding-smoke.cjs')({page,application,evidence,pass});
    await require('./smart-recognition-smoke.cjs')({page,application,root,evidence,pass});
    await close();assert.deepEqual(errors,[]);fs.writeFileSync(path.join(evidence,'smart-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(onlyAutomaticWorkspace){
    await require('./automatic-workspace-smoke.cjs')({page,application,root,evidence,pass});
    await close();assert.deepEqual(errors,[]);fs.writeFileSync(path.join(evidence,'automatic-workspace-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(onlyAutomatic) {
    await page.locator('#module-duel').click();await page.waitForFunction(()=>moduleUI.current==='duel'&&!moduleUI.switching);
    await page.locator('[data-duel-action="bo1"]').click();
    await require('./automatic-selection-smoke.cjs')({page,application,evidence,pass});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'automatic-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(onlyModular) {
    await require('./modular-smoke.cjs')({page,application,root,evidence,pass});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'modular-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(onlyDuel) {
    await require('./duel-smoke.cjs')({page,application,root,evidence,pass});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'duel-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--scrollbars-only')) {
    await require('./scrollbars-smoke.cjs')({page,application,evidence,pass});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'scrollbars-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--home-only')) {
    await page.locator('#module-home').click();
    await page.waitForFunction(()=>moduleUI.current==='home'&&!moduleUI.switching);
    await page.screenshot({path:path.join(evidence,'home.png')});
    await page.locator('#navigation-toggle').click();
    await page.screenshot({path:path.join(evidence,'home-collapsed.png')});
    await close();assert.deepEqual(errors,[]);
    console.log('PASS Final packaged/development home, brand and collapsible navigation');return;
  }
  if(onlySelection) {
    await require('./selection-preview-smoke.cjs')({page,application,evidence,pass});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'selection-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--route-display-only')) {
    const plans=await page.evaluate(()=>api('/api/plans'));
    assert(plans.length,'Run the full smoke once to create an isolated saved plan');
    const plan=await page.evaluate(id=>api('/api/plan/'+id),plans[0].id);
    await require('./route-display-smoke.cjs')({page,plan,pass,evidence});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'route-display-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(onlyCompromise) {
    compromiseSaved=await require('./compromise-smoke.cjs')({application,page,nativeWait,nativeState,hostWait,pass,evidence});
    const plan=await page.evaluate(id=>api('/api/plan/'+id),compromiseSaved.id);
    await require('./route-display-smoke.cjs')({page,plan,pass,evidence});
    await close();await verifyBranchRestart();console.log(JSON.stringify({label,checks,errors}));process.exit(0);
  }
  if(process.argv.includes('--inspection-only')) {
    const plans=await page.evaluate(()=>api('/api/plans'));let plan;
    for(const p of plans){const r=await page.evaluate(id=>api(`/api/plan/${id}`),p.id);if(r.review?.nodes.some(n=>n.state?.cards.some(c=>c.overlay_target!=null))){plan=r;break;}}
    assert(plan,'Run the full smoke once to create an isolated saved material route');
    await page.evaluate(id=>showPlan(id),plan.id);
    await require('./plan-tutorial-smoke.cjs')({page,application,plan,pass,evidence});
    await require('./review-details-smoke.cjs')({page,plan,pass,evidence});
    await require('./tag-manager-smoke.cjs')({page,plan,pass,evidence});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'inspection-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--library-only')) {
    const plans=await page.evaluate(()=>api('/api/plans'));
    const selected=plans.find(p=>!p.imported);assert(selected,'Run the desktop smoke once to create an isolated saved plan');
    const plan=await page.evaluate(id=>api(`/api/plan/${id}`),selected.id);
    await require('./plan-library-smoke.cjs')({page,application,plan,pass,evidence});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'library-only-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--tutorial-only')) {
    const plans=await page.evaluate(()=>api('/api/plans'));
    assert(plans.length,'Run the full desktop smoke once to create an isolated saved plan');
    await page.evaluate(id=>showPlan(id),plans[0].id);
    const plan=await page.evaluate(id=>api(`/api/plan/${id}`),plans[0].id);
    await require('./plan-tutorial-smoke.cjs')({page,application,plan,pass,evidence});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'tutorial-only-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--materials-only')) {
    await require('./review-materials-smoke.cjs')({page,nativeWait,nativeState,hostWait,waitHistory,pass,evidence});
    await close();assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'materials-only-result.json'),JSON.stringify({checks,errors},null,2));return;
  }
  if(process.argv.includes('--timeline-only')) {
    await require('./timeline-effects-smoke.cjs')({page,nativeWait,nativeState,hostWait,waitHistory,pass,evidence});
    await close();
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'timeline-only-result.json'),JSON.stringify({checks,errors},null,2));
    return;
  }
  const bootstrap = await (await fetch(`${service.url}/api/bootstrap`)).json();
  assert.equal(bootstrap.cards, 14981);
  pass('Desktop window, isolated renderer, embedded Python and local catalog');
  await page.locator('#module-decks').click();
  await page.waitForFunction(()=>moduleUI.current==='decks'&&!moduleUI.switching);
  let deck,deckId;
  if(onlyNative) {
    ({deck,deckId}=await page.evaluate(async()=>{
      const deck={main:Array.from({length:40},(_,i)=>i%2?1184620:55144522),extra:[23995346],side:[55144522]};
      const saved=await api('/api/decks',{name:'原生场地验收 '+crypto.randomUUID(),deck});
      await api('/api/card-favorites',{id:55144522,favorite:true});
      await switchModule('decks');await openDeck(saved.id);await switchModule('expansion');await deckList();
      return {deck,deckId:saved.id};
    }));
    await openSavedDeck(deckId);
  } else {
    ({deck,deckId}=await require('./deck-management-smoke.cjs')({page,application,evidence,label,pass}));
    await require('./deck-tags-smoke.cjs')({page,application,deckId,deck,evidence,pass});
    await require('./modules-smoke.cjs')({page,application,deckId,deck,pass,evidence});
    await require('./duel-smoke.cjs')({page,application,root,evidence,pass});
    await require('./platform-branding-smoke.cjs')({page,application,evidence,pass});
    await require('./smart-recognition-smoke.cjs')({page,application,root,evidence,pass});
  }
  await page.evaluate(()=>switchModule('expansion'));
  if (process.argv.includes('--decks-only')) {
    const savedTags = (await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),deckId)).tag_selection;
    await close(); await launch(false,false);
    const reopened = await page.evaluate(id=>api('/api/deck?id='+encodeURIComponent(id)),deckId);
    assert.deepEqual(reopened.deck,deck);
    assert.deepEqual(reopened.tag_selection,savedTags);
    assert((await page.evaluate(()=>api('/api/card-favorites'))).cards.includes(55144522));
    await close();assert.deepEqual(errors,[]);
    pass('Decks, TAG selections and favorites survive a fresh desktop/backend restart');
    fs.writeFileSync(path.join(evidence,'deck-result.json'),JSON.stringify({label,globalInput:false,clipboardWriter:'isolated',checks,errors},null,2));
    return;
  }
  await designExpansion('起手验收方案');
  let sessionId = await page.evaluate(() => app.active.id);
  let sessionPath = path.join(root, 'runtime', '_trainer', 'sessions', sessionId);
  await page.waitForTimeout(2500);
  let metadata = JSON.parse(fs.readFileSync(path.join(sessionPath, 'session.json'), 'utf8'));
  nativePid = metadata.pid;
  assert.equal(metadata.status, 'running');
  assert.deepEqual(metadata.deck, deck);
  const firstId=sessionId, firstOpening=metadata.expansion.actual_opening, firstConfig=metadata.expansion;
  await nativeWait(sessionId,s=>s.prompt===11);
  let firstReport=await (await fetch(`${service.url}/api/report/${sessionId}`)).json();
  assert.deepEqual(firstReport.initial_hand.map(c=>c.code),firstOpening);
  assert.equal(firstReport.final_state.cards.filter(c=>c.controller===0&&c.location===1).length,35);
  const firstInitial=firstReport.final_state;
  await activatePot(sessionId);
  firstReport=await (await fetch(`${service.url}/api/report/${sessionId}`)).json();
  assert.equal(firstReport.actions.length,1);
  await page.locator('#restart-expansion').click();
  await page.locator('#flow-confirm').click();
  await page.waitForFunction(id=>!!app.active&&app.active.id!==id&&!flow.busy,firstId,{timeout:30000});
  sessionId=await page.evaluate(()=>app.active.id);
  sessionPath=path.join(root,'runtime','_trainer','sessions',sessionId);
  metadata=JSON.parse(fs.readFileSync(path.join(sessionPath,'session.json'),'utf8'));
  nativePid=metadata.pid;
  assert.deepEqual(metadata.expansion,firstConfig);
  await hostWait(sessionId,s=>s.frame_ready);
  await nativeWait(sessionId,s=>s.prompt===11);
  const retryReport=await (await fetch(`${service.url}/api/report/${sessionId}`)).json();
  assert.deepEqual(retryReport.initial_hand.map(c=>c.code),firstOpening);
  assert.deepEqual(retryReport.final_state,firstInitial);
  assert.equal(retryReport.actions.length,0);
  assert.equal(JSON.parse(fs.readFileSync(path.join(root,'runtime','_trainer','sessions',firstId,'session.json'))).plan_stage,'discarded');
  assert(!(await (await fetch(`${service.url}/api/history`)).json()).some(r=>r.id===firstId));
  pass('Opening constraints reach the real engine; restart restores exact initial state with a fresh journal');
  console.log(JSON.stringify({ phase: 'embedded-training', label, sessionId, nativePid, service, sessionPath }));
  const host = await hostWait(sessionId, s => s.frame_ready && s.visible && s.owns_stage_hit_test && s.composition_compatible);
  assert.equal(host.ready, true); assert.equal(host.child_style, true); assert.equal(host.caption, false);
  assert.equal(host.frame_ready,true);
  await page.waitForFunction(()=>document.querySelector('#native-loading').hidden);
  assertComposition(host);
  const sessionSnapshot = await page.evaluate(id=>api('/api/design/'+id),sessionId);
  await page.locator('#module-home').click();
  await page.waitForFunction(()=>moduleUI.current==='home'&&!moduleUI.switching);
  await hostWait(sessionId,s=>!s.visible);
  assert.equal(await page.evaluate(()=>app.active.id),sessionId);
  await page.locator('#module-tags').click();
  await page.waitForFunction(()=>moduleUI.current==='tags'&&!moduleUI.switching);
  assert.equal(await page.locator('#expansion-navigation').isVisible(),false);
  assert.equal(await page.locator('#tags').isVisible(),true);
  assert.equal(await page.evaluate(()=>app.active.id),sessionId);
  await page.locator('#module-decks').click();
  await page.waitForFunction(()=>moduleUI.current==='decks'&&!moduleUI.switching);
  assert.equal(await page.locator('#active-training').isVisible(),false);
  // Save the shared source through the independent module while the engine runs.
  await page.evaluate(async id=>{await openDeck(id);await addCard(55144522,'side');await saveDeck();},deckId);
  assert.deepEqual(await page.evaluate(id=>api('/api/design/'+id),sessionId),sessionSnapshot);
  await page.evaluate(async()=>{await undoDeck();await saveDeck();});
  await page.locator('#module-expansion').click();
  await page.waitForFunction(()=>moduleUI.current==='expansion'&&!moduleUI.switching);
  assert.equal(await page.evaluate(()=>app.active.id),sessionId);
  assert.equal(await page.evaluate(()=>app.view),'training');
  assertComposition(await hostWait(sessionId,s=>s.visible&&s.owns_stage_hit_test&&s.composition_compatible));
  pass('Live expansion survives primary module switching; editing shared source leaves its frozen design unchanged and native field resumes');
  const expandedStage=await page.locator('#native-stage').boundingBox();
  await page.locator('#navigation-toggle').click();
  const collapsedHost=await hostWait(sessionId,s=>s.visible&&s.bounds.width>expandedStage.width&&s.owns_stage_hit_test&&s.composition_compatible);
  assertComposition(collapsedHost);
  assert.equal(await page.evaluate(()=>app.active.id),sessionId);
  await page.locator('#navigation-toggle').click();
  assertComposition(await hostWait(sessionId,s=>s.visible&&Math.abs(s.bounds.width-expandedStage.width)<3&&s.owns_stage_hit_test));
  pass('Collapsing and reopening the left navigation resizes the live native stage and preserves its session');
  // Wait for the collapse/reopen requests and ResizeObserver to settle before
  // measuring idle polling. A continuously changing layout never passes this gate.
  let stableHost,stableCycles=0;
  for(let i=0;i<20&&stableCycles<3;i++) {
    await page.evaluate(()=>syncNativeHost());await new Promise(resolve=>setTimeout(resolve,250));
    const sample=await hostWait(sessionId,s=>s.visible&&s.owns_stage_hit_test&&s.timeline_accessible);
    stableCycles=stableHost&&JSON.stringify(sample.layout_updates)===JSON.stringify(stableHost.layout_updates)&&JSON.stringify(sample.bounds)===JSON.stringify(stableHost.bounds)?stableCycles+1:0;
    stableHost=sample;
  }
  assert.equal(stableCycles,3,'Native placement must settle after navigation resizing');
  const stability=[];
  for(let i=0;i<12;i++) {
    await page.evaluate(async()=>{await refreshHistory();await refreshTimeline();await syncNativeHost();});
    await new Promise(resolve=>setTimeout(resolve,250));
    const sample=await hostWait(sessionId,s=>s.visible&&s.owns_stage_hit_test);
    stability.push({bounds:sample.bounds,updates:sample.layout_updates});
    fs.writeFileSync(path.join(evidence,'native-stability.json'),JSON.stringify(stability,null,2));
    assert.deepEqual(sample.bounds,stableHost.bounds,'Idle polling must keep the native field bounds stable');
    assert.equal(sample.layout_updates.region,stableHost.layout_updates.region,'Idle polling must not reset the clipping region');
    assert.equal(sample.layout_updates.visibility,stableHost.layout_updates.visibility,'Idle polling must not hide/show the field');
  }
  pass('Native field stays visible across 12 polling cycles without repeated clipping or hide/show');
  await require('./native-paint-smoke.cjs')({page,application,sid:sessionId,nativeState,hostWait,evidence,pass});
  fs.writeFileSync(path.join(evidence, 'native-host.json'), JSON.stringify(host, null, 2));
  await page.screenshot({path: path.join(evidence, 'training-shell.png')});
  const stage = await page.locator('#native-stage').boundingBox();
  assert(Math.abs(stage.width-host.bounds.width)<3 && Math.abs(stage.height-host.bounds.height)<3);
  assert(Math.abs(stage.x-host.bounds.x)<3 && Math.abs(stage.y-host.bounds.y)<3);
  const invalid = await fetch(`${service.url}/api/desktop/layout`, {method:'POST',headers:{'Content-Type':'application/json','X-Trainer-Token':bootstrap.token},body:JSON.stringify({hwnd:host.hwnd,visible:false})});
  assert.equal(invalid.status,400, 'The native child cannot be supplied as a replacement host');
  let state = await nativeWait(sessionId, s=>s.prompt===11 && s.targets.some(t=>t.location===2 && t.code===55144522));
  assert(!state.buttons.some(b=>['忽略时点','显示时点','可用时点','洗切手卡','结束训练'].includes(b.text)));
  const startupRows=fs.readFileSync(path.join(sessionPath,'native.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
  const idle=startupRows.find(r=>r.kind==='batch'&&r.raw.startsWith('0b'));
  assert(idle,'Initial actionable prompt must be recorded');
  console.log(JSON.stringify({startupMs:idle.time_ms-metadata.started_ms,firstFrameMs:host.frame_ms-metadata.started_ms}));
  const pot = state.targets.find(t=>t.location===2 && t.code===55144522);
  await nativeState(sessionId,'click',{x:pot.x,y:pot.y});
  state=await nativeWait(sessionId,s=>s.buttons.some(b=>b.text==='发动'));
  let button=state.buttons.find(b=>b.text==='发动');
  await nativeState(sessionId,'click',{x:button.x,y:button.y});
  state=await nativeWait(sessionId,s=>s.prompt===18);
  let zone=state.targets.find(t=>t.location===8 && t.sequence===0);
  await nativeState(sessionId,'click',{x:zone.x,y:zone.y});
  state=await nativeWait(sessionId,s=>s.prompt===11 && s.targets.some(t=>t.location===2 && t.code===1184620));
  const monster=state.targets.find(t=>t.location===2 && t.code===1184620);
  await nativeState(sessionId,'click',{x:monster.x,y:monster.y});
  state=await nativeWait(sessionId,s=>s.buttons.some(b=>b.text==='召唤'));
  button=state.buttons.find(b=>b.text==='召唤');
  await nativeState(sessionId,'click',{x:button.x,y:button.y});
  state=await nativeWait(sessionId,s=>s.prompt===18);
  zone=state.targets.find(t=>t.location===4 && t.sequence===0);
  await nativeState(sessionId,'click',{x:zone.x,y:zone.y});
  state=await nativeWait(sessionId,s=>s.prompt===11 && s.targets.some(t=>t.location===4 && t.code===1184620));
  await require('./timeline-smoke.cjs')({page,sid:sessionId,sessionPath,nativeWait,nativeState,pass,evidence});
  fs.copyFileSync(path.join(evidence,'native-latest.png'),path.join(evidence,'embedded-board.png'));
  const originalViewport = await page.evaluate(()=>({width:innerWidth,height:innerHeight}));
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1100,800));
  const resizedHost = await hostWait(sessionId, async s => {
    const r = await page.locator('#native-stage').boundingBox();
    return await page.evaluate(() => innerWidth === 1100) && s.ready && Math.abs(s.bounds.width-r.width)<3 && Math.abs(s.bounds.height-r.height)<3;
  });
  assertComposition(resizedHost);
  const resized = await nativeWait(sessionId,s=>s.width<state.width);
  assert(resized.width < state.width);
  fs.copyFileSync(path.join(evidence,'native-latest.png'),path.join(evidence,'embedded-resized.png'));
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents.setZoomFactor(1.25));
  const zoomedHost = await hostWait(sessionId, async s => {
    const r = await page.locator('#native-stage').boundingBox();
    return s.ready && Math.abs(s.bounds.width-r.width*1.25)<3 && Math.abs(s.bounds.y-r.y*1.25)<3;
  });
  assertComposition(zoomedHost);
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents.setZoomFactor(1));
  await application.evaluate(({BrowserWindow},size)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(size.width,size.height),originalViewport);
  await page.locator('#nav-decks').click();
  await hostWait(sessionId, s => s.visible === false);
  await page.locator('#nav-training').click();
  assertComposition(await hostWait(sessionId, s => s.visible && s.composition_compatible && s.owns_stage_hit_test));
  pass('HWND composition has no layered surface covering the native field, including after resize/zoom and page switching');
  pass('Native child parent/bounds, resize/125% zoom, internal effect/summon, frame capture and page switching without global input');
  state = await nativeWait(sessionId, s => s.prompt === 11 && s.buttons.some(b => b.text === 'ＥＰ'));
  button = state.buttons.find(b => b.text === 'ＥＰ');
  await nativeState(sessionId, 'click', {x: button.x, y: button.y});
  state = await nativeWait(sessionId, s => s.prompt === 11 && s.buttons.some(b => b.text === 'ＢＰ'));
  button = state.buttons.find(b => b.text === 'ＢＰ');
  await nativeState(sessionId, 'click', {x: button.x, y: button.y});
  state = await nativeWait(sessionId, s => s.prompt === 10);
  const attacker = state.targets.find(t => t.location === 4 && t.code === 1184620);
  assert(attacker, 'The normally summoned monster must still be on the field');
  await nativeState(sessionId, 'click', {x: attacker.x, y: attacker.y});
  state = await nativeWait(sessionId, s => s.buttons.some(b => b.text === '攻击'));
  button = state.buttons.find(b => b.text === '攻击');
  await nativeState(sessionId, 'click', {x: button.x, y: button.y});
  let battleReport;
  for (let attempt = 0; attempt < 200; attempt++) {
    battleReport = await (await fetch(`${service.url}/api/report/${sessionId}`)).json();
    if (battleReport.events.some(e => e.message === 114)) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(battleReport.events.some(e => e.message === 114), 'Wait for the native damage step to finish');
  assert.equal(battleReport.actions.length, 2, 'A normal attack must not add expansion steps');
  for (const msg of [110, 113, 111, 91, 114]) assert(battleReport.events.some(e => e.message === msg), `Missing battle message ${msg}`);
  const battleDamage = battleReport.events.find(e => e.message === 91);
  assert.equal(battleDamage.player, 1);
  assert(battleDamage.amount > 0);
  assert.equal(battleReport.final_state.lp[1], 8000 - battleDamage.amount);
  pass('Real direct attack keeps battle evidence and final LP without adding expansion steps');
  await page.locator('#finish-training').click();
  await waitHistory('completed');
  await page.waitForFunction(id => app.reportId === id && !document.querySelector('#history').hidden, sessionId);
  let report = await (await fetch(`${service.url}/api/report/${sessionId}`)).json();
  assert.equal(report.status, 'completed');
  const journal = fs.readFileSync(path.join(sessionPath, 'native.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(journal[0].test_control, true);
  assert(journal.some(r => r.kind === 'end' && r.reason === 'manual'));
  assert.equal(report.statistics['效果抽卡'],2);
  assert.equal(report.statistics['通常召唤成功'],1);
  assert.equal(report.actions.length,2);
  assert.equal(await page.locator('#review-steps > li').count(), report.review.nodes.length);
  await page.locator('#review-log-toggle').click();
  await page.locator('[data-log-mode="detailed"]').click();
  assert.equal(await page.locator('#review-log .log-action').count(), 2);
  assert.equal(await page.locator('#review-log .log-action h4').filter({hasText: /攻击宣言|伤害步骤|战斗结果|受到.*伤害/}).count(), 0);
  await page.screenshot({ path: path.join(evidence, 'report.png') });
  if (report.actions.some(a => a.kind === 'effect')) {
    const effectDescription=page.locator('#review-log .log-effect-description p').first();
    assert(await effectDescription.isVisible());assert((await effectDescription.innerText()).trim().length>0);
    assert((await page.locator('#review-log .log-role').first().innerText()).includes('处理结果'));
  }
  await page.locator('.review-evidence > summary').click();
  await page.locator('#all-events').check();
  assert(await page.locator('#all-events').isChecked());
  await page.waitForFunction(() => [...document.querySelectorAll('#review-raw-events summary')].some(e => e.textContent === '战斗结果'));
  assert.equal(await page.locator('#review-raw-events summary').filter({hasText: '战斗结果'}).count(), 1);
  await page.locator('#all-events').uncheck();
  await page.waitForFunction(() => document.querySelectorAll('#review-log .log-action').length === 2);
  const popupPromise = page.waitForEvent('popup');
  await page.locator('a[href^="/api/raw/"]').click();
  const rawWindow = await popupPromise;
  await rawWindow.waitForLoadState();
  assert((await rawWindow.locator('body').innerText()).includes(sessionId));
  assert.equal(await rawWindow.evaluate(() => typeof require), 'undefined');
  await rawWindow.close();
  pass('Raw-event toggle and JSONL open in an isolated Electron child window');
  pass('Real embedded engine effect/summon, journal and completed report');
  await page.locator('#review-log-close').click();
  await require('./review-smoke.cjs')({page,report,pass,evidence});
  await page.locator('#draft-name').fill('正式展开方案');
  await page.locator('#draft-notes').fill('正式方案的冻结备注');
  await page.route('**/api/plans/save',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'隔离测试：模拟磁盘失败'})}),{times:1});
  await page.locator('#save-plan').click();
  await page.locator('#confirm-save-plan').click();
  await page.waitForFunction(()=>document.querySelector('#confirmation-message').textContent.includes('模拟磁盘失败')&&!flow.busy);
  assert.equal(await page.locator('#draft-name').inputValue(),'正式展开方案');
  await page.locator('#confirm-save-plan').click();
  await page.waitForFunction(id=>flow.selectedPlan===id&&!document.querySelector('#plans').hidden,sessionId);
  report=await (await fetch(`${service.url}/api/plan/${sessionId}`)).json();
  const duplicate=await page.evaluate(async id=>api('/api/plans/save',{id,name:'重复请求',notes:''}),sessionId);
  assert.deepEqual(duplicate,report);
  assert.equal((await (await fetch(`${service.url}/api/plans`)).json()).filter(p=>p.id===sessionId).length,1);
  await page.screenshot({path:path.join(evidence,'saved-plan.png')});
  await require('./plan-tutorial-smoke.cjs')({page,application,plan:report,pass,evidence});
  await require('./plan-library-smoke.cjs')({page,application,plan:report,pass,evidence});
  await require('./tag-manager-smoke.cjs')({page,plan:report,pass,evidence});
  await require('./route-display-smoke.cjs')({page,plan:report,pass,evidence});
  pass('Draft text adjustment, visible save failure with retained content, retry and idempotent formal save');
  await close();
  pass('Window close releases service, native process and listening port');
  await launch(false, false);
  await openSavedDeck(deckId);
  await page.waitForFunction(id => deckSelection.selected?.id === id && !deckSelection.loading, deckId);
  assert.deepEqual(await page.evaluate(() => deckSelection.selected.deck), deck);
  await page.locator('#nav-plans').click();
  await page.locator('#history-archive > summary').click();
  await page.locator(`[data-report="${sessionId}"]`).click();
  await page.waitForFunction(id => app.reportId === id, sessionId);
  assert.deepEqual(await (await fetch(`${service.url}/api/report/${sessionId}`)).json(), report);
  assert((await page.evaluate(()=>api('/api/card-favorites'))).cards.includes(55144522));
  pass('Restart retains complete deck, favorites and exact report');
  await page.locator('#nav-decks').click();
  await designExpansion('正常随机模式');
  const interrupted = await page.evaluate(() => app.active.id);
  await page.waitForTimeout(2000);
  const interruptedPath = path.join(root, 'runtime', '_trainer', 'sessions', interrupted);
  nativePid = JSON.parse(fs.readFileSync(path.join(interruptedPath, 'session.json'))).pid;
  assertComposition(await hostWait(interrupted, s => s.frame_ready && s.visible && s.composition_compatible && s.owns_stage_hit_test));
  const normalJournal = fs.readFileSync(path.join(interruptedPath, 'native.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(normalJournal[0].test_control, false);
  const normalBoot = await (await fetch(`${service.url}/api/bootstrap`)).json();
  const disabledControl = await fetch(`${service.url}/api/native/test`, {method:'POST',
    headers:{'Content-Type':'application/json','X-Trainer-Token':normalBoot.token},
    body:JSON.stringify({id:interrupted,kind:'capture'})});
  assert.equal(disabledControl.status, 400);
  assert.match((await disabledControl.json()).error, /未启用内部验收接口/);
  pass('Normal startup uses compatible composition with random training and refuses internal test input/capture');
  await close();
  const stopped = JSON.parse(fs.readFileSync(path.join(interruptedPath, 'session.json')));
  assert.equal(stopped.status, 'interrupted');
  assert.equal(stopped.end_reason, 'client_closed');
  assert(fs.existsSync(path.join(interruptedPath, 'report.json')));
  pass('Closing the app during native training flushes an interrupted report and cleans up');
  if(onlyNative) {
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(evidence,'result.json'),JSON.stringify({label,embedded:true,globalInput:false,checks,errors,root,sessionId,interrupted},null,2));
    return;
  }
  await launch();
  await openSavedDeck(deckId);
  await page.waitForFunction(id=>deckSelection.selected?.id===id&&!deckSelection.loading,deckId);
  await designExpansion('AI 干扰验收',true);
  let aiId=await page.evaluate(()=>app.active.id);
  await hostWait(aiId,s=>s.frame_ready);
  await nativeWait(aiId,s=>s.prompt===11);
  const aiInitial=await (await fetch(`${service.url}/api/report/${aiId}`)).json();
  assert.equal(aiInitial.final_state.cards.filter(c=>c.controller===1&&c.location===2).length,5);
  assert.equal(aiInitial.final_state.cards.filter(c=>c.controller===1&&c.location===2&&c.code===14558127).length,1);
  await activatePot(aiId);
  const aiReport=await (await fetch(`${service.url}/api/report/${aiId}`)).json();
  assert(aiReport.events.some(e=>e.message===70&&e.cards.some(c=>c.code===14558127)), 'The opponent must actually activate Ash Blossom');
  assert.equal(aiReport.statistics['效果抽卡'],0,'Ash Blossom must resolve and negate the Pot draw');
  assert(aiReport.final_state.cards.some(c=>c.controller===1&&c.location===16&&c.code===14558127));
  await page.locator('#restart-expansion').click();await page.locator('#flow-confirm').click();
  await page.waitForFunction(id=>!!app.active&&app.active.id!==id&&!flow.busy,aiId,{timeout:30000});
  aiId=await page.evaluate(()=>app.active.id);await hostWait(aiId,s=>s.frame_ready);await nativeWait(aiId,s=>s.prompt===11);
  const aiRetry=await (await fetch(`${service.url}/api/report/${aiId}`)).json();
  assert.deepEqual(aiRetry.final_state,aiInitial.final_state);
  assert.equal(aiRetry.actions.length,0);
  await activatePot(aiId);
  const repeatedAI=await (await fetch(`${service.url}/api/report/${aiId}`)).json();
  assert.equal(repeatedAI.statistics['效果抽卡'],0);
  const aiTimeline=await page.evaluate(id=>api(`/api/timeline/${id}`),aiId);
  assert(aiTimeline.nodes.some(n=>n.steps.filter(s=>s.kind==='effect').length===2),'Both links must share the completed-chain restore boundary, alongside any retained rule evidence');
  await page.evaluate(()=>refreshTimeline());
  await page.locator(`[data-rewind="${aiTimeline.nodes[0].id}"]`).click();
  await page.waitForFunction(()=>!rewindState.busy,null,{timeout:30000});
  assert.deepEqual((await (await fetch(`${service.url}/api/report/${aiId}`)).json()).final_state,aiInitial.final_state);
  await activatePot(aiId);
  assert.deepEqual((await (await fetch(`${service.url}/api/report/${aiId}`)).json()).final_state,repeatedAI.final_state);
  pass('Multi-link Ash Blossom chain rewinds both sides and replays identically; chain links share one legal node');
  let aiState=await nativeWait(aiId,s=>s.prompt===11&&s.buttons.some(b=>b.text==='ＥＰ'));
  const endPhase=aiState.buttons.find(b=>b.text==='ＥＰ');
  await nativeState(aiId,'click',{x:endPhase.x,y:endPhase.y});
  await nativeWait(aiId,s=>s.prompt===11&&s.buttons.some(b=>b.text==='ＢＰ'));
  const afterAITurn=await (await fetch(`${service.url}/api/report/${aiId}`)).json();
  assert(afterAITurn.final_state.cards.some(c=>c.controller===1&&c.location===4&&c.code===1184620),'Opponent must actually take its normal summon turn');
  assert(afterAITurn.events.some(e=>e.actor==='opponent_ai'));
  fs.copyFileSync(path.join(evidence,'native-latest.png'),path.join(evidence,'opponent-ai.png'));
  await page.locator('#finish-training').click();await waitHistory('completed');
  await page.waitForFunction(()=>!!flow.draft&&!document.querySelector('#draft-editor').hidden);
  await page.locator('#save-plan').click();
  await page.locator('#confirm-save-plan').click();
  await page.waitForFunction(id=>flow.selectedPlan===id&&!flow.busy,aiId);
  await page.locator('#delete-plan').click();await page.locator('#flow-cancel').click();
  assert((await (await fetch(`${service.url}/api/plans`)).json()).some(p=>p.id===aiId));
  await page.locator('#delete-plan').click();
  assert((await page.locator('#flow-message').innerText()).includes('AI 干扰验收'));
  await page.locator('#flow-confirm').click();
  await page.waitForFunction(()=>flow.selectedPlan===null);
  assert(!(await (await fetch(`${service.url}/api/plans`)).json()).some(p=>p.id===aiId));
  assert((await (await fetch(`${service.url}/api/plans`)).json()).some(p=>p.id===sessionId));
  assert.deepEqual(await (await fetch(`${service.url}/api/plan/${sessionId}`)).json(),report);
  assert((await (await fetch(`${service.url}/api/decks`)).json()).some(d=>d.id===deckId));
  pass('Real opponent AI activates and resolves Ash Blossom; retry restores both players; named deletion preserves other plans and source');
  await page.locator('#nav-decks').click();
  const banDeck=await page.evaluate(async()=>api('/api/decks',{name:`起手禁用-${Date.now()}`,deck:{main:[...Array(5).fill(55144522),...Array(35).fill(1184620)],extra:[],side:[]}}));
  await page.evaluate(()=>deckList());await openSavedDeck(banDeck.id);
  await page.waitForFunction(id=>deckSelection.selected?.id===id&&!deckSelection.loading,banDeck.id);
  await page.locator('#selection-next').click();await page.waitForFunction(()=>!!flow.design);
  await page.locator('#plan-name').fill('禁用卡后续仍可抽取');
  await page.locator('[data-slot="0"]').click();await page.locator('#choose-banned').click();await page.locator('[data-choice="1184620"]').click();
  assert.deepEqual(await page.evaluate(()=>flow.design.conditions.slots),[null,null,null,null,null]);
  assert.equal(await page.locator('[data-unban="1184620"]').count(),1);
  await page.locator('#begin-expansion').click();await page.waitForFunction(()=>!!app.active&&!flow.busy);
  const banId=await page.evaluate(()=>app.active.id);await hostWait(banId,s=>s.frame_ready);await nativeWait(banId,s=>s.prompt===11);
  const banInitial=await (await fetch(`${service.url}/api/report/${banId}`)).json();
  assert.deepEqual(banInitial.initial_hand.map(c=>c.code),Array(5).fill(55144522));
  assert.equal(banInitial.final_state.cards.filter(c=>c.controller===0&&c.location===1&&c.code===1184620).length,35);
  await activatePot(banId);
  const banAfter=await (await fetch(`${service.url}/api/report/${banId}`)).json();
  assert.equal(banAfter.final_state.cards.filter(c=>c.controller===0&&c.location===2&&c.code===1184620).length,2);
  assert.equal(banAfter.statistics['效果抽卡'],2);
  await page.locator('#finish-training').click();await waitHistory('completed');
  pass('Whole-hand ban occupies no slot, leaves all banned copies in the deck, and real effect draws can draw them later');
  await require('./expansion-settings-smoke.cjs')({page,nativeWait,nativeState,hostWait,waitHistory,pass,evidence});
  await require('./condition-cards-smoke.cjs')({page,nativeWait,hostWait,waitHistory,pass,evidence});
  await require('./timeline-effects-smoke.cjs')({page,nativeWait,nativeState,hostWait,waitHistory,pass,evidence});
  await require('./review-materials-smoke.cjs')({page,nativeWait,nativeState,hostWait,waitHistory,pass,evidence});
  compromiseSaved=await require('./compromise-smoke.cjs')({application,page,nativeWait,nativeState,hostWait,pass,evidence});
  await page.locator('#nav-decks').click();
  await page.evaluate(async id=>{const current=await api(`/api/deck?id=${encodeURIComponent(id)}`);await api('/api/decks',{...current,deck:{...current.deck,side:[]}});},deckId);
  assert.deepEqual(await (await fetch(`${service.url}/api/plan/${sessionId}`)).json(),report);
  assert.equal((await (await fetch(`${service.url}/api/deck?id=${encodeURIComponent(deckId)}`)).json()).deck.side.length,0);
  pass('Editing the source deck leaves the entire saved plan byte-for-byte equivalent at the API');
  await page.locator('#module-decks').click();
  await page.waitForFunction(()=>moduleUI.current==='decks'&&!moduleUI.switching);
  if (await page.locator('#deck-workbench').isVisible()) await page.locator('#back-to-decks').click();
  await page.locator('[data-open-deck='+JSON.stringify(deckId)+']').click({button:'right'});
  await page.locator('[data-deck-command="delete"]').click();
  await page.locator('#delete-cancel').click();
  await page.waitForFunction(() => !app.busy);
  assert((await (await fetch(`${service.url}/api/decks`)).json()).some(d => d.id === deckId));
  await page.locator('[data-open-deck='+JSON.stringify(deckId)+']').click({button:'right'});
  await page.locator('[data-deck-command="delete"]').click();
  await page.locator('#delete-confirm').click();
  await page.waitForFunction(() => !app.busy && document.querySelector('#notice').textContent.startsWith('已删除'));
  assert(!(await (await fetch(`${service.url}/api/decks`)).json()).some(d => d.id === deckId));
  assert.deepEqual(await (await fetch(`${service.url}/api/report/${sessionId}`)).json(), report);
  const deletedBackups = fs.readdirSync(path.join(root, 'runtime', '_trainer', 'backups', 'deleted'));
  assert(deletedBackups.some(id => JSON.parse(fs.readFileSync(path.join(root, 'runtime', '_trainer', 'backups', 'deleted', id, 'metadata.json'))).id === deckId));
  await close();
  pass('Deletion cancel, confirmed deletion, verified recovery backup and retained training report');
  await verifyBranchRestart();
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(evidence, 'result.json'), JSON.stringify({ label, embedded:true,globalInput:false,checks,errors,root,sessionId,interrupted }, null, 2));
})().catch(async error => {
  console.error(error);
  fs.writeFileSync(path.join(evidence, 'failure.json'), JSON.stringify({ error: error.stack, checks, errors }, null, 2));
  if (application) {
    await page.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{});
    const state=await page.evaluate(()=>({view:app.view,active:app.active,draft:flow.draft,busy:flow.busy,notice:document.querySelector('#notice').textContent,designError:document.querySelector('#design-error').textContent})).catch(()=>null);
    fs.writeFileSync(path.join(evidence,'failure-state.json'),JSON.stringify(state,null,2));
    // Only this isolated test profile: never leave a failed test at an unsaved-edits dialog.
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().forEach(w => w.destroy())).catch(() => {});
    await application.close().catch(() => {});
  }
  process.exitCode = 1;
});
