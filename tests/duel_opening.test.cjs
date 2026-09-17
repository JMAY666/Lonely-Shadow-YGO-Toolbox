const test=require('node:test'),assert=require('node:assert/strict');
const Opening=require('../src/trainer/web/duel-opening.js');
const ready=()=>({monitor_id:'m',round_id:'r',phase:'detected',confirmed:{order:'first'},opening:{status:'ready',snapshot_id:'s',cards:[1,1,2,3,4],confirmed:null}});
test('only confirmed first-player openings can proceed',()=>{
  const frame=ready();assert(Opening.ready(frame));assert(Opening.first(frame));
  assert.deepEqual(Opening.confirmation(frame),{monitor_id:'m',round_id:'r',snapshot_id:'s'});
  frame.confirmed.order='second';assert(Opening.ready(frame));assert.throws(()=>Opening.confirmation(frame));
  frame.phase='waiting_start';assert(!Opening.ready(frame));
});
test('partial deals and an old snapshot confirmation never unlock the next stage',()=>{
  const frame=ready();assert(!Opening.confirmed(frame));frame.opening.confirmed={snapshot_id:'old'};assert(!Opening.confirmed(frame));
  frame.opening.confirmed.snapshot_id='s';assert(Opening.confirmed(frame));frame.opening.status='dealing';assert(!Opening.confirmed(frame));
});
