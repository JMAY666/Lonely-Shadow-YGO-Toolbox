const test=require('node:test'),assert=require('node:assert/strict');
const Order=require('../src/trainer/web/duel-order.js');
const detected=(id='a',order='first')=>({monitor_id:'m',round_id:id,revision:1,phase:'detected',detected_order:order});
test('waiting and old rounds never become a confirmable result',()=>{
  const state=Order.create(detected());assert(Order.ready(state));state.manual='second';
  Order.accept(state,{...detected(),phase:'rps',detected_order:null});assert(!Order.ready(state));assert.equal(state.manual,null);
  assert.throws(()=>Order.confirmation(state));Order.accept(state,detected('b','second'));assert.equal(Order.selected(state),'second');
});
test('manual correction records both explicit choice and original observation identity',()=>{
  const state=Order.create(detected());state.manual='second';Order.accept(state,detected());
  assert.deepEqual(Order.confirmation(state),{monitor_id:'m',round_id:'a',revision:1,order:'second',manual:true});
  Order.accept(state,detected('next'));assert.equal(state.manual,null);
});
test('old confirmation cannot unlock a new round or an unsaved manual correction',()=>{
  const state=Order.create({...detected(),confirmed:{order:'first',source:'automatic'}});
  assert(Order.confirmed(state));state.manual='second';assert(!Order.confirmed(state));
  Order.accept(state,{...detected('next'),phase:'rps',detected_order:null,confirmed:null});assert(!Order.confirmed(state));
});
