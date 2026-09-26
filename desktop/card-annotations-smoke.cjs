'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

module.exports = async ({page, application, root, evidence, pass}) => {
  const enter = async name => {
    await require('./navigation-test.cjs')(page, name);
    await page.waitForFunction(name => moduleUI.current === name && !moduleUI.switching, name);
  };
  const search = async q => {
    await page.locator('#anno-q').fill(q);
    await page.locator('#anno-form button[type="submit"]').first().click();
  };
  const reset = async () => {
    await page.locator('#anno-reset').click();
    await page.waitForFunction(()=>annoUI.mode==='folders'&&!annoUI.busy&&annoUI.folders.length>100);
  };
  const selectCard = async code => {
    if (await page.evaluate(()=>annoUI.mode==='folders')) await page.locator('[data-anno-mode="cards"]').click();
    await search(String(code));
    await page.waitForFunction(code=>annoUI.detail?.code===code,code);
  };
  for (const name of ['tags', 'intelligence', 'modular']) await enter(name);
  await enter('cardanno');
  await page.waitForFunction(()=>!annoUI.busy&&annoUI.folders.length>100);
  const annotated = Object.keys(JSON.parse(fs.readFileSync(path.join(__dirname,'../src/trainer/card-annotations.json'),'utf8')).cards).length;
  assert.match(await page.locator('#anno-overview').textContent(), new RegExp(`已标注 ${annotated} 张`));
  assert.equal(await page.locator('#anno-advanced').getAttribute('open'),null);
  assert.equal(await page.locator('#anno-kind').isVisible(),false);
  assert.equal(await page.locator('#anno-card-layout').isVisible(),false);
  assert.equal(await page.locator('#anno-folders').isVisible(),true);
  assert.equal(await page.locator('[data-anno-note-input]').count(),0);
  assert.match(await page.locator('#anno-overview').textContent(),/14,716/);
  const releaseDates=await page.evaluate(()=>annoUI.folders.filter(f=>f.release?.date).map(f=>f.release.date));
  assert.deepEqual(releaseDates,[...releaseDates].sort().reverse());
  assert.equal(await page.locator('#anno-folder-sort').inputValue(),'newest');
  assert.ok((await page.locator('.anno-folder').first().boundingBox()).height<=100,'folder height is compact');
  await page.locator('#anno-folder-sort').selectOption('oldest');
  const oldest=await page.evaluate(()=>annoUI.folders.filter(f=>f.release?.date).map(f=>f.release.date));
  assert.deepEqual(oldest,[...oldest].sort());
  await page.locator('#anno-folder-sort').selectOption('name');
  const names=await page.evaluate(()=>annoUI.folders.filter(f=>f.id!=='unassigned').map(f=>f.name));
  assert.deepEqual(names,[...names].sort(new Intl.Collator('zh-Hans-CN',{numeric:true}).compare));
  await page.locator('#anno-folder-sort').selectOption('newest');
  await page.waitForFunction(()=>[...document.querySelectorAll('.anno-folder-cover img')].slice(0,5).every(i=>i.complete&&i.naturalWidth>0));
  await page.screenshot({path:path.join(evidence,'annotations-folders.png')});
  // Folder paging and the independent no-series collection.
  await page.locator('[data-anno-folder-page="48"]').click();
  assert.equal(await page.evaluate(()=>annoUI.folderOffset),48);
  await page.locator('[data-anno-folder-page="0"]').click();
  await page.locator('.anno-folder-heading [data-anno-folder="unassigned"]').click();
  await page.waitForFunction(()=>annoUI.folder?.id==='unassigned'&&annoUI.results?.total>0);
  assert.equal(await page.evaluate(()=>annoUI.results.cards.every(c=>c.series.length===1&&c.series[0].id==='unassigned')),true);
  await reset();
  // The local old translation finds the official Chinese folder, with its emblem and cover.
  await search('救祓少女');
  await page.locator('.anno-folder[data-anno-folder="set:172"]').waitFor();
  assert.match(await page.locator('.anno-folder[data-anno-folder="set:172"]').textContent(),/驱魔姐妹/);
  await page.locator('.anno-folder[data-anno-folder="set:172"]').click();
  await selectCard(42741437);
  assert.equal(await page.locator('[data-anno-mode="folders"]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('[data-anno-mode="cards"]').getAttribute('aria-pressed'),'false');
  assert.match(await page.locator('#anno-detail .anno-detail-series').textContent(),/驱魔姐妹/);
  assert.match(await page.locator('#anno-detail .anno-monster[data-kind="xyz"]').textContent(),/◎超量/);
  await page.waitForFunction(()=>document.querySelector('.anno-card-thumb').naturalWidth>0);
  assert.equal(await page.locator('#anno-art-popover').isVisible(),false);
  assert.equal(await page.locator('#anno-art-image').getAttribute('src'),null,'full original art is not loaded until requested');
  const detailHeight=(await page.locator('.anno-detail-body').boundingBox()).height;
  await page.locator('#anno-art-toggle').click();
  await page.waitForFunction(()=>document.querySelector('#anno-art-image').naturalWidth>0);
  assert.equal(await page.locator('#anno-art-popover').isVisible(),true);
  assert.notEqual(await page.locator('#anno-art-popover').evaluate(node=>getComputedStyle(node).backgroundColor),'rgba(0, 0, 0, 0)');
  const popup=await page.locator('#anno-art-popover').boundingBox();
  const trigger=await page.locator('#anno-art-toggle').boundingBox();
  assert.ok(popup.x>=0&&popup.y>=0&&popup.x+popup.width<=1280&&popup.y+popup.height<=900);
  assert.ok(Math.abs(popup.y-(trigger.y+trigger.height/2))<30,'popover opens at the click');
  assert.equal((await page.locator('.anno-detail-body').boundingBox()).height,detailHeight,'art does not expand the text layout');
  await page.screenshot({path:path.join(evidence,'annotations-art-popover.png'),preserveScroll:true});
  await page.locator('#anno-art-toggle').click();
  assert.equal(await page.locator('#anno-art-popover').isVisible(),false);
  await page.locator('#anno-art-toggle').click();
  await page.locator('#anno-q').click();
  assert.equal(await page.locator('#anno-art-popover').isVisible(),false,'outside click dismisses');
  await page.locator('#anno-art-toggle').focus();await page.locator('#anno-art-toggle').press('Enter');
  assert.equal(await page.locator('#anno-art-popover').isVisible(),true);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#anno-art-popover').isVisible(),false);
  const colours=await page.evaluate(()=>['resource','removal','disruption'].map(c=>getComputedStyle(document.querySelector(`#anno-tagpool [data-category="${c}"]`)).color));
  assert.equal(new Set(colours).size,3);
  await page.screenshot({path:path.join(evidence,'annotations-series-detail.png')});
  await page.locator('#anno-back').click();
  await page.waitForFunction(()=>annoUI.mode==='folders'&&document.querySelector('#anno-folders').offsetHeight>0);
  assert.equal(await page.locator('#anno-q').inputValue(),'救祓少女');
  await reset();
  // Batch two: a Japanese old alias still finds the newly curated official Chinese folder.
  await search('ブラックフェザー');
  await page.locator('.anno-folder[data-anno-folder="set:33"]').waitFor();
  assert.match(await page.locator('.anno-folder[data-anno-folder="set:33"]').textContent(),/黑羽/);
  assert.equal(await page.locator('.anno-folder[data-anno-folder="set:33"]').getAttribute('data-tone'),'steel');
  await page.locator('.anno-folder[data-anno-folder="set:33"]').click();
  await selectCard(2009101);
  assert.match(await page.locator('#anno-detail .anno-detail-series').textContent(),/黑羽/);
  assert.match(await page.locator('#anno-detail .anno-monster[data-kind="tuner"]').textContent(),/♪调整/);
  await page.locator('#anno-back').click();
  await page.waitForFunction(()=>annoUI.mode==='folders'&&!annoUI.busy);
  await reset();
  // Each extra-deck type, plus a hybrid synchro/tuner, is read from card type bits.
  for (const [code,kind] of [[23995346,'fusion'],[14812471,'link'],[69248256,'synchro'],[42781164,'tuner']]) {
    await selectCard(code);
    assert.equal(await page.locator(`#anno-detail .anno-monster[data-kind="${kind}"]`).count(),1);
    assert.equal(await page.locator('#anno-detail .anno-extra').count(),1);
    assert.equal(await page.locator('#anno-art-popover').isVisible(),false);
  }
  // Capability queries still separate source zones and effects after the sample set expands.
  const byGrave = await page.evaluate(() => api('/api/annotations', {op:'query',etags:['etag:add-hand'],from_zone:'grave'}));
  assert.ok(byGrave.total >= 2);
  // Results are paginated; specific examples need their own query as coverage grows.
  for (const [code, expected] of [[674561,1],[16509007,1],[213326,0]]) {
    const result=await page.evaluate(code=>api('/api/annotations',{
      op:'query',q:String(code),etags:['etag:add-hand'],from_zone:'grave'
    }),code);
    assert.equal(result.total,expected);
  }
  const strict=await page.evaluate(()=>api('/api/annotations',{op:'query',q:'16387555',etags:['etag:special-summon','etag:banish']}));
  assert.equal(strict.total,0);
  const loose=await page.evaluate(()=>api('/api/annotations',{op:'query',q:'16387555',etags:['etag:special-summon','etag:banish'],scope:'card'}));
  assert.equal(loose.total,1);assert.ok(loose.cards[0].cross_effects);
  for (const tag of ['etag:draw','etag:return-deck','etag:hand-look']) {
    const hit=await page.evaluate(tag=>api('/api/annotations',{op:'query',q:'25311006',etags:[tag]}),tag);
    assert.equal(hit.total,1);
  }
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'25311006',etags:['etag:add-hand']}))).total,0);
  for (const zone of ['field','monster','spell','field_spell','pendulum']) {
    const hit=await page.evaluate(zone=>api('/api/annotations',{op:'query',q:'86066372',action:'destroy',from_zone:zone}),zone);
    assert.equal(hit.total,1);
  }
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'86066372',action:'destroy',from_zone:'grave'}))).total,0);
  const maxx=await page.evaluate(()=>api('/api/annotations',{op:'card',code:23434538}));
  assert.equal(maxx.effects.find(e=>e.key==='m1').structure.activation.fast_effect,true);
  const shifter=await page.evaluate(()=>api('/api/annotations',{op:'card',code:91800273}));
  assert.match(shifter.effects[0].structure.cost[0].text,/必须实际送墓/);
  await search('');
  await page.locator('#anno-advanced > summary').click();
  await page.locator('[data-anno-etag="etag:add-hand"]').click();
  await page.locator('#anno-from').selectOption('grave');
  await page.locator('#anno-form button[type="submit"]').first().click();
  await page.waitForFunction(total=>annoUI.results?.total===total,byGrave.total);
  await search('674561');
  await page.waitForFunction(()=>annoUI.detail?.code===674561&&!annoUI.busy);
  assert.match(await page.locator('#anno-results').textContent(),/暗黑爆发/);
  assert.match(await page.locator('#anno-detail').textContent(),/来源区域：墓地/);
  assert.equal(await page.locator('#anno-advanced').getAttribute('open'),null);
  assert.match(await page.locator('#anno-filter-count').textContent(),/已选 2 项/);
  // Re-querying the same card must preserve other unsaved personal notes.
  await reset();
  await selectCard(16387555);
  assert.match(await page.locator('#anno-detail .anno-detail-series').textContent(),/杀手旋律/);
  assert.match(await page.locator('#anno-detail').textContent(),/脚本映射已核对/);
  await page.locator('#anno-edit-toggle').click();
  await page.locator('[data-anno-note-input="m2"]').fill('另一段尚未保存的备注');
  await page.locator('[data-anno-note-input="m1"]').fill('桌面验收备注：确认特召来源含卡组。');
  await page.locator('[data-anno-note="m1"]').click();
  await page.locator('#anno-detail',{hasText:'桌面验收备注：确认特召来源含卡组。'}).waitFor();
  await page.waitForFunction(()=>!annoUI.busy);
  assert.equal(await page.locator('[data-anno-note-input="m2"]').inputValue(),'另一段尚未保存的备注');
  if ((await page.evaluate(()=>api('/api/annotations',{op:'card',code:16387555}))).status!=='confirmed') {
    await page.locator('[data-anno-op="set-review"][data-value="confirmed"]').click();
    await page.waitForFunction(()=>annoUI.detail?.status==='confirmed'&&!annoUI.busy);
  }
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'card',code:16387555}))).status,'confirmed');
  const personal=JSON.parse(fs.readFileSync(path.join(root,'runtime','_trainer','card-annotations.json'),'utf8'));
  assert.equal(personal.version,2);
  assert.match(personal.cards['16387555'].text_digest,/^[a-f0-9]{64}$/);
  assert.ok(personal.cards['16387555'].frozen_text.includes('①'));
  const draft=await page.evaluate(()=>api('/api/annotations',{op:'draft',code:483}));
  assert.equal(draft.origin,'auto');
  await page.evaluate(revision=>api('/api/annotations',{op:'discard-draft',code:483,revision}),draft.revision);
  await page.locator('#anno-edit-toggle').click();
  await search('不存在的测试卡名');
  await page.waitForFunction(()=>annoUI.results?.total===0&&!annoUI.detail);
  assert.equal(await page.locator('#anno-detail .anno-effect').count(),0);
  await selectCard(89631139);
  assert.match(await page.locator('#anno-detail').textContent(),/通常怪兽 · 无效果文本/);
  await selectCard(483);
  assert.equal(await page.locator('[data-anno-op="draft"]').count(),0);
  await page.locator('#anno-edit-toggle').click();
  assert.equal(await page.locator('[data-anno-op="draft"]').isVisible(),true);
  await selectCard(14558127);
  await page.locator('[data-anno-card="14558127"]').focus();
  await page.locator('[data-anno-card="14558127"]').press('Enter');
  await page.locator('#anno-refresh').click();
  await page.waitForFunction(()=>annoUI.results?.total===1&&!annoUI.busy);
  assert.equal(await page.locator('#anno-q').inputValue(),'14558127');
  await application.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.setMinimumSize(760,650);w.setContentSize(760,900);});
  await page.waitForFunction(()=>innerWidth===760);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.locator('#anno-art-toggle').click();
  const narrowArt=await page.locator('#anno-art-popover').boundingBox();
  assert.ok(narrowArt.x>=0&&narrowArt.x+narrowArt.width<=760&&narrowArt.y+narrowArt.height<=900);
  await page.locator('#anno-art-close').click();
  await page.screenshot({path:path.join(evidence,'annotations-narrow-detail.png')});
  await reset();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:path.join(evidence,'annotations-narrow-folders.png')});
  await application.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.setMinimumSize(900,650);w.setContentSize(1280,900);});
  await page.waitForFunction(()=>innerWidth===1280);
  // Phase 3: common TAGs must find the actual reviewed cards, not only action queries.
  for (const [code,tag] of [[27762803,'etag:stat-change'],[41589166,'etag:protect'],
                           [64892035,'etag:lock'],[50823978,'etag:damage-modify']]) {
    const result=await page.evaluate(([code,tag])=>api('/api/annotations',{
      op:'query',q:String(code),etags:[tag]
    }),[code,tag]);
    assert.equal(result.total,1,`${code} common TAG remains searchable`);
  }
  for (const [code,quantity] of [[15609017,/动态固定：N个.*发动时确定/],
                               [58374719,/动态上限：1至N个.*发动时确定/],
                               [82542267,/对象：1至2个/]]) {
    await reset();
    await selectCard(code);
    await page.waitForFunction(()=>!annoUI.busy);
    assert.match(await page.locator('#anno-detail .anno-struct').allTextContents().then(lines=>lines.join(' ')),quantity);
    if(code===15609017) {
      await page.locator('#anno-detail .anno-more > summary').first().click();
      await page.screenshot({path:path.join(evidence,'annotations-dynamic-target.png')});
    }
  }
  assert.ok(fs.existsSync(path.join(root,'runtime','_trainer','card-annotations.json')));
  // Actual monster-batch data must distinguish a procedure, conversion, and trigger.
  const procedure=await page.evaluate(()=>api('/api/annotations',{op:'query',q:'82199284',action:'require_attack_return'}));
  assert.equal(procedure.total,1);
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'82199284',action:'return_hand'}))).total,0);
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'99690140',etags:['etag:effect-damage']}))).total,1);
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'99690140',action:'burn'}))).total,0);
  const esper=await page.evaluate(()=>api('/api/annotations',{op:'card',code:91663373}));
  assert.equal(esper.effects[0].effect_type,'trigger');
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'91663373',etags:['etag:hand-look']}))).total,1);
  const conflict=await page.evaluate(()=>api('/api/annotations',{op:'card',code:23421244}));
  assert.equal(conflict.status,'none');
  // Player requirements and delayed trap effects stay separate from direct actions.
  for (const [code,action,expected] of [[60530944,'require_player_send_grave',1],[60530944,'send_grave',0],
      [57006589,'replace_damage_with_recovery',1],[57006589,'heal',0],[67630339,'perform_battle_damage_calculation',1],
      [67630339,'burn',0],[65810489,'special_summon',1]]) {
    const result=await page.evaluate(([code,action])=>api('/api/annotations',{op:'query',q:String(code),action}),[code,action]);
    assert.equal(result.total,expected);
  }
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'95096437',action:'discard_hand',timing:'fast_window'}))).total,0);
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'query',q:'95096437',action:'discard_hand'}))).total,1);
  await reset();
  await selectCard(72453068);
  await page.waitForFunction(()=>!annoUI.busy);
  assert.match(await page.locator('#anno-detail .anno-struct').allTextContents().then(rows=>rows.join(' ')),/对方.*LP.*少1000/);
  assert.equal((await page.evaluate(()=>api('/api/annotations',{op:'card',code:63571750}))).status,'none');
  pass('Card annotations: Chinese series folders, aliases, covers, colours, collapsed filters/art, monster symbols, queries and personal corrections');
};
