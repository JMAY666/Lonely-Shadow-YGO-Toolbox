'use strict';

async function cardNamesForCopy(codes, readCard) {
  if (!Array.isArray(codes) || !codes.length || codes.length > 90 || codes.some(code => !Number.isInteger(code) || code < 1 || code > 0xffffffff)) throw new Error('请选择有效卡牌后复制卡名');
  const cards = await Promise.all([...new Set(codes)].map(readCard));
  if (cards.some(card => typeof card?.name !== 'string' || !card.name.trim() || card.name.length > 512)) throw new Error('无法读取完整卡名');
  return [...new Set(cards.map(card => card.name))];
}
module.exports = {cardNamesForCopy};
