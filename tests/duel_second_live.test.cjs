const test=require('node:test'),assert=require('node:assert/strict');
const model=require('../src/trainer/web/duel-second-live.js');
test('old resource previews stay historical and cannot cross observation revisions',()=>{
 const doc={revision:2},p={revision:2,can_apply:true,current:true,created_ms:1000};
 assert(model.canApply(doc,p));assert(model.fresh(p,2000));assert(!model.fresh(p,4000));
 assert(!model.canApply({...doc,revision:3},p));assert(!model.canApply({...doc,closed:true},p));
});
test('effect description references are not assumed to be card effect numbers',()=>{
 const catalog={1184620:{str1:'local text',str2:'other'}};
 assert.equal(model.effectText(catalog,{code:1184620,description:1184620*16}),'local text');
 assert.equal(model.effectText(catalog,{code:1184620,description:1184620*16+1}),'other');
 assert.equal(model.effectText(catalog,{code:1184620,description:0}),'');
 assert.equal(model.effectText(catalog,{code:1184620,description:100*16}),'');
 assert.equal(model.effectText({}, {code:1184620,description:1184620*16}),'');
});
