const test=require('node:test'),assert=require('node:assert/strict');
const automatic=require('../src/trainer/web/duel-automatic.js');
const result=()=>({deck:{main:[1,1,2],extra:[3],side:[4]},captured_ms:1});
const ready=()=>{const draft=automatic.create();automatic.accept(draft,result());draft.tags=[{id:'one'},{id:'two'}];return draft;};

test('save requires a successful fresh capture and a valid filename',()=>{
  assert.match(automatic.payload(automatic.create()).error,/获取/);
  const draft=ready();
  for(const name of ['', '   ', 'a/b', '<卡组>', 'CON', 'nul.txt', 'a.', 'a'.repeat(81)]) {
    draft.name=name;assert(automatic.payload(draft).error,name);
  }
  draft.name='第一套';assert.equal(automatic.payload(draft).name,'第一套');
  draft.fresh=false;assert.match(automatic.payload(draft).error,/获取/);
});
test('fresh captures replace every zone, preserve naming and TAGs, and clear misplaced copy marks',()=>{
  const draft=ready();draft.name='第一套';automatic.setRole(draft,'one','primary');draft.marks.add('main:0');
  automatic.accept(draft,result());assert.equal(draft.marks.size,1);
  const changed=result();changed.deck.main[0]=7;changed.deck.side=[];
  draft.pending={id:'old'};automatic.accept(draft,changed);
  assert.deepEqual(draft.deck.deck,changed.deck);assert.equal(draft.marks.size,0);assert.equal(draft.pending,null);
  assert.equal(draft.name,'第一套');assert.deepEqual(draft.tagIds,['one']);
});
test('save payload is detached from live UI and manual TAG roles are exclusive',()=>{
  const draft=ready();draft.pending={id:'old'};automatic.setRole(draft,'one','primary');
  assert.equal(draft.pending,null);automatic.setRole(draft,'one','secondary');
  assert.deepEqual(draft.tagIds,['one']);assert.deepEqual(draft.primaryIds,[]);
  automatic.setRole(draft,'two','primary');const values=automatic.payload(draft);
  draft.deck.deck.main.length=0;draft.tagIds.length=0;
  assert.equal(values.deck.main.length,3);assert.deepEqual(values.tag_selection,{tag_ids:['one','two'],primary_ids:['two']});
  automatic.setRole(draft,'unknown','primary');assert.deepEqual(draft.tagIds,[]);
});
