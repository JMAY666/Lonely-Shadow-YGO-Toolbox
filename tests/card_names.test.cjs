const assert=require('node:assert/strict');
const test=require('node:test');
const {cardNamesForCopy}=require('../desktop/card-names.cjs');

test('card-name copying keeps selection order, merges duplicate names and reads only unique card ids',async()=>{
  const read=[];
  const names=await cardNamesForCopy([11,11,12,13],async id=>{read.push(id);return {name:id===12?'乙':'甲'};});
  assert.deepEqual(read,[11,12,13]);assert.deepEqual(names,['甲','乙']);
  assert.equal(names.join(' + '),'甲 + 乙');
});
test('invalid or oversized card-name requests are rejected before reading cards',async()=>{
  for(const codes of [null,[],Array(91).fill(11),[0],[-1],[1.5],['11'],[0x100000000]]) {
    await assert.rejects(cardNamesForCopy(codes,()=>{throw Error('must not read');}),/请选择有效卡牌/);
  }
});
test('missing names and read failures prevent partial clipboard text',async()=>{
  for(const card of [{},{name:''},{name:' '},{name:'字'.repeat(513)}]) await assert.rejects(cardNamesForCopy([11],async()=>card),/完整卡名/);
  await assert.rejects(cardNamesForCopy([11,12],async code=>{if(code===12)throw Error('failed');return {name:'甲'};}),/failed/);
});
