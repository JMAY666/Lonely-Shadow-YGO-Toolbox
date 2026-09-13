const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

const source = readFileSync(path.join(__dirname, '../src/trainer/web/app.js'), 'utf8');
function setup() {
  const loading = { hidden: false, textContent: '正在准备训练场地……' };
  const context = vm.createContext({
    document: { querySelector: () => loading }, window: {},
    setTimeout: fn => { queueMicrotask(fn); return 1; },
  });
  vm.runInContext(source.slice(0, source.indexOf('function deckState()')) +
    '\nglobalThis.training = {app, waitNativeFrame};', context);
  context.training.app.active = {id: 'current'};
  return { ...context.training, context, loading };
}
const ready = {frame_ready: true, visible: true, owns_stage_hit_test: true, composition_compatible: true};

test('first frame alone cannot dismiss the loading message over an obscured field', async () => {
  const e = setup();
  const states = [
    {...ready, frame_ready: false}, {...ready, composition_compatible: false},
    {...ready, owns_stage_hit_test: false}, {...ready, visible: false}, ready,
  ];
  e.context.api = async () => {
    assert.equal(e.loading.hidden, false);
    return states.shift();
  };
  await e.waitNativeFrame('current');
  assert.equal(states.length, 0);
  assert.equal(e.loading.hidden, true);
});

test('persistent composition failure keeps a visible recovery message', async () => {
  const e = setup();
  e.context.api = async () => ({...ready, composition_compatible: false});
  await e.waitNativeFrame('current');
  assert.equal(e.loading.hidden, false);
  assert.match(e.loading.textContent, /未能显示.*重新启动/);
});

test('readiness response for an ended session cannot hide a new session loading message', async () => {
  const e = setup();
  e.context.api = async () => { e.app.active = {id: 'new'}; return ready; };
  await e.waitNativeFrame('current');
  assert.equal(e.loading.hidden, false);
  assert.equal(e.loading.textContent, '正在准备训练场地……');
});
