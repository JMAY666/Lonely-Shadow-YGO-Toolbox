const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname,'../src/trainer/web/deck-tags.js'),'utf8');

function setup() {
  const nodes = new Map();
  const $ = key => {
    if (!nodes.has(key)) nodes.set(key,{value:'',textContent:'',innerHTML:'',open:true,
      setAttribute(){},focus(){},close(){this.open=false;},showModal(){this.open=true;}});
    return nodes.get(key);
  };
  const context = vm.createContext({$,structuredClone,setTimeout:()=>1,clearTimeout(){},escape:s=>s,
    tagSearchKey:s=>s.toLowerCase(),zones:['main','extra','side'],zoneNames:{main:'主',extra:'额外',side:'副'},
    app:{busy:false,deckEpoch:1,deck:{main:[1],extra:[],side:[]},deckTags:{tag_ids:['a'],primary_ids:['a']},deckTagNames:{a:'甲'}},
    activeDesignDeckEdit:()=>false,card:async id=>({id,name:'测试卡'}),deckList:async()=>{},
    api:async()=>({tags:[],suggestions:{tag_ids:[],primary_ids:[],candidates:[]}}),dirty(){context.app.dirty=true;},
    setDeckTags(value,names){context.app.deckTags=structuredClone(value);context.app.deckTagNames={...names};}});
  vm.runInContext(source.slice(0,source.indexOf("$('#deck-tags-button').onclick"))+'\nglobalThis.e={deckTagUI,setDeckTagRole,searchDeckTags,openDeckTags,closeDeckTags,applyDeckTags,refreshDeckTagName};',context);
  const ui=context.e.deckTagUI;
  Object.assign(ui,{epoch:1,deck:context.app.deck,draft:{tag_ids:['a'],primary_ids:['a']},names:{a:'甲'},tags:[],suggestions:null});
  return {context,ui,$,...context.e};
}
const plain = value=>JSON.parse(JSON.stringify(value));
const deferred = () => {let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

test('shared tag renaming refreshes current and suspended editor labels without changing selections or dirty state',()=>{
  const e=setup(),buffer={deckTags:{tag_ids:['a'],primary_ids:[]},deckTagNames:{a:'甲'},dirty:true};
  e.context.moduleUI={editors:{decks:{state:buffer},expansion:null}};
  e.refreshDeckTagName({id:'a',name:'新正名'});
  assert.equal(e.context.app.deckTagNames.a,'新正名');assert.equal(buffer.deckTagNames.a,'新正名');
  assert.deepEqual(plain(e.context.app.deckTags),{tag_ids:['a'],primary_ids:['a']});
  assert.equal(buffer.dirty,true);assert.equal(e.context.app.dirty,undefined);
});
test('role changes do not duplicate a tag, allow multiple primaries and remove it from both lists',()=>{
  const e=setup();e.setDeckTagRole('b','primary');e.setDeckTagRole('b','primary');
  assert.deepEqual(plain(e.ui.draft),{tag_ids:['a','b'],primary_ids:['a','b']});
  e.setDeckTagRole('a','secondary');assert.deepEqual(plain(e.ui.draft.primary_ids),['b']);
  e.setDeckTagRole('b','');assert.deepEqual(plain(e.ui.draft),{tag_ids:['a'],primary_ids:[]});
  assert.deepEqual(plain(e.context.app.deckTags),{tag_ids:['a'],primary_ids:['a']});
  e.ui.draft.tag_ids=Array.from({length:30},(_,i)=>String(i));e.setDeckTagRole('overflow','secondary');
  assert.equal(e.ui.draft.tag_ids.length,30);assert.match(e.$('#deck-tags-status').textContent,/30/);
});
test('late tag search responses cannot replace newer results or a closed picker',async()=>{
  const e=setup(),first=deferred(),second=deferred();let calls=0;
  e.context.api=()=>++calls===1?first.promise:second.promise;
  const old=e.searchDeckTags(),latest=e.searchDeckTags();
  second.resolve({tags:[{id:'b',name:'乙',aliases:[],deck_card_ids:[]}],suggestions:{tag_ids:[],primary_ids:[],candidates:[]}});await latest;
  e.closeDeckTags();first.resolve({tags:[{id:'a',name:'甲'}],suggestions:{}});await old;
  assert.equal(e.ui.tags[0].id,'b');assert.equal(e.$('#deck-tags-dialog').open,false);
  assert.deepEqual(plain(e.context.app.deckTags),{tag_ids:['a'],primary_ids:['a']});
});
test('failed search retains the draft and reports a recoverable error',async()=>{
  const e=setup();e.context.api=async()=>{throw Error('synthetic search failure');};
  await e.searchDeckTags();
  assert.deepEqual(plain(e.ui.draft),{tag_ids:['a'],primary_ids:['a']});
  assert.equal(e.ui.busy,false);assert.match(e.$('#deck-tags-status').textContent,/已有选择仍保留/);
});
test('typing during card loading does not lose the deck card chooser',async()=>{
  const e=setup(),pending=deferred();e.$('#deck-tags-dialog').open=false;e.context.card=()=>pending.promise;
  const opening=e.openDeckTags();++e.ui.serial;e.$('#deck-tags-search').value='new query';
  pending.resolve({id:1,name:'测试卡'});await opening;
  assert.equal(e.ui.cards.length,1);assert.equal(e.ui.cards[0].counts.main,1);
});
test('apply copies the draft into the editor and refuses a changed deck epoch',()=>{
  const e=setup();e.ui.draft={tag_ids:['b'],primary_ids:['b']};
  e.applyDeckTags();assert.deepEqual(plain(e.context.app.deckTags),{tag_ids:['b'],primary_ids:['b']});
  e.ui.draft.tag_ids.push('c');assert.equal(e.context.app.deckTags.tag_ids.length,1);
  assert.equal(e.context.app.dirty,true);e.context.app.deckEpoch=2;e.applyDeckTags();
  assert.equal(e.context.app.deckTags.tag_ids.length,1);
});
