import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json, now
from card_annotations import CardAnnotations, Registry, draft_entry, segments, digest, validate_entry, zone_matches

SEARCHER = '①：从卡组把1只「测试」怪兽加入手卡。'
RECYCLER = '①：以自己墓地1只「测试」怪兽为对象才能发动。那只怪兽加入手卡。'
DUAL = '这个卡名的①②的效果1回合各能使用1次。\n①：从卡组把1只怪兽特殊召唤。这个回合，自己不是怪兽不能特殊召唤。\n②：把对方场上1只怪兽破坏。'
PENDULUM = '「测试灵摆」的灵摆效果1回合只能使用1次。\n①：从卡组把1只「测试」怪兽加入手卡。\n【怪兽效果】\n①：把这张卡破坏，从卡组把1只怪兽特殊召唤。'
FLAVOR = '用于测试的通常怪兽，没有任何效果文本。'

CARDS = [
    (20000001, 2, 0, SEARCHER),
    (20000002, 2, 0, RECYCLER),
    (20000003, 0x21, 0x1d5, DUAL),
    (20000004, 0x1000021, 0xaf, PENDULUM),
    (20000005, 0x11, 0, FLAVOR),
]


def make_entry(code, desc, effects, **extra):
    return {'code': code,
            'text_digest': hashlib.sha256(desc.replace('\r\n', '\n').strip().encode()).hexdigest(),
            'review': {'status': 'reviewed', 'origin': 'manual', 'checked_on': '2026-09-24', 'basis': '测试标注'},
            'frozen_text': desc, 'effects': effects, 'relations': [], 'notes': [], **extra}


def simple_effect(key, number, tags, processing, usage=()):
    return {'key': key, 'kind': 'numbered', 'number': number, 'tags': list(tags),
            'structure': {'activation': {'timing': 'manual', 'zones': ['hand'], 'conditions': [], 'fast_effect': False},
                          'cost': [], 'targeting': [], 'processing': processing, 'usage': list(usage)},
            'notes': []}


def fixed_grant(effect_type, tags, processing, timing='end_phase', cost=(), usage=()):
    """An explicitly known future effect, separate from the effect granting it."""
    child = {'effect_type': effect_type, 'tags': list(tags),
             'structure': {'activation': {'timing': timing, 'zones': ['monster'],
                                          'conditions': ['取得此固定效果后满足其发动条件'],
                                          'fast_effect': effect_type == 'quick'},
                           'cost': list(cost), 'targeting': [], 'usage': list(usage),
                           'processing': deepcopy(processing)}}
    return {'action': 'grant_effect', 'selector': {'text': '取得以下固定效果'},
            'then': deepcopy(processing), 'granted_effect': child}


def granting_effect(grants, own_processing=(), own_tags=(), cost=()):
    tags = set(own_tags).union(*(set(grant['granted_effect']['tags']) for grant in grants))
    effect = simple_effect('m1', 1, sorted(tags), [*own_processing, *grants])
    effect['effect_type'] = 'spell_activation'
    effect['own_tags'] = list(own_tags)
    effect['structure']['cost'] = list(cost)
    return effect


class CardAnnotationTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / '.local/test-runs'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.root = Path(self.temp.name)
        (self.root / 'script').mkdir()
        with closing(sqlite3.connect(self.root / 'cards.cdb')) as db:
            db.execute('CREATE TABLE datas(id INTEGER PRIMARY KEY, ot INTEGER, alias INTEGER, setcode INTEGER, type INTEGER, atk INTEGER, def INTEGER, level INTEGER, race INTEGER, attribute INTEGER, category INTEGER)')
            db.execute('CREATE TABLE texts(id INTEGER PRIMARY KEY, name TEXT, desc TEXT, str1 TEXT, str2 TEXT, str3 TEXT, str4 TEXT, str5 TEXT, str6 TEXT, str7 TEXT, str8 TEXT, str9 TEXT, str10 TEXT, str11 TEXT, str12 TEXT, str13 TEXT, str14 TEXT, str15 TEXT, str16 TEXT)')
            for code, card_type, setcode, desc in CARDS:
                db.execute('INSERT INTO datas VALUES(?,?,?,?,?,0,0,1,1,1,0)', (code, 0, 0, setcode, card_type))
                db.execute('INSERT INTO texts(id,name,desc) VALUES(?,?,?)', (code, f'测试卡{code}', desc))
            db.commit()
        self.store = Store(self.root)
        self.curated_path = self.root / 'curated-annotations.json'
        self.write_curated()
        self.service = CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)

    def tearDown(self):
        assert self.root.resolve().is_relative_to(Path(__file__).resolve().parents[1] / '.local/test-runs')
        self.temp.cleanup()

    def write_curated(self, mutate=None):
        entries = {
            '20000001': make_entry(20000001, SEARCHER, [
                simple_effect('m1', 1, ['etag:add-hand'],
                              [{'action': 'add_hand', 'count': '1', 'from_zones': ['deck'], 'to_zones': ['hand'],
                                'selector': {'text': '1只「测试」怪兽'}}])]),
            '20000002': make_entry(20000002, RECYCLER, [
                simple_effect('m1', 1, ['etag:add-hand'],
                              [{'action': 'add_hand', 'count': '1', 'from_zones': ['grave'], 'to_zones': ['hand'],
                                'selector': {'text': '对象怪兽'}}])]),
            '20000003': make_entry(20000003, DUAL, [
                {'key': 'm-pre', 'kind': 'unnumbered', 'number': None, 'tags': [], 'structure': {}, 'notes': []},
                simple_effect('m1', 1, ['etag:special-summon', 'etag:lock'],
                              [{'action': 'special_summon', 'count': '1', 'from_zones': ['deck'], 'to_zones': ['monster'],
                                'selector': {'text': '1只怪兽'},
                                'restrictions': ['这个回合，自己不是怪兽不能特殊召唤']}], ['per_effect_name_soft_opt']),
                simple_effect('m2', 2, ['etag:destroy'],
                              [{'action': 'destroy', 'count': '1', 'selector': {'text': '对方场上1只怪兽'}}],
                              ['per_effect_name_soft_opt'])],
                relations=[{'kind': 'usage_limit_group', 'effects': ['m1', 'm2'], 'text': '这个卡名的①②的效果1回合各能使用1次。'}]),
            '20000005': make_entry(20000005, FLAVOR, [], no_effect=True),
        }
        if mutate: mutate(entries)
        document = {'version': 1, 'id': 'test-annotations', 'title': '测试标注', 'checked_on': '2026-09-24',
                    'verified_against': {}, 'cards': entries}
        self.curated_path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')

    def test_segments_cover_pre_numbered_pendulum_and_ambiguous(self):
        self.assertEqual([s['key'] for s in segments(DUAL, 0x21)], ['m-pre', 'm1', 'm2'])
        pendulum = segments(PENDULUM, 0x1000021)
        self.assertEqual([s['key'] for s in pendulum], ['p-pre', 'p1', 'm1'])
        self.assertEqual([s['block'] for s in pendulum], ['p', 'p', 'm'])
        self.assertEqual([s['key'] for s in segments(FLAVOR, 0x11)], ['m-all'])
        ambiguous = segments('①：效果。①：重复编号。', 0x21)
        self.assertEqual([s['kind'] for s in ambiguous], ['ambiguous'])

    def test_same_tag_keeps_source_zone_difference(self):
        by_deck = self.service.search({'etags': ['etag:add-hand'], 'from_zone': 'deck'})
        by_grave = self.service.search({'etags': ['etag:add-hand'], 'from_zone': 'grave'})
        self.assertEqual([c['code'] for c in by_deck['cards']], [20000001])
        self.assertEqual([c['code'] for c in by_grave['cards']], [20000002])
        both = self.service.search({'etags': ['etag:add-hand']})
        self.assertEqual(both['total'], 2)
        evidence = both['cards'][0]['hits'][0]['evidence']
        self.assertTrue(any(item['condition'] == 'tag' for item in evidence))

    def test_conditions_do_not_cross_effects(self):
        strict = self.service.search({'etags': ['etag:special-summon', 'etag:destroy'], 'etag_mode': 'all'})
        self.assertEqual(strict['total'], 0)
        loose = self.service.search({'etags': ['etag:special-summon', 'etag:destroy'], 'etag_mode': 'all', 'scope': 'card'})
        self.assertEqual(loose['total'], 1)
        self.assertTrue(loose['cards'][0]['cross_effects'])
        self.assertEqual(sorted(loose['cards'][0]['hit_keys']), ['m1', 'm2'])

    def test_action_and_zones_do_not_mix_sequential_processing_items(self):
        effect = simple_effect('m1', 1, ['etag:banish', 'etag:add-hand'], [
            {'action': 'banish', 'from_zones': ['deck'], 'to_zones': ['banished'], 'then': [
                {'action': 'add_hand', 'from_zones': ['banished'], 'to_zones': ['hand'],
                 'timing': '第二次自己的准备阶段'}]}])
        self.install_grant_effect(effect)
        for scope in ('effect', 'card'):
            for conditions in (
                {'action': 'add_hand', 'from_zone': 'deck'},
                {'action': 'banish', 'to_zone': 'hand'},
                {'from_zone': 'deck', 'to_zone': 'hand'},
            ):
                with self.subTest(scope=scope, conditions=conditions):
                    self.assertEqual(self.service.search({'q': '20000001', 'scope': scope, **conditions})['total'], 0)
            result = self.service.search({'q': '20000001', 'scope': scope, 'action': 'add_hand',
                                          'from_zone': 'banished', 'to_zone': 'hand'})
            self.assertEqual(result['total'], 1)
            evidence = result['cards'][0]['hits'][0]['evidence']
            self.assertEqual({item['condition'] for item in evidence}, {'action', 'from_zone', 'to_zone'})
            self.assertEqual(len({item['processing_path'] for item in evidence}), 1)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'add_hand'})['total'], 1)

    def test_processing_match_searches_all_branches_and_keeps_implicit_destination(self):
        effect = simple_effect('m1', 1, ['etag:add-hand', 'etag:destroy'], [
            {'action': 'choose_branch', 'branches': [
                {'condition': '回收墓地', 'actions': [{'action': 'add_hand', 'from_zones': ['grave']}]},
                {'condition': '回收除外', 'actions': [{'action': 'add_hand', 'from_zones': ['banished']}]},
                {'condition': '破坏', 'actions': [{'action': 'destroy', 'from_zones': ['opponent_monster']}]}]}])
        self.install_grant_effect(effect)
        found = self.service.search({'q': '20000001', 'action': 'add_hand', 'from_zone': 'banished', 'to_zone': 'hand'})
        self.assertEqual(found['total'], 1)
        evidence = found['cards'][0]['hits'][0]['evidence']
        self.assertTrue(any('隐含去向' in item['basis'] for item in evidence))
        self.assertEqual(len({item['processing_path'] for item in evidence}), 1)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'add_hand', 'from_zone': 'opponent_monster'})['total'], 0)

    def test_card_scope_keeps_movement_atomic_but_allows_other_effect_conditions(self):
        def mutate(entries):
            entry = entries['20000003']
            entry['effects'][1]['structure']['processing'] = [{'action': 'add_hand', 'from_zones': ['grave']}]
            entry['effects'][1]['tags'] = ['etag:add-hand']
            entry['effects'][2]['structure']['processing'] = [{'action': 'destroy', 'from_zones': ['opponent_monster']}]
        self.write_curated(mutate)
        self.service.reload()
        self.assertEqual(self.service.search({'q': '20000003', 'scope': 'card', 'action': 'add_hand',
                                              'from_zone': 'opponent_monster'})['total'], 0)
        result = self.service.search({'q': '20000003', 'scope': 'card', 'action': 'add_hand',
                                      'from_zone': 'grave', 'etags': ['etag:destroy']})
        self.assertEqual(result['total'], 1)
        self.assertTrue(result['cards'][0]['cross_effects'])

    def test_random_result_and_replacement_actions_require_their_distinct_contracts(self):
        samples = {
            'toss_coin': {'count': 1, 'executor': 'self', 'branches': [
                {'condition': '表', 'actions': [{'action': 'draw', 'from_zones': ['deck']}]},
                {'condition': '里', 'actions': [{'action': 'draw', 'from_zones': ['opponent_deck']}]}]},
            'roll_dice': {'rolls': 2, 'faces': 6, 'executor': 'self', 'result': 'sum',
                          'then': [{'action': 'destroy', 'from_zones': ['monster']}]},
            'add_to_extra_faceup': {'count': 1, 'from_zones': ['deck'], 'to_zones': ['extra_faceup'],
                                    'shuffle_source_after': True},
            'set_lp': {'recipient': 'both', 'amount': 3000},
            'replace_draw_with_discard': {'source_activation': 'draw_only_effect',
                'quantity': 'cards_that_would_be_drawn', 'reveal_to': 'both', 'counts_as_draw': False,
                'cards_enter_hand': False, 'from_zones': ['deck_top'], 'to_zones': ['grave']},
            'redirect_effect_damage': {'source_player': 'opponent', 'recipient': 'opponent',
                                       'source_effect': 'activated', 'duration': '本回合'},
            'place_deck_bottom': {'executor': 'self', 'count': 1, 'from_zones': ['deck'],
                                  'to_zones': ['deck_bottom'], 'shuffle_before_placement': True},
        }
        def entry_for(action):
            tags = {'toss_coin': ['etag:draw'], 'roll_dice': ['etag:destroy'],
                    'place_deck_bottom': ['etag:deck-look']}.get(action, [])
            item = {'action': action, 'selector': {'text': '已核实的测试处理'}, **deepcopy(samples[action])}
            return make_entry(20000001, SEARCHER, [simple_effect('m1', 1, tags, [item])])
        for action in samples:
            with self.subTest(valid=action):
                validate_entry(entry_for(action), self.service.registry, {'m1'}, card_type=2)
        invalid = [
            ('toss_coin', 'count', True), ('toss_coin', 'count', 0), ('toss_coin', 'executor', 'unknown'),
            ('toss_coin', 'branches', []), ('toss_coin', 'branches', 2),
            ('toss_coin', 'branches', [{'condition': '表', 'actions': []}, {'condition': '里', 'actions': []}]),
            ('roll_dice', 'rolls', -1), ('roll_dice', 'faces', 20), ('roll_dice', 'faces', True),
            ('roll_dice', 'result', ''), ('roll_dice', 'then', []),
            ('add_to_extra_faceup', 'to_zones', ['hand']), ('add_to_extra_faceup', 'from_zones', []),
            ('add_to_extra_faceup', 'count', '1'), ('add_to_extra_faceup', 'shuffle_source_after', 'yes'),
            ('set_lp', 'amount', -3000), ('set_lp', 'amount', True), ('set_lp', 'recipient', 'card'),
            ('replace_draw_with_discard', 'source_activation', 'any_effect'),
            ('replace_draw_with_discard', 'counts_as_draw', True),
            ('replace_draw_with_discard', 'cards_enter_hand', True),
            ('replace_draw_with_discard', 'reveal_to', 'self'),
            ('replace_draw_with_discard', 'from_zones', ['hand']),
            ('replace_draw_with_discard', 'to_zones', ['hand']),
            ('redirect_effect_damage', 'source_effect', 'battle'),
            ('redirect_effect_damage', 'duration', ''),
            ('place_deck_bottom', 'to_zones', ['deck_top']),
            ('place_deck_bottom', 'shuffle_before_placement', 'yes'),
        ]
        for action, field, value in invalid:
            with self.subTest(action=action, field=field, value=value):
                entry = entry_for(action)
                entry['effects'][0]['structure']['processing'][0][field] = value
                with self.assertRaises(ValueError):
                    validate_entry(entry, self.service.registry, {'m1'}, card_type=2)

    def test_random_branches_preserve_player_source_and_replacement_is_not_draw(self):
        effect = simple_effect('m1', 1, ['etag:draw'], [
            {'action': 'toss_coin', 'selector': {'text': '结算时掷一次'}, 'count': 1, 'executor': 'self',
             'branches': [
                 {'condition': '表', 'actions': [{'action': 'draw', 'from_zones': ['deck'], 'to_zones': ['hand']}]},
                 {'condition': '里', 'actions': [{'action': 'draw', 'from_zones': ['opponent_deck'], 'to_zones': ['opponent_hand']}]}]}])
        self.install_grant_effect(effect)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'draw', 'from_zone': 'opponent_deck',
                                              'to_zone': 'opponent_hand'})['total'], 1)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'draw', 'from_zone': 'deck',
                                              'to_zone': 'opponent_hand'})['total'], 0)
        replacement = {'action': 'replace_draw_with_discard', 'selector': {'text': '原应抽卡直接丢墓'},
                       'source_activation': 'draw_only_effect', 'quantity': 'cards_that_would_be_drawn',
                       'reveal_to': 'both', 'counts_as_draw': False, 'cards_enter_hand': False,
                       'from_zones': ['deck_top'], 'to_zones': ['grave']}
        self.install_grant_effect(simple_effect('m1', 1, [], [replacement]))
        for action in ('draw', 'discard_hand', 'negate_effect'):
            self.assertEqual(self.service.search({'q': '20000001', 'action': action})['total'], 0)

    def test_whole_turn_skip_lp_swap_and_lock_qualifiers_have_explicit_parameters(self):
        skip = {'action': 'skip_turn', 'selector': {'text': '跳过对方下回合'}, 'player': 'opponent',
                'duration': '下次对方回合', 'count': 1, 'stacking': 'non_cumulative'}
        swap = {'action': 'swap_lp', 'selector': {'text': '双方当前基本分互换'}, 'players': ['self', 'opponent']}
        for item in (skip, swap):
            entry = make_entry(20000001, SEARCHER, [simple_effect('m1', 1, [], [deepcopy(item)])])
            validate_entry(entry, self.service.registry, {'m1'}, card_type=2)
        for sample, field, value in (
            (skip, 'count', 0), (skip, 'count', True), (skip, 'player', 'card'),
            (skip, 'duration', ''), (skip, 'stacking', 'unknown'),
            (swap, 'players', ['self', 'self']), (swap, 'players', ['self']),
            (swap, 'players', [[], {}]), (swap, 'players', 'both'),
        ):
            with self.subTest(field=field, value=value):
                item = deepcopy(sample); item[field] = value
                with self.assertRaises(ValueError):
                    validate_entry(make_entry(20000001, SEARCHER, [simple_effect('m1', 1, [], [item])]),
                                   self.service.registry, {'m1'}, card_type=2)
        for qualifier in ('self_only', 'summon_response_only'):
            for value in (0, 1, 'false', None):
                with self.subTest(qualifier=qualifier, value=value):
                    effect = simple_effect('m1', 1, ['etag:lock'], [{'action': 'lock', qualifier: value}])
                    with self.assertRaises(ValueError):
                        validate_entry(make_entry(20000001, SEARCHER, [effect]), self.service.registry, {'m1'})

    def test_misspelled_target_range_fields_cannot_silently_render_as_fixed_one(self):
        for target in (
            {'count': 1, 'count_min': 1, 'count_max': 2, 'filter': '1至2张对象'},
            {'count_min': 1, 'count_max': 5, 'filter': '1至5张对象'},
            {'min_count': 1, 'max_count': 2, 'count_max': 2, 'filter': '新旧字段混用'},
        ):
            with self.subTest(target=target):
                effect = simple_effect('m1', 1, [], [])
                effect['structure']['targeting'] = [target]
                with self.assertRaisesRegex(ValueError, 'count_min/count_max'):
                    validate_entry(make_entry(20000001, SEARCHER, [effect]), self.service.registry, {'m1'})

    def test_attribute_equip_target_and_shuffle_contracts_do_not_imply_other_actions(self):
        samples = {
            'change_attribute': ({'from_zones': ['monster'], 'count': 1,
                                  'attribute_selection': 'resolution', 'duration': '表侧存在期间'}, ['etag:stat-change']),
            'change_equip_target': ({'from_zones': ['field'], 'count': 'all', 'keeps_controller': True}, []),
            'shuffle_deck': ({'from_zones': ['deck'], 'executor': 'self'}, ['etag:deck-look']),
        }
        def entry_for(action):
            fields, tags = samples[action]
            effect = simple_effect('m1', 1, tags, [
                {'action': action, 'selector': {'text': '经来源核实的处理'}, **deepcopy(fields)}])
            effect['effect_type'] = 'spell_activation'
            return make_entry(20000001, SEARCHER, [effect])
        for action in samples:
            validate_entry(entry_for(action), self.service.registry, {'m1'}, card_type=2)
        for action, field, value in (
            ('change_attribute', 'attribute_selection', 'any_time'), ('change_attribute', 'attribute', 'light'),
            ('change_attribute', 'count', True), ('change_attribute', 'duration', ''),
            ('change_equip_target', 'from_zones', ['hand']), ('change_equip_target', 'keeps_controller', False),
            ('change_equip_target', 'to_zones', ['spell']), ('change_equip_target', 'count', 0),
            ('shuffle_deck', 'from_zones', ['grave']), ('shuffle_deck', 'from_zones', ['deck_top']),
            ('shuffle_deck', 'executor', 'card'), ('shuffle_deck', 'to_zones', ['deck']),
            ('shuffle_deck', 'count', 1),
        ):
            with self.subTest(action=action, field=field, value=value):
                entry = entry_for(action); entry['effects'][0]['structure']['processing'][0][field] = value
                with self.assertRaises(ValueError): validate_entry(entry, self.service.registry, {'m1'}, card_type=2)
        for action in ('change_attribute', 'shuffle_deck'):
            entry = entry_for(action); entry['effects'][0]['tags'] = []
            with self.assertRaises(ValueError): validate_entry(entry, self.service.registry, {'m1'}, card_type=2)
        fixed = entry_for('change_attribute')
        fixed['effects'][0]['structure']['processing'][0].update(attribute_selection='fixed', attribute='water')
        validate_entry(fixed, self.service.registry, {'m1'}, card_type=2)
        self.write_curated(lambda entries: entries.update({'20000001': entry_for('shuffle_deck')}))
        self.service.reload()
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'shuffle_deck'})['total'], 1)
        for action in ('deck_reveal', 'return_deck', 'draw'):
            self.assertEqual(self.service.search({'q': '20000001', 'action': action})['total'], 0)

    def test_unknown_cards_are_not_negatives(self):
        result = self.service.search({'etags': ['etag:add-hand']})
        self.assertEqual(result['catalog_total'], len(CARDS))
        self.assertEqual(result['annotated_total'], 4)  # 20000004 stays unannotated, never returned.
        self.assertNotIn(20000004, [card['code'] for card in result['cards']])
        only_none = self.service.search({'etags': ['etag:add-hand'], 'status': ['none']})
        self.assertEqual(only_none['total'], 0)

    def test_trap_semantic_actions_reject_wrong_players_events_and_damage_kinds(self):
        samples = [
            {'action':'reverse_coin_effect','from_zones':['monster'],'count':1,'mode':'swap_current_heads_tails_effects',
             'requires_actual_coin_effect':True,'new_coin_toss':False},
            {'action':'require_player_send_grave','players':['self','opponent'],'from_zones':['monster','opponent_monster'],
             'to_zones':['grave','opponent_grave'],'remaining_rule':'one_attribute_per_player','selection_order':'turn_player_first',
             'simultaneous':True,'is_effect_movement':False,'respects_monster_immunity':False,'destination_rule':'each_sent_cards_owner_grave'},
            {'action':'replace_damage_with_recovery','recipient':'self','source_effect':'directly_chained_opponent_effect',
             'applies_at':'source_effect_resolution','preserves_other_processing':True},
            {'action':'perform_battle_damage_calculation','from_zones':['opponent_monster'],
             'attacker_rule':'second_direct_attacker_this_battle_phase','defender_rule':'first_direct_attacker_this_battle_phase',
             'requires_distinct_instances':True,'is_effect_damage':False},
        ]
        for item in samples:
            validate_entry(self.rule_action_entry(item, []),self.service.registry,card_type=2)
        changes = [
            (0,'count',True),(0,'count',2),(0,'mode','reroll'),(0,'requires_actual_coin_effect',False),(0,'new_coin_toss',True),
            (1,'players',['opponent','opponent']),(1,'players',[{},[]]),(1,'players',[]),(1,'to_zones',['grave']),
            (1,'selection_order','any'),(1,'is_effect_movement',True),(1,'respects_monster_immunity',True),(1,'count',1),
            (2,'recipient','opponent'),(2,'applies_at','activation'),(2,'preserves_other_processing',False),(2,'amount',2000),
            (3,'attacker_rule','any_attacker'),(3,'requires_distinct_instances',False),(3,'is_effect_damage',True),(3,'to_zones',['grave']),
        ]
        for index,field,value in changes:
            with self.subTest(index=index,field=field,value=value):
                item=deepcopy(samples[index]);item[field]=value
                with self.assertRaises(ValueError):validate_entry(self.rule_action_entry(item,[]),self.service.registry,card_type=2)
        for index in (0,2,3):
            for tag in ('etag:draw','etag:effect-damage','etag:recover-lp'):
                with self.assertRaisesRegex(ValueError,'TAG 与处理'):
                    validate_entry(self.rule_action_entry(samples[index],[tag]),self.service.registry,card_type=2)

    def test_dynamic_lp_rule_is_not_fixed_amount_damage_or_recovery(self):
        action={'action':'set_lp','recipient':'self','amount_rule':{'text':'处理时对方LP减1000','evaluated_at':'resolution'}}
        entry=self.rule_action_entry(action,[])
        validate_entry(entry,self.service.registry,card_type=2)
        for changes in ({'amount':3000},{'amount_rule':None},{'amount_rule':{}},
                        {'amount_rule':{'text':'','evaluated_at':'resolution'}},
                        {'amount_rule':{'text':'对方LP减1000','evaluated_at':'activation'}},
                        {'amount_rule':{'text':'对方LP减1000','evaluated_at':'resolution','expression':'evaluate()'}}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):validate_entry(self.rule_action_entry({**action,**changes},[]),self.service.registry,card_type=2)
        self.write_curated(lambda entries:entries.update({'20000001':entry}));self.service.reload()
        self.assertEqual(self.service.search({'q':'20000001','action':'set_lp'})['total'],1)
        for tag in ('etag:effect-damage','etag:recover-lp'):
            self.assertEqual(self.service.search({'q':'20000001','etags':[tag]})['total'],0)
        fixed={**action,'amount':0};del fixed['amount_rule']
        validate_entry(self.rule_action_entry(fixed,[]),self.service.registry,card_type=2)

    def test_opponent_banished_queries_do_not_borrow_another_players_destination(self):
        item={'action':'special_summon','from_zones':['opponent_banished'],'to_zones':['opponent_monster'],'count':1}
        entry=self.rule_action_entry(item,['etag:special-summon'])
        self.write_curated(lambda entries:entries.update({'20000001':entry}));self.service.reload()
        self.assertEqual(self.service.search({'q':'20000001','action':'special_summon','from_zone':'opponent_banished','to_zone':'opponent_monster'})['total'],1)
        self.assertEqual(self.service.search({'q':'20000001','action':'special_summon','from_zone':'banished','to_zone':'opponent_monster'})['total'],0)
        effect=entry['effects'][0];effect['structure']['processing']=[{'action':'destroy'}];effect['tags']=['etag:destroy']
        effect['structure']['cost']=[{'kind':'return_hand_cost','text':'把自己场上1只怪兽返回持有者手卡'}]
        self.write_curated(lambda entries:entries.update({'20000001':entry}));self.service.reload()
        self.assertEqual(self.service.search({'q':'20000001','cost_kind':'return_hand_cost'})['total'],1)
        self.assertEqual(self.service.search({'q':'20000001','action':'return_hand'})['total'],0)

    def test_attack_return_is_a_procedure_not_an_effect_return_or_activation_cost(self):
        item = {'action': 'require_attack_return', 'selector': {'text': '攻击宣言须返回其它卡'},
                'from_zones': ['field'], 'to_zones': ['hand', 'opponent_hand'], 'count': 1,
                'executor': 'self', 'exclude_source_instance': True, 'payment_timing': 'attack_declaration',
                'is_effect_movement': False}
        entry = self.rule_action_entry(item, [])
        entry['effects'][0]['effect_type'] = 'continuous'
        validate_entry(entry, self.service.registry, card_type=33)
        self.write_curated(lambda entries: entries.update({'20000001': entry}))
        self.service.reload()
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'require_attack_return'})['total'], 1)
        for query in ({'action': 'return_hand'}, {'etags': ['etag:add-hand']}, {'cost_kind': 'return_deck'}):
            self.assertEqual(self.service.search({'q': '20000001', **query})['total'], 0)
        for field, value in (('count', True), ('count', 2), ('from_zones', ['grave']),
                             ('to_zones', ['extra']), ('executor', 'opponent'),
                             ('exclude_source_instance', False), ('payment_timing', 'activation'),
                             ('is_effect_movement', True)):
            with self.subTest(field=field, value=value):
                broken = deepcopy(entry)
                broken['effects'][0]['structure']['processing'][0][field] = value
                with self.assertRaises(ValueError): validate_entry(broken, self.service.registry, card_type=33)
        with self.assertRaisesRegex(ValueError, 'TAG 与处理'):
            validate_entry(self.rule_action_entry(item, ['etag:add-hand']), self.service.registry, card_type=33)

    def test_event_damage_recipient_is_preserved_without_inventing_a_fixed_player(self):
        item = {'action': 'burn', 'amount': 1000, 'recipient_rule': '战斗破坏本卡的玩家'}
        entry = self.rule_action_entry(item, ['etag:effect-damage'])
        entry['effects'][0]['effect_type'] = 'trigger'
        validate_entry(entry, self.service.registry, card_type=33)
        self.write_curated(lambda entries: entries.update({'20000001': entry}))
        self.service.reload()
        shown = self.service.view(20000001)['effects'][0]['structure']['processing'][0]
        self.assertEqual(shown['recipient_rule'], '战斗破坏本卡的玩家')
        self.assertNotIn('recipient', shown)
        for value in ('', None, True, []):
            broken = deepcopy(entry)
            broken['effects'][0]['structure']['processing'][0]['recipient_rule'] = value
            with self.assertRaises(ValueError): validate_entry(broken, self.service.registry, card_type=33)
        broken = deepcopy(entry)
        broken['effects'][0]['structure']['processing'][0]['recipient'] = 'opponent'
        with self.assertRaisesRegex(ValueError, '固定recipient'):
            validate_entry(broken, self.service.registry, card_type=33)

    def test_battle_damage_conversion_is_effect_damage_but_not_fixed_burn(self):
        item = {'action': 'convert_battle_damage', 'selector': {'text': '将本卡战斗伤害当作效果伤害'},
                'from_zones': ['monster'], 'count': 1, 'source_damage': 'battle', 'result_damage': 'effect',
                'damage_source': 'this_card', 'recipient': 'opponent', 'creates_chain': False}
        entry = self.rule_action_entry(item, ['etag:effect-damage', 'etag:damage-modify'])
        entry['effects'][0]['effect_type'] = 'continuous'
        validate_entry(entry, self.service.registry, card_type=33)
        self.write_curated(lambda entries: entries.update({'20000001': entry}))
        self.service.reload()
        self.assertEqual(self.service.search({'q': '20000001', 'etags': ['etag:effect-damage']})['total'], 1)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'convert_battle_damage'})['total'], 1)
        for action in ('burn', 'destroy', 'grant_extra_attack'):
            self.assertEqual(self.service.search({'q': '20000001', 'action': action})['total'], 0)
        for field, value in (('count', False), ('count', 2), ('amount', 1000), ('source_damage', 'effect'),
                             ('result_damage', 'battle'), ('recipient', 'self'), ('damage_source', 'any_card'),
                             ('creates_chain', True), ('from_zones', ['grave']), ('to_zones', ['hand'])):
            with self.subTest(field=field, value=value):
                broken = deepcopy(entry)
                broken['effects'][0]['structure']['processing'][0][field] = value
                with self.assertRaises(ValueError): validate_entry(broken, self.service.registry, card_type=33)
        with self.assertRaisesRegex(ValueError, 'TAG 与处理'):
            validate_entry(self.rule_action_entry(item, []), self.service.registry, card_type=33)

    def test_new_branch_and_material_actions_require_complete_structure(self):
        registry = self.service.registry
        branch = {'action': 'choose_branch', 'selector': {'text': '回手或特召二选一'},
                  'branches': [
                      {'condition': '回手', 'actions': [{'action': 'add_hand', 'selector': {'text': '对象卡'},
                                                     'from_zones': ['grave'], 'to_zones': ['hand']}]},
                      {'condition': '特召', 'actions': [{'action': 'special_summon', 'selector': {'text': '对象卡'},
                                                     'from_zones': ['grave'], 'to_zones': ['monster']}]}]}
        effect = simple_effect('m1', 1, ['etag:add-hand', 'etag:special-summon'], [branch])
        effect['effect_type'] = 'spell_activation'
        entry = make_entry(20000001, SEARCHER, [effect])
        validate_entry(entry, registry, {'m1'}, card_type=2)
        broken = deepcopy(entry)
        broken['effects'][0]['structure']['processing'][0]['branches'].pop()
        with self.assertRaisesRegex(ValueError, '互斥分支'):
            validate_entry(broken, registry, {'m1'}, card_type=2)

        material = {'action': 'use_as_fusion_material', 'selector': {'text': '处理时选融合素材'},
                    'from_zones': ['hand', 'deck'],
                    'then': [{'action': 'special_summon', 'selector': {'text': '融合怪兽'},
                              'from_zones': ['extra'], 'to_zones': ['monster']}]}
        entry['effects'][0]['tags'] = ['etag:special-summon']
        entry['effects'][0]['structure']['processing'] = [material]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        entry['effects'][0]['structure']['processing'][0]['then'] = []
        with self.assertRaisesRegex(ValueError, '融合素材处理'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

        entry['effects'][0]['tags'] = []
        entry['effects'][0]['effect_type'] = 'spell_effect'
        entry['effects'][0]['structure']['processing'] = [
            {'action': 'place_faceup_card', 'selector': {'text': '墓地的永续陷阱'},
             'from_zones': ['grave'], 'to_zones': ['spell']}]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        entry['effects'][0]['structure']['processing'][0]['to_zones'] = ['field_spell']
        with self.assertRaisesRegex(ValueError, '表侧放置永续魔陷'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

    def test_synchro_tuner_and_field_return_have_distinct_validation(self):
        registry = self.service.registry
        synchro = {'action': 'use_as_synchro_material', 'selector': {'text': '场上怪兽作为素材'},
                   'from_zones': ['monster'], 'then': [
                       {'action': 'special_summon', 'selector': {'text': '同调怪兽'},
                        'from_zones': ['extra'], 'to_zones': ['monster']}]}
        effect = simple_effect('m1', 1, ['etag:special-summon'], [synchro])
        effect['effect_type'] = 'spell_effect'
        entry = make_entry(20000001, SEARCHER, [effect])
        validate_entry(entry, registry, {'m1'}, card_type=2)
        broken = deepcopy(entry)
        broken['effects'][0]['structure']['processing'][0]['then'] = []
        with self.assertRaisesRegex(ValueError, '同调素材处理'):
            validate_entry(broken, registry, {'m1'}, card_type=2)

        entry['effects'][0]['tags'] = []
        entry['effects'][0]['structure']['processing'] = [
            {'action': 'treat_as_tuner', 'selector': {'text': '对象当调整'}, 'duration': '本回合'}]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        del entry['effects'][0]['structure']['processing'][0]['duration']
        with self.assertRaisesRegex(ValueError, '调整化'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

        entry['effects'][0]['tags'] = ['etag:add-hand']
        entry['effects'][0]['structure']['processing'] = [
            {'action': 'return_hand', 'selector': {'text': '场上对象卡'},
             'from_zones': ['field'], 'to_zones': ['hand', 'extra']}]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        entry['effects'][0]['structure']['processing'][0]['from_zones'] = ['grave']
        with self.assertRaisesRegex(ValueError, '场上卡回手'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

    def test_link_xyz_equip_name_and_counter_actions_require_evidence_fields(self):
        registry = self.service.registry
        effect = simple_effect('m1', 1, ['etag:special-summon'], [])
        effect['effect_type'] = 'spell_effect'
        entry = make_entry(20000001, SEARCHER, [effect])
        for action, error in (('use_as_link_material', '连接素材处理'),
                              ('use_as_xyz_material', '超量素材处理')):
            material = {'action': action, 'selector': {'text': '场上素材'}, 'from_zones': ['monster'],
                        'then': [{'action': 'special_summon', 'selector': {'text': '额外怪兽'},
                                  'from_zones': ['extra'], 'to_zones': ['monster']}]}
            effect['structure']['processing'] = [material]
            validate_entry(entry, registry, {'m1'}, card_type=2)
            material['from_zones'] = ['grave']
            with self.assertRaisesRegex(ValueError, error):
                validate_entry(entry, registry, {'m1'}, card_type=2)

        effect['tags'] = []
        equip = {'action': 'equip_as_spell', 'selector': {'text': '怪兽作装备卡'},
                 'from_zones': ['opponent_monster'], 'to_zones': ['spell']}
        effect['structure']['processing'] = [equip]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        equip['to_zones'] = ['grave']
        with self.assertRaisesRegex(ValueError, '怪兽作装备卡'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

        for action, extra, drop, error in (
                ('change_level', {'duration': '本回合'}, 'duration', '等级变更'),
                ('treat_as_name', {'from_zones': ['hand']}, 'from_zones', '名称视作'),
                ('place_counter', {'count': 1}, 'count', '放置指示物')):
            item = {'action': action, 'selector': {'text': '明确处理'}, **extra}
            effect['structure']['processing'] = [item]
            validate_entry(entry, registry, {'m1'}, card_type=2)
            del item[drop]
            with self.assertRaisesRegex(ValueError, error):
                validate_entry(entry, registry, {'m1'}, card_type=2)

        transfer = {'action': 'give_control', 'selector': {'text': '己方怪兽交给对方'},
                    'from_zones': ['monster'], 'to_zones': ['opponent_monster']}
        effect['structure']['processing'] = [transfer]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        transfer['to_zones'] = ['monster']
        with self.assertRaisesRegex(ValueError, '移交控制权'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

        payment = {'action': 'require_lp_payment', 'selector': {'text': '对方支付500基本分'},
                   'executor': 'opponent'}
        effect['structure']['processing'] = [payment]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        del payment['executor']
        with self.assertRaisesRegex(ValueError, '支付基本分处理'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

    def test_defense_attacks_preserve_damage_stat_and_old_attack_value(self):
        effect = simple_effect('m1', 1, [], [{'action': 'attack_in_defense'}])
        effect['effect_type'] = 'continuous'
        entry = make_entry(20000001, SEARCHER, [effect])
        validate_entry(entry, self.service.registry, {'m1'}, card_type=33)
        action = effect['structure']['processing'][0]
        for stat in ('atk', 'def'):
            action['damage_calculation_stat'] = stat
            validate_entry(entry, self.service.registry, {'m1'}, card_type=33)
        action['damage_calculation_stat'] = 'level'
        with self.assertRaisesRegex(ValueError, '伤害计算数值'):
            validate_entry(entry, self.service.registry, {'m1'}, card_type=33)

    def test_pendulum_placement_and_copy_effect_keep_source_and_timing(self):
        effect = simple_effect('m1', 1, [], [])
        effect['effect_type'] = 'ignition'
        entry = make_entry(20000001, SEARCHER, [effect])
        actions = (
            ({'action': 'place_pendulum', 'from_zones': ['extra_faceup'], 'to_zones': ['pendulum']},
             'to_zones', '灵摆区放置'),
            ({'action': 'redirect_attack', 'selector': {'text': '转移到本卡'}},
             'selector', '攻击转移'),
            ({'action': 'copy_effect', 'from_zones': ['grave'], 'duration': '直到回合结束',
              'selector': {'text': '对象超量怪兽的效果'}}, 'duration', '效果复制'),
        )
        for action, field, error in actions:
            effect['structure']['processing'] = [action]
            validate_entry(entry, self.service.registry, {'m1'}, card_type=33)
            invalid = deepcopy(entry)
            del invalid['effects'][0]['structure']['processing'][0][field]
            with self.assertRaisesRegex(ValueError, error):
                validate_entry(invalid, self.service.registry, {'m1'}, card_type=33)
        self.assertEqual(effect['tags'], [])

    def test_continuous_equipment_effect_cannot_claim_fast_activation(self):
        effect = simple_effect('m1', 1, [], [])
        effect['effect_type'] = 'spell_continuous'
        entry = make_entry(20000001, SEARCHER, [effect])
        validate_entry(entry, self.service.registry, {'m1'}, card_type=33)
        effect['structure']['activation']['fast_effect'] = True
        with self.assertRaisesRegex(ValueError, '持续适用的魔法效果'):
            validate_entry(entry, self.service.registry, {'m1'}, card_type=33)

    def test_damage_prevention_is_not_effect_damage_or_implicit_battle_only(self):
        action = {'action': 'prevent_damage', 'damage_scope': 'battle_and_effect',
                  'recipient': 'self', 'duration': '本回合'}
        effect = simple_effect('m1', 1, ['etag:prevent-damage'], [action])
        effect['effect_type'] = 'spell_effect'
        entry = make_entry(20000001, SEARCHER, [effect])
        validate_entry(entry, self.service.registry, {'m1'}, card_type=2)
        for field in ('damage_scope', 'recipient', 'duration'):
            invalid = deepcopy(entry)
            del invalid['effects'][0]['structure']['processing'][0][field]
            with self.assertRaisesRegex(ValueError, '伤害防止'):
                validate_entry(invalid, self.service.registry, {'m1'}, card_type=2)
        effect['tags'] = ['etag:effect-damage']
        with self.assertRaisesRegex(ValueError, 'TAG 与处理不一致'):
            validate_entry(entry, self.service.registry, {'m1'}, card_type=2)

    def test_return_and_cost_substitution_actions_keep_zone_boundaries(self):
        registry = self.service.registry
        effect = simple_effect('m1', 1, [], [])
        effect['effect_type'] = 'spell_effect'
        entry = make_entry(20000001, SEARCHER, [effect])
        valid = (
            ({'action': 'return_grave', 'selector': {'text': '除外卡回墓地'},
              'from_zones': ['banished'], 'to_zones': ['grave']}, 'from_zones', '除外卡回墓地'),
            ({'action': 'increase_normal_summon_limit', 'selector': {'text': '本回合三次通常召唤'},
              'duration': '本回合'}, 'duration', '通常召唤次数增加'),
            ({'action': 'substitute_tribute_cost', 'selector': {'text': '墓地卡替代解放'},
              'from_zones': ['grave'], 'to_zones': ['banished']}, 'from_zones', '解放费用替代'),
            ({'action': 'return_unsummoned', 'selector': {'text': '召唤无效回手'},
              'to_zones': ['hand', 'extra']}, 'to_zones', '被无效召唤怪兽回手'),
            ({'action': 'substitute_detach_source', 'selector': {'text': '取其他超量怪兽素材'},
              'from_zones': ['xyz_material']}, 'from_zones', '超量取除来源替代'),
        )
        for item, required, error in valid:
            effect['tags'] = ['etag:add-hand'] if item['action'] == 'return_unsummoned' else []
            effect['structure']['processing'] = [item]
            validate_entry(entry, registry, {'m1'}, card_type=2)
            broken = deepcopy(entry)
            del broken['effects'][0]['structure']['processing'][0][required]
            with self.assertRaisesRegex(ValueError, error):
                validate_entry(broken, registry, {'m1'}, card_type=2)

        effect['tags'] = ['etag:add-hand']
        effect['structure']['processing'] = [
            {'action': 'return_hand', 'selector': {'text': '对方场上怪兽回手'},
             'from_zones': ['opponent_monster'], 'to_zones': ['hand']}]
        validate_entry(entry, registry, {'m1'}, card_type=2)
        effect['structure']['processing'][0]['from_zones'] = ['opponent_grave']
        with self.assertRaisesRegex(ValueError, '场上卡回手'):
            validate_entry(entry, registry, {'m1'}, card_type=2)

    def short_rule_actions(self):
        # Minimal meaningful parameter sets from the reviewed short-card proposals.
        return [
            ({'action': 'remove_counter', 'counter_type': '魔力指示物', 'from_zones': ['field'], 'count': 'all'}, []),
            ({'action': 'place_deck_top', 'executor': 'opponent', 'from_zones': ['opponent_deck'],
              'to_zones': ['opponent_deck_top'], 'count': 1, 'shuffle_before_placement': True,
              'inspects_opponent_deck': False}, ['etag:deck-look']),
            ({'action': 'reveal_set_cards', 'from_zones': ['field'], 'controller': 'opponent',
              'audience': 'self', 'changes_position': False, 'count': 'all'}, []),
            ({'action': 'change_hand_limit', 'recipient': 'self', 'value': 7, 'duration': '本次决斗'}, []),
            ({'action': 'skip_phase', 'player': 'self', 'phase': 'standby', 'count': 1, 'duration': '下次自己的准备阶段'}, []),
            ({'action': 'advance_turn_count', 'amount': 1, 'count': 1}, []),
            ({'action': 'repeat_phase', 'player': 'opponent', 'phase': 'battle', 'count': 2, 'duration': '下次实际进行战斗阶段的回合'}, []),
            ({'action': 'redirect_spell_recipient', 'source_activation': 'spell_card_activation',
              'recipient_rule': 'other_player', 'count': 1}, []),
            ({'action': 'change_race', 'race': 'dragon', 'duration': '本回合', 'from_zones': ['monster'],
              'count': 'all', 'applies_to_later_monsters': False}, ['etag:stat-change']),
            ({'action': 'activate_field_spell', 'from_zones': ['deck'], 'to_zones': ['field_spell'],
              'count': 1, 'resolve_activation_effect': False}, []),
            ({'action': 'reveal_drawn_cards', 'player': 'opponent', 'duration': '对方第2次回合结束时'}, []),
            ({'action': 'reverse_stat_modifiers', 'stats': ['atk', 'def'], 'duration': '本回合'}, ['etag:stat-change']),
            ({'action': 'reroll_dice', 'player': 'both', 'duration': '本回合', 'applications': 1,
              'dice_scope': 'entire_dice_procedure', 'stacking': 'non_cumulative'}, []),
            ({'action': 'move_to_end_phase', 'phase': 'end', 'duration': '立即移行'}, []),
            ({'action': 'redirect_spell_target', 'source_activation': 'spell_card_activation',
              'original_target_kind': 'monster', 'new_target_rule': 'different_legal_target',
              'from_zones': ['field'], 'count': 1}, []),
        ]

    def rule_action_entry(self, action, tags):
        action = {'selector': {'text': '按官方资料记录的本卡处理'}, **deepcopy(action)}
        effect = simple_effect('m1', 1, tags, [action])
        effect['effect_type'] = 'spell_activation'
        return make_entry(20000001, SEARCHER, [effect])

    def test_short_rule_actions_require_parameters_not_just_registered_names(self):
        for action, tags in self.short_rule_actions():
            entry = self.rule_action_entry(action, tags)
            validate_entry(entry, self.service.registry, card_type=2)
            for field in {'selector', *action} - {'action', 'inspects_opponent_deck'}:
                with self.subTest(action=action['action'], missing=field):
                    invalid = deepcopy(entry)
                    del invalid['effects'][0]['structure']['processing'][0][field]
                    with self.assertRaises(ValueError):
                        validate_entry(invalid, self.service.registry, card_type=2)

    def test_short_rule_actions_reject_mechanically_different_parameter_values(self):
        fixtures = {a['action']: (a, tags) for a, tags in self.short_rule_actions()}
        mutations = [
            ('remove_counter', 'counter_type', ''),
            ('remove_counter', 'count', True),
            ('place_deck_top', 'to_zones', ['grave']),
            ('place_deck_top', 'shuffle_before_placement', 1),
            ('place_deck_top', 'inspects_opponent_deck', 'false'),
            ('place_deck_top', 'executor', 'owner'),
            ('reveal_set_cards', 'changes_position', True),
            ('reveal_set_cards', 'from_zones', ['hand']),
            ('reveal_set_cards', 'audience', []),
            ('change_hand_limit', 'value', -1),
            ('change_hand_limit', 'value', True),
            ('change_hand_limit', 'value', 7.0),
            ('skip_phase', 'phase', 'whole_turn'),
            ('skip_phase', 'count', 0),
            ('skip_phase', 'count', '2'),
            ('advance_turn_count', 'amount', False),
            ('advance_turn_count', 'amount', -1),
            ('repeat_phase', 'count', 1),
            ('repeat_phase', 'duration', ''),
            ('redirect_spell_recipient', 'source_activation', 'spell_effect'),
            ('redirect_spell_recipient', 'recipient_rule', 'both_players'),
            ('redirect_spell_target', 'original_target_kind', 'player'),
            ('redirect_spell_target', 'new_target_rule', 'same_target'),
            ('redirect_spell_target', 'from_zones', ['grave']),
            ('redirect_spell_target', 'count', 2),
            ('change_race', 'race', 8192),
            ('change_race', 'applies_to_later_monsters', 'false'),
            ('activate_field_spell', 'to_zones', ['spell']),
            ('activate_field_spell', 'resolve_activation_effect', True),
            ('reveal_drawn_cards', 'player', 'drawer'),
            ('reverse_stat_modifiers', 'stats', ['level']),
            ('reverse_stat_modifiers', 'stats', ['atk', 'atk']),
            ('reroll_dice', 'applications', 0),
            ('reroll_dice', 'dice_scope', 'keep_one_previous_result'),
            ('reroll_dice', 'stacking', 'unknown'),
            ('move_to_end_phase', 'phase', 'battle'),
        ]
        for name, field, value in mutations:
            with self.subTest(action=name, field=field, value=value):
                action, tags = deepcopy(fixtures[name])
                action[field] = value
                with self.assertRaises(ValueError):
                    validate_entry(self.rule_action_entry(action, tags), self.service.registry, card_type=2)

    def test_support_actions_cannot_borrow_later_cards_draw_destroy_or_negation_tags(self):
        for action, tags in self.short_rule_actions():
            for borrowed in ('etag:draw', 'etag:destroy', 'etag:negate-effect', 'etag:negate-activation'):
                with self.subTest(action=action['action'], borrowed=borrowed):
                    with self.assertRaisesRegex(ValueError, 'TAG 与处理'):
                        validate_entry(self.rule_action_entry(action, [*tags, borrowed]), self.service.registry, card_type=2)
        # A card which actually draws and then skips its next phases keeps its draw capability.
        skip = next(a for a, _ in self.short_rule_actions() if a['action'] == 'skip_phase')
        entry = self.rule_action_entry(skip, ['etag:draw'])
        entry['effects'][0]['structure']['processing'].insert(0, {'action': 'draw', 'count': 2})
        validate_entry(entry, self.service.registry, card_type=2)

    def test_new_race_and_modifier_actions_use_existing_stat_tag_without_changing_legacy_rules(self):
        for action, tags in self.short_rule_actions():
            if action['action'] not in ('change_race', 'reverse_stat_modifiers'): continue
            self.assertEqual(tags, ['etag:stat-change'])
            with self.assertRaisesRegex(ValueError, 'etag:stat-change'):
                validate_entry(self.rule_action_entry(action, []), self.service.registry, card_type=2)
        # Existing stat_change annotations do not gain new required fields or tag rules.
        validate_entry(self.rule_action_entry({'action': 'stat_change'}, []), self.service.registry, card_type=2)

    def test_opponent_extra_is_not_self_extra_or_a_field_zone(self):
        action = {'action': 'return_deck', 'from_zones': ['opponent_monster'], 'to_zones': ['opponent_extra']}
        entry = self.rule_action_entry(action, ['etag:return-deck'])
        self.write_curated(mutate=lambda entries: entries.update({'20000001': entry}))
        self.service.reload()
        self.assertEqual(self.service.search({'q': '20000001', 'to_zone': 'opponent_extra'})['total'], 1)
        for zone in ('extra', 'extra_faceup', 'opponent_extra_monster_zone', 'field'):
            self.assertFalse(zone_matches(zone, ['opponent_extra']))
            self.assertEqual(self.service.search({'q': '20000001', 'to_zone': zone})['total'], 0)
        self.assertIn('opponent_deck_top', self.service.registry.vocab['zones'])
        self.assertFalse(zone_matches('deck_top', ['opponent_deck_top']))

    def test_target_ranges_are_explicit_and_preserve_fixed_and_unbounded_quantities(self):
        effect = simple_effect('m1', 1, ['etag:return-deck'], [
            {'action': 'return_deck', 'from_zones': ['grave'], 'to_zones': ['deck']}])
        effect['effect_type'] = 'spell_activation'
        entry = make_entry(20000001, SEARCHER, [effect])
        for quantity in ({'count': 2}, {'count': 0}, {'min_count': 1, 'max_count': 3},
                         {'min_count': 0, 'max_count': 0}, {'min_count': 2, 'max_count': None}):
            with self.subTest(quantity=quantity):
                effect['structure']['targeting'] = [{**quantity, 'filter': '符合条件的墓地怪兽'}]
                validate_entry(entry, self.service.registry, card_type=2)
                self.write_curated(mutate=lambda entries: entries.update({'20000001': entry}))
                self.service.reload()
                self.assertEqual(self.service.search({'q': '20000001', 'action': 'return_deck', 'from_zone': 'grave'})['total'], 1)
                self.assertEqual(self.service.view(20000001)['effects'][0]['structure']['targeting'], effect['structure']['targeting'])
        effect['structure']['targeting'] = [{'min_count': 1, 'max_count': 3, 'filter': '自己墓地火山怪兽'}]
        self.assertEqual(effect['structure']['targeting'][0]['min_count'], 1, '33725271必须是1至3，不是0至3')

    def test_target_ranges_reject_missing_bounds_ambiguity_and_non_integer_counts(self):
        entry = self.rule_action_entry({'action': 'return_deck'}, ['etag:return-deck'])
        invalid_quantities = [
            {}, {'min_count': 1}, {'max_count': 3}, {'max_count': None},
            {'count': 3, 'min_count': 1, 'max_count': 3},
            {'count': 2, 'min_count': 2, 'variable_count': True},
            {'count': None, 'min_count': 1, 'max_count': None},
            {'min_count': 3, 'max_count': 2}, {'min_count': -1, 'max_count': 3},
            {'min_count': 0, 'max_count': -1}, {'min_count': 1.0, 'max_count': 3},
            {'min_count': 1, 'max_count': 3.0}, {'min_count': '1', 'max_count': 3},
            {'min_count': None, 'max_count': 3}, {'min_count': True, 'max_count': 3},
            {'min_count': 0, 'max_count': False}, {'count': True}, {'count': False},
            {'count': -1}, {'count': 1.0}, {'count': '1'},
        ]
        for quantity in invalid_quantities:
            with self.subTest(quantity=quantity):
                entry['effects'][0]['structure']['targeting'] = [{**quantity, 'filter': '对象'}]
                with self.assertRaisesRegex(ValueError, '对象'):
                    validate_entry(entry, self.service.registry, card_type=2)

    def short_03_actions(self):
        return [
            {'action': 'increase_pendulum_summon_limit', 'executor': 'self', 'count': 1,
             'from_zones': ['extra_faceup'], 'duration': '本回合'},
            {'action': 'win_duel', 'recipient': 'self', 'delayed': True, 'creates_chain': False,
             'turn_count': 20, 'count_both_players_turns': True, 'start_turn_inclusive': True,
             'resolution_timing': 'end_of_20th_turn_including_activation_turn'},
            {'action': 'place_and_use_spell', 'count': 1, 'from_zones': ['opponent_grave'],
             'to_zones': ['spell', 'field_spell'], 'executor': 'self',
             'used_spell_cost_timing': 'resolution', 'used_spell_targeting_timing': 'resolution'},
            {'action': 'return_to_field', 'count': 1, 'from_zones': ['banished'], 'to_zones': ['monster'],
             'delayed': True, 'creates_chain': False, 'resolution_timing': 'next_own_standby',
             'position': 'same_as_before_banish', 'counts_as_special_summon': False},
        ]

    def test_short_03_actions_require_explicit_semantic_parameters(self):
        for action in self.short_03_actions():
            entry = self.rule_action_entry(action, [])
            validate_entry(entry, self.service.registry, card_type=2)
            for field in {'selector', *action} - {'action'}:
                with self.subTest(action=action['action'], missing=field):
                    invalid = deepcopy(entry)
                    del invalid['effects'][0]['structure']['processing'][0][field]
                    with self.assertRaises(ValueError):
                        validate_entry(invalid, self.service.registry, card_type=2)
        immediate_win = next(a for a in self.short_03_actions() if a['action'] == 'win_duel')
        for field in ('turn_count', 'count_both_players_turns', 'start_turn_inclusive'): del immediate_win[field]
        immediate_win.update(delayed=False, resolution_timing='符合指定胜利条件时')
        validate_entry(self.rule_action_entry(immediate_win, []), self.service.registry, card_type=2)

    def test_short_03_actions_reject_wrong_sources_timings_and_boolean_integers(self):
        fixtures = {a['action']: a for a in self.short_03_actions()}
        changes = [
            ('increase_pendulum_summon_limit', 'count', True),
            ('increase_pendulum_summon_limit', 'count', 0),
            ('increase_pendulum_summon_limit', 'from_zones', ['grave']),
            ('increase_pendulum_summon_limit', 'from_zones', ['extra']),
            ('increase_pendulum_summon_limit', 'duration', ''),
            ('win_duel', 'turn_count', True), ('win_duel', 'turn_count', 20.0),
            ('win_duel', 'turn_count', -1), ('win_duel', 'recipient', 'both'),
            ('win_duel', 'count_both_players_turns', 'true'),
            ('win_duel', 'start_turn_inclusive', 1), ('win_duel', 'delayed', 'true'),
            ('win_duel', 'creates_chain', 'false'), ('win_duel', 'resolution_timing', ''),
            ('place_and_use_spell', 'count', 2), ('place_and_use_spell', 'count', True),
            ('place_and_use_spell', 'to_zones', ['monster']),
            ('place_and_use_spell', 'executor', 'both'),
            ('place_and_use_spell', 'used_spell_cost_timing', 'activation'),
            ('place_and_use_spell', 'used_spell_targeting_timing', 'activation'),
            ('return_to_field', 'count', False), ('return_to_field', 'count', 0),
            ('return_to_field', 'from_zones', ['grave']),
            ('return_to_field', 'to_zones', ['hand']),
            ('return_to_field', 'creates_chain', True),
            ('return_to_field', 'counts_as_special_summon', True),
            ('return_to_field', 'position', ''), ('return_to_field', 'delayed', 1),
        ]
        for action, field, value in changes:
            with self.subTest(action=action, field=field, value=value):
                changed = {**fixtures[action], field: value}
                with self.assertRaises(ValueError):
                    validate_entry(self.rule_action_entry(changed, []), self.service.registry, card_type=2)

    def test_short_03_actions_do_not_claim_summons_damage_or_unknown_used_spell_abilities(self):
        for action in self.short_03_actions():
            for borrowed in ('etag:special-summon', 'etag:normal-summon', 'etag:draw', 'etag:effect-damage', 'etag:recover-lp'):
                with self.subTest(action=action['action'], borrowed=borrowed):
                    with self.assertRaisesRegex(ValueError, 'TAG 与处理'):
                        validate_entry(self.rule_action_entry(action, [borrowed]), self.service.registry, card_type=2)
            entry = self.rule_action_entry(action, [])
            self.write_curated(mutate=lambda entries: entries.update({'20000001': entry}))
            self.service.reload()
            self.assertEqual(self.service.search({'q': '20000001', 'action': action['action']})['total'], 1)
            self.assertEqual(self.service.search({'q': '20000001', 'action': 'special_summon'})['total'], 0)
            self.assertEqual(self.service.search({'q': '20000001', 'action': 'draw'})['total'], 0)
        used = self.rule_action_entry(next(a for a in self.short_03_actions() if a['action'] == 'place_and_use_spell'), [])
        used['effects'][0]['structure']['processing'][0]['granted_effect'] = fixed_grant(
            'trigger', ['etag:draw'], [{'action': 'draw'}])['granted_effect']
        with self.assertRaisesRegex(ValueError, '只能登记在 grant_effect'):
            validate_entry(used, self.service.registry, card_type=2)

    def test_return_to_field_keeps_temporary_banish_and_return_zones_bound_to_their_own_actions(self):
        returned = self.rule_action_entry(next(a for a in self.short_03_actions() if a['action'] == 'return_to_field'), [])['effects'][0]['structure']['processing'][0]
        entry = self.rule_action_entry({'action': 'banish', 'from_zones': ['monster'],
                                        'to_zones': ['banished'], 'then': [returned]}, ['etag:banish'])
        self.write_curated(mutate=lambda entries: entries.update({'20000001': entry}))
        self.service.reload()
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'return_to_field', 'from_zone': 'banished', 'to_zone': 'monster'})['total'], 1)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'return_to_field', 'from_zone': 'monster'})['total'], 0)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'banish', 'to_zone': 'monster'})['total'], 0)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'special_summon'})['total'], 0)

    def test_return_deck_cost_supports_explicit_non_hand_origin_without_an_effect_tag(self):
        label = self.service.registry.vocab['cost_kinds']['return_deck']
        self.assertIn('明确来源', label)
        self.assertIn('额外卡组', label)
        effect = simple_effect('m1', 1, ['etag:draw'], [{'action': 'draw', 'count': 1}])
        effect['effect_type'] = 'spell_activation'
        for text in ('把手卡1张指定卡放回持有者主卡组最下面', '把自己墓地1只融合怪兽返回持有者额外卡组'):
            effect['structure']['cost'] = [{'kind': 'return_deck', 'text': text}]
            entry = make_entry(20000001, SEARCHER, [effect])
            validate_entry(entry, self.service.registry, card_type=2)
            self.write_curated(mutate=lambda entries: entries.update({'20000001': entry}))
            self.service.reload()
            self.assertEqual(self.service.search({'q': '20000001', 'cost_kind': 'return_deck'})['total'], 1)
            self.assertEqual(self.service.search({'q': '20000001', 'action': 'return_deck'})['total'], 0)

    def test_dynamic_target_count_distinguishes_exact_n_from_up_to_n_without_evaluating(self):
        rules = [
            {'mode': 'exact', 'text': '作为费用解放的暗属性连接怪兽的连接标记数量', 'evaluated_at': 'activation'},
            {'mode': 'up_to', 'text': '发动时双方相互连接怪兽的数量', 'evaluated_at': 'activation', 'minimum': 1},
            {'mode': 'up_to', 'text': '指定数量的计算说明，不是表达式执行', 'evaluated_at': 'activation', 'minimum': 0},
        ]
        for rule in rules:
            with self.subTest(rule=rule):
                entry = self.rule_action_entry({'action': 'destroy', 'from_zones': ['field']}, ['etag:destroy'])
                target = {'count_rule': deepcopy(rule), 'filter': '满足卡文的场上卡'}
                entry['effects'][0]['structure']['targeting'] = [target]
                validate_entry(entry, self.service.registry, card_type=2)
                self.write_curated(mutate=lambda entries: entries.update({'20000001': entry}))
                self.service.reload()
                self.assertEqual(self.service.search({'q': '20000001', 'action': 'destroy', 'from_zone': 'field'})['total'], 1)
                self.assertEqual(self.service.view(20000001)['effects'][0]['structure']['targeting'], [target])
                self.assertNotIn('count', target)
                self.assertNotIn('max_count', target)

    def test_dynamic_target_count_rejects_mixed_modes_missing_basis_and_boolean_minimum(self):
        exact = {'mode': 'exact', 'text': '作为费用解放怪兽的连接标记数', 'evaluated_at': 'activation'}
        upto = {'mode': 'up_to', 'text': '双方相互连接怪兽数', 'evaluated_at': 'activation', 'minimum': 1}
        bad_rules = [None, [], False, 'N', {},
                     {**exact, 'mode': 'fixed'}, {**exact, 'mode': True},
                     {**exact, 'text': ''}, {**exact, 'text': '   '}, {**exact, 'text': 2},
                     {**exact, 'evaluated_at': 'resolution'}, {**exact, 'evaluated_at': False},
                     {**exact, 'minimum': 0}, {**exact, 'minimum': None},
                     {**exact, 'source': 'legacy_formula_id'},
                     {**upto, 'minimum': -1}, {**upto, 'minimum': True},
                     {**upto, 'minimum': False}, {**upto, 'minimum': 1.0}, {**upto, 'minimum': '1'}]
        bad_rules.extend({k: v for k, v in upto.items() if k != missing}
                         for missing in ('mode', 'text', 'evaluated_at', 'minimum'))
        for rule in bad_rules:
            with self.subTest(rule=rule):
                entry = self.rule_action_entry({'action': 'destroy'}, ['etag:destroy'])
                entry['effects'][0]['structure']['targeting'] = [{'count_rule': rule, 'filter': '对象'}]
                with self.assertRaisesRegex(ValueError, '对象'):
                    validate_entry(entry, self.service.registry, card_type=2)
        for mixed in ({'count': 1}, {'count': None}, {'min_count': 1}, {'max_count': None},
                      {'min_count': 1, 'max_count': 3}):
            with self.subTest(mixed=mixed):
                entry = self.rule_action_entry({'action': 'destroy'}, ['etag:destroy'])
                entry['effects'][0]['structure']['targeting'] = [{'count_rule': exact, 'filter': '对象', **mixed}]
                with self.assertRaisesRegex(ValueError, '不能与固定数量或常量范围混用'):
                    validate_entry(entry, self.service.registry, card_type=2)

    def test_usage_and_action_filters(self):
        locked = self.service.search({'etags': ['etag:special-summon'], 'usage': 'per_effect_name_soft_opt'})
        self.assertEqual([c['code'] for c in locked['cards']], [20000003])
        destroyed = self.service.search({'action': 'destroy'})
        self.assertEqual([c['code'] for c in destroyed['cards']], [20000003])
        self.assertEqual(destroyed['cards'][0]['hits'][0]['key'], 'm2')

    def install_grant_effect(self, effect):
        self.write_curated(mutate=lambda entries: entries['20000001'].update(effects=[effect]))
        self.service.reload()

    def test_real_fixed_grants_match_ultimate_timing_and_stranger_cost(self):
        cases = [
            (86221741, '③：这张卡有「急袭猛禽」怪兽在作为超量素材的场合，得到以下效果。\n'
             '●自己·对方的结束阶段才能发动。对方场上有表侧表示怪兽存在的场合，那些攻击力下降1000。不存在的场合，给与对方1000伤害。',
             'm3', fixed_grant('trigger', ['etag:effect-damage', 'etag:stat-change'], [
                 {'action': 'choose_branch', 'branches': [
                     {'condition': '处理时对方有表侧怪兽', 'actions': [
                         {'action': 'stat_change', 'from_zones': ['opponent_monster']}]},
                     {'condition': '处理时对方没有表侧怪兽', 'actions': [
                         {'action': 'burn', 'recipient': 'opponent', 'amount': 1000}]}]}]),
             {'timing': 'end_phase', 'action': 'burn', 'etags': ['etag:effect-damage']}),
            (15092394, '①：这张卡有超量怪兽在作为超量素材的场合，得到以下效果。\n'
             '●1回合1次，把这张卡1个超量素材取除，以对方场上1只怪兽为对象才能发动。那只怪兽破坏，给与对方那个原本攻击力数值的伤害。',
             'm1', fixed_grant('ignition', ['etag:destroy', 'etag:effect-damage'], [
                 {'action': 'destroy', 'from_zones': ['opponent_monster'], 'then': [
                     {'action': 'burn', 'recipient': 'opponent'}]}], timing='main_phase_self',
                 cost=[{'kind': 'detach_material', 'text': '取除本卡1个素材'}], usage=['soft_opt']),
             {'action': 'destroy', 'cost_kind': 'detach_material', 'usage': 'soft_opt',
              'from_zone': 'opponent_monster', 'etags': ['etag:destroy']}),
        ]
        additions = {}
        for code, desc, key, grant, _ in cases:
            effect = granting_effect([grant])
            effect.update(key=key, number=int(key[1:]), effect_type='non_effect')
            self.store.catalog.cards[code] = {'name': str(code), 'type': 0x800021, 'desc': desc}
            additions[str(code)] = make_entry(code, desc, [effect])
        self.write_curated(mutate=lambda entries: entries.update(additions))
        self.service.reload()
        for code, _, key, _, conditions in cases:
            with self.subTest(code=code):
                result = self.service.search({'q': str(code), **conditions})
                self.assertEqual(result['total'], 1)
                self.assertEqual(result['cards'][0]['hit_keys'], [key])
                evidence = result['cards'][0]['hits'][0]['evidence']
                self.assertTrue(evidence)
                self.assertTrue(all(item['effect_source'] == 'granted_effect' for item in evidence))
                self.assertTrue(all('固定获赋效果' in item['basis'] for item in evidence))
                self.assertTrue(all(item['effect_path'] == '0.granted_effect' for item in evidence))

    def test_parent_cost_tags_and_zones_cannot_mix_with_granted_actions(self):
        grant = fixed_grant('trigger', ['etag:destroy'], [
            {'action': 'destroy', 'from_zones': ['opponent_monster']}])
        effect = granting_effect([grant], own_tags=['etag:protect'],
                                 own_processing=[{'action': 'protect', 'from_zones': ['grave']}],
                                 cost=[{'kind': 'lp', 'text': '支付500LP以获得效果'}])
        self.install_grant_effect(effect)
        for condition in ({'cost_kind': 'lp'}, {'action': 'destroy'}, {'etags': ['etag:protect']}):
            self.assertEqual(self.service.search({'q': '20000001', **condition})['total'], 1)
        for condition in ({'cost_kind': 'lp'}, {'from_zone': 'grave'}, {'etags': ['etag:protect']}):
            with self.subTest(condition=condition):
                self.assertEqual(self.service.search({'q': '20000001', 'action': 'destroy', **condition})['total'], 0)
        card_scope = self.service.search({'q': '20000001', 'action': 'destroy', 'cost_kind': 'lp', 'scope': 'card'})
        self.assertEqual(card_scope['total'], 1)
        self.assertTrue(card_scope['cards'][0]['cross_effects'])

    def test_each_fixed_granted_effect_is_a_separate_matching_unit(self):
        draw = fixed_grant('trigger', ['etag:draw'], [
            {'action': 'draw', 'from_zones': ['deck'], 'to_zones': ['hand']}],
            cost=[{'kind': 'discard'}], usage=['soft_opt'])
        destroy = fixed_grant('quick', ['etag:destroy'], [
            {'action': 'destroy', 'from_zones': ['opponent_monster']}], timing='fast_window',
            cost=[{'kind': 'banish'}], usage=['name_soft_opt'])
        self.install_grant_effect(granting_effect([draw, destroy]))
        positive = {'q': '20000001', 'action': 'draw', 'timing': 'end_phase', 'cost_kind': 'discard',
                    'usage': 'soft_opt', 'from_zone': 'deck', 'to_zone': 'hand', 'etags': ['etag:draw']}
        self.assertEqual(self.service.search(positive)['total'], 1)
        for conditions in (
            {'action': 'draw', 'timing': 'fast_window'},
            {'action': 'draw', 'cost_kind': 'banish'},
            {'action': 'destroy', 'usage': 'soft_opt'},
            {'action': 'destroy', 'from_zone': 'deck'},
            {'etags': ['etag:draw', 'etag:destroy']},
        ):
            with self.subTest(conditions=conditions):
                self.assertEqual(self.service.search({'q': '20000001', **conditions})['total'], 0)

    def test_nested_fixed_grants_and_branch_containers_keep_boundaries(self):
        leaf = fixed_grant('trigger', ['etag:draw'], [{'action': 'draw', 'from_zones': ['deck']}])
        middle = fixed_grant('ignition', ['etag:draw'], [leaf], timing='main_phase_self',
                             cost=[{'kind': 'discard'}])
        middle['granted_effect']['own_tags'] = []
        effect = granting_effect([])
        effect['tags'] = ['etag:draw']
        effect['structure']['processing'] = [{'action': 'protect', 'branches': [
            {'condition': '固定授予条件', 'actions': [middle]}]}]
        self.install_grant_effect(effect)
        result = self.service.search({'q': '20000001', 'action': 'draw', 'timing': 'end_phase'})
        self.assertEqual(result['total'], 1)
        evidence = result['cards'][0]['hits'][0]['evidence']
        self.assertTrue(all(item['effect_path'] == '0.branch0.0.granted_effect.0.granted_effect' for item in evidence))
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'draw', 'cost_kind': 'discard'})['total'], 0)

    def test_copy_effect_does_not_expand_unknown_copied_capabilities(self):
        action = {'action': 'copy_effect', 'selector': {'text': '墓地对象的效果'},
                  'from_zones': ['grave'], 'duration': '至结束阶段'}
        effect = simple_effect('m1', 1, [], [action])
        effect['effect_type'] = 'spell_activation'
        self.install_grant_effect(effect)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'copy_effect'})['total'], 1)
        for query in ({'action': 'burn'}, {'etags': ['etag:effect-damage']}, {'timing': 'end_phase'}):
            self.assertEqual(self.service.search({'q': '20000001', **query})['total'], 0)
        action['granted_effect'] = fixed_grant('trigger', ['etag:effect-damage'], [{'action': 'burn'}])['granted_effect']
        with self.assertRaisesRegex(ValueError, '只能登记在 grant_effect'):
            validate_entry(make_entry(20000001, SEARCHER, [effect]), self.service.registry, card_type=2)

    def test_legacy_grant_without_metadata_retains_query_and_browse_behavior(self):
        effect = simple_effect('m1', 1, ['etag:destroy'], [
            {'action': 'grant_effect', 'then': [{'action': 'destroy', 'from_zones': ['opponent_monster']}]}])
        effect['effect_type'] = 'spell_activation'
        effect['structure']['cost'] = [{'kind': 'lp', 'text': '旧标注的费用'}]
        self.install_grant_effect(effect)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'destroy', 'cost_kind': 'lp'})['total'], 1)
        result = self.service.search({'q': '20000001'})
        self.assertEqual(result['cards'][0]['hit_keys'], ['m1'])
        self.assertEqual(result['cards'][0]['hits'][0]['evidence'], [])

    def test_fixed_grants_browse_once_with_original_segment_and_summary_tags(self):
        effect = granting_effect([fixed_grant('trigger', ['etag:draw'], [{'action': 'draw'}]),
                                  fixed_grant('trigger', ['etag:destroy'], [{'action': 'destroy'}])])
        self.install_grant_effect(effect)
        before = deepcopy(self.service.document)
        result = self.service.search({'q': '20000001'})
        self.assertEqual(result['total'], 1)
        hits = result['cards'][0]['hits']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['key'], 'm1')
        self.assertEqual(set(hits[0]['tags']), {'etag:draw', 'etag:destroy'})
        self.assertEqual(hits[0]['evidence'], [])
        self.assertEqual(self.service.document, before)

    def test_fixed_grant_personal_tag_overrides_mask_children_and_keep_additions(self):
        self.install_grant_effect(granting_effect([
            fixed_grant('trigger', ['etag:destroy'], [{'action': 'destroy'}])]))
        self.service.command({'op': 'set-tags', 'code': 20000001, 'key': 'm1',
                              'add': ['etag:draw'], 'remove': ['etag:destroy'], 'revision': 1})
        before = deepcopy(self.service.document)
        saved = self.service.path.read_bytes()
        self.assertEqual(self.service.search({'q': '20000001', 'etags': ['etag:destroy']})['total'], 0)
        self.assertEqual(self.service.search({'q': '20000001', 'etags': ['etag:draw']})['total'], 1)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'destroy'})['total'], 1)
        self.assertEqual(self.service.search({'q': '20000001', 'action': 'destroy', 'etags': ['etag:draw']})['total'], 0)
        self.assertEqual(self.service.document, before)
        self.assertEqual(self.service.path.read_bytes(), saved)
        self.service.reload()
        self.assertEqual(self.service.search({'q': '20000001', 'etags': ['etag:destroy']})['total'], 0)
        self.service.command({'op': 'set-tags', 'code': 20000001, 'key': 'm1',
                              'add': ['etag:destroy'], 'remove': ['etag:draw'], 'revision': 2})
        result = self.service.search({'q': '20000001', 'etags': ['etag:destroy'], 'timing': 'end_phase'})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['cards'][0]['hits'][0]['evidence'][0]['effect_source'], 'granted_effect')

    def test_fixed_grant_payload_rejects_unknown_or_invalid_semantic_fields(self):
        grant = fixed_grant('trigger', ['etag:draw'], [{'action': 'draw', 'from_zones': ['deck']}],
                            cost=[{'kind': 'discard'}], usage=['soft_opt'])
        original = make_entry(20000001, SEARCHER, [granting_effect([grant])])
        def mutate_child(entry):
            return entry['effects'][0]['structure']['processing'][0]['granted_effect']
        mutations = (
            ('effect_types', lambda child: child.update(effect_type='invented')),
            ('effect_types', lambda child: child.update(effect_type=['trigger'])),
            ('TAG', lambda child: child.update(tags=['etag:not-registered'])),
            ('timings', lambda child: child['structure']['activation'].update(timing='invented')),
            ('zones', lambda child: child['structure']['activation'].update(zones=['invented'])),
            ('cost_kinds', lambda child: child['structure']['cost'][0].update(kind='invented')),
            ('usage_limits', lambda child: child['structure'].update(usage=['invented'])),
            ('actions', lambda child: child['structure']['processing'][0].update(action='invented')),
            ('快速效果', lambda child: child['structure']['activation'].update(fast_effect=True)),
            ('TAG 与处理', lambda child: child.update(tags=['etag:destroy'])),
            ('结构无效', lambda child: child.update(structure=[])),
            ('固定处理', lambda child: child['structure'].update(processing=[])),
        )
        for error, mutate in mutations:
            with self.subTest(error=error):
                entry = deepcopy(original)
                mutate(mutate_child(entry))
                with self.assertRaisesRegex(ValueError, error):
                    validate_entry(entry, self.service.registry, card_type=2)
        entry = deepcopy(original)
        entry['review']['status'] = 'draft'
        mutate_child(entry)['tags'] = ['etag:destroy']
        with self.assertRaisesRegex(ValueError, 'TAG 与处理'):
            validate_entry(entry, self.service.registry, card_type=2)

    def test_fixed_grant_requires_own_tags_and_identical_compatibility_tree(self):
        grant = fixed_grant('trigger', ['etag:draw'], [{'action': 'draw'}])
        original = make_entry(20000001, SEARCHER, [granting_effect([grant])])
        validate_entry(original, self.service.registry, card_type=2)
        entry = deepcopy(original)
        del entry['effects'][0]['own_tags']
        with self.assertRaisesRegex(ValueError, 'own_tags'):
            validate_entry(entry, self.service.registry, card_type=2)
        entry = deepcopy(original)
        entry['effects'][0]['structure']['processing'][0]['then'][0]['count'] = 2
        with self.assertRaisesRegex(ValueError, '处理树不一致'):
            validate_entry(entry, self.service.registry, card_type=2)
        entry = deepcopy(original)
        entry['effects'][0]['tags'].append('etag:destroy')
        with self.assertRaisesRegex(ValueError, '并集一致'):
            validate_entry(entry, self.service.registry, card_type=2)
        entry = deepcopy(original)
        entry['effects'][0]['own_tags'] = ['etag:draw']
        with self.assertRaisesRegex(ValueError, 'TAG 与处理'):
            validate_entry(entry, self.service.registry, card_type=2)

    def test_overview_counts_full_and_partial(self):
        overview = self.service.overview()
        self.assertEqual(overview['statuses']['reviewed'], 4)
        self.assertEqual(overview['statuses']['none'], 1)
        self.assertEqual(overview['annotated_total'], 4)
        self.write_curated(mutate=lambda entries: entries['20000003']['effects'].pop(0))
        self.service.reload()
        self.assertEqual(self.service.overview()['statuses']['partial'], 1)

    def test_digest_mismatch_marks_stale_and_keeps_entry(self):
        view = self.service.view(20000001)
        self.assertEqual(view['status'], 'reviewed')
        with closing(sqlite3.connect(self.root / 'cards.cdb')) as db:
            db.execute('UPDATE texts SET desc=? WHERE id=?', (SEARCHER + '卡文已改动。', 20000001))
            db.commit()
        self.store.reload_resources()
        self.service.reload()
        view = self.service.view(20000001)
        self.assertEqual(view['status'], 'stale')
        self.assertFalse(view['digest_ok'])
        self.assertTrue(view['effects'][0]['annotated'], '旧标注按冻结文本保留')
        fresh = self.service.search({'etags': ['etag:add-hand'], 'status': ['reviewed']})
        self.assertNotIn(20000001, [card['code'] for card in fresh['cards']])

    def test_draft_flow_and_review_statuses(self):
        made = self.service.command({'op': 'draft', 'code': 20000004})
        self.assertEqual(made['origin'], 'auto')
        view = self.service.view(20000004)
        self.assertEqual(view['status'], 'auto')
        self.assertTrue(all(effect.get('notes') for effect in view['effects'] if effect.get('annotated')))
        self.assertEqual(self.service.overview()['statuses']['auto'], 1)
        revision = made['revision']
        with self.assertRaises(ValueError):
            self.service.command({'op': 'set-review', 'code': 20000004, 'value': 'confirmed', 'revision': revision})
        pending = self.service.command({'op': 'set-review', 'code': 20000004, 'value': 'pending', 'revision': revision})
        self.assertEqual(pending['status'], 'pending')
        with self.assertRaises(ValueError):
            self.service.command({'op': 'set-review', 'code': 20000004, 'value': None, 'revision': revision})
        noted = self.service.command({'op': 'add-note', 'code': 20000004, 'key': 'p1', 'text': '人工核对备注', 'revision': revision + 1})
        self.assertEqual(noted['revision'], revision + 2)
        view = self.service.view(20000004)
        self.assertTrue(any(note['text'] == '人工核对备注' for effect in view['effects'] for note in effect.get('notes', [])))
        discarded = self.service.command({'op': 'discard-draft', 'code': 20000004, 'revision': revision + 2})
        self.assertEqual(discarded['revision'], revision + 3)
        self.assertEqual(self.service.view(20000004)['status'], 'none')

    def test_tag_overrides_apply_and_can_be_undone(self):
        revision = self.service.document['revision']
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': ['etag:draw'], 'remove': [], 'revision': revision})
        view = self.service.view(20000002)
        self.assertIn('etag:draw', view['effects'][0]['tags'])
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': [], 'remove': ['etag:draw'], 'revision': revision + 1})
        self.assertNotIn('etag:draw', self.service.view(20000002)['effects'][0]['tags'])
        self.assertIn('etag:add-hand', self.service.view(20000002)['effects'][0]['tags'])

    def test_personal_corrections_are_isolated_across_text_update_and_restart(self):
        service, code = self.service, 20000001
        service.command({'op': 'set-tags', 'code': code, 'key': 'm1', 'add': ['etag:destroy'], 'remove': ['etag:add-hand'], 'revision': 1})
        service.command({'op': 'add-note', 'code': code, 'key': 'm1', 'text': '只针对旧检索效果', 'revision': 2})
        service.command({'op': 'set-review', 'code': code, 'value': 'confirmed', 'revision': 3})
        original = deepcopy(service.document)
        new_text = '①：自己抽1张。'
        with closing(sqlite3.connect(self.root / 'cards.cdb')) as db:
            db.execute('UPDATE texts SET desc=? WHERE id=?', (new_text, code))
            db.commit()
        self.store.reload_resources()
        service.reload()
        self.assertEqual(service.view(code)['status'], 'stale')
        with self.assertRaises(ValueError):
            service.command({'op': 'add-note', 'code': code, 'key': 'm1', 'text': '不可混入新卡文', 'revision': 4})
        def update(entries):
            entries[str(code)] = make_entry(code, new_text, [simple_effect('m1', 1, ['etag:draw'], [{'action': 'draw', 'count': '1'}])])
        self.write_curated(mutate=update)
        service = CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)
        view = service.view(code)
        self.assertEqual(view['status'], 'pending')
        self.assertTrue(view['personal_review_required'])
        self.assertEqual(view['effects'][0]['tags'], ['etag:draw'])
        self.assertEqual(view['effects'][0]['notes'], [])
        self.assertEqual(view['personal_history'][0]['notes']['m1'][0]['text'], '只针对旧检索效果')
        self.assertNotIn(code, [c['code'] for c in service.search({'etags': ['etag:destroy']})['cards']])
        self.assertEqual(read_json(service.path), original, 'browsing does not rewrite old data')
        service.command({'op': 'add-note', 'code': code, 'key': 'm1', 'text': '新卡文的核对备注', 'revision': 4})
        self.assertEqual(read_json(service.backup_dir / '4.json'), original)
        service.command({'op': 'set-review', 'code': code, 'value': 'confirmed', 'revision': 5})
        restarted = CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)
        view = restarted.view(code)
        self.assertEqual(view['status'], 'confirmed')
        self.assertFalse(view['personal_review_required'])
        self.assertEqual(view['effects'][0]['notes'][0]['text'], '新卡文的核对备注')
        self.assertEqual(view['effects'][0]['tags'], ['etag:draw'])
        self.assertEqual(view['personal_history'][0]['tag_remove'], {'m1': ['etag:add-hand']})
        self.assertEqual(restarted.document['cards'][str(code)]['text_digest'], digest(new_text))

    def test_unversioned_personal_data_is_preserved_and_backed_up_before_adoption(self):
        code = 20000001
        legacy = {'version': 1, 'revision': 7, 'cards': {str(code): {
            'confirmed': True, 'pending': False, 'tag_add': {'m1': ['etag:destroy']},
            'tag_remove': {'m1': ['etag:add-hand']}, 'notes': {'m1': [{'text': '旧版备注', 'ts': 1}]}}}}
        atomic_json(self.service.path, legacy)
        self.service.reload()
        view = self.service.view(code)
        self.assertEqual(view['status'], 'pending')
        self.assertEqual(view['effects'][0]['tags'], ['etag:add-hand'])
        self.assertEqual(view['personal_history'][0], legacy['cards'][str(code)])
        self.assertEqual(read_json(self.service.path), legacy)
        self.service.command({'op': 'set-review', 'code': code, 'value': 'confirmed', 'revision': 7})
        self.assertEqual(read_json(self.service.backup_dir / '7.json'), legacy)
        saved = read_json(self.service.path)
        self.assertEqual(saved['version'], 2)
        self.assertEqual(saved['cards'][str(code)]['history'][0]['notes'], legacy['cards'][str(code)]['notes'])
        self.service.reload()
        self.assertEqual(self.service.view(code)['status'], 'confirmed')
        self.assertEqual(len(self.service.view(code)['personal_history']), 1)

    def test_failed_personal_save_does_not_mutate_memory_or_saved_data(self):
        self.service.command({'op': 'add-note', 'code': 20000001, 'key': 'm1', 'text': '保存的备注', 'revision': 1})
        before = deepcopy(self.service.document)
        def fail_current(path, value):
            if path == self.service.path: raise OSError('simulated disk write failure')
            atomic_json(path, value)
        with patch.object(self.service, 'atomic_json', side_effect=fail_current):
            with self.assertRaises(OSError):
                self.service.command({'op': 'set-review', 'code': 20000001, 'value': 'confirmed', 'revision': 2})
        self.assertEqual(self.service.document, before)
        self.assertEqual(read_json(self.service.path), before)
        self.assertEqual(read_json(self.service.backup_dir / '2.json'), before)

    def test_broad_zone_queries_only_include_explicit_child_zones(self):
        self.assertTrue(zone_matches('field', ['opponent_monster']))
        self.assertTrue(zone_matches('field', ['field_spell']))
        self.assertTrue(zone_matches('monster', ['opponent_monster']))
        self.assertTrue(zone_matches('spell', ['pendulum']))
        self.assertFalse(zone_matches('spell', ['field']))
        self.assertFalse(zone_matches('spell', ['opponent_monster']))
        self.assertFalse(zone_matches('grave', ['spell']))
        self.assertTrue(zone_matches('monster', ['extra_monster_zone']))
        self.assertTrue(zone_matches('field', ['extra_monster_zone']))
        self.assertFalse(zone_matches('extra_monster_zone', ['monster']))
        self.assertTrue(zone_matches('opponent_monster', ['opponent_extra_monster_zone']))
        self.assertTrue(zone_matches('field', ['opponent_extra_monster_zone']))
        self.assertFalse(zone_matches('extra_monster_zone', ['opponent_extra_monster_zone']))

    def test_curated_samples_query_corrected_capabilities_and_reject_regressions(self):
        path = Path(__file__).resolve().parents[1] / 'src/trainer/card-annotations.json'
        cards = json.loads(path.read_text('utf-8'))['cards']
        talent = next(e for e in cards['25311006']['effects'] if e['key'] == 'm1')
        for tag in ('etag:draw', 'etag:return-deck', 'etag:hand-look'):
            self.assertIsNotNone(self.service._effect_conditions(talent, {'etags': [tag]}))
        self.assertIsNone(self.service._effect_conditions(talent, {'etags': ['etag:add-hand']}))
        self.assertEqual(len(talent['structure']['processing'][0]['branches']), 2)
        accesscode = next(e for e in cards['86066372']['effects'] if e['key'] == 'm2')
        for zone in ('field', 'monster', 'opponent_monster', 'spell', 'pendulum', 'field_spell'):
            self.assertIsNotNone(self.service._effect_conditions(accesscode, {'action': 'destroy', 'from_zone': zone}))
        for zone in ('hand', 'grave', 'deck'):
            self.assertIsNone(self.service._effect_conditions(accesscode, {'action': 'destroy', 'from_zone': zone}))
        for effect in cards['23434538']['effects']:
            if effect.get('effect_type') == 'quick':
                self.assertTrue(effect['structure']['activation']['fast_effect'])
        broken = deepcopy(cards['23434538'])
        next(e for e in broken['effects'] if e['key'] == 'm1')['structure']['activation']['fast_effect'] = False
        with self.assertRaisesRegex(ValueError, '快速效果'):
            validate_entry(broken, self.service.registry)
        broken = deepcopy(cards['25311006'])
        next(e for e in broken['effects'] if e['key'] == 'm1')['tags'] = ['etag:draw', 'etag:add-hand']
        with self.assertRaisesRegex(ValueError, 'TAG 与处理'):
            validate_entry(broken, self.service.registry)
        broken = deepcopy(cards['14087893'])
        broken['effects'][0]['structure']['activation']['fast_effect'] = False
        with self.assertRaisesRegex(ValueError, '快速效果'):
            validate_entry(broken, self.service.registry, card_type=0x10002)

    def test_invalid_curated_data_fails_closed(self):
        self.write_curated(mutate=lambda entries: entries['20000001']['effects'][0]['tags'].append('etag:not-registered'))
        with self.assertRaises(ValueError):
            CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)
        self.write_curated(mutate=lambda entries: entries['20000001']['effects'][0].update(key='m9'))
        with self.assertRaises(ValueError):
            CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)

    def test_browsing_includes_no_effect_and_unknown_only_when_requested(self):
        regular = self.service.search({})
        self.assertIn(20000005, [card['code'] for card in regular['cards']])
        self.assertTrue(all(not card['cross_effects'] for card in regular['cards']))
        unknown = self.service.search({'catalog_scope': 'all', 'status': ['none']})
        self.assertEqual([card['code'] for card in unknown['cards']], [20000004])
        self.assertEqual(self.service.search({'status': []})['total'], 0)

    def test_stale_text_is_not_rebound_and_never_matches_abilities(self):
        self.service.command({'op': 'add-note', 'code': 20000001, 'key': 'm1', 'text': '保留备注', 'revision': 1})
        self.store.catalog.cards[20000001]['desc'] = '①：把场上1张卡破坏。'
        self.service.reload()
        view = self.service.view(20000001)
        self.assertEqual(view['effects'][0]['text'], SEARCHER)
        self.assertNotEqual(view['current_text_digest'], view['text_digest'])
        self.assertIn('保留备注', str(view['effects'][0]['notes']))
        self.assertNotIn(20000001, [card['code'] for card in self.service.search({'etags': ['etag:add-hand']})['cards']])
        self.assertEqual(self.service.search({'status': ['stale']})['total'], 1)

    def test_partial_status_is_consistent_and_tokens_are_not_unannotated(self):
        self.write_curated(mutate=lambda entries: entries['20000003']['effects'].pop(0))
        self.service.reload()
        self.assertEqual(self.service.view(20000003)['status'], 'partial')
        self.assertEqual(self.service.search({'status': ['partial']})['total'], 1)
        self.store.catalog.cards[99999999] = {'name': '测试衍生物', 'type': 0x4011, 'desc': ''}
        overview = self.service.overview()
        self.assertEqual(overview['tokens'], 1)
        self.assertEqual(overview['eligible_total'], 5)
        self.assertEqual(overview['statuses']['none'], 1)
        self.assertEqual(self.service.search({'catalog_scope': 'all'})['total'], 5)

    def test_removed_builtin_tag_can_be_restored(self):
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': [], 'remove': ['etag:add-hand'], 'revision': 1})
        self.assertNotIn('etag:add-hand', self.service.view(20000002)['effects'][0]['tags'])
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': ['etag:add-hand'], 'remove': [], 'revision': 2})
        self.assertIn('etag:add-hand', self.service.view(20000002)['effects'][0]['tags'])

    def test_registry_rejects_bad_documents(self):
        with self.assertRaises(ValueError):
            Registry({'version': 2})
        with self.assertRaises(ValueError):
            Registry({'version': 1, 'tags': [{'id': 'not-an-etag', 'name': 'x', 'definition': 'y', 'category': 'resource'}],
                      'vocabularies': {'categories': {'resource': '资源'}}})

    def test_snapshot_and_automatic_review_cannot_forge_trust(self):
        self.write_curated(mutate=lambda entries: entries['20000001'].update(frozen_text='不同的卡文'))
        with self.assertRaises(ValueError):
            self.service.reload()
        self.write_curated(mutate=lambda entries: entries['20000001']['review'].update(origin='auto'))
        with self.assertRaises(ValueError):
            self.service.reload()

    def test_draft_entry_records_evidence_only(self):
        entry = draft_entry(20000003, segments(DUAL, 0x21), '0' * 64)
        self.assertEqual(entry['review']['origin'], 'auto')
        self.assertEqual(entry['review']['status'], 'draft')
        keys = {effect['key']: effect for effect in entry['effects']}
        self.assertIn('etag:special-summon', keys['m1']['tags'])
        self.assertIn('etag:destroy', keys['m2']['tags'])
        self.assertTrue(keys['m1']['structure']['processing'][0].get('evidence'))

    def test_extra_confirmation_stays_distinct_from_main_deck_reveal(self):
        entry = make_entry(20000001, SEARCHER, [simple_effect('m1', 1, ['etag:deck-look'],
                            [{'action': 'extra_reveal', 'from_zones': ['opponent_extra'],
                              'selector': {'text': '确认对方额外卡组'}}])])
        entry['effects'][0]['effect_type'] = 'spell_activation'
        entry['effects'][0]['structure']['activation']['fast_effect'] = False
        registry = self.service.registry
        validate_entry(entry, registry, {'m1'}, card_type=2)
        for zones in ([], ['deck'], ['opponent_deck'], ['extra', 'deck']):
            invalid = deepcopy(entry)
            invalid['effects'][0]['structure']['processing'][0]['from_zones'] = zones
            with self.assertRaises(ValueError):
                validate_entry(invalid, registry, {'m1'}, card_type=2)
        self.write_curated(lambda entries: entries.update({'20000001': entry}))
        self.service.reload()
        self.assertEqual(self.service.search({'action': 'extra_reveal', 'from_zone': 'opponent_extra'})['total'], 1)
        self.assertEqual(self.service.search({'action': 'deck_reveal', 'from_zone': 'opponent_extra'})['total'], 0)

    def test_dynamic_damage_preserves_formula_without_evaluation(self):
        entry = make_entry(20000001, SEARCHER, [simple_effect('m1', 1, ['etag:effect-damage'],
                    [{'action': 'burn', 'recipient': 'opponent',
                      'amount_rule': {'text': '处理时对方场上卡数乘400', 'evaluated_at': 'resolution'}}])])
        entry['effects'][0]['effect_type'] = 'spell_activation'
        entry['effects'][0]['structure']['activation']['fast_effect'] = False
        validate_entry(entry, self.service.registry, {'m1'}, card_type=2)
        for rule in ({'text': '400', 'evaluated_at': 'activation'},
                     {'text': '', 'evaluated_at': 'resolution'},
                     {'text': '400', 'evaluated_at': 'resolution', 'execute': True}):
            invalid = deepcopy(entry)
            invalid['effects'][0]['structure']['processing'][0]['amount_rule'] = rule
            with self.assertRaises(ValueError):
                validate_entry(invalid, self.service.registry, {'m1'}, card_type=2)
        invalid = deepcopy(entry)
        invalid['effects'][0]['structure']['processing'][0]['amount'] = 400
        with self.assertRaises(ValueError):
            validate_entry(invalid, self.service.registry, {'m1'}, card_type=2)

    def test_distinct_usage_scopes_and_additive_attribute(self):
        effect = simple_effect('m1', 1, ['etag:stat-change'],
                              [{'action': 'change_attribute', 'selector': {'text': '追加光，保留暗'},
                                'from_zones': ['monster'], 'count': 1, 'mode': 'add', 'attribute': 'light',
                                'attribute_selection': 'fixed', 'duration': '表侧存在期间'}],
                              ['battle_step_once', 'name_duel_once', 'chain_once'])
        effect['effect_type'] = 'ignition'
        entry = make_entry(20000003, DUAL, [effect])
        validate_entry(entry, self.service.registry, card_type=0x21)
        invalid = deepcopy(entry)
        invalid['effects'][0]['structure']['processing'][0]['mode'] = 'replace_and_add'
        with self.assertRaises(ValueError):
            validate_entry(invalid, self.service.registry, card_type=0x21)

    def test_folders_apply_effect_filters_and_card_counts_without_changing_personal_data(self):
        before = json.dumps(self.service.document, sort_keys=True)
        query = {'catalog_scope': 'all', 'etags': ['etag:add-hand'], 'from_zone': 'grave'}
        flat = self.service.search(query)
        grouped = self.service.search({**query, 'group_by': 'series'})
        self.assertEqual(grouped['total'], flat['total'])
        for folder in grouped['folders']:
            cards = self.service.search({**query, 'series': folder['id']})
            self.assertEqual(cards['total'], folder['count'])
            self.assertIn(folder['cover_code'], [c['code'] for c in cards['cards']])
        self.assertEqual(json.dumps(self.service.document, sort_keys=True), before)

    def test_unknown_folder_is_rejected_and_catalog_reload_updates_membership(self):
        with self.assertRaises(ValueError):
            self.service.search({'series': 'set:missing'})
        with self.assertRaises(ValueError):
            self.service.search({'series': ['set:dd']})
        with closing(sqlite3.connect(self.root / 'cards.cdb')) as db:
            db.execute('UPDATE datas SET setcode=? WHERE id=?', (0x172, 20000001))
            db.commit()
        self.store.reload_resources()
        self.service.reload()
        view = self.service.view(20000001)
        self.assertEqual(view['series'][0]['name'], '驱魔姐妹')
        self.assertEqual(self.service.search({'q': '救祓少女'})['cards'][0]['code'], 20000001)


if __name__ == '__main__':
    unittest.main()
