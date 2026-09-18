'use strict';
function buildBranchedTutorial(plan,include=true) {
  const routes=[{id:'main',label:'主线',model:buildPlanTutorial(plan)}];
  for(const b of plan.branches||[]) {
    if(Array.isArray(include)&&!include.includes(b.id))continue;
    const route=b.report;
    if(!route)continue;
    // A compact log can hide a routine material cleanup. If the user selected
    // that exact boundary, retain its real action as a connector anchor instead
    // of silently drawing the arrow from a different visible action.
    const sourceNode=reviewNodes(plan).find(n=>n.id===b.source.node_id);
    const sourceAction=plan.actions?.find(a=>a.id===b.source.action_id);
    if(b.valid!==false&&sourceNode?.kind==='step'&&sourceAction) {
      const main=routes[0].model;
      let step=main.steps.find(s=>s.id===sourceNode.id);
      if(!step) {step={id:sourceNode.id,number:sourceNode.number,title:'分支起点',actions:[],notes:[]};main.steps.push(step);main.steps.sort((a,b)=>a.number-b.number);}
      if(!step.actions.some(a=>a.id===sourceAction.id)) {
        step.actions.push(tutorialAction(sourceAction,sourceNode,plan));
        step.actions.sort((a,b)=>sourceNode.action_ids.indexOf(a.id)-sourceNode.action_ids.indexOf(b.id));
      }
    }
    const model=buildPlanTutorial({...route,name:b.name});
    const suffix=new Set((route.actions||[]).filter(a=>(a.evidence_refs||[]).some(ref=>Number(String(ref).split(':')[0])>b.source.seq)).map(a=>a.id));
    model.steps=model.steps.filter(step=>step.actions.some(a=>suffix.has(a.id)));
    model.name=b.name+' · 妥协终场';
    model.branchFinal=true;
    // The branch starts at a response, so its actual inherited hand is context,
    // not a fresh five-card opening for a separate duel.
    model.conditionsNote='继承主线至 '+b.source.timing+'；从该时点独立记录。';
    const facts=observedBranchFacts(b).map(p=>({sources:p.source_cards,affected:p.affected_cards,text:p.result,label:p.confirmed?'实际结算':'实际事件（影响待核对）'}));
    if(!facts.length)facts.push({sources:[...new Set(b.conditions.hand)].map(code=>({code,name:plan.catalog?.[code]?.name||route.catalog?.[code]?.name||String(code)})),affected:b.source.cards||[],text:'尚未记录为实际阻抗',label:'预设条件'});
    routes.push({id:b.id,label:b.name,source:b.source,valid:b.valid!==false,model,facts});
  }
  routes[0].model.stepLinks=reviewStepLinks(plan,['initial',...routes[0].model.steps.map(s=>s.id),'final']);
  return {name:plan.name,routes};
}
function layoutBranchedTutorial(model) {
  let y=42;
  const routes=model.routes.map(route=>{
    const inner=layoutPlanTutorial(route.model),head=route.id==='main'?44:Math.max(150,(route.facts?.length||1)*110+62);
    const result={...route,x:32,y,head,width:inner.width,height:inner.height+head,inner};y+=result.height+54;return result;
  });
  const main=routes[0],connections=[];
  routes.slice(1).forEach((route,i)=>{
    const box=main.inner.boxes.find(b=>b.id===route.source.node_id),action=box?.actions.find(a=>a.id===route.source.action_id);
    if(!route.valid||(!box&&route.source.node_id!=='initial'))return;
    const rowBottom=box?Math.max(...main.inner.boxes.filter(b=>b.row===box.row).map(b=>b.y+b.height)):0;
    const x=main.x+(box?box.x+box.width:main.inner.pad+main.inner.openingWidth),sy=main.y+main.head+(box?box.y+(action?.y||24)+22:main.inner.overviewY+45);
    connections.push({route:route.id,checkpoint:route.source.checkpoint,node:route.source.node_id,action:route.source.action_id,x,y:sy,
      gapY:main.y+main.head+(box?rowBottom+16:main.inner.overviewY+main.inner.overviewHeight+16),
      gutter:main.x+main.width+34+i*28,endX:route.x+route.width-12,endY:route.y+28});
  });
  return {width:1550+28*(routes.length-1),height:y,routes,connections};
}
function renderBranchedTutorial(model,layout,assets={}) {
  const esc=tutorialEscape,out=[`<svg xmlns="http://www.w3.org/2000/svg" width="${layout.width}" height="${layout.height}" viewBox="0 0 ${layout.width} ${layout.height}" role="img" aria-label="${esc(model.name)} · 主线与妥协分支" font-family="Microsoft YaHei, sans-serif"><rect width="100%" height="100%" fill="#f3f7f2"/><defs><marker id="branch-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto"><path d="M1 1L9 5L1 9" fill="none" stroke="#a16b28" stroke-width="1.5"/></marker></defs>`];
  for(const route of layout.routes) {
    const color=route.id==='main'?'#2c745e':'#a16b28';
    out.push(`<g data-tutorial-route="${esc(route.id)}"><rect x="${route.x-12}" y="${route.y-10}" width="${route.width+24}" height="${route.height+22}" rx="12" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="10 7"/><text x="${route.x+20}" y="${route.y+25}" font-size="22" font-weight="700" fill="${color}">${esc(route.label)}</text>`);
    if(route.source) {
      out.push(`<text x="${route.x+350}" y="${route.y+25}" font-size="15" fill="#765633">${esc(route.source.timing)} · 原步骤 ${esc(route.source.node_id)} · 恢复节点 #${route.source.checkpoint}${!route.valid?' · 起点失效':''}</text>`);
      (route.facts||[]).forEach((fact,i)=>{
        const y=route.y+48+i*110;let x=route.x+20;
        const pics=cards=>{for(const c of cards.slice(0,6)){const src=`/pics/${Number(c.code)}.jpg`;out.push(`<image href="${esc(assets[src]||src)}" x="${x}" y="${y}" width="48" height="70"/><text x="${x+24}" y="${y+87}" text-anchor="middle" font-size="11" fill="#263c30">${esc(String(c.name||c.code).slice(0,8))}</text>`);x+=90;}};
        pics(fact.sources);out.push(`<text x="${x}" y="${y+40}" font-size="26" fill="${color}">→</text>`);x+=48;pics(fact.affected);
        out.push(`<text x="${x+16}" y="${y+27}" font-size="15" fill="${color}">${esc(fact.label)}</text><text x="${x+16}" y="${y+53}" font-size="16" fill="#263c30">${esc(fact.text)}</text>`);
      });
    }
    const inner=renderPlanTutorialSvg(route.model,route.inner,assets).replace('<svg ',`<svg x="${route.x}" y="${route.y+route.head}" `).replaceAll('tutorial-arrow',`tutorial-arrow-${route.id}`);
    out.push(inner,'</g>');
  }
  for(const c of layout.connections)out.push(`<g data-branch-connection="${esc(c.route)}" data-source-node="${esc(c.node)}" data-source-checkpoint="${c.checkpoint}"><circle cx="${c.x}" cy="${c.y}" r="5" fill="#a16b28"/><path d="M${c.x} ${c.y}H${c.x+9}V${c.gapY}H${c.gutter}V${c.endY}H${c.endX}" fill="none" stroke="#a16b28" stroke-width="2" marker-end="url(#branch-arrow)"/></g>`);
  out.push('</svg>');return out.join('');
}
function mountTutorialBranches(plan,include) {
  document.querySelector('#tutorial-branch-options')?.remove();
  if(!plan.branches?.length)return;
  const enabled=plan.branches.filter(b=>b.report),ids=include===true?enabled.map(b=>b.id):Array.isArray(include)?include:[];
  const box=document.createElement('div');box.id='tutorial-branch-options';box.className='tutorial-branch-options';
  box.innerHTML=`<label><input id="tutorial-include-branches" type="checkbox" ${include?'checked':''}>包含妥协场</label>${include?enabled.map(b=>`<label><input data-tutorial-branch="${escape(b.id)}" type="checkbox" ${ids.includes(b.id)?'checked':''}>${escape(b.name)}</label>`).join(''):''}`;
  $('#plan-tutorial-dialog').querySelector('header').after(box);
  $('#tutorial-include-branches').onchange=e=>openPlanTutorial(plan,e.target.checked);
  box.querySelectorAll('[data-tutorial-branch]').forEach(input=>input.onchange=()=>openPlanTutorial(plan,[...box.querySelectorAll('[data-tutorial-branch]:checked')].map(i=>i.dataset.tutorialBranch)));
}
