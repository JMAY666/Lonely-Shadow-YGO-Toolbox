const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
function setup(extra={}) {
  const el={addEventListener(){}};
  const context=vm.createContext({Map,structuredClone,flow:{draft:null},app:{},$:()=>el,
    document:{addEventListener(){},querySelectorAll:()=>[]},escape:String,eventSummary:e=>e.result||e.type||'',zoneNames:{},...extra});
  for(const file of ['opening-rules.js','activation.js','review.js','plan-tutorial.js'])vm.runInContext(readFileSync(path.join(__dirname,'../src/trainer/web',file),'utf8'),context);
  return vm.runInContext('({buildPlanTutorial,layoutPlanTutorial,renderPlanTutorialSvg,tutorialWrap,tutorialAssets,reviewUI})',context);
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

test('one-image tutorial includes the explicitly revealed card from an older frozen plan',()=>{
  const r=setup(),plan=fixture(),action=plan.actions[0],shown={code:30,name:'需要展示的额外怪兽',instance_id:30,controller:0,location:64};
  plan.events.unshift({id:action.id,message:70,chain:1},{id:'resolve',message:72,chain:1},{id:'reveal',message:31,cards:[shown]});
  plan.events.push({id:'done',message:73,chain:1});
  const frozen=JSON.stringify(plan),model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  const reveal=model.steps[0].actions[0].stages.find(stage=>stage.label.includes('展示'));
  assert.equal(reveal.cards[0].name,shown.name);assert.match(svg,/需要展示的额外怪兽/);
  assert.equal(JSON.stringify(plan),frozen);
});

test('conditional tutorial shows sets, bans and the frozen instance without implying route interchangeability',()=>{
  const r=setup(),plan=fixture(),condition={kind:'condition',version:1,rule:{op:'all',items:[{field:'level',op:'eq',value:3},{field:'monster_kind',op:'in',values:['tuner']}]}};
  plan.expansion={conditions:{hand_count:2,slots:[10,condition],banned:[condition]},actual_opening:[10,11]};
  const before=JSON.stringify(plan),model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  assert.equal(model.opening[1].src,'/condition-card.svg');assert.equal(model.opening[1].name,'任意等级 3 调整');
  assert(model.opening[2].name.startsWith('禁止：'));assert.match(svg,/条件集合/);assert.match(svg,/实例/);
  assert.match(model.warnings.join(' '),/尚未证明可替换/);assert.equal(JSON.stringify(plan),before);
});
test('tutorial reads the frozen plan only and preserves costs, targets, notes and final marks without full effect text or resources',()=>{
  const r=setup(),plan=fixture(),before=JSON.stringify(plan);
  r.reviewUI.report={annotations:{nodes:{'step:2:0':{name:'无关草稿'}}}};
  const model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  for(const label of ['起手条件','终场展示','任意手牌 ×1','发动①','Cost · 支付 LP','支付 1000 LP','对象','检索','无效一次','我方墓地','Step 2'])assert(svg.includes(label),label);
  for(const label of ['效果原文','展开使用资源','不应列出的使用资源','无关草稿'])assert(!svg.includes(label),label);
  assert.equal(model.finalCards.length,2);assert.equal(model.steps.length,1);
  assert.equal((svg.match(/class="tutorial-flow-card"/g)||[]).length,3,'Actor, target and result each have their own card image');
  assert.deepEqual(Array.from(model.steps[0].actions[0].stages,s=>s.label),['发动①','Cost · 支付 LP','对象','检索']);
  assert.match(svg,/路线 &lt;测试&gt;/);assert.match(svg,/用户备注 &amp; &lt;保留&gt;/);
  assert.match(svg,/fill="#b33737"/);assert.equal(JSON.stringify(plan),before);
});
test('tutorial shows the identified effect and random deck-top outcomes without fixing the opponent identities',()=>{
  const r=setup(),plan=require('./fixtures/random-reveal.cjs')(),before=JSON.stringify(plan);
  const model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  assert.match(svg,/作为同调素材送去墓地/);assert.match(svg,/翻开对方卡组顶部/);assert.match(svg,/随机牌/);
  assert.match(svg,/选择放回对方卡组最上面或最下面/);assert(!svg.includes('示例翻牌'));assert(!svg.includes('/pics/52155219'));
  assert.equal(JSON.stringify(plan),before);
});

test('field card activation without extra actions stays a simple card stage in old frozen plans',()=>{
  const r=setup(),plan=fixture(),a=plan.actions[0];
  plan.catalog[10].type=0x80002;a.cards[0].name='转生炎兽的圣域';a.engine_effect={effect_type:0x1a};a.results=[];a.costs=[];a.targets=[];
  const before=JSON.stringify(plan),model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  assert.equal(model.steps[0].actions[0].stages[0].label,'发动场地魔法卡');
  assert(!svg.includes('处理结果未记录'));assert(!svg.includes('发动①'));assert.equal(JSON.stringify(plan),before);
  a.status='negated';assert(r.renderPlanTutorialSvg(r.buildPlanTutorial(plan)).includes('发动被无效'));
  a.status='resolved';a.engine_effect.effect_type=0x82;assert(r.renderPlanTutorialSvg(r.buildPlanTutorial(plan)).includes('处理结果未记录'));
});

test('tutorial projects condition-origin actors and final instances while preserving distinct same-name targets',()=>{
  const r=setup(),plan=fixture();
  plan.expansion={conditions:{slots:[{kind:'condition',version:1,rule:{field:'level',op:'eq',value:3}}],banned:[]},actual_opening:[10]};
  const before=JSON.stringify(plan),model=r.buildPlanTutorial(plan);
  const stages=model.steps[0].actions[0].stages;
  assert.equal(stages[0].cards[0].src,'/condition-card.svg');assert.match(stages[0].cards[0].name,/等级 = 3/);
  assert.equal(stages.find(s=>s.label==='对象').cards[0].src,'/pics/10.jpg');
  assert.equal(model.finalCards[0].src,'/condition-card.svg');
  assert(!model.conditionsNote.includes('起手怪兽'));assert.equal(JSON.stringify(plan),before);
});
test('negated and unrecorded outcomes and random dependencies remain explicit',()=>{
  const r=setup(),plan=fixture();plan.actions[0].status='negated';plan.actions[0].results=[];
  plan.requirements.random=[{name:'需要随机命中',count:1}];
  const svg=r.renderPlanTutorialSvg(r.buildPlanTutorial(plan));
  assert.match(svg,/发动被无效/);assert(!svg.includes('处理结果未记录'));assert.match(svg,/Cost/);assert.match(svg,/随机依赖：需要随机命中 ×1/);
  assert(!svg.includes('data-tutorial-role="检索"'));
  plan.requirements.random=[];plan.requirements.uncertain=[{name:'取得方式缺少记录',count:1}];
  const uncertain=r.renderPlanTutorialSvg(r.buildPlanTutorial(plan));
  assert.match(uncertain,/来源待核对：取得方式缺少记录 ×1/);assert(!uncertain.includes('随机依赖：'));
});
test('position mini maps accompany action and final cards using recorded zones, without mutating the plan',()=>{
  const r=setup(),plan=fixture(),actor=plan.actions[0].cards[0];
  plan.actions[0].targets=[{...actor,controller:1,location:8,sequence:5}];
  plan.actions[0].results=[{message:63,cards:[{...actor,location:4,sequence:6,summon_method:'连接召唤',materials:[{...actor,sequence:3}]}]}];
  const before=JSON.stringify(plan),model=r.buildPlanTutorial(plan),svg=r.renderPlanTutorialSvg(model);
  const positions=model.steps[0].actions[0].stages.flatMap(s=>s.cards).filter(c=>c.fieldPosition).map(c=>c.fieldPosition);
  assert.deepEqual(JSON.parse(JSON.stringify(positions)),[{controller:0,location:4,sequence:0},{controller:1,location:8,sequence:5},{controller:0,location:4,sequence:3},{controller:0,location:4,sequence:6}]);
  assert.equal((svg.match(/class="tutorial-location-map"/g)||[]).length,5,'Four operation cards and one marked field card');
  assert.equal((svg.match(/data-active-slot="true"/g)||[]).length,5);
  assert.match(svg,/data-controller="1" data-location="8" data-sequence="5"/);
  assert.match(svg,/fill="#b75757"/);assert.match(svg,/fill="#237caa"/);
  assert.match(svg,/width="30" height="24"/);assert.equal(JSON.stringify(plan),before);
  const layout=r.layoutPlanTutorial(model);
  for(const box of layout.boxes)for(const action of box.actions)for(const stage of action.stages)for(const card of stage.cards) {
    assert(card.y+72+card.mapHeight+card.lines.length*14+card.places.length*13<=stage.height);
  }
  assert(layout.finalCards[0].headHeight>=108);
});
test('unknown or off-field positions do not get fabricated highlighted mini maps',()=>{
  const r=setup(),plan=fixture();
  plan.actions[0].cards[0].sequence=-1;
  plan.annotations.final_marks={};
  const svg=r.renderPlanTutorialSvg(r.buildPlanTutorial(plan));
  assert(!svg.includes('tutorial-location-map'));
  assert.match(svg,/我方墓地/);
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
      assert(box.y+box.height<layout.height-40);assert(box.notesY+box.notes.length*20<box.height);
      for(const action of box.actions)for(const stage of action.stages) {
        assert(stage.x>=0&&stage.x+stage.width<=box.width-36+.1);
        assert(action.y+stage.y+stage.height<box.height);
      }
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
  const step={...model.steps[0],title:'自定义步骤名称'.repeat(11)};
  model.steps=Array.from({length:25},(_,i)=>({...step,id:'long:'+i,number:i+2}));
  model.opening=[];model.conditionsNote='需要保留一张手牌作为后续费用';
  const layout=r.layoutPlanTutorial(model);
  for(const box of layout.boxes)assert(box.height>box.header+73,'Full card artwork fits below a multi-line title');
  assert(layout.openingNoteY+16>98,'Condition note follows the empty-opening message with readable spacing');
  assert(layout.openingNoteY+layout.conditionLines.length*20<layout.overviewHeight);
});

test('summon materials, card costs and results are pictured in order without repeating operation sentences',()=>{
  const r=setup(),plan=fixture(),[actor]=plan.actions[0].cards;
  const material={...actor,instance_id:4,code:12,name:'素材怪兽'},summoned={...actor,instance_id:5,code:13,name:'连接怪兽',summon_method:'连接召唤',materials:[actor,material]};
  plan.actions[0].costs=[{message:50,cards:[material],origin:{controller:0,location:128},destination:{controller:0,location:16},reason:128}];
  plan.actions[0].results=[{message:63,cards:[summoned]}];
  const model=r.buildPlanTutorial(plan),stages=model.steps[0].actions[0].stages,svg=r.renderPlanTutorialSvg(model);
  assert.deepEqual(Array.from(stages,s=>s.label),['发动①','Cost · 送墓','对象','素材','连接召唤']);
  assert.equal((svg.match(/class="tutorial-flow-card"/g)||[]).length,6);
  assert.equal(stages[1].hint,'我方素材 → 我方墓地');
  assert.deepEqual(Array.from(stages[3].cards,c=>c.src),['/pics/10.jpg','/pics/12.jpg']);
  assert.equal(stages[4].cards[0].src,'/pics/13.jpg');
  assert(!svg.includes('连接召唤 · 连接怪兽'));
});

test('many materials and long card names wrap within a stage without dropping any copies',()=>{
  const r=setup(),model=r.buildPlanTutorial(fixture());
  const cards=Array.from({length:7},(_,i)=>({name:'很长的卡牌名称'.repeat(4)+i,src:`/pics/${100+i}.jpg`,location:'对方墓地'}));
  model.steps=Array.from({length:25},(_,i)=>({id:'large:'+i,number:i+2,title:'',actions:[{id:'summon',stages:[{label:'素材',cards},{label:'连接召唤',cards:cards.slice(0,1)}],notes:[]}],notes:[]}));
  const layout=r.layoutPlanTutorial(model);
  for(const box of layout.boxes) {
    const stages=box.actions[0].stages;assert.equal(stages[0].cards.length,7);
    assert(stages[1].y>=stages[0].height+24,'The result follows the wrapped material group');
    for(const stage of stages)for(const card of stage.cards) {
      assert(card.x>=0&&card.x+70<=stage.width);
      assert(card.y+72+card.lines.length*14+card.places.length*13<=stage.height);
    }
  }
});

test('export embeds cards used only as costs, targets, materials or results and deduplicates requests',async()=>{
  const requested=[],r=setup({fetch:async src=>{requested.push(src);return {ok:true,blob:async()=>({type:'image/jpeg',arrayBuffer:async()=>new Uint8Array([1,2]).buffer})};},btoa:s=>Buffer.from(s,'binary').toString('base64')});
  const plan=fixture(),actor=plan.actions[0].cards[0];
  plan.actions[0].costs=[{message:50,cards:[{...actor,code:12}],destination:{controller:0,location:16}}];
  plan.actions[0].targets=[{...actor,code:13}];
  plan.actions[0].results=[{message:63,cards:[{...actor,code:14,summon_method:'连接召唤',materials:[{...actor,code:15}]}]}];
  const model=r.buildPlanTutorial(plan),assets=await r.tutorialAssets(model),svg=r.renderPlanTutorialSvg(model,undefined,assets);
  assert.deepEqual(requested.slice().sort(),['/pics/10.jpg','/pics/12.jpg','/pics/13.jpg','/pics/14.jpg','/pics/15.jpg','/review-back.svg'].sort());
  assert(!svg.includes('href="/pics/'));assert(!svg.includes('href="/review-back.svg'));
});
