'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),test=require('node:test');
const source=path.join(__dirname,'../src/trainer/web/intelligence-matchups.js');
const escape=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
function setup(){
  const data={topics:{topic:{name:'OCG · 样例牌组',tag_ids:['tag']}},tags:[{id:'tag',name:'融合主题'}],card_tags:{22:['response-tag']}};
  const context=vm.createContext({URL,escape,tagSearchKey:value=>String(value??'').toLowerCase(),intelUI:{data,decks:[]},intelBadge:text=>`<span>${escape(text)}</span>`,intelRef:code=>`<span data-card="${code}"></span>`,intelCard:code=>({name:({11:'起动卡',22:'灰流丽',33:'无限泡影'})[code]||`卡库缺失 · ${code}`})});
  vm.runInContext(fs.existsSync(source)?fs.readFileSync(source,'utf8'):'',context);
  return {context,data};
}
function record(){return {id:'matchup',title:'示例的关键断点',topic_id:'topic',status:'已记录',note:'保留资源',research:{format:'OCG',period:'2026-07—2026-09',reviewed_at:'2026-09-20',summary:'先识别检索方向',recognition:'观察第一张起动卡',priorities:'优先打断检索',warnings:'不要过早交牌',metagame:'公开比赛样本',sources:[]},steps:[{opponent:11,action:'发动检索效果',timing:'连锁该效果',condition:'已确认该效果检索',note:'各断点独立判断',responses:[{mode:'alternative',cards:[22],method:'无效这个效果',condition:'可以从手牌发动',expected:'阻止这次检索',note:'仍需确认后续补点'},{mode:'combination',cards:[22,33],method:'先处理保护再响应',condition:'两张牌都满足条件',expected:'配合处理',note:''}]}]};}

test('record filters separate OCG, Master Duel and personal records and search research, cards and tags',()=>{
  const {context:c,data}=setup(),ocg=record(),md={...record(),id:'md',research:{...record().research,format:'Master Duel'}},personal={...record(),id:'personal'};delete personal.research;
  const all=[ocg,md,personal],filtered=f=>all.filter(r=>c.intelMatchupMatches(r,f,data,c.intelCard)).map(r=>r.id);
  assert.deepEqual(filtered({format:'OCG'}),['matchup']);
  assert.deepEqual(filtered({format:'Master Duel'}),['md']);
  assert.deepEqual(filtered({format:'personal'}),['personal']);
  assert.deepEqual(filtered({q:'先识别'}),['matchup','md']);
  assert.deepEqual(filtered({q:'灰流丽',format:'OCG',tag:'response-tag',topic:'topic'}),['matchup']);
  assert.deepEqual(filtered({q:'融合主题'}),['matchup','md','personal']);
  assert.deepEqual(filtered({q:'无限泡影',topic:'other'}),[]);
  assert.deepEqual(filtered({q:'不存在的卡'}),[]);
});

test('research sources link only absolute http(s) URLs and escape all supplied titles and notes',()=>{
  const {context:c}=setup(),html=c.intelMatchupSources({sources:[
    {id:'safe',title:'环境 <img src=x onerror=alert(1)>',url:'https://example.org/report?q="card"&format=OCG',kind:'metagame',published_at:'2026-09-01',note:'样本 <script>bad()</script>'},
    {id:'http',title:'对策',url:'http://example.org/strategy',kind:'strategy'},
    {id:'card',title:'卡文',url:'https://example.org/card',kind:'card_text'},
    {id:'js',title:'不安全链接',url:'javascript:alert(1)',kind:'strategy'},
    {id:'relative',title:'相对链接',url:'/local-file',kind:'strategy'},
    {id:'data',title:'数据链接',url:'data:text/html,bad',kind:'strategy'}
  ]});
  assert.equal((html.match(/<a /g)||[]).length,3);
  assert.match(html,/rel="noopener noreferrer"/);
  assert.match(html,/环境证据/);assert.match(html,/对策参考/);assert.match(html,/卡文核对/);
  assert.match(html,/&lt;img/);assert.match(html,/&lt;script&gt;/);
  assert(!html.includes('<img'));assert(!html.includes('<script>'));assert(!/href="(?:javascript:|data:|\/local)/.test(html));
});

test('reading separates conditional breakpoints and alternatives from a multi-card combination',()=>{
  const {context:c}=setup(),r=record();r.title='<svg onload=bad()>标题';r.steps[0].responses[0].method='<img src=x>应对';
  const before=JSON.stringify(r),html=c.intelMatchupReader(r);
  assert.match(html,/看到对手做什么/);assert.match(html,/何时交/);assert.match(html,/前提/);
  assert.match(html,/单独可选/);assert.match(html,/组合/);assert.match(html,/按当前局面选择/);
  for(const text of ['先识别检索方向','2026-07—2026-09','2026-09-20','尚未经规则引擎验证','可以从手牌发动','阻止这次检索','仍需确认后续补点'])assert(html.includes(text),text);
  assert(!html.includes('<svg'));assert(!html.includes('<img src=x>'));assert.match(html,/&lt;svg/);
  assert.equal(JSON.stringify(r),before,'Reading must never change saved data or the pending draft');
});

test('card walkthrough connects only valid breakpoint indices and resolves evidence by source identity',()=>{
  const {context:c}=setup(),r=record();
  r.research.sources=[{id:'card',title:'效果原文',url:'https://example.org/card',kind:'card_text'},{id:'strategy',title:'策略说明',url:'https://example.org/strategy',kind:'strategy'}];
  r.research.step_sources=[['card','strategy','absent']];
  r.research.walkthrough={premise:'起手只有此起动卡',sequence:[{card:11,action:'发动检索',result:'取得后续卡',step_index:0},{card:null,action:'继续展开',result:'可能形成终场',step_index:null},{card:22,action:'<script>bad()</script>',result:'不存在断点',step_index:99}],branches:[{label:'放行',body:'对手取得后续卡'},{label:'此处阻抗',body:'本次检索被阻止'},{label:'仍有补点',body:'对手可能继续'}],conclusion:'手工卡文推演，尚未通过引擎验收',source_ids:['strategy']};
  const html=c.intelMatchupReader(r);
  assert.match(html,/intel-walkthrough/);assert.match(html,/起手只有此起动卡/);assert.match(html,/第 1 步/);
  assert.match(html,/得到什么/);assert.match(html,/取得后续卡/);assert.match(html,/data-intel-breakpoint="0"/);
  assert(!html.includes('data-intel-breakpoint="99"'));assert(!html.includes('<script>'));
  assert.match(html,/id="intel-matchup-step-0"/);assert.match(html,/依据：/);
  assert.equal((html.match(/href="https:\/\/example.org\/card"/g)||[]).length,2,'The step and reference list both cite the matching card source');
  for(const text of ['放行','此处阻抗','仍有补点','手工卡文推演'])assert(html.includes(text),text);
});

test('manual step edits keep the original route but remove stale step links and source bindings',()=>{
  const {context:c,data}=setup(),r=record();
  r.research.sources=[{id:'card',title:'原路线卡文',url:'https://example.org/card',kind:'card_text'}];
  r.research.step_sources=[['card']];
  r.research.walkthrough={premise:'原前提',sequence:[{card:11,action:'原始动作',result:'原始结果',step_index:0}],branches:[],conclusion:'原始推演',source_ids:['card']};
  data.records={matchup:structuredClone(r)};
  r.steps[0].action='当前未保存的另一动作';
  const html=c.intelMatchupReader(r);
  assert.match(html,/原始导入路线/);assert.match(html,/当前断点已手动调整/);assert.match(html,/原始动作/);assert.match(html,/当前未保存的另一动作/);
  assert(!html.includes('data-intel-breakpoint='));
  assert.equal((html.match(/href="https:\/\/example.org\/card"/g)||[]).length,2,'Only original walkthrough and global references retain the source');
  r.steps=data.records.matchup.steps;r.research.steps_edited=true;
  assert(!c.intelMatchupReader(r).includes('data-intel-breakpoint='),'Persisted prior manual edits remain explicit');
});

test('walkthrough-only cards participate in card number and TAG filters',()=>{
  const {context:c,data}=setup(),r=record();
  r.research.walkthrough={sequence:[{card:99,action:'路线独有卡',result:'补资源'}]};
  data.card_tags[99]=['route-tag'];
  assert.equal(c.intelMatchupMatches(r,{q:'99'},data,c.intelCard),true);
  assert.equal(c.intelMatchupMatches(r,{tag:'route-tag'},data,c.intelCard),true);
});

test('a deleted researched draft becomes personal while preserving every research field and source',()=>{
  const {context:c}=setup(),r=record();
  r.research.sources=[{title:'卡文依据',url:'https://example.org/card',note:'原始核对说明'}];
  r.research.walkthrough={premise:'原路线前提',sequence:[{card:11,action:'原动作',result:'原结果'}],branches:[{label:'打断后',body:'分支结果'}],conclusion:'条件推演'};
  assert.equal(typeof c.intelMatchupDetachResearch,'function');
  c.intelMatchupDetachResearch(r);
  assert.equal(r.research,undefined);
  for(const text of ['先识别检索方向','原始核对说明','https://example.org/card','原路线前提','原动作','原结果','分支结果','条件推演'])assert(r.reference_copy.includes(text),text);
});

test('topic hierarchy uses record formats, retains identities and groups the two environments',()=>{
  const {context:c,data}=setup();
  data.topics={ocg:{id:'ocg',name:'OCG · 闪刀',tag_ids:[]},md:{id:'md',name:'Master Duel · 闪刀',tag_ids:[]},personal:{id:'personal',name:'我的 <笔记>',tag_ids:[]}};
  data.records={a:{...record(),topic_id:'ocg'},b:{...record(),topic_id:'md',research:{...record().research,format:'Master Duel'}}};
  const before=JSON.stringify(data);
  assert.equal(typeof c.intelTopicOptionsHtml,'function');
  const all=c.intelTopicOptionsHtml(data,'md','');
  assert.match(all,/<optgroup label="OCG">/);assert.match(all,/<optgroup label="Master Duel">/);
  assert.match(all,/<option value="md" selected>闪刀<\/option>/);
  assert.match(all,/我的 &lt;笔记&gt;/);assert(!all.includes('OCG · 闪刀'));
  const ocg=c.intelTopicOptionsHtml(data,'','OCG');
  assert.match(ocg,/value="ocg"/);assert(!ocg.includes('value="md"'));assert(!ocg.includes('value="personal"'));
  assert.equal(JSON.stringify(data),before);
});

test('shared and empty personal topics remain reachable without guessing format from their names',()=>{
  const {context:c,data}=setup();
  data.topics={mixed:{name:'共用主题'},empty:{name:'OCG · 我的空主题'}};
  data.records={a:{...record(),topic_id:'mixed'},b:{...record(),topic_id:'mixed',research:{...record().research,format:'Master Duel'}}};
  assert.equal(typeof c.intelTopicOptionsHtml,'function');
  for(const format of ['OCG','Master Duel'])assert.match(c.intelTopicOptionsHtml(data,'mixed',format),/value="mixed" selected/);
  const all=c.intelTopicOptionsHtml(data,'','');
  assert.equal((all.match(/value="mixed"/g)||[]).length,1);
  assert.match(c.intelTopicOptionsHtml(data,'','personal'),/OCG · 我的空主题/);
  assert(!c.intelTopicOptionsHtml(data,'','OCG').includes('value="empty"'));
});
