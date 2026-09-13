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
const root = path.join(workspace, '.local', `desktop-check-${label}`);
const evidence = path.join(workspace, '.local', 'evidence', `electron-${label}`);
fs.mkdirSync(evidence, { recursive: true });
const executable = packaged ? path.join(workspace, require('../package.json').build.directories.output, 'win-unpacked', 'YGOTrainer.exe') : require('electron');
const checks = [], errors = [];
let application, page, service, nativePid;
const env = { ...process.env };
env.YGO_DESKTOP_TEST = '1';
env.YGO_DESKTOP_BACKGROUND = '1';
delete env.ELECTRON_RUN_AS_NODE;
// Prove packaged startup does not resolve Python, Node or tooling from developer PATH.
if (packaged) env.PATH = path.join(process.env.SystemRoot, 'System32');
function pass(text) { checks.push(text); console.log(`PASS ${text}`); }
async function launch(first = false, testControl = true) {
  const args = [...(packaged ? [] : [workspace]), '--data-dir', root];
  if (first) args.push('--import-from', path.join(workspace, '.local', 'YGOPro-Lite'));
  application = await electron.launch({ executablePath: executable, args,
    env: {...env, YGO_DESKTOP_TEST: testControl ? '1' : '0'}, timeout: 120000 });
  page = await application.firstWindow();
  page.on('pageerror', error => errors.push(error.message));
  await page.waitForFunction(() => document.querySelector('#resource-count')?.textContent.includes('张卡牌'), null, { timeout: 300000 });
  service = JSON.parse(fs.readFileSync(path.join(root, 'runtime', '_trainer', 'service.json'), 'utf8'));
  assert.equal(await page.evaluate(() => typeof require), 'undefined');
  return page;
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
  assert.equal(host.composition_compatible, true, 'A layered web surface must not cover the native field');
  assert.deepEqual(host.layered_overlaps, []);
  assert.equal(host.owns_stage_hit_test, true);
}
async function close() {
  const pid = service.pid, url = service.url;
  const exited = once(application.process(), 'exit');
  await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(w => !w.getParentWindow()).close());
  await Promise.race([exited, new Promise((_, reject) => { const t = setTimeout(() => reject(new Error('Desktop did not exit')), 25000); t.unref(); })]);
  assert.throws(() => process.kill(pid, 0));
  if (nativePid) assert.throws(() => process.kill(nativePid, 0));
  await assert.rejects(fetch(url, { signal: AbortSignal.timeout(1500) }));
  application = null;
}

(async () => {
  await launch(true);
  const bootstrap = await (await fetch(`${service.url}/api/bootstrap`)).json();
  assert.equal(bootstrap.cards, 14981);
  pass('Desktop window, isolated renderer, embedded Python and local catalog');
  const deck = { main: Array.from({ length: 40 }, (_, i) => i % 2 ? 1184620 : 55144522), extra: [23995346], side: [55144522] };
  const source = path.join(evidence, 'acceptance.ydk');
  fs.writeFileSync(source, '\uFEFF#main\r\n' + deck.main.join('\r\n') + '\r\n#extra\r\n23995346\r\n!side\r\n55144522\r\n');
  await page.locator('#import-deck').click();
  await page.locator('#import-file').setInputFiles(source);
  await page.locator('#import-apply').waitFor({ state: 'visible' });
  await page.waitForFunction(() => !document.querySelector('#import-apply').disabled);
  const name = `Electron-${label}-${Date.now()}`;
  await page.locator('#import-name').fill(name);
  await page.locator('#import-apply').click();
  await page.waitForFunction(() => document.querySelector('#count-main').textContent === '40');
  assert.deepEqual(await page.evaluate(() => app.deck), deck);
  await page.locator('#save-deck').click();
  await page.waitForFunction(() => !app.dirty && !!app.id && !app.busy);
  const deckId = await page.evaluate(() => app.id);
  assert.equal(await page.locator('#card-library').isVisible(), false);
  assert.equal(await page.locator('#library-toggle').getAttribute('aria-expanded'), 'false');
  await page.locator('#library-toggle').click();
  await page.waitForFunction(() => !document.querySelector('#card-library').hidden);
  await page.locator('#search').fill('55144522');
  await page.locator('#search-button').click();
  await page.waitForFunction(() => document.querySelectorAll('#search-results button').length === 1);
  await page.locator('#search-results button').first().click();
  await page.waitForFunction(() => [...document.querySelectorAll('#card-detail img')].some(i => i.complete && i.naturalWidth > 0));
  await page.locator('#search-results button').first().dblclick();
  await page.waitForFunction(() => document.querySelector('#count-main').textContent === '41');
  await page.screenshot({ path: path.join(evidence, 'drawer.png') });
  await page.locator('#library-close').click();
  assert.equal(await page.locator('#card-library').isVisible(), false);
  await page.locator('#undo-deck').click();
  await page.waitForFunction(() => document.querySelector('#count-main').textContent === '40');
  pass('Card drawer starts collapsed; opens, searches/adds, and closes without changing the deck');
  await page.locator('#new-deck').click();
  await page.locator('#compact-deck').selectOption(deckId);
  await page.locator('#compact-open').click();
  await page.waitForFunction(id => app.id === id && !app.busy, deckId);
  assert.deepEqual(await page.evaluate(() => app.deck), deck);
  await page.screenshot({ path: path.join(evidence, 'editor.png') });
  pass('YDK file import, all zones/order, image/effect, add/undo, save and reopen');
  await page.locator('#start-training').click();
  await page.waitForFunction(() => !!app.active);
  const sessionId = await page.evaluate(() => app.active.id);
  const sessionPath = path.join(root, 'runtime', '_trainer', 'sessions', sessionId);
  await page.waitForTimeout(2500);
  const metadata = JSON.parse(fs.readFileSync(path.join(sessionPath, 'session.json'), 'utf8'));
  nativePid = metadata.pid;
  assert.equal(metadata.status, 'running');
  assert.deepEqual(metadata.deck, deck);
  console.log(JSON.stringify({ phase: 'embedded-training', label, sessionId, nativePid, service, sessionPath }));
  const host = await hostWait(sessionId, s => s.frame_ready && s.visible && s.owns_stage_hit_test && s.composition_compatible);
  assert.equal(host.ready, true); assert.equal(host.child_style, true); assert.equal(host.caption, false);
  assert.equal(host.frame_ready,true);
  await page.waitForFunction(()=>document.querySelector('#native-loading').hidden);
  assertComposition(host);
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
  const report = await (await fetch(`${service.url}/api/report/${sessionId}`)).json();
  assert.equal(report.status, 'completed');
  const journal = fs.readFileSync(path.join(sessionPath, 'native.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(journal[0].test_control, true);
  assert(journal.some(r => r.kind === 'end' && r.reason === 'manual'));
  assert.equal(report.statistics['效果抽卡'],2);
  assert.equal(report.statistics['通常召唤成功'],1);
  assert.equal(report.actions.length,2);
  assert.equal(await page.locator('.timeline > li').count(), 2);
  assert.equal(await page.locator('.action-title').filter({hasText: /攻击宣言|伤害步骤|战斗结果|受到.*伤害/}).count(), 0);
  await page.screenshot({ path: path.join(evidence, 'report.png') });
  assert.equal(await page.locator('.action-title').filter({ hasText: '编号未知' }).count(), 0);
  if (report.actions.some(a => a.kind === 'effect')) {
    assert(await page.locator('.effect-description').count() > 0);
    assert((await page.locator('.actual-execution').first().innerText()).includes('实际结果'));
  }
  await page.locator('#all-events').check();
  assert(await page.locator('#all-events').isChecked());
  await page.waitForFunction(() => [...document.querySelectorAll('.action-title')].some(e => e.textContent === '战斗结果'));
  assert.equal(await page.locator('.action-title').filter({hasText: '战斗结果'}).count(), 1);
  await page.locator('#all-events').uncheck();
  await page.waitForFunction(() => document.querySelectorAll('.timeline > li').length === 2);
  const popupPromise = page.waitForEvent('popup');
  await page.locator('a[href^="/api/raw/"]').click();
  const rawWindow = await popupPromise;
  await rawWindow.waitForLoadState();
  assert((await rawWindow.locator('body').innerText()).includes(sessionId));
  assert.equal(await rawWindow.evaluate(() => typeof require), 'undefined');
  await rawWindow.close();
  pass('Raw-event toggle and JSONL open in an isolated Electron child window');
  pass('Real embedded engine effect/summon, journal and completed report');
  await close();
  pass('Window close releases service, native process and listening port');
  await launch(false, false);
  await page.locator('#compact-deck').selectOption(deckId);
  await page.locator('#compact-open').click();
  await page.waitForFunction(id => app.id === id && !app.busy, deckId);
  assert.deepEqual(await page.evaluate(() => app.deck), deck);
  await page.locator('#nav-history').click();
  await page.locator(`[data-report="${sessionId}"]`).click();
  await page.waitForFunction(id => app.reportId === id, sessionId);
  assert.deepEqual(await (await fetch(`${service.url}/api/report/${sessionId}`)).json(), report);
  pass('Restart retains complete deck and exact report');
  await page.locator('#nav-decks').click();
  await page.locator('#start-training').click();
  await page.waitForFunction(() => !!app.active);
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
  await launch();
  await page.locator('#compact-deck').selectOption(deckId);
  await page.locator('#delete-deck').click();
  await page.locator('#delete-cancel').click();
  await page.waitForFunction(() => !app.busy);
  assert((await (await fetch(`${service.url}/api/decks`)).json()).some(d => d.id === deckId));
  await page.locator('#delete-deck').click();
  await page.locator('#delete-confirm').click();
  await page.waitForFunction(() => !app.busy && document.querySelector('#notice').textContent.startsWith('已删除'));
  assert(!(await (await fetch(`${service.url}/api/decks`)).json()).some(d => d.id === deckId));
  assert.deepEqual(await (await fetch(`${service.url}/api/report/${sessionId}`)).json(), report);
  const deletedBackups = fs.readdirSync(path.join(root, 'runtime', '_trainer', 'backups', 'deleted'));
  assert(deletedBackups.some(id => JSON.parse(fs.readFileSync(path.join(root, 'runtime', '_trainer', 'backups', 'deleted', id, 'metadata.json'))).id === deckId));
  await close();
  pass('Deletion cancel, confirmed deletion, verified recovery backup and retained training report');
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(evidence, 'result.json'), JSON.stringify({ label, embedded:true,globalInput:false,checks,errors,root,sessionId,interrupted }, null, 2));
})().catch(async error => {
  console.error(error);
  fs.writeFileSync(path.join(evidence, 'failure.json'), JSON.stringify({ error: error.stack, checks, errors }, null, 2));
  if (application) {
    // Only this isolated test profile: never leave a failed test at an unsaved-edits dialog.
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().forEach(w => w.destroy())).catch(() => {});
    await application.close().catch(() => {});
  }
  process.exitCode = 1;
});
