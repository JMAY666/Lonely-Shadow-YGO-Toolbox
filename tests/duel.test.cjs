const test=require('node:test'),assert=require('node:assert/strict');
const model=require('../src/trainer/web/duel-model.js');
const {normalize,defaults,createController}=require('../desktop/tutorial-shortcuts.cjs');
const TutorialBindings=require('../src/trainer/web/tutorial-bindings.js');
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
  registered.get('RIGHT')();assert.deepEqual(sent,[{action:'forward',session:'a'}]);
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
  const context=vm.createContext({crypto:require('node:crypto'),window:{},$:()=>({textContent:''}),DuelModel:model,TutorialBindings,
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

test('module Step links govern navigation instead of adjacency in the display array',()=>{
  const graph=model.graph([{id:'main',label:'主线',model:{steps:[{id:'s1',number:1},{id:'s2',number:2}],
    stepLinks:[{from:'initial',to:'s1',module_path:['1','2']},{from:'s1',to:'final',module_path:['2','4']}]}}]);
  assert.equal(model.navigate(graph,{key:'main/s1',choice:0},'forward').key,'main/final');
  assert(!graph.edges.some(e=>e.to==='main/s2'));
  assert.deepEqual(graph.edges.find(e=>e.from==='main/s1').module_path,['2','4']);
});

test('all foreground actions resolve the same saved keys as the background controller',()=>{
  const sent=[],registered=new Map(),bindings=normalize({back:'left',forward:'Shift+Control+f9',up:'up',down:'down',end:'Alt+Enter'});
  const ctl=createController({registry:{register(key,fn){registered.set(key,fn);return true;},unregister(key){registered.delete(key);}},send:value=>sent.push(value.action),isFocused:()=>false});
  ctl.update({active:true,enabled:true,suspended:false,session:'shared',bindings});
  for(const [action,event] of Object.entries({back:{key:'ArrowLeft'},forward:{key:'F9',ctrlKey:true,shiftKey:true},up:{key:'ArrowUp'},down:{key:'ArrowDown'},end:{key:'Enter',altKey:true}})) {
    assert.equal(TutorialBindings.actionFor(bindings,event),action);
    registered.get(TutorialBindings.accelerator(event))();assert.equal(sent.at(-1),action);
  }
  assert.equal(TutorialBindings.actionFor(bindings,{key:'ArrowRight'}),undefined);
  assert.equal(TutorialBindings.actionFor({...bindings,up:''},{key:'ArrowUp'}),undefined);
  assert.equal(TutorialBindings.normalize,normalize);
});

function previewFixture() {
  const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel.js'),'utf8');
  let time=0,id=0,opened=[];const timers=new Map();
  const panel={hidden:true,hovered:false,contains:()=>false,matches(){return this.hovered;}};
  const context=vm.createContext({TutorialBindings,crypto:require('node:crypto'),window:{},document:{activeElement:null,querySelector:()=>null},$:()=>panel,reviewUI:{},closeReviewDetail(){},
    clearTimeout:id=>timers.delete(id),setTimeout:(fn,delay)=>{timers.set(++id,{fn,due:time+delay});return id;}});
  vm.runInContext(source.slice(0,source.indexOf("$('#duel').addEventListener"))+'\nglobalThis.ui=duelUI;',context);
  context.paintDuelPreview=()=>{panel.hidden=false;opened.push(context.ui.previewId);};
  const anchor=key=>({dataset:{duelNode:key},isConnected:true,hovered:true,getBoundingClientRect:()=>({left:1,top:1}),matches(){return this.hovered;}});
  const advance=ms=>{time+=ms;for(const [id,timer] of [...timers])if(timer.due<=time){timers.delete(id);timer.fn();}};
  return {context,panel,anchor,advance,timers,opened};
}

test('ending a manual tutorial succeeds without a native session and stops only its own bound session',async()=>{
  for(const active of [null,{id:'unrelated'},{id:'bound'}]) {
    const {context:c}=previewFixture(),calls=[],state={modularSession:active?'bound':undefined};
    c.app={active};c.ui.state=state;c.api=async(path,body)=>calls.push({path,body});
    c.syncDuelShortcuts=async()=>{};c.renderDuel=()=>{};
    await c.endDuel();assert.equal(state.stage,6);assert.equal(state.ended,true);
    assert.equal(calls.length,active?.id==='bound'?2:0);
  }
});

test('step hover has one fixed delay; descendant transitions and old close timers cannot restart or hide it',()=>{
  const r=previewFixture(),a=r.anchor('a'),b=r.anchor('b'),c=r.context;
  c.showDuelPreview(a);r.advance(160);c.showDuelPreview(a);r.advance(119);assert(r.panel.hidden);
  r.advance(1);assert.deepEqual(r.opened,['a']);
  a.hovered=false;c.scheduleDuelPreviewClose();c.scheduleDuelPreviewClose();assert.equal(r.timers.size,1);
  c.showDuelPreview(b);r.advance(280);assert.deepEqual(r.opened,['a','b']);assert(!r.panel.hidden);
  r.advance(500);assert(!r.panel.hidden);
  b.hovered=false;c.scheduleDuelPreviewClose();r.panel.hovered=true;r.advance(220);assert(!r.panel.hidden);
  r.panel.hovered=false;c.scheduleDuelPreviewClose();r.advance(220);assert(r.panel.hidden);
});

test('canceling and reentering a new step never leaves the previous step content visible',()=>{
  const r=previewFixture(),a=r.anchor('a'),b=r.anchor('b'),c=r.context;
  c.showDuelPreview(a);r.advance(280);assert(!r.panel.hidden);
  a.hovered=false;c.showDuelPreview(b);assert(r.panel.hidden);
  r.advance(100);b.hovered=false;c.scheduleDuelPreviewClose();
  r.advance(100);b.hovered=true;c.showDuelPreview(b);r.advance(279);assert(r.panel.hidden);
  r.advance(1);assert.equal(r.opened.at(-1),'b');assert(!r.panel.hidden);
});

test('hover cancels detached targets and explicit close suppresses the current trigger until exit',()=>{
  const r=previewFixture(),a=r.anchor('a'),c=r.context;
  c.showDuelPreview(a);a.isConnected=false;r.advance(280);assert.deepEqual(r.opened,[]);
  c.closeDuelPreview();a.isConnected=true;c.showDuelPreview(a);r.advance(280);assert(!r.panel.hidden);
  c.closeDuelPreview(true);c.showDuelPreview(a);r.advance(1000);assert(r.panel.hidden);
  c.ui.previewSuppressed=null;c.showDuelPreview(a);r.advance(280);assert(!r.panel.hidden);
});

test('long step previews stay outside the graph and leave the footer clickable',()=>{
  const {context:c}=previewFixture();
  const fixture={anchor:{left:550},graph:{top:225,bottom:635},width:720,height:684,viewport:{width:1440,height:900},footer:{left:1190,right:1414,top:848}};
  const below=c.duelPreviewPlacement(fixture);
  assert(below.top>fixture.graph.bottom);assert(below.top+below.height<fixture.footer.top);
  const above=c.duelPreviewPlacement({...fixture,graph:{top:225,bottom:1000}});
  assert(above.top>=70);assert(above.top+above.height<225);
  assert.equal(c.duelPreviewPlacement({...fixture,graph:{top:40,bottom:1000}}),null);
  const tile={left:120,right:380,top:235,bottom:670};
  const beside=c.duelPreviewPlacement({...fixture,anchor:tile,graph:tile,beside:true,footer:null});
  assert(beside.left>=tile.right);assert.equal(beside.height,684);
});

test('pointer down cancels a pending preview and graph movement cannot rearm it until the mouse moves',()=>{
  const r=previewFixture(),c=r.context,a=r.anchor('a');
  c.showDuelPreview(a);r.advance(150);c.pauseDuelPreviewForClick({clientX:300,clientY:400});
  r.advance(500);assert(r.panel.hidden);
  c.showDuelPreview(a);r.advance(500);assert(r.panel.hidden);
  c.moduleUI={current:'duel'};
  const event={clientX:300,clientY:400,buttons:0,target:{closest:()=>a}};
  c.resumeDuelPreviewAfterMove(event);r.advance(500);assert(r.panel.hidden);
  c.resumeDuelPreviewAfterMove({...event,clientX:340,buttons:1});r.advance(500);assert(r.panel.hidden);
  c.resumeDuelPreviewAfterMove({...event,clientX:340});r.advance(280);assert(!r.panel.hidden);
});

test('final notes retain full text and instance ownership without revealing a random card through effect text',()=>{
  const {context:c}=previewFixture(),long='保存的终场说明。'.repeat(60);
  c.structuredClone=structuredClone;
  c.escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  c.reviewRandomDraw=card=>card.instance_id===2;
  const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/review.js'),'utf8');
  vm.runInContext(source.slice(source.indexOf('function reviewFallback'),source.indexOf('function mountReview')),c);
  vm.runInContext(source.slice(source.indexOf('function reviewEffectParts'),source.indexOf('function reviewMarkEditor')),c);
  const plan={catalog:{10:{desc:'①：可见的完整效果。'},11:{desc:'①：随机卡牌的隐藏身份。'}},requirements:{final:{notes:long}},
    annotations:{nodes:{final:{notes:long}},cards:{1:'这张卡的说明',2:'抽牌的用户备注'},final_marks:{1:{marked:true,effects:{0:{note:'完整效果备注。'.repeat(60)}}},2:{marked:true,effects:{0:{note:'保留随机卡备注'}}}}},
    final_state:{cards:[{instance_id:1,code:10,name:'已知卡牌',location:16},{instance_id:2,code:11,name:'隐藏卡牌名称',location:2}]}};
  const before=JSON.stringify(plan),compact=c.duelFinalNotes(plan),detail=c.duelFinalNotes(plan,true);
  assert(compact.includes(long));assert.equal(compact.split(long).length,2);assert(compact.includes('完整效果备注。'.repeat(60)));
  assert(compact.includes('已知卡牌 · 墓地'));assert(compact.includes('抽牌的用户备注'));assert(!compact.includes('可见的完整效果。'));
  assert(detail.includes('可见的完整效果。'));assert(!detail.includes('随机卡牌的隐藏身份'));assert(!detail.includes('隐藏卡牌名称'));
  assert.equal(JSON.stringify(plan),before);
});

test('held shortcuts repeat after a delay, stop on release and never leak across sessions',()=>{
  let time=0,focused=false,listener,stops=0;const sent=[],registered=new Map();
  const ctl=createController({registry:{register(k,f){registered.set(k,f);return true;},unregister(k){registered.delete(k);}},
    send:e=>sent.push(e),isFocused:()=>focused,now:()=>time,watchKeys:(_bindings,receive)=>{listener=receive;return ()=>stops++;}});
  const config={active:true,enabled:true,suspended:false,session:'first',bindings:defaults};
  ctl.update(config);ctl.invoke('forward');ctl.invoke('forward');assert.equal(sent.length,1);
  time=349;listener(['forward']);assert.equal(sent.length,1);
  time=350;listener(['forward']);assert.equal(sent.length,2);
  time=449;listener(['forward']);assert.equal(sent.length,2);
  time=450;listener(['forward']);assert.equal(sent.length,3);
  listener([]);time=900;listener(['forward']);assert.equal(sent.length,3);
  ctl.invoke('forward');assert.equal(sent.length,4);
  ctl.update({...config,session:'second'});time=1400;listener(['forward']);assert.equal(sent.length,4);
  ctl.invoke('back');focused=true;time=2000;listener(['back']);assert.equal(sent.length,5);
  ctl.sync();assert.equal(registered.size,0);assert(stops>=2);
});
