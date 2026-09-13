const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

// Exercise the editor state and asynchronous requests without a browser dependency.
// Real rendering and pointer interactions are checked separately in the local UI.
const source = readFileSync(path.join(__dirname, '../src/trainer/web/app.js'), 'utf8');
const editorSource = source.slice(0, source.indexOf("document.addEventListener('click'"));
const cards = [
  {id:101, name:'测试怪兽甲', type:0x21, level:4, atk:1000, def:500, extra:false},
  {id:102, name:'测试怪兽乙', type:0x11, level:8, atk:2000, def:1000, extra:false},
  {id:201, name:'测试融合', type:0x61, level:8, extra:true},
  {id:202, name:'测试连接', type:0x4000021, level:2, extra:true},
  {id:301, name:'测试魔法', type:2, extra:false},
  {id:401, name:'测试陷阱', type:4, extra:false},
  {id:501, name:'测试衍生物', type:0x4001, extra:false},
];

function setup() {
  const elements = new Map();
  function node(selector) {
    if (!elements.has(selector)) elements.set(selector, {
      value: selector === '#deck-name' ? '测试构筑' : '', textContent:'', innerHTML:'',
      disabled:false, hidden:false, clientHeight:0, scrollHeight:0,
      classList:{toggle() {}, add() {}, remove() {}}, style:{setProperty() {}},
      open:false, showModal() { this.open = true; }, close() { this.open = false; },
      setAttribute(name, value) { this[name] = value; }, removeAttribute() {}, focus() { this.focused = true; },
    });
    return elements.get(selector);
  }
  const context = vm.createContext({
    document:{querySelector:node, querySelectorAll:() => [], activeElement:null, body:{classList:{toggle() {}}}},
    window:{innerWidth:1280}, structuredClone, TextEncoder, setTimeout:() => 1, clearTimeout() {}, confirm:() => true,
    fetch:async () => { throw new Error('Unexpected network request'); },
  });
  vm.runInContext(editorSource + '\nglobalThis.editor = {app, card, addCard, removeCard, undoDeck, sortDeck, renderDeck, showCard, search, saveDeck, openDeck, newDeck, deleteDeck, confirmDeckDeletion, setLibraryOpen, deckState, dirty, importState, invalidateImport, previewImport, previewYdk, loadYdkFile, applyImportedDeck, availableImportName};', context);
  const editor = context.editor;
  context.confirmDeckDeletion = async () => true;
  for (const c of cards) editor.app.cache.set(c.id, {...c,script_available:true});
  editor.app.savedState = editor.deckState();
  return {...editor, node, context};
}
const plain = value => JSON.parse(JSON.stringify(value));

test('delete confirmation settles on submit/cancel without waiting for a rendering-frame close event', async () => {
  for(const action of ['delete','cancel']) {
    const e=setup(), dialog=e.node('#delete-dialog'), listeners=new Map(), formListeners=new Map();
    dialog.addEventListener=(type,fn)=>listeners.set(type,fn);
    dialog.removeEventListener=type=>listeners.delete(type);
    dialog.querySelector=()=>({addEventListener:(type,fn)=>formListeners.set(type,fn),removeEventListener:type=>formListeners.delete(type)});
    dialog.close=value=>{dialog.open=false;dialog.returnValue=value;}; // Deliberately no close event.
    const answer=e.confirmDeckDeletion({name:'删除测试'},true);
    assert.equal(dialog.open,true);
    if(action==='delete') formListeners.get('submit')({preventDefault(){},submitter:{value:'delete'}});
    else listeners.get('cancel')({preventDefault(){}});
    assert.equal(await answer,action==='delete');
    assert.equal(dialog.open,false);assert.equal(listeners.size,0);assert.equal(formListeners.size,0);
  }
});

test('deleting a selected deck preserves a different unsaved construct and sends its revision', async () => {
  const e = setup();
  e.app.id = 'library/current.ydk'; e.app.deck.main = [101]; e.dirty();
  e.node('#compact-deck').value = 'library/delete.ydk';
  const requests = [];
  e.context.api = async (url, body) => {
    requests.push([url, body]);
    if (url.startsWith('/api/deck?')) return {id:'library/delete.ydk',name:'删除测试',revision:'revision-a'};
    if (url === '/api/decks/delete') return {id:body.id,backup:'backups/deleted/test'};
    if (url === '/api/decks') return [];
    throw new Error(url);
  };
  await e.deleteDeck();
  assert.deepEqual(plain(requests[1][1]), {id:'library/delete.ydk',revision:'revision-a'});
  assert.deepEqual(plain(e.app.deck.main), [101]);
  assert.equal(e.app.id, 'library/current.ydk');
  assert.equal(e.app.dirty, true);
});

test('canceling deck deletion keeps current edits and does not send a mutation', async () => {
  const e = setup();
  e.app.id = 'library/test.ydk'; e.app.deck.main = [101]; e.dirty();
  e.node('#compact-deck').value = e.app.id;
  e.context.confirmDeckDeletion = async () => false;
  let requests = 0;
  e.context.api = async (_url, body) => { requests++; assert.equal(body, undefined); return {id:e.app.id,name:'测试',revision:'r'}; };
  await e.deleteDeck();
  assert.equal(requests, 1); assert.equal(e.app.busy, false);
  assert.deepEqual(plain(e.app.deck.main), [101]); assert.equal(e.app.dirty, true);
});

test('drawer open and close preserve edits and return keyboard focus', () => {
  const e = setup(); e.app.deck.main = [101]; e.dirty();
  e.setLibraryOpen(true);
  assert.equal(e.node('#card-library').hidden, false);
  assert.equal(e.node('#library-toggle')['aria-expanded'], 'true');
  assert.equal(e.node('#search').focused, true);
  e.setLibraryOpen(false);
  assert.equal(e.node('#card-library').hidden, true);
  assert.equal(e.node('#library-toggle')['aria-expanded'], 'false');
  assert.equal(e.node('#library-toggle').focused, true);
  assert.deepEqual(plain(e.app.deck.main), [101]); assert.equal(e.app.dirty, true);
});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes,no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

test('renders every copy in all three zones and escapes card names', async () => {
  const e = setup();
  e.app.deck = {main:[101,101,102], extra:[201,202], side:[101]};
  e.app.cache.get(101).name = '<unsafe "name">';
  await e.renderDeck();
  for (const [zone,count] of [['main',3],['extra',2],['side',1]]) {
    assert.equal((e.node(`#cards-${zone}`).innerHTML.match(/data-detail=/g) || []).length, count);
    assert.equal(e.node(`#count-${zone}`).textContent, count);
  }
  assert.equal(e.node('#deck-total').textContent, '6 张');
  assert.match(e.node('#cards-main').innerHTML, /&lt;unsafe &quot;name&quot;&gt;/);
  assert.doesNotMatch(e.node('#cards-main').innerHTML, /<unsafe/);
});

test('removes exactly the clicked duplicate from its source zone; undo restores order and saved state', async () => {
  const e = setup();
  e.app.deck = {main:[101,102,101], extra:[201], side:[101]};
  e.app.id = 'library/test.ydk';
  e.app.savedState = e.deckState();
  await e.removeCard(101, 'main', 2);
  assert.deepEqual(plain(e.app.deck), {main:[101,102], extra:[201], side:[101]});
  assert.equal(e.app.dirty, true);
  assert.equal(e.node('#start-training').disabled, true);
  await e.undoDeck();
  assert.deepEqual(plain(e.app.deck.main), [101,102,101]);
  assert.equal(e.app.dirty, false);
  assert.equal(e.node('#start-training').disabled, false);
  assert.equal(e.node('#undo-deck').disabled, true);
});

test('stale card positions and missing cards do not remove a different copy or create an undo entry', async () => {
  const e = setup();
  e.app.deck.main = [101,102,101];
  await e.removeCard(101, 'main', 1);
  await e.removeCard(201, 'extra');
  assert.deepEqual(plain(e.app.deck.main), [101,102,101]);
  assert.equal(e.app.undo.length, 0);
});

test('adds to the correct zone, rejects tokens and mismatched zones, and enforces each capacity', async () => {
  const e = setup();
  await e.addCard(101);
  await e.addCard(201);
  await e.addCard(201, 'side');
  assert.deepEqual(plain(e.app.deck), {main:[101], extra:[201], side:[201]});
  const before = JSON.stringify(e.app.deck), undoBefore = e.app.undo.length;
  await e.addCard(201, 'main');
  await e.addCard(101, 'extra');
  await e.addCard(501, 'side');
  assert.equal(JSON.stringify(e.app.deck), before);
  assert.equal(e.app.undo.length, undoBefore);
  for (const [zone,code,limit] of [['main',101,60],['extra',201,15],['side',101,15]]) {
    e.app.deck[zone] = Array(limit).fill(code);
    await e.addCard(code, zone);
    assert.equal(e.app.deck[zone].length, limit);
    assert.equal(e.app.undo.length, undoBefore);
  }
});

test('sort retains copies and zones and can be undone exactly', async () => {
  const e = setup();
  e.app.deck = {main:[401,101,301,102,101], extra:[202,201], side:[301,101,201]};
  const before = JSON.stringify(e.app.deck);
  await e.sortDeck();
  assert.deepEqual(plain(e.app.deck.main), [102,101,101,301,401]);
  assert.deepEqual(plain(e.app.deck.extra), [201,202]);
  assert.deepEqual(plain(e.app.deck.side), [101,201,301]);
  await e.undoDeck();
  assert.equal(JSON.stringify(e.app.deck), before);
});

test('a delayed card request cannot add a card after switching constructs', async () => {
  const e = setup(), request = deferred();
  e.app.cache.delete(101);
  e.context.api = () => request.promise;
  const add = e.addCard(101);
  ++e.app.deckEpoch;
  request.resolve(cards[0]);
  await add;
  assert.deepEqual(plain(e.app.deck.main), []);
  assert.equal(e.app.undo.length, 0);
});

test('new construct holds the picker until its list refresh finishes', async () => {
  const e = setup(), list = deferred();
  e.app.deck.main = [101];
  e.context.api = () => list.promise;
  const pending = e.newDeck();
  assert.equal(e.app.busy, true);
  assert.equal(e.node('#compact-deck').disabled, true);
  assert.equal(e.node('#compact-open').disabled, true);
  await e.addCard(102);
  assert.deepEqual(plain(e.app.deck.main), []);
  list.resolve([]);
  await pending;
  assert.equal(e.app.busy, false);
  assert.equal(e.node('#compact-deck').disabled, false);
  assert.equal(e.node('#compact-open').disabled, false);
});

test('rapid selection keeps the newest detail and shares concurrent card requests', async () => {
  const e = setup(), first = deferred();
  e.app.cache.delete(101);
  let requests = 0;
  e.context.api = () => { requests++; return first.promise; };
  const oldDetail = e.showCard(101), sameCard = e.card(101);
  await e.showCard(102);
  first.resolve(cards[0]);
  await Promise.all([oldDetail, sameCard]);
  assert.equal(requests, 1);
  assert.equal(e.app.selected, 102);
  assert.match(e.node('#card-detail').innerHTML, /测试怪兽乙/);
  assert.doesNotMatch(e.node('#card-detail').innerHTML, /测试怪兽甲/);
});

test('late search results cannot replace a newer search', async () => {
  const e = setup(), old = deferred();
  e.context.api = () => old.promise;
  const pending = e.search();
  e.context.api = async () => ({total:1, cards:[cards[1]]});
  await e.search();
  old.resolve({total:1, cards:[cards[0]]});
  await pending;
  assert.match(e.node('#search-results').innerHTML, /测试怪兽乙/);
  assert.doesNotMatch(e.node('#search-results').innerHTML, /测试怪兽甲/);
});

test('save uses the existing revision, leaves editing dirty on failure, and unlocks the controls', async () => {
  const e = setup();
  e.app.id = 'library/test.ydk';
  e.app.revision = 'old-revision';
  await e.addCard(101);
  let sent;
  e.context.api = async (url, body) => { sent = body; throw new Error('模拟保存冲突'); };
  await assert.rejects(e.saveDeck(), /模拟保存冲突/);
  assert.equal(sent.revision, 'old-revision');
  assert.deepEqual(plain(sent.deck.main), [101]);
  assert.equal(e.app.revision, 'old-revision');
  assert.equal(e.app.dirty, true);
  assert.equal(e.app.busy, false);
  assert.equal(e.node('#save-deck').disabled, false);
});

test('saving an existing construct keeps its source id and requests a practice copy', async () => {
  const e = setup();
  e.app.id = 'existing/测试构筑.ydk';
  e.app.revision = 'source-revision';
  e.app.deck.main = [101];
  let sent;
  e.context.api = async (url, body) => {
    if (url === '/api/decks' && body) {
      sent = body;
      return {id:'library/测试构筑 - 练习.ydk', revision:'saved-revision'};
    }
    return [];
  };
  await e.saveDeck();
  assert.equal(sent.id, 'existing/测试构筑.ydk');
  assert.equal(sent.name, '测试构筑 - 练习');
  assert.equal(e.app.id, 'library/测试构筑 - 练习.ydk');
  assert.equal(e.app.dirty, false);
  assert.equal(e.node('#start-training').disabled, false);
});

function importPreview(overrides = {}) {
  return {can_import:true, deck:{main:[101,102,101],extra:[201],side:[101]},
    counts:{main:3,extra:1,side:1}, cards:{main:[{id:101,name:'测试怪兽甲',quantity:2}],extra:[],side:[]},
    errors:[], warnings:[], ...overrides};
}

test('import preview does not change the current construct and escapes diagnostics', async () => {
  const e = setup();
  e.app.deck.main = [102];
  e.node('#import-dialog').open = true;
  e.node('#import-text').value = '#main\n99999';
  e.context.previewYdk = async () => importPreview({can_import:false, errors:['<script>invalid</script>']});
  await e.previewImport();
  assert.deepEqual(plain(e.app.deck.main), [102]);
  assert.equal(e.node('#import-apply').disabled, true);
  assert.match(e.node('#import-result').innerHTML, /&lt;script&gt;/);
  assert.doesNotMatch(e.node('#import-result').innerHTML, /<script>/);
});

test('changed import text invalidates late preview responses', async () => {
  const e = setup(), request = deferred();
  e.node('#import-dialog').open = true;
  e.node('#import-text').value = '#main\n101';
  e.context.previewYdk = () => request.promise;
  const pending = e.previewImport();
  e.node('#import-text').value = '#main\n102';
  e.invalidateImport();
  request.resolve(importPreview());
  await pending;
  assert.equal(e.importState.preview, null);
  assert.equal(e.node('#import-apply').disabled, true);
});

test('file import reads once and requests preview automatically', async () => {
  const e = setup();
  e.node('#import-dialog').open = true;
  let reads = 0, requests = 0;
  e.context.previewYdk = async text => {
    requests++;
    assert.equal(text, '#main\n101');
    return importPreview();
  };
  await e.loadYdkFile({name:'测试卡组.YDK',size:10,text:async () => { reads++; return '#main\n101'; }});
  assert.equal(reads, 1);
  assert.equal(requests, 1);
  assert.equal(e.node('#import-name').value, '测试卡组');
  assert.equal(e.node('#import-apply').disabled, false);
  await e.loadYdkFile({name:'photo.png',size:1,text:async () => { throw new Error('must not read'); }});
  assert.equal(e.node('#import-apply').disabled, true);
  assert.equal(requests, 1);
});

test('applying an import starts a new unsaved construct and keeps every copy and zone', async () => {
  const e = setup();
  e.app.id = 'library/existing.ydk';
  e.app.revision = 'existing-revision';
  e.node('#import-dialog').open = true;
  e.node('#import-text').value = e.importState.text = '#main\n101\n102\n101\n#extra\n201\n!side\n101';
  e.node('#import-name').value = 'Existing';
  e.importState.preview = importPreview();
  e.context.api = async url => {
    assert.equal(url, '/api/decks');
    return [{source:'library',name:'existing'}];
  };
  await e.applyImportedDeck();
  assert.deepEqual(plain(e.app.deck), {main:[101,102,101],extra:[201],side:[101]});
  assert.equal(e.app.id, null);
  assert.equal(e.app.revision, null);
  assert.equal(e.app.dirty, true);
  assert.equal(e.node('#deck-name').value, 'Existing - 导入');
  assert.equal(e.node('#start-training').disabled, true);
});

test('canceling replacement preserves unsaved edits and never fetches or saves', async () => {
  const e = setup();
  e.app.deck.main = [102];
  e.app.dirty = true;
  e.context.confirm = () => false;
  e.node('#import-text').value = e.importState.text = '#main\n101';
  e.importState.preview = importPreview();
  e.context.api = () => { throw new Error('must not request'); };
  await e.applyImportedDeck();
  assert.deepEqual(plain(e.app.deck.main), [102]);
  assert.equal(e.app.dirty, true);
});

test('import names handle Windows reserved names and multiple case-insensitive collisions', () => {
  const e = setup();
  assert.equal(e.availableImportName('Deck', [{source:'library',name:'deck'},{source:'library',name:'DECK - 导入'}]), 'Deck - 导入 (2)');
  assert.equal(e.availableImportName('CON', []), '导入-CON');
  assert.equal(e.availableImportName('../bad:name', []), '.._bad_name');
});

test('YDK preserves BOM/CRLF, passcode order, duplicate counts and all zones', async () => {
  const e = setup();
  const p = await e.previewYdk('\ufeff#created by test\r\n#main\r\n00101\r\n102\r\n101\r\n#extra\r\n201\r\n!side\r\n201\r\n101\r\n');
  assert.equal(p.can_import, true);
  assert.deepEqual(plain(p.deck), {main:[101,102,101],extra:[201],side:[201,101]});
  assert.deepEqual(plain(p.cards.main.map(c => [c.id,c.quantity])), [[101,2],[102,1]]);
});

test('YDK accepts optional empty sections and complete free-practice decks', async () => {
  const e = setup();
  assert.equal((await e.previewYdk('#MAIN\n101')).can_import, true);
  const p = await e.previewYdk('#main\n' + '101\n'.repeat(40) + '#extra\n' + '201\n'.repeat(15) + '!side\n' + '102\n'.repeat(15));
  assert.equal(p.can_import, true);
  assert.deepEqual(plain(p.counts), {main:40,extra:15,side:15});
  assert.deepEqual(plain(p.warnings), []);
});

test('YDK reports unknown passcodes without dropping them or changing the current deck', async () => {
  const e = setup();
  e.app.deck.main = [102];
  e.context.api = async () => { const error = new Error('missing'); error.status = 400; throw error; };
  const p = await e.previewYdk('#main\n101\n4294967295');
  assert.equal(p.can_import, false);
  assert.deepEqual(plain(p.deck.main), [101,4294967295]);
  assert.match(p.errors.join(' '), /第 3 行.*4294967295/);
  assert.deepEqual(plain(e.app.deck.main), [102]);
});

test('YDK rejects invalid lines and missing, misspelled or repeated sections', async () => {
  const e = setup();
  for (const line of ['101 x3','测试怪兽','https://example.com/deck','-1','0','4294967296','!unknown']) {
    const p = await e.previewYdk('#main\n101\n' + line);
    assert.equal(p.can_import, false, line);
    assert.match(p.errors.join(' '), /第 3 行/);
  }
  for (const text of ['101','#main\n101\n#side\n101','#main\n101\n#main\n102','#main\n101\n!extra\n201']) {
    assert.equal((await e.previewYdk(text)).can_import, false, text);
  }
});

test('YDK rejects tokens and incorrect card zones and never truncates over-capacity decks', async () => {
  const e = setup();
  for (const text of ['#main\n501','#main\n201','#main\n101\n#extra\n102','#main\n101\n!side\n501']) {
    assert.equal((await e.previewYdk(text)).can_import, false, text);
  }
  for (const [marker,zone,code,count] of [['#main','main',101,61],['#extra','extra',201,16],['!side','side',101,16]]) {
    const p = await e.previewYdk((zone === 'main' ? '' : '#main\n101\n') + marker + '\n' + (code+'\n').repeat(count));
    assert.equal(p.can_import, false);
    assert.equal(p.deck[zone].length, count);
  }
});

test('YDK distinguishes draft warnings from parse errors and connection failures', async () => {
  const e = setup();
  e.app.cache.get(101).script_available = false;
  const p = await e.previewYdk('#main\n101');
  assert.equal(p.can_import, true);
  assert.equal(p.warnings.length, 2);
  e.context.api = async () => { throw new Error('network failure'); };
  await assert.rejects(e.previewYdk('#main\n999'), /无法读取本地卡牌资料/);
  for (const text of ['', '\ufeff', '#main\n#extra\n!side', '\0\1\2']) {
    assert.equal((await e.previewYdk(text)).can_import, false);
  }
  for (const text of [null, [], 'x'.repeat(32769), '\n'.repeat(1002)]) {
    await assert.rejects(e.previewYdk(text));
  }
});

test('dropping a YDK file opens preview while multiple files are rejected without changing the deck', async () => {
  const e = setup(), handlers = new Map();
  e.context.document.addEventListener = (name, callback) => handlers.set(name, callback);
  vm.runInContext(source.slice(source.indexOf("document.addEventListener('dragover'"), source.indexOf('let searchTimer;')), e.context);
  e.context.previewYdk = async text => { assert.equal(text, '#main\n101'); return importPreview(); };
  const file = {name:'drag.ydk',size:10,text:async () => '#main\n101'};
  let prevented = false;
  await handlers.get('drop')({dataTransfer:{types:['Files'],files:[file]},preventDefault() { prevented = true; }});
  assert.equal(prevented, true);
  assert.equal(e.node('#import-dialog').open, true);
  assert.equal(e.node('#import-apply').disabled, false);
  assert.deepEqual(plain(e.app.deck.main), []);
  await handlers.get('drop')({dataTransfer:{types:['Files'],files:[file,file]},preventDefault() {}});
  assert.equal(e.node('#import-apply').disabled, true);
  assert.match(e.node('#import-status').textContent, /一次拖入一个/);
  assert.deepEqual(plain(e.app.deck.main), []);
});
