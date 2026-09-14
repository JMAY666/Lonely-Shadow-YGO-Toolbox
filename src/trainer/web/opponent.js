'use strict';
// This renderer submits one versioned choice to the same native duel. It never
// simulates legality, edits the board, or operates a second engine instance.
const opponentState={id:new URLSearchParams(location.search).get('session'),token:null,state:null,busy:false,key:null};
const opponentEscape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const opponentError=error=>{document.querySelector('#opponent-error').textContent=error.message||String(error);};
async function opponentApi(path,body) {
  const response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Trainer-Token':opponentState.token},body:JSON.stringify(body)}:undefined);
  const value=await response.json();if(!response.ok)throw new Error(value.error);return value;
}
function opponentInt(value) {const buffer=new ArrayBuffer(4);new DataView(buffer).setInt32(0,value,true);return [...new Uint8Array(buffer)];}
function parseOpponentPrompt(raw) {
  const bytes=Uint8Array.from((raw.match(/../g)||[]).map(v=>parseInt(v,16)));
  const u32=offset=>new DataView(bytes.buffer).getUint32(offset,true),u16=offset=>new DataView(bytes.buffer).getUint16(offset,true);
  const result={message:bytes[0],choices:[],mode:'single',min:1,max:1};
  const choice=(label,response,code=null,details='')=>result.choices.push({label,response,code,details});
  const card=(p,width=8)=>({code:u32(p)&0x7fffffff,controller:bytes[p+4],location:bytes[p+5],sequence:bytes[p+6]});
  const cardChoice=(p,index,response)=>{const c=card(p),zone={1:'主卡组',2:'手牌',4:'怪兽区',8:'魔法／陷阱区',16:'墓地',32:'除外',64:'额外卡组',128:'素材'}[c.location]||'未知区域';choice('选择此卡',response,c.code,`${c.controller===1?'对手':'我方'} · ${zone}${[4,8].includes(c.location)?' '+(c.sequence+1):''}`);};
  const msg=bytes[0];
  if(msg===12||msg===13){choice(msg===12?'发动效果':'是',opponentInt(1),msg===12?u32(2):null);choice(msg===12?'不发动':'否',opponentInt(0));}
  else if(msg===16) {
    let forced=false;
    for(let i=0;i<bytes[2];i++) {const p=12+i*14;forced ||=!!bytes[p+1];cardChoice(p+2,i,opponentInt(i));Object.assign(result.choices.at(-1),{label:'发动',description:u32(p+10)});result.choices.at(-1).details+=bytes[p+1]?' · 必须发动':'';}
    if(!forced)choice('放弃本次响应',opponentInt(-1));
  } else if(msg===11||msg===10) {
    let p=2;
    const groups=msg===11?['通常召唤','特殊召唤','变更表示','盖放怪兽','盖放魔法／陷阱','发动']:['发动','攻击'];
    groups.forEach((label,group)=>{const count=bytes[p++],width=msg===11?(group===5?11:7):(group===0?11:8);for(let i=0;i<count;i++,p+=width){cardChoice(p,i,opponentInt((i<<16)|group));result.choices.at(-1).label=label;}});
    if(bytes[p])choice(msg===11?'进入战斗阶段':'进入主要阶段 2',opponentInt(msg===11?6:2));
    if(bytes[p+1])choice('结束回合',opponentInt(msg===11?7:3));
    if(msg===11&&bytes[p+2])choice('整理手牌顺序',opponentInt(8));
  } else if(msg===14||msg===143) {
    for(let i=0;i<bytes[2];i++) {
      const value=u32(3+i*4);choice(msg===143?`数字 ${value}`:`选项 ${i+1}`,opponentInt(i),msg===14&&value>=10000?Math.floor(value/16):null);
      if(msg===14)result.choices.at(-1).description=value;
    }
  } else if(msg===19) {
    for(const [flag,name]of [[1,'表侧攻击'],[2,'里侧攻击'],[4,'表侧守备'],[8,'里侧守备']])if(bytes[6]&flag)choice(name,opponentInt(flag),u32(2));
  } else if(msg===15||msg===20) {
    result.mode='cards';result.min=bytes[3];result.max=bytes[4];
    for(let i=0;i<bytes[5];i++)cardChoice(6+i*8,i,[i]);
    if(msg===20) {result.tributeMinimum=result.min;result.min=1;for(let i=0;i<bytes[5];i++)result.choices[i].details+=' · 解放值 '+bytes[13+i*8];}
    if(bytes[2])result.cancel=opponentInt(-1);
  } else if(msg===26) {
    let p=7;for(let i=0;i<bytes[6];i++,p+=8)cardChoice(p,i,[1,i]);
    const selectable=bytes[6],unselected=bytes[p++];
    for(let i=0;i<unselected;i++,p+=8){cardChoice(p,i,[1,selectable+i]);result.choices.at(-1).label='取消选择';}
    if(bytes[2]||bytes[3])choice(bytes[2]?'完成选择':'取消',opponentInt(-1));
  } else if(msg===18||msg===24) {
    result.mode='places';result.min=result.max=bytes[2]||1;const unavailable=u32(3);
    if(bytes[2]===0)result.cancel=[1,0,0];
    for(let i=0;i<32;i++)if(!(unavailable&(1<<i))) {
      const controller=(i>=16?0:1),zone=(i%16>=8?8:4),sequence=i%8;
      choice(`${controller===1?'对手':'我方'} · ${zone===4?'怪兽区':'魔法／陷阱区'} ${sequence+1}`,[controller,zone,sequence]);
    }
  } else if(msg===23) {
    result.mode='sum';result.min=bytes[7];result.max=bytes[8];result.target=u32(3);result.sumMode=bytes[1];
    let p=10;const mandatory=bytes[9];result.mandatory=mandatory;
    for(let i=0;i<mandatory;i++,p+=11)result.choices.push({code:u32(p),label:'已指定素材',fixed:true,details:'合计值 '+u32(p+7)});
    const count=bytes[p++];for(let i=0;i<count;i++,p+=11){cardChoice(p,i,[i]);result.choices.at(-1).details+=' · 合计值 '+u32(p+7);}
    if(result.sumMode===1)result.max=count;
  } else if(msg===140||msg===141) {
    result.mode='mask';result.min=result.max=bytes[2];const mask=u32(3);
    const attributes=['地','水','炎','风','光','暗','神'];
    const races=['战士','魔法使','天使','恶魔','不死','机械','水','炎','岩石','鸟兽','植物','昆虫','雷','龙','兽','兽战士','恐龙','鱼','海龙','爬虫类','念动力','幻神兽','创造神','幻龙','电子界','幻想魔'];
    for(let i=0;i<32;i++)if(mask&(1<<i))choice((msg===141?attributes:races)[i]||'类型 '+(i+1),[i]);
  } else if(msg===142)result.mode='announce-card';
  else if(msg===25) {
    result.mode='sort';for(let i=0;i<bytes[2];i++)cardChoice(3+i*7,i,[i]);result.cancel=[255];
  } else if(msg===22) {
    result.mode='counter';result.target=u16(4);
    for(let i=0;i<bytes[6];i++){const p=7+i*9;cardChoice(p,i,[i]);result.choices.at(-1).available=u16(p+7);}
  } else if(msg===132)for(const [i,name]of [[1,'石头'],[2,'剪刀'],[3,'布']])choice(name,opponentInt(i));
  else result.error='此选择窗口尚未提供界面，请保留对局并报告窗口编号 '+msg;
  return result;
}
async function submitOpponent(command,bytes=null) {
  if(opponentState.busy)return;opponentState.busy=true;
  document.querySelectorAll('#opponent-prompt button').forEach(b=>b.disabled=true);
  try {
    const state=opponentState.state;
    const op=await opponentApi('/api/opponent/control',{id:opponentState.id,command,version:state.version,raw:bytes?.map(b=>(b&255).toString(16).padStart(2,'0')).join('')});
    for(let i=0;i<60;i++) {
      const latest=await opponentApi('/api/opponent/state/'+opponentState.id);
      if(latest.token===op.token||latest.version!==state.version||!latest.running){opponentState.key=null;break;}
      await new Promise(resolve=>setTimeout(resolve,50));
    }
    document.querySelector('#opponent-error').textContent='';
  } catch(e){opponentError(e);opponentState.key=null;}
  finally{opponentState.busy=false;await refreshOpponent();}
}
async function renderOpponent(state) {
  const zoneName={1:'主卡组',2:'手牌',4:'怪兽区',8:'魔法／陷阱区',16:'墓地',32:'除外',64:'额外卡组',128:'素材'};
  const snapshot=state.state;
  document.querySelector('#opponent-context').textContent=`${state.context.name} · 与我方窗口同步 · ${state.running?(state.manual?'手动接管中，AI 暂停':'AI 托管中'):'对局已结束，记录保留'}`;
  if(snapshot)document.querySelector('#opponent-board').innerHTML=`<h2>共享场面 · 第 ${snapshot.turn} 回合 · 我方 LP ${snapshot.lp[0]} / 对手 LP ${snapshot.lp[1]} · 连锁 ${snapshot.chain_depth}</h2>${[0,1].map(side=>`<div><h3>${side?'对手':'我方'}</h3><div class="branch-cards">${snapshot.cards.filter(c=>c.controller===side&&[2,4,8,16,32].includes(c.location)).map(c=>`<span class="branch-card"><img src="/pics/${c.code}.jpg" alt="${opponentEscape(c.name)}"><span>${opponentEscape(c.name)}</span><small>${zoneName[c.location]} ${[4,8].includes(c.location)?c.sequence+1:''}</small></span>`).join('')}</div></div>`).join('')}`;
  const area=document.querySelector('#opponent-prompt');
  if(!state.running||!state.manual||state.player!==1||state.answered||!state.raw||state.raw==='-') {area.innerHTML=`<h2>${!state.running?'对局已结束':!state.manual?'对手由 AI 继续操作':state.player===0?'等待我方操作，请返回主窗口':'等待引擎处理'}</h2>`;return;}
  const model=parseOpponentPrompt(state.raw);
  if(model.error){area.textContent=model.error;return;}
  await Promise.all(model.choices.filter(c=>c.code).map(async c=>{try{const card=await opponentApi('/api/card/'+c.code);c.name=card.name;c.desc=card.desc;if(c.description&&Math.floor(c.description/16)===c.code)c.details+=' · '+(card['str'+((c.description%16)+1)]||'');}catch{}}));
  if(opponentState.state?.version!==state.version)return;
  area.innerHTML=`<h2>${({10:'选择战斗操作',11:'选择主要阶段操作',12:'是否发动效果',13:'确认选择',14:'选择效果选项',15:'选择卡牌',16:'选择连锁响应',18:'选择放置区域',19:'选择表示形式',20:'选择祭品',22:'选择指示物',23:'选择合计素材',24:'选择不可用区域',25:'排列卡牌',26:'选择或取消卡牌',132:'选择猜拳',140:'宣言种族',141:'宣言属性',142:'宣言卡牌',143:'宣言数字'})[model.message]||'对手选择'}</h2><p>请选择规则允许的操作。提交后由引擎校验，非法选择会保留此窗口供重新选择。</p>${model.mode!=='single'?`<p>数量 ${model.min}–${model.max}${model.target?' · 要求合计 '+model.target:''}</p>`:''}<div class="opponent-choices">${model.choices.map((c,i)=>`<label class="opponent-choice">${model.mode==='single'?`<button data-opponent-choice="${i}">`:`<input ${['sort','counter'].includes(model.mode)?`type="number" min="0" max="${c.available??model.choices.length-1}" value="${model.mode==='sort'?i:0}"`:`type="checkbox" ${c.fixed?'checked disabled':''}`} data-opponent-select="${i}">`}${c.code?`<img src="/pics/${c.code}.jpg" alt="${opponentEscape(c.name||c.code)}">`:''}<strong>${opponentEscape(c.label)}${c.name?' · '+opponentEscape(c.name):''}</strong><small>${opponentEscape(c.details||'')}</small>${c.desc?`<span class="opponent-card-text">${opponentEscape(c.desc)}</span>`:''}${model.mode==='single'?'</button>':''}</label>`).join('')}</div>${model.mode==='announce-card'?'<label>宣言卡牌编号<input id="opponent-declare-code" type="number" min="1"></label><label>搜索卡名<input id="opponent-declare-search" type="search"></label><div id="opponent-declare-results"></div>':''}${model.mode!=='single'?'<button id="opponent-submit" class="primary">提交选择</button>':''}${model.cancel?'<button id="opponent-cancel">取消选择</button>':''}`;
  area.querySelectorAll('[data-opponent-choice]').forEach(button=>button.onclick=()=>submitOpponent('answer',model.choices[Number(button.dataset.opponentChoice)].response));
  if(model.cancel)document.querySelector('#opponent-cancel').onclick=()=>submitOpponent('answer',model.cancel);
  if(model.mode==='announce-card')document.querySelector('#opponent-declare-search').onchange=async e=>{
    try {const data=await opponentApi('/api/cards?q='+encodeURIComponent(e.target.value));document.querySelector('#opponent-declare-results').innerHTML=data.cards.map(c=>`<button data-declare="${c.id}">${opponentEscape(c.name)}</button>`).join('');document.querySelectorAll('[data-declare]').forEach(b=>b.onclick=()=>document.querySelector('#opponent-declare-code').value=b.dataset.declare);}catch(e){opponentError(e);}
  };
  if(model.mode!=='single')document.querySelector('#opponent-submit').onclick=()=>{
    try {
      const inputs=[...area.querySelectorAll('[data-opponent-select]')],selected=inputs.filter(i=>i.checked&&!i.disabled).map(i=>Number(i.dataset.opponentSelect));let response;
      if(model.mode==='announce-card') {
        const code=Number(document.querySelector('#opponent-declare-code').value);
        if(!Number.isInteger(code)||code<=0||code>0xffffffff)throw new Error('请输入完整的有效卡牌编号');
        response=opponentInt(code);
      }
      else if(model.mode==='sort')response=inputs.map(i=>Number(i.value));
      else if(model.mode==='counter')response=inputs.flatMap(i=>{const n=Number(i.value);if(!Number.isInteger(n)||n<0||n>65535)throw new Error('指示物数量无效');return [n&255,n>>8];});
      else {
        if(selected.length<model.min||selected.length>model.max)throw new Error('请选择符合数量要求的项目');
        if(model.mode==='mask')response=opponentInt(selected.reduce((n,i)=>n|(1<<model.choices[i].response[0]),0));
        else if(model.mode==='places')response=selected.flatMap(i=>model.choices[i].response);
        else if(model.mode==='sum')response=[selected.length+model.mandatory,...Array.from({length:model.mandatory},(_,i)=>i),...selected.map(i=>model.choices[i].response[0])];
        else response=[selected.length,...selected.map(i=>model.choices[i].response[0])];
      }
      if(response.length>64||response.some(n=>!Number.isInteger(n)||n<0||n>255))throw new Error('本次选择超出规则输入范围');
      void submitOpponent('answer',response);
    }catch(e){opponentError(e);}
  };
}
async function refreshOpponent() {
  if(opponentState.busy||!opponentState.token)return;
  try {
    const state=await opponentApi('/api/opponent/state/'+opponentState.id),key=JSON.stringify([state.version,state.manual,state.answered,state.running]);opponentState.state=state;
    if(key===opponentState.key)return;opponentState.key=key;await renderOpponent(state);
  }catch(e){opponentError(e);}
}
document.querySelector('#opponent-take').onclick=()=>submitOpponent('take');
document.querySelector('#opponent-release').onclick=()=>submitOpponent('release');
document.querySelector('#opponent-close').onclick=async()=>{await submitOpponent('release');if(opponentState.state&&!opponentState.state.manual)window.close();};
opponentApi('/api/bootstrap').then(boot=>{opponentState.token=boot.token;return refreshOpponent();}).catch(opponentError);
setInterval(()=>void refreshOpponent(),350);
if(typeof module!=='undefined')module.exports={parseOpponentPrompt,opponentInt};
