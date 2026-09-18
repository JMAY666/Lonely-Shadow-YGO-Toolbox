'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Model=require('../src/trainer/web/duel-second-routes.js');
test('second routes require a current linked engine and live observation record',()=>{
  const doc={route_panel:{current:true}};
  assert(Model.available(doc));assert(!Model.available({...doc,closed:true}));
  assert(!Model.available({...doc,status_reason:'changed'}));assert(!Model.available({route_panel:{current:false}}));
  assert(!Model.available({route_panel:{current:true,route_ready:false}}));
});
test('route instructions name physical zones and distinguish automatic empty responses',()=>{
  assert.match(Model.step({bound_decision:{selection:[{kind:'place',place:[0,8,0]}]}},{}),/魔陷区第 1 格/);
  assert.match(Model.step({bound_decision:{selection:[{kind:'place',place:[0,4,5]}]}},{}),/额外怪兽区（左）/);
  assert.match(Model.step({automatic:true,bound_decision:{selection:[{kind:'pass'}]}},{}),/自动通过空响应/);
});
