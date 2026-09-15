const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname,'../src/trainer/web/deck-selection.js'),'utf8');
const plain = value => JSON.parse(JSON.stringify(value));
function setup() {
  const elements = new Map(), calls = [], designs = [];
  const node = selector => {
    if (!elements.has(selector)) elements.set(selector,{hidden:false,disabled:false,innerHTML:'',textContent:'',querySelectorAll:()=>[],setAttribute(name,value){this[name]=value;},focus(){this.focused=true;}});
    return elements.get(selector);
  };
  const saved = {id:'library/saved.ydk',name:'已保存卡组',revision:'one',deck:{main:[11,11,12],extra:[21],side:[31]}};
  const app = {busy:false,active:null,dirty:true,deck:{main:[99],extra:[],side:[]},id:'library/editor.ydk',undo:[{main:[98]}],cache:new Map()};
  const context = vm.createContext({$:node,app,structuredClone,flow:{design:null},window:{},navigator:{},notice(){},
    closeReviewDetail(){},pruneReviewCards(){},reviewCard:c=>`<button data-review-card="${c.code}"></button>`,
    handCount:d=>d.conditions.hand_count??5,cardName:(_d,code)=>`卡牌 ${code}`,renderDesign(){},
    zones:['main','extra','side'],zoneNames:{main:'主卡组',extra:'额外卡组',side:'副卡组'},
    escape:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    api:async(url,body)=>{calls.push({url,body});assert.equal(body,undefined);return structuredClone(saved);},
    card:async id=>{const value={id,name:`卡牌 ${id}`,desc:'效果<原文>',type:1,level:4,atk:1000,def:500};app.cache.set(id,value);return value;},
    openDesign:async selected=>designs.push(plain(selected)),updateStart:()=>context.updateDeckSelectionControls()});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/trainer/web/deck-tag-view.js'),'utf8')+source.slice(0,source.indexOf("$('#selection-list').addEventListener"))+'\nglobalThis.selection=deckSelection;',context);
  return {context,app,saved,calls,designs,node,state:context.selection};
}
test('preview and confirmation read saved data without changing dirty editors, source or card order',async()=>{
  const e=setup(), before=plain(e.app);
  await e.context.previewExpansionDeck(e.saved.id);
  assert.deepEqual(plain(e.state.selected),e.saved);
  assert.equal(e.node('#selection-name').textContent,e.saved.name);
  assert.match(e.node('#selection-cards').innerHTML,/主卡组[\s\S]*data-review-card="11"[\s\S]*data-review-card="11"[\s\S]*data-review-card="12"[\s\S]*额外卡组[\s\S]*副卡组/);
  assert(!/data-detail=|data-add=|data-remove=|draggable="true"/.test(e.node('#selection-cards').innerHTML));
  assert(!e.node('#selection-cards').innerHTML.includes('<input'));
  assert.equal(e.node('#selection-next').disabled,false);
  assert.equal(e.node('#selection-next').focused,true);
  await e.context.confirmExpansionDeck();
  assert.deepEqual(e.designs,[{...e.saved,quick_cards:[]}]);
  assert.deepEqual(plain(e.app),before);
  assert.equal(e.calls.length,2);
});
test('returning to the list cancels a pending preview and prevents stale confirmation',async()=>{
  const e=setup();let resolve;
  e.context.api=()=>new Promise(r=>{resolve=r;});
  const pending=e.context.previewExpansionDeck('old');
  assert.equal(e.node('#selection-next').disabled,true);
  e.context.backToDeckSelection();
  resolve(e.saved);await pending;
  assert.equal(e.state.selected,null);
  assert.equal(e.node('#selection-list-page').hidden,false);
  await e.context.confirmExpansionDeck();assert.equal(e.designs.length,0);
});
test('a late preview response never replaces the newer choice',async()=>{
  const e=setup(), resolves=[];
  e.context.api=()=>new Promise(r=>resolves.push(r));
  const first=e.context.previewExpansionDeck('old'),second=e.context.previewExpansionDeck('new');
  resolves[1]({...e.saved,id:'new',name:'新选择'});await second;
  resolves[0]({...e.saved,id:'old',name:'旧选择'});await first;
  assert.equal(e.state.selected.id,'new');assert.equal(e.node('#selection-name').textContent,'新选择');
});
test('a changed revision refreshes the preview and needs another confirmation',async()=>{
  const e=setup();await e.context.previewExpansionDeck(e.saved.id);
  e.state.picks.add('main:1');
  e.saved.revision='two';e.saved.name='更新后的名称';e.saved.deck.main.push(12);
  await e.context.confirmExpansionDeck();
  assert.equal(e.designs.length,0);assert.match(e.node('#selection-message').textContent,/卡组已更新/);
  assert.equal(e.node('#selection-name').textContent,'更新后的名称');
  assert.deepEqual(plain(e.state.selected.deck),e.saved.deck);
  assert.equal(e.state.picks.size,0);
  await e.context.confirmExpansionDeck();assert.deepEqual(e.designs,[{...e.saved,quick_cards:[]}]);
});
test('failed or deleted decks keep the next step unavailable or retryable without starting a design',async()=>{
  const e=setup(), api=e.context.api;
  e.context.api=async()=>{throw Error('卡组不存在');};
  await e.context.previewExpansionDeck('missing');
  assert.equal(e.state.selected,null);assert.equal(e.node('#selection-next').disabled,true);
  assert.match(e.node('#selection-message').textContent,/卡组不存在/);
  e.context.api=api;await e.context.previewExpansionDeck(e.saved.id);
  e.context.api=async()=>{throw Error('读取失败');};
  await e.context.confirmExpansionDeck();
  assert.equal(e.state.busy,false);assert.equal(e.app.busy,false);assert.equal(e.designs.length,0);
  assert.match(e.node('#selection-message').textContent,/读取失败/);
  e.context.api=api;await e.context.confirmExpansionDeck();assert.equal(e.designs.length,1);
});
test('duplicate confirmations and active sessions cannot start another design',async()=>{
  const e=setup();await e.context.previewExpansionDeck(e.saved.id);
  let resolve;e.context.api=()=>new Promise(r=>{resolve=r;});
  const first=e.context.confirmExpansionDeck();await e.context.confirmExpansionDeck();
  assert.equal(e.node('#selection-next').disabled,true);
  resolve(e.saved);await first;assert.equal(e.designs.length,1);
  e.app.active={id:'running'};e.context.updateDeckSelectionControls();
  assert.equal(e.node('#selection-next').disabled,true);
  await e.context.confirmExpansionDeck();assert.equal(e.designs.length,1);
});
test('selection lists have no management controls and explain an empty library',()=>{
  const e=setup();e.context.renderDeckSelectionList([{id:'library/a',name:'<名称>',source:'library'}]);
  assert.match(e.node('#selection-list').innerHTML,/预览卡组：&lt;名称>/);
  assert(!/data-open-deck|data-deck-menu|data-create-deck|改名|删除|导入/.test(e.node('#selection-list').innerHTML));
  e.context.renderDeckSelectionList([]);
  assert.match(e.node('#selection-list').innerHTML,/暂无可用卡组/);
});
test('popup marks preserve separate copies across a same-deck preview and travel only as candidates',async()=>{
  const e=setup();await e.context.previewExpansionDeck(e.saved.id);
  for(const key of ['main:0','main:1','extra:0']) e.state.picks.add(key);
  assert.deepEqual(plain(e.context.selectedDeckCards()),[{code:11,zone:'main'},{code:11,zone:'main'},{code:21,zone:'extra'}]);
  e.context.backToDeckSelection();await e.context.previewExpansionDeck(e.saved.id);
  assert.equal(e.state.picks.size,3);
  await e.context.confirmExpansionDeck();
  assert.deepEqual(e.designs[0].quick_cards,[{code:11,zone:'main'},{code:11,zone:'main'},{code:21,zone:'extra'}]);
  assert.deepEqual(e.designs[0].deck,e.saved.deck);
  e.saved.id='library/other.ydk';await e.context.previewExpansionDeck(e.saved.id);assert.equal(e.state.picks.size,0);
});
test('mark controls operate only on the current preview card and never add controls over the artwork',async()=>{
  const e=setup();await e.context.previewExpansionDeck(e.saved.id);
  e.context.reviewUI={selected:{code:11,selection_key:'main:0'},detailReport:{id:`selection:${e.saved.id}`}};
  e.context.updatePreviewMarkButton();assert.equal(e.node('#toggle-preview-card-mark').textContent,'添加标记');
  e.context.togglePreviewMark();assert.equal(e.state.picks.has('main:0'),true);
  assert.equal(e.node('#toggle-preview-card-mark')['aria-pressed'],'true');
  e.context.togglePreviewMark();assert.equal(e.state.picks.size,0);
  e.context.reviewUI.detailReport.id='unrelated';e.context.togglePreviewMark();assert.equal(e.state.picks.size,0);
  assert(!/type="checkbox"|data-selection-pick/.test(e.node('#selection-cards').innerHTML));
});
test('quick candidates fill empty slots only, respect stock and bans, and exclude extra and side cards',()=>{
  const e=setup(),d={name:'方案',deck:structuredClone(e.saved.deck),quick_cards:[{code:11,zone:'main'},{code:11,zone:'main'},{code:12,zone:'main'},{code:21,zone:'extra'},{code:31,zone:'side'}],conditions:{hand_count:5,slots:[null,null,null,null,null],banned:[]}};
  e.context.flow.design=d;
  assert.deepEqual(plain(e.context.mainQuickCodes()),[11,12]);
  e.context.renderDesignCardShortcuts();assert.deepEqual(d.conditions.slots,[null,null,null,null,null]);
  e.context.applyOpeningShortcut(11);e.context.applyOpeningShortcut(11);e.context.applyOpeningShortcut(11);
  assert.deepEqual(d.conditions.slots,[11,11,null,null,null]);
  d.conditions.banned=[12];e.context.applyOpeningShortcut(12);e.context.applyOpeningShortcut(21);
  assert.deepEqual(d.conditions.slots,[11,11,null,null,null]);
  d.conditions.banned=[];d.conditions.hand_count=2;e.context.applyOpeningShortcut(12);
  assert.deepEqual(d.conditions.slots,[11,11,null,null,null]);
  assert.equal(e.context.openingShortcutError(11,0),'');
  d.name='';assert.match(e.context.openingShortcutError(11,0),/方案名称/);
});
test('drag placement replaces only the chosen slot and rejects stale, banned or over-stock candidates',()=>{
  const e=setup(),d={name:'方案',deck:structuredClone(e.saved.deck),quick_cards:[{code:11,zone:'main'}],conditions:{hand_count:3,slots:[11,12,null],banned:[]}};
  e.context.flow.design=d;
  e.context.applyOpeningShortcut(11,1);assert.deepEqual(d.conditions.slots,[11,11,null]);
  e.context.applyOpeningShortcut(11,2);assert.deepEqual(d.conditions.slots,[11,11,null]);
  d.conditions.banned=[11];e.context.applyOpeningShortcut(11,0);assert.deepEqual(d.conditions.slots,[11,11,null]);
  e.state.drag={code:11,design:d};
  assert.equal(e.context.currentOpeningDrag().code,11);
  e.context.flow.design=structuredClone(d);assert.equal(e.context.currentOpeningDrag(),null);
});
test('copy captures the chosen names and retries failures without changing selection or plan name',async()=>{
  const e=setup(),seen=[],messages=[];e.context.notice=value=>messages.push(value);
  let reject;
  e.context.window.trainerDesktop={copyCardNames:codes=>{seen.push(codes);return new Promise((_,r)=>{reject=r;});}};
  const codes=[11,11,12],first=e.context.copySelectedCardNames(codes);codes.push(21);
  await e.context.copySelectedCardNames([21]);assert.equal(seen.length,1);
  reject(Error('复制不可用'));await first;assert.equal(e.state.copying,false);assert.match(messages[0],/复制失败/);
  assert.deepEqual(plain(seen[0]),[11,11,12]);
  e.context.window.trainerDesktop.copyCardNames=async()=>({count:2});await e.context.copySelectedCardNames([11,12]);
  assert.match(messages[1],/已复制 2 个卡名/);
});
test('confirmed selection enters preparation even with an unrelated dirty editor and clones its snapshot',async()=>{
  const expansion=fs.readFileSync(path.join(__dirname,'../src/trainer/web/expansion.js'),'utf8');
  const selected={id:'saved',revision:'one',name:'选择的卡组',deck:{main:[11],extra:[],side:[]}};
  let mounted;
  const context=vm.createContext({flow:{design:null},app:{dirty:true,id:'unsaved'},structuredClone,
    notice:()=>{throw Error('Should use the confirmed selection');},draftDirty:()=>false,
    api:async url=>{assert.equal(url,'/api/opponent');return {deck:{main:[12]},opening:[12]};},
    mountDesign:async d=>{mounted=d;},$:()=>({focus(){}})});
  vm.runInContext(expansion.slice(expansion.indexOf('async function openDesign'),expansion.indexOf('async function mountDesign')),context);
  await context.openDesign(selected);
  assert.equal(mounted.id,'saved');assert.equal(mounted.deck_name,selected.name);
  mounted.deck.main.push(12);assert.deepEqual(selected.deck.main,[11]);
});
test('a previously customized preparation cannot silently replace the confirmed saved deck',async()=>{
  const expansion=fs.readFileSync(path.join(__dirname,'../src/trainer/web/expansion.js'),'utf8');
  const selected={id:'saved',revision:'one',name:'已保存',deck:{main:[11],extra:[],side:[]}};
  const previous={...structuredClone(selected),deck_name:selected.name,deck:{main:[12],extra:[],side:[]}};
  let mounted,accepted=false,confirmations=0;
  const context=vm.createContext({flow:{design:previous},app:{},structuredClone,draftDirty:()=>false,
    confirmFlow:async()=>{confirmations++;return accepted;},switchView:()=>{throw Error('Must not reuse the customized deck');},
    api:async()=>({deck:{main:[12]},opening:[12]}),mountDesign:async d=>{mounted=d;},$:()=>({focus(){}})});
  vm.runInContext(expansion.slice(expansion.indexOf('async function openDesign'),expansion.indexOf('async function mountDesign')),context);
  await context.openDesign(selected);assert.equal(mounted,undefined);assert.equal(context.flow.design,previous);
  accepted=true;await context.openDesign(selected);
  assert.deepEqual(plain(mounted.deck),selected.deck);assert.equal(confirmations,2);
});
