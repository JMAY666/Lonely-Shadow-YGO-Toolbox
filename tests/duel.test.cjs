const test=require('node:test'),assert=require('node:assert/strict');
const model=require('../src/trainer/web/duel-model.js');
const {normalize,defaults,createController}=require('../desktop/tutorial-shortcuts.cjs');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');

test('shared hand counts prevent overflow from either candidate area and permit replacement',()=>{
  const deck={main:[1,1,2,3,4],extra:[9],side:[1]};
  let hand=Array(3).fill(null);
  assert.match(model.handError(deck,3,hand),/还需选择 3/);
  hand=model.place(deck,3,hand,1);hand=model.place(deck,3,hand,1);
  assert.equal(model.place(deck,3,hand,1),null);
  assert.equal(model.place(deck,3,hand,9),null);
  hand=model.place(deck,3,hand,2);assert.equal(model.handError(deck,3,hand),'');
  assert.equal(model.place(deck,3,hand,3),null);
  assert.deepEqual(model.place(deck,3,hand,3,0),[3,1,2]);
  assert.deepEqual(model.place(deck,3,hand,1,0),[1,1,2]);
  assert.match(model.handError(deck,3,[1,1,1]),/实际投入/);
  assert.match(model.handError(deck,3,[1,1,2,3]),/超出/);
});
test('navigation follows graph edges, explicit branch selection and mouse jumps',()=>{
  const routes=[{id:'main',label:'主线',model:{steps:[{id:'s1',number:1},{id:'s2',number:2}]}},
    {id:'a',label:'妥协 A',source:{node_id:'s1',timing:'结算后'},model:{steps:[{id:'b1',number:3}]}},
    {id:'orphan',label:'不可达',source:{node_id:'missing'},model:{steps:[{id:'c1'}]}}];
  const graph=model.graph(routes);let pos={key:graph.start,choice:0};
  assert.equal(pos.key,'main/s1');assert(!graph.nodes.some(n=>n.route==='orphan'));
  assert.equal(model.navigate(graph,pos,'forward').key,'main/s2');
  pos=model.navigate(graph,pos,'down');assert.equal(pos.choice,1);
  pos=model.navigate(graph,pos,'forward');assert.equal(pos.key,'a/b1');
  pos=model.navigate(graph,pos,'back');assert.deepEqual(pos,{key:'main/s1',choice:1});
  pos={key:'main/s2',choice:0};pos=model.navigate(graph,pos,'forward');assert.equal(pos.key,'main/final');
  assert.deepEqual(model.navigate(graph,pos,'forward'),pos);
});
test('shortcut conflicts, focused editing, failure rollback and lifecycle cleanup',()=>{
  let focused=false;const registered=new Map(),sent=[];
  const registry={register(key,fn){if(key==='CONTROL+ALT+F1')return false;registered.set(key,fn);return true;},unregister(key){registered.delete(key);}};
  const ctl=createController({registry,send:e=>sent.push(e),isFocused:()=>focused});
  const config={active:true,enabled:true,suspended:false,session:'a',bindings:defaults};
  assert.equal(ctl.update(config).registered.length,4);
  registered.get('CONTROL+SHIFT+RIGHT')();assert.deepEqual(sent,[{action:'forward',session:'a'}]);
  focused=true;ctl.sync();assert.equal(registered.size,0);ctl.invoke('forward');assert.equal(sent.length,1);
  focused=false;ctl.sync();assert.equal(registered.size,4);
  assert.equal(ctl.update({...config,suspended:true}).registered.length,0);
  assert.match(ctl.update({...config,bindings:{...defaults,end:'Control+Alt+F1'}}).error,/注册失败/);assert.equal(registered.size,0);
  assert.throws(()=>normalize({...defaults,end:defaults.back}),/相同快捷键/);
  assert.throws(()=>normalize({...defaults,end:'Command+garbage'}),/格式无效/);
  ctl.update(config);ctl.stop();assert.equal(registered.size,0);ctl.invoke('back');assert.equal(sent.length,1);
  ctl.update({...config,enabled:false});assert.equal(registered.size,0);
});
test('source-deck refresh safely clears stale matches even when a count input is empty',async()=>{
  const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel.js'),'utf8');
  const context=vm.createContext({crypto:require('node:crypto'),window:{},$:()=>({textContent:''}),DuelModel:model,
    api:async()=>({id:'deck',revision:'new',deck:{main:[1,1],extra:[],side:[]}})});
  vm.runInContext(source.slice(0,source.indexOf("$('#duel').addEventListener"))+'\nglobalThis.state=duelState();',context);
  Object.assign(context.state,{deck:{id:'deck',revision:'old'},count:NaN,result:{matches:['old']},plan:{id:'old'},stage:2,reached:5});
  assert.equal(await context.refreshDuelDeck(),false);
  assert.equal(context.state.stage,1);assert.equal(context.state.plan,null);assert.equal(context.state.result,null);
  assert.equal(context.state.hand.length,0);assert.equal(context.state.deck.revision,'new');
  context.api=async()=>{throw new Error('missing');};
  await assert.rejects(context.refreshDuelDeck(),/无法读取所选卡组/);
  assert.equal(context.state.deck,null);assert.equal(context.state.deckPage,'list');
});
