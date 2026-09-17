const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const model=require('../src/trainer/web/duel-auto-workspace.js');
const vm=require('node:vm');
test('automatic workspaces own filters, selection, graph and shortcut sessions',()=>{
  const input={context_id:'a',deck:{id:'automatic/a'},hand:[1,1,2,3,4]};
  const a=model.create(input),b=model.create({...input,context_id:'b'});
  a.hand[0]=7;a.planSort='largest';a.plan={id:'choice'};a.position={key:'main/step'};
  assert.deepEqual(b.hand,[1,1,2,3,4]);assert.equal(b.planSort,'shortest');assert.equal(b.plan,null);assert.equal(b.position,null);
  assert.notEqual(a.session,b.session);assert.deepEqual(input.hand,[1,1,2,3,4]);
});
test('automatic view/controller files use dedicated DOM, state and request boundaries',()=>{
  const read=name=>fs.readFileSync(path.join(__dirname,'../src/trainer/web',name),'utf8');
  for(const name of ['duel-auto-views.js','duel-auto-forecast.js']){
    const text=read(name);assert(!/\bduelState\(\)|\bduelUI\./.test(text),name);assert(!/id=["']duel-/.test(text),name);
  }
  const text=read('duel-auto-workspace.js');assert(text.includes('/api/automatic-duel/select'));assert(text.includes('data-workspace="automatic"'));
});

test('closing an automatic workspace detaches pending search callbacks without touching manual state',async()=>{
  const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel-auto-workspace.js'),'utf8');
  const forecastSource=fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel-auto-forecast.js'),'utf8');
  const forecast={generation:4},workspace={generation:2,forecast,context:{context_id:'owned'}};
  const state={plan:{id:'manual'},automatic:{workspace}},requests=[];
  const scope=vm.createContext({module:{exports:{}},duelState:()=>state,clearTimeout,structuredClone,
    $:()=>null,api:async(url,body)=>{requests.push({url,body});},autoDuelObservationDialog:{open:false}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel-forecast.js'),'utf8').split('const observationDialog=')[0],scope);
  vm.runInContext(source,scope);await vm.runInContext('disposeAutoDuel()',scope);
  assert.equal(state.automatic.workspace,null);assert.equal(workspace.forecast,null);assert.equal(forecast.generation,5);
  assert.equal(state.plan.id,'manual');assert.equal(requests[0].body.context_id,'owned');
  // Load function declarations only: no browser dialog is needed for a late repaint.
  vm.runInContext(forecastSource.split('const autoDuelObservationDialog=')[0],scope);
  assert.doesNotThrow(()=>vm.runInContext('autoPaintForecastResults()',scope));
});

test('leaving the automatic tutorial releases shortcuts before the module changes',async()=>{
  const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel-auto-workspace.js'),'utf8');
  const workspace={stage:6,enabled:true,session:'automatic-owned'},state={operationMode:'automatic',stage:6,automatic:{workspace}},payloads=[];
  const scope=vm.createContext({module:{exports:{}},duelState:()=>state,$:()=>null,duelStages:{plans:5,tutorial:6},moduleUI:{current:'duel'},
    duelUI:{bindings:{},shortcutQueue:Promise.resolve()},window:{trainerDesktop:{tutorialUpdate:async value=>{payloads.push(value);return value;}}}});
  vm.runInContext(source,scope);vm.runInContext('document={querySelector:()=>null}',scope);
  await vm.runInContext('syncAutoDuelShortcuts(true)',scope);
  assert.equal(payloads[0].active,false);assert.equal(workspace.enabled,true);
  await vm.runInContext('syncAutoDuelShortcuts()',scope);assert.equal(payloads[1].active,true);
});
