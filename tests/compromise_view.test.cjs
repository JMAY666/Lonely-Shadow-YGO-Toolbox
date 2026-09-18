const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const web=path.join(__dirname,'../src/trainer/web');
function opponent() {
  const context=vm.createContext({location:{search:'?session=fixture'},URLSearchParams,Uint8Array,ArrayBuffer,DataView});
  const source=fs.readFileSync(path.join(web,'opponent.js'),'utf8').split("document.querySelector('#opponent-take').onclick")[0];
  vm.runInContext(source+'\nglobalThis.parse=parseOpponentPrompt;',context);return context.parse;
}
const u32=n=>{const b=Buffer.alloc(4);b.writeUInt32LE(n);return b;};
function menuFixture(extra={}) {
  const elements=new Map();
  const context=vm.createContext({Map,structuredClone,CSS:{escape:String},document:{querySelector:()=>null},
    flow:{draft:{id:'plan',name:'当前方案'},busy:false},app:{view:'history',active:null},
    reviewUI:{report:{id:'plan'},nodes:[{id:'step:a',number:2},{id:'step:b',number:23}],node:'step:a'},reviewTitle:n=>'Step '+n.number,
    $:key=>{if(!elements.has(key))elements.set(key,{value:'42',parentElement:{},querySelectorAll:()=>[],open:false});return elements.get(key);},...extra});
  const source=fs.readFileSync(path.join(web,'compromise.js'),'utf8').split("$('#nav-compromise').onclick")[0];
  vm.runInContext(source+`\nbranchUI.root={id:'plan',name:'当前方案',branches_revision:3,review:{revision:'main-v1'},branches:[],branch_points:[{node_id:'step:b',checkpoint:42,timing:'发动后的响应窗口'}]};
    globalThis.menu={branchUI,branchMenu,branchNodeContext,branchMenuPosition,createBranchFromMenu};`,context);
  return {context,elements,...context.menu};
}
test('context actions belong to the right-clicked step, and unavailable, active and nested routes explain why creation is disabled',()=>{
  const m=menuFixture();
  assert.equal(m.branchNodeContext('step:b').nodeId,'step:b');assert.equal(m.branchNodeContext('step:b').points[0].checkpoint,42);
  assert.match(m.branchNodeContext('step:a').reason,/没有可准确恢复/);
  m.context.app.active={id:'running'};assert.match(m.branchNodeContext('step:b').reason,/先结束/);
  m.context.app.active=null;m.branchUI.viewing=true;assert.match(m.branchNodeContext('step:b').reason,/子分支/);
});
test('context popup is clamped to all viewport edges without depending on document scroll',()=>{
  const {branchMenuPosition:position}=menuFixture();
  for(const [x,y]of [[-5,-5],[12,12],[1279,899],[600,899]]) {
    const p=position(x,y,370,300,1280,900);assert(p.left>=8&&p.top>=8);assert(p.left+370<=1272&&p.top+300<=892);
  }
  const narrow=position(319,239,304,224,320,240);assert.equal(narrow.left,8);assert.equal(narrow.top,8);
});
test('context submission rejects a changed route before sending a mutation',async()=>{
  let calls=0;const m=menuFixture({api:async()=>{calls++;}});
  m.branchMenu.context=m.branchNodeContext('step:b');m.branchUI.root.branches_revision++;
  await m.createBranchFromMenu();assert.equal(calls,0);assert.equal(m.elements.get('#create-compromise').disabled,true);
});
test('context creation sends its captured node and checkpoint exactly once even if another step was selected',async()=>{
  let finish;const bodies=[];
  const m=menuFixture({api:async(url,body)=>{bodies.push({url,body});return new Promise(resolve=>{finish=resolve;});}});
  vm.runInContext('openBranchDesign=async()=>{};',m.context);
  m.branchMenu.context=m.branchNodeContext('step:b');
  const pending=m.createBranchFromMenu();await m.createBranchFromMenu();
  assert.equal(bodies.length,1);assert.equal(bodies[0].body.node_id,'step:b');assert.equal(bodies[0].body.checkpoint,42);assert.equal(bodies[0].body.revision,3);
  finish({id:'plan',branches:[{id:'created',valid:true}]});await pending;assert.equal(m.branchUI.selected,'created');
});
test('first review starts with no draft and does not cache or dereference a null draft',()=>{
  const context=vm.createContext({Map,flow:{draft:null}});
  const source=fs.readFileSync(path.join(web,'compromise.js'),'utf8').split("$('#nav-compromise').onclick")[0];
  vm.runInContext(source+'\nstashBranchDraft();globalThis.size=branchUI.drafts.size;',context);
  assert.equal(context.size,0);
});
test('unsaved annotations in another route still trigger the existing unsaved-change guard',()=>{
  const context=vm.createContext({Map,branchUI:{drafts:new Map([['b',{name:'方案',originalName:'方案',notes:'',originalNotes:'',annotations:{nodes:{final:{notes:'未保存'}}},originalAnnotations:'{}'}]])},branchConfigurationDirty:()=>false});
  const source=fs.readFileSync(path.join(web,'expansion.js'),'utf8').split("$('#start-training').onclick")[0];
  vm.runInContext(source+'\nglobalThis.dirty=draftDirty();',context);assert.equal(context.dirty,true);
});
test('viewing an unplayed branch shows an explicitly empty read-only route, never the mainline end board',()=>{
  let mounted;
  const el={parentElement:{}};
  const context=vm.createContext({Map,structuredClone,flow:{draft:{id:'main',annotations:{}}},reviewUI:{report:null},$:()=>el,
    mountReview:report=>{mounted=report;}});
  const source=fs.readFileSync(path.join(web,'compromise.js'),'utf8').split("$('#nav-compromise').onclick")[0];
  vm.runInContext(source+`\nbranchUI.root={id:'main',name:'主线',expansion:{name:'主线',notes:''},catalog:{},final_state:{cards:[{code:1}]},branches:[{id:'pending',valid:true}]};branchUI.selected='pending';branchUI.viewing=true;displayBranchRoute();`,context);
  assert.equal(mounted.final_state,null);assert.equal(mounted.actions.length,0);assert.equal(mounted.plan_stage,'branch_pending');
  assert(mounted.review.nodes.every(n=>n.state===null));
});
test('plan text stays shared across route switches while route annotations remain isolated',()=>{
  let mounted;
  const context=vm.createContext({Map,structuredClone,flow:{draft:null},reviewUI:{report:null},$:()=>({parentElement:{}}),mountReview:r=>{mounted=r;}});
  const source=fs.readFileSync(path.join(web,'compromise.js'),'utf8').split("$('#nav-compromise').onclick")[0];
  vm.runInContext(source+`\nbranchUI.root={id:'main',name:'原名称',expansion:{name:'原名称',notes:''},catalog:{},branches:[{id:'b',report:{actions:[],expansion:{}}}]};
    branchUI.drafts.set('main',{id:'main',name:'原名称',notes:'',annotations:{notes:'主线说明'}});
    flow.draft={id:'main',name:'在分支视图修改的方案名称',notes:'共用备注',annotations:{notes:'分支说明'}};
    branchUI.key='b';stashBranchDraft();branchUI.selected='b';branchUI.viewing=true;displayBranchRoute();
    globalThis.main=branchUI.drafts.get('main');`,context);
  assert.equal(context.main.name,'在分支视图修改的方案名称');assert.equal(context.main.notes,'共用备注');assert.equal(context.main.annotations.notes,'主线说明');
  assert.equal(mounted.expansion.name,context.main.name);
});
test('opponent response window distinguishes optional and forced choices and encodes their exact engine indexes',()=>{
  const parse=opponent();
  const packet=forced=>Buffer.concat([Buffer.from([16,1,1,0]),Buffer.alloc(8),Buffer.from([0,forced]),u32(14558127),Buffer.from([1,2,0,0]),u32(0)]).toString('hex');
  const optional=parse(packet(0));assert.equal(optional.choices.length,2);assert.equal(optional.choices[0].code,14558127);
  assert.deepEqual([...optional.choices[0].response],[0,0,0,0]);assert.deepEqual([...optional.choices[1].response],[255,255,255,255]);
  const forced=parse(packet(1));assert.equal(forced.choices.length,1);
  const yes=parse(Buffer.concat([Buffer.from([12,1]),u32(14558127),Buffer.from([1,2,0,0]),u32(0)]).toString('hex'));
  assert.equal(yes.choices.length,2);assert.deepEqual([...yes.choices[1].response],[0,0,0,0]);
});
test('sum and place choices preserve mandatory cards, totals and absolute player positions',()=>{
  const parse=opponent();
  const sum=Buffer.concat([Buffer.from([23,0,1]),u32(8),Buffer.from([1,2,1]),u32(10),Buffer.from([1,4,0]),u32(4),Buffer.from([1]),u32(11),Buffer.from([1,4,1]),u32(4)]);
  const model=parse(sum.toString('hex'));assert.equal(model.target,8);assert.equal(model.mandatory,1);assert.equal(model.choices[1].code,11);
  assert.deepEqual([...model.choices[1].response],[0]);
  const place=parse(Buffer.concat([Buffer.from([18,1,1]),u32(0xfffffffe)]).toString('hex'));
  assert.deepEqual([...place.choices[0].response],[1,4,0]);
  const optionalPlace=parse(Buffer.concat([Buffer.from([18,1,0]),u32(0xffffffff)]).toString('hex'));
  assert.deepEqual([...optionalPlace.cancel],[1,0,0]);
  const tribute=parse(Buffer.concat([Buffer.from([20,1,0,2,2,1]),u32(10),Buffer.from([1,4,0,2])]).toString('hex'));
  assert.equal(tribute.min,1,'A double tribute may legally pay a tribute value of two using one card');
  assert.equal(tribute.tributeMinimum,2);
});
function tutorial(extra={}) {
  const el={addEventListener(){}};
  const context=vm.createContext({Map,Set,structuredClone,flow:{draft:null},app:{},$:()=>el,document:{addEventListener(){},querySelectorAll:()=>[]},escape:String,eventSummary:()=>'',zoneNames:{},...extra});
  for(const file of ['activation.js','review.js','plan-tutorial.js','compromise-tutorial.js'])vm.runInContext(fs.readFileSync(path.join(web,file),'utf8'),context);
  return vm.runInContext('({buildPlanTutorial,layoutPlanTutorial,renderPlanTutorialSvg,tutorialAssets})',context);
}
test('branch connectors from a short Step pass below its taller row neighbour',()=>{
  const tools=tutorial(),base=tools.buildPlanTutorial(require('./fixtures/opponent-hand-reveal.cjs')());
  const [long,short]=base.steps,main={...base,steps:[short,long]};
  const model={name:'mixed row branch',routes:[{id:'main',label:'main',model:main},
    {id:'branch',label:'branch',valid:true,source:{node_id:short.id,action_id:short.actions[0].id,checkpoint:1},facts:[],model:{...base,branchFinal:true,steps:[short]}}]};
  const layout=tools.layoutPlanTutorial(model),route=layout.routes[0],[a,b]=route.inner.boxes;
  assert.equal(a.row,b.row);assert(a.height<b.height);
  assert(layout.connections[0].gapY>route.y+route.head+b.y+b.height,'The branch line must not cross the tall neighbour');
});
function planFixture() {
  const card={code:10,instance_id:1,name:'我方效果',controller:0,location:8,sequence:0};
  const action={id:'3:0',kind:'effect',cards:[card],status:'resolved',costs:[],results:[],targets:[],evidence_refs:['3:0','9:0']};
  const report={name:'主线',actions:[action],events:[],catalog:{10:{name:'我方效果',desc:'①抽牌。',type:2}},annotations:{},
    requirements:{main:[],extra:[],opening:[],random:[]},review:{nodes:[{id:'initial',kind:'initial',number:1,state:{cards:[]},action_ids:[]},{id:'step:3:0',kind:'step',number:2,state:{cards:[card]},action_ids:['3:0']},{id:'final',kind:'final',number:3,state:{cards:[card]},action_ids:[]}],complete:true}};
  report.branches=[1,2].map(i=>({id:'branch-'+i,name:'妥协 '+i,source:{node_id:'step:3:0',action_id:'3:0',checkpoint:5,seq:5,timing:'发动后的响应窗口',cards:[card]},conditions:{hand:[14558127]},premises:[],report:{...report,name:'分支',actions:[{...action,status:'disabled'}]}}));
  return report;
}
test('tutorial keeps mainline default and gives each chosen branch an exact response-step connector and separate region',()=>{
  const tools=tutorial(),plan=planFixture(),before=JSON.stringify(plan);
  const simple=tools.buildPlanTutorial(plan);assert(!simple.routes);
  const model=tools.buildPlanTutorial(plan,true),layout=tools.layoutPlanTutorial(model),svg=tools.renderPlanTutorialSvg(model,layout);
  assert.equal(model.routes.length,3);assert.equal(layout.connections.length,2);
  for(const connection of layout.connections){assert.equal(connection.node,'step:3:0');assert.equal(connection.checkpoint,5);assert.equal(connection.action,'3:0');}
  assert.equal((svg.match(/data-branch-connection=/g)||[]).length,2);assert.equal((svg.match(/stroke-dasharray=/g)||[]).length,3);
  assert(svg.includes('预设条件'));assert.equal(JSON.stringify(plan),before);
  const chosen=tools.buildPlanTutorial(plan,['branch-2']);assert.equal(chosen.routes.length,2);assert.equal(chosen.routes[1].id,'branch-2');
  plan.branches[0].source.node_id='missing';assert.equal(tools.layoutPlanTutorial(tools.buildPlanTutorial(plan,true)).connections.length,1,'Missing source must not be silently rebound');
});
test('branch export embeds scenario-only card artwork, including cards absent from actual steps',async()=>{
  const fetched=[];
  const tools=tutorial({fetch:async url=>{fetched.push(url);return {ok:true,blob:async()=>({type:'image/png',arrayBuffer:async()=>Uint8Array.from([1,2,3]).buffer})};},Uint8Array,btoa:text=>Buffer.from(text,'binary').toString('base64')});
  const model=tools.buildPlanTutorial(planFixture(),true),assets=await tools.tutorialAssets(model);
  assert(fetched.includes('/pics/14558127.jpg'));assert(assets['/pics/14558127.jpg'].startsWith('data:image/png;base64,'));
  const svg=tools.renderPlanTutorialSvg(model,tools.layoutPlanTutorial(model),assets);assert(!svg.includes('href="/pics/'));
});
test('a normally hidden cleanup becomes an explicit real anchor only when a selected branch needs it',()=>{
  const tools=tutorial(),plan=planFixture();
  plan.actions[0]={...plan.actions[0],kind:'action',evidence_refs:['3:0']};
  plan.events=[{id:'3:0',message:50,origin:{location:128},destination:{location:16},reason:1024,cards:plan.actions[0].cards}];
  assert.equal(tools.buildPlanTutorial(plan).steps.length,0);
  const included=tools.buildPlanTutorial(plan,true),layout=tools.layoutPlanTutorial(included);
  assert.equal(included.routes[0].model.steps[0].actions[0].id,'3:0');
  assert.equal(layout.connections.length,2);assert.equal(layout.connections[0].action,'3:0');
});

test('branched tutorial repeats no opening conditions in branch regions and gives their end board full width',()=>{
  const tools=tutorial(),plan=planFixture(),model=tools.buildPlanTutorial(plan,true),layout=tools.layoutPlanTutorial(model);
  const svg=tools.renderPlanTutorialSvg(model,layout);
  assert.equal((svg.match(/>起手条件</g)||[]).length,1);
  assert.equal((svg.match(/>终场</g)||[]).length,2);
  for(const b of layout.routes.slice(1)){assert(b.model.branchFinal);assert.equal(b.inner.openingRows.length,0);assert.equal(b.inner.finalWidth,b.inner.width-b.inner.pad*2);}
});
