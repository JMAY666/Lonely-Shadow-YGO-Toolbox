'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Model=require('../src/trainer/web/duel-second-hints.js');
test('hint choice depends on the same live revision, window and expiry',()=>{
  const doc={revision:4,current:{window:{id:'w'}},advice:{current:true,revision:4,window_id:'w',expires_ms:100}};
  assert(Model.current(doc,99));assert(!Model.current(doc,100));
  assert(!Model.current({...doc,revision:5},99));assert(!Model.current({...doc,status_reason:'gap'},99));
  assert(!Model.current({...doc,current:{window:{id:'other'}}},99));
});
test('same-card effects retain their identities and shared use group',()=>{
  const doc={current:{turn:1,cards:[{id:'c',code:1,controller:0}],effect_counts:{'0:shared':{turn:1,status:'used'}}},
    hint_options:{effects:[{id:'one',code:1,group:'shared',limit:'use_name_turn'},{id:'two',code:1,group:'shared',limit:'use_name_turn'},{id:'other',code:2}]}};
  assert.deepEqual(Model.select(doc,'c').map(e=>e.id),['one','two']);
  assert(Model.select(doc,'c').every(e=>Model.effectStatus(doc,e,doc.current.cards[0])==='已使用'));
  doc.current.turn=2;assert(Model.select(doc,'c').every(e=>Model.effectStatus(doc,e,doc.current.cards[0])==='未核对'));
});
