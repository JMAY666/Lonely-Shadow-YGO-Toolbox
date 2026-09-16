const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function setup(file,extra={}) {
  const context=vm.createContext({$:()=>({}),run:fn=>fn,...extra});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/trainer/web',file),'utf8'),context);return context;
}
test('series aliases and multiple primary tags filter without duplicating plans',()=>{
  const c=setup('plan-library.js'),plans=[{name:'路线 A',tags:[{id:'a',name:'转生炎兽',aliases:['沙拉','Salamangreat'],primary:true},{id:'b',name:'炎王',aliases:[],primary:false}]},{name:'路线 B',tags:[{id:'b',name:'炎王',aliases:[],primary:true}]},{name:'空白',tags:[]}];
  assert.equal(c.filterPlans(plans,'ｓａｌａｍａｎｇｒｅａｔ').length,1);
  assert.equal(c.filterPlans(plans,'沙拉').length,1);
  assert.equal(c.filterPlans(plans,'','b').length,2);
  assert.equal(c.filterPlans(plans,'','b',true).length,1);
  assert.equal(c.filterPlans(plans,'','untagged').length,1);
  plans[0].tags[1].primary=true;assert.equal(c.filterPlans(plans,'','b',true).length,2);
});

test('favorite filter composes with folder and text searches without changing stored plans',()=>{
  const c=setup('plan-library.js'),plans=[{id:'1',name:'one',favorite:true,tags:[{id:'a',name:'a'}]},
    {id:'2',name:'two',favorite:false,tags:[{id:'a',name:'a'}]},{id:'3',name:'three',favorite:true,tags:[]}];
  assert.equal(c.filterPlans(plans,'','',false,true).length,2);
  assert.equal(c.filterPlans(plans,'','a',false,true)[0].id,'1');
  assert.equal(c.filterPlans(plans,'two','a',false,true).length,0);
  assert.equal(c.filterPlans(plans,'two','a').length,1);
});

test('out-of-order favorite acknowledgements never roll back another item',async()=>{
  const pending={},plans=[{id:'a',favorite:false},{id:'b',favorite:false}],duel={stage:5,result:{matches:structuredClone(plans)}};
  const c=setup('plan-library.js',{$:id=>id==='#saved-plan-favorite'?null:{},document:{querySelectorAll:()=>[]},
    api:(_url,body)=>new Promise(resolve=>pending[body.id]=resolve),duelState:()=>duel,duelStages:{plans:5}});
  c.renderPlanList=()=>{};c.renderDuel=()=>{};
  vm.runInContext('globalThis.favoriteState=planLibraryUI',c);c.favoriteState.plans=plans;
  const buttons=['a','b'].map(id=>({dataset:{planFavorite:id},getAttribute:()=> 'false'}));
  c.bindPlanFavorites({querySelectorAll:()=>buttons});
  const calls=buttons.map(b=>b.onclick({stopPropagation(){}}));
  pending.b({plans:['a','b']});await calls[1];
  pending.a({plans:['a']});await calls[0];
  assert(plans.every(p=>p.favorite));assert(duel.result.matches.every(p=>p.favorite));
});
test('frozen field activation is recognized from native evidence, with costs and negation preserved',()=>{
  const c=setup('activation.js'),a={kind:'effect',id:'2:0',cards:[{code:1,instance_id:8}],status:'resolved',results:[]},r={catalog:{1:{type:0x80002}},events:[{id:a.id,engine_effect:{effect_type:0x1a}}]};
  const before=JSON.stringify({a,r});
  assert.equal(c.cardActivation(a,r),'发动场地魔法卡');assert.equal(c.activationResultMissing(a,r),false);
  assert.equal(JSON.stringify({a,r}),before);
  a.status='pending';assert(c.activationResultMissing(a,r));
  for(const status of ['negated','disabled']){a.status=status;assert.equal(c.activationResultMissing(a,r),false);}
  a.status='resolved';a.engine_effect={effect_type:0x82};assert.equal(c.cardActivation(a,r),null);assert(c.activationResultMissing(a,r));
});
test('old placement fallback needs matching physical card evidence and does not infer activation from field type alone',()=>{
  const c=setup('activation.js'),a={kind:'effect',id:'2:0',cards:[{code:1,instance_id:8}],evidence_refs:['1:0','2:0']},r={catalog:{1:{type:0x80002}},events:[{id:'1:0',message:50,cards:[{instance_id:8}],origin:{location:2},destination:{location:8,position:1}},{id:'2:0'}]};
  assert.equal(c.cardActivation(a,r),'发动场地魔法卡');r.events[0].cards[0].instance_id=9;assert.equal(c.cardActivation(a,r),null);
});

test('saved plan search finds cards from either route by name or exact code and keeps folder scope',()=>{
  const c=setup('plan-library.js');
  const plans=[{name:'方案 A',tags:[{id:'a',name:'转生炎兽'}],search_cards:[{code:14812471,name:'转生炎兽 烽火猞猁'}]},{name:'方案 B',tags:[],search_cards:[{code:10,name:'分支续展卡'}]}];
  assert.equal(c.filterPlans(plans,'猞猁').length,1);assert.equal(c.filterPlans(plans,'14812471').length,1);
  assert.equal(c.filterPlans(plans,'14812').length,0);assert.equal(c.filterPlans(plans,'分支续展').length,1);
  assert.equal(c.filterPlans(plans,'分支续展','a').length,0);assert.equal(c.filterPlans(plans,'不存在').length,0);
});
