"""Independent automatic-mode workspaces over the shared rules/plan services."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import re
import threading
import uuid

import deck_tags
from duel import validate_hand


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class AutomaticDuels:
    def __init__(self,store,read,write,now):
        self.store,self.read,self.write,self.now=store,read,write,now
        self.root=store.root/'automatic-contexts'
        self.lock=threading.RLock()
        self.contexts={}

    def validate_input(self,value):
        if not isinstance(value,dict):raise ValueError('缺少自动模式卡组快照，请返回卡组预览。')
        deck=deepcopy(value.get('deck'));self.store.validate(deck)
        name=value.get('name') or '自动捕捉卡组'
        if not isinstance(name,str) or len(name)>80:raise ValueError('卡组名称无效')
        selected=deck_tags.selection(value.get('tag_selection',deck_tags.empty_selection()),self.store.library.all_tags())
        return {'name':name,'deck':deck,'tag_selection':selected}

    def checked_input(self,value,submitted,hand):
        result=self.validate_input(value)
        if any(Counter(result['deck'][zone])!=Counter(submitted[zone]) for zone in ('main','extra','side')):
            raise ValueError('本局使用的卡组与已捕捉卡组不同，请重新获取卡组后再开始。')
        self.store.validate(submitted);validate_hand(submitted,len(hand),hand)
        result['deck']=deepcopy(submitted)
        return result

    def context(self,identifier,active=True):
        if not isinstance(identifier,str) or not re.fullmatch('[a-f0-9]{32}',identifier):raise ValueError('自动模式上下文无效')
        with self.lock:
            if identifier not in self.contexts:
                stored=self.read(self.root/(identifier+'.json'))
                if stored.get('revision')!=digest(stored.get('input')):raise ValueError('自动对局快照内容已变化，不能继续使用')
                self.contexts[identifier]=stored
            value=self.contexts[identifier]
            if active and value.get('closed'):raise ValueError('此自动对局工作区已结束，请重新确认本局起手。')
            return value

    def save(self,context):
        self.write(self.root/(context['id']+'.json'),context)

    def prepare(self,body):
        monitor=self.store.ygopro_order
        with monitor.lock:
            current=monitor.round
            if (body.get('monitor_id')!=monitor.monitor_id or not current or current['id']!=body.get('round_id')
                    or not current['confirmed'] or current['confirmed']['order']!='first'):
                raise ValueError('请先确认本局先攻与起手。')
            opening=current['opening']
            if not opening['confirmed'] or opening['snapshot_id']!=body.get('snapshot_id'):
                raise ValueError('起手快照尚未确认或已变化。')
            if not current.get('plan_input'):raise ValueError('本局缺少已核对的卡组快照，请重新确认起手。')
            inputs={**deepcopy(current['plan_input']), 'hand':list(opening['confirmed']['cards']),
                    'round_id':current['id'], 'snapshot_id':opening['snapshot_id'], 'turn_order':'first'}
        with self.lock:
            for context in self.contexts.values():
                if not context.get('closed') and context['input']==inputs:return self.public(context)
            context={'id':uuid.uuid4().hex,'schema':1,'created_ms':self.now(),'input':inputs,
                     'revision':digest(inputs),'planner_ids':[],'closed':False,'selected_plan':None}
            self.save(context);self.contexts[context['id']]=context
            return self.public(context)

    def public(self,context):
        return {'context_id':context['id'],'round_id':context['input']['round_id'],'snapshot_id':context['input']['snapshot_id'],
                'deck':self.deck(context['id']),'hand':list(context['input']['hand'])}

    def deck(self,identifier):
        context=self.context(identifier,active=False);data=deepcopy(context['input']);vocabulary=self.store.library.all_tags()
        return {'id':'automatic/'+identifier,'revision':context['revision'],'name':data['name'],'deck':data['deck'],
                'source':'automatic','representatives':[None]*3,'tag_selection':data['tag_selection'],
                'tag_names':{key:vocabulary[key]['name'] for key in data['tag_selection']['tag_ids'] if key in vocabulary}}

    def request(self,context,body,intent):
        data=context['input']
        return {**body,'consumer':'automatic-duel','automatic_context':context['id'],'intent':intent,
                'deck_id':'automatic/'+context['id'],'revision':context['revision'],
                'hand_count':len(data['hand']),'hand':list(data['hand'])}

    def match(self,body):
        context=self.context(body.get('context_id'))
        result=self.store.modular.dispatch(self.request(context,{},'match'))['result']
        for plan in result['matches']:
            plan['automatic_revision']=digest({key:value for key,value in plan.items() if key!='favorite'})
        return result

    def select(self,body):
        context=self.context(body.get('context_id'));result=self.match(body)
        plan=next((p for p in result['matches'] if p['id']==body.get('plan_id')),None)
        if not plan or plan['automatic_revision']!=body.get('revision'):
            raise ValueError('方案或匹配条件已变化，请刷新方案列表后重新选择。')
        with self.lock:
            self.context(context['id']);context['selected_plan']=deepcopy(plan);self.save(context)
        return plan

    def dispatch(self,body):
        intent=body.get('intent')
        if intent not in ('plan','plan-adopt','plan-confirm','plan-observe','plan-close','plan-prepare','plan-poll','plan-cancel'):
            raise ValueError('自动模式推演操作无效')
        with self.lock:
            context=self.context(body.get('context_id'));sid=body.get('id')
            if sid and sid not in context['planner_ids']:raise ValueError('临时方案不属于当前自动工作区')
            if not sid and intent not in ('plan','plan-prepare','plan-poll','plan-cancel'):raise ValueError('请先生成本局临时方案')
            request=self.request(context,body,intent)
        result=self.store.modular.dispatch(request)['result']
        result_sid=result.get('id')
        with self.lock:
            closed=context['closed']
            if not closed:
                if result_sid and result_sid not in context['planner_ids']:context['planner_ids'].append(result_sid)
                if intent=='plan-close':context['planner_ids']=[p for p in context['planner_ids'] if p!=sid]
                self.save(context)
        if closed:
            # A queued preparation may be created after close_owner ran, and
            # can return before it has a native session ID to close.
            self.store.modular.precompute.close_owner('automatic-duel', context['id'])
            if result_sid:self.store.modular.dispatch(self.request(context,{'id':result_sid},'plan-close'))
            raise ValueError('自动工作区已切换，迟到的推演已关闭。')
        return result

    def close(self,body):
        with self.lock:
            context=self.context(body.get('context_id'),active=False)
            context['closed']=True;context['closed_ms']=self.now();self.save(context)
            sessions=list(context['planner_ids'])
        self.store.modular.precompute.close_owner('automatic-duel', context['id'])
        for sid in sessions:
            if sid in self.store.planning:
                try:self.store.modular.dispatch(self.request(context,{'id':sid},'plan-close'))
                except ValueError:
                    if sid in self.store.planning:raise
        return {'closed':True}
