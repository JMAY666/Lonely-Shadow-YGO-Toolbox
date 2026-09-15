'use strict';
const path=require('node:path');
const {app}=require('electron');
// The renderer assets live outside app.asar in a packaged installation.
const {defaults,legacyDefaults,labels,normalize}=require(app?.isPackaged
  ?path.join(process.resourcesPath,'trainer','web','tutorial-bindings.js')
  :path.join(__dirname,'../src/trainer/web/tutorial-bindings.js'));
function createController({registry,send,isFocused,watchKeys,now=Date.now,onStatus}) {
  let state = {active:false,enabled:false,suspended:false,session:'',bindings:defaults}, registered = [], error = '';
  let stopWatching;
  const held = new Map();
  function release() {stopWatching?.();stopWatching=null;held.clear();for (const key of registered) registry.unregister(key); registered = [];}
  function canInvoke(action) {return state.active && state.enabled && !state.suspended && !isFocused() && registered.includes(state.bindings[action]);}
  function invoke(action) {
    if (!canInvoke(action) || stopWatching && held.has(action)) return;
    held.set(action,now()+350);
    send({action,session:state.session});
  }
  function checkHeld(actions) {
    const time=now();
    for (const [action,next] of held) {
      if (!actions.includes(action) || !canInvoke(action)) {held.delete(action);continue;}
      if (action!=='end' && time>=next) {
        held.set(action,time+100);send({action,session:state.session});
      }
    }
  }
  function sync() {
    release(); error = '';
    if (state.active && state.enabled && !state.suspended && !isFocused()) {
      for (const [action,key] of Object.entries(state.bindings)) {
        if (!key) continue;
        try {
          if (!registry.register(key, () => invoke(action))) throw new Error();
          registered.push(key);
        } catch {
          error = `${labels[action]}：${key} 注册失败或被占用，请修改组合键。后台快捷键已暂停。`;
          release(); break;
        }
      }
      if (!error && registered.length && watchKeys) stopWatching=watchKeys(state.bindings,checkHeld,message=>{
        stopWatching?.();stopWatching=null;held.clear();
        error='连续快捷键不可用：'+message;onStatus?.(status());
      });
    }
    return status();
  }
  function status() {return {registered:registered.slice(),error,enabled:state.enabled,active:state.active,session:state.session};}
  function update(value) {
    const bindings = normalize(value.bindings);
    if (typeof value.session !== 'string' || value.session.length > 128 || ['active','enabled','suspended'].some(k => typeof value[k] !== 'boolean')) throw new Error('教程快捷键状态无效');
    state = {...value,bindings}; return sync();
  }
  function stop() {state.active = false; state.session = ''; release();}
  return {update,sync,status,stop,invoke,checkHeld};
}
module.exports = {defaults,legacyDefaults,normalize,createController};
