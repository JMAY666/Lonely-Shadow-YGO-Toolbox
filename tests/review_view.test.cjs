const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const source=['opening-rules.js','activation.js','review.js'].map(file=>readFileSync(path.join(__dirname,'../src/trainer/web',file),'utf8')).join('\n');
function setup(extra={}){
  const context=vm.createContext({flow:{draft:null},app:{},Map,structuredClone,CSS:{escape:s=>s},
    escape:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    document:{addEventListener(){}},eventSummary:e=>e.result||e.type||'',zoneNames:{},dt:()=>'',stageNames:{},...extra});
  vm.runInContext(source+'\nglobalThis.r={reviewUI,reviewHover,openReviewDetail,backReviewDetail,closeReviewDetail,scheduleReviewHover,scheduleReviewDetailClose,renderBoard,reviewCard,reviewLogAction,provenance,reviewTitle,reviewFallback,previewReview,summaryHtml,reviewRandomDraw,reviewFinalCards,reviewEffectParts,compactCleanup,reviewLocationIcon};',context);
  return {...context.r,context};
}

test('frozen effect logs recover explicit reveal identity in compact and detailed views without rewriting results',()=>{
  const r=setup(),shown={code:20,name:'被展示的同调怪兽',instance_id:5,controller:0,location:64,sequence:0};
  const actor={code:10,name:'测试魔法',instance_id:1,controller:0,location:8,sequence:0};
  const action={id:'a',activation_ref:'a',kind:'effect',cards:[actor],status:'resolved',results:[],costs:[],targets:[],effect_text:'展示怪兽',effect_text_source:'single_numbered_clause',selected_effect_text:'展示怪兽',effect_number:1,evidence_refs:['a']};
  const report={actions:[action],events:[{id:'a',message:70,chain:1},{id:'start',message:72,chain:1},{id:'reveal',message:31,cards:[shown]},{id:'end',message:73,chain:1},{id:'other',message:31,cards:[{...shown,name:'不能归入本效果'}]}],catalog:{10:{type:2},20:{type:0x2001}},annotations:{nodes:{},cards:{},effects:{},final_marks:{}}};
  const frozen=JSON.stringify(report),node={id:'step',kind:'step',action_ids:['a'],state:{cards:[actor,shown]}};
  for(const mode of ['compact','detailed']){
    const html=r.reviewLogAction(action,node,{report,mode,editable:false,nodes:[node],edits:report.annotations});
    assert.match(html,/展示我方(?:EX )?额外卡组卡牌/);assert.match(html,/被展示的同调怪兽/);assert.match(html,/pics\/20\.jpg/);
    assert(!html.includes('不能归入本效果'));
  }
  assert.equal(JSON.stringify(report),frozen);
  action.results=[{event_ref:'reveal',message:31,cards:[shown]}];
  assert.equal(r.context.recordedActionResults(action,report).length,1,'New projections do not duplicate the same reveal');
  report.events[2].cause={handler_instance:999};action.results=[];
  assert.equal(r.context.recordedActionResults(action,report).length,0,'Conflicting engine evidence is not guessed');
});

test('opponent hand reveals use one counted back without masking later explicit activations or own reveals',()=>{
  const r=setup(),plan=require('./fixtures/opponent-hand-reveal.cjs')(),frozen=JSON.stringify(plan),node=plan.review.nodes[1];
  const event=plan.events.find(e=>e.id==='22:0');
  const projected=r.context.reviewOperationCards(event,event.cards);
  for(const mode of ['compact','detailed']){
    const html=(mode==='compact'?r.context.compactOperation:r.context.reviewOperation)(event,node.id,'',{report:plan,nodes:plan.review.nodes,edits:plan.annotations});
    assert.equal((html.match(/src="\/review-back.svg"/g)||[]).length,1);assert.match(html,/随机手牌 ×5/);
    assert.match(html,/5 张随机牌/);assert(!/魔物狩人|灰流丽|pics\/(1184620|14558127)/.test(html));
  }
  const html=r.reviewCard(projected[4],node.id,{report:plan,name:true,face:true});
  assert.match(html,/随机手牌/);assert(!html.includes('14558127'));
  const original=r.reviewCard(event.cards[4],node.id,{report:plan,name:true,face:true});
  assert.match(original,/灰流丽/);assert.match(original,/pics\/14558127/);
  const own=plan.events.find(e=>e.id==='24:0');
  assert.match(r.context.compactOperation(own,node.id,'',{report:plan,nodes:plan.review.nodes,edits:plan.annotations}),/pics\/14442329/);
  assert.equal(JSON.stringify(plan),frozen);
});

test('quantity-only groups preserve single cards, sides, notes, effects and separate movement results',()=>{
  const r=setup(),plan=require('./fixtures/opponent-hand-reveal.cjs')(),event=plan.events.find(e=>e.id==='22:0'),node=plan.review.nodes[1];
  const cards=r.context.reviewOperationCards(event,event.cards),before=JSON.stringify(plan);
  const project=(e=event,cs=cards,edits=plan.annotations)=>r.context.reviewQuantityCards(e,cs,node,plan,edits);
  const group=project()[0];assert.equal(group._display_members.length,5);assert.equal(group._display_members[4].instance_id,cards[4].instance_id);
  assert.equal(project(event,cards.slice(0,1))[0],cards[0]);
  for(const message of [50,61,63,70])assert.equal(project({...event,message}).length,5);
  assert.equal(project(event,cards,{cards:{20:'本张有独立说明'}}).length,2);
  assert.equal(project(event,cards,{final_marks:{20:{marked:true}}}).length,2);
  const own=cards.map(c=>({...c,controller:0,_display_random:undefined,identity_known:true}));
  assert.equal(project(event,own).length,5,'Known identities stay separate');
  assert.equal(project(event,[...cards.slice(0,2),...own,...cards.slice(2)]).length,7,'Unrelated cards do not get reordered');
  const drawn=cards.map(c=>({...c,controller:0,identity_known:true,_display_random:undefined}));
  const draw={id:'27:0',native_seq:27,message:90,cards:drawn};
  const drawPlan={...plan,events:[...plan.events,draw]};
  const counted=r.context.reviewQuantityCards(draw,drawn,{kind:'final'},drawPlan);
  assert.equal(counted.length,1);assert.match(r.context.reviewCardLabel(counted[0],{kind:'final'},drawPlan),/随机抽牌 ×5/);
  assert.equal(JSON.stringify(plan),before);
});

test('Step boards and tutorial node order use canonical modules while frozen annotations stay unchanged',()=>{
  const r=setup();
  const plan={id:'modular',actions:[],catalog:{},review:{nodes:[
    {id:'step:b',kind:'step',number:3,module_id:'b',state:{cards:[{code:999}]}},
    {id:'step:a',kind:'step',number:2,module_id:'a',state:{cards:[]}}],
    module_graph:{schema:1,modules:[{id:'a',state:{cards:[{instance_id:4,code:42,name:'真实模块',controller:0,location:4,sequence:1}]}},
      {id:'b',state:null}],step_order:['step:a','step:b'],step_links:[{from:'step:a',to:'step:b',module_path:['a','b']}]}},
    annotations:{nodes:{'step:a':{notes:'原批注'}}}};
  const frozen=JSON.stringify(plan),nodes=r.context.reviewNodes(plan);
  assert.deepEqual(Array.from(nodes,n=>n.id),['step:a','step:b']);
  assert.match(r.renderBoard(nodes[0],plan),/真实模块/);
  assert.match(r.renderBoard(nodes[1],plan),/未记录完整状态/);
  assert(!r.renderBoard(nodes[1],plan).includes('999'));
  assert.equal(JSON.stringify(plan),frozen);
});
test('XYZ host shows its own body plus material count, while attached copies do not occupy monster slots',()=>{
  const r=setup();r.reviewUI.report={catalog:{10:{type:0x800001}}};
  const node={id:'step',number:2,kind:'step',state:{cards:[{instance_id:1,code:10,controller:0,location:4,sequence:0},
    {instance_id:2,code:11,controller:0,location:128,sequence:0,overlay_target:1},
    {instance_id:3,code:11,controller:0,location:128,sequence:1,overlay_target:1}]}};
  const html=r.renderBoard(node);
  assert.match(html,/素材 ×2/);assert.equal((html.match(/data-review-card=/g)||[]).length,1);
  assert(!html.includes('opponent-board'));
});

test('a separate tutorial report renders its own cards and board without changing the review buffer',()=>{
  const r=setup(),original={id:'editing',catalog:{10:{type:1}},actions:[],events:[]};
  r.reviewUI.report=original;r.reviewUI.node='editing-node';r.context.flow.draft={id:'editing',annotations:{...{nodes:{},cards:{},effects:{},final_marks:{}},effects:{'1:0':'私人编辑缓冲'}}};
  const card={instance_id:42,code:20,name:'教程卡牌',identity_known:true,controller:0,location:4,sequence:3,position:1};
  const n={id:'tutorial-node',kind:'step',number:2,action_ids:['1:0'],state:{cards:[card],lp:[8000,8000]}};
  const report={id:'tutorial',catalog:{20:{type:1}},review:{nodes:[n]},events:[{id:'1:0',message:61,cards:[card]}],actions:[{id:'1:0',kind:'operation',cards:[card],evidence_refs:['1:0']}],annotations:{nodes:{},cards:{},effects:{},final_marks:{}}};
  const before=JSON.stringify({original,draft:r.context.flow.draft,report});
  const html=r.context.renderRecordedStep(report,n,'compact'),board=r.renderBoard(n,report);
  assert.match(html,/教程卡牌/);assert.match(html,/通常召唤/);assert.match(board,/4 号主怪兽区/);
  assert(!html.includes('私人编辑缓冲'));
  assert([...r.reviewUI.cards.values()].every(entry=>entry.report===report));
  assert.equal(r.reviewUI.report,original);assert.equal(r.reviewUI.node,'editing-node');
  assert.equal(JSON.stringify({original,draft:r.context.flow.draft,report}),before);
});
test('costs, targets, failed effects and horizontal materials have distinct image-based representations',()=>{
  const r=setup();const c={code:10,name:'<注入>',instance_id:1,controller:0,location:2};
  r.reviewUI.logMode='detailed';
  const cost={id:'2:0',message:50,cards:[c],origin:c,destination:{controller:0,location:16}};
  r.reviewUI.report={events:[cost],catalog:{}};
  const a={id:'3:0',kind:'effect',cards:[c],status:'negated',effect_text:'①：费用；处理。②：其他效果。',
    evidence_refs:['2:0'],costs:[{event_ref:'2:0',cards:[c]}],targets:[c],results:[]};
  const html=r.reviewLogAction(a,{id:'node',number:2});
  assert.match(html,/费用 Cost/);assert.match(html,/>对象</);assert.match(html,/发动被无效/);
  assert.match(html,/效果原文（发动项待核对）/);assert.match(html,/log-effect-description/);assert.match(html,/①：费用；处理。②：其他效果。/);
  assert(!html.includes('<注入>'));assert((html.match(/data-review-card=/g)||[]).length>=3);
  const summon={id:'4:0',kind:'summon',cards:[{...c,materials:[{...c,instance_id:2},{...c,instance_id:3}],summon_method:'连接召唤'}],summary:'连接召唤',evidence_refs:[]};
  const log=r.reviewLogAction(summon,{id:'node',number:2});
  assert.match(log,/<b>＋<\/b>/);assert.match(log,/不能视作叠放素材/);
});

test('compact effect keeps activation, cost and summon horizontally, with failed and missing results explicit',()=>{
  const r=setup(), c=(code,name)=>({code,name,instance_id:code,controller:0,location:4});
  const host=c(10,'雄马'), material=c(11,'羚羊'), summoned=c(12,'小妖');
  const cost={id:'3:0',message:50,cards:[material],origin:{controller:0,location:128},destination:{controller:0,location:16}};
  const result={id:'4:0',message:63,cards:[summoned]};
  r.reviewUI.report={catalog:{},events:[cost,result]};
  const a={id:'2:0',kind:'effect',cards:[host],costs:[{event_ref:cost.id,cards:[material]}],results:[{event_ref:result.id,cards:[summoned]}],status:'resolved'};
  const html=r.reviewLogAction(a,{id:'step',number:2});
  assert.match(html,/compact-chain/);assert.match(html,/发动效果/);assert.match(html,/Cost · 送墓/);assert.match(html,/特殊召唤/);
  assert(html.indexOf('雄马')<html.indexOf('羚羊')&&html.indexOf('羚羊')<html.indexOf('小妖'));
  assert.equal((html.match(/data-review-card=/g)||[]).length,3);
  assert(!html.includes('具体效果待补充'));assert(!html.includes('textarea'));
  const failed=r.reviewLogAction({...a,status:'negated',results:[]},{id:'step',number:2});
  assert.match(failed,/发动被无效/);assert.match(failed,/Cost · 送墓/);assert(!failed.includes('处理结果未记录'));
});

test('XYZ material movements appear once; Link destinations remain available only in detailed mode',()=>{
  const r=setup(), material={code:11,name:'素材甲',instance_id:1,controller:0,location:4};
  const move={id:'2:0',message:50,cards:[material],origin:material,destination:{controller:0,location:128},reason:8};
  const host={code:12,name:'超量怪兽',instance_id:2,controller:0,location:4,summon_method:'超量召唤',materials:[material]};
  const n={id:'step',number:2,state:{cards:[host,{...material,location:128,overlay_target:2}]}};
  r.reviewUI.report={events:[move],catalog:{}};r.reviewUI.nodes=[n];
  const a={id:'3:0',kind:'summon',cards:[host],summary:'超量召唤',evidence_refs:[move.id]};
  for(const mode of ['compact','detailed']) {
    r.reviewUI.logMode=mode;const html=r.reviewLogAction(a,n);
    assert(!html.includes('log-materials'));assert.match(html,/素材 ×1/);
    assert.equal((html.match(/data-review-card=/g)||[]).length,2);
  }
  const link={...a,cards:[{...host,summon_method:'连接召唤'}]};
  r.reviewUI.logMode='compact';assert(!r.reviewLogAction(link,n).includes('素材去向'));
  r.reviewUI.logMode='detailed';assert.match(r.reviewLogAction(link,n),/素材去向/);
});

test('random draws use card backs across nodes, log, details identity and saved summary without masking searched copies or rewriting facts',()=>{
  const r=setup(), drawn={code:10,name:'同名牌',instance_id:1,controller:0,location:2}, searched={...drawn,instance_id:2};
  const initial={id:'initial',kind:'initial',number:1,state_ref:2,action_ids:[]};
  const step={id:'step',kind:'step',number:2,state_ref:8,action_ids:[]};
  const final={id:'final',kind:'final',state_ref:10,state:{cards:[drawn,searched]}};
  const report={id:'saved',final_state:final.state,annotations:{final_marks:{1:{marked:true,effects:{}},2:{marked:true,effects:{}}}},catalog:{},initial_hand_ref:'2:0',events:[
    {id:'2:0',native_seq:2,message:90,cards:[searched]},
    {id:'5:0',native_seq:5,message:90,draw_kind:'effect',cards:[drawn]},
    {id:'7:0',native_seq:7,message:50,cards:[searched],origin:{location:1},destination:{location:2}}],review:{nodes:[initial,step,final]}};
  const before=JSON.stringify(report);r.reviewUI.report=report;r.reviewUI.nodes=report.review.nodes;
  assert.match(r.reviewCard(drawn,'initial',{face:true,name:true}),/pics\/10.jpg/);
  const html=r.reviewCard(drawn,'step',{face:true,name:true});
  assert.match(html,/随机抽牌/);assert.match(html,/review-back.svg/);assert(!html.includes('同名牌'));assert(!html.includes('pics/10'));
  assert.match(r.reviewCard(searched,'step',{face:true,name:true}),/pics\/10.jpg/);
  assert(!r.reviewRandomDraw({...drawn,instance_id:null},step));
  for(const mode of ['compact','detailed']) {
    r.reviewUI.logMode=mode;
    const log=r.reviewLogAction({id:'5:0',kind:'action',summary:'抽到同名牌',cards:[drawn]},step);
    assert.match(log,/随机抽牌/);assert(!log.includes('pics/10'));assert(!log.includes('同名牌'));
  }
  r.reviewUI.report={events:[]};
  const summary=r.summaryHtml({final:{cards:[drawn,searched]}},report);
  assert.match(summary,/随机抽牌/);assert.equal((summary.match(/pics\/10.jpg/g)||[]).length,1);
  assert.equal(JSON.stringify(report),before);
  const legacy={...report};delete legacy.review;
  assert.match(r.summaryHtml({final:{cards:[drawn]}},legacy),/随机抽牌/);
  const opponent={...drawn,instance_id:3,controller:1};
  const opposite={events:[{id:'9:0',message:90,cards:[opponent]}]};
  assert(!r.reviewRandomDraw(opponent,{kind:'final'},opposite));
  const unknown=r.reviewCard({...drawn,identity_known:false},'final',{face:true});
  assert(!unknown.includes('pics/'));assert.match(unknown,/未知卡牌/);
});
test('provenance stops at selected boundary and never merges an identical-name copy',()=>{
  const r=setup();const c={instance_id:1,code:10,name:'同名卡',controller:0,location:2};
  r.reviewUI.nodes=[{id:'initial',number:1,state_ref:2,action_ids:[]},{id:'step',number:2,state_ref:4,action_ids:[]}];
  r.reviewUI.report={initial_hand:[c],events:[{id:'4:0',native_seq:4,message:61,cards:[{...c,location:4,sequence:0}]},
    {id:'6:0',native_seq:6,message:50,cards:[c],origin:c,destination:{controller:0,location:16}},
    {id:'3:0',native_seq:3,message:50,cards:[{...c,instance_id:2}],origin:c,destination:{controller:0,location:32}}]};
  const history=r.provenance(c,r.reviewUI.nodes[1]);
  assert.equal(history.length,2);assert.match(history[1].text,/通常召唤/);assert(!JSON.stringify(history).includes('除外'));
  const saved={...r.reviewUI.report,review:{nodes:r.reviewUI.nodes}};
  r.reviewUI.nodes=[];r.reviewUI.report=null;
  assert.equal(r.provenance(c,saved.review.nodes[1],saved)[0].node.id,'initial');
});
test('deck-top reveals and their later outcomes use random backs, selected effects and real return side',()=>{
  const r=setup(),plan=require('./fixtures/random-reveal.cjs')(),before=JSON.stringify(plan),node=plan.review.nodes[1];
  r.reviewUI.report=plan;r.reviewUI.nodes=plan.review.nodes;r.reviewUI.node=node.id;
  for(const mode of ['compact','detailed']) {
    r.reviewUI.logMode=mode;
    const html=r.reviewLogAction(plan.actions[0],node);
    assert.match(html,/②效果/);assert.match(html,/这张卡作为同调素材送去墓地的场合才能发动/);
    assert.match(html,/翻开对方卡组顶部 2 张随机牌/);assert.match(html,/选择放回对方卡组最上面或最下面/);
    assert(!html.includes('示例翻牌'));assert(!html.includes('/pics/52155219'));assert(!html.includes('/pics/56003780'));
    assert.equal((html.match(/class="review-card[^\"]*random-card/g)||[]).length,3);assert.match(html,/随机牌 ×2/);
  }
  const revealed=plan.events[1].cards[0];
  assert.match(r.reviewCard(revealed,'initial',{face:true}),/pics\/52155219/);
  assert.match(r.reviewCard({...revealed,location:32,position:5},'final',{face:true,name:true}),/随机牌/);
  assert.match(r.reviewCard({...revealed,instance_id:99},'final',{face:true,name:true}),/pics\/52155219/);
  assert.equal(JSON.stringify(plan),before);
});

test('conditional opening identities follow materials, zones and later cards without hiding another identical copy',()=>{
  const r=setup(),c={code:10,name:'实例甲',instance_id:1,controller:0,location:2,position:1},exact={...c,instance_id:2};
  const rule={kind:'condition',version:1,rule:{field:'level',op:'eq',value:3}};
  const result={code:20,name:'同调结果',instance_id:3,controller:0,location:4,sequence:0,position:1,materials:[c,exact],summon_method:'同调召唤'};
  const event={id:'2:0',message:63,cards:[result]},action={id:'2:0',kind:'operation',summary:'同调召唤',cards:[result],evidence_refs:['2:0']};
  const node={id:'step',kind:'step',number:2,action_ids:['2:0'],state:{cards:[{...c,location:16},result]}};
  const plan={initial_hand:[c,exact],expansion:{conditions:{slots:[rule,10]},actual_opening:[10,10]},catalog:{},events:[event],actions:[action],review:{nodes:[node]}};
  const before=JSON.stringify(plan);r.reviewUI.report=plan;r.reviewUI.nodes=[node];
  const opening=r.context.reviewOpeningCards(plan,{id:'initial',kind:'initial'});
  assert.match(opening,/condition-card.svg/);assert.equal((opening.match(/pics\/10.jpg/g)||[]).length,1);
  for(const mode of ['compact','detailed']){
    r.reviewUI.logMode=mode;const html=r.reviewLogAction(action,node);
    assert.match(html,/condition-origin-card/);assert.match(html,/任意满足 等级 = 3/);
    assert.equal((html.match(/pics\/10.jpg/g)||[]).length,1);assert.match(html,/pics\/20.jpg/);
  }
  assert(!r.reviewCard({...c,location:16},node,{report:plan,name:true}).includes('/pics/10'));
  assert.match(r.reviewCard(exact,node,{report:plan,name:true}),/pics\/10.jpg/);
  assert.match(r.reviewCard({...c,instance_id:null},node,{report:plan,name:true}),/pics\/10.jpg/);
  assert.equal(JSON.stringify(plan),before);
});

test('a fixed bottom-only effect is not changed into an optional top placement',()=>{
  const r=setup(),plan=require('./fixtures/random-reveal.cjs')();
  plan.actions[0].selected_effect_text='将那张卡放回卡组最下面。';
  assert.equal(r.context.reviewDeckOperation(plan.events[3],plan.events[3].cards,plan),'放回对方卡组最下面');
});

test('illegal Link defense is flagged instead of drawn as legal defense',()=>{
  const r=setup();r.reviewUI.report={catalog:{10:{type:0x4000001}}};
  const html=r.reviewCard({code:10,controller:0,location:4,position:4});
  assert.match(html,/状态待核对/);assert(!html.includes('is-defense'));
  const unknown=r.reviewCard({code:10,controller:0,location:4});
  assert.match(unknown,/表示未记录/);assert(!unknown.includes('>攻击<'));
});

test('confirmation submits the reviewed normalized name instead of falsely treating trimmed whitespace as a conflicting save',async()=>{
  const r=setup(),elements=new Map();
  r.context.$=s=>{if(!elements.has(s))elements.set(s,{});return elements.get(s);};
  r.context.flow.draft={id:'draft',name:'  已核对的名称  ',notes:'保留备注',annotations:{},originalName:'旧名称',originalNotes:''};
  r.context.api=async(url,body)=>({...body,name:body.name.trim(),confirmation:'checked',saved:false});
  vm.runInContext('renderConfirmation=()=>{};switchView=()=>{};',r.context);
  await r.previewReview();
  assert.equal(r.reviewUI.pending.payload.name,'已核对的名称');
  assert.equal(r.reviewUI.pending.payload.notes,'保留备注');
  assert.equal(r.context.flow.draft.name,'  已核对的名称  ');
});


test('final summaries show marked grave and banished instances only and retain effect notes',()=>{
  const r=setup(), cards=[{instance_id:1,code:10,name:'场上',controller:0,location:4,sequence:0},{instance_id:2,code:10,name:'墓地同名',controller:0,location:16},{instance_id:3,code:11,name:'除外',controller:0,location:32}];
  const report={catalog:{10:{desc:'①②每回合一次。①：检索。②：墓地效果。'}},final_state:{cards},annotations:{cards:{2:'后续资源'},final_marks:{2:{marked:true,effects:{2:{note:'阻抗'}}},3:{marked:true,effects:{}}}}};
  r.reviewUI.report=report;
  const html=r.summaryHtml({},report);assert(!html.includes('>场上<'));assert.match(html,/墓地同名/);assert.match(html,/除外/);assert.match(html,/②效果/);assert.match(html,/阻抗/);assert(!html.includes('未填写终场'));
  assert.equal(r.reviewEffectParts(report.catalog[10].desc).length,3);
});

test('compact final marks keep numbers and red notes, omit field maps, and detailed mode retains the source text',()=>{
  const r=setup(),cards=[{instance_id:1,code:10,name:'场上怪兽',controller:0,location:4,sequence:5},
    {instance_id:2,code:10,name:'场地魔法',controller:0,location:8,sequence:5},
    {instance_id:3,code:10,name:'墓地卡牌',controller:0,location:16}];
  const plan={catalog:{10:{desc:'①：效果原文。②：另一效果原文。'}},annotations:{final_marks:Object.fromEntries(cards.map(c=>[c.instance_id,{marked:true,effects:{0:{note:'红色备注 <内容>'},1:{note:'  '}}}]))}};
  const before=JSON.stringify(plan),node={id:'final',kind:'final',state:{cards}};
  const compact=r.reviewFinalCards(node,plan,plan.annotations);
  assert.equal((compact.match(/data-review-card=/g)||[]).length,3);
  assert.match(compact,/①效果/);assert.match(compact,/②效果/);
  assert.match(compact,/class="marked-note">红色备注 &lt;内容>/);
  assert(!compact.includes('效果原文'));assert(!compact.includes('location-icon'));
  assert.equal((compact.match(/class="marked-location"/g)||[]).length,1);
  assert.match(compact,/>我方墓地</);
  const detail=r.reviewFinalCards(node,plan,plan.annotations,{compact:false});
  assert.match(detail,/效果原文/);assert.match(detail,/location-icon/);
  assert.equal(JSON.stringify(plan),before);
});

test('saved management summaries retain full marked effects, positions and notes while confirmation stays compact',()=>{
  const r=setup(),cards=[{instance_id:1,code:10,name:'终场怪兽',controller:0,location:4,sequence:5,position:1}];
  const description='①：这是需要在展开管理完整保留的效果原文。②：未勾选的另一效果。';
  const note='完整保留的逐效果备注。'.repeat(35);
  const plan={catalog:{10:{desc:description}},final_state:{cards},annotations:{cards:{1:'此卡的完整实例说明'},final_marks:{1:{marked:true,effects:{0:{note}}}}}};
  r.reviewUI.report=plan;
  const before=JSON.stringify(plan),summary={final:{notes:'终场整体说明'}};
  const saved=r.summaryHtml(summary,plan),confirmation=r.summaryHtml(summary);
  assert.match(saved,/①：这是需要在展开管理完整保留的效果原文。/);
  assert(saved.includes(note));assert.match(saved,/此卡的完整实例说明/);assert.match(saved,/终场整体说明/);
  assert.match(saved,/location-icon/);assert.match(saved,/>我方 额外怪兽区 1</);
  assert(!saved.includes('②：未勾选的另一效果。'));
  assert(!confirmation.includes('效果原文'));assert(!confirmation.includes('location-icon'));
  assert.equal(JSON.stringify(plan),before);
});

test('compact operations restore small field mini maps and retain graveyard and overlay cost locations',()=>{
  const r=setup(),card={instance_id:1,code:10,name:'效果怪兽',location:4,controller:0,sequence:0};
  const cost={id:'2:0',message:50,cards:[card],origin:{location:128,controller:0},destination:{location:16,controller:0}};
  const summon={id:'3:0',message:63,cards:[card]};r.reviewUI.report={events:[cost,summon],catalog:{}};
  const html=r.reviewLogAction({id:'1:0',kind:'effect',cards:[card],costs:[cost],results:[summon],status:'resolved'},{id:'step',number:2});
  assert.match(html,/compact-card-location/);assert.match(html,/location-icon/);assert.match(html,/<svg/);
  assert.match(html,/我方素材/);assert.match(html,/我方墓地/);assert.match(html,/特殊召唤/);
});
test('compact cleanup omits only explicit rule material disposal and never a cost or effect',()=>{
  const r=setup(), e={id:'1:0',message:50,origin:{location:128},destination:{location:16},reason:1024};
  r.reviewUI.report={events:[e]};const a={id:e.id,kind:'action',evidence_refs:[e.id]};
  assert(r.compactCleanup(a));e.reason=0x20000400;assert(r.compactCleanup(a));e.cost=true;assert(!r.compactCleanup(a));delete e.cost;
  e.reason=64;assert(!r.compactCleanup(a));e.reason=1024;assert(!r.compactCleanup({...a,kind:'effect'}));
  assert.match(r.reviewLocationIcon({location:4,sequence:2,controller:0}),/<svg/);
});

function detailFixture() {
  let time=0,serial=0;const timers=new Map(),panel={hidden:true,focus(){},matches:()=>false};
  const r=setup({$:()=>panel,clearTimeout:id=>timers.delete(id),setTimeout:(fn,delay)=>{timers.set(++serial,{fn,due:time+delay});return serial;}});
  vm.runInContext('renderReviewDetail=()=>{};',r.context);
  const host={code:10,instance_id:1},material={code:11,instance_id:2},node={id:'step',action_ids:[],state:{cards:[host,material]}};
  const report={id:'fixture',review:{nodes:[node]}};r.reviewUI.report=report;
  const button=(key,inside=false)=>({dataset:{reviewCard:key},isConnected:true,hovered:true,closest:()=>inside?panel:null,matches(){return this.hovered;},getBoundingClientRect:()=>({left:1,right:50,top:20,bottom:100}),focus(){}});
  const outside=button('host'),nested=button('material',true);
  r.reviewUI.cards.set('host',{card:host,node:'step',report});r.reviewUI.cards.set('material',{card:material,node:'step',report});
  const advance=ms=>{time+=ms;for(const [id,t] of [...timers])if(t.due<=time){timers.delete(id);t.fn();}};
  return {...r,outside,nested,host,material,advance,timers};
}
test('material navigation keeps the external anchor and returns to the original material tab',()=>{
  const r=detailFixture();r.openReviewDetail(r.outside);r.reviewUI.materialTab=true;
  r.openReviewDetail(r.nested);r.nested.isConnected=false;
  assert.equal(r.reviewUI.selected,r.material);assert.equal(r.reviewUI.anchor.element,r.outside);assert.equal(r.reviewUI.detailHistory.length,1);
  assert.equal(r.reviewUI.detailPinned,true);r.backReviewDetail();
  assert.equal(r.reviewUI.selected,r.host);assert.equal(r.reviewUI.materialTab,true);assert.equal(r.reviewUI.detailHistory.length,0);
  r.closeReviewDetail();assert.equal(r.reviewUI.selected,null);
});
test('hover opens only after its delay, stale targets are canceled and pinned detail is stable',()=>{
  const r=detailFixture();r.scheduleReviewHover(r.outside);r.advance(399);assert.equal(r.reviewUI.selected,null);
  r.advance(1);assert.equal(r.reviewUI.selected,r.host);assert.equal(r.reviewUI.detailPinned,false);
  r.closeReviewDetail();r.scheduleReviewHover(r.outside);r.outside.hovered=false;r.advance(400);assert.equal(r.reviewUI.selected,null);
  r.outside.hovered=true;r.scheduleReviewHover(r.outside);r.closeReviewDetail();r.advance(400);assert.equal(r.reviewUI.selected,null);
  r.openReviewDetail(r.outside);r.scheduleReviewHover({...r.outside,dataset:{reviewCard:'material'}});r.advance(400);assert.equal(r.reviewUI.selected,r.host);
});

test('hidden review history cannot consume duel bindings, and modal settings suspend history navigation',()=>{
  const listeners={},r=setup({moduleUI:{current:'duel'},document:{addEventListener:(name,fn)=>{(listeners[name]??=[]).push(fn);},querySelector:()=>null},$:()=>({hidden:true})});
  r.context.app.view='history';r.reviewUI.nodes=[{id:'a'},{id:'b'}];r.reviewUI.node='a';
  let selected=0;r.context.selectReviewNode=()=>selected++;
  const event={key:'ArrowRight',target:{closest:()=>null},preventDefault(){this.defaultPrevented=true;}};
  listeners.keydown.forEach(fn=>fn(event));assert.equal(selected,0);assert(!event.defaultPrevented);
  r.context.moduleUI.current='expansion';r.context.document.querySelector=()=>({open:true});
  listeners.keydown.forEach(fn=>fn(event));assert.equal(selected,0);
  r.context.document.querySelector=()=>null;listeners.keydown.forEach(fn=>fn(event));assert.equal(selected,1);assert(event.defaultPrevented);
});

test('Balelynx replacement shows effect two and the prevention result only with matching native cause',()=>{
  const r=setup(),c={code:14812471,instance_id:54,name:'转生炎兽 烽火猞猁',controller:0,location:16};
  const e={id:'20:0',message:50,cards:[c],origin:{controller:0,location:16},destination:{controller:0,location:32,position:5},reason:64,
    cause:{owner_code:c.code,handler_code:c.code,handler_instance:54,event_code:50,effect_type:2058,range:16}};
  const a={id:e.id,kind:'action',cards:[c],evidence_refs:[e.id],summary:'除外'};
  const report={events:[e],actions:[a],catalog:{14812471:{desc:'①：检索。\n②：自己场上的「转生炎兽」卡被战斗·效果破坏的场合，可以作为代替把墓地的这张卡除外。'}}};
  const before=JSON.stringify(report);r.reviewUI.report=report;
  const html=r.reviewLogAction(a,{id:'step',number:2});
  assert.match(html,/②效果代替破坏/);assert.match(html,/代替我方「转生炎兽」卡被破坏/);assert(!html.includes('处理结果未记录'));
  assert.equal(JSON.stringify(report),before);
  for(const field of ['owner_code','handler_instance','event_code','effect_type','range']) {
    const saved=e.cause[field];e.cause[field]=999;
    assert.equal(r.context.appliedReplacement(a,report),null,field);e.cause[field]=saved;
  }
  e.reason=128;assert.equal(r.context.appliedReplacement(a,report),null);
});

test('opponent Infinite Impermanence is connected to the affected monster with costs and all evidence retained',()=>{
  const r=setup(),monster={code:10,instance_id:1,name:'我方怪兽',controller:0,location:4},trap={code:10045474,instance_id:2,name:'无限泡影',controller:1,location:8};
  const own={id:'1:0',activation_ref:'1:0',kind:'effect',status:'disabled',cards:[monster],evidence_refs:['1:0','4:0'],results:[],targets:[],costs:[]};
  const response={id:'2:0',activation_ref:'2:0',kind:'effect',status:'resolved',cards:[trap],engine_effect:{effect_type:0x10},targets:[monster],costs:[{message:100,text:'支付 1000 LP',cards:[]}],results:[{event_ref:'4:0',message:76,cards:[monster]}],evidence_refs:['2:0','4:0']};
  const negated={id:'4:0',message:76,resolution_source_ref:'2:0',activation_ref:'1:0',cards:[monster]};
  const report={actions:[own,response],events:[{id:'1:0'},{id:'2:0'},negated],catalog:{10:{type:1},10045474:{type:4}}};r.reviewUI.report=report;
  const before=JSON.stringify(report),group=r.context.groupedLogActions(report.actions,report);assert.equal(group.length,1);
  const html=r.reviewLogAction(group[0],{id:'step',number:2});
  for(const text of ['对方 发动陷阱卡','无限泡影','我方怪兽效果被无效','1000 LP','查看记录依据 · 3 条'])assert(html.includes(text),text);
  assert(!html.includes('处理结果未记录'));assert.equal(JSON.stringify(report),before);
  negated.resolution_source_ref=null;assert.equal(r.context.groupedLogActions(report.actions,report).length,2);
  negated.resolution_source_ref='2:0';assert.equal(r.context.groupedLogActions([own],report).length,1,'No action is removed from another step');
});

test('legacy Impermanence target and delayed disabled event form one observed sequence without rewriting causal evidence',()=>{
  const r=setup(),monster={code:2772337,instance_id:49,controller:0,location:4,name:'赐炎之咎姬'},trap={code:10045474,instance_id:97,controller:1,location:8,name:'无限泡影'};
  const own={id:'1:0',activation_ref:'1:0',kind:'effect',chain_group:1,chain_link:1,status:'disabled',cards:[monster],evidence_refs:['1:0','9:0'],results:[]};
  const response={id:'3:0',activation_ref:'3:0',kind:'effect',chain_group:1,chain_link:2,status:'resolved',cards:[trap],engine_effect:{owner_code:10045474,effect_type:26},targets:[],results:[],evidence_refs:['3:0','7:0']};
  const target={id:'4:0',kind:'target',cards:[monster],evidence_refs:['4:0']};
  const events=[{id:'1:0',message:70},{id:'2:0',message:71,activation_ref:'1:0'},
    {id:'3:0',message:70},{id:'4:0',message:83,targets:[monster]},{id:'5:0',message:71,activation_ref:'3:0'},
    {id:'6:0',message:72,activation_ref:'3:0'},{id:'7:0',message:73,activation_ref:'3:0'},
    {id:'8:0',message:72,activation_ref:'1:0'},{id:'9:0',message:76,activation_ref:'1:0',resolution_source_ref:'1:0'}];
  const report={actions:[own,response,target],events,catalog:{2772337:{type:1},10045474:{type:4}}};r.reviewUI.report=report;
  const before=JSON.stringify(report),group=r.context.groupedLogActions(report.actions,report);
  assert.equal(group.length,1);assert.equal(group[0]._interaction.direct,false);
  const html=r.reviewLogAction(group[0],{id:'step',number:2});
  assert.match(html,/无限泡影/);assert.match(html,/随后 我方怪兽效果被无效/);assert.match(html,/按实际对象与结算顺序连接/);
  assert(group[0]._interaction.source.evidence_refs.includes('4:0'));
  assert.equal(JSON.stringify(report),before);
  response.status='negated';assert.equal(r.context.negationLinks(report).length,0);
  response.status='resolved';events[3].targets=[{...monster,instance_id:50}];assert.equal(r.context.negationLinks(report).length,0);
});
