'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const View=require('../src/trainer/web/live-duel.js');
test('changed view generation rejects late responses without sharing mutable drafts',()=>{
  const a=View.create(),b=View.create(),generation=a.generation;
  a.generation++;assert.equal(View.current(a,generation),false);assert.equal(b.generation,0);assert.equal(b.value,null);
});
test('manual windows expire at their deadline and empty references never count as live windows',()=>{
  assert.equal(View.expired({expires_at:120},120),true);assert.equal(View.expired({expires_at:120},119),false);
  assert.equal(View.expired({expires_at:null},900),false);
});
