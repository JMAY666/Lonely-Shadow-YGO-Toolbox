const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const DuelModel=require('../src/trainer/web/duel-model.js');
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
});
