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
test('frozen field activation is recognized from native evidence, with costs and negation preserved',()=>{
  const c=setup('activation.js'),a={kind:'effect',id:'2:0',cards:[{code:1,instance_id:8}],status:'resolved',results:[]},r={catalog:{1:{type:0x80002}},events:[{id:a.id,engine_effect:{effect_type:0x1a}}]};
  const before=JSON.stringify({a,r});
  assert.equal(c.cardActivation(a,r),'发动场地魔法卡');assert.equal(c.activationResultMissing(a,r),false);
  assert.equal(JSON.stringify({a,r}),before);
  for(const status of ['pending','negated','disabled']){a.status=status;assert(c.activationResultMissing(a,r));}
  a.status='resolved';a.engine_effect={effect_type:0x82};assert.equal(c.cardActivation(a,r),null);assert(c.activationResultMissing(a,r));
});
test('old placement fallback needs matching physical card evidence and does not infer activation from field type alone',()=>{
  const c=setup('activation.js'),a={kind:'effect',id:'2:0',cards:[{code:1,instance_id:8}],evidence_refs:['1:0','2:0']},r={catalog:{1:{type:0x80002}},events:[{id:'1:0',message:50,cards:[{instance_id:8}],origin:{location:2},destination:{location:8,position:1}},{id:'2:0'}]};
  assert.equal(c.cardActivation(a,r),'发动场地魔法卡');r.events[0].cards[0].instance_id=9;assert.equal(c.cardActivation(a,r),null);
});
