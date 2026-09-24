'use strict';
const assert = require('node:assert/strict');

module.exports = async ({page, application, root, evidence, pass}) => {
  const enter = async name => {
    await page.locator('#module-' + name).click();
    await page.waitForFunction(name => moduleUI.current === name && !moduleUI.switching, name);
  };
  await enter('cardanno');
  await page.locator('#anno-overview .anno-status').first().waitFor();
  assert.match(await page.locator('#anno-overview').textContent(), /卡库 14981 张/);
  assert.match(await page.locator('#anno-overview').textContent(), /已标注 11 张/);
  assert.match(await page.locator('#anno-overview').textContent(), /效果 TAG 18 个/);

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
  await page.waitForFunction(() => document.querySelector('#anno-results')?.textContent.includes('命中'), null, {timeout: 20000});
  await page.locator('[data-anno-etag="etag:add-hand"]').click();
  await page.locator('#anno-from').selectOption('grave');
  await page.locator('#anno-form button[type="submit"]').click();
  await page.waitForFunction(() => document.querySelector('#anno-results')?.textContent.includes('命中 2 张'), null, {timeout: 20000});
  const results = await page.locator('#anno-results').textContent();
  assert.match(results, /暗黑爆发/);
  assert.match(results, /来源区域：grave/);
  assert.ok(!results.includes('E-紧急呼唤'));
  assert.match(results, /未标注卡片不代表没有该能力/);

  // Detail shows per-effect structure, engine link, relations and notes.
  await page.locator('#anno-reset').click();
  await page.waitForFunction(() => [...document.querySelectorAll('.anno-card h3')].some(node => node.textContent.includes('提示员')), null, {timeout: 20000});
  await page.locator('[data-anno-card="16387555"]').click();
  await page.locator('#anno-detail .anno-effect').first().waitFor();
  const detail = await page.locator('#anno-detail').textContent();
  assert.match(detail, /杀手级调整曲·提示员/);
  assert.match(detail, /引擎已验证/);
  assert.match(detail, /次数限制组/);
  assert.match(detail, /这个回合，自己不是调整不能特殊召唤/);

  // Personal corrections: effect note + review state persist through revision locks.
  await page.locator('[data-anno-note-input="m1"]').fill('桌面验收备注：确认特召来源含卡组。');
  await page.locator('[data-anno-note="m1"]').click();
  await page.locator('#anno-detail', {hasText: '桌面验收备注：确认特召来源含卡组。'}).waitFor();
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
  const fs = require('node:fs'), path = require('node:path');
  assert.ok(fs.existsSync(path.join(root, 'runtime', '_trainer', 'card-annotations.json')), 'personal layer saved under user data');
  pass('Card annotations: evidence queries keep same-tag differences, never cross effects, engine links and personal corrections persist');
};
