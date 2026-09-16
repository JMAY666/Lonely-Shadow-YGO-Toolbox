'use strict';
const { app, BrowserWindow, dialog, Menu, screen, ipcMain, clipboard, globalShortcut } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const branding = require('./branding.cjs');
const tutorialShortcuts = require('./tutorial-shortcuts.cjs');
app.setName(branding.name);
const brandAssets = app.isPackaged ? path.join(process.resourcesPath, 'trainer', 'web', 'brand') : path.dirname(branding.icon);
const applicationIcon = path.join(brandAssets, 'app.ico');

// Chromium's layered DirectComposition surface can cover the sibling OpenGL
// child even when that child owns the hit test. Select HWND composition before
// creating any windows; the renderer and native engine keep GPU acceleration.
if (process.platform === 'win32') app.commandLine.appendSwitch('disable-direct-composition');

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0) return null;
  if (!process.argv[index + 1] || process.argv[index + 1].startsWith('--')) throw new Error(`${name} 需要一个路径`);
  return path.resolve(process.argv[index + 1]);
}
const workspace = path.resolve(__dirname, '..');
const dataDir = argument('--data-dir') || branding.defaultDataDir({packaged:app.isPackaged,
  workspace, localAppData:process.env.LOCALAPPDATA, appData:app.getPath('appData')});
fs.mkdirSync(dataDir, { recursive: true });
app.setPath('userData', path.join(dataDir, 'electron'));
fs.mkdirSync(app.getPath('userData'), { recursive: true });
app.setAppUserModelId(branding.appId);
const webPreferences = { nodeIntegration: false, contextIsolation: true, sandbox: true };
let mainWindow, backend, ready, shuttingDown = false, finished = false, log;
let closeRequested = false;
const queueLayout = require('./native-layout.cjs').latestLayout(async bounds => {
  if(shuttingDown)return;
  const response=await fetch(`${ready.url}/api/desktop/layout`,{method:'POST',
    headers:{'Content-Type':'application/json','X-Trainer-Token':ready.token},body:JSON.stringify(bounds),signal:AbortSignal.timeout(5000)});
  const value=await response.json();
  if(!response.ok)throw new Error(value.error);
  return value;
});
let tutorialController;
const tutorialSettingsFile = path.join(dataDir, 'tutorial-shortcuts.json');
function readTutorialSettings() {
  try {
    const saved=JSON.parse(fs.readFileSync(tutorialSettingsFile,'utf8'));
    const bindings=tutorialShortcuts.normalize(saved.bindings);
    const legacy=tutorialShortcuts.normalize(tutorialShortcuts.legacyDefaults);
    return {bindings:!saved.version&&Object.keys(legacy).every(key=>bindings[key]===legacy[key])?tutorialShortcuts.normalize(tutorialShortcuts.defaults):bindings};
  }
  catch(error) {return {bindings:{...tutorialShortcuts.defaults},error:error.code==='ENOENT'?'':'快捷键设置无法读取，原文件已保留；当前使用默认组合键。'};}
}

function watchTutorialKeys(bindings, callback, failed) {
  const resources=app.isPackaged?process.resourcesPath:path.join(workspace,'.local','desktop-bundle');
  const program=app.isPackaged?path.join(resources,'trainer','tutorial_keys.py'):path.join(workspace,'src','trainer','tutorial_keys.py');
  const child=spawn(path.join(resources,'python','python.exe'),['-I','-u',program,JSON.stringify(bindings),String(process.pid)],{windowsHide:true,stdio:['ignore','pipe','pipe']});
  let stopped=false;
  const lines=readline.createInterface({input:child.stdout});
  lines.on('line',line=>{if(stopped)return;try {const actions=JSON.parse(line);if(Array.isArray(actions))callback(actions.filter(action=>Object.hasOwn(bindings,action)));}catch{ /* Ignore incomplete output on exit. */ }});
  child.on('error',error=>{if(!stopped)failed(error.message);});
  child.on('exit',()=>{if(!stopped)failed('按键状态辅助进程已退出，请重新启用快捷键');});
  child.stderr.on('data',data=>writeLog('Tutorial repeat: '+data.toString()));
  return ()=>{stopped=true;lines.close();child.kill();};
}

function writeLog(message) {
  log?.write(`${new Date().toISOString()} ${message}\n`);
}
async function stop() {
  if (shuttingDown) return;
  shuttingDown = true;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.setEnabled(false);
    mainWindow.setTitle(`${branding.name} · 正在保存并退出`);
  }
  if (backend && backend.exitCode === null && backend.signalCode === null) {
    const exited = new Promise(resolve => backend.once('exit', resolve));
    if (ready) {
      try {
        await fetch(`${ready.url}/api/shutdown`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Trainer-Token': ready.token },
          body: '{}', signal: AbortSignal.timeout(2500)
        });
      } catch (error) { writeLog(`HTTP shutdown: ${error.message}`); }
    }
    backend.stdin.end();
    let timer;
    await Promise.race([exited, new Promise(resolve => {
      timer = setTimeout(() => { writeLog('Service shutdown timed out; closing owned service and its job.'); backend.kill(); resolve(); }, 15000);
    })]);
    clearTimeout(timer);
  }
  finished = true;
  log?.end();
  app.exit(0);
}

function allowedPage(url, origin) {
  try { const u = new URL(url); return u.origin === origin && !u.username && !u.password; }
  catch { return false; }
}

function bindWindow(window, origin) {
  const contents = window.webContents;
  contents.on('will-navigate', (event, url) => { if (!allowedPage(url, origin)) event.preventDefault(); });
  contents.on('will-redirect', (event, url) => { if (!allowedPage(url, origin)) event.preventDefault(); });
  contents.setWindowOpenHandler(({ url }) => {
    if (!allowedPage(url, origin)) return { action: 'deny' };
    const parsed=new URL(url);
    const opponent=parsed.pathname==='/opponent.html'&&/^[0-9a-f-]{36}$/.test(parsed.searchParams.get('session')||'');
    if(!opponent&&!/^\/api\/(raw|ydk)\/[0-9a-f-]{36}$/.test(parsed.pathname))return { action: 'deny' };
    return { action: 'allow', overrideBrowserWindowOptions: { parent: mainWindow, icon:applicationIcon, show:process.env.YGO_DESKTOP_BACKGROUND!=='1', width: 1050, height: 820, autoHideMenuBar: true, webPreferences } };
  });
  contents.on('did-create-window', (child,details) => {
    bindWindow(child, origin);
    const parsed=new URL(details.url);
    if(parsed.pathname!=='/opponent.html')return;
    const id=parsed.searchParams.get('session');let releasing=false,canClose=false;
    child.on('close',event=>{
      if(canClose||shuttingDown)return;
      event.preventDefault();if(releasing)return;releasing=true;
      void (async()=>{
        for(let attempt=0;attempt<30;attempt++) {
          const state=await (await fetch(`${ready.url}/api/opponent/state/${id}`)).json();
          if(!state.running||!state.manual){canClose=true;child.close();return;}
          if(attempt%5===0)await fetch(`${ready.url}/api/opponent/control`,{method:'POST',headers:{'Content-Type':'application/json','X-Trainer-Token':ready.token},body:JSON.stringify({id,command:'release',version:state.version})});
          await new Promise(resolve=>setTimeout(resolve,100));
        }
        writeLog('Opponent window retained: AI handover was not acknowledged.');
      })().catch(error=>writeLog(`Opponent handover: ${error.message}`)).finally(()=>{releasing=false;});
    });
  });
  contents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  contents.session.setPermissionCheckHandler(() => false);
}

function launchBackend(importFrom) {
  const resources = app.isPackaged ? process.resourcesPath : path.join(workspace, '.local', 'desktop-bundle');
  const python = path.join(resources, 'python', 'python.exe');
  const program = app.isPackaged ? path.join(resources, 'trainer', 'app.py') : path.join(workspace, 'src', 'trainer', 'app.py');
  if (!fs.existsSync(python) || !fs.existsSync(path.join(resources, 'runtime.zip'))) {
    throw new Error('缺少桌面运行资源。开发环境请先运行 npm run desktop:prepare；打包版请完整解压应用包。');
  }
  // The embedded interpreter has an isolated sys.path. runpy explicitly adds only our source directory.
  const bootstrap = 'import sys,runpy; p=sys.argv.pop(1); sys.path.insert(0,p); runpy.run_path(p+"/app.py",run_name="__main__")';
  const args = ['-I', '-X', 'utf8', '-u', '-c', bootstrap, path.dirname(program), '--desktop', '--no-browser', '--port', '0',
    '--runtime', path.join(dataDir, 'runtime'), '--bundle', path.join(resources, 'runtime.zip'), '--parent-pid', String(process.pid), '--embedded'];
  if (process.env.YGO_DESKTOP_TEST === '1') args.push('--enable-native-test');
  if (importFrom) args.push('--import-from', importFrom);
  backend = spawn(python, args, { cwd: dataDir, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  backend.stderr.setEncoding('utf8');
  backend.stderr.on('data', chunk => writeLog(chunk));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('本地服务未能在 5 分钟内启动，请检查日志及磁盘空间。')), 300000);
    backend.once('error', error => { clearTimeout(timer); reject(error); });
    backend.once('exit', (code, signal) => {
      clearTimeout(timer);
      if (!ready) reject(new Error(`本地服务启动失败（${code ?? signal}）。请查看 ${path.join(dataDir, 'logs', 'desktop.log')}`));
      else if (!shuttingDown) {
        if (process.env.YGO_DESKTOP_BACKGROUND !== '1') dialog.showErrorBox('训练服务已退出', '本地服务意外退出，已落盘的记录保留。请重新启动应用。');
        writeLog('Service exited unexpectedly.');
        mainWindow?.destroy();
      }
    });
    readline.createInterface({ input: backend.stdout }).on('line', line => {
      try {
        const value = JSON.parse(line);
        if (value.event === 'ready' && value.pid === backend.pid && /^http:\/\/127\.0\.0\.1:\d+$/.test(value.url)) {
          ready = value;
          clearTimeout(timer);
          resolve(value);
        } else writeLog(line);
      } catch { writeLog(line); }
    });
  });
}

if (!app.requestSingleInstanceLock()) {
  app.exit(0);
} else {
  app.on('second-instance', () => { if (mainWindow && process.env.YGO_DESKTOP_BACKGROUND !== '1') { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.show(); mainWindow.focus(); } });
  app.on('before-quit', event => {
    if (finished) return;
    event.preventDefault();
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close();
    else void stop();
  });
  app.on('window-all-closed', () => { void stop(); });
  app.on('will-quit', () => tutorialController?.stop());
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null);
    fs.mkdirSync(path.join(dataDir, 'logs'), { recursive: true });
    log = fs.createWriteStream(path.join(dataDir, 'logs', 'desktop.log'), { flags: 'a' });
    const stateFile = path.join(dataDir, 'window.json');
    let bounds = { width: 1440, height: 920 };
    try {
      const saved = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
      if (Number.isInteger(saved.width) && Number.isInteger(saved.height) && saved.width >= 900 && saved.height >= 650) {
        const display = screen.getDisplayMatching(saved).workArea;
        bounds = { width: Math.min(saved.width, display.width), height: Math.min(saved.height, display.height), x: display.x + 20, y: display.y + 20 };
      }
    } catch { /* First launch or damaged window settings: use defaults. */ }
    mainWindow = new BrowserWindow({ ...bounds, minWidth: 900, minHeight: 650, title: branding.name, icon:applicationIcon, autoHideMenuBar: true,
      ...(process.platform === 'win32' ? { titleBarStyle: 'hidden',
        titleBarOverlay: { color: '#152129', symbolColor: '#dce6ea', height: 60 } } : {}),
      show: process.env.YGO_DESKTOP_BACKGROUND !== '1',
      webPreferences: { ...webPreferences, preload: path.join(__dirname, 'preload.cjs'), backgroundThrottling: false } });
    tutorialController = tutorialShortcuts.createController({registry:globalShortcut,watchKeys:process.platform==='win32'?watchTutorialKeys:undefined,
      onStatus:value=>mainWindow?.webContents.send('trainer:tutorial-status',value),
      isFocused:()=>!!mainWindow?.isFocused(),send:value=>mainWindow?.webContents.send('trainer:tutorial-action',value)});
    const shortcutSender = event => {
      if (!ready || shuttingDown || event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || new URL(event.senderFrame.url).origin !== ready.url) throw new Error('无效的教程快捷键请求');
    };
    ipcMain.handle('trainer:tutorial-settings', event => {shortcutSender(event);return readTutorialSettings();});
    ipcMain.handle('trainer:tutorial-save-settings', (event, bindings) => {
      shortcutSender(event);
      const settings={version:2,bindings:tutorialShortcuts.normalize(bindings)};
      const temporary=tutorialSettingsFile+'.tmp';
      if(fs.existsSync(tutorialSettingsFile))fs.copyFileSync(tutorialSettingsFile,tutorialSettingsFile+'.backup');
      fs.writeFileSync(temporary,JSON.stringify(settings,null,2)+'\n');fs.renameSync(temporary,tutorialSettingsFile);
      return settings;
    });
    ipcMain.handle('trainer:tutorial-update', (event, value) => {shortcutSender(event);return tutorialController.update(value);});
    const syncTutorial = () => {
      const status=tutorialController.sync();mainWindow?.webContents.send('trainer:tutorial-status',status);
    };
    mainWindow.on('focus',syncTutorial);mainWindow.on('blur',syncTutorial);
    mainWindow.webContents.on('did-start-navigation', (_event,_url,_inPlace,isMainFrame) => {if(isMainFrame)tutorialController.stop();});
    mainWindow.webContents.on('render-process-gone',()=>tutorialController.stop());
    if(process.env.YGO_DESKTOP_TEST==='1')globalThis.tutorialAcceptance=tutorialController;
    ipcMain.handle('trainer:copy-deck', async (event, id) => {
      if (!ready || shuttingDown || event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || new URL(event.senderFrame.url).origin !== ready.url) throw new Error('无效的卡组复制请求');
      if (typeof id !== 'string' || id.length > 512) throw new Error('构筑标识无效');
      const response = await fetch(`${ready.url}/api/decks/export?id=${encodeURIComponent(id)}`);
      const exported = await response.json();
      if (!response.ok) throw new Error(exported.error || '无法读取已保存卡组');
      if (typeof exported.text !== 'string' || exported.text.length > 65536) throw new Error('YDK 内容过长，请使用文件导出');
      clipboard.writeText(exported.text);
      return {copied:true,name:exported.name};
    });
    ipcMain.handle('trainer:copy-card-names', async (event, codes) => {
      if (!ready || shuttingDown || event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || new URL(event.senderFrame.url).origin !== ready.url) throw new Error('无效的卡名复制请求');
      const names = await require('./card-names.cjs').cardNamesForCopy(codes, async code => {
        const response = await fetch(`${ready.url}/api/card/${code}`);
        const card = await response.json();
        if (!response.ok) throw new Error(card.error || '无法读取卡名');
        return card;
      });
      clipboard.writeText(names.join(' + '));
      return {copied:true,count:names.length};
    });
    ipcMain.handle('trainer:layout', async (event, bounds) => {
      if (!ready || shuttingDown || event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || new URL(event.senderFrame.url).origin !== ready.url) throw new Error('无效的训练区域请求');
      const handle = mainWindow.getNativeWindowHandle();
      const hwnd = (handle.length === 8 ? handle.readBigUInt64LE() : BigInt(handle.readUInt32LE())).toString();
      return queueLayout({...bounds,hwnd});
    });
    mainWindow.webContents.on('will-prevent-unload', event => {
      const response = dialog.showMessageBoxSync(mainWindow, { type: 'question', title: '内容尚未保存',
        message: '构筑、前置设计或草稿文字可能尚未保存，展开中的记录尚未成为正式方案。是否离开？已落盘的草稿和历史会保留。', buttons: ['继续编辑', '离开页面'], defaultId: 0, cancelId: 0 });
      if (response === 1) event.preventDefault();
    });
    mainWindow.on('close', event => {
      event.preventDefault();
      if (closeRequested || shuttingDown) return;
      closeRequested = true;
      try { fs.writeFileSync(stateFile, JSON.stringify(mainWindow.getNormalBounds())); }
      catch (error) { writeLog(`Window settings: ${error.message}`); }
      void (async () => {
        // Keep the parent HWND alive until the native child has flushed and exited.
        const dirty = ready && await mainWindow.webContents.executeJavaScript('typeof unsavedSummary === "function" ? unsavedSummary() : (typeof app !== "undefined" && app.dirty ? "构筑有未保存修改。" : "")').catch(() => '未能确认保存状态。');
        if (dirty) {
          const { response } = await dialog.showMessageBox(mainWindow, { type: 'question', title: '内容尚未保存',
            message: `${dirty}\n是否退出？已落盘的草稿和历史会保留。`, buttons: ['继续编辑', '退出应用'], defaultId: 0, cancelId: 0 });
          if (response === 0) { closeRequested = false; return; }
        }
        await stop();
      })().catch(error => { closeRequested = false; writeLog(error.stack); });
    });
    mainWindow.on('closed', () => {
      tutorialController.stop();
      mainWindow = null;
      for (const child of BrowserWindow.getAllWindows()) child.destroy();
      void stop();
    });
    const loading = fs.readFileSync(path.join(__dirname, 'loading.html'), 'utf8')
      .replace('__APP_ICON__', fs.readFileSync(path.join(brandAssets, 'app.svg')).toString('base64'));
    await mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(loading));
    if (process.env.YGO_DESKTOP_TEST === '1') globalThis.brandingAcceptance = {
      windowIconExists:fs.existsSync(applicationIcon),
      loadingImage:await mainWindow.webContents.executeJavaScript('document.images[0].complete && document.images[0].naturalWidth > 0'),
      loadingTitlebar:await mainWindow.webContents.executeJavaScript('getComputedStyle(document.querySelector(".loading-titlebar")).webkitAppRegion === "drag"')
    };
    const importFrom = argument('--import-from') || (!app.isPackaged ? path.join(workspace, '.local', 'YGOPro-Lite') : null);
    const service = await launchBackend(importFrom);
    if (shuttingDown || !mainWindow) return;
    bindWindow(mainWindow, service.url);
    await mainWindow.loadURL(service.url);
    writeLog(`Ready: service ${service.pid}, ${service.url}, data ${dataDir}`);
  }).catch(error => {
    writeLog(error.stack || error.message);
    if (!shuttingDown && process.env.YGO_DESKTOP_BACKGROUND !== '1') dialog.showErrorBox(`${branding.name} 启动失败`, error.message);
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.destroy();
    void stop();
  });
}
