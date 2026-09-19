'use strict';
// This launcher creates only a hidden, isolated acceptance instance.
const { _electron: electron } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const workspace = path.resolve(__dirname, '../..');
const local = path.join(workspace, '.local/ygo-agent-pilot');
const root = path.join(local, 'desktop-check-development-modular');
const evidence = path.join(local, 'evidence');
let app, child;
(async () => {
  fs.mkdirSync(path.join(local, 'empty-import'), {recursive: true});
  fs.mkdirSync(evidence, {recursive: true});
  const env = {...process.env, YGO_DESKTOP_TEST: '1', YGO_DESKTOP_BACKGROUND: '1'};
  delete env.ELECTRON_RUN_AS_NODE;
  app = await electron.launch({executablePath: require('electron'),
    args: [workspace, '--data-dir', root, '--import-from', path.join(local, 'empty-import')],
    env, timeout: 120000});
  const page = await app.firstWindow();
  await page.waitForFunction(() => document.querySelector('#resource-count')?.textContent.includes('张卡牌'), null, {timeout: 300000});
  await app.evaluate(({BrowserWindow}) => {
    const window = BrowserWindow.getAllWindows().find(w => !w.getParentWindow());
    window.webContents.setBackgroundThrottling(false);
    if (window.isVisible()) throw new Error('Pilot window must remain hidden');
  });
  await page.evaluate(async () => {flow.restarting = true; displayView('training'); await syncNativeHost();});
  const service = JSON.parse(fs.readFileSync(path.join(root, 'runtime/_trainer/service.json'), 'utf8'));
  child = spawn(path.join(local, '.venv/Scripts/python.exe'), ['-u', path.join(__dirname, 'run.py'),
    '--runtime', path.join(root, 'runtime'), '--url', service.url, ...process.argv.slice(2)],
    {windowsHide: true, env: {...process.env, PYTHONIOENCODING: 'utf-8'}, stdio: 'inherit'});
  const timer = setTimeout(() => child.kill(), 180000);
  const code = await new Promise((resolve, reject) => {child.once('error', reject); child.once('exit', resolve);}).finally(() => clearTimeout(timer));
  if (code !== 0) throw new Error(`Pilot exited ${code}`);
})().catch(error => {console.error(error); process.exitCode = 1;}).finally(async () => {
  if (child && child.exitCode === null) child.kill();
  if (app) {
    await app.evaluate(({BrowserWindow}) => BrowserWindow.getAllWindows().forEach(w => w.destroy())).catch(() => {});
    await app.close().catch(() => {});
  }
});
