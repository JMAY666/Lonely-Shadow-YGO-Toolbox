'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Model=require('../src/trainer/web/duel-second.js');
const fs=require('node:fs'),vm=require('node:vm');

test('opening and current hand remain separate projections with duplicate instances',()=>{
  const doc={input:{opening:{cards:[1,2,2,3,4]}},current:{cards:[{id:'a',code:1,controller:0,location:16},{id:'b',code:2,controller:0,location:2},{id:'c',code:2,controller:0,location:2},{id:'d',code:3,controller:0,location:2},{id:'e',code:4,controller:0,location:2},{id:'f',code:5,controller:0,location:2}]}};
  assert.deepEqual(Model.hand(doc).map(c=>c.code),[2,2,3,4,5]);
  assert.deepEqual(doc.input.opening.cards,[1,2,2,3,4]);
});
test('expired, closed and interrupted windows cannot stay current',()=>{
  const doc={current:{window:{expires_ms:100}},status_reason:'',closed:false};
  assert(Model.validWindow(doc,99));assert(!Model.validWindow(doc,100));
  assert(!Model.validWindow({...doc,closed:true},99));
  assert(!Model.validWindow({...doc,status_reason:'断流'},99));
});
test('requests and response acceptance bind to record, round and revision',()=>{
  const doc={id:'one',revision:2,input:{round_id:'round'}};
  assert.deepEqual(Model.event(doc,'choice',{note:'实际不响应'},'event'),{id:'one',round_id:'round',revision:2,event_id:'event',kind:'choice',payload:{note:'实际不响应'}});
  assert(Model.accept(doc,{...doc,revision:3}));
  assert(!Model.accept(doc,{...doc,revision:1}));
  assert(!Model.accept(doc,{...doc,id:'two'}));
  assert(!Model.accept(doc,{...doc,input:{round_id:'next'}}));
});

test('second-player history does not start or select a residual first-player forecast',()=>{
  const source=fs.readFileSync(require.resolve('../src/trainer/web/duel.js'),'utf8');
  const render=source.slice(source.indexOf('function renderDuel()'),source.indexOf('function focusDuelPosition()'));
  for(const second of [true,false]){
    const calls={select:0,prepare:0,mount:0},nodes=new Map();
    const state={stage:5,reached:5,operationMode:'manual',automatic:{},secondOrder:second,result:{matches:[]},openingForecast:null};
    const context={duelStepResizeObserver:null,closeDuelPreview(){},duelState:()=>state,
      duelStages:{mode:0,function:1,deck:2,order:3,hand:4,plans:5,tutorial:6,complete:7},duelUI:{busy:false,message:''},
      $:key=>{if(!nodes.has(key))nodes.set(key,{dataset:{},contains:()=>false,querySelectorAll:()=>[],setAttribute(){}});return nodes.get(key);},
      secondActive:()=>second,secondWorkspace:()=>({readonly:true}),secondWorkspacePage:()=>'<record>',
      mountSecondDuel:()=>calls.mount++,syncDuelOrderWatch(){},selectForecastStage:()=>calls.select++,prepareDuelOpening:()=>calls.prepare++,
      duelMatchesPage:()=>'<first>',duelTell(){},bindPlanFavorites(){},pruneReviewCards(){},autoDuelState:()=>null};
    vm.runInNewContext(render+'\nrenderDuel();',context);
    assert.deepEqual(calls,second?{select:0,prepare:0,mount:1}:{select:1,prepare:1,mount:0});
    assert.equal(nodes.get('#duel-body').innerHTML,second?'<record>':'<first>');
  }
});

test('frozen card text cannot overwrite the shared current catalog on entry',async()=>{
  const code=1,live={id:code,name:'current catalog'},frozen={id:code,name:'older snapshot'};
  const cache=new Map([[code,live]]),state={operationMode:'manual',automatic:{},deck:{id:'deck',revision:'v1'},hand:[code],stage:4};
  const doc={id:'record',input:{round_id:'round',opening:{cards:[code]}},catalog:{1:frozen}};
  const context={crypto:require('node:crypto').webcrypto,clearTimeout(){},duelState:()=>state,
    api:async()=>doc,app:{cache},card:async()=>live,syncDuelShortcuts:async()=>{},duelStages:{plans:5,hand:4},
    duelReach:stage=>{state.stage=stage;},duelTell(){},renderDuel(){}};
  vm.runInNewContext(fs.readFileSync(require.resolve('../src/trainer/web/duel-second.js'),'utf8'),context);
  await context.startSecondDuel(false);
  assert.equal(cache.get(code).name,'current catalog');assert.equal(state.secondManual.doc.catalog[code].name,'older snapshot');
});
