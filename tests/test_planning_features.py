from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from plan_endboard import attach_terminal_marks, marked_terminal, marked_evaluation
from planning_cache import PlanningCache
from modular import Modular
from modular_decisions import resource_rank
from duel_continuation import anchor_source


def card(instance, code=10, zone=4, sequence=0):
    return dict(instance_id=instance, code=code, controller=0, location=zone, sequence=sequence, position=1)


class TerminalMarksTests(unittest.TestCase):
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

    def test_preference_reranks_cached_candidates_but_sources_and_actual_states_recompute(self):
        ctx = dict(forecast_meta={},precise=False,goal=[],preference='shortest',preference_version=1)
        state = dict(version=1,revision=0,player=0,running=True,answered=False,state={'cards': []})
        def candidate(name, steps, marks):
            return {'id': name, 'steps': [{'edge': name}], 'remaining': steps, 'goal_met': True, 'conditional': False,
                    'evaluation': {'marked_cards': marks, 'marked_effects': 0}, 'robustness': {'status': 'unassessed', 'scenarios': []}}
        result = dict(seconds=2,candidates=[candidate('short',1,1),candidate('large',5,3)])
        fake = SimpleNamespace(search_lock=threading.RLock(), context=lambda sid: ctx, library=SimpleNamespace(sync=lambda: None),
            state=lambda sid: deepcopy(state), token=lambda s,c: [s['version'],s['revision'],fake.version,c['preference_version']],
            version='source1', planning_cache=PlanningCache(), _search=Mock(side_effect=lambda *a,**kw: deepcopy(result)),
            valid_token=lambda *a: True, rank=Modular.rank, audit=Mock())
        first=Modular.search(fake,'s');self.assertFalse(first['cache']['result_hit'])
        ctx.update(preference='largest',preference_version=2)
        second=Modular.search(fake,'s');self.assertTrue(second['cache']['result_hit'])
        self.assertEqual(second['candidates'][0]['remaining'],5);fake._search.assert_called_once()
        self.assertEqual(second['candidates'][0]['token'][-1],2)
        fake.version='source2';Modular.search(fake,'s');self.assertEqual(fake._search.call_count,2)
        state['_observations']=[{'index':0,'codes':[10]}];Modular.search(fake,'s');self.assertEqual(fake._search.call_count,3)
        state['revision']=1;Modular.search(fake,'s');self.assertEqual(fake._search.call_count,4)


class ContinuationAnchorTests(unittest.TestCase):
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
