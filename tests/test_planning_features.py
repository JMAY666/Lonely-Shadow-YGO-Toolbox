from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from plan_endboard import attach_terminal_marks, marked_terminal, marked_evaluation, satisfied_marked_terminal
from planning_cache import PlanningCache
from modular import Modular, RouteFrontier, empty_response_edge, route_signature, guide_block_reason
from modular_decisions import resource_rank, model
from duel_continuation import anchor_source, replay_anchor


def card(instance, code=10, zone=4, sequence=0):
    return dict(instance_id=instance, code=code, controller=0, location=zone, sequence=sequence, position=1)


class TerminalMarksTests(unittest.TestCase):
    def test_marked_goal_does_not_require_unmarked_incidental_cards(self):
        marked=card(1,10,16)
        edge=attach_terminal_marks({'edges':[{'terminal':True}]},{'final_state':{'cards':[marked,card(2,20)]},
            'annotations':{'final_marks':{'1':{'marked':True,'effects':{}}}}})['edges'][0]
        reached=satisfied_marked_terminal(edge,{'cards':[card(101,10,16),card(102,30)]})
        self.assertEqual(reached['terminal_mark_status'],'complete')
        self.assertEqual([t['card']['code'] for t in reached['terminal_targets']],[10])
        self.assertIsNone(satisfied_marked_terminal(edge,{'cards':[card(101,10,2)]}))
        self.assertIsNone(satisfied_marked_terminal({'terminal_marks':[]},{'cards':[card(101)]}))

    def test_only_explicit_marks_map_once_by_code_and_zone_not_source_instance_id(self):
        report = {'final_state': {'cards': [card(1), card(2), card(3, 11, 16), card(4, 12, 16)]},
                  'annotations': {'final_marks': {'1': {'marked': True, 'effects': {'1': {'note': 'one effect'}}},
                                                  '3': {'marked': True, 'effects': {}}}, 'cards': {'3': 'followup'}}}
        source = attach_terminal_marks({'edges': [{'terminal': True}]}, report)['edges'][0]
        result = marked_terminal(source, {'cards': [card(101, sequence=3), card(102), card(103, 11, 16), card(104, 12, 16)]})
        self.assertEqual([t['card']['instance_id'] for t in result['terminal_targets']], [102, 103])
        self.assertEqual(result['terminal_targets'][1]['note'], 'followup')
        self.assertEqual(marked_evaluation(result)['marked_cards'], 2)
        self.assertEqual(marked_evaluation(result)['marked_effects'], 1)
        self.assertEqual(report['annotations']['final_marks']['1']['effects']['1']['note'], 'one effect')

    def test_missing_marks_never_fall_back_to_all_board_grave_or_hand_cards(self):
        state = {'cards': [card(1), card(2, 11, 16), card(3, 12, 2)]}
        self.assertEqual(marked_terminal({}, state)['terminal_targets'], [])
        source = {'terminal_marks': [{'card': card(9), 'mark': {'marked': True}, 'note': ''}]}
        wrong_zone = marked_terminal(source, {'cards': [card(1, 10, 16)]})
        self.assertEqual(wrong_zone['terminal_mark_status'], 'partial')
        self.assertEqual(wrong_zone['terminal_targets'], [])
        self.assertEqual(resource_rank({'marked_cards': 1, 'marked_effects': 2, 'board': 99, 'hand': 99}), (1, 2))

    def test_duplicate_marks_need_distinct_instances_and_precise_mode_keeps_positions(self):
        source = {'terminal_marks': [{'card': card(i), 'mark': {'marked': True}, 'note': ''} for i in (1, 2)]}
        result = marked_terminal(source, {'cards': [card(4, sequence=2)]})
        self.assertEqual(len(result['terminal_targets']), 1)
        self.assertEqual(result['terminal_mark_status'], 'partial')
        self.assertEqual(marked_terminal(source, {'cards': [card(4, sequence=2)]}, True)['terminal_targets'], [])


class PlanningCacheTests(unittest.TestCase):
    def test_bounded_isolated_deep_copies_and_disposal(self):
        cache = PlanningCache(max_bytes=10000, max_entries=2)
        cache.put('probe', 'a', '1', {'cards': [1]})
        cached = cache.get('probe', 'a', '1'); cached['cards'].append(2)
        self.assertEqual(cache.get('probe', 'a', '1'), {'cards': [1]})
        self.assertIsNone(cache.get('probe', 'b', '1'))
        cache.put('probe', 'a', '2', {})
        cache.put('search', 'a', '3', {})
        self.assertIsNone(cache.get('probe', 'a', '1'))
        cache.discard('a', 'search'); self.assertIsNone(cache.get('search', 'a', '3'))
        cache.discard('a'); self.assertEqual(cache.bytes, 0)

    def search_fixture(self, complete=True):
        ctx = dict(forecast_meta={},precise=False,goal=[],preference='shortest',preference_version=1)
        state = dict(version=1,revision=0,player=0,running=True,answered=False,state={'cards': []})
        def candidate(name, steps, marks):
            return {'id': name, 'path': [name], 'steps': [{'edge': name}], 'remaining': steps, 'goal_met': True, 'conditional': False,
                    'evaluation': {'marked_cards': marks, 'marked_effects': 0}, 'robustness': {'status': 'unassessed', 'scenarios': []}}
        result = dict(seconds=2,complete=complete,limited=not complete,candidates=[candidate('short',1,1),candidate('large',5,3)])
        def compute(*args, **kwargs):
            value=deepcopy(result);Modular.rank(value['candidates'],ctx['preference']);return value
        fake = SimpleNamespace(search_lock=threading.RLock(), context=lambda sid: ctx, library=SimpleNamespace(sync=lambda: None),
            state=lambda sid: deepcopy(state), token=lambda s,c: [s['version'],s['revision'],fake.version,c['preference_version']],
            version='source1', planning_cache=PlanningCache(), _search=Mock(side_effect=compute),
            valid_token=lambda *a: True, rank=Modular.rank, audit=Mock())
        return fake,ctx,state

    def test_preference_and_refresh_recompute_but_identical_complete_search_can_reuse(self):
        fake,ctx,state=self.search_fixture()
        first=Modular.search(fake,'s');self.assertFalse(first['cache']['result_hit'])
        repeat=Modular.search(fake,'s');self.assertTrue(repeat['cache']['result_hit'])
        ctx.update(preference='largest',preference_version=2)
        second=Modular.search(fake,'s');self.assertFalse(second['cache']['result_hit'])
        self.assertEqual(second['candidates'][0]['remaining'],5);self.assertEqual(fake._search.call_count,2)
        repeated=Modular.search(fake,'s');self.assertEqual(repeated['candidates'][0]['token'][-1],2)
        refreshed=Modular.search(fake,'s',refresh=True);self.assertFalse(refreshed['cache']['result_hit']);self.assertEqual(fake._search.call_count,3)
        fake.version='source2';Modular.search(fake,'s');self.assertEqual(fake._search.call_count,4)
        state['_observations']=[{'index':0,'codes':[10]}];Modular.search(fake,'s');self.assertEqual(fake._search.call_count,5)
        state['revision']=1;Modular.search(fake,'s');self.assertEqual(fake._search.call_count,6)

    def test_a_budget_limited_single_answer_never_becomes_a_cached_final_answer(self):
        fake,ctx,state=self.search_fixture(complete=False)
        for preference in ('shortest','largest','balanced','shortest'):
            ctx['preference']=preference
            result=Modular.search(fake,'s')
            self.assertTrue(result['limited']);self.assertFalse(result['cache']['result_hit'])
        self.assertEqual(fake._search.call_count,4)
        self.assertFalse(fake.planning_cache.entries)

    def test_sources_take_turns_and_mixed_descendants_cannot_jump_ahead(self):
        queue=RouteFrontier()
        queue.append(('long',[1,2]));queue.append(('short',[1]));queue.append(('mixed',None))
        self.assertEqual(queue.popleft()[0],'long')
        queue.appendleft(('long-next',[2]))
        self.assertEqual(queue.popleft()[0],'short')
        queue.appendleft(('short-descendants',None))
        self.assertEqual(queue.popleft()[0],'long-next')
        self.assertEqual(queue.popleft()[0],'short-descendants')
        self.assertEqual(queue.popleft()[0],'mixed');self.assertFalse(queue)

    def test_only_an_empty_response_window_can_be_inserted_without_a_source_choice(self):
        raw='100000000000000000000000';prompt=model(raw,{'cards':[]})
        guide=[{'id':'recorded','source':{'plan':'plan'},'terminal':True}]
        edge=empty_response_edge(prompt,guide,raw)
        self.assertTrue(edge['automatic']);self.assertFalse(edge['terminal']);self.assertTrue(edge['_keep_guide'])
        self.assertEqual(edge['decision']['selection'],[{'kind':'pass'}])
        prompt['choices'].append({'semantic':{'kind':'activate'},'response':'00000000'})
        self.assertIsNone(empty_response_edge(prompt,guide,raw))

    def test_same_actions_for_multiple_goals_or_adaptive_positions_are_not_fake_extra_routes(self):
        decision={'message':18,'selection':[{'kind':'place','place':[0,4,0]}]}
        a={'steps':[{'decision':decision}], 'conditional':False,'terminal_goal_id':'a'}
        b=deepcopy(a);b['terminal_goal_id']='b';b['steps'][0]['decision']['selection'][0]['place'][2]=1
        self.assertEqual(route_signature(a,False),route_signature(b,False))
        self.assertNotEqual(route_signature(a,True),route_signature(b,True))

    def test_missing_deck_copy_explains_the_actual_zone_instead_of_claiming_no_route(self):
        edge={'decision':{'selection':[{'card':{'code':10,'controller':0,'location':1}}]}}
        current={'state':{'cards':[card(1,10,2)]}}
        reason=guide_block_reason(edge,current,{10:{'name':'测试卡'}})
        self.assertIn('卡组',reason);self.assertIn('当前可用 0',reason);self.assertIn('手卡',reason)
        current['_unknown_draws']=[1]
        self.assertIn('随机结果未确认',guide_block_reason(edge,current,{}))


class ContinuationAnchorTests(unittest.TestCase):
    def test_missing_resource_explains_the_prefix_failure_without_changing_progress(self):
        raw = (bytes([15,0,0,1,1,1]) + (20).to_bytes(4,'little') + bytes([0,1,0,0])).hex()
        state = {'raw':raw,'state':{'cards':[card(1,10,2),card(2,20,1)]}}
        fake = SimpleNamespace(state=lambda sid:state,store=SimpleNamespace(catalog=SimpleNamespace(cards={10:{'name':'测试补点'}})))
        source = {'edges':[{'decision':{'message':15,'player':0,'context':None,
            'selection':[{'kind':'card','card':{'code':10,'controller':0,'location':1}}]}}]}
        ctx = {'precise':False,'forecast_steps':[{'existing':True}]}; before = deepcopy(ctx)
        with self.assertRaisesRegex(ValueError,'测试补点.*卡组.*当前可用 0.*手卡.*原教程保留'):
            replay_anchor(fake,'test',ctx,source)
        self.assertEqual(ctx,before)

    def test_selected_step_uses_its_following_decision_boundary_and_fails_closed_for_old_records(self):
        report={'id':'plan','name':'source','edit_revision':3,'review':{'nodes':[
            {'id':'s8','number':8,'kind':'step','state_ref':18},{'id':'s9','number':9,'kind':'step','state_ref':29}]}}
        route={'id':'plan','unknown':[],'snapshots':[{'position':i,'seq':seq,'state':{},'player':0,'raw':'0b00'} for i,seq in enumerate([10,20,30,40])]}
        edges=[{'position':i,'source':{'route':'plan'}} for i in range(3)]
        fake=SimpleNamespace(read=lambda path:report,store=SimpleNamespace(plan_path=lambda x:x),
            library=SimpleNamespace(entries={'plan':{'version':'a','routes':[route]}},edges=lambda ids:edges))
        anchor={'plan':'plan','revision':3,'node':'s9','route':'main'}
        result=anchor_source(fake,anchor)
        self.assertEqual(result['target']['seq'],30)
        self.assertEqual([e['position'] for e in result['edges']],[0,1])
        self.assertEqual([g['number'] for g in result['layout']],[8,9])
        with self.assertRaisesRegex(ValueError,'已修改'):anchor_source(fake,{**anchor,'revision':2})
        report['review']['nodes'][1].pop('state_ref')
        with self.assertRaisesRegex(ValueError,'决策边界'):anchor_source(fake,anchor)


if __name__ == '__main__': unittest.main()
