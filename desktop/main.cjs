'use strict';
const { app, BrowserWindow, dialog, Menu, screen, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0) return null;
  if (!process.argv[index + 1] || process.argv[index + 1].startsWith('--')) throw new Error(`${name} 需要一个路径`);
  return path.resolve(process.argv[index + 1]);
}
const workspace = path.resolve(__dirname, '..');
const dataDir = argument('--data-dir') || (app.isPackaged
  ? path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'YGOTrainer')
  : path.join(workspace, '.local', 'desktop-dev'));
fs.mkdirSync(dataDir, { recursive: true });
app.setPath('userData', path.join(dataDir, 'electron'));
fs.mkdirSync(app.getPath('userData'), { recursive: true });
app.setAppUserModelId('local.ygotrainer.desktop');
const webPreferences = { nodeIntegration: false, contextIsolation: true, sandbox: true };
let mainWindow, backend, ready, shuttingDown = false, finished = false, log;
let closeRequested = false;
let layoutQueue = Promise.resolve();

function writeLog(message) {
  log?.write(`${new Date().toISOString()} ${message}\n`);
}
async function stop() {
  if (shuttingDown) return;
  shuttingDown = true;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.setEnabled(false);
    mainWindow.setTitle('游戏王工具箱 · 正在保存并退出');
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
    if (!allowedPage(url, origin) || !/^\/api\/(raw|ydk)\/[0-9a-f-]{36}$/.test(new URL(url).pathname)) return { action: 'deny' };
    return { action: 'allow', overrideBrowserWindowOptions: { parent: mainWindow, width: 1000, height: 760, autoHideMenuBar: true, webPreferences } };
  });
  contents.on('did-create-window', child => bindWindow(child, origin));
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
    mainWindow = new BrowserWindow({ ...bounds, minWidth: 900, minHeight: 650, title: '游戏王工具箱', autoHideMenuBar: true,
      show: process.env.YGO_DESKTOP_BACKGROUND !== '1',
      webPreferences: { ...webPreferences, preload: path.join(__dirname, 'preload.cjs'), backgroundThrottling: false } });
    ipcMain.handle('trainer:layout', async (event, bounds) => {
      if (!ready || shuttingDown || event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame || new URL(event.senderFrame.url).origin !== ready.url) throw new Error('无效的训练区域请求');
      const handle = mainWindow.getNativeWindowHandle();
      const hwnd = (handle.length === 8 ? handle.readBigUInt64LE() : BigInt(handle.readUInt32LE())).toString();
      return layoutQueue = layoutQueue.catch(() => {}).then(async () => {
        if(shuttingDown) return;
        const response = await fetch(`${ready.url}/api/desktop/layout`, { method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Trainer-Token': ready.token }, body: JSON.stringify({ ...bounds, hwnd }), signal: AbortSignal.timeout(5000) });
        const value = await response.json();
        if (!response.ok) throw new Error(value.error);
        return value;
      });
    });
    mainWindow.webContents.on('will-prevent-unload', event => {
      const response = dialog.showMessageBoxSync(mainWindow, { type: 'question', title: '构筑尚未保存',
        message: '当前构筑有未保存修改。是否放弃这些修改并继续？', buttons: ['继续编辑', '放弃修改'], defaultId: 0, cancelId: 0 });
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
        const dirty = ready && await mainWindow.webContents.executeJavaScript('typeof app !== "undefined" && app.dirty').catch(() => true);
        if (dirty) {
          const { response } = await dialog.showMessageBox(mainWindow, { type: 'question', title: '构筑尚未保存',
            message: '当前构筑有未保存修改。是否放弃这些修改并退出？', buttons: ['继续编辑', '放弃修改并退出'], defaultId: 0, cancelId: 0 });
          if (response === 0) { closeRequested = false; return; }
        }
        await stop();
      })().catch(error => { closeRequested = false; writeLog(error.stack); });
    });
    mainWindow.on('closed', () => {
      mainWindow = null;
      for (const child of BrowserWindow.getAllWindows()) child.destroy();
      void stop();
    });
    await mainWindow.loadFile(path.join(__dirname, 'loading.html'));
    const importFrom = argument('--import-from') || (!app.isPackaged ? path.join(workspace, '.local', 'YGOPro-Lite') : null);
    const service = await launchBackend(importFrom);
    if (shuttingDown || !mainWindow) return;
    bindWindow(mainWindow, service.url);
    await mainWindow.loadURL(service.url);
    writeLog(`Ready: service ${service.pid}, ${service.url}, data ${dataDir}`);
  }).catch(error => {
    writeLog(error.stack || error.message);
    if (!shuttingDown && process.env.YGO_DESKTOP_BACKGROUND !== '1') dialog.showErrorBox('游戏王工具箱启动失败', error.message);
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.destroy();
    void stop();
  });
}
