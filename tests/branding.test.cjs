const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const fs = require('node:fs');
const brand = require('../desktop/branding.cjs');
test('renaming keeps the legacy packaged/default development storage identities',()=>{
  assert.equal(brand.defaultDataDir({packaged:true,localAppData:'legacy-local',appData:'roaming'}),path.join('legacy-local','YGOTrainer'));
  assert.equal(brand.defaultDataDir({packaged:true,appData:'roaming'}),path.join('roaming','YGOTrainer'));
  assert.equal(brand.defaultDataDir({packaged:false,workspace:'workspace'}),path.join('workspace','.local','desktop-dev'));
  assert.equal(brand.appId,'local.ygotrainer.desktop');
});
test('ICO contains valid PNG frames for small taskbar/title icons and the packaged executable',()=>{
  const ico=fs.readFileSync(brand.icon), pngSignature=Buffer.from([137,80,78,71,13,10,26,10]);
  assert.equal(ico.readUInt16LE(2),1);
  const sizes=[];
  for(let i=0;i<ico.readUInt16LE(4);i++) {
    const position=6+i*16,size=ico[position]||256,length=ico.readUInt32LE(position+8),offset=ico.readUInt32LE(position+12);
    const png=ico.subarray(offset,offset+length);
    assert.equal(png.length,length);assert.deepEqual(png.subarray(0,8),pngSignature);
    assert.equal(png.readUInt32BE(16),size);assert.equal(png.readUInt32BE(20),size);sizes.push(size);
  }
  assert.deepEqual(sizes,[16,24,32,48,64,128,256]);
});
