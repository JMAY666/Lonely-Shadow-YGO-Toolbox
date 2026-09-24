'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const model=require('../src/trainer/web/duel-auto-follow.js');

test('browsing keeps actual progress and ignores responses for retired follow sessions',()=>{
  const run=model.create({id:'plan'});run.id='current';run.value={completed:[{key:'main/s1'}]};
  model.browse(run);assert.equal(run.viewLive,false);assert.equal(run.value.completed.length,1);
  assert.equal(model.accept(run,{id:'old'}),false);assert.equal(model.accept(run,{id:'current'}),true);
  run.stopped=true;assert.equal(model.accept(run,{id:'current'}),false);
});

test('live updates confirm temporary operation ranges while leaving manual view alone',()=>{
  const plan={temporary:true},run=model.create(plan);run.id='follow';run.viewLive=false;
  const workspace={plan,follow:run,context:{context_id:'ctx',round_id:'round'},forecast:{data:{}},position:{key:'main/s1'},stage:6};
  const progressLabel={textContent:''},panel={hidden:false};
  const scope=vm.createContext({module:{exports:{}},crypto,autoDuelState:()=>workspace,$:selector=>selector==='#auto-duel-follow'?panel:selector==='#auto-duel-forecast-progress'?progressLabel:null,
    reviewNodes:()=>[{kind:'step',forecast_absolute_end:2},{kind:'step',forecast_absolute_end:5}],
    duelStages:{tutorial:6},moduleUI:{current:'duel'},document:{querySelector:()=>null}});
  vm.runInContext(fs.readFileSync(require.resolve('../src/trainer/web/duel-auto-follow.js'),'utf8'),scope);
  scope.workspace=workspace;scope.run=run;
  scope.value={id:'follow',context_id:'ctx',round_id:'round',temporary_confirmed:6,next_key:'main/final',completed:[{},{}]};
  vm.runInContext('acceptAutoFollow(workspace,run,value)',scope);
  assert.equal(plan.confirmed,2);assert.equal(workspace.forecast.data.confirmed,6);
  assert.match(progressLabel.textContent,/已确认 2 步/);
  assert.equal(workspace.position.key,'main/s1');
  scope.value={...scope.value,round_id:'previous',temporary_confirmed:99};
  vm.runInContext('acceptAutoFollow(workspace,run,value)',scope);
  assert.equal(workspace.forecast.data.confirmed,6);
});

test('temporary arrow navigation during follow never calls plan-confirm',async()=>{
  const workspace={plan:{temporary:true},forecast:{},follow:{},position:{key:'main/s1'},graph:{}};
  let confirmations=0,browses=0;
  const scope=vm.createContext({autoDuelState:()=>workspace,autoFollowBrowse:()=>browses++,paintAutoDuelPosition:()=>{},
    DuelModel:{navigate:()=>({key:'main/s2'})},autoDuelDispatch:()=>confirmations++});
  const source=fs.readFileSync(require.resolve('../src/trainer/web/duel-auto-forecast.js'),'utf8').split('const autoDuelObservationDialog=')[0];
  vm.runInContext(source,scope);await vm.runInContext('autoAdvanceDuelForecast()',scope);
  assert.equal(confirmations,0);assert.equal(browses,1);assert.equal(workspace.position.key,'main/s2');
});

test('an action during polling is queued and manual confirmation keeps its original step key',async()=>{
  const plan={},run=model.create(plan);run.id='follow';run.viewLive=false;run.value={next_key:'main/first'};
  const workspace={plan,follow:run,context:{context_id:'ctx',round_id:'round'}};const calls=[];
  let resolveFirst;
  const value={id:'follow',context_id:'ctx',round_id:'round',next_key:'main/second'};
  const scope=vm.createContext({module:{exports:{}},crypto,autoDuelState:()=>workspace,$:()=>null,clearTimeout:()=>{},setTimeout:()=>1,
    api:async(url,body)=>{calls.push(body);if(calls.length===1)return new Promise(r=>resolveFirst=r);return value;}});
  vm.runInContext(fs.readFileSync(require.resolve('../src/trainer/web/duel-auto-follow.js'),'utf8'),scope);
  scope.workspace=workspace;scope.run=run;
  const polling=vm.runInContext('pollAutoFollow(workspace,run)',scope);
  await vm.runInContext("pollAutoFollow(workspace,run,'manual')",scope);
  resolveFirst(value);await polling;await new Promise(setImmediate);
  assert.equal(calls.length,2);assert.equal(calls[1].action,'manual');assert.equal(calls[1].key,'main/first');
});
