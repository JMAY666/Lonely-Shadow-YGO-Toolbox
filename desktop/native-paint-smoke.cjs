'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

module.exports=async({page,application,sid,nativeState,hostWait,evidence,pass})=>{
  const before=await hostWait(sid,s=>s.ready&&s.visible&&s.composition_compatible);
  assert.equal(before.parent_clips_children,true,'Parent painting must exclude the OpenGL child');
  const samples=[];
  const opacity=await page.locator('#training-title').evaluate(el=>el.style.opacity);
  try {
    for(let i=0;i<16;i++) {
      // Force Chromium frames while the native engine keeps presenting its own
      // field. Only this hidden acceptance window and its renderer are touched.
      await page.locator('#training-title').evaluate((el,i)=>el.style.opacity=i%2?'.9':'1',i);
      await application.evaluate(async({BrowserWindow})=>{
        await BrowserWindow.getAllWindows().find(w=>!w.getParentWindow()).webContents.capturePage(undefined,{stayHidden:true});
      });
      await nativeState(sid);
      const png=fs.readFileSync(path.join(evidence,'native-latest.png')).toString('base64');
      const {bitmap,...metrics}=await application.evaluate(({nativeImage},png)=>{
        const image=nativeImage.createFromBuffer(Buffer.from(png,'base64')),{width,height}=image.getSize();
        // Sample stationary sky/background, away from card hover, LP and other
        // legitimate game animations. This checks the rendered pixels, not FPS.
        const region={x:Math.floor(width*.38),y:Math.floor(height*.18),width:Math.floor(width*.5),height:Math.floor(height*.16)};
        const pixels=image.crop(region).toBitmap();
        let lit=0;for(let i=0;i<pixels.length;i+=4)if(Math.max(pixels[i],pixels[i+1],pixels[i+2])>32)lit++;
        return {width,height,region,lit:lit/(pixels.length/4),bitmap:pixels.toString('base64')};
      },png);
      const frame={...metrics,hash:crypto.createHash('sha256').update(Buffer.from(bitmap,'base64')).digest('hex')};
      const host=await hostWait(sid,s=>s.ready&&s.visible);
      assert.equal(host.parent_clips_children,true);
      assert.equal(host.composition_compatible,true);
      assert.deepEqual(host.bounds,before.bounds);
      assert(frame.lit>.9,'The engine background must remain drawn, not blank or black');
      if(samples.length)assert.equal(frame.hash,samples[0].hash,'Stationary game pixels must not jump while Chromium repaints');
      samples.push(frame);
    }
  } finally {
    await page.locator('#training-title').evaluate((el,opacity)=>el.style.opacity=opacity,opacity);
    fs.writeFileSync(path.join(evidence,'native-parent-paint.json'),JSON.stringify(samples,null,2));
  }
  await page.screenshot({path:path.join(evidence,'native-parent-paint-shell.png')});
  pass('Parent excludes the native field from painting; 16 engine-frame background samples stay identical during Chromium repaints');
};
