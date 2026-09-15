'use strict';
const path = require('node:path');
const name = 'Lonely-Shadow-Yu-Gi-Oh-Toolbox';
const appId = 'local.ygotrainer.desktop';
// Storage identity is deliberately independent of the product's display name.
function defaultDataDir({packaged, workspace, localAppData, appData}) {
  return packaged ? path.join(localAppData || appData, 'YGOTrainer') : path.join(workspace, '.local', 'desktop-dev');
}
module.exports = {name, appId, defaultDataDir, icon:path.join(__dirname, '../src/trainer/web/brand/app.ico')};
