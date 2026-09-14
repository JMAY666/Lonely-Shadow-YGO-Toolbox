const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../src/trainer/web/timeline.js'),'utf8');
function setup() {
  const context = vm.createContext({$:()=>({}),escape:s=>String(s).replaceAll('<','&lt;').replaceAll('"','&quot;')});
  vm.runInContext(source.slice(0,source.indexOf('async function refreshTimeline'))+'\nglobalThis.view={renderRewind,rewindState,resetTimelineSession};',context);
  return context.view;
}
test('initial/current/future nodes preserve action numbers and expose a single restore boundary for a chain',()=>{
  const {renderRewind}=setup();
  const step=n=>({number:n,kind:'effect',cards:[{code:1,name:'<牌>'}],summary:'test'});
  const html=renderRewind({available:true,cursor:2,at_node:true,nodes:[
    {id:1,ordinal:0,initial:true,steps:[],turn:1,phase:4,lp:[8000]},
    {id:2,ordinal:1,steps:[step(1),step(2)],turn:1,phase:4,lp:[7000]},
    {id:3,ordinal:2,steps:[step(3)],turn:1,phase:4,lp:[7000]}],pending:[]});
  assert.match(html,/初始状态/);
  assert.match(html,/data-rewind="2" aria-current="step" disabled/);
  assert.match(html,/步骤 1/);assert.match(html,/步骤 2/);assert.match(html,/步骤 3/);
  assert.match(html,/作为一组恢复/);assert.match(html,/rewind-future/);
  assert(!html.includes('<牌>'));
});
test('ending or replacing a session releases old restore locks and invalidates late timeline responses',()=>{
  const {rewindState:s,resetTimelineSession}=setup();
  Object.assign(s,{id:'old',busy:true,submitting:true,data:{id:'old'},operation:'old-op'});
  const generation=s.generation;
  resetTimelineSession(null);
  assert.equal(s.busy,false);assert.equal(s.submitting,false);assert.equal(s.data,null);
  assert(s.generation>generation);
  resetTimelineSession('new');assert.equal(s.id,'new');assert.equal(s.operation,null);
});
test('restore locks all nodes, while unfinished chain steps never become restore buttons',()=>{
  const {renderRewind,rewindState}=setup();rewindState.busy=true;
  const html=renderRewind({available:true,cursor:1,at_node:false,nodes:[{id:1,ordinal:0,initial:true,steps:[],turn:1,phase:4,lp:[8000]}],
    pending:[{number:1,kind:'action',cards:[],summary:'待处理'}]});
  assert.match(html,/data-rewind="1" aria-current="step" disabled/);
  assert.equal((html.match(/data-rewind/g)||[]).length,1);
  assert.match(html,/正在处理/);
});
