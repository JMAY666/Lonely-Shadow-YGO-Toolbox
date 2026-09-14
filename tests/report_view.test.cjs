const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const escape = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const context = vm.createContext({escape, zoneNames:{main:'主',extra:'额外',side:'副'}, dt:()=>'',duration:()=>'',statusNames:{completed:'完成'},reasons:{}, cardsHtml:()=>'',eventSummary:()=>''});
for(const file of ['activation.js','report-view.js'])vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/trainer/web',file), 'utf8'), context);
function render(number) {
  return context.renderTrainingReport({id:'test',name:'测试',events:[],deck:{main:[],extra:[],side:[]},catalog:{},started_ms:0,status:'completed',warnings:[],statistics:{},limitations:[],actions:[{
    id:'a',kind:'effect',time_ms:0,cards:[{name:'多效果卡'}],evidence_refs:[],heading:'发动多效果卡的效果（编号未知）：',
    effect_number:number,effect_quote:'①：只截取的第一段。',effect_text:'①：第一段。\n②：完整第二段 <script>。',
    execution:[{role:'effect',text:'实际抽 2 张卡',cards:[]}]
  }]}, {raw:false});
}
test('known and unknown effects both show the full frozen card text above actual results', () => {
  for (const number of [1, null]) {
    const html = render(number);
    assert.match(html, /发动多效果卡的效果<\/span>/);
    assert.match(html, /②：完整第二段 &lt;script&gt;/);
    assert.doesNotMatch(html, /编号未知|只截取的第一段|<script>/);
    assert(html.indexOf('效果文本') < html.indexOf('实际结果'));
    assert.match(html, /实际抽 2 张卡/);
  }
});
