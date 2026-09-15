(function(root,factory) {
  const bindings=factory();
  if(typeof module==='object'&&module.exports)module.exports=bindings;
  else root.TutorialBindings=bindings;
})(globalThis,function() {
  'use strict';
  const defaults=Object.freeze({back:'Left',forward:'Right',up:'Up',down:'Down',end:''});
  const legacyDefaults=Object.freeze({back:'Control+Shift+Left',forward:'Control+Shift+Right',up:'Control+Shift+Up',down:'Control+Shift+Down',end:''});
  const labels=Object.freeze({back:'后退',forward:'前进',up:'上一条路线',down:'下一条路线',end:'展开结束'});
  const modifiers=['CONTROL','ALT','SHIFT','SUPER'];
  function normalize(bindings) {
    if(!bindings||typeof bindings!=='object')throw new Error('快捷键设置无效');
    const result={},used=new Set();
    for(const action of Object.keys(defaults)) {
      const raw=bindings[action];
      if(typeof raw!=='string'||raw.length>80)throw new Error(`${labels[action]}快捷键无效`);
      if(!raw.trim()){result[action]='';continue;}
      const parts=raw.trim().split('+').map(value=>value.trim().toUpperCase()),key=parts.pop();
      if(parts.some(value=>!modifiers.includes(value))||new Set(parts).size!==parts.length||!/^(LEFT|RIGHT|UP|DOWN|[A-Z0-9]|F(?:[1-9]|1[0-9]|2[0-4])|SPACE|ENTER|HOME|END|PAGEUP|PAGEDOWN)$/.test(key))throw new Error(`${labels[action]}快捷键格式无效；示例 Control+Shift+Right`);
      const normalized=[...modifiers.filter(value=>parts.includes(value)),key].join('+');
      if(used.has(normalized))throw new Error('多个动作不能使用相同快捷键');
      used.add(normalized);result[action]=normalized;
    }
    return result;
  }
  function accelerator(event) {
    const aliases={ArrowLeft:'LEFT',ArrowRight:'RIGHT',ArrowUp:'UP',ArrowDown:'DOWN',' ':'SPACE'};
    if(['Control','Alt','Shift','Meta'].includes(event.key))return '';
    return [...(event.ctrlKey?['CONTROL']:[]),...(event.altKey?['ALT']:[]),...(event.shiftKey?['SHIFT']:[]),...(event.metaKey?['SUPER']:[]),aliases[event.key]||event.key.toUpperCase()].join('+');
  }
  function actionFor(bindings,event) {
    const key=accelerator(event);
    return Object.entries(bindings).find(([,binding])=>binding&&binding.toUpperCase()===key)?.[0];
  }
  return {defaults,legacyDefaults,labels,normalize,accelerator,actionFor};
});
