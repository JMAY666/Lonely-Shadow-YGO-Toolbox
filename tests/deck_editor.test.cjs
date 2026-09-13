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
      classList:{toggle() {}}, style:{setProperty() {}},
      setAttribute() {}, removeAttribute() {},
    });
    return elements.get(selector);
  }
  const context = vm.createContext({
    document:{querySelector:node, querySelectorAll:() => [], activeElement:null, body:{classList:{toggle() {}}}},
    window:{innerWidth:1280}, structuredClone, setTimeout:() => 1, clearTimeout() {}, confirm:() => true,
    fetch:async () => { throw new Error('Unexpected network request'); },
  });
  vm.runInContext(editorSource + '\nglobalThis.editor = {app, card, addCard, removeCard, undoDeck, sortDeck, renderDeck, showCard, search, saveDeck, openDeck, newDeck, deckState, dirty};', context);
  const editor = context.editor;
  for (const c of cards) editor.app.cache.set(c.id, {...c});
  editor.app.savedState = editor.deckState();
  return {...editor, node, context};
}
const plain = value => JSON.parse(JSON.stringify(value));
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
