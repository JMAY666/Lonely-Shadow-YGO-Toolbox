'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/trainer/web/superpre.js'),'utf8');
function fixture(open=false) {
  const elements=new Map();
  const $=selector=>{if(!elements.has(selector))elements.set(selector,{textContent:'',removeAttribute(name){delete this[name];}});return elements.get(selector);};
  $('#app-settings-dialog').open=open;
  const context=vm.createContext({$,window:{},dt:value=>'time:'+value,clearTimeout(){},setTimeout(){return 1;},
    app:{cache:new Map([[1,{name:'old'}]]),pendingCards:new Map(),view:'home',deck:{main:[1]},dirty:true,searchGeneration:0,renderGeneration:0,detailGeneration:0},
    api:async url=>url==='/api/superpre'?state():({cards:123}),notice(){},Date});
  vm.runInContext(source+'\nglobalThis.ui=superpreUI;',context);
  return {context,$};
}
function state(extra={}) {return {installed:null,latest:null,update_available:false,job:{busy:false,action:'',error:'',message:''},...extra};}
test('settings opened during a cold start initializes once the patch script loads',async()=>{
  const {context:c,$}=fixture(true);
  await new Promise(setImmediate);
  assert(c.ui.state);assert.equal($('#superpre-state').textContent,'未安装');
  assert.equal($('#superpre-install').disabled,false);
});
test('patch controls follow installation, update and operation states with errors still visible',()=>{
  const {context:c,$}=fixture();
  c.renderSuperpre(state());
  assert.equal($('#superpre-install').disabled,false);assert.equal($('#superpre-update').disabled,true);assert.equal($('#superpre-uninstall').disabled,true);
  const installed={version:'1',card_count:2,updated_ms:1,sha256:'old'};
  const latest={version:'2',updated_ms:2,checked_ms:3,download_url:'https://cdntx.moecube.com/ygopro-super-pre/archive/ygopro-super-pre-2.ypk'};
  c.renderSuperpre(state({installed,latest,update_available:true}));
  assert.equal($('#superpre-install').disabled,true);assert.equal($('#superpre-update').disabled,false);assert.equal($('#superpre-uninstall').disabled,false);
  assert.equal($('#superpre-updated').textContent,'time:2');assert.equal($('#superpre-download').href,latest.download_url);
  c.renderSuperpre(state({installed,latest,job:{busy:true,loaded:5,total:10,message:'下载中'}}));
  for(const action of ['install','check','update','uninstall'])assert.equal($('#superpre-'+action).disabled,true);
  assert.equal($('#superpre-progress').value,5);
  c.renderSuperpre(state({installed,latest,job:{busy:false,error:'离线',message:'旧版保留'}}));
  assert.equal($('#superpre-error').textContent,'离线');assert.equal($('#superpre-installed').textContent,'1 · 2 张补丁卡 · time:1');
});
test('resource changes invalidate live card caches without losing unsaved deck buffers',async()=>{
  const {context:c,$}=fixture();
  await c.refreshSuperpreCatalog(state());
  const before=JSON.stringify(c.app.deck);
  await c.refreshSuperpreCatalog(state({installed:{sha256:'new'}}));
  assert.equal(c.app.cache.size,0);assert.equal(c.app.catalogEpoch,1);assert.equal(c.app.searchGeneration,1);
  assert.equal(JSON.stringify(c.app.deck),before);assert.equal(c.app.dirty,true);
  assert.equal($('#resource-count').textContent,'123 张卡牌');
});
test('fast successful mutations refresh state and repeated clicks cannot submit concurrent operations',async()=>{
  const {context:c}=fixture();let submitCount=0,resolve;
  c.ui.state=state();c.api=async(url,body)=>{if(body){submitCount++;return new Promise(r=>{resolve=r;});}return state();};
  const first=c.superpreAction('install');await c.superpreAction('install');assert.equal(submitCount,1);
  let reads=0;c.loadSuperpreSettings=async()=>{reads++;};
  resolve(state({installed:{version:'1'}}));await first;
  assert.equal(reads,1);assert.equal(c.ui.request,false);
});
test('uninstall refreshes an open editor and explains missing cards without changing its draft',async()=>{
  const {context:c,$}=fixture();let searches=0,renders=0;
  c.app.view='decks';c.app.selected=1;c.ui.applied='installed';
  c.search=async()=>{searches++;};c.renderDeck=async()=>{renders++;};c.showCard=async()=>{throw new Error('missing');};
  await c.refreshSuperpreCatalog(state());
  assert.equal(searches,1);assert.equal(renders,1);assert.equal(c.app.detailGeneration,1);
  assert.match($('#card-detail').innerHTML,/构筑已保留/);assert.equal(JSON.stringify(c.app.deck),'{"main":[1]}');assert(c.app.dirty);
});
test('in-flight card lookups from an older catalog cannot repopulate the refreshed cache',async()=>{
  const appSource=fs.readFileSync(path.join(__dirname,'../src/trainer/web/app.js'),'utf8');
  const c=vm.createContext({app:{cache:new Map(),pendingCards:new Map()},api:null});let resolveOld,resolveNew;
  c.api=()=>new Promise(resolve=>{resolveOld=resolve;});
  vm.runInContext(appSource.slice(appSource.indexOf('async function card('),appSource.indexOf('function switchView(')),c);
  const old=c.card(1);c.app.catalogEpoch=1;c.app.cache.clear();c.app.pendingCards.clear();
  c.api=()=>new Promise(resolve=>{resolveNew=resolve;});const fresh=c.card(1);
  resolveOld({id:1,name:'stale'});await old;
  assert.equal(c.app.cache.size,0);assert(c.app.pendingCards.has(1));
  resolveNew({id:1,name:'fresh'});await fresh;assert.equal(c.app.cache.get(1).name,'fresh');
});
