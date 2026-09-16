'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// Only the Windows main window merges its native controls into the app header.
window.addEventListener('DOMContentLoaded', () => {
  if (process.platform === 'win32') document.documentElement.classList.add('desktop-shell');
}, { once: true });
contextBridge.exposeInMainWorld('trainerDesktop', {
  updateLayout: bounds => ipcRenderer.invoke('trainer:layout', bounds),
  copyDeckCode: id => ipcRenderer.invoke('trainer:copy-deck', id),
  copyCardNames: codes => ipcRenderer.invoke('trainer:copy-card-names', codes),
  tutorialSettings: () => ipcRenderer.invoke('trainer:tutorial-settings'),
  openPatchLink: url => ipcRenderer.invoke('trainer:open-patch-link',url),
  tutorialSaveSettings: bindings => ipcRenderer.invoke('trainer:tutorial-save-settings',bindings),
  tutorialUpdate: value => ipcRenderer.invoke('trainer:tutorial-update',value),
  onTutorialAction: callback => {const listener=(_event,value)=>callback(value);ipcRenderer.on('trainer:tutorial-action',listener);return ()=>ipcRenderer.removeListener('trainer:tutorial-action',listener);},
  onTutorialStatus: callback => {const listener=(_event,value)=>callback(value);ipcRenderer.on('trainer:tutorial-status',listener);return ()=>ipcRenderer.removeListener('trainer:tutorial-status',listener);}
});
