'use strict';
const defaults = {back:'Left',forward:'Right',up:'Up',down:'Down',end:''};
const legacyDefaults = {back:'Control+Shift+Left',forward:'Control+Shift+Right',up:'Control+Shift+Up',down:'Control+Shift+Down',end:''};
const labels = {back:'后退',forward:'前进',up:'上一条路线',down:'下一条路线',end:'展开结束'};
function normalize(bindings) {
  if (!bindings || typeof bindings !== 'object') throw new Error('快捷键设置无效');
  const result = {}, used = new Set();
  for (const action of Object.keys(defaults)) {
    const raw = bindings[action];
    if (typeof raw !== 'string' || raw.length > 80) throw new Error(`${labels[action]}快捷键无效`);
    if (!raw.trim()) { result[action] = ''; continue; }
    const parts = raw.trim().split('+').map(v => v.trim().toUpperCase()), key = parts.pop();
    const mods = ['CONTROL','ALT','SHIFT','SUPER'];
    if (parts.some(v => !mods.includes(v)) || new Set(parts).size !== parts.length || !/^(LEFT|RIGHT|UP|DOWN|[A-Z0-9]|F(?:[1-9]|1[0-9]|2[0-4])|SPACE|ENTER|HOME|END|PAGEUP|PAGEDOWN)$/.test(key)) throw new Error(`${labels[action]}快捷键格式无效；示例 Control+Shift+Right`);
    const normalized = [...mods.filter(v => parts.includes(v)),key].join('+');
    if (used.has(normalized)) throw new Error('多个动作不能使用相同快捷键');
    used.add(normalized); result[action] = normalized;
  }
  return result;
}
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
