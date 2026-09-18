const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const DuelModel=require('../src/trainer/web/duel-model.js');
test('forecast pictures explicitly revealed cards even when they do not move',()=>{
  const c=setup(),shown={instance_id:7,code:123,name:'已展示的额外怪兽',controller:0,location:64,sequence:0};
  const step={decision:{selection:[]},revealed_cards:[shown],before:{cards:[shown]},state:{cards:[shown]}};
  const operations=c.forecastOperations([step]);
  assert.equal(operations.length,1);assert.equal(operations[0].message,31);assert.equal(operations[0].cards[0].name,shown.name);
});
function setup() {
  const el={addEventListener(){}};
  const c=vm.createContext({structuredClone,Map,Set,flow:{draft:null},app:{},$:()=>el,document:{addEventListener(){},querySelectorAll:()=>[]},
    escape:String,zoneNames:{},DuelModel,duelState:()=>({hand:[1,2]}),duelName:code=>'card '+code});
  for(const file of ['activation.js','review.js','duel-forecast.js']) {
    const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web',file),'utf8');
    vm.runInContext(file==='duel-forecast.js'?source.slice(0,source.indexOf('const observationDialog=')):source,c);
  }
  return c;
}
const card=(id,code,location,extra={})=>({instance_id:id,code,name:'card '+code,controller:0,location,sequence:0,position:1,identity_known:true,...extra});
test('plan ranking uses marked finals only, balances scores and never reorders source arrays',()=>{
  const plan=(id,steps,cards,effects=0)=>({id,steps,final_state:{cards:Array.from({length:12},(_,i)=>card(i,10+i,4))},annotations:{final_marks:Object.fromEntries(Array.from({length:cards},(_,i)=>[i,{marked:true,effects:i===0?Object.fromEntries(Array.from({length:effects},(_,j)=>[j,{note:''}])):{}}]))}});
  const plans=[plan('long',9,3),plan('middle',3,2),plan('short',1,1)];
  const before=JSON.stringify(plans);
  for(const [preference,expected] of [['shortest','short'],['largest','long'],['balanced','middle']])assert.equal(DuelModel.rankPlans(plans,preference,p=>p.steps)[0].plan.id,expected);
  assert.equal(JSON.stringify(plans),before);
  const unknown=plan('unmarked',1,0);unknown.requirements={final:{cards:unknown.final_state.cards}};
  assert.equal(DuelModel.markedFinalCards(unknown).length,0,'Unmarked complete state is never an effective terminal');
});
test('forecast compact summon reuses material pictures, arrows and position maps',()=>{
  const c=setup(),material=card(1,10,4),extra=card(2,11,64),summoned={...extra,location:4,sequence:5,summon_info:0x4c000000,material_instance_ids:[1]};
  const step={decision:{selection:[{kind:'special',card:extra}]},bindings:[{card:extra}],before:{cards:[material,extra]},state:{cards:[{...material,location:16},summoned]},source:{name:'source'}};
  const node={id:'step',number:2,forecast_step:step,state:step.state};
  const report={temporary:true,confirmed:0,review:{nodes:[node]},catalog:{11:{type:0x4000001}},annotations:{}};
  const html=c.renderForecastStep(node,report);
  assert.match(html,/连接召唤/);assert.match(html,/compact-summon/);assert.match(html,/chain-arrow/);assert.match(html,/location-icon/);
  assert.match(html,/pics\/10.jpg/);assert.match(html,/pics\/11.jpg/);assert.match(html,/操作详情与来源/);
  assert.equal(c.forecastOperations([step]).length,1,'Material grave moves are not repeated as independent effects');
});
test('forecast effect uses actual search and cost deltas with full prose tucked into details',()=>{
  const c=setup(),actor=card(1,10,4),cost=card(2,12,2),target=card(3,13,2);
  const step={decision:{selection:[{kind:'activate',card:actor}]},bindings:[{card:actor}],effect_label:{number:2,text:'full effect text'},
    before:{cards:[actor,cost,{code:13,controller:0,location:1}]},state:{cards:[actor,{...cost,location:16,reason:0x80},target]},source:{name:'source'}};
  const node={id:'step',number:2,forecast_step:step,state:step.state};
  const html=c.renderForecastStep(node,{temporary:true,confirmed:0,review:{nodes:[node]},catalog:{},annotations:{}});
  assert.match(html,/发动效果 2/);assert.match(html,/Cost · 送墓/);assert.match(html,/检索/);assert.match(html,/我方主卡组/);assert.match(html,/chain-arrow/);
});
test('temporary final shows only mapped marks, with grave notes and no unrelated cards',()=>{
  const c=setup(),initial={cards:[card(1,10,2)]},terminal={cards:[card(1,10,16),card(2,20,4),card(3,30,16)]};
  const candidate={steps:[],terminal,terminal_targets:[{card:terminal.cards[0],mark:{marked:true,effects:{}},note:'useful grave'}],terminal_mark_count:1,terminal_mark_status:'complete'};
  const report=c.temporaryDuelPlan({route:'r',catalog:{},initial,prefix:[]},candidate);
  const html=c.renderForecastTerminal(report.review.nodes.at(-1),report);
  assert.match(html,/pics\/10.jpg/);assert.match(html,/useful grave/);assert.doesNotMatch(html,/pics\/(20|30).jpg/);
  report.annotations.final_marks={};assert.match(c.renderForecastTerminal(report.review.nodes.at(-1),report),/尚无已匹配/);
});
test('leading response choices join the next operation and frozen prefix labels stay intact',()=>{
  const c=setup(),state={cards:[card(1,10,4)]};
  const prefix={decision:{selection:[{kind:'summon'}]},state,before:{cards:[]}};
  const pass={decision:{selection:[{kind:'pass'}]},state,before:state,automatic:true};
  const set={decision:{selection:[{kind:'spell_set'}]},state,before:state};
  const plan=c.temporaryDuelPlan({route:'r',catalog:{},initial:state,prefix:[prefix],prefix_layout:[{start:0,end:0,number:9,name:'保留名称',notes:'保留批注'}]},
    {steps:[pass,set],terminal:state});
  const nodes=plan.review.nodes.filter(n=>n.kind==='step');
  assert.equal(nodes.length,2);assert.equal(plan.confirmed,1);
  assert.equal(nodes[1].forecast_index,0);assert.equal(nodes[1].forecast_end,1);
  assert.equal(plan.annotations.nodes[nodes[0].id].name,'保留名称');assert.equal(plan.annotations.nodes[nodes[0].id].notes,'保留批注');
});
test('field-card activation uses the shared activation label and one placed card picture',()=>{
  const c=setup(),actor=card(1,10,2),placed={...actor,location:8,sequence:5};
  const step={decision:{selection:[{kind:'activate',card:actor}]},bindings:[{card:actor,effect:{effect_type:0x1a}}],before:{cards:[actor]},state:{cards:[placed]},source:{name:'source'}};
  const node={id:'step',number:2,forecast_step:step,state:step.state};
  const html=c.renderForecastStep(node,{temporary:true,confirmed:0,review:{nodes:[node]},catalog:{10:{type:0x80002}},annotations:{}});
  assert.match(html,/发动场地魔法卡/);assert.equal((html.match(/pics\/10.jpg/g)||[]).length,1);assert.match(html,/location-icon/);
});

test('a single partial candidate is clearly distinguished from one fully searched route',()=>{
  const c=setup();
  const limited=c.forecastSearchNotice({limited:true,complete:false,candidates:[{}]});
  assert.match(limited,/搜索尚未完成/);assert.match(limited,/不能据此判断其他偏好/);
  const complete=c.forecastSearchNotice({limited:false,complete:true,candidates:[{}]});
  assert.match(complete,/只找到一条/);assert.match(complete,/各偏好可能推荐同一条/);
  assert.doesNotMatch(complete,/搜索尚未完成/);
  const empty=c.forecastSearchNotice({limited:false,complete:true,candidates:[]});
  assert.match(empty,/未找到可用路线/);assert.doesNotMatch(empty,/同时占优/);
});

function navigationFixture({temporary=true,anchor=null,confirmed=2,stage='plans'}={}) {
  const requests=[],stages={plans:6,tutorial:7};
  const state={deck:{id:'deck',revision:'v1'},hand:[1,2,3],count:3,stage:stages[stage],reached:7,
    plan:{id:'source',temporary,confirmed},forecast:{id:'old-session',generation:0,anchor,selected:['source'],
      sources:[{id:'source'}],preference:'largest',precise:true,goal:[99],data:{confirmed}},
    graph:{nodes:[{key:'main/step',route:'main'}]},position:{key:'main/step'}};
  const c=vm.createContext({structuredClone,clearTimeout(){},setTimeout(){return 1;},duelState:()=>state,duelStages:stages,renderDuel(){},syncDuelShortcuts:async()=>{},
    duelNodeSource:()=>({node:{id:'step',kind:'step',number:9}}),
    api:async()=>({sources:[{id:'source',status:'ready'}]}),
    modularDispatch:async(consumer,intent,body)=>{requests.push({consumer,intent,...body});return {job:'prepared',version:'v1',status:'ready',id:body.id||'new-session',data:{id:body.id||'new-session',confirmed:0,result:{preference:body.preference,candidates:[]}}};}});
  const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel-forecast.js'),'utf8');
  vm.runInContext(source.slice(0,source.indexOf('const observationDialog=')),c);
  vm.runInContext('paintForecastResults=()=>{};',c);
  return {c,state,requests,stages};
}

test('opening preparation preserves the previous tutorial and uses a separate origin',async()=>{
  for(const anchor of [null,{plan:'source',node:'step',number:9}]){
    const {c,state,requests,stages}=navigationFixture({anchor});
    await c.launchModularFromDuel();
    assert(!requests.some(r=>r.intent==='plan-close'));
    const request=requests.find(r=>r.intent==='plan-prepare');assert.equal(request.id,undefined);assert.equal(request.anchor,null);
    assert.equal(request.preference,'largest');assert.equal(request.precise,true);assert.deepEqual([...request.goal],[99]);
    assert.equal(state.forecast.id,'new-session');assert.equal(state.plan.confirmed,2);assert.equal(state.tutorialForecast.id,'old-session');
    assert.match(c.forecastStartText(state),/起手/);
  }
});

test('opening and refresh request only the confirmed deck library and drop ineligible selections',async()=>{
  const {c,state,requests}=navigationFixture();const urls=[];
  c.api=async url=>{urls.push(url);return {sources:[{id:'source',status:'ready'}]};};
  await c.prepareDuelOpening(state);
  assert(urls.every(url=>url==='/api/modular/library?deck_id=deck&revision=v1'));
  const f=state.openingForecast;f.selected.push('unrelated');
  await c.prepareForecast(state,f,{refresh:true});
  assert.deepEqual([...f.selected],['source']);
  assert(requests.filter(r=>r.intent==='plan-prepare').every(r=>!r.sources.includes('unrelated')));
});

test('an empty scoped library has a clear message and never requests a whole-library forecast',async()=>{
  const {c,state,requests}=navigationFixture();
  c.api=async()=>({sources:[],reason:'没有与当前卡组主、副 Tag 匹配的可用展开来源'});
  await c.prepareDuelOpening(state);
  assert.equal(state.openingForecast.busy,false);
  assert.match(state.openingForecast.error,/Tag/);
  assert(!requests.some(r=>r.intent==='plan-prepare'));
});

test('tutorial continuation keeps its session and confirmed prefix',async()=>{
  const {c,state,requests}=navigationFixture({stage:'tutorial'});
  await c.launchModularFromDuel();
  assert.equal(requests.filter(r=>r.intent==='plan-prepare').length,1);assert.equal(requests[0].id,'old-session');assert.equal(state.plan.confirmed,2);
  assert.match(c.forecastStartText(state),/已确认操作/);
});

test('browsing the plan list hides continuation controls without discarding the tutorial',()=>{
  const {c,state}=navigationFixture();const forecast=state.forecast,plan=state.plan;
  c.renderDuelForecast(); // No DOM is needed: the continuation panel is not mounted.
  assert.equal(state.forecast,forecast);assert.equal(state.plan,plan);
});

test('ready opening clicks and preference switches do not restart preparation or follow shortcut sessions',async()=>{
  const {c,state,requests}=navigationFixture();state.session='duel-owner';
  await c.launchModularFromDuel();const first=state.forecast;
  state.session='new-shortcut-registration';
  await c.launchModularFromDuel();first.preference='cheapest';await c.searchDuelBrain();
  assert.equal(requests.filter(r=>r.intent==='plan-prepare').length,1);
  assert(requests.filter(r=>r.intent==='plan-poll').every(r=>r.session==='duel-owner'));
  assert.equal(state.plan.confirmed,2);assert.equal(state.forecast,first);
});

test('an explicit temporary preference survives preparation of a separate opening',async()=>{
  const {c,state}=navigationFixture();state.session='duel-owner';state.planSort='shortest';
  state.forecast.preference='cheapest';state.forecast.preferenceManual=true;
  await c.launchModularFromDuel();
  assert.equal(state.forecast.preference,'cheapest');assert.equal(state.forecast.preferenceManual,true);
});

test('changing settings during the first search does not reuse its cancelled startup engine',async()=>{
  const {c,state,requests}=navigationFixture();
  const f=state.forecast;f.slot='opening';f.busy=true;f.job='running';f.inputKey='previous';f.goal=[44];
  await c.searchDuelBrain();
  assert.equal(requests.find(r=>r.intent==='plan-prepare').id,undefined);
  assert.equal(state.plan.confirmed,2);
});

test('an unfinished ordinary-Step reconstruction restarts its anchor while an adopted prefix keeps its engine',async()=>{
  for(const adopted of [false,true]){
    const {c,state,requests}=navigationFixture({stage:'tutorial',anchor:{plan:'source',node:'step',number:9}});
    const f=state.forecast;f.slot='continuation';f.busy=true;f.job='running';f.inputKey='previous';f.adopted=adopted;
    await c.searchDuelBrain();const request=requests.find(r=>r.intent==='plan-prepare');
    assert.equal(request.id,adopted?'old-session':undefined);
    if(!adopted)assert.equal(request.anchor.node,'step');
    assert.equal(state.plan.confirmed,2);
  }
});

test('failed new settings cannot resurrect a previous job by switching preferences',async()=>{
  const {c,state,requests}=navigationFixture();const f=state.forecast;
  f.slot='opening';f.job='old-job';f.inputKey='old-input';f.selected=[];
  c.modularDispatch=async(consumer,intent,body)=>{requests.push({intent,...body});if(intent==='plan-prepare')throw Error('请选择来源');return {};};
  await c.searchDuelBrain();assert.equal(f.job,null);assert.equal(f.data,null);assert.match(f.error,/请选择/);
  f.preference='cheapest';await c.searchDuelBrain();
  assert(!requests.some(r=>r.intent==='plan-poll'));assert(requests.some(r=>r.intent==='plan-cancel'&&r.job==='old-job'));
});

test('late preparation after input replacement cannot populate the new forecast',async()=>{
  const {c,state,requests}=navigationFixture();state.session='duel-owner';let resolve;
  c.modularDispatch=async(consumer,intent,body)=>{
    if(intent==='plan-prepare')return new Promise(done=>{resolve=done;});
    requests.push({intent,...body});return {};
  };
  const waiting=c.prepareDuelOpening(state);await new Promise(setImmediate);
  const old=state.openingForecast;c.dropDuelForecast(state);
  state.hand=[9,8,7];state.planningSession='new-round';state.forecast=state.openingForecast={generation:0};
  resolve({job:'late',version:'old'});await waiting;
  assert.equal(state.forecast.data,undefined);assert.equal(old.released,true);
  assert(requests.some(r=>r.intent==='plan-cancel'&&r.job==='late'&&r.session==='duel-owner'));
});

test('a new ordinary tutorial Step replaces the previous anchor',async()=>{
  const {c,state,requests}=navigationFixture({stage:'tutorial',temporary:false,anchor:{plan:'source',node:'old-step',number:8}});
  await c.launchModularFromDuel();
  const request=requests.find(r=>r.intent==='plan-prepare'&&r.slot==='continuation');assert.equal(request.id,undefined);assert.equal(request.anchor.node,'step');
  assert.match(c.forecastStartText(state),/Step 9/);
  const count=requests.filter(r=>r.intent==='plan-prepare').length;
  state.forecast.preference='balanced';await c.searchDuelBrain();
  assert.equal(requests.filter(r=>r.intent==='plan-prepare').length,count,'Assigning the native session ID does not change the continuation origin');
});

test('a late confirmation cannot navigate or mutate a replacement opening forecast',async()=>{
  const {c,state}=navigationFixture({stage:'tutorial',confirmed:0});let resolve;
  c.modularDispatch=()=>new Promise(done=>{resolve=done;});
  c.duelNodeSource=()=>({node:{kind:'step',number:2,forecast_index:0,forecast_end:0}});
  const previousPlan=state.plan,waiting=c.advanceDuelForecast();
  state.forecast={id:'replacement'};state.plan=null;state.graph=null;state.position=null;
  resolve({confirmed:1});await waiting;
  assert.equal(previousPlan.confirmed,0);assert.equal(state.plan,null);assert.equal(state.position,null);
});
