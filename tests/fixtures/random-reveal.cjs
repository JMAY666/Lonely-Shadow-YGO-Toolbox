'use strict';
// Public card text and invented event/instance IDs, never a user's route.
const catalog=require('./killer_tune_catalog.json');
module.exports=function randomRevealPlan() {
  const source={code:16387555,name:catalog['16387555'].name,instance_id:1,controller:0,location:16,position:5};
  const first={code:52155219,name:'示例翻牌甲',instance_id:2,controller:1,location:1,sequence:8};
  const second={code:56003780,name:'示例翻牌乙',instance_id:3,controller:1,location:1,sequence:7};
  const events=[{id:'10:0',message:70,cards:[source]},
    {id:'11:0',message:30,player:1,cards:[first,second]},
    {id:'12:0',message:50,cards:[first],origin:{controller:1,location:1},destination:{controller:1,location:32,position:5}},
    {id:'13:0',message:50,cards:[second],origin:{controller:1,location:1},destination:{controller:1,location:1,sequence:0},deck_operation:'move_to_bottom'},
    {id:'14:0',message:73,cards:[source],activation_ref:'10:0'}].map(e=>({...e,native_seq:Number(e.id.split(':')[0])}));
  const action={id:'10:0',activation_ref:'10:0',kind:'effect',status:'resolved',cards:[source],costs:[],targets:[],
    effect_number:2,effect_text:catalog['16387555'].desc,selected_effect_text:'②：'+catalog['16387555'].desc.split('②：')[1],effect_text_source:'audited_text_and_activation',
    results:events.slice(1,4).map(e=>({event_ref:e.id,message:e.message,cards:e.cards})),evidence_refs:events.map(e=>e.id)};
  const state={cards:[source,{...first,location:32,position:5},{...second,code:null,identity_known:false}],lp:[8000,8000]};
  return {id:'synthetic-random-reveal',name:'卡组顶部随机牌与效果说明验收',plan_stage:'deleted',status:'completed',events,actions:[action],
    catalog:structuredClone(catalog),initial_hand:[{...source,location:2}],initial_hand_ref:'1:0',final_state:state,final_state_ref:16,
    review:{nodes:[{id:'initial',kind:'initial',number:1,state_ref:1,state:{cards:[{...source,location:2}]},action_ids:[]},
      {id:'reveal',kind:'step',number:2,state_ref:15,state,action_ids:['10:0']},
      {id:'final',kind:'final',number:3,state_ref:16,state,action_ids:[]}]},
    annotations:{nodes:{},cards:{},effects:{},costs:{},final_marks:{},extra_conditions:[]},
    requirements:{opening:[],main:[],extra:[],random:[],uncertain:[]}};
};
