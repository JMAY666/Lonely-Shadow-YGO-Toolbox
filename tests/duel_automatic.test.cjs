const test=require('node:test'),assert=require('node:assert/strict');
const automatic=require('../src/trainer/web/duel-automatic.js');
const ready=()=>Object.assign(automatic.create(),{deck:automatic.sample(),name:'界面验收'});

test('preview save rejects empty, invalid and reserved names without creating entries',()=>{
  assert.match(automatic.save(automatic.create()).error,/获取/);
  const draft=ready();
  for(const name of ['', '   ', 'a/b', '<卡组>', 'CON', 'nul.txt', 'a.', 'a'.repeat(81)]) {
    draft.name=name;assert(automatic.save(draft).error,name);assert.equal(draft.saved.length,0);
  }
});
test('same-name preview update needs confirmation and replaces cards and TAGs in one entry',()=>{
  const draft=ready();automatic.setRole(draft,'demo-blue-eyes','primary');
  assert(automatic.save(draft).saved);
  draft.deck.deck.main.push(55144522);automatic.setRole(draft,'demo-dragon','secondary');
  assert(automatic.save(draft).confirmation);assert.equal(draft.saved[0].deck.main.length,40);
  assert(automatic.save(draft,[],true).overwritten);assert.equal(draft.saved.length,1);
  assert.equal(draft.saved[0].deck.main.length,41);
  assert.deepEqual(draft.saved[0].tag_selection,{tag_ids:['demo-blue-eyes','demo-dragon'],primary_ids:['demo-blue-eyes']});
  draft.deck.deck.main.length=0;draft.tagIds.length=0;assert.equal(draft.saved[0].deck.main.length,41);
  assert.equal(draft.saved[0].tag_selection.tag_ids.length,2);
});
test('a collision with a real deck is simulated without mutating the real source',()=>{
  const source=[{id:'existing',revision:'unchanged',name:'Demo',deck:{main:[123],extra:[],side:[]}}],before=structuredClone(source);
  const draft=ready();draft.name='  Ｄｅｍｏ  ';
  assert(automatic.save(draft,source).confirmation);assert.equal(draft.saved.length,0);
  assert(automatic.save(draft,source,true).overwritten);assert.deepEqual(source,before);
  assert.equal(draft.saved.length,1);
  draft.name='Other';assert(automatic.save(draft,source,true).saved);assert.equal(draft.saved.length,2);
});
test('changing TAGs cancels an outstanding overwrite and keeps main/sub roles exclusive',()=>{
  const draft=ready();automatic.save(draft);automatic.save(draft);assert(draft.pending);
  automatic.setRole(draft,'demo-blue-eyes','primary');assert.equal(draft.pending,null);
  assert(automatic.save(draft,[],true).confirmation);
  automatic.setRole(draft,'demo-blue-eyes','secondary');assert.deepEqual(draft.tagIds,['demo-blue-eyes']);assert.deepEqual(draft.primaryIds,[]);
  automatic.setRole(draft,'demo-blue-eyes','');assert.deepEqual(draft.tagIds,[]);
  automatic.setRole(draft,'untrusted','primary');assert.deepEqual(draft.tagIds,[]);
  const other=ready();assert.equal(other.saved.length,0);assert.equal(other.marks.size,0);
});
