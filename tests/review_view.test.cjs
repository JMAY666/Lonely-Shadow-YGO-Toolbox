const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const source=readFileSync(path.join(__dirname,'../src/trainer/web/review.js'),'utf8');
function setup(){
  const context=vm.createContext({flow:{draft:null},app:{},Map,structuredClone,CSS:{escape:s=>s},
    escape:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    document:{addEventListener(){}},eventSummary:e=>e.result||e.type||'',zoneNames:{},dt:()=>'',stageNames:{}});
  vm.runInContext(source+'\nglobalThis.r={reviewUI,renderBoard,reviewCard,reviewLogAction,provenance,reviewTitle,reviewFallback,previewReview,summaryHtml,reviewRandomDraw,reviewFinalCards,reviewEffectParts,compactCleanup,reviewLocationIcon};',context);
  return {...context.r,context};
}
test('XYZ host shows its own body plus material count, while attached copies do not occupy monster slots',()=>{
  const r=setup();r.reviewUI.report={catalog:{10:{type:0x800001}}};
  const node={id:'step',number:2,kind:'step',state:{cards:[{instance_id:1,code:10,controller:0,location:4,sequence:0},
    {instance_id:2,code:11,controller:0,location:128,sequence:0,overlay_target:1},
    {instance_id:3,code:11,controller:0,location:128,sequence:1,overlay_target:1}]}};
  const html=r.renderBoard(node);
  assert.match(html,/素材 ×2/);assert.equal((html.match(/data-review-card=/g)||[]).length,1);
  assert(!html.includes('opponent-board'));
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
  assert.match(html,/具体效果待补充/);assert.match(html,/aria-describedby=/);assert.match(html,/role="tooltip"/);
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
  assert.match(failed,/发动被无效/);assert.match(failed,/Cost · 送墓/);assert.match(failed,/处理结果未记录/);
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
test('compact cleanup omits only explicit rule material disposal and never a cost or effect',()=>{
  const r=setup(), e={id:'1:0',message:50,origin:{location:128},destination:{location:16},reason:1024};
  r.reviewUI.report={events:[e]};const a={id:e.id,kind:'action',evidence_refs:[e.id]};
  assert(r.compactCleanup(a));e.reason=0x20000400;assert(r.compactCleanup(a));e.cost=true;assert(!r.compactCleanup(a));delete e.cost;
  e.reason=64;assert(!r.compactCleanup(a));e.reason=1024;assert(!r.compactCleanup({...a,kind:'effect'}));
  assert.match(r.reviewLocationIcon({location:4,sequence:2,controller:0}),/<svg/);
});
