'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const file=path.join(__dirname,'../src/trainer/web/intelligence-opponents.js');
const escape=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
function setup(){const c=vm.createContext({escape,tagSearchKey:s=>String(s??'').toLowerCase(),intelBadge:s=>'<span>'+escape(s)+'</span>',tagCatalogueCard:c=>'<button class="review-card" data-card="'+c.id+'">'+escape(c.name)+'</button>',intelMatchupUrl:s=>s.startsWith('https://')?s:'',console});if(fs.existsSync(file))vm.runInContext(fs.readFileSync(file,'utf8'),c);return c;}
function fixture(){return {checked_at:'2026-09-20',periods:[{id:'p',format:'OCG',label:'九月样本',start:'2026-09-01',end:'2026-09-20',sample_size:100,metric:'公开样本占比',note:'不等于天梯占有率',source_ids:['s']}],tags:[{id:'set:62',name:'卡通'}],sources:[{id:'s',title:'公开构筑来源',url:'https://example.org/report'}],cards:{11:{id:11,name:'卡牌甲'},22:{id:22,name:'卡牌乙'}},decks:[{id:'d',name:'卡通代表构筑',period_id:'p',format:'OCG',archetype:'toon',tag_ids:['set:62'],source_ids:['s'],sample_count:20,sample_size:100,share:.2,reported_date:'2026-09-06',date_note:'赛事日期',counts:{main:40,extra:15,side:null},main:[{code:11,quantity:3}],extra:[{code:22,quantity:1}],side:null,routes:[1,2].map(i=>({id:'route-'+i,title:'路线 '+i,opening:{cards:[{code:11,quantity:1}],other_cards:1,conditions:'空场并有一张可用素材'},steps:[{id:'step',cards:[11,22],action:'展开操作',result:'得到资源'}],endboard:[{code:22,quantity:1,note:'基础终场'}],source_ids:['s'],validation:'card_text_reviewed',notes:'按条件推演'}))}]};}
test('opponent filters compose environment, source period, TAG and composition card search',()=>{
 const c=setup(),d=fixture();assert.equal(typeof c.intelOpponentMatches,'function');
 assert(c.intelOpponentMatches(d.decks[0],{format:'OCG',period:'p',tag:'set:62',q:'卡牌甲'},d));
 for(const filter of [{format:'Master Duel'},{period:'other'},{tag:'other'},{q:'未知'}])assert(!c.intelOpponentMatches(d.decks[0],filter,d));
 assert(c.intelOpponentMatches(d.decks[0],{q:'22'},d));
});
test('composition preview exposes counts, source denominator and two routes without editing controls',()=>{
 const c=setup(),d=fixture();assert.equal(typeof c.intelOpponentReader,'function');
 const before=JSON.stringify(d),html=c.intelOpponentReader(d.decks[0],d);
 for(const text of ['20.0%','20 / 100','40','15','副卡组未披露','路线 1','路线 2','起手条件','预期终场','尚未经规则引擎验证','https://example.org/report'])assert(html.includes(text),text);
 assert(!html.includes('data-intel-field'));assert(!html.includes('<textarea'));assert(!html.includes('contenteditable'));assert(!html.includes('data-intel-action="save"'));
 assert.equal(JSON.stringify(d),before);
 d.decks[0].name='<img src=x onerror=bad()>构筑';assert(!c.intelOpponentReader(d.decks[0],d).includes('<img src=x'));
});
