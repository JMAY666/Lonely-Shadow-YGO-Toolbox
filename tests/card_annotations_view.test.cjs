const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../src/trainer/web/card-annotations.js'), 'utf8');

function setup() {
  const nodes = new Map();
  const $ = key => {
    if (!nodes.has(key)) nodes.set(key, {value: '', textContent: '', innerHTML: '', hidden: false,
      setAttribute() {}, style: {}});
    return nodes.get(key);
  };
  const context = vm.createContext({$, URL, structuredClone, setTimeout: () => 1, clearTimeout() {},
    escape: s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])),
    notice() {}, run: fn => fn,
    api: async () => ({})});
  vm.runInContext(source.slice(0, source.indexOf("$('#card-annotations').addEventListener"))
    + '\nglobalThis.e={annoUI,annoEffectLabel,annoCardKind,annoEvidenceItems,annoProcessingLines,annoStructureLines,annoOverviewHTML,annoResultsHTML,annoDetailHTML,annoRelationLabel,annoMonsterBadgesHTML,annoSeriesBadgesHTML,annoFoldersHTML,annoTagBadgeHTML,annoRenderShell,annoSortedFolders,annoArtPosition,annoArtPopoverHTML};', context);
  return {context, $, ...context.e};
}

const registry = {
  tags: {'etag:add-hand': {id: 'etag:add-hand', name: '加入手卡', definition: '', category: 'resource', synonyms: []},
         'etag:banish': {id: 'etag:banish', name: '除外', definition: '', category: 'removal', synonyms: []}},
  actions: {add_hand: '加入手卡', banish: '除外', special_summon: '特殊召唤'},
  zones: {deck: '卡组', hand: '手卡', grave: '墓地', banished: '除外区', monster: '怪兽区'},
  cost_kinds: {discard_self: '把这张卡从手卡丢弃'},
  usage_limits: {name_soft_opt: '这个卡名的效果1回合只能使用1次'},
  timings: {on_summon: '召唤·特殊召唤成功时', manual: '任意时点'},
  categories: {resource: '资源与检索', removal: '除去与转移'},
};

test('effect labels distinguish numbered, leading text and pendulum blocks', () => {
  const e = setup();
  assert.equal(e.annoEffectLabel({number: 2, key: 'm2', block: 'm'}), '②');
  assert.equal(e.annoEffectLabel({number: 1, key: 'p1', block: 'p'}), '灵摆·①');
  assert.equal(e.annoEffectLabel({number: null, key: 'm-pre', block: 'm'}), '无编号前文');
  assert.equal(e.annoEffectLabel({number: null, key: 'm-pre', block: 'm', effect_type: 'non_effect'}), '规则与限制');
});

test('card kinds combine type bits and normal monsters stay distinguishable', () => {
  const e = setup();
  assert.equal(e.annoCardKind(0x21), '效果怪兽');
  assert.equal(e.annoCardKind(0x11), '通常怪兽');
  assert.equal(e.annoCardKind(0x2), '通常魔法');
  assert.equal(e.annoCardKind(0x102), '通常魔法');
  assert.equal(e.annoCardKind(0x100004), '反击陷阱');
});

test('evidence rows use human-readable labels', () => {
  const e = setup(); e.annoUI.registry = registry;
  const html = e.annoEvidenceItems({evidence: [
    {condition: 'tag', value: ['etag:add-hand'], basis: '效果 TAG'},
    {condition: 'from_zone', value: 'deck', basis: '卡组'}]});
  assert.match(html, /效果 TAG：加入手卡 — 效果 TAG/);
  assert.match(html, /来源区域：卡组 — 卡组/);
});

test('processing lines render nested then and conditional branches with selectors', () => {
  const e = setup();
  const lines = e.annoProcessingLines([
    {action: 'add_hand', count: '1', from_zones: ['deck'], to_zones: ['hand'], selector: {text: '1只怪兽'}},
    {action: 'banish', selector: {text: '那张卡'}, then: [{action: 'special_summon', count: 'up_to_1', from_zones: ['grave']}],
     branches: [{condition: '盖放发动', actions: [{action: 'banish', selector: {text: '同纵列卡'}}]}]}], registry);
  assert.match(lines[0], /加入手卡×1（卡组 → 手卡）：1只怪兽/);
  assert.ok(lines.some(line => line.includes('↳') && line.includes('特殊召唤×至多1')));
  assert.ok(lines.some(line => line.includes('若「盖放发动」')));
});

test('structure lines cover activation, cost, targeting, usage and fast-effect note', () => {
  const e = setup();
  const lines = e.annoStructureLines({structure: {
    activation: {timing: 'on_summon', zones: ['hand'], conditions: ['手卡发动需自己场上没有卡'], fast_effect: true},
    cost: [{kind: 'discard_self', text: '把这张卡从手卡丢弃'}],
    targeting: [{count: 1, filter: '对方场上1只表侧表示怪兽'}],
    processing: [{action: 'banish', selector: {text: '对象怪兽'}}],
    usage: ['name_soft_opt']}}, registry);
  assert.ok(lines.some(line => line.startsWith('发动：召唤·特殊召唤成功时') && line.includes('区域 手卡') && line.includes('快速效果；仍须满足发动条件')));
  assert.ok(lines.some(line => line.includes('费用：把这张卡从手卡丢弃')));
  assert.ok(lines.some(line => line.includes('对象：1×')));
  assert.ok(lines.some(line => line.includes('次数：这个卡名的效果1回合只能使用1次')));
});

test('results list shows per-effect hits, cross-effect warning and unknown-is-not-negative note', () => {
  const e = setup();
  const html = e.annoResultsHTML({total: 1, offset: 0, annotated_total: 4, catalog_total: 5,
    note: '查询只在已标注范围内命中', cards: [
      {code: 20000003, name: '测试卡', type: 0x21, status: 'reviewed', cross_effects: true,
       hits: [{key: 'm1', number: 1, block: 'm', text: '①：测试效果', tags: ['etag:add-hand'],
               evidence: [{condition: 'tag', value: ['etag:add-hand'], basis: '效果 TAG'}]}]}]});
  assert.match(html, /找到 1 张/);
  assert.match(html, /跨效果命中/);
  assert.match(html, /已核对/);
  assert.doesNotMatch(html, /①：测试效果/, 'list does not duplicate full effect text');
  const empty = e.annoResultsHTML({total: 0, offset: 0, annotated_total: 4, catalog_total: 5, note: '', cards: []});
  assert.match(empty, /未标注不代表没有该能力/);
});

test('detail marks stale entries, unannotated segments and drafts as auto', () => {
  const e = setup();
  const stale = e.annoDetailHTML({code: 1, name: '测试', type: 2, status: 'stale', digest_ok: false,
    text_digest: 'a'.repeat(64), review: {status: 'reviewed', origin: 'manual'},
    provenance: {source: 'curated', title: '内置资料', checked_on: '2026-09-24'},
    no_effect: false, missing_keys: [], relations: [], notes: [],
    effects: [{key: 'm1', number: 1, block: 'm', text: '①：旧文本', annotated: true, tags: ['etag:add-hand'], notes: []},
              {key: 'm2', number: null, block: 'm', text: '前置文本', annotated: false}]}, registry);
  assert.match(stale, /卡库卡文已变化/);
  assert.match(stale, /未标注/);
  assert.ok(!stale.includes('data-anno-op="draft"'), 'stale entries cannot generate drafts');
  e.annoUI.editing = true;
  const fresh = e.annoDetailHTML({code: 1, name: '测试', type: 2, status: 'none', digest_ok: true,
    text_digest: 'a'.repeat(64), review: null, provenance: null, no_effect: false,
    missing_keys: ['m1'], relations: [], notes: [], effects: [{key: 'm1', number: 1, block: 'm', text: '①', annotated: false}]}, registry);
  assert.match(fresh, /data-anno-op="draft"/);
});

test('overview chips reflect selectable statuses and catalog source digest', () => {
  const e = setup();
  const html = e.annoOverviewHTML({catalog: {cards: 14981, sources: [{path: 'cards.cdb', sha256: '5f13245de4e6'}]},
    tokens: 265, annotated_total: 11, statuses: {reviewed: 11, none: 14970, stale: 0},
    curated: {title: '样本', checked_on: '2026-09-24'}, registry: {tags: 18}, stale_codes: [], missing_codes: [], note: '未标注 ≠ 没有能力'});
  assert.match(html, /卡库 14981 张 · 衍生物 265/);
  assert.match(html, /cards\.cdb/);
  assert.match(html, /<details class="anno-coverage">/);
  assert.match(html, /未标注 ≠ 没有能力/);
  assert.doesNotMatch(html, /待核对<\/span>/, 'no stale highlight when none are stale');
});

test('read mode hides mutation controls and preserves optional branches and duration', () => {
  const e = setup();
  const view = {code:1,name:'测试',type:0x10002,status:'reviewed',digest_ok:true,full:true,origin:'manual',
    effects:[{key:'m1',number:1,annotated:true,text:'效果原文',tags:['etag:add-hand'],structure:{processing:[]}}],missing_keys:[]};
  const read = e.annoDetailHTML(view,registry);
  assert.doesNotMatch(read, /data-anno-note-input|data-anno-tag-add|data-anno-op=/);
  assert.match(read, /速攻魔法/);
  e.annoUI.editing = true;
  assert.match(e.annoDetailHTML(view,registry), /data-anno-note-input/);
  const lines = e.annoProcessingLines([{action:'add_hand',branch:'B',optional:true,duration:'直到下回合结束',count:'all'}],registry);
  assert.ok(lines.some(line=>line.includes('分支 B（选择其一）')));
  assert.ok(lines.some(line=>line.includes('可选：加入手卡×全部')));
  assert.ok(lines.some(line=>line.includes('直到下回合结束')));
});

test('stale no-effect cards keep old flavor separate from the current text', () => {
  const e = setup();
  const html = e.annoDetailHTML({code:1,name:'测试',type:0x11,status:'stale',digest_ok:false,no_effect:true,
    effects:[{key:'m-all',text:'旧版描述'}],current_text:'新版原文',missing_keys:[]},registry);
  const reading = html.split('资料来源与核对信息')[0];
  assert.match(reading,/旧版描述/);
  assert.doesNotMatch(reading,/新版原文/);
  assert.match(html,/当前卡库原文（未套用旧标注）/);
});

test('monster symbols retain hybrid types without calling every pendulum or ritual an extra monster', () => {
  const e = setup();
  const hybrid = e.annoMonsterBadgesHTML(0x1002041);
  assert.match(hybrid,/额外卡组/);assert.match(hybrid,/∞/);assert.match(hybrid,/✧/);assert.match(hybrid,/◈/);
  assert.doesNotMatch(e.annoMonsterBadgesHTML(0x1000021),/class="anno-badge anno-extra"/);
  assert.doesNotMatch(e.annoMonsterBadgesHTML(0x81),/额外卡组/);
  assert.equal(e.annoMonsterBadgesHTML(0x82),'','ritual spells are not monsters');
  assert.match(e.annoMonsterBadgesHTML(0x800021),/◎/);
  assert.match(e.annoMonsterBadgesHTML(0x4000021),/↗/);
});

test('effect colours are category-based and keep escaped labels and definitions', () => {
  const e = setup();
  assert.match(e.annoTagBadgeHTML('etag:add-hand',registry),/data-category="resource"/);
  assert.match(e.annoTagBadgeHTML('etag:banish',registry),/data-category="removal"/);
  assert.match(e.annoSeriesBadgesHTML([{name:'<test>',emblem:'<svg onload=x>',tone:'ice',name_basis:'依据'}]),/&lt;test&gt;/);
  assert.doesNotMatch(e.annoSeriesBadgesHTML([{name:'x',emblem:'<svg onload=x>'}]),/onload/);
});

test('folder homepage exposes local covers, Chinese tie-breaks and a closed art popover', () => {
  const e = setup();
  const folders = ['转生炎兽','相剑','青眼','驱魔姐妹','杀手旋律'].map((name,i)=>({id:'set:'+i,name,cover_code:i+1,count:2,annotated:1}));
  const html = e.annoFoldersHTML({total:10,folders});
  const names = [...e.annoUI.folders].map(f=>f.name);
  assert.deepEqual(names,['青眼','驱魔姐妹','杀手旋律','相剑','转生炎兽']);
  assert.match(html,/src="\/pics\/3.jpg"/);
  assert.match(html,/data-anno-folder/);
  e.annoRenderShell();
  assert.match(e.$('#card-annotations').innerHTML,/<details id="anno-advanced" class="anno-more">/);
  assert.equal(e.annoUI.mode,'folders');
  const view={code:1,name:'卡',type:0x21,digest_ok:true,effects:[]};
  const detail=e.annoDetailHTML(view,registry);
  assert.match(detail,/id="anno-art-toggle" aria-controls="anno-art-popover" aria-expanded="false"/);
  assert.doesNotMatch(detail,/<img src=/);
  assert.match(e.annoArtPopoverHTML(),/popover="auto"/);
  assert.doesNotMatch(e.annoArtPopoverHTML(),/src=/);
});

test('series release sorting handles both directions, ties, unknown dates and unassigned cards', () => {
  const e=setup();
  const input=[{id:'unassigned',name:'无系列归属'}, {id:'unknown',name:'日期未知'},
    {id:'old',name:'旧系列',release:{date:'2001-01-01'}},
    {id:'new-b',name:'相剑',release:{date:'2025-01-01'}},
    {id:'new-a',name:'青眼',release:{date:'2025-01-01'}}];
  assert.deepEqual([...e.annoSortedFolders(input,'newest')].map(f=>f.id),['new-a','new-b','old','unknown','unassigned']);
  assert.deepEqual([...e.annoSortedFolders(input,'oldest')].map(f=>f.id),['old','new-a','new-b','unknown','unassigned']);
});

test('each card result has a small picture beside its metadata', () => {
  const e=setup();
  const html=e.annoResultsHTML({total:1,offset:0,cards:[{code:123,name:'测试',type:0x21,status:'none',hits:[]}]});
  assert.match(html,/<img class="anno-card-thumb" src="\/pics\/123.jpg" alt="" loading="lazy"><span class="anno-card-copy">/);
});

test('art popover stays inside viewport near right and bottom edges', () => {
  const e=setup();
  for (const [x,y] of [[800,600],[5,5],[400,590]]) {
    const p=e.annoArtPosition(x,y,258,385,820,620);
    assert.ok(p.left>=12&&p.top>=12);
    assert.ok(p.left+258<=808&&p.top+385<=608);
  }
});
