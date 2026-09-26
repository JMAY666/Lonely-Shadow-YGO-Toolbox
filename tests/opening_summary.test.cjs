'use strict';
const assert=require('node:assert/strict'),test=require('node:test'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function renderer(){
  const ctx={escape:value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),openingName:code=>'card '+code,openingCard:code=>`<div data-card="${code}"></div>`,openingNote:()=>''};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/trainer/web/opening-summary.js'),'utf8'),ctx);return ctx;
}
function result(){return {analysis:{routes:[],groups:0,omitted:0,coverage_gaps:[],errors:[],effects:[],comparisons:[]},concentration:{groups:[],primary:[],status:'none',total:40,unclassified:40},cards:[{code:1,name:'<script>bad</script>',count:1,roles:['handtrap']}],handtrap_count:1,knowledge:[],role_names:{handtrap:'手坑'},hand_count:1,frozen:[1],supplemental:[],warnings:[],notes:{},boundary:'scope',source_version:'abc',revision:0};}
test('opening overview escapes card names and keeps statistics and metadata behind closed evidence panels',()=>{
  const html=renderer().renderOpeningOverview(result());
  assert(!html.includes('<script>bad</script>'));assert(html.includes('&lt;script&gt;bad&lt;/script&gt;'));
  for(const id of ['composition','participation','knowledge','gaps'])assert.match(html,new RegExp(`data-opening-panel="${id}" >`));
  assert(!html.includes('<main>'));assert(!html.includes('卡组关键卡与配合说明'));
});
test('route summary explains unresolved randomness without presenting a verified one-card line',()=>{
  const r={key:'x',sources:[{name:'route',plan_id:'p',revision:'hash'}],condition:{status:'random',reason:'未知翻牌'},turn_order:'first',opening:[{code:1,count:1}],generic_cost:0,required_hand:1,one_card:false,endboard:[],endboard_count:0,steps:[],relative_unused:[]};
  const html=renderer().openingRouteCard(r,result(),false);
  assert(html.includes('含随机结果'));assert(html.includes('未知翻牌'));assert(!html.includes('一卡起手依据'));
});

test('opening route preserves fixed granted constraints from its frozen capability snapshot',()=>{
  const r={key:'granted',sources:[{name:'route',plan_id:'p',revision:'hash'}],condition:{status:'satisfied',reason:''},
    turn_order:'first',opening:[],generic_cost:0,required_hand:0,one_card:false,endboard_count:1,steps:[],relative_unused:[],
    endboard:[{code:15092394,name:'急袭猛禽-异邦猎鹰',effect:'m1',status:'reviewed',capability:{tags:[],facts:[
      {label:'固定获赋效果',text:'须另行满足发动或适用条件'},
      {label:'固定获赋效果·时点',text:'自己主要阶段'},
      {label:'固定获赋效果·费用',text:'取除本卡1个素材'},
      {label:'固定获赋效果·次数',text:'每回合1次'},
      {label:'条件',text:'有超量怪兽素材'}
    ]}}]};
  const before=JSON.stringify(r);
  const html=renderer().openingRouteCard(r,result(),false);
  assert(html.includes('须另行满足发动或适用条件'));
  assert(html.includes('固定获赋效果·时点：自己主要阶段'));
  assert(html.includes('固定获赋效果·费用：取除本卡1个素材'));
  assert(html.includes('固定获赋效果·次数：每回合1次'));
  assert(html.includes('条件：有超量怪兽素材'));
  assert.equal(JSON.stringify(r),before,'rendering must not modify the frozen snapshot');
});
