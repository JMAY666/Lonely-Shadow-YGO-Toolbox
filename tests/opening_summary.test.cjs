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
