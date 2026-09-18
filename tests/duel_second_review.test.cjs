'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
test('review renders frozen knowledge separately, escapes user notes and never resolves unknown cards from the later catalog',()=>{
  const context={escape:v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'),
    SecondDuelModel:{phases:{main1:'主要阶段 1'},zones:{4:'怪兽区'}},
    secondName:(doc,code)=>doc.catalog[code]?.name||'未知'};
  vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/trainer/web/duel-second-hints.js'),'utf8'),context);
  const doc={catalog:{1:{name:'我方手坑'},999:{name:'后来才知道的隐藏卡'}}};
  const data={notice:'当时与实际分开',known_state:{turn:1,turn_player:1,phase:'main1',cards:[{controller:0,location:2,code:1},{controller:1,location:8,code:null}],window:{label:'原窗口'}},decisions:[{choice:'use'}],
    notes:[{kind:'choice',time_ms:1,note:'<img src=x onerror=bad>'}],actual:{notice:'实际观察',own_hand_departures:[1],opponent_field_departures:[],
      actions:[{player:0,selection:[{kind:'activate',card:{code:1}}]},{player:1,selection:[]}],outcomes:[{kind:'effect_negated',link:1}]}};
  const html=context.secondReviewHtml(doc,data);
  assert.match(html,/手牌 1 张/);assert.match(html,/未知盖卡/);assert(!html.includes('后来才知道的隐藏卡'));
  assert(html.includes('&lt;img'));assert(!html.includes('<img'));assert.match(html,/随后实际/);assert.match(html,/连锁 1：效果被无效/);
  assert.match(html,/尚未自动核实/);
});
