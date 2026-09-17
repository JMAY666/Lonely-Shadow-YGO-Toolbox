'use strict';
const conditionEditor={value:null,schema:null,generation:0,timer:null,valid:false,templates:[]};
const conditionEsc=OpeningRules.safe;
function conditionAt(path){return path?path.split('.').reduce((node,key)=>node.items[Number(key)],conditionEditor.value.rule):conditionEditor.value.rule;}
function conditionReplace(path,node){if(!path)conditionEditor.value.rule=node;else{const parts=path.split('.'),index=Number(parts.pop());conditionAt(parts.join('.')).items[index]=node;}}
function conditionDefault(field='level'){
  return ['level','rank','link'].includes(field)?{field,op:'eq',value:3}:{field,op:'in',values:field==='code'?[choiceDesign().deck.main[0]].filter(Boolean):field==='setcode'?[]:[conditionEditor.schema.fields[field].options[0].value]};
}
function closeConditionEditor(){++conditionEditor.generation;clearTimeout(conditionEditor.timer);conditionEditor.value=null;$('#condition-card-editor').hidden=true;$('#opening-choices').hidden=false;}
async function openConditionEditor(value=null){
  closeConditionEditor();$('#opening-error').textContent='';$('#condition-card-editor').hidden=false;$('#opening-choices').hidden=true;
  $('#opening-shortcut-section').hidden=true;
  $('#condition-rule-tree').textContent='正在加载条件选项…';$('#condition-apply').disabled=true;
  const generation=conditionEditor.generation;
  try{conditionEditor.schema ||= await api('/api/opening/schema');}
  catch(error){$('#condition-rule-tree').textContent=error.message;return;}
  if(generation!==conditionEditor.generation)return;
  const d=choiceDesign(),existing=flow.mode==='banned'?d.conditions.banned[flow.banIndex]:d.conditions.slots[flow.slot];
  conditionEditor.value=structuredClone(value|| (OpeningRules.is(existing)?existing:OpeningRules.tuner(3)));
  conditionEditor.templates=[1,2,3].map(OpeningRules.tuner);
  for(const target of [flow.design,flow.design.opponent_config].filter(Boolean))for(const entry of [...target.conditions.slots,...target.conditions.banned]){
    if(OpeningRules.is(entry)&&!conditionEditor.templates.some(t=>JSON.stringify(t)===JSON.stringify(entry)))conditionEditor.templates.push(structuredClone(entry));
  }
  $('#condition-templates').innerHTML=conditionEditor.templates.map((v,i)=>`<button type="button" data-condition-template="${i}">${conditionEsc(OpeningRules.describe(v,flow.design.catalog))}</button>`).join('');
  renderConditionEditor();scheduleConditionPreview();
}
function renderConditionNode(node,path='',depth=0){
  const schema=conditionEditor.schema,esc=conditionEsc;
  const remove=path?`<button type="button" data-condition-remove="${path}" aria-label="移除此条件">移除</button>`:'';
  if(['all','any','not'].includes(node.op)){
    return `<fieldset class="condition-group"><legend>${node.op==='not'?'排除以下条件':node.op==='all'?'全部满足（且）':'任意满足（或）'}</legend><div class="condition-node-toolbar"><select data-condition-group="${path}" aria-label="组合关系">${[['all','全部满足（且）'],['any','任意满足（或）'],['not','排除（非）']].filter(([op])=>op!=='not'||node.items.length===1).map(([op,label])=>`<option value="${op}" ${op===node.op?'selected':''}>${label}</option>`).join('')}</select>${remove}</div>${node.items.map((child,i)=>renderConditionNode(child,path?path+'.'+i:String(i),depth+1)).join('')}<div class="condition-node-toolbar">${node.op!=='not'&&depth<6?`<button type="button" data-condition-add="${path}" data-node-kind="leaf">＋条件</button><button type="button" data-condition-add="${path}" data-node-kind="all">＋且／或组合</button><button type="button" data-condition-add="${path}" data-node-kind="not">＋排除组合</button>`:''}</div></fieldset>`;
  }
  const field=schema.fields[node.field];if(!field)return '<p>不支持的字段，请替换条件。</p>';
  const numeric=field.numeric;
  const operations=numeric?[['eq','等于'],['gte','大于等于'],['lte','小于等于'],['between','范围']]:[['in','包含其中任意'],['not_in','排除所有所选']];
  let values;
  if(numeric)values=node.op==='between'?`<input type="number" min="0" max="255" data-condition-number="${path}" data-value-key="min" value="${esc(node.min)}" aria-label="范围下限"><span>至</span><input type="number" min="0" max="255" data-condition-number="${path}" data-value-key="max" value="${esc(node.max)}" aria-label="范围上限">`:`<input type="number" min="0" max="255" data-condition-number="${path}" data-value-key="value" value="${esc(node.value)}" aria-label="条件数值">`;
  else if(node.field==='setcode')values=`<input data-condition-setcodes="${path}" value="${esc((node.values||[]).join(', '))}" placeholder="十进制编号，逗号分隔" aria-label="数据库系列编号">`;
  else{
    const options=node.field==='code'?[...new Set([...choiceDesign().deck.main,...node.values])].map(value=>({value,label:OpeningRules.describe(value,flow.design.catalog)+(choiceDesign().deck.main.includes(value)?'':'（不在当前主卡组）')})):field.options;
    values=`<select multiple data-condition-values="${path}" aria-label="${esc(field.label)}选项">${options.map(o=>`<option value="${esc(o.value)}" ${node.values.includes(o.value)?'selected':''}>${esc(o.label)}</option>`).join('')}</select>`;
  }
  return `<div class="condition-leaf"><select data-condition-field="${path}" aria-label="条件字段">${Object.entries(schema.fields).map(([key,f])=>`<option value="${key}" ${node.field===key?'selected':''}>${esc(f.label)}</option>`).join('')}</select><select data-condition-op="${path}" aria-label="比较方式">${operations.map(([key,label])=>`<option value="${key}" ${key===node.op?'selected':''}>${label}</option>`).join('')}</select><div class="condition-values">${values}</div>${remove}</div>`;
}
function renderConditionEditor(){
  if(!conditionEditor.value)return;
  $('#condition-rule-tree').innerHTML=renderConditionNode(conditionEditor.value.rule);
  $('#condition-purpose').textContent=flow.mode==='banned'?'禁止上手：命中的所有卡牌均不能进入整副初始手牌，不占槽位。':`起手槽位 ${flow.slot+1}：由 1 张满足条件的真实卡牌填充。`;
  $('#condition-face-preview').innerHTML=OpeningRules.face(conditionEditor.value,flow.design.catalog,flow.mode==='banned');
}
function conditionProposal(){
  const conditions=structuredClone(choiceDesign().conditions);
  const kind=flow.mode==='banned'?'banned':'slots';
  const index=kind==='banned'?(Number.isInteger(flow.banIndex)?flow.banIndex:conditions.banned.length):flow.slot;
  conditions[kind][index]=structuredClone(conditionEditor.value);
  return {conditions,focus:{kind,index}};
}
function scheduleConditionPreview(){
  clearTimeout(conditionEditor.timer);conditionEditor.valid=false;$('#condition-apply').disabled=true;
  $('#condition-preview-result').textContent='正在按当前主卡组校验全部起手槽位…';
  $('#condition-face-preview').innerHTML=OpeningRules.face(conditionEditor.value,flow.design.catalog,flow.mode==='banned');
  const generation=++conditionEditor.generation;
  conditionEditor.timer=setTimeout(async()=>{
    try{
      const proposal=conditionProposal(),deck=structuredClone(choiceDesign().deck);
      const result=await api('/api/opening/preview',{deck,...proposal});
      if(generation!==conditionEditor.generation||!conditionEditor.value)return;
      conditionEditor.valid=!!result.conditions;$('#condition-apply').disabled=!conditionEditor.valid;
      const f=result.focus;
      $('#condition-preview-result').innerHTML=`${(result.errors||[]).map(e=>`<p class="form-error">${conditionEsc(e)}</p>`).join('')}${(result.warnings||[]).map(e=>`<p>${conditionEsc(e)}</p>`).join('')}${f?`<p><strong>原始匹配 ${f.types} 种 / ${f.copies} 张</strong>${flow.mode==='required'?`<br>结合全部槽位后，可用于本槽 ${f.usable_types} 种`:'<br>以下全部副本禁止出现在初始手牌'}</p><div class="condition-preview-cards">${f.cards.map(c=>`<article class="condition-preview-card ${!c.available_count&&flow.mode==='required'?'condition-unavailable':''}"><img src="/pics/${c.code}.jpg" alt=""><div><strong>${conditionEsc(c.name)}</strong><small>投入 ${c.count} 张${flow.mode==='required'?` · 最大余量 ${c.available_count} 张`:''}</small><small>${conditionEsc(c.reason)}</small></div></article>`).join('')||'<p>当前没有匹配卡牌。</p>'}</div>`:''}<p class="condition-preview-help">${flow.mode==='required'?'最大余量指先满足其他指定／条件槽位后，该卡最多可剩下几张供本槽及随机补齐使用；各卡独立计算，不能相加。每个条件槽只占 1 张。':'禁止规则不删除牌组副本，后续抽牌和检索照常。'}</p>${result.valid?'<p>整套起手规则可满足。</p>':'<p>可以保留条件继续编辑，解决冲突后才能开始。</p>'}`;
    }catch(error){if(generation===conditionEditor.generation)$('#condition-preview-result').textContent='预览失败：'+error.message;}
  },120);
}
function applyConditionCard(){
  if(!conditionEditor.valid)return;
  const d=choiceDesign(),proposal=conditionProposal();d.conditions=proposal.conditions;
  flow.design.startError='';closeConditionEditor();$('#opening-dialog').close();renderDesign();
}
$('#choose-condition').onclick=run(()=>openConditionEditor());
$('#condition-cancel').onclick=()=>{closeConditionEditor();renderChoices();};
$('#condition-apply').onclick=applyConditionCard;
$('#opening-dialog').addEventListener('close',closeConditionEditor);
$('#condition-card-editor').addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.conditionTemplate!==undefined){conditionEditor.value=structuredClone(conditionEditor.templates[Number(b.dataset.conditionTemplate)]);}
  else if(b.dataset.conditionRemove!==undefined){const parts=b.dataset.conditionRemove.split('.'),i=Number(parts.pop()),parent=conditionAt(parts.join('.'));if(parent.items.length===1){$('#opening-error').textContent='组合至少保留一项；可先添加新条件或替换当前字段。';return;}parent.items.splice(i,1);}
  else if(b.dataset.conditionAdd!==undefined){const parent=conditionAt(b.dataset.conditionAdd);if(parent.items.length>=30)return;const leaf=conditionDefault();parent.items.push(b.dataset.nodeKind==='leaf'?leaf:{op:b.dataset.nodeKind,items:[leaf]});}
  else return;
  renderConditionEditor();scheduleConditionPreview();
});
$('#condition-rule-tree').addEventListener('change',e=>{
  const t=e.target,d=t.dataset;
  if(d.conditionGroup!==undefined)conditionAt(d.conditionGroup).op=t.value;
  else if(d.conditionField!==undefined)conditionReplace(d.conditionField,conditionDefault(t.value));
  else if(d.conditionOp!==undefined){const n=conditionAt(d.conditionOp);if(conditionEditor.schema.fields[n.field].numeric){const value=n.value??n.min??3;conditionReplace(d.conditionOp,t.value==='between'?{field:n.field,op:t.value,min:value,max:value}:{field:n.field,op:t.value,value});}else n.op=t.value;}
  else if(d.conditionValues!==undefined){const n=conditionAt(d.conditionValues);n.values=[...t.selectedOptions].map(o=>['code','race','attribute'].includes(n.field)?Number(o.value):o.value);}
  else return;
  renderConditionEditor();scheduleConditionPreview();
});
$('#condition-rule-tree').addEventListener('input',e=>{
  const t=e.target,d=t.dataset;
  if(d.conditionNumber!==undefined)conditionAt(d.conditionNumber)[d.valueKey]=t.value.trim()===''?null:Number(t.value);
  else if(d.conditionSetcodes!==undefined)conditionAt(d.conditionSetcodes).values=t.value.split(/[,，\s]+/).filter(Boolean).map(Number);
  else return;
  scheduleConditionPreview();
});
