const test=require('node:test'),assert=require('node:assert/strict');
const model=require('../src/trainer/web/duel-second-live.js');
test('old resource previews stay historical and cannot cross observation revisions',()=>{
 const doc={revision:2},p={revision:2,can_apply:true,current:true,created_ms:1000};
 assert(model.canApply(doc,p));assert(model.fresh(p,2000));assert(!model.fresh(p,4000));
 assert(!model.canApply({...doc,revision:3},p));assert(!model.canApply({...doc,closed:true},p));
});
