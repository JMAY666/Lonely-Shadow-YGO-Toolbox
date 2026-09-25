'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const view=require('../src/trainer/web/card-capabilities.js');
const value=()=>({code:1,status_label:'已核对',trusted:true,version:'abc',tags:[],relations:[],boundary:'静态参考',effects:[
  {key:'m1',label:'效果1',text:'<img onerror=bad>',legacy_key:'0',tags:[{name:'<script>bad</script>'}],facts:[{label:'次数',text:'共用1次'}],notes:[],candidates:[{role:'handtraps',label:'手坑候选',reason:'条件参考'}]}]});
test('shared renderer escapes data and keeps purpose acceptance explicit',()=>{
  const html=view.html(value(),{purpose:'handtraps',adopt:true});
  assert(!html.includes('<script>'));
  assert(!html.includes('<img onerror'));
  assert(html.includes('data-capability-select="0"'));
  assert(html.includes('共用1次'));
  assert(!view.html(value()).includes('data-capability-select'));
});
test('untrusted and ambiguous mappings never offer effect adoption',()=>{
  const data=value();data.trusted=false;
  assert(!view.html(data,{purpose:'handtraps',adopt:true}).includes('data-capability-select'));
  data.trusted=true;data.effects[0].legacy_key=null;
  assert(!view.html(data,{purpose:'handtraps',adopt:true}).includes('data-capability-select'));
});
test('old records and frozen versions have explicit presentation',()=>{
  assert(view.html(null,{frozen:true}).includes('旧记录没有保存标注版本'));
  assert(view.html(value(),{frozen:true}).includes('保存时的卡片能力'));
  assert(view.comparison({tags:[],effects:[],unknown_cards:1,basis:'不累计次数'}).includes('不按零能力处理'));
});
