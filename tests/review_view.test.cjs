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
  vm.runInContext(source+'\nglobalThis.r={reviewUI,renderBoard,reviewCard,reviewLogAction,provenance,reviewTitle,reviewFallback,previewReview};',context);
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
test('provenance stops at selected boundary and never merges an identical-name copy',()=>{
  const r=setup();const c={instance_id:1,code:10,name:'同名卡',controller:0,location:2};
  r.reviewUI.nodes=[{id:'initial',number:1,state_ref:2,action_ids:[]},{id:'step',number:2,state_ref:4,action_ids:[]}];
  r.reviewUI.report={initial_hand:[c],events:[{id:'4:0',native_seq:4,message:61,cards:[{...c,location:4,sequence:0}]},
    {id:'6:0',native_seq:6,message:50,cards:[c],origin:c,destination:{controller:0,location:16}},
    {id:'3:0',native_seq:3,message:50,cards:[{...c,instance_id:2}],origin:c,destination:{controller:0,location:32}}]};
  const history=r.provenance(c,r.reviewUI.nodes[1]);
  assert.equal(history.length,2);assert.match(history[1].text,/通常召唤/);assert(!JSON.stringify(history).includes('除外'));
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
