"""State boundaries that protect confirmed progress and real expansions."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from duel_planner import route_context, confirm, projected, commit_projection, observe
from modular import Modular


class ForecastStateTests(unittest.TestCase):
    def setUp(self):
        self.ctx = {'forecast_meta': {'inputs': {}, 'catalog': {}, 'initial': {}}, 'forecast_steps': [],
                    'forecast_route': {'id': 'route', 'confirmed': 0,
                                       'candidate': {'steps': [{'path_end': 1}, {'path_end': 2}], 'path': ['a', 'b']},
                                       'base': {'revision': 0}, 'prefix': []}}
        self.modular = SimpleNamespace(sessions={'forecast': self.ctx}, store=SimpleNamespace(planning={'forecast'}),
                                       bridge=Mock(), audit=Mock(), public_result=lambda value: value)

    def test_stale_routes_and_forward_skips_never_change_progress(self):
        before = deepcopy(self.ctx['forecast_route'])
        for body in [{'id':'forecast','route':'old','index':0}, {'id':'forecast','route':'route','index':1},
                     {'id':'real-expansion','route':'route','index':0}]:
            with self.assertRaises(ValueError): route_context(self.modular, body)
        self.assertEqual(self.ctx['forecast_route'], before)
        self.modular.bridge.assert_not_called()

    def test_live_confirmation_records_source_and_rechecks_guard_after_engine_work(self):
        self.modular.bridge.return_value={'state':{'cards':[]},'raw':'0b00','player':0}
        body={'id':'forecast','route':'route','index':0,'through':1}
        guard=Mock(side_effect=ValueError('route changed'))
        with self.assertRaisesRegex(ValueError,'route changed'):
            confirm(self.modular,body,source='mdpro3-read-only',evidence={'event_through':42},guard=guard)
        self.assertEqual(self.ctx['forecast_route']['confirmed'],0)
        self.assertNotIn('forecast_state',self.ctx)
        confirm(self.modular,body,source='mdpro3-read-only',evidence={'event_through':42},guard=Mock())
        self.assertEqual(self.modular.audit.call_args.args[1],'live_confirmed_step')
        self.assertEqual(self.modular.audit.call_args.kwargs['source'],'mdpro3-read-only')
        self.assertEqual(self.ctx['forecast_route']['confirmed'],2)

    def test_interruption_is_applied_to_the_action_after_an_empty_response_acknowledgement(self):
        actor={'instance_id':1,'code':1,'controller':0,'location':4}
        self.ctx['forecast_route']['candidate']['steps']=[
            {'path_end':1,'automatic':True,'decision':{'selection':[{'kind':'pass'}]}},
            {'path_end':2,'decision':{'selection':[{'kind':'activate','card':{'code':1}}]},'bindings':[]}]
        before={'state':{'cards':[actor]},'raw':'0b00','player':0}
        after={'state':{'cards':[actor,{'instance_id':9,'code':10,'controller':1,'location':16}]},'raw':'0b00','player':0,'batches':[]}
        self.modular.store.catalog=SimpleNamespace(cards={10:{'extra':False}})
        self.modular.bridge.side_effect=[before,after]
        self.modular.search=Mock(return_value={'status':'found','candidates':[]})
        with patch('duel_planner.advance_facts',return_value={'facts':[{'code':1}]}):
            result=observe(self.modular,{'id':'forecast','route':'route','index':0,'through':1,'kind':'interruption','cards':[10]})
        self.assertEqual(self.modular.bridge.call_args_list[0].args[2],['a'])
        self.assertEqual(self.modular.bridge.call_args_list[1].args[2],['b'])
        self.assertEqual(result['confirmed'],2)

    def test_group_confirmation_requires_actual_random_outcomes(self):
        self.ctx['forecast_route']['candidate']['observation_required'] = [2, 2]
        with self.assertRaisesRegex(ValueError, '随机结果'):
            confirm(self.modular, {'id':'forecast','route':'route','index':0,'through':1})
        self.assertEqual(self.ctx['forecast_route']['confirmed'], 0)
        self.modular.bridge.assert_not_called()

    def test_group_confirmation_preserves_prefix_and_is_idempotent(self):
        self.modular.bridge.return_value = {'state':{'cards':[]},'raw':'0b00','player':0,'effects':{}}
        body = {'id':'forecast','route':'route','index':0,'through':1}
        first = confirm(self.modular, body); repeated = confirm(self.modular, body)
        self.assertEqual(first['confirmed'], 2); self.assertEqual(repeated['confirmed'], 2)
        self.modular.bridge.assert_called_once_with('forecast', {'revision':0}, ['a','b'])
        self.assertEqual(self.ctx['forecast_state']['_prefix'], ['a','b'])

    def test_projection_carries_replay_history_and_engine_restrictions(self):
        base = {'revision':3,'_prefix':['earlier'],'_observations':[{'index':0,'kind':0,'codes':[1]}]}
        following = {'state':{'cards':[],'normal_summons_used':[1,0],'normal_summon_limit':[1,1],
                             'extra_normal_summon_used':[True,False],'effect_usage':[{'used':1}]},
                     'raw':'0b00','player':0,'effects':{}}
        result = projected(base,following,['next'])
        self.assertEqual(result['_prefix'], ['earlier','next'])
        self.assertEqual(result['state']['normal_summons_used'], [1,0])
        self.assertEqual(result['state']['extra_normal_summon_used'], [True,False])
        self.assertEqual(result['state']['normal_summon_limit'], [1,1])
        self.assertEqual(result['_observations'], base['_observations'])
        self.assertEqual(base['revision'], 3)

    def test_distinct_confirmations_never_reuse_a_forecast_version(self):
        value = {'revision': 1}
        commit_projection(self.ctx, deepcopy(value)); first = self.ctx['forecast_state']['revision']
        commit_projection(self.ctx, deepcopy(value))
        self.assertGreater(self.ctx['forecast_state']['revision'], first)

    def test_forecasts_cannot_be_driven_by_live_execute_or_auto_apis(self):
        fake = SimpleNamespace(context=lambda sid: self.ctx)
        with self.assertRaisesRegex(ValueError, '临时方案'): Modular.automatic(fake, {'id':'forecast','enabled':True})
        with self.assertRaisesRegex(ValueError, '临时方案'): Modular.execute(fake, {'id':'forecast','candidate':'a'})
