'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const Model=require('../src/trainer/web/duel-second-battle.js');
test('battle previews are scoped to the original observation and native checkpoint',()=>{
 const doc={revision:3,route_panel:{current:true},native_link:{stamp:'a'}},h={revision:3,origin:{stamp:'a'}};
 assert(Model.current(doc,h));assert(!Model.current({...doc,revision:4},h));
 assert(!Model.current({...doc,native_link:{stamp:'b'}},h));assert(!Model.current({...doc,closed:true},h));
});
