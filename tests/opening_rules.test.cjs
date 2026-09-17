const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const source=readFileSync(path.join(__dirname,'../src/trainer/web/opening-rules.js'),'utf8');
function setup(api=async()=>({valid:true,errors:[],warnings:[]})){
  let renders=0;
  const ctx=vm.createContext({api,app:{catalogEpoch:0},flow:{design:null},renderDesign(){renders++;},structuredClone});
  vm.runInContext(source+'\nglobalThis.rules=OpeningRules;',ctx);
  return {rules:ctx.rules,ctx,renders:()=>renders};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('condition faces and summaries escape user card names and retain grouping',()=>{
  const {rules}=setup(),c=rules.tuner(3);
  assert.equal(rules.describe(c),'任意等级 3 调整');
  const r={kind:'condition',version:1,rule:{op:'any',items:[c.rule,{op:'not',items:[{field:'code',op:'in',values:[1]}]}]}};
  const html=rules.face(r,{1:{name:'<script>unsafe</script>'}});
  assert(!html.includes('<script>'));assert(html.includes(' 或 '));assert(html.includes('排除（'));
  const plan={catalog:{1:{name:'实例'}},expansion:{conditions:{slots:[c],banned:[r]},actual_opening:[1]}};
  assert.match(rules.summary(plan),/起手（实例）/);assert.match(rules.summary(plan),/其他候选/);
});
test('authoritative preview ignores stale replies and invalidates when deck, conditions or catalog changes',async()=>{
  const replies=[],e=setup(body=>new Promise(resolve=>replies.push(resolve)));
  const d={deck:{main:[1,2],extra:[],side:[]},conditions:{hand_count:1,slots:[e.rules.tuner(1)],banned:[]}};
  e.ctx.flow.design=d;assert.match(e.rules.error(d),/正在校验/);await tick();
  d.conditions.slots[0]=e.rules.tuner(2);assert.match(e.rules.error(d),/正在校验/);await tick();
  replies[0]({valid:false,errors:['旧错误'],warnings:[]});await tick();assert.equal(e.renders(),0);
  replies[1]({valid:true,errors:[],warnings:[]});await tick();assert.equal(e.rules.error(d),'');
  d.deck.main=[1];assert.match(e.rules.error(d),/正在校验/);await tick();replies[2]({valid:false,errors:['空候选'],warnings:[]});await tick();assert.equal(e.rules.error(d),'空候选');
  e.ctx.app.catalogEpoch++;assert.match(e.rules.error(d),/正在校验/);await tick();assert.equal(replies.length,4);
});
