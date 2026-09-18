'use strict';
const assert=require('node:assert/strict'),path=require('node:path');

module.exports=async({page,application,evidence,pass})=>{
  await page.evaluate(async()=>{
    await switchModule('duel');await startNewDuel();
    const s=duelState();s.mode='BO1';s.operationMode='automatic';s.functionPage='platform';s.stage=s.reached=duelStages.function;renderDuel();
  });
  for(const width of [900,1280,1600]){
    await application.evaluate(({BrowserWindow},width)=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(width,900),width);
    await page.waitForFunction(width=>innerWidth===width,width);
    const frames=await page.locator('.duel-platform').evaluateAll(buttons=>buttons.map(button=>{
      const box=button.getBoundingClientRect();return {x:box.x,y:box.y,width:box.width,height:box.height,background:getComputedStyle(button).backgroundImage};
    }));
    assert.equal(frames.length,4);
    for(const [index,slug] of ['ygopro','ygopro2','mdpro3','masterduel'].entries()){
      assert.match(frames[index].background,new RegExp('/brand/duel-'+slug+'\\.svg'));
      assert(frames[index].x>=0&&frames[index].x+frames[index].width<=width);
      assert(Math.abs(frames[index].width-frames[index].height)<2);
      const art=await page.evaluate(async slug=>{
        const response=await fetch('/brand/duel-'+slug+'.svg');const text=await response.text();
        const image=new Image();image.src='data:image/svg+xml;base64,'+btoa(text);await image.decode();
        return {ok:response.ok,embedded:text.includes('data:image/png;base64,'),size:[image.naturalWidth,image.naturalHeight]};
      },slug);
      assert(art.ok&&art.embedded);assert.deepEqual(art.size,[600,600]);
    }
    assert(frames.every(frame=>Math.abs(frame.width-frames[0].width)<2));
    if(width>=1280)assert(frames.every(frame=>Math.abs(frame.y-frames[0].y)<2),'Four platforms fit on one row at desktop widths');
    await page.screenshot({path:path.join(evidence,`platform-branding-${width}.png`)});
  }
  await application.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).setContentSize(1280,900));
  await page.evaluate(()=>startNewDuel());
  pass('Platform branding: original client emblems load offline, correct per-platform background overrides, matched square geometry at 900/1280/1600 widths');
};
