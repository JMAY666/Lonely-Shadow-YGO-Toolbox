'use strict';

// Read-only projection of one frozen route. Never infer successful results from
// effect text, or borrow states / draft annotations from another open report.
const tutorialColors={ink:'#203d36',muted:'#61766e',accent:'#2c745e',note:'#b33737',warning:'#985423'};
function tutorialEscape(value) {
  return String(value??'').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g,'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&apos;');
}
function tutorialWrap(value,width,size=15) {
  const lines=[];
  for(const paragraph of String(value??'').split(/\r?\n/)) {
    let line='',used=0;
    for(const char of paragraph) {
      const advance=size*(/[\x20-\x7e]/.test(char)?0.6:1);
      if(line&&used+advance>width){lines.push(line);line='';used=0;}
      line+=char;used+=advance;
    }
    lines.push(line);
  }
  return lines;
}
function tutorialNote(value) {
  const chars=Array.from(String(value||'').trim());
  return chars.length>150?chars.slice(0,149).join('')+'…':chars.join('');
}
function tutorialCard(c,node,plan) {
  const known=reviewKnown(c)&&!reviewRandomDraw(c,node,plan);
  const fieldPosition=[0,1].includes(c.controller)&&[4,8].includes(c.location)&&Number.isInteger(c.sequence)&&reviewFieldSlots(c).some(s=>s.active)?
    {controller:c.controller,location:c.location,sequence:c.sequence}:null;
  return {name:reviewCardLabel(c,node,plan),src:known?`/pics/${Number(c.code)}.jpg`:'/review-back.svg',fieldPosition};
}
function tutorialPositionMap(position,x,y) {
  if(!position)return '';
  const color=position.controller===1?'#b75757':'#237caa',sx=30/55,sy=24/44;
  // Absolute SVG coordinates and explicit styling survive offline SVG and PNG
  // export, without depending on the application's HTML/CSS location icon.
  return `<g class="tutorial-location-map" role="img" aria-label="${tutorialEscape(reviewPlace(position))}" data-controller="${position.controller}" data-location="${position.location}" data-sequence="${position.sequence}"><title>${tutorialEscape(reviewPlace(position))}</title><rect x="${x}" y="${y}" width="30" height="24" fill="none"/>${reviewFieldSlots(position).map(s=>`<rect x="${x+s.x*sx}" y="${y+s.y*sy}" width="${8*sx}" height="${9*sy}" rx="0.5" fill="${s.active?color:'none'}" stroke="${color}" stroke-width="0.55"${s.active?' data-active-slot="true"':''}/>`).join('')}</g>`;
}
function tutorialFlowCards(cards,node,plan,locations=true) {
  return (cards||[]).map(c=>({...tutorialCard(c,node,plan),
    location:locations&&c.location&&![4,8].includes(c.location)?reviewPlace(c):c.controller===1?'对方':''}));
}
function tutorialOperationStages(item,node,plan,role='') {
  const event=(plan.events||[]).find(e=>e.id===(item.event_ref||item.id))||item;
  const cards=item.cards||event.cards||[];
  const dest=event.destination,origin=event.origin;
  const stage=(label,cs=cards,hint='',locations=true)=>({label:role?`${role} · ${label}`:label,role,cards:tutorialFlowCards(cs,node,plan,locations),hint});
  if(event.message===90)return [stage(`抽 ${cards.length} 张卡（随机）`,cards,'',false)];
  const method=cards.find(c=>c.summon_method)?.summon_method||({61:'通常召唤',63:'特殊召唤',65:'反转召唤',54:'盖放'}[event.message]);
  if(method) {
    const materials=cards.flatMap(c=>c.materials||[]);
    return [...(materials.length?[stage('素材',materials)]:[]),stage(method)];
  }
  if(event.message===50&&dest) {
    const deckOp={move_to_bottom:'放回卡组底部',move_to_top:'放回卡组顶部',reorder:'调整卡组顺序',position_refresh:'更新卡组位置'}[event.deck_operation];
    const operation=deckOp||(dest.location===16?(origin?.location===2&&(event.reason&0x4000)?'丢弃':'送墓'):dest.location===32?((dest.position&10)?'里侧除外':'除外'):dest.location&128?'成为素材':dest.location===2?(origin?.location===1?'检索':'回到手牌'):dest.location===1?'回到卡组':`移至${reviewPlace(dest)}`);
    const changedSide=origin?.controller!=null&&dest.controller!=null&&origin.controller!==dest.controller;
    const places=[origin&&![4,8].includes(origin.location)?reviewPlace(origin):'',
      changedSide||![4,8].includes(dest.location)?reviewPlace(dest):''].filter(Boolean);
    const result=stage(operation,cards,places.join(' → '),false);
    if(!cards.length)result.text='卡牌未记录';
    return [result];
  }
  let text=item.text||item.summary||event.result||eventSummary(event)||'操作未记录';
  for(const c of cards)if(c.name&&(!reviewKnown(c)||reviewRandomDraw(c,node,plan)))text=text.replaceAll(c.name,tutorialCard(c,node,plan).name);
  return [{...stage(({53:'改变表示',100:'支付 LP'}[event.message])||'处理结果'),text}];
}
function tutorialAction(action,node,plan) {
  const stages=[],notes=[],add=(text,color='ink')=>{if(text)notes.push({text,color});};
  if(action.kind==='effect') {
    const num=Number(action.effect_number),label=num>0?('①②③④⑤⑥⑦⑧⑨⑩'[num-1]||String(num)):'效果';
    stages.push({label:cardActivation(action,plan)||`发动${label}`,cards:tutorialFlowCards(action.cards,node,plan),text:action.cards?.length?'':'卡牌未记录'});
    for(const cost of action.costs||[])stages.push(...tutorialOperationStages(cost,node,plan,'Cost'));
    if(action.targets?.length)stages.push({label:'对象',cards:tutorialFlowCards(action.targets,node,plan)});
    for(const result of action.results||[])stages.push(...tutorialOperationStages(result,node,plan));
    if(action.status!=='resolved')add(({negated:'发动被无效',disabled:'效果被无效',pending:'已发动，尚未确认结算'}[action.status])||action.status_label||'结算状态未记录','warning');
    if(activationResultMissing(action,plan))add('处理结果未记录','warning');
    add(tutorialNote(plan.annotations?.effects?.[action.id]),'note');
  } else {
    stages.push(...tutorialOperationStages(action,node,plan,action.kind==='cost'?'Cost':''));
  }
  return {id:action.id,stages,notes};
}
function buildPlanTutorial(plan,includeBranches=false) {
  if(includeBranches && typeof buildBranchedTutorial==='function')return buildBranchedTutorial(plan,includeBranches);
  const nodes=plan.review?.nodes||reviewFallback(plan),edits=plan.annotations||{};
  const actions=new Map((plan.actions||[]).map(a=>[a.id,a]));
  const steps=[];
  for(const n of nodes.filter(n=>n.kind==='step')) {
    const active=(n.action_ids||[]).map(id=>actions.get(id)).filter(a=>a&&!compactCleanup(a,plan));
    const edit=edits.nodes?.[n.id]||{};
    if(!active.length&&!edit.name&&!edit.notes)continue;
    const notes=[];
    if(edit.notes?.trim())notes.push({text:tutorialNote(edit.notes),color:'note'});
    if(!active.length)notes.push({text:'本节点没有已记录操作',color:'muted'});
    steps.push({id:n.id,number:n.number,title:tutorialNote(edit.name||''),actions:active.map(a=>tutorialAction(a,n,plan)),notes});
  }
  let opening=plan.requirements?.opening;
  const openingKnown=Array.isArray(opening);
  if(!openingKnown) {
    const groups=new Map();
    for(const c of plan.initial_hand||[]) {
      const shown=tutorialCard(c,nodes.find(n=>n.kind==='initial'),plan),key=shown.src+shown.name;
      if(groups.has(key))groups.get(key).count++;
      else groups.set(key,{...shown,count:1});
    }
    opening=[...groups.values()];
  } else opening=opening.map(c=>({name:c.name||c.constraint||'待核对卡牌',count:c.count,src:c.code?`/pics/${Number(c.code)}.jpg`:'/review-back.svg',constraint:c.constraint&&c.constraint!==c.name?c.constraint:'',manual:c.status==='用户补充'}));
  const finalNode=nodes.find(n=>n.kind==='final')||{id:'final',kind:'final',state:plan.final_state};
  const finalState=finalNode.state||plan.final_state;
  const marked=(finalState?.cards||[]).filter(c=>edits.final_marks?.[String(c.instance_id)]?.marked).sort((a,b)=>a.controller-b.controller||a.location-b.location||a.sequence-b.sequence);
  const finalCards=marked.map(c=>{
    const mark=edits.final_marks[String(c.instance_id)],notes=[];
    if(edits.cards?.[String(c.instance_id)]?.trim())notes.push({text:tutorialNote(edits.cards[String(c.instance_id)]),color:'note'});
    for(const p of reviewEffectParts(plan.catalog?.[c.code]?.desc).filter(p=>mark.effects?.[p.key])) {
      notes.push({text:p.label+'效果',color:'ink'});
      if(mark.effects[p.key].note?.trim())notes.push({text:tutorialNote(mark.effects[p.key].note),color:'note'});
    }
    return {...tutorialCard(c,finalNode,plan),location:![4,8].includes(c.location)?reviewPlace(c):c.controller===1?'对方':'',notes};
  });
  const warnings=[];
  if(!openingKnown)warnings.push('旧方案未保存条件摘要，起手仅展示已记录手牌。');
  if(plan.requirements?.random?.length)warnings.push('随机依赖：'+plan.requirements.random.map(c=>`${c.name||c.constraint} ×${c.count}`).join('、'));
  if(plan.review?.complete===false)warnings.push('部分步骤快照缺失；流程按已记录动作展示。');
  warnings.push(...(plan.requirements?.warnings||[]));
  return {name:plan.name||plan.expansion?.name||'展开',opening,openingKnown,finalCards,steps,warnings,
    finalNote:tutorialNote(plan.requirements?.final?.notes||edits.nodes?.final?.notes),
    conditionsNote:tutorialNote(plan.requirements?.note||edits.conditions_note),note:tutorialNote(plan.expansion?.notes)};
}

function layoutTutorialStage(stage,maxWidth) {
  const labelWidth=Math.ceil(Array.from(stage.label).reduce((sum,c)=>sum+12*(/[\x20-\x7e]/.test(c)?.6:1),16));
  const width=Math.min(maxWidth,stage.cards.length?Math.max(84,Math.min(132,labelWidth),stage.cards.length*76+8):stage.text?.length>60?240:100);
  const labels=tutorialWrap(stage.label,width-12,12),columns=Math.max(1,Math.floor((width-8)/76));
  const cards=stage.cards.map(c=>({...c,mapHeight:c.fieldPosition?28:0,lines:tutorialWrap(c.name,70,11),places:c.location?tutorialWrap(c.location,70,10):[]}));
  let y=labels.length*17+12;
  for(let i=0;i<cards.length;i+=columns) {
    const row=cards.slice(i,i+columns),height=Math.max(...row.map(c=>72+c.mapHeight+c.lines.length*14+c.places.length*13));
    row.forEach((c,col)=>Object.assign(c,{x:(width-row.length*76+6)/2+col*76,y}));
    y+=height+6;
  }
  const lines=stage.text?tutorialWrap(stage.text,width-16,12):[],hints=stage.hint?tutorialWrap(stage.hint,width-12,10):[];
  const textY=y;y+=lines.length*17;
  const hintY=y;y+=hints.length*14;
  return {...stage,width,height:Math.max(48,y+8),labels,cards,lines,hints,textY,hintY};
}
function layoutTutorialAction(action,width) {
  const stages=action.stages.map(s=>layoutTutorialStage(s,width)),rows=[[]];
  let x=0,y=0;
  for(const stage of stages) {
    if(x&&x+stage.width>width){x=0;rows.push([]);}
    stage.x=x;x+=stage.width+14;rows.at(-1).push(stage);
  }
  for(const row of rows.filter(r=>r.length)) {
    const labelLines=Math.max(...row.map(s=>s.labels.length));
    for(const stage of row) {
      const extra=(labelLines-stage.labels.length)*17;
      stage.cards.forEach(c=>c.y+=extra);stage.textY+=extra;stage.hintY+=extra;stage.height+=extra;
    }
    const height=Math.max(...row.map(s=>s.height));
    row.forEach(s=>Object.assign(s,{y,height}));y+=height+24;
  }
  if(stages.length)y-=24;
  const notes=action.notes.flatMap(l=>tutorialWrap(l.text,width,14).map(text=>({...l,text})));
  const notesY=y+(notes.length?8:0);
  return {...action,stages,notes,notesY,height:notesY+notes.length*20};
}
function layoutPlanTutorial(model) {
  if(model.routes)return layoutBranchedTutorial(model);
  const width=1440,pad=32,gap=32,columns=model.steps.length>24?4:3;
  const nodeWidth=(width-pad*2-gap*(columns-1))/columns;
  const boxes=model.steps.map(s=>{
    const bodyWidth=nodeWidth-36;
    const title=s.title?tutorialWrap(s.title,nodeWidth-132,14):[];
    const header=Math.max(48,26+title.length*18);
    const actions=s.actions.map(a=>layoutTutorialAction(a,bodyWidth));
    let y=header;
    actions.forEach(a=>{a.y=y;y+=a.height+16;});
    const notes=s.notes.flatMap(l=>tutorialWrap(l.text,bodyWidth,14).map(text=>({...l,text})));
    return {...s,actions,notes,notesY:y,title,header,width:nodeWidth,height:Math.max(140,y+notes.length*20+18)};
  });
  const openingColumns=model.opening.length>3?2:1,openingWidth=openingColumns===2?570:370;
  const finalWidth=width-pad*2-openingWidth-24,finalColumns=finalWidth>900&&model.finalCards.length>=4?4:3;
  const cardWidth=(finalWidth-40-24*(finalColumns-1))/finalColumns;
  const finalCards=model.finalCards.map(c=>{
    const lines=[...tutorialWrap(c.name,cardWidth-82,15).map(text=>({text,color:'ink'})),
      ...(c.location?tutorialWrap(c.location,cardWidth-82,12).map(text=>({text,color:'muted'})):[])];
    const notes=c.notes.flatMap(l=>tutorialWrap(l.text,cardWidth-16,14).map(text=>({...l,text})));
    const headHeight=Math.max(c.fieldPosition?108:82,lines.length*20+8);
    return {...c,lines,notes,headHeight,width:cardWidth,height:headHeight+notes.length*20+12};
  });
  let finalHeight=58;
  for(let i=0;i<finalCards.length;i+=finalColumns) {
    const row=finalCards.slice(i,i+finalColumns),height=Math.max(...row.map(c=>c.height));
    row.forEach((c,col)=>Object.assign(c,{x:pad+openingWidth+24+20+col*(cardWidth+24),y:finalHeight}));
    finalHeight+=height+12;
  }
  if(!finalCards.length)finalHeight+=60;
  const finalNotes=tutorialWrap(model.finalNote,finalWidth-40,14);
  if(model.finalNote)finalHeight+=finalNotes.length*20+12;
  const openingCardWidth=(openingWidth-40-16*(openingColumns-1))/openingColumns;
  const openingRows=model.opening.map(c=>{
    const lines=tutorialWrap(`${c.name} ×${c.count}${c.manual?'（补充）':''}`,openingCardWidth-68,15);
    const conditions=c.constraint?tutorialWrap(c.constraint,openingCardWidth-68,13):[];
    return {...c,lines,conditions,height:Math.max(80,(lines.length+conditions.length)*21+16)};
  });
  let openingBottom=58;
  for(let i=0;i<openingRows.length;i+=openingColumns) {
    const row=openingRows.slice(i,i+openingColumns),height=Math.max(...row.map(c=>c.height));
    row.forEach((c,col)=>Object.assign(c,{x:pad+20+col*(openingCardWidth+16),y:openingBottom}));
    openingBottom+=height;
  }
  const conditionLines=model.conditionsNote?tutorialWrap(model.conditionsNote,openingWidth-40,14):[];
  const openingNoteY=openingBottom+(!openingRows.length?44:0);
  const openingHeight=openingNoteY+conditionLines.length*20+18;
  const overviewY=100,overviewHeight=Math.max(180,openingHeight,finalHeight+10);
  let y=overviewY+overviewHeight+72;
  for(let i=0;i<boxes.length;i+=columns) {
    const rowIndex=Math.floor(i/columns),row=boxes.slice(i,i+columns),height=Math.max(...row.map(b=>b.height));
    row.forEach((b,col)=>Object.assign(b,{x:pad+(rowIndex%2?columns-1-col:col)*(nodeWidth+gap),y,height}));
    y+=height+gap;
  }
  if(!boxes.length)y+=65;
  const footer=[...model.warnings.map(text=>({text,color:'warning'})),...(model.note?[{text:model.note,color:'note'}]:[])].flatMap(l=>tutorialWrap(l.text,width-pad*2,14).map(text=>({...l,text})));
  return {width,height:y+footer.length*20+60,pad,gap,columns,boxes,openingWidth,openingNoteY,finalWidth,openingRows,finalCards,finalNotes,conditionLines,overviewY,overviewHeight,footerY:y,footer};
}
function renderPlanTutorialSvg(model,layout=layoutPlanTutorial(model),assets={}) {
  if(model.routes)return renderBranchedTutorial(model,layout,assets);
  const out=[],esc=tutorialEscape;
  const rect=(x,y,w,h,fill,stroke='#d9e5df',radius=12)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}"/>`;
  const text=(value,x,y,size=15,color='ink',weight=400,anchor='start')=>`<text x="${x}" y="${y}" text-anchor="${anchor}" font-size="${size}" font-weight="${weight}" fill="${tutorialColors[color]||color}">${esc(value)}</text>`;
  const picture=(src,x,y,w=48,h=70)=>`<image href="${esc(assets[src]||src)}" x="${x}" y="${y}" width="${w}" height="${h}" preserveAspectRatio="xMidYMid meet"/>`;
  const {width,height,pad,overviewY,overviewHeight,openingWidth,finalWidth}=layout;
  out.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(model.name)} · 展开一图流" font-family="Microsoft YaHei, Noto Sans CJK SC, sans-serif"><title>${esc(model.name)} · 展开一图流</title><defs><marker id="tutorial-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 1 1 L 9 5 L 1 9" fill="none" stroke="#2c745e" stroke-width="1.7"/></marker></defs>`);
  out.push(rect(0,0,width,height,'#f3f7f2','#f3f7f2',0),rect(pad,26,6,42,'#2c745e','#2c745e',3),text('展开',pad+22,58,30,'ink',700));
  const title=tutorialWrap(model.name,width-260,22);
  out.push(text(title[0]+(title.length>1?'…':''),pad+110,57,22,'accent',600),text(`${model.steps.length} 个步骤 · 顺箭头阅读`,width-245,83,13,'muted'));
  out.push(rect(pad,overviewY,openingWidth,overviewHeight,'#fff'),rect(pad+openingWidth+24,overviewY,finalWidth,overviewHeight,'#fff'));
  out.push(text('起手条件',pad+20,overviewY+34,19,'ink',700),text('终场展示',pad+openingWidth+44,overviewY+34,19,'ink',700));
  for(const c of layout.openingRows) {
    const y=overviewY+c.y;
    out.push(picture(c.src,c.x,y,45,65));
    c.lines.forEach((l,i)=>out.push(text(l,c.x+62,y+18+i*21,15,'ink',600)));
    c.conditions.forEach((l,i)=>out.push(text(l,c.x+62,y+18+(c.lines.length+i)*21,13,'muted')));
  }
  if(!layout.openingRows.length)out.push(text(model.openingKnown?'未识别到指定起手，请核对方案':'起手未记录',pad+20,overviewY+78,14,'muted'));
  layout.conditionLines.forEach((l,i)=>out.push(text(l,pad+20,overviewY+layout.openingNoteY+16+i*20,14,'note')));
  for(const c of layout.finalCards) {
    const y=overviewY+c.y;
    out.push(picture(c.src,c.x,y,50,73));
    out.push(tutorialPositionMap(c.fieldPosition,c.x+10,y+78));
    c.lines.forEach((l,i)=>out.push(text(l.text,c.x+64,y+16+i*20,i===0?15:14,l.color,i===0?600:400)));
    c.notes.forEach((l,i)=>out.push(text(l.text,c.x,y+c.headHeight+16+i*20,14,l.color,l.color==='note'?600:400)));
  }
  if(!layout.finalCards.length)out.push(text('未标记终场卡牌；可在终场步骤中勾选。',pad+openingWidth+44,overviewY+83,15,'muted'));
  if(model.finalNote)layout.finalNotes.forEach((l,i)=>out.push(text(l,pad+openingWidth+44,overviewY+overviewHeight-20-(layout.finalNotes.length-1-i)*20,14,'note')));
  out.push(text('展开流程',pad,overviewY+overviewHeight+44,21,'ink',700),text('卡图 + 关键词 · 按 Step 序号依次展开',pad+116,overviewY+overviewHeight+43,14,'muted'));
  // Each row reverses direction. Row turns travel outside the boxes so that
  // arrows cannot cross text, including an incomplete final row.
  layout.boxes.forEach((box,i)=>{
    if(i===layout.boxes.length-1)return;
    const next=layout.boxes[i+1],right=Math.floor(i/layout.columns)%2===0;
    const fromX=right?box.x+box.width:box.x,fromY=box.y+box.height/2;
    const toX=right?next.x:next.x+next.width,toY=next.y+next.height/2;
    let d=`M ${fromX} ${fromY} L ${toX- (right?4:-4)} ${toY}`;
    if(next.y!==box.y) {
      const turnX=fromX+(right?19:-19),endX=right?next.x+next.width:next.x;
      d=`M ${fromX} ${fromY} H ${turnX} V ${toY} H ${endX+(right?4:-4)}`;
    }
    out.push(`<path class="tutorial-connector" d="${d}" fill="none" stroke="#2c745e" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#tutorial-arrow)"/>`);
  });
  for(const box of layout.boxes) {
    out.push(`<g class="tutorial-step" data-tutorial-node="${esc(box.id)}" role="button" tabindex="0" aria-label="Step ${box.number}，查看原步骤"><title>Step ${box.number} · 查看原步骤与完整说明</title>`,rect(box.x,box.y,box.width,box.height,'#fff'));
    out.push(rect(box.x+16,box.y+14,76,25,'#e8f1e9','#e8f1e9',7),text(`Step ${box.number}`,box.x+27,box.y+32,13,'accent',700));
    box.title.forEach((l,i)=>out.push(text(l,box.x+105,box.y+32+i*18,14,'ink',600)));
    for(const [index,action] of box.actions.entries()) {
      const ax=box.x+18,ay=box.y+action.y;
      out.push(`<g class="tutorial-action" data-tutorial-action="${esc(action.id)}">`);
      if(index)out.push(`<path d="M ${ax} ${ay-8} H ${box.x+box.width-18}" stroke="#e3ebe5"/>`);
      action.stages.forEach((s,i)=>{
        const next=action.stages[i+1];if(!next)return;
        const d=s.y===next.y?`M ${ax+s.x+s.width+2} ${ay+s.y+s.height/2} L ${ax+next.x-3} ${ay+next.y+next.height/2}`:
          `M ${ax+s.x+s.width/2} ${ay+s.y+s.height+2} V ${ay+next.y-12} H ${ax+next.x+next.width/2} V ${ay+next.y-3}`;
        out.push(`<path class="tutorial-flow-arrow" d="${d}" fill="none" stroke="#2c745e" stroke-width="1.3" marker-end="url(#tutorial-arrow)"/>`);
      });
      for(const stage of action.stages) {
        const x=ax+stage.x,y=ay+stage.y;
        out.push(`<g class="tutorial-stage" data-tutorial-role="${esc(stage.label)}">`,rect(x,y,stage.width,stage.height,stage.role==='Cost'?'#fff6e9':'#f4f8f5','#e3ebe5',7));
        stage.labels.forEach((l,i)=>out.push(text(l,x+stage.width/2,y+18+i*17,12,stage.role==='Cost'?'warning':'accent',600,'middle')));
        stage.cards.forEach((c,i)=>{
          const cx=x+c.x,cy=y+c.y;
          out.push(`<g class="tutorial-flow-card"><title>${esc(c.name+(c.location?' · '+c.location:''))}</title>`,picture(c.src,cx+12.5,cy,45,65));
          out.push(tutorialPositionMap(c.fieldPosition,cx+20,cy+68));
          c.lines.forEach((l,i)=>out.push(text(l,cx+35,cy+78+c.mapHeight+i*14,11,'ink',400,'middle')));
          c.places.forEach((l,i)=>out.push(text(l,cx+35,cy+78+c.mapHeight+c.lines.length*14+i*13,10,'muted',400,'middle')));
          out.push('</g>');
          if(stage.cards[i+1]?.y===c.y)out.push(text('+',cx+73,cy+35,11,'muted',600,'middle'));
        });
        stage.lines.forEach((l,i)=>out.push(text(l,x+stage.width/2,y+stage.textY+13+i*17,12,'ink',400,'middle')));
        stage.hints.forEach((l,i)=>out.push(text(l,x+stage.width/2,y+stage.hintY+12+i*14,10,'muted',400,'middle')));
        out.push('</g>');
      }
      action.notes.forEach((l,i)=>out.push(text(l.text,ax,ay+action.notesY+14+i*20,14,l.color,l.color==='note'?600:400)));
      out.push('</g>');
    }
    box.notes.forEach((l,i)=>out.push(text(l.text,box.x+18,box.y+box.notesY+14+i*20,14,l.color,l.color==='note'?600:400)));
    out.push('</g>');
  }
  if(!layout.boxes.length)out.push(text('本方案没有可展示的展开动作。',pad,overviewY+overviewHeight+105,16,'muted'));
  layout.footer.forEach((l,i)=>out.push(text(l.text,pad,layout.footerY+12+i*20,14,l.color)));
  out.push(text('依据已保存路线生成 · 位置图：蓝色为我方，红色为对方 · 卡牌效果全文与完整备注可在原步骤中查看',pad,height-24,12,'muted'),'</svg>');
  return out.join('');
}

const planTutorialUI={plan:null,model:null,layout:null,busy:false,assets:null};
function openPlanTutorial(plan,includeBranches=false) {
  closeReviewDetail();
  const model=buildPlanTutorial(plan,includeBranches),layout=layoutPlanTutorial(model);
  Object.assign(planTutorialUI,{plan,model,layout,assets:null});
  if(typeof mountTutorialBranches==='function')mountTutorialBranches(plan,includeBranches);
  $('#plan-tutorial-canvas').innerHTML=renderPlanTutorialSvg(model,layout);
  $('#plan-tutorial-canvas').classList.remove('actual-size');
  $('#plan-tutorial-zoom').textContent='原始大小';
  $('#plan-tutorial-status').textContent='点击步骤可回看；导出的图片包含卡图，可离线查看。';
  const dialog=$('#plan-tutorial-dialog');
  if(!dialog.open)dialog.showModal();
  $('#plan-tutorial-scroll').scrollTo(0,0);
}
async function tutorialAssets(model) {
  if(model.routes)return Object.assign({},...await Promise.all(model.routes.map(route=>tutorialAssets({...route.model,
    opening:[...route.model.opening,...(route.facts||[]).flatMap(f=>[...f.sources,...f.affected]).map(c=>({src:`/pics/${Number(c.code)}.jpg`}))]}))));
  const sources=[...new Set([...model.opening,...model.finalCards,...model.steps.flatMap(s=>s.actions.flatMap(a=>a.stages.flatMap(stage=>stage.cards)))].map(c=>c.src))];
  const assets={};
  let next=0;
  await Promise.all(Array.from({length:Math.min(6,sources.length)},async()=>{
    while(next<sources.length) {
      const src=sources[next++],response=await fetch(src);
      if(!response.ok)throw new Error('卡图加载失败，请重试');
      const blob=await response.blob(),bytes=new Uint8Array(await blob.arrayBuffer());
      let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
      assets[src]=`data:${blob.type||'image/jpeg'};base64,${btoa(binary)}`;
    }
  }));
  return assets;
}
async function tutorialPng(svg,layout) {
  const scale=Math.min(2,Math.sqrt(32000000/(layout.width*layout.height)),16000/layout.height);
  if(scale<.5)throw new Error('流程过长，请导出 SVG 以保留清晰度');
  const url=URL.createObjectURL(new Blob([svg],{type:'image/svg+xml;charset=utf-8'}));
  try {
    const img=new Image();img.src=url;await img.decode();
    const canvas=document.createElement('canvas');
    canvas.width=Math.round(layout.width*scale);canvas.height=Math.round(layout.height*scale);
    const context=canvas.getContext('2d');if(!context)throw new Error('图片画布创建失败，请重试');
    context.drawImage(img,0,0,canvas.width,canvas.height);
    return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('PNG 生成失败，请重试')),'image/png'));
  } finally {URL.revokeObjectURL(url);}
}
async function exportPlanTutorial(format) {
  const ui=planTutorialUI;if(ui.busy||!ui.model||!['png','svg'].includes(format))return;
  const {model,layout}=ui;ui.busy=true;
  document.querySelectorAll('[data-tutorial-export]').forEach(b=>b.disabled=true);
  $('#plan-tutorial-status').textContent='正在准备卡图与导出文件…';
  try {
    const assets=ui.assets||await tutorialAssets(model);
    if(ui.model===model)ui.assets=assets;
    const svg=renderPlanTutorialSvg(model,layout,assets);
    const blob=format==='png'?await tutorialPng(svg,layout):new Blob([svg],{type:'image/svg+xml;charset=utf-8'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=(model.name.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'_').replace(/[. ]+$/,'').slice(0,70)||'展开')+`-一图流.${format}`;
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
    if(ui.model===model)$('#plan-tutorial-status').textContent=`${format.toUpperCase()} 已生成，已开始下载。`;
  } catch(e) {if(ui.model===model)$('#plan-tutorial-status').textContent=`导出失败：${e.message}`;}
  finally {ui.busy=false;document.querySelectorAll('[data-tutorial-export]').forEach(b=>b.disabled=false);}
}
$('#plan-tutorial-close').onclick=()=>$('#plan-tutorial-dialog').close();
$('#plan-tutorial-zoom').onclick=()=>{
  const actual=$('#plan-tutorial-canvas').classList.toggle('actual-size');
  $('#plan-tutorial-zoom').textContent=actual?'适应宽度':'原始大小';
};
document.querySelectorAll('[data-tutorial-export]').forEach(b=>b.onclick=()=>exportPlanTutorial(b.dataset.tutorialExport));
async function followTutorialStep(e) {
  const step=e.target.closest('[data-tutorial-node]');if(!step)return;
  if(e.type==='keydown'&&!['Enter',' '].includes(e.key))return;
  e.preventDefault();
  const plan=planTutorialUI.plan,id=step.dataset.tutorialNode;
  $('#plan-tutorial-dialog').close();
  await $('#edit-plan').onclick();
  const route=step.closest('[data-tutorial-route]')?.dataset.tutorialRoute;
  if(route&&route!=='main'&&typeof displayBranchRoute==='function') {branchUI.selected=route;branchUI.viewing=true;displayBranchRoute();}
  if(app.view==='history'&&reviewUI.report?.id===plan.id)selectReviewNode(id);
}
$('#plan-tutorial-canvas').addEventListener('click',followTutorialStep);
$('#plan-tutorial-canvas').addEventListener('keydown',followTutorialStep);
