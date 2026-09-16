const test=require('node:test'),assert=require('node:assert/strict');
const {latestLayout}=require('../desktop/native-layout.cjs');
test('scroll bursts apply only the in-flight and newest placement, including the final hide',async()=>{
  const calls=[],releases=[];const update=latestLayout(value=>{calls.push(value);return new Promise(resolve=>releases.push(resolve));});
  const first=update({y:0}),waiting=Array.from({length:80},(_,y)=>update({y})),last=update({visible:false});
  assert.equal(calls.length,1);releases.shift()('first');await first;assert.deepEqual(calls,[{y:0},{visible:false}]);
  releases.shift()('last');assert((await Promise.all(waiting)).every(value=>value==='last'));assert.equal(await last,'last');
});
test('a failed placement rejects its callers and does not block the newest retry',async()=>{
  let reject;const calls=[];const update=latestLayout(value=>{calls.push(value);return calls.length===1?new Promise((_,r)=>reject=r):Promise.resolve(value);});
  const a=update(1),failure=assert.rejects(a,/layout failed/),b=update(2);reject(new Error('layout failed'));await failure;assert.equal(await b,2);assert.deepEqual(calls,[1,2]);
});
