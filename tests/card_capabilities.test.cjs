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

test('terminal comparison keeps fixed-granted timing costs limits and independent-use boundary',()=>{
  const data={tags:[],unknown_cards:0,basis:'静态参考',effects:[{code:15092394,key:'m1',relations:[],facts:[
    {label:'条件',text:'有超量怪兽素材'},
    {label:'固定获赋效果',text:'以下效果须另行满足自己的发动或适用条件。'},
    {label:'固定获赋效果·时点',text:'自己主要阶段'},
    {label:'固定获赋效果·费用',text:'取除1个素材'},
    {label:'固定获赋效果·次数',text:'每张表侧卡片每回合1次'}
  ]},{code:86221741,key:'m3',relations:[],facts:[
    {label:'条件',text:'有RR素材'},
    {label:'固定获赋效果·时点',text:'结束阶段'},
    {label:'固定获赋效果·次数说明',text:'每个结束阶段最多发动1次'},
    {label:'固定获赋效果·固定获赋效果·条件',text:'<须核对>'}
  ]}]};
  const html=view.comparison(data);
  assert(html.includes('固定获赋效果：以下效果须另行满足'));
  assert(html.includes('固定获赋效果·时点：结束阶段'));
  assert(html.includes('固定获赋效果·费用：取除1个素材'));
  assert(html.includes('固定获赋效果·次数说明：每个结束阶段最多发动1次'));
  assert(html.includes('条件：有RR素材'));
  assert(html.includes('条件：&lt;须核对&gt;'));
  assert(!html.includes('<须核对>'));
});
