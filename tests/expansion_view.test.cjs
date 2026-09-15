const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const source=readFileSync(path.join(__dirname,'../src/trainer/web/expansion.js'),'utf8');
const tagViewSource=readFileSync(path.join(__dirname,'../src/trainer/web/deck-tag-view.js'),'utf8');
function setup(){
  const elements=new Map();
  const node=s=>{if(!elements.has(s))elements.set(s,{textContent:'',innerHTML:'',value:'',hidden:false,disabled:false,close(){this.closed=true;},classList:{toggle(){}},focus(){}});return elements.get(s);};
  let clock=0;const timers=new Map();let next=0;
  const context=vm.createContext({$:node,app:{active:null,dirty:false},notice(){},structuredClone,
    performance:{now:()=>clock},setInterval:fn=>{timers.set(++next,fn);return next;},clearInterval:id=>timers.delete(id),
    escape:s=>String(s??'').replaceAll('<','&lt;'),run:fn=>fn,window:{},document:{},
    api:async()=>{throw Error('unexpected request');}});
  vm.runInContext(tagViewSource+source.slice(0,source.indexOf("$('#start-training').onclick"))+'\nglobalThis.e={flow,conditionError,chooseOpening,renderChoices,renderDesign,prepareDraft,savePlan,unsavedSummary,allowReportChange,resizeSlots,handError,resetTimer,startTimer,stopTimer,timerValue,renderTimer,deleteDraft,finishDesignDeckEdit};',context);
  const d={name:'方案',deck:{main:[1,1,...Array(38).fill(2)],extra:[3],side:[4]},catalog:{1:{id:1,name:'甲'},2:{id:2,name:'乙'}},conditions:{slots:[null,null,null,null,null],banned:[]}};
  context.e.flow.design=d;
  return {...context.e,context,node,d,tick(ms){clock+=ms;for(const fn of [...timers.values()])fn();},timers};
}

test('slot selection enforces copies, replacement does not double-count, and removal reopens capacity',()=>{
  const e=setup();e.chooseOpening(1);e.flow.slot=1;e.chooseOpening(1);e.flow.slot=2;e.chooseOpening(1);
  assert.deepEqual(e.d.conditions.slots,[1,1,null,null,null]);
  assert.match(e.node('#opening-error').textContent,/只有 2 张.*指定 3 张/);
  e.flow.slot=0;e.chooseOpening(1);assert.equal(e.d.conditions.slots.filter(c=>c===1).length,2);
  e.chooseOpening(2);e.flow.slot=2;e.chooseOpening(1);assert.equal(e.d.conditions.slots[2],1);
});
test('changing actual count preserves overflow selections and detects removed cards without crashing',()=>{
  const e=setup();e.d.conditions.slots=[null,1,null,null,2];
  e.resizeSlots(e.d,1);assert.deepEqual(e.d.conditions.slots,[null,1,null,null,2]);
  assert.match(e.conditionError(e.d),/超出数量/);e.renderDesign();assert.match(e.node('#opening-slots').innerHTML,/overflow-slot/);
  e.d.conditions.slots[4]=null;e.d.conditions.slots[1]=null;e.resizeSlots(e.d,1);
  assert.deepEqual(e.d.conditions.slots,[null]);e.d.conditions.banned=[1];assert.equal(e.conditionError(e.d),'');
  e.d.conditions.slots=[1];assert.match(e.conditionError(e.d),/同时被指定和禁用/);
  e.d.conditions.banned=[];e.d.deck.main=Array(40).fill(2);assert.match(e.conditionError(e.d),/已不在当前主卡组/);e.renderDesign();
  e.resizeSlots(e.d,null);assert.match(e.conditionError(e.d),/起手数量请输入/);
});
test('opponent selection uses its own stock and editing validation includes LP and time settings',()=>{
  const e=setup();e.d.opponent_ai=true;e.d.opponent_config={name:'对手',deck:{main:Array(40).fill(2),extra:[],side:[]},conditions:{hand_count:2,slots:[null,null],banned:[]}};
  e.flow.target='opponent';e.chooseOpening(2);assert.deepEqual(e.d.conditions.slots,[null,null,null,null,null]);
  assert.deepEqual(e.d.opponent_config.conditions.slots,[2,null]);e.renderChoices();assert(!e.node('#opening-choices').innerHTML.includes('data-choice="1"'));
  for(const lp of [null,0,-1,1.5,2147483648]){e.d.player_lp=lp;assert.match(e.conditionError(e.d),/玩家初始 LP/);}
  e.d.player_lp=1;e.d.opponent_lp=2147483647;e.d.timer={mode:'down',seconds:0};assert.match(e.conditionError(e.d),/计时时长/);
  e.d.timer.seconds=1;assert.equal(e.conditionError(e.d),'');
});
test('shared deck apply locks duplicate clicks, preserves edits on failure and restores the original editor',async()=>{
  const e=setup(), original=structuredClone(e.d.deck),edited={main:Array(40).fill(2),extra:[],side:[]};
  e.context.app.deck=edited;e.context.app.id=null;e.node('#deck-name').value='训练卡组';
  e.flow.deckEdit={target:'player',name:'来源卡组',restore:{deck:original,id:'source'}};
  for(const fn of ['updateStart','dirty','switchView'])e.context[fn]=()=>{};
  e.context.renderDeck=async()=>{};e.context.deckList=async()=>{};
  let reject,calls=0;e.context.card=()=>{calls++;return new Promise((_,r)=>reject=r);};
  const first=e.finishDesignDeckEdit(true);await e.finishDesignDeckEdit(true);assert.equal(calls,1);
  reject(Error('读取失败'));await assert.rejects(first,/读取失败/);assert(e.flow.deckEdit);assert.equal(e.context.app.busy,false);
  assert.deepEqual(e.d.deck,original);assert.deepEqual(e.context.app.deck,edited);
  e.context.card=async id=>({id,name:'乙'});await e.finishDesignDeckEdit(true);
  assert.deepEqual(e.d.deck,edited);assert.equal(e.flow.deckEdit,null);assert.equal(e.context.app.id,'source');assert.deepEqual(e.context.app.deck,original);
});
test('timer starts only on readiness, uses overall elapsed time, stops, resets and expires once',()=>{
  const e=setup(),messages=[];e.context.notice=m=>messages.push(m);
  e.resetTimer('one',{mode:'up',seconds:7});e.tick(5000);assert.equal(e.timerValue(e.flow.timer),7);
  e.startTimer('stale');e.tick(1000);assert.equal(e.timerValue(e.flow.timer),7);
  e.startTimer('one');e.tick(2100);assert.equal(e.timerValue(e.flow.timer),9);e.startTimer('one');assert.equal(e.timers.size,1);
  e.stopTimer();e.tick(5000);assert.equal(e.timerValue(e.flow.timer),9);assert.equal(e.timers.size,0);
  e.resetTimer('two',{mode:'down',seconds:2});e.startTimer('two');e.tick(2000);
  assert.equal(e.timerValue(e.flow.timer),0);assert.equal(e.timers.size,0);assert.equal(e.node('#timer-expired').hidden,false);
  e.renderTimer();e.tick(5000);assert.equal(messages.length,1);
  e.resetTimer('off',{mode:'off',seconds:0});e.startTimer('off');assert.equal(e.timers.size,0);assert.equal(e.node('#expansion-timer').hidden,true);
});
test('draft deletion cancel or failure retains current content, success affects only the selected id',async()=>{
  const e=setup();e.flow.design=null;e.prepareDraft({id:'target',plan_stage:'draft',expansion:{name:'草稿',notes:''}});
  e.flow.draft.notes='尚未保存';let requests=[];e.context.confirmFlow=async()=>false;
  e.context.api=async(...args)=>{requests.push(args);throw Error('删除失败');};
  await e.deleteDraft();assert.equal(requests.length,0);assert.equal(e.flow.draft.notes,'尚未保存');
  e.context.confirmFlow=async()=>true;await assert.rejects(e.deleteDraft(),/删除失败/);assert.equal(e.flow.draft.notes,'尚未保存');
  assert.match(e.node('#draft-message').textContent,/当前内容已保留/);
  e.context.api=async(...args)=>{requests.push(args);return {};};e.context.refreshPlans=async()=>{};e.context.refreshHistory=async()=>{};e.context.switchView=()=>{};
  await e.deleteDraft();assert.equal(e.flow.draft,null);assert.equal(requests.at(-1)[0],'/api/drafts/discard');assert.equal(requests.at(-1)[1].id,'target');
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
  e.context.showPlan=async id=>{assert.equal(await e.allowReportChange(id),true);throw Error('查看暂不可用');};
  const notices=[];e.context.notice=text=>notices.push(text);
  await e.savePlan();
  assert.equal(e.flow.draft,null);assert.equal(e.flow.busy,false);
  assert(notices.every(message=>message.includes('已保存')));
  assert(!e.node('#draft-message').textContent.includes('保存失败'));
});
