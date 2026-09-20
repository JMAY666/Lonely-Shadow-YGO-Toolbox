'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
test('desktop reference links dispatch approved public sources and reject non-reference destinations',async()=>{
  const file=path.join(__dirname,'../desktop/reference-links.cjs');
  assert(fs.existsSync(file),'Reference link dispatch is available');
  const {openReference}=require(file),calls=[],shell={openExternal:async url=>{calls.push(url);}};
  const url='https://www.db.yugioh-card.com/yugiohdb/card_search.action?ope=2&cid=12950&request_locale=ja';
  await openReference(shell,url);assert.deepEqual(calls,[url]);
  for(const bad of ['file:///C:/test','javascript:alert(1)','https://masterduelmeta.com.evil.example/','https://name:password@roadoftheking.com/','http://localhost/','not a URL'])assert.throws(()=>openReference(shell,bad));
  assert.equal(calls.length,1);
});
