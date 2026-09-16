"""State boundaries that protect confirmed progress and real expansions."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from duel_planner import route_context, confirm, projected, commit_projection
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
        following = {'state':{'cards':[],'normal_summons_used':[1,0],'effect_usage':[{'used':1}]},
                     'raw':'0b00','player':0,'effects':{}}
        result = projected(base,following,['next'])
        self.assertEqual(result['_prefix'], ['earlier','next'])
        self.assertEqual(result['state']['normal_summons_used'], [1,0])
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
