'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
module.exports=async({page,nativeWait,nativeState,hostWait,waitHistory,pass,evidence})=>{
  const request=(url,body)=>page.evaluate(({url,body})=>api(url,body),{url,body});
  for(const [code,alias] of [[18144507,18144506],[23434539,23434538]]){
    const card=await request('/api/card/'+code);assert.equal(card.alias,alias);assert.equal(card.script_available,true);
  }
  async function start(deck,hand,label){
    const saved=await request('/api/decks',{name:label+'-'+Date.now(),deck});
    await page.evaluate(async({saved,hand,label})=>{
      flow.draft=null;flow.design=null;await switchModule('expansion');
      await mountDesign({...saved,deck_name:saved.name,name:label,notes:'隔离规则引擎验收',
        conditions:{hand_count:hand.length,slots:hand,banned:[]},opponent_ai:false,opponent_responses:false,
        opponent_config:{...await api('/api/opponent'),conditions:{hand_count:1,slots:[null],banned:[]}},
        turn_order:'first',player_lp:8000,opponent_lp:8000,timer:{mode:'off',seconds:0}});
    },{saved,hand,label});
    await page.locator('#begin-expansion').click();await page.waitForFunction(()=>app.active&&!flow.busy);
    const id=await page.evaluate(()=>app.active.id);await hostWait(id,s=>s.frame_ready);await nativeWait(id,s=>s.prompt===11);
    const report=await request('/api/report/'+id);assert(report.loaded_verified);assert.deepEqual(report.expansion.actual_opening,hand);
    assert.deepEqual(report.deck,deck);assert(!report.warnings.some(w=>w.includes('脚本诊断')));
    return id;
  }
  async function finish(){await page.locator('#finish-training').click();await waitHistory('completed');await page.waitForFunction(()=>!app.active&&!flow.busy);}
  const maxx=await start({main:[23434539,...Array(39).fill(1184620)],extra:[],side:[]},[23434539],'异画增殖的G脚本');
  let state=await nativeWait(maxx,s=>s.targets.some(t=>t.code===23434539&&t.location===2));
  let target=state.targets.find(t=>t.code===23434539&&t.location===2);await nativeState(maxx,'click',{x:target.x,y:target.y});
  state=await nativeWait(maxx,s=>s.buttons.some(b=>b.text==='发动'));target=state.buttons.find(b=>b.text==='发动');
  await nativeState(maxx,'click',{x:target.x,y:target.y});
  await nativeWait(maxx,s=>s.prompt===11&&!s.targets.some(t=>t.code===23434539&&t.location===2));
  const activated=await request('/api/report/'+maxx);
  assert(activated.events.some(e=>e.message===70&&e.cards?.some(c=>c.code===23434539||c.code===23434538)));
  assert(activated.final_state.cards.some(c=>c.controller===0&&c.location===16&&c.code===23434539));
  assert(!activated.warnings.some(w=>w.includes('脚本诊断')));
  await page.screenshot({path:path.join(evidence,'artwork-alias-effect.png')});await finish();
  let deck={main:[18144507,...Array(39).fill(1184620)],extra:[],side:[]},hand=[18144507];
  if(process.env.YGO_ALIAS_REPLAY){
    const captured=JSON.parse(fs.readFileSync(process.env.YGO_ALIAS_REPLAY,'utf8')).recognition.context;
    deck=captured.deck.deck;hand=captured.hand;
    assert(deck.main.includes(18144507));
  }
  const replay=await start(deck,hand,'异画羽毛扫冻结输入复测');
  await page.screenshot({path:path.join(evidence,'artwork-alias-frozen-input.png')});await finish();
  fs.writeFileSync(path.join(evidence,'alias-scripts-result.json'),JSON.stringify({maxx,replay,privateReplay:!!process.env.YGO_ALIAS_REPLAY,passed:true},null,2));
  pass('Native artwork-alias scripts: alternate Maxx C activates and resolves its real effect; alternate Duster deck and frozen hand initialize with exact input and no script diagnostics');
};
