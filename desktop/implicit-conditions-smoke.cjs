'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
module.exports=async({page,root,evidence,pass})=>{
  const proof=JSON.parse(fs.readFileSync(path.join(evidence,'implicit-engine-results.json'),'utf8'));
  const target=path.join(root,'runtime/_trainer/plans',proof.plan+'.json'),before=fs.readFileSync(target);
  const checks=await page.evaluate(async id=>{
    const plan=await api('/api/plan/'+id);
    await switchModule('expansion');await showPlan(id);
    const detail=summaryHtml(plan.requirements,plan);
    const preview=await api('/api/plans/preview',{id,name:plan.name,notes:plan.expansion.notes,annotations:plan.annotations});
    const confirm=summaryHtml(preview.requirements,plan);
    const diagram=renderPlanTutorialSvg(buildPlanTutorial(plan));
    return {detail,confirm,diagram,conditions:plan.requirements.implicit.conditions,preview:preview.requirements.implicit.conditions};
  },proof.plan);
  assert.deepEqual(checks.conditions,checks.preview);
  for(const html of [checks.detail,checks.confirm]){
    assert(html.indexOf('起手条件')<html.indexOf('隐性条件'));assert(html.indexOf('隐性条件')<html.indexOf('展开使用资源'));
    assert.match(html,/定向送墓/);assert.match(html,/检索/);assert.match(html,/不要求开局已有/);assert.match(html,/操作选择及区域变化依据/);
  }
  assert.doesNotMatch(checks.diagram,/隐性条件/);assert.match(checks.diagram,/检索/);assert.match(checks.diagram,/送墓/);
  assert(fs.readFileSync(target).equals(before));
  await page.locator('.implicit-conditions').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(evidence,'implicit-conditions.png'),preserveScroll:true});
  pass('Save confirmation and reopened details share evidence; SVG retains search and mill operations without a condition section');
};
