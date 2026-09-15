const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/app.js'),'utf8');
function context(current) {
  const context=vm.createContext({moduleUI:{current,editorOwner:current,expansionView:'training'},
    flow:{deckEdit:{target:'opponent'}},document:{},window:{}});
  vm.runInContext(source.slice(0,source.indexOf('function deckState()'))+'\nglobalThis.e={app,switchView,activeDesignDeckEdit};',context);
  return context;
}
test('background expansion completion updates its return page without touching another module or its unsaved deck',()=>{
  for(const module of ['home','decks','tags']) {
    const c=context(module),a=c.e.app;
    a.view=module;a.id='library/unsaved.ydk';a.dirty=true;a.deck.main=[11,12];a.undo=[[9]];
    const before=JSON.stringify(a);
    c.e.switchView('history');
    assert.equal(c.moduleUI.expansionView,'history');
    assert.equal(c.moduleUI.current,module);
    assert.equal(JSON.stringify(a),before);
  }
});
test('suspended design deck editing cannot redirect standalone saves or disable standalone deletion',()=>{
  const c=context('decks');
  assert.equal(!!c.e.activeDesignDeckEdit(),false);
  c.moduleUI.editorOwner='expansion';
  assert.equal(c.e.activeDesignDeckEdit(),true);
  c.flow.deckEdit=null;
  assert.equal(!!c.e.activeDesignDeckEdit(),false);
});
test('module switching cannot race a discard confirmation while it is still hiding the native host',async()=>{
  const modules=fs.readFileSync(path.join(__dirname,'../src/trainer/web/modules.js'),'utf8');
  let message='';
  const c=vm.createContext({$:()=>({innerHTML:''}),app:{busy:false},flow:{confirming:true},rewindState:{},tagManagerUI:{},
    notice:value=>{message=value;},document:{querySelector(){throw Error('The modal has not been opened yet');}}});
  vm.runInContext(modules.slice(0,modules.indexOf('document.querySelectorAll'))+'\nglobalThis.e={moduleUI,switchModule};',c);
  await c.e.switchModule('decks');
  assert.equal(c.e.moduleUI.current,'home');
  assert.equal(c.e.moduleUI.switching,false);
  assert.match(message,/当前操作尚未完成/);
});
test('a failed native-host update releases the confirmation lock without accepting a discard',async()=>{
  const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/expansion.js'),'utf8');
  const node={querySelector:()=>({}),classList:{toggle(){}}};
  const c=vm.createContext({$:()=>node,flow:{confirming:false},syncNativeHost:async()=>{throw Error('host update failed');}});
  vm.runInContext(source.slice(source.indexOf('async function confirmFlow'),source.indexOf('async function openDesign')),c);
  await assert.rejects(c.confirmFlow('title','warning','discard'),/host update failed/);
  assert.equal(c.flow.confirming,false);
});
