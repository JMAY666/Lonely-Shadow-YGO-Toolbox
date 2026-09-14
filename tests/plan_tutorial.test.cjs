const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
function setup() {
  const el={addEventListener(){}};
  const context=vm.createContext({Map,structuredClone,flow:{draft:null},app:{},$:()=>el,
    document:{addEventListener(){},querySelectorAll:()=>[]},escape:String,eventSummary:e=>e.result||e.type||'',zoneNames:{}});
  for(const file of ['review.js','plan-tutorial.js'])vm.runInContext(readFileSync(path.join(__dirname,'../src/trainer/web',file),'utf8'),context);
  return vm.runInContext('({buildPlanTutorial,layoutPlanTutorial,renderPlanTutorialSvg,tutorialWrap,reviewUI})',context);
}
function fixture() {
  const a={instance_id:1,code:10,name:'起手怪兽',controller:0,location:4,sequence:0};
  const b={instance_id:2,code:11,name:'检索魔法',controller:0,location:2};
  const grave={...a,instance_id:3,location:16};
  const cost={id:'3:0',message:100,cards:[],result:'支付 1000 LP'};
  const result={id:'4:0',message:50,cards:[b],origin:{location:1,controller:0},destination:{location:2,controller:0}};
  const action={id:'2:0',kind:'effect',effect_number:1,status:'resolved',cards:[a],costs:[cost],targets:[grave],results:[result],effect_text:'①：不可当成已发生结果的效果原文。'};
  return {id:'test-plan',name:'路线 <测试>',catalog:{10:{desc:action.effect_text}},
    events:[cost,result],actions:[action],initial_hand:[a],initial_hand_ref:'1:0',
    final_state:{cards:[a,grave,b]},requirements:{opening:[{name:'起手怪兽',code:10,count:1},{name:'任意手牌',code:null,count:1}],main:[{name:'不应列出的使用资源',count:9}],random:[]},
    annotations:{cards:{},nodes:{'step:2:0':{name:'检索准备',notes:'用户备注 & <保留>'}},final_marks:{1:{marked:true,effects:{0:{note:'无效一次'}}},3:{marked:true,effects:{}}}},
    review:{complete:true,nodes:[{id:'initial',kind:'initial',number:1,action_ids:[]},{id:'step:2:0',kind:'step',number:2,state_ref:5,action_ids:['2:0']},{id:'final',kind:'final',number:3,action_ids:[],state:{cards:[a,grave,b]}}]}};
}
test('tutorial reads the frozen plan only and preserves costs, targets, notes and final marks without full effect text or resources',()=>{
  const r=setup(),plan=fixture(),before=JSON.stringify(plan);
  r.reviewUI.report={annotations:{nodes:{'step:2:0':{name:'无关草稿'}}}};
  const model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  for(const label of ['起手条件','终场展示','任意手牌 ×1','发动①','Cost · 支付 1000 LP','对象 ·','检索 ·','无效一次','我方墓地','Step 2'])assert(svg.includes(label),label);
  for(const label of ['效果原文','展开使用资源','不应列出的使用资源','无关草稿','我方 1 号主怪兽区'])assert(!svg.includes(label),label);
  assert.equal(model.finalCards.length,2);assert.equal(model.steps.length,1);
  assert.match(svg,/路线 &lt;测试&gt;/);assert.match(svg,/用户备注 &amp; &lt;保留&gt;/);
  assert.match(svg,/fill="#b33737"/);assert.equal(JSON.stringify(plan),before);
});
test('negated and unrecorded outcomes and random dependencies remain explicit',()=>{
  const r=setup(),plan=fixture();plan.actions[0].status='negated';plan.actions[0].results=[];
  plan.requirements.random=[{name:'需要随机命中',count:1}];
  const svg=r.renderPlanTutorialSvg(r.buildPlanTutorial(plan));
  assert.match(svg,/发动被无效/);assert.match(svg,/处理结果未记录/);assert.match(svg,/Cost/);assert.match(svg,/随机依赖：需要随机命中 ×1/);
  assert(!svg.includes('检索 ·'));
});
test('random drawn instance is masked while identical searched copy and actual opening remain distinguishable',()=>{
  const r=setup(),plan=fixture(),drawn={instance_id:8,code:99,name:'抽中身份',controller:0,location:2};
  plan.events.push({id:'7:0',message:90,cards:[drawn]});
  plan.actions.push({id:'7:0',kind:'action',cards:[drawn],summary:'抽中身份'});
  plan.review.nodes.splice(2,0,{id:'draw',kind:'step',number:3,state_ref:7,action_ids:['7:0']});
  plan.review.nodes.at(-1).state.cards.push(drawn);plan.annotations.final_marks[8]={marked:true,effects:{}};
  const model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  assert(!svg.includes('抽中身份'));assert(!svg.includes('/pics/99.jpg'));
  assert.match(svg,/随机抽牌/);assert.match(svg,/抽 1 张卡（随机）/);assert.match(svg,/检索魔法/);
});
test('serpentine rows retain chronological order, distinct arrows and readable bounds for short and long routes',()=>{
  const r=setup();
  for(const count of [0,1,2,3,4,8,16,25,50]) {
    const plan=fixture(),model=r.buildPlanTutorial(plan),step=model.steps[0];
    model.steps=Array.from({length:count},(_,i)=>({...step,id:'step:'+i,number:i+2}));
    const layout=r.layoutPlanTutorial(model),svg=r.renderPlanTutorialSvg(model,layout);
    assert.equal(layout.boxes.length,count);assert.equal((svg.match(/class="tutorial-connector"/g)||[]).length,Math.max(0,count-1));
    for(let i=0;i<count;i++) {
      const box=layout.boxes[i],row=Math.floor(i/layout.columns);
      assert.equal(box.number,i+2);assert(box.x>=layout.pad&&box.x+box.width<=layout.width-layout.pad+.1);
      assert(box.y+box.height<layout.height-40);assert(box.header+box.lines.length*21<box.height);
      if(i%layout.columns&&i>0)assert.equal(box.x>layout.boxes[i-1].x,row%2===0);
    }
    if(count===16)assert(layout.height/layout.width<2.2,'16 steps should fold into a compact sheet');
  }
});
test('only explicit cleanup is omitted, notes and uncertain events survive, and old plans never invent state',()=>{
  const r=setup(),plan=fixture();
  const cleanup={id:'6:0',message:50,origin:{location:128},destination:{location:16},reason:1024};
  plan.events.push(cleanup);plan.actions.push({id:'6:0',kind:'action',evidence_refs:['6:0'],summary:'规则素材清理'});
  plan.review.nodes.splice(2,0,{id:'cleanup',kind:'step',number:3,action_ids:['6:0']});
  assert.equal(r.buildPlanTutorial(plan).steps.length,1);
  cleanup.reason=64;assert.equal(r.buildPlanTutorial(plan).steps.length,2);
  delete plan.review;delete plan.requirements;
  const model=r.buildPlanTutorial(plan);assert.equal(model.steps.length,2);assert.match(model.warnings.join(''),/旧方案/);
  assert.equal(model.opening[0].count,1);
  delete plan.final_state;assert.equal(r.buildPlanTutorial(plan).finalCards.length,0);
});
test('export SVG embeds only supplied card images and escapes names, IDs and notes',()=>{
  const r=setup(),model=r.buildPlanTutorial(fixture()),assets={'/pics/10.jpg':'data:image/jpeg;base64,AA=='};
  model.steps[0].id='bad"><script>alert(1)</script>';
  const svg=r.renderPlanTutorialSvg(model,undefined,assets);
  assert.match(svg,/href="data:image\/jpeg;base64,AA=="/);assert(!svg.includes('href="/pics/10.jpg"'));
  assert(!svg.includes('<script>'));assert.match(svg,/&lt;script&gt;/);
});

test('long step titles leave enough room for artwork and missing opening text does not overlap condition notes',()=>{
  const r=setup(),model=r.buildPlanTutorial(fixture());
  const step={...model.steps[0],title:'自定义步骤名称'.repeat(11),lines:[{text:'通常召唤',color:'ink'}]};
  model.steps=Array.from({length:25},(_,i)=>({...step,id:'long:'+i,number:i+2}));
  model.opening=[];model.conditionsNote='需要保留一张手牌作为后续费用';
  const layout=r.layoutPlanTutorial(model);
  for(const box of layout.boxes)assert(box.height>box.header+73,'Full card artwork fits below a multi-line title');
  assert(layout.openingNoteY+16>98,'Condition note follows the empty-opening message with readable spacing');
  assert(layout.openingNoteY+layout.conditionLines.length*20<layout.overviewHeight);
});
