'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// Only the Windows main window merges its native controls into the app header.
window.addEventListener('DOMContentLoaded', () => {
  if (process.platform === 'win32') document.documentElement.classList.add('desktop-shell');
}, { once: true });
contextBridge.exposeInMainWorld('trainerDesktop', {
  updateLayout: bounds => ipcRenderer.invoke('trainer:layout', bounds)
});
