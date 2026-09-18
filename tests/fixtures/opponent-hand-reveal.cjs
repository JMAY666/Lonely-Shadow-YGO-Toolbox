// Synthetic diagram fixture: no user deck, account or recorded session.
module.exports=function(){
  const card=(code,name,instance_id,controller,location,sequence=0)=>({code,name,instance_id,controller,location,sequence,position:1});
  const actor=card(42781164,'操作怪兽',1,0,4),rotary=card(17209452,'墓地效果怪兽',2,0,16);
  const spell=card(78058681,'检索魔法',3,0,2),field=card(14442329,'场地魔法',4,0,2);
  const hand=Array.from({length:5},(_,i)=>card(i===4?14558127:1184620,i===4?'灰流丽':'魔物狩人',20+i,1,2,i));
  const events=[
    {id:'10:0',message:70,chain:1,cards:[actor]}, {id:'11:0',message:72,chain:1,cards:[]},
    {id:'12:0',message:50,cards:[spell],origin:{controller:0,location:1},destination:{controller:0,location:2}},
    {id:'13:0',message:31,cards:[spell]}, {id:'14:0',message:73,chain:1,cards:[]}, {id:'15:0',message:74,cards:[]},
    {id:'20:0',message:70,chain:1,cards:[rotary]}, {id:'21:0',message:72,chain:1,cards:[]},
    {id:'22:0',message:31,cards:hand},
    {id:'23:0',message:50,cards:[field],origin:{controller:0,location:1},destination:{controller:0,location:2}},
    {id:'24:0',message:31,cards:[field]}, {id:'25:0',message:73,chain:1,cards:[]}, {id:'26:0',message:74,cards:[]},
    {id:'30:0',message:70,chain:1,cards:[{...field,location:8,sequence:5}]}
  ].map(e=>({...e,native_seq:Number(e.id.split(':')[0]),type:'合成展示事件'}));
  const effect=(id,cards,text,refs)=>({id,kind:'effect',activation_ref:id,cards,status:'resolved',costs:[],targets:[],effect_number:1,
    effect_text:text,selected_effect_text:text,effect_text_source:'single_numbered_clause',
    evidence_refs:[id,...refs],results:refs.map(ref=>{const e=events.find(e=>e.id===ref);return {event_ref:ref,message:e.message,cards:e.cards};})});
  const actions=[
    effect('10:0',[actor],'①：特殊召唤后检索一张魔法卡，并向对方展示所选卡牌。',['12:0','13:0']),
    effect('20:0',[rotary],'②：查看对方手牌，从卡组检索一张场地魔法，向对方展示后加入手牌。',['22:0','23:0','24:0']),
    effect('30:0',[{...field,location:8,sequence:5}],'发动场地魔法。',[])
  ];
  actions[1].effect_number=2;
  actions[2].engine_effect={effect_type:0x10};
  const state={cards:[actor,rotary,spell,field,...hand],lp:[8000,8000]};
  return {id:'synthetic-opponent-reveal',name:'长短步骤与随机手牌验收',status:'completed',plan_stage:'deleted',initial_hand:[spell],
    final_state:state,events,actions,catalog:{78058681:{name:'检索魔法',type:2},14442329:{name:'场地魔法',type:0x80002}},
    annotations:{nodes:{},cards:{},effects:{},final_marks:{}},branches:[],
    review:{nodes:[{id:'initial',kind:'initial',number:1,action_ids:[],state},
      {id:'long',kind:'step',number:5,action_ids:['10:0','20:0'],state,state_ref:26},
      {id:'short',kind:'step',number:6,action_ids:['30:0'],state,state_ref:30},
      {id:'final',kind:'final',number:7,action_ids:[],state}]}};
};
