'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const View=require('../src/trainer/web/going-second.js');
test('Late analysis cannot return after changed input, next round, exit or newer request',()=>{
  const s=View.create(),serial=++s.serial,key='round-a-hand-a';
  assert(View.accepts(s,serial,key,key));
  assert(!View.accepts(s,serial,key,'round-b-hand-a'));
  assert(!View.accepts(s,serial,key,'round-a-hand-b'));
  View.invalidate(s);assert(!View.accepts(s,serial,key,key));
  const second=++s.serial;++s.serial;assert(!View.accepts(s,second,key,key));
});
