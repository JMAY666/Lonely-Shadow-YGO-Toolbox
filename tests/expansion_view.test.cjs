const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const source=readFileSync(path.join(__dirname,'../src/trainer/web/expansion.js'),'utf8');
function setup(){
  const elements=new Map();
  const node=s=>{if(!elements.has(s))elements.set(s,{textContent:'',innerHTML:'',value:'',hidden:false,disabled:false,close(){this.closed=true;},classList:{toggle(){}},focus(){}});return elements.get(s);};
  const context=vm.createContext({$:node,app:{active:null,dirty:false},notice(){},structuredClone,
    escape:s=>String(s??'').replaceAll('<','&lt;'),run:fn=>fn,window:{},document:{},
    api:async()=>{throw Error('unexpected request');}});
  vm.runInContext(source.slice(0,source.indexOf("$('#start-training').onclick"))+'\nglobalThis.e={flow,conditionError,chooseOpening,renderChoices,renderDesign,prepareDraft,savePlan,unsavedSummary,allowReportChange};',context);
  const d={name:'方案',deck:{main:[1,1,...Array(38).fill(2)],extra:[3],side:[4]},catalog:{1:{id:1,name:'甲'},2:{id:2,name:'乙'}},conditions:{slots:[null,null,null,null,null],banned:[]}};
  context.e.flow.design=d;
  return {...context.e,context,node,d};
}

test('slot selection enforces copies, replacement does not double-count, and removal reopens capacity',()=>{
  const e=setup();e.chooseOpening(1);e.flow.slot=1;e.chooseOpening(1);e.flow.slot=2;e.chooseOpening(1);
  assert.deepEqual(e.d.conditions.slots,[1,1,null,null,null]);
  assert.match(e.node('#opening-error').textContent,/只有 2 张.*指定 3 张/);
  e.flow.slot=0;e.chooseOpening(1);assert.equal(e.d.conditions.slots.filter(c=>c===1).length,2);
  e.chooseOpening(2);e.flow.slot=2;e.chooseOpening(1);assert.equal(e.d.conditions.slots[2],1);
});
test('conflicts are visible and never overwrite either setting; bans use no slot',()=>{
  const e=setup();e.chooseOpening(1);e.flow.mode='banned';e.chooseOpening(1);
  assert.deepEqual(e.d.conditions.banned,[]);assert.match(e.node('#opening-error').textContent,/已被指定/);
  e.chooseOpening(2);assert.deepEqual(e.d.conditions.banned,[2]);assert.deepEqual(e.d.conditions.slots,[1,null,null,null,null]);
  e.flow.slot=1;e.flow.mode='required';e.chooseOpening(2);assert.equal(e.d.conditions.slots[1],null);assert.match(e.node('#opening-error').textContent,/已被禁用/);
  assert.match(e.conditionError(e.d),/只剩 1 张.*需要 4 张/);
});
test('choice list contains main cards only with total, assigned and remaining counts',()=>{
  const e=setup();e.chooseOpening(1);e.renderChoices();const html=e.node('#opening-choices').innerHTML;
  assert.match(html,/牌组内 2 张 · 已指定 1 张 · 剩余可指定 1 张/);
  assert(!html.includes('data-choice="3"'));assert(!html.includes('data-choice="4"'));
  e.d.name='   ';assert.match(e.conditionError(e.d),/先填写方案名称/);
});
test('saving locks duplicate requests and a failure retains edited text and retry controls',async()=>{
  const e=setup();e.flow.design=null;
  e.prepareDraft({id:'draft',plan_stage:'draft',expansion:{name:'原名',notes:'原备注'}});
  e.flow.draft.name='新名';e.flow.draft.notes='新备注';
  let calls=0,reject;
  e.context.api=()=>{calls++;return new Promise((_,r)=>reject=r);};
  const first=e.savePlan();await e.savePlan();assert.equal(calls,1);assert(e.node('#draft-name').disabled);
  reject(Error('磁盘失败'));await assert.rejects(first,/磁盘失败/);
  assert.equal(e.flow.draft.name,'新名');assert.equal(e.flow.draft.notes,'新备注');
  assert.equal(e.node('#save-plan').disabled,false);assert.equal(e.node('#draft-name').disabled,false);
  assert.match(e.node('#draft-message').textContent,/内容已保留/);assert.match(e.unsavedSummary(),/尚未保存/);
});
test('save confirmation stays successful when a later view refresh fails; pending save prevents draft replacement',async()=>{
  const e=setup();e.flow.design=null;
  e.prepareDraft({id:'draft',plan_stage:'draft',expansion:{name:'已确认方案',notes:''}});
  e.context.api=async()=>{
    assert.equal(await e.allowReportChange('another-draft'),false);
    return {id:'draft',name:'已确认方案'};
  };
  e.context.refreshHistory=async()=>{throw Error('列表暂不可用');};
  e.context.showPlan=async()=>{throw Error('查看暂不可用');};
  const notices=[];e.context.notice=text=>notices.push(text);
  await e.savePlan();
  assert.equal(e.flow.draft,null);assert.equal(e.flow.busy,false);
  assert(notices.every(message=>message.includes('已保存')));
  assert(!e.node('#draft-message').textContent.includes('保存失败'));
});
