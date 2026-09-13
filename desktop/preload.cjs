'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('trainerDesktop', {
  updateLayout: bounds => ipcRenderer.invoke('trainer:layout', bounds)
});
