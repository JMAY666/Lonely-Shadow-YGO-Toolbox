'use strict';
const assert = require('node:assert/strict');

module.exports = async ({page, application, root, evidence, pass}) => {
  const enter = async name => {
    await require('./navigation-test.cjs')(page, name);
    await page.waitForFunction(name => moduleUI.current === name && !moduleUI.switching, name);
  };
  for (const name of ['tags', 'intelligence', 'modular']) await enter(name);
  await enter('cardanno');
  await page.locator('#anno-overview .anno-status').first().waitFor();
  assert.match(await page.locator('#anno-overview').textContent(), /卡库 14981 张/);
  assert.match(await page.locator('#anno-overview').textContent(), /已标注 11 张/);
  assert.match(await page.locator('#anno-overview').textContent(), /效果标签 20 个/);
  assert.equal(await page.locator('#anno-advanced').getAttribute('open'),null);
  assert.equal(await page.locator('[data-anno-note-input]').count(),0);
  assert.equal(await page.locator('#workspace-library').isVisible(),true);
  assert.match(await page.locator('#anno-overview').textContent(), /14,716/);
  await page.screenshot({path:require('node:path').join(evidence,'annotations-browse.png')});

  // Same tag, different source zones: the shared etag never merges the two cards.
  const byGrave = await page.evaluate(() => api('/api/annotations', {op: 'query', etags: ['etag:add-hand'], from_zone: 'grave'}));
  const graveCodes = byGrave.cards.map(card => card.code);
  assert.ok(graveCodes.includes(674561) && graveCodes.includes(16509007), 'grave-source hits include 暗黑爆发 and 混音手①');
  assert.ok(!graveCodes.includes(213326), 'deck-only searcher E-紧急呼唤 must not match a grave filter');
  // No sample card special-summons and banishes inside ONE effect, but 提示员
  // has one of each across m1/m2 — the pair must stay separated by default.
  const strict = await page.evaluate(() => api('/api/annotations', {op: 'query', etags: ['etag:special-summon', 'etag:banish'], etag_mode: 'all'}));
  assert.equal(strict.total, 0, 'conditions must not cross effects');
  const loose = await page.evaluate(() => api('/api/annotations', {op: 'query', etags: ['etag:special-summon', 'etag:banish'], etag_mode: 'all', scope: 'card'}));
  assert.equal(loose.total, 1);
  assert.equal(loose.cards[0].code, 16387555);
  assert.ok(loose.cards[0].cross_effects, 'card scope explains that different effects satisfied the conditions');

  // UI: chip + zone filter + submit produces the same evidence-backed list.
  await page.waitForFunction(() => document.querySelector('#anno-results')?.textContent.includes('找到'), null, {timeout: 20000});
  await page.locator('#anno-advanced > summary').click();
  await page.locator('[data-anno-etag="etag:add-hand"]').click();
  await page.locator('#anno-from').selectOption('grave');
  await page.locator('#anno-form button[type="submit"]').first().click();
  await page.waitForFunction(() => document.querySelector('#anno-results')?.textContent.includes('找到 2 张'), null, {timeout: 20000});
  const results = await page.locator('#anno-results').textContent();
  assert.match(results, /暗黑爆发/);
  assert.match(await page.locator('#anno-detail').textContent(), /来源区域：墓地/);
  assert.ok(!results.includes('E-紧急呼唤'));
  assert.match(await page.locator('#anno-overview').textContent(), /未标注 ≠ 没有能力/);

  // Detail shows per-effect structure, engine link, relations and notes.
  await page.locator('#anno-reset').click();
  await page.waitForFunction(() => !annoUI.busy && [...document.querySelectorAll('.anno-card-title')].some(node => node.textContent.includes('提示员')), null, {timeout: 20000});
  await page.locator('[data-anno-card="16387555"]').click();
  await page.waitForFunction(()=>annoUI.detail?.code===16387555);
  const detail = await page.locator('#anno-detail').textContent();
  assert.match(detail, /杀手级调整曲·提示员/);
  assert.match(detail, /脚本映射已核对/);
  assert.match(detail, /次数限制组/);
  assert.match(detail, /从效果处理后至本回合结束/);

  // Personal corrections: effect note + review state persist through revision locks.
  await page.locator('#anno-edit-toggle').click();
  await page.locator('[data-anno-note-input="m2"]').fill('另一段尚未保存的备注');
  await page.locator('[data-anno-note-input="m1"]').fill('桌面验收备注：确认特召来源含卡组。');
  await page.locator('[data-anno-note="m1"]').click();
  await page.locator('#anno-detail', {hasText: '桌面验收备注：确认特召来源含卡组。'}).waitFor();
  await page.waitForFunction(()=>!annoUI.busy);
  assert.equal(await page.locator('[data-anno-note-input="m2"]').inputValue(),'另一段尚未保存的备注');
  if ((await page.evaluate(() => api('/api/annotations', {op: 'card', code: 16387555}))).status !== 'confirmed') {
    await page.locator('[data-anno-op="set-review"][data-value="confirmed"]').click();
    await page.locator('#anno-detail .anno-badge.is-review', {hasText: '已确认'}).first().waitFor();
  }
  const personal = await page.evaluate(() => api('/api/annotations', {op: 'card', code: 16387555}));
  assert.equal(personal.status, 'confirmed');
  assert.match(JSON.stringify(personal.effects.find(effect => effect.key === 'm1').notes), /桌面验收备注/);

  // Auto drafts stay a separate, discardable status and never become reviewed.
  const draft = await page.evaluate(() => api('/api/annotations', {op: 'draft', code: 483}));
  assert.equal(draft.origin, 'auto');
  assert.equal((await page.evaluate(() => api('/api/annotations', {op: 'card', code: 483}))).status, 'auto');
  await page.evaluate(revision => api('/api/annotations', {op: 'discard-draft', code: 483, revision}), draft.revision);
  assert.equal((await page.evaluate(() => api('/api/annotations', {op: 'card', code: 483}))).status, 'none');
  // Empty queries remove stale selection; unannotated and no-effect cards are browseable.
  await page.locator('#anno-edit-toggle').click();
  await page.locator('#anno-q').fill('不存在的测试卡名');
  await page.locator('#anno-form button[type="submit"]').first().click();
  await page.waitForFunction(()=>annoUI.results?.total===0&&!annoUI.detail);
  assert.equal(await page.locator('#anno-detail .anno-effect').count(),0);
  await page.locator('#anno-q').fill('89631139');
  await page.locator('#anno-form button[type="submit"]').first().click();
  await page.waitForFunction(()=>annoUI.detail?.code===89631139);
  assert.match(await page.locator('#anno-detail').textContent(),/通常怪兽 · 无效果文本/);
  await page.locator('#anno-q').fill('483');
  await page.locator('#anno-catalog-scope').selectOption('all');
  await page.locator('#anno-form button[type="submit"]').first().click();
  await page.waitForFunction(()=>annoUI.detail?.code===483);
  assert.equal(await page.locator('[data-anno-op="draft"]').count(),0);
  await page.locator('#anno-edit-toggle').click();
  assert.equal(await page.locator('[data-anno-op="draft"]').isVisible(),true);
  await page.locator('#anno-reset').click();
  await page.waitForFunction(()=>annoUI.results?.total===11&&!annoUI.busy);
  // Keyboard selection and refresh preserve query state.
  await page.locator('[data-anno-card="14558127"]').focus();
  await page.locator('[data-anno-card="14558127"]').press('Enter');
  await page.waitForFunction(()=>annoUI.detail?.code===14558127);
  await page.locator('#anno-q').fill('14558127');
  await page.locator('#anno-refresh').click();
  await page.waitForFunction(()=>annoUI.results?.total===1&&!annoUI.busy);
  assert.equal(await page.locator('#anno-q').inputValue(),'14558127');
  await page.screenshot({path:require('node:path').join(evidence,'annotations-detail.png')});
  await application.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.setMinimumSize(760,650);w.setContentSize(760,900);});
  await page.waitForFunction(()=>innerWidth===760);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:require('node:path').join(evidence,'annotations-narrow.png')});
  await application.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.setMinimumSize(900,650);w.setContentSize(1280,900);});
  const fs = require('node:fs'), path = require('node:path');
  assert.ok(fs.existsSync(path.join(root, 'runtime', '_trainer', 'card-annotations.json')), 'personal layer saved under user data');
  pass('Card annotations: evidence queries keep same-tag differences, never cross effects, engine links and personal corrections persist');
};
