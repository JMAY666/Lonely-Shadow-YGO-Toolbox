'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

module.exports = async function ({application,page,pass,evidence}) {
  if (process.platform !== 'win32') return;
  const windowState = await application.evaluate(({BrowserWindow}) => {
    const window = BrowserWindow.getAllWindows().find(window => !window.getParentWindow());
    return {bounds:window.getBounds(), content:window.getContentBounds(),
      resizable:window.isResizable(), minimizable:window.isMinimizable(),
      maximizable:window.isMaximizable(), closable:window.isClosable(), visible:window.isVisible()};
  });
  assert(windowState.content.y - windowState.bounds.y < 10, 'No separate native title row above the header');
  assert(windowState.resizable && windowState.minimizable && windowState.maximizable && windowState.closable);
  assert.equal(windowState.visible,false,'Title bar checks keep the isolated app hidden');
  const layouts = [];
  for (const [width,height,zoom] of [[900,650,1],[1280,900,1],[1600,1000,1],[1100,800,1.25]]) {
    await application.evaluate(({BrowserWindow},{width,height,zoom}) => {
      const window = BrowserWindow.getAllWindows().find(window => !window.getParentWindow());
      window.setContentSize(width,height);
      window.webContents.setZoomFactor(zoom);
    },{width,height,zoom});
    await page.waitForFunction(({width,zoom}) => Math.abs(innerWidth - width / zoom) <= 1 && navigator.windowControlsOverlay?.visible,{width,zoom});
    // Wait for the native control rectangle to follow the latest resize/zoom.
    await page.waitForFunction(() => {
      const area = navigator.windowControlsOverlay.getTitlebarAreaRect();
      return area.width > innerWidth - 200 && area.right < innerWidth && area.height > 0;
    });
    const layout = await page.evaluate(() => {
      const header = document.querySelector('.app-bar');
      const area = navigator.windowControlsOverlay.getTitlebarAreaRect();
      const brand = header.querySelector('.brand');
      const local = header.querySelector('.local');
      return {viewport:innerWidth, area:area.toJSON(), header:header.getBoundingClientRect().toJSON(),
        brand:brand.getBoundingClientRect().toJSON(), text:brand.textContent.trim(),
        textFits:brand.querySelector('span').scrollWidth <= brand.querySelector('span').clientWidth,
        local:getComputedStyle(local).display === 'none' ? null : local.getBoundingClientRect().toJSON(),
        drag:getComputedStyle(header).webkitAppRegion, overflow:document.documentElement.scrollWidth > innerWidth};
    });
    assert.equal(layout.text,require('./branding.cjs').name);
    assert.equal(layout.drag,'drag');
    assert.equal(layout.header.top,0);
    assert(Math.abs(layout.header.height - layout.area.height) < 1,'Header and native buttons share one row');
    assert(layout.brand.right < layout.area.right && layout.brand.bottom <= layout.header.bottom);
    assert(layout.textFits,'The full product name fits at supported desktop widths');
    if(layout.local)assert(layout.local.right < layout.area.right,'Resource status stays clear of window buttons');
    assert.equal(layout.overflow,false);
    layouts.push({width,height,zoom,...layout});
    await page.screenshot({path:path.join(evidence,`titlebar-${width}-${zoom}.png`)});
  }
  // A long page must keep the merged title/drag area under the native controls.
  await page.evaluate(() => {
    const spacer = document.createElement('div');spacer.id = 'titlebar-scroll-probe';spacer.style.height = '2000px';
    document.body.append(spacer);window.scrollTo(0,400);
  });
  assert.equal((await page.locator('.app-bar').boundingBox()).y,0);
  await page.evaluate(() => {document.querySelector('#titlebar-scroll-probe').remove();window.scrollTo(0,0);});
  await application.evaluate(({BrowserWindow}) => {
    const window = BrowserWindow.getAllWindows().find(window => !window.getParentWindow());
    window.webContents.setZoomFactor(1);window.setContentSize(1280,900);
  });
  await page.waitForFunction(() => innerWidth === 1280 && innerHeight === 900);
  fs.writeFileSync(path.join(evidence,'titlebar-result.json'),JSON.stringify({windowState,layouts},null,2));
  pass('Single integrated desktop title row; native controls, safe text/status bounds, 900/1280/1600 widths, 125% zoom and scrolling');
};
