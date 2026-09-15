'use strict';
const assert = require('node:assert/strict');

// Check actual rendered surfaces throughout the existing desktop scenarios.
// Card artwork and exported SVG tutorial artwork have their own original palette.
module.exports = async function checkTheme(page) {
  const failures = await page.evaluate(() => {
    const bright = [];
    for (const node of document.querySelectorAll('body,main,section,article,aside,header,footer,dialog,div,input,textarea,select,button')) {
      const box = node.getBoundingClientRect(), style = getComputedStyle(node);
      if (box.width < 80 || box.height < 32 || box.bottom <= 0 || box.top >= innerHeight || box.right <= 0 || box.left >= innerWidth ||
          style.visibility === 'hidden' || !node.checkVisibility() || node.closest('#notice,.primary,#plan-tutorial-canvas')) continue;
      const rgb = style.backgroundColor.match(/[\d.]+/g)?.map(Number);
      if (!rgb || rgb.length > 3 && rgb[3] < .5) continue;
      if ((.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2])/255 > .67) bright.push({node:node.id || node.className || node.tagName,background:style.backgroundColor});
    }
    return bright;
  });
  assert.deepEqual(failures, [], 'Visible application surfaces use the shared dark palette');
};
