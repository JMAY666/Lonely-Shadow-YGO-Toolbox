'use strict';
// Render the source vector with the bundled Electron, without showing a window.
const {app, BrowserWindow, nativeImage} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const target = path.resolve(__dirname, '../src/trainer/web/brand');
const profile = path.resolve(__dirname, '../.local/icon-renderer');
fs.mkdirSync(profile, {recursive:true});
app.setPath('userData',profile);
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const window = new BrowserWindow({show:false, width:256, height:256, transparent:true,
    webPreferences:{offscreen:true, backgroundThrottling:false, sandbox:true}});
  const svg = fs.readFileSync(path.join(target, 'app.svg'), 'utf8');
  await window.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(`<style>html,body{margin:0;width:256px;height:256px;overflow:hidden;background:transparent}svg{display:block}</style>${svg}`));
  await new Promise(resolve=>setTimeout(resolve,250));
  const capture = await window.webContents.capturePage(undefined, {stayHidden:true});
  const master = nativeImage.createFromBuffer(capture.toPNG()).resize({width:256,height:256});
  fs.writeFileSync(path.join(target, 'app.png'), master.toPNG());
  const sizes = [16,24,32,48,64,128,256];
  const images = sizes.map(size => master.resize({width:size,height:size,quality:'best'}).toPNG());
  const header = Buffer.alloc(6 + images.length * 16);
  header.writeUInt16LE(1,2); header.writeUInt16LE(images.length,4);
  let offset = header.length;
  images.forEach((png,i) => {
    const start = 6+i*16;
    header[start] = header[start+1] = sizes[i]===256 ? 0 : sizes[i];
    header.writeUInt16LE(1,start+4); header.writeUInt16LE(32,start+6);
    header.writeUInt32LE(png.length,start+8); header.writeUInt32LE(offset,start+12);
    offset += png.length;
  });
  fs.writeFileSync(path.join(target, 'app.ico'), Buffer.concat([header,...images]));
  console.log('Generated app.png and app.ico (16, 24, 32, 48, 64, 128, 256 px).');
  window.destroy(); app.quit();
}).catch(error => {console.error(error);app.exit(1);});
