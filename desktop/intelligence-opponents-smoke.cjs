'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
module.exports=async({page,application,root,evidence,pass})=>{
 page.setDefaultTimeout(30000);
 const tagFile=path.join(root,'runtime','_trainer','tag-library.json');
 const beforeTags=fs.existsSync(tagFile)?fs.readFileSync(tagFile):null;
 const before=await page.evaluate(async()=>({intel:await api('/api/intelligence'),decks:await api('/api/decks')}));
 await page.locator('#module-intelligence').click();
 await page.waitForFunction(()=>moduleUI.current==='intelligence'&&!moduleUI.switching);
 await page.locator('[data-intel-tab="opponents"]').click();
 await page.waitForFunction(()=>!intelOpponentUI.busy&&!!intelOpponentUI.data);
 assert.equal(await page.locator('#intel-actions button').count(),0);
 assert.equal(await page.locator('#intel-editor [data-intel-field],#intel-editor textarea,#intel-editor [contenteditable]').count(),0);
 const data=await page.evaluate(()=>intelOpponentUI.data);
 assert(data.readonly);assert(data.decks.length>=2);assert(data.decks.every(d=>d.routes.length>=2));
 assert.equal(await page.locator('.opponent-list-item').count(),data.decks.length);
 assert.deepEqual(await page.locator('.opponent-list-item').evaluateAll(rows=>rows.map(row=>row.dataset.opponentSelect)),data.decks.map(d=>d.id));
 for(let i=1;i<data.periods.length;i++)assert(data.periods[i-1].end>=data.periods[i].end);
 for(const p of data.periods){
   const rows=data.decks.filter(d=>d.period_id===p.id);
   for(let i=1;i<rows.length;i++)assert(rows[i-1].share>=rows[i].share);
   for(const d of rows)assert.equal(d.share,d.sample_count/d.sample_size);
 }
 const rejection=await page.evaluate(async()=>{try{await api('/api/intelligence/opponents',{op:'save',main:[]});return null;}catch(e){return e.message;}});
 assert.match(rejection,/仅供预览|不支持修改/);
 pass('Opponent catalog is a read-only preview with dates, source denominators and at least two structured routes per composition; POST mutation is rejected');
 for(const format of ['OCG','Master Duel']){
   await page.locator('[data-opponent-format="'+format+'"]').click();
   const ids=await page.locator('.opponent-list-item').evaluateAll(rows=>rows.map(row=>row.dataset.opponentSelect));
   assert(ids.length>0);assert(ids.every(id=>data.decks.find(d=>d.id===id).format===format));
   const p=data.periods.find(p=>p.format===format);
   await page.locator('#intel-opponent-period').selectOption(p.id);
   const selected=await page.locator('.opponent-list-item').evaluateAll(rows=>rows.map(row=>row.dataset.opponentSelect));
   assert(selected.every(id=>data.decks.find(d=>d.id===id).period_id===p.id));
 }
 await page.locator('[data-opponent-clear]').click();
 const sample=data.decks[0];
 await page.locator('#intel-opponent-tag').selectOption(sample.tag_ids[0]);
 await page.locator('#intel-opponent-q').fill(String(sample.main[0].code));
 assert(await page.locator('[data-opponent-select="'+sample.id+'"]').count()>0);
 await page.locator('[data-opponent-select="'+sample.id+'"]').click();
 assert.match(await page.locator('.opponent-sample').textContent(),new RegExp(sample.sample_count+' / '+sample.sample_size));
 for(const [i,zone] of ['main','extra','side'].entries()){
   const panel=page.locator('.opponent-deck-zone').nth(i);
   if(sample[zone]===null){assert.match(await panel.textContent(),/未披露/);continue;}
   const counts=await panel.locator('.opponent-card-quantity').allTextContents();
   assert.equal(counts.length,sample[zone].length);assert.equal(counts.reduce((a,t)=>a+Number(t.replace('×','')),0),sample.counts[zone]);
 }
 assert.equal(await page.locator('.opponent-route').count(),sample.routes.length);
 await page.locator('[data-opponent-route]').nth(1).click();
 assert(await page.locator('#intel-editor .intel-editor-body').evaluate(el=>el.scrollTop)>0);
 await page.locator('.opponent-deck-zone .review-card').first().click();
 await page.locator('#review-card-popover').waitFor({state:'visible'});
 await page.evaluate(()=>closeReviewDetail());
 pass('Format, source-period, TAG and card search compose correctly; preview quantities, unknown side decks, route jumps and card details retain source data');
 await application.evaluate(({shell})=>{globalThis.opponentExternal=[];globalThis.opponentOriginalExternal=shell.openExternal;shell.openExternal=async url=>{globalThis.opponentExternal.push(url);};});
 const link=page.locator('.intel-opponent-reader .opponent-source-links a').first(),url=await link.getAttribute('href');
 await link.click();assert.deepEqual(await application.evaluate(()=>globalThis.opponentExternal),[url]);
 await application.evaluate(({shell})=>{shell.openExternal=globalThis.opponentOriginalExternal;delete globalThis.opponentOriginalExternal;delete globalThis.opponentExternal;});
 await page.locator('[data-opponent-clear]').click();
 for(const [width,height] of [[1440,950],[900,700],[390,844]]){
   await application.evaluate(({BrowserWindow},s)=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.setMinimumSize(0,0);w.setContentSize(s.width,s.height);},{width,height});
   await page.waitForFunction(s=>innerWidth===s.width&&innerHeight===s.height,{width,height});
   const failures=await page.evaluate(()=>{
     const errors=[];if(document.documentElement.scrollWidth>innerWidth+1)errors.push('page overflow');
     for(const el of document.querySelectorAll('#intelligence button,#intelligence input,#intelligence select,.opponent-deck-grid,.opponent-route-steps>li')){
       if(!el.checkVisibility())continue;const r=el.getBoundingClientRect();if(r.left<0||r.right>innerWidth+1||r.width<1)errors.push(el.className||el.id);
     }
     return errors;
   });assert.deepEqual(failures,[]);
   await page.locator('.opponent-heading').scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(evidence,'opponents-overview-'+width+'.png'),preserveScroll:true});
   await page.locator('.opponent-route').first().scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(evidence,'opponents-route-'+width+'.png'),preserveScroll:true});
 }
 assert.deepEqual(await page.evaluate(async()=>({intel:await api('/api/intelligence'),decks:await api('/api/decks')})),before);
 assert.deepEqual(fs.existsSync(tagFile)?fs.readFileSync(tagFile):null,beforeTags);
 pass('Desktop reference dispatch and 1440/900/390px preview layouts pass; viewing, filtering and rejected writes leave all personal TAG and deck data unchanged');
 await application.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows().find(w=>!w.getParentWindow());w.setMinimumSize(0,0);w.setContentSize(1440,950);});
};
