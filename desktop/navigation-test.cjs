'use strict';
// Exercise the same category and workspace buttons used by a person.
module.exports = async (page, name) => {
  const group = ['decks','expansion','modular'].includes(name) ? 'training'
    : ['cardanno','intelligence','tags'].includes(name) ? 'library' : null;
  if (group && !await page.locator(`#module-${name}`).isVisible()) {
    if (!await page.locator('#primary-navigation').isVisible()) await page.locator('#navigation-toggle').click();
    await page.locator(`#nav-group-${group}`).click();
    await page.waitForFunction(() => !moduleUI.switching);
  }
  await page.locator(`#module-${name}`).click();
  await page.waitForFunction(name => moduleUI.current === name && !moduleUI.switching, name);
};
