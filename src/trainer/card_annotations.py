"""Unified per-effect card annotations: segmentation, tags, structure, coverage and query.

This module holds STATIC capability knowledge: what a card's printed text says.
Whether an effect can be activated, will resolve or forms a combo in a live
duel stays with the rule engine and recorded state; a tag hit is never an
activation verdict (docs/card-annotation-system.md).

Identity rules mirror the rest of the toolbox: cards are integer codes from
the installed catalog, effect keys are stable per frozen card text, and every
annotation is validated against the current text digest (fail-closed like
card_semantics.AUDITED_EFFECTS).
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from card_semantics import AUDITED_EFFECTS, CIRCLED
from card_series import CardSeries

CLAUSE = re.compile(r'(?m)(?:^|(?<=[。]))[ \t]*([' + CIRCLED + r'])\s*[:：]')
PENDULUM_MONSTER_MARKER = re.compile(r'【怪兽(?:效果|描述)】')
PENDULUM_HEADER = re.compile(r'(?m)^[^\n]*【灵摆】[^\n]*$')
TAG_ID = re.compile(r'etag:[a-z0-9-]+')
HEX64 = re.compile(r'[0-9a-f]{64}')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
RELATION_KINDS = {'material_rule', 'summon_condition', 'shared_limit', 'usage_limit_group',
                  'exclusive_choice', 'choose_branch', 'order', 'depends_on'}
STATUSES = ('none', 'auto', 'partial', 'reviewed', 'confirmed', 'pending', 'stale')
CONDITION_FIELDS = ('action', 'from_zone', 'to_zone', 'usage', 'cost_kind', 'timing')

# Only promote explicitly recorded child zones to a broader query. A generic
# field annotation never proves that a particular child zone is eligible.
ZONE_GROUPS = {'field': {'monster', 'opponent_monster', 'extra_monster_zone', 'opponent_extra_monster_zone', 'spell', 'pendulum', 'field_spell'},
               'monster': {'opponent_monster', 'extra_monster_zone', 'opponent_extra_monster_zone'},
               'opponent_monster': {'opponent_extra_monster_zone'}, 'spell': {'pendulum'}}
ACTION_TAGS = {'add_hand': 'etag:add-hand', 'draw': 'etag:draw', 'return_deck': 'etag:return-deck',
               'return_hand': 'etag:add-hand',
               'return_unsummoned': 'etag:add-hand',
               'hand_reveal': 'etag:hand-look', 'deck_reveal': 'etag:deck-look',
               'destroy': 'etag:destroy', 'banish': 'etag:banish', 'send_grave': 'etag:send-grave',
               'special_summon': 'etag:special-summon', 'normal_summon': 'etag:normal-summon',
               'negate_effect': 'etag:negate-effect', 'negate_activation': 'etag:negate-activation',
               'burn': 'etag:effect-damage', 'heal': 'etag:recover-lp',
               'prevent_damage': 'etag:prevent-damage', 'place_deck_top': 'etag:deck-look',
               'place_deck_bottom': 'etag:deck-look', 'shuffle_deck': 'etag:deck-look',
               'convert_battle_damage': 'etag:effect-damage'}


def zone_matches(query, zones):
    return bool(({query} | ZONE_GROUPS.get(query, set())) & set(zones or []))


def _processing_nodes(items, include_granted=True):
    """Walk processing paths; fixed grants can form a separate effect boundary."""
    for index, item in enumerate(items or []):
        yield str(index), item
        if include_granted or 'granted_effect' not in item:
            for sub_index, sub in _processing_nodes(item.get('then'), include_granted):
                yield f'{index}.then.{sub_index}', sub
        for branch_index, branch in enumerate(item.get('branches') or []):
            for sub_index, sub in _processing_nodes(branch.get('actions'), include_granted):
                yield f'{index}.branch{branch_index}.{sub_index}', sub
            for sub_index, sub in _processing_nodes(branch.get('then'), include_granted):
                yield f'{index}.branch{branch_index}.then.{sub_index}', sub


def processing_actions(items):
    for _, item in _processing_nodes(items):
        yield item['action']

# Implied destinations keep queries honest when an annotation omits to_zones:
# the action itself names the zone it moves a card to.
DEFAULT_DESTINATION = {'add_hand': 'hand', 'draw': 'hand', 'special_summon': 'monster',
                       'normal_summon': 'monster', 'return_deck': 'deck', 'banish': 'banished',
                       'send_grave': 'grave'}

# Draft patterns are deliberately conservative: they propose candidates with
# the matched snippet as evidence and never mark anything reviewed.
DRAFT_PATTERNS = (
    (re.compile(r'(?:从|在)[^。；\n]{0,16}?(卡组|墓地|除外|额外卡组)[^。；\n]{0,24}?(?:加入手[卡牌]|回到手[卡牌])'), 'add_hand_source'),
    (re.compile(r'(?:加入手[卡牌]|回到手[卡牌])'), 'add_hand'),
    (re.compile(r'特殊召唤'), 'special_summon'),
    (re.compile(r'进行[^。；\n]{0,8}召唤'), 'normal_summon'),
    (re.compile(r'破坏'), 'destroy'),
    (re.compile(r'(?!除外状态)[^。；\n]{0,24}除外'), 'banish'),
    (re.compile(r'发动[^。；\n]{0,8}?无效'), 'negate_activation'),
    (re.compile(r'无效'), 'negate_effect'),
    (re.compile(r'(?:回到|放回)[^。；\n]{0,12}卡组'), 'return_deck'),
    (re.compile(r'确认[^。；\n]{0,8}?手卡|观看[^。；\n]{0,8}?手卡'), 'hand_reveal'),
    (re.compile(r'翻开'), 'deck_reveal'),
    (re.compile(r'这个卡名[^。；\n]{0,16}?1回合[^。；\n]{0,10}?只能[^。；\n]{0,12}?1次'), 'name_limit'),
)
DRAFT_TAG = {'add_hand': 'etag:add-hand', 'add_hand_source': 'etag:add-hand',
             'special_summon': 'etag:special-summon', 'normal_summon': 'etag:normal-summon',
             'destroy': 'etag:destroy', 'banish': 'etag:banish',
             'negate_effect': 'etag:negate-effect', 'negate_activation': 'etag:negate-activation',
             'return_deck': 'etag:return-deck', 'hand_reveal': 'etag:hand-look',
             'deck_reveal': 'etag:deck-look'}
DRAFT_SOURCE_ZONE = {'卡组': 'deck', '墓地': 'grave', '除外': 'banished', '额外卡组': 'extra'}


def digest(text):
    """Same normalization as card_semantics.effect_clause so AUDITED digests align."""
    return hashlib.sha256((text or '').replace('\r\n', '\n').strip().encode('utf-8')).hexdigest()


def block_segments(block, prefix, out):
    if not block.strip(): return
    matches = list(CLAUSE.finditer(block))
    numbers = [CIRCLED.index(match[1]) + 1 for match in matches]
    if numbers and len(set(numbers)) == len(numbers):
        leading = block[:matches[0].start()].strip()
        if leading:
            out.append({'key': f'{prefix}-pre', 'block': prefix, 'number': None, 'kind': 'unnumbered', 'text': leading})
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
            number = numbers[index]
            out.append({'key': f'{prefix}{number}', 'block': prefix, 'number': number, 'kind': 'numbered',
                        'text': block[match.start():end].strip()})
    else:
        out.append({'key': f'{prefix}-all', 'block': prefix, 'number': None,
                    'kind': 'ambiguous' if numbers else 'unnumbered', 'text': block.strip()})


def segments(desc, card_type):
    """Split frozen card text into stable per-effect segments (p*/m* keys)."""
    text = (desc or '').replace('\r\n', '\n').strip()
    result = []
    if card_type & 0x1000000:
        marker = PENDULUM_MONSTER_MARKER.search(text)
        pendulum, monster = (text[:marker.start()], text[marker.end():]) if marker else (text, '')
        block_segments(PENDULUM_HEADER.sub('', pendulum).strip(), 'p', result)
        block_segments(monster.strip(), 'm', result)
    else:
        block_segments(text, 'm', result)
    return result


class Registry:
    """Generic effect tags and controlled vocabularies, shared by every annotator."""

    def __init__(self, document):
        if document.get('version') != 1: raise ValueError('效果 TAG 词表版本不受支持')
        self.updated_on = document.get('updated_on', '')
        self.categories = document.get('vocabularies', {}).get('categories', {})
        self.tags = {}
        for tag in document.get('tags', []):
            identifier = tag.get('id', '')
            if not TAG_ID.fullmatch(identifier) or identifier in self.tags: raise ValueError(f'效果 TAG 编号无效：{identifier}')
            if tag.get('category') not in self.categories: raise ValueError(f'效果 TAG 分类无效：{identifier}')
            if not tag.get('name') or not tag.get('definition'): raise ValueError(f'效果 TAG 缺少名称或定义：{identifier}')
            self.tags[identifier] = tag
        self.vocab = {}
        for name, values in document.get('vocabularies', {}).items():
            if name == 'categories': continue
            if not isinstance(values, dict) or not values: raise ValueError(f'受控词表无效：{name}')
            self.vocab[name] = values

    def require(self, vocabulary, value, where):
        values = self.vocab.get(vocabulary)
        if values is None or not isinstance(value, str) or value not in values:
            raise ValueError(f'{where}使用了未登记的{vocabulary}取值：{value}')
        return value

    def zone_label(self, value): return self.vocab.get('zones', {}).get(value, value)
    def action_label(self, value): return self.vocab.get('actions', {}).get(value, value)
    def usage_label(self, value): return self.vocab.get('usage_limits', {}).get(value, value)
    def tag_order(self, tag): return (self.tags[tag]['name'], tag)


def _check_text(value, where, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{where}文本无效')
    return value.strip()


def _check_notes(value, where):
    if not isinstance(value, list): raise ValueError(f'{where}备注无效')
    for item in value:
        if not isinstance(item, dict): raise ValueError(f'{where}备注格式无效')
        _check_text(item.get('text', ''), f'{where}备注')
        refs = item.get('source_refs', [])
        if not isinstance(refs, list) or any(not isinstance(r, str) or len(r) > 600 for r in refs):
            raise ValueError(f'{where}备注来源无效')


def _check_rule_action(item, where):
    """Parameters that distinguish the newer rule/support actions from other abilities."""
    action = item['action']
    supported = {'remove_counter', 'place_deck_top', 'reveal_set_cards', 'change_hand_limit',
                 'skip_phase', 'advance_turn_count', 'repeat_phase', 'redirect_spell_recipient',
                 'change_race', 'activate_field_spell', 'reveal_drawn_cards', 'reverse_stat_modifiers',
                 'reroll_dice', 'move_to_end_phase', 'redirect_spell_target', 'toss_coin', 'roll_dice',
                 'add_to_extra_faceup', 'set_lp', 'replace_draw_with_discard', 'redirect_effect_damage',
                 'place_deck_bottom', 'increase_pendulum_summon_limit', 'win_duel',
                 'place_and_use_spell', 'return_to_field'}
    supported.update({'skip_turn', 'swap_lp', 'change_attribute', 'change_equip_target', 'shuffle_deck',
                      'require_attack_return', 'convert_battle_damage', 'reverse_coin_effect',
                      'require_player_send_grave', 'replace_damage_with_recovery', 'perform_battle_damage_calculation'})
    if action not in supported: return
    where = f'{where} {action}'
    _check_text((item.get('selector') or {}).get('text', ''), f'{where}选择器')
    def integer(field, minimum=1):
        if type(item.get(field)) is not int or item[field] < minimum:
            raise ValueError(f'{where} {field}须为不小于{minimum}的整数')
    def choice(field, values):
        if not isinstance(item.get(field), str) or item[field] not in values:
            raise ValueError(f'{where} {field}取值无效')
    def text_field(field): _check_text(item.get(field, ''), f'{where} {field}', 400)
    def boolean(field):
        if type(item.get(field)) is not bool: raise ValueError(f'{where} {field}须为布尔值')
    players = {'self', 'opponent', 'both'}
    if action == 'reverse_coin_effect':
        if item.get('from_zones') != ['monster']:
            raise ValueError(f'{where}须登记己方怪兽区来源')
        integer('count')
        if item['count'] != 1: raise ValueError(f'{where}只处理1只对象')
        choice('mode', {'swap_current_heads_tails_effects'})
        if item.get('requires_actual_coin_effect') is not True or item.get('new_coin_toss') is not False:
            raise ValueError(f'{where}须有实际投币获赋效果且不重新投币')
        return
    if action == 'require_player_send_grave':
        affected = item.get('players')
        if not isinstance(affected, list) or not affected or any(type(p) is not str for p in affected) \
                or len(set(affected)) != len(affected) or not set(affected) <= {'self', 'opponent'}:
            raise ValueError(f'{where}须明确不重复的适用玩家')
        expected_from = {'monster' if p == 'self' else 'opponent_monster' for p in affected}
        expected_to = {'grave', 'opponent_grave'}
        if set(item.get('from_zones') or []) != expected_from or set(item.get('to_zones') or []) != expected_to:
            raise ValueError(f'{where}玩家须对应来源，墓地去向须保留持有者两种可能')
        choice('destination_rule', {'each_sent_cards_owner_grave'})
        choice('remaining_rule', {'one_attribute_per_player', 'one_monster'})
        choice('selection_order', {'turn_player_first'} if len(affected) == 2 else {'affected_player'})
        if item.get('simultaneous') is not True or item.get('is_effect_movement') is not False \
                or item.get('respects_monster_immunity') is not False or 'count' in item:
            raise ValueError(f'{where}须明确同时、作用于玩家、非效果移动且不编造固定数量')
        return
    if action == 'replace_damage_with_recovery':
        choice('recipient', {'self'})
        choice('source_effect', {'directly_chained_opponent_effect', 'battle_and_effect_damage_this_turn'})
        if item.get('preserves_other_processing') is not True or 'amount' in item:
            raise ValueError(f'{where}须保留来源其他处理且不编造固定回复量')
        if item['source_effect'] == 'directly_chained_opponent_effect':
            choice('applies_at', {'source_effect_resolution'})
        else:
            choice('applies_at', {'each_damage_event'})
            text_field('duration')
        return
    if action == 'perform_battle_damage_calculation':
        if item.get('from_zones') != ['opponent_monster'] or 'to_zones' in item:
            raise ValueError(f'{where}须明确两只对方怪兽且不登记区域移动')
        choice('attacker_rule', {'second_direct_attacker_this_battle_phase'})
        choice('defender_rule', {'first_direct_attacker_this_battle_phase'})
        if item.get('requires_distinct_instances') is not True or item.get('is_effect_damage') is not False:
            raise ValueError(f'{where}须为不同实例的战斗计算，不能冒充效果伤害')
        return
    if action == 'require_attack_return':
        if not item.get('from_zones') or not set(item['from_zones']) <= {'field'} | ZONE_GROUPS['field']:
            raise ValueError(f'{where}须明确场上来源')
        if not item.get('to_zones') or not set(item['to_zones']) <= {'hand', 'opponent_hand'}:
            raise ValueError(f'{where}须实际返回持有者手卡')
        integer('count')
        if item['count'] != 1 or item.get('exclude_source_instance') is not True:
            raise ValueError(f'{where}须返回1张本卡实例以外的卡')
        choice('executor', {'self'})
        choice('payment_timing', {'attack_declaration'})
        if item.get('is_effect_movement') is not False:
            raise ValueError(f'{where}攻击手续不是效果移动')
        return
    if action == 'convert_battle_damage':
        if item.get('from_zones') != ['monster'] or 'to_zones' in item:
            raise ValueError(f'{where}须明确本卡怪兽区来源且不登记卡片去向')
        integer('count')
        if item['count'] != 1 or 'amount' in item:
            raise ValueError(f'{where}须为本卡1只的伤害性质变更，不是固定数值伤害')
        choice('source_damage', {'battle'})
        choice('result_damage', {'effect'})
        choice('damage_source', {'this_card'})
        choice('recipient', {'opponent'})
        if item.get('creates_chain') is not False:
            raise ValueError(f'{where}伤害性质变更不新建连锁')
        return
    if action == 'shuffle_deck':
        choice('executor', players)
        if not item.get('from_zones') or not set(item['from_zones']) <= {'deck', 'opponent_deck'}:
            raise ValueError(f'{where}须明确洗切哪一方的卡组')
        if 'to_zones' in item or ('count' in item and item['count'] != 'all'):
            raise ValueError(f'{where}洗切整副卡组，不移动指定数量的卡')
        return
    if action in {'change_attribute', 'change_equip_target'}:
        if not item.get('from_zones'): raise ValueError(f'{where}须登记from_zones')
        if item.get('count') != 'all': integer('count')
        if action == 'change_attribute':
            choice('attribute_selection', {'activation', 'resolution', 'fixed'})
            text_field('duration')
            if item['attribute_selection'] == 'fixed':
                choice('attribute', {'earth', 'water', 'fire', 'wind', 'light', 'dark', 'divine'})
            elif 'attribute' in item:
                raise ValueError(f'{where}按时点选择属性时不能又写固定attribute')
        else:
            if not set(item['from_zones']) <= {'field'} | ZONE_GROUPS['field']:
                raise ValueError(f'{where}须选择场上已存在的装备卡')
            if item.get('keeps_controller') is not True or 'to_zones' in item:
                raise ValueError(f'{where}只改变装备对象，保持控制权且不登记区域移动')
        return
    if action == 'skip_turn':
        choice('player', players)
        integer('count')
        text_field('duration')
        choice('stacking', {'non_cumulative', 'cumulative'})
        return
    if action == 'swap_lp':
        sides = item.get('players')
        if not isinstance(sides, list) or len(sides) != 2 or any(not isinstance(side, str) for side in sides) \
                or set(sides) != {'self', 'opponent'}:
            raise ValueError(f'{where} players须明确自己与对方各一次')
        return
    if action in {'remove_counter', 'place_deck_top', 'place_deck_bottom', 'reveal_set_cards', 'change_race',
                  'activate_field_spell', 'redirect_spell_target', 'add_to_extra_faceup',
                  'replace_draw_with_discard', 'increase_pendulum_summon_limit',
                  'place_and_use_spell', 'return_to_field'} and not item.get('from_zones'):
        raise ValueError(f'{where}须登记 from_zones')
    if action in {'remove_counter', 'place_deck_top', 'place_deck_bottom', 'reveal_set_cards', 'change_race'}:
        if item.get('count') != 'all': integer('count')
    if action in {'change_hand_limit', 'skip_phase', 'repeat_phase', 'change_race',
                  'reveal_drawn_cards', 'reverse_stat_modifiers', 'reroll_dice', 'move_to_end_phase',
                  'redirect_effect_damage'}:
        text_field('duration')
    if action in {'skip_phase', 'repeat_phase', 'reveal_drawn_cards', 'reroll_dice'}:
        choice('player', players)
    if action == 'remove_counter': text_field('counter_type')
    elif action in {'place_deck_top', 'place_deck_bottom'}:
        choice('executor', players)
        destinations = {'deck_top', 'opponent_deck_top'} if action == 'place_deck_top' else {'deck_bottom', 'opponent_deck_bottom'}
        if not item.get('to_zones') or not set(item['to_zones']) <= destinations:
            raise ValueError(f'{where} to_zones须为对应的卡组顶／底区域')
        boolean('shuffle_before_placement')
        if 'inspects_opponent_deck' in item: boolean('inspects_opponent_deck')
    elif action == 'reveal_set_cards':
        choice('controller', players)
        choice('audience', players)
        if item.get('changes_position') is not False:
            raise ValueError(f'{where} changes_position须为false，不改变表示形式')
    elif action == 'change_hand_limit':
        choice('recipient', players)
        integer('value', 0)
    elif action in {'skip_phase', 'repeat_phase'}:
        choice('phase', {'draw', 'standby', 'main1', 'battle', 'main2', 'end'})
        integer('count', 2 if action == 'repeat_phase' else 1)
    elif action == 'advance_turn_count':
        integer('amount')
        integer('count')
    elif action in {'redirect_spell_recipient', 'redirect_spell_target'}:
        choice('source_activation', {'spell_card_activation'})
        integer('count')
        if item['count'] != 1: raise ValueError(f'{where}只对应一个适用者或卡片对象')
        if action == 'redirect_spell_recipient': choice('recipient_rule', {'other_player'})
        else:
            choice('original_target_kind', {'monster', 'spell_trap', 'card'})
            choice('new_target_rule', {'different_legal_target'})
    elif action == 'change_race':
        text_field('race')
        boolean('applies_to_later_monsters')
    elif action == 'activate_field_spell':
        integer('count')
        if item['count'] != 1 or item.get('to_zones') != ['field_spell']:
            raise ValueError(f'{where}须发动1张卡到 field_spell')
        if item.get('resolve_activation_effect') is not False:
            raise ValueError(f'{where} resolve_activation_effect须为false')
    elif action == 'reverse_stat_modifiers':
        stats = item.get('stats')
        if not isinstance(stats, list) or not stats or any(v not in ('atk', 'def') for v in stats) or len(set(stats)) != len(stats):
            raise ValueError(f'{where} stats须为不重复的atk/def列表')
    elif action == 'reroll_dice':
        integer('applications')
        choice('dice_scope', {'entire_dice_procedure'})
        choice('stacking', {'non_cumulative', 'cumulative'})
        if 'optional' in item: boolean('optional')
    elif action == 'move_to_end_phase': choice('phase', {'end'})
    elif action in {'toss_coin', 'roll_dice'}:
        choice('executor', players)
        if action == 'toss_coin': integer('count')
        else:
            integer('rolls')
            integer('faces')
            if item['faces'] != 6: raise ValueError(f'{where}须使用六面骰')
            text_field('result')
        branches = item.get('branches') or []
        if not isinstance(branches, list): raise ValueError(f'{where}随机结果分支须为列表')
        if not item.get('then') and (len(branches) < 2 or any(not isinstance(b, dict) or not b.get('actions') for b in branches)):
            raise ValueError(f'{where}须登记随机结果的后续处理或至少两个结果分支')
    elif action == 'add_to_extra_faceup':
        integer('count')
        if item.get('to_zones') != ['extra_faceup']:
            raise ValueError(f'{where} to_zones须为extra_faceup')
        if 'shuffle_source_after' in item: boolean('shuffle_source_after')
    elif action == 'set_lp':
        choice('recipient', players)
        if ('amount' in item) == ('amount_rule' in item):
            raise ValueError(f'{where}须恰好一种固定amount或动态amount_rule')
        if 'amount_rule' in item:
            rule = item['amount_rule']
            if not isinstance(rule, dict) or set(rule) != {'text', 'evaluated_at'} \
                    or rule.get('evaluated_at') != 'resolution':
                raise ValueError(f'{where}动态LP规则须有文字依据及resolution时点')
            _check_text(rule.get('text'), f'{where}动态LP依据', 400)
        else:
            integer('amount', 0)
    elif action == 'replace_draw_with_discard':
        choice('source_activation', {'draw_only_effect'})
        choice('quantity', {'cards_that_would_be_drawn'})
        choice('reveal_to', {'both'})
        if item.get('counts_as_draw') is not False or item.get('cards_enter_hand') is not False:
            raise ValueError(f'{where}既不算抽卡也不经过手卡')
        if not set(item['from_zones']) <= {'deck_top', 'opponent_deck_top'} or not item.get('to_zones') \
                or not set(item['to_zones']) <= {'grave', 'opponent_grave'}:
            raise ValueError(f'{where}须从卡组顶直接丢去墓地')
    elif action == 'redirect_effect_damage':
        choice('source_player', players)
        choice('recipient', players)
        choice('source_effect', {'activated', 'continuous', 'all'})
    elif action == 'increase_pendulum_summon_limit':
        choice('executor', players)
        integer('count')
        text_field('duration')
        if not set(item['from_zones']) <= {'hand', 'extra_faceup'}:
            raise ValueError(f'{where}须明确hand或extra_faceup的灵摆召唤来源')
    elif action == 'win_duel':
        choice('recipient', {'self', 'opponent'})
        boolean('delayed')
        boolean('creates_chain')
        text_field('resolution_timing')
        turn_fields = ('turn_count', 'count_both_players_turns', 'start_turn_inclusive')
        if any(field in item for field in turn_fields):
            if not all(field in item for field in turn_fields):
                raise ValueError(f'{where}回合计数的turn_count及两个计数标志须成组登记')
            integer('turn_count')
            boolean('count_both_players_turns')
            boolean('start_turn_inclusive')
    elif action == 'place_and_use_spell':
        choice('executor', {'self', 'opponent'})
        integer('count')
        if item['count'] != 1 or not item.get('to_zones') or not set(item['to_zones']) <= {'spell', 'field_spell'}:
            raise ValueError(f'{where}须将1张魔法本体置于spell或field_spell')
        choice('used_spell_cost_timing', {'resolution'})
        choice('used_spell_targeting_timing', {'resolution'})
    elif action == 'return_to_field':
        if item.get('count') != 'all': integer('count')
        if item['from_zones'] != ['banished'] or not item.get('to_zones') \
                or not set(item['to_zones']) <= {'field'} | ZONE_GROUPS['field']:
            raise ValueError(f'{where}须从banished返回场上区域')
        text_field('position')
        text_field('resolution_timing')
        boolean('delayed')
        if item.get('creates_chain') is not False or item.get('counts_as_special_summon') is not False:
            raise ValueError(f'{where}回场不新建连锁且不算特殊召唤')
    if action in {'reveal_set_cards', 'redirect_spell_target'}:
        if not set(item['from_zones']) <= {'field'} | ZONE_GROUPS['field']:
            raise ValueError(f'{where}来源必须是场上区域')


def _check_processing(items, registry, where, reviewed=False, card_type=None):
    if not isinstance(items, list): raise ValueError(f'{where}处理无效')
    for item in items:
        if not isinstance(item, dict): raise ValueError(f'{where}处理项无效')
        registry.require('actions', item.get('action'), where)
        if 'recipient_rule' in item:
            _check_text(item['recipient_rule'], f'{where}受影响玩家规则', 400)
            if 'recipient' in item:
                raise ValueError(f'{where}事件决定的玩家规则不能同时指定固定recipient')
        if item.get('action') == 'lock':
            for qualifier in ('self_only', 'summon_response_only', 'attack_response_only'):
                if qualifier in item and type(item[qualifier]) is not bool:
                    raise ValueError(f'{where}限制范围 {qualifier} 须为布尔值')
        count = item.get('count')
        if count is not None and not (isinstance(count, int) or count in ('all', 'up_to_1') or re.fullmatch(r'\d+', str(count))):
            raise ValueError(f'{where}数量无效')
        for field in ('from_zones', 'to_zones'):
            zones = item.get(field)
            if zones is not None:
                if not isinstance(zones, list) or not zones: raise ValueError(f'{where}{field}无效')
                for zone in zones: registry.require('zones', zone, where)
        selector = item.get('selector')
        if selector is not None and (not isinstance(selector, dict) or not selector.get('text')):
            raise ValueError(f'{where}选择器缺少文字说明')
        _check_rule_action(item, where)
        granted = item.get('granted_effect')
        if 'granted_effect' in item:
            if item['action'] != 'grant_effect' or not isinstance(granted, dict):
                raise ValueError(f'{where}固定获赋效果只能登记在 grant_effect 中')
            _check_effect_payload(granted, registry, f'{where}固定获赋效果', reviewed, card_type, fixed=True)
            if item.get('then') != granted['structure']['processing']:
                raise ValueError(f'{where}获赋效果的 then 与固定处理树不一致')
        elif item.get('then') is not None:
            _check_processing(item['then'], registry, f'{where}后续', reviewed, card_type)
        if item.get('branches') is not None:
            branches = item['branches']
            if not isinstance(branches, list): raise ValueError(f'{where}分支无效')
            for branch in branches:
                if not isinstance(branch, dict): raise ValueError(f'{where}分支格式无效')
                _check_text(branch.get('condition', '分支'), f'{where}分支条件', 400)
                _check_processing(branch.get('actions', []), registry, f'{where}分支', reviewed, card_type)
                if branch.get('then') is not None:
                    _check_processing(branch['then'], registry, f'{where}分支后续', reviewed, card_type)
        if item.get('action') == 'choose_branch':
            branches = item.get('branches') or []
            if len(branches) < 2 or any(not branch.get('actions') for branch in branches):
                raise ValueError(f'{where}互斥分支必须至少有两个非空选项')
        if item.get('action') == 'use_as_fusion_material':
            if not item.get('from_zones') or not any(next_action.get('action') == 'special_summon'
                                                      for next_action in item.get('then', [])):
                raise ValueError(f'{where}融合素材处理须登记来源和后续融合召唤')
        if item.get('action') == 'use_as_ritual_material':
            if not item.get('from_zones') or not any(next_action.get('action') == 'special_summon'
                                                      for next_action in item.get('then', [])):
                raise ValueError(f'{where}仪式素材处理须登记来源和后续仪式召唤')
        if item.get('action') == 'use_as_synchro_material':
            if 'monster' not in item.get('from_zones', []) or not any(next_action.get('action') == 'special_summon'
                                                    for next_action in item.get('then', [])):
                raise ValueError(f'{where}同调素材处理须登记场上来源和后续同调召唤')
        if item.get('action') == 'use_as_link_material':
            if 'monster' not in item.get('from_zones', []) or not any(next_action.get('action') == 'special_summon'
                                                    for next_action in item.get('then', [])):
                raise ValueError(f'{where}连接素材处理须登记场上来源和后续连接召唤')
        if item.get('action') == 'use_as_xyz_material':
            if 'monster' not in item.get('from_zones', []) or not any(next_action.get('action') == 'special_summon'
                                                    for next_action in item.get('then', [])):
                raise ValueError(f'{where}超量素材处理须登记场上来源和后续超量召唤')
        if item.get('action') == 'treat_as_tuner' and not item.get('duration'):
            raise ValueError(f'{where}调整化须登记适用时限')
        if item.get('action') == 'change_level' and not item.get('duration'):
            raise ValueError(f'{where}等级变更须登记适用时限')
        if item.get('action') == 'attack_in_defense' and item.get('damage_calculation_stat', 'atk') not in ('atk', 'def'):
            raise ValueError(f'{where}守备表示攻击的伤害计算数值须为 atk 或 def')
        if item.get('action') == 'place_pendulum' and (not item.get('from_zones') or item.get('to_zones') != ['pendulum']):
            raise ValueError(f'{where}灵摆区放置须登记来源和灵摆区域去向')
        if item.get('action') == 'redirect_attack' and not (item.get('selector') or {}).get('text'):
            raise ValueError(f'{where}攻击转移须登记新的攻击对象')
        if item.get('action') == 'copy_effect' and (not item.get('from_zones') or not item.get('duration')
                                                  or not (item.get('selector') or {}).get('text')):
            raise ValueError(f'{where}效果复制须登记对象来源和适用时限')
        if item.get('action') == 'prevent_damage' and (item.get('damage_scope') not in ('battle', 'effect', 'battle_and_effect')
                                                     or item.get('recipient') not in ('self', 'opponent', 'both')
                                                     or not item.get('duration')):
            raise ValueError(f'{where}伤害防止须登记伤害范围、承受者和适用时限')
        if item.get('action') == 'treat_as_name' and not item.get('from_zones'):
            raise ValueError(f'{where}名称视作须登记适用区域')
        if item.get('action') == 'place_counter' and not item.get('count'):
            raise ValueError(f'{where}放置指示物须登记数量')
        if item.get('action') == 'give_control' and ('monster' not in item.get('from_zones', []) or 'opponent_monster' not in item.get('to_zones', [])):
            raise ValueError(f'{where}移交控制权须登记己方怪兽区来源和对方怪兽区去向')
        if item.get('action') == 'require_lp_payment' and item.get('executor') not in ('self', 'opponent'):
            raise ValueError(f'{where}支付基本分处理须登记执行者')
        if item.get('action') == 'return_grave' and ('banished' not in item.get('from_zones', []) or 'grave' not in item.get('to_zones', [])):
            raise ValueError(f'{where}除外卡回墓地须登记除外区来源和墓地去向')
        if item.get('action') == 'increase_normal_summon_limit' and not item.get('duration'):
            raise ValueError(f'{where}通常召唤次数增加须登记适用时限')
        if item.get('action') == 'substitute_tribute_cost' and ('grave' not in item.get('from_zones', []) or 'banished' not in item.get('to_zones', [])):
            raise ValueError(f'{where}解放费用替代须登记墓地来源及除外去向')
        if item.get('action') == 'return_unsummoned' and not {'hand', 'extra'} & set(item.get('to_zones', [])):
            raise ValueError(f'{where}被无效召唤怪兽回手须登记手卡或额外卡组去向')
        if item.get('action') == 'substitute_detach_source' and 'xyz_material' not in item.get('from_zones', []):
            raise ValueError(f'{where}超量取除来源替代须登记素材区域')
        if item.get('action') == 'return_hand' and not {'field', 'monster', 'opponent_monster', 'extra_monster_zone', 'opponent_extra_monster_zone', 'spell', 'field_spell', 'pendulum'} & set(item.get('from_zones', [])):
            raise ValueError(f'{where}场上卡回手须登记场上来源')
        if item.get('action') == 'equip_as_spell' and (not item.get('from_zones') or 'spell' not in item.get('to_zones', [])):
            raise ValueError(f'{where}怪兽作装备卡须登记来源与魔陷区去向')
        if item.get('action') == 'grant_effect' and not item.get('then'):
            raise ValueError(f'{where}赋予效果须登记未来处理')
        if item.get('action') == 'place_faceup_card' and 'spell' not in item.get('to_zones', []):
            raise ValueError(f'{where}表侧放置永续魔陷须登记魔陷区去向')
        if item.get('action') == 'tribute' and not item.get('from_zones'):
            raise ValueError(f'{where}处理时解放须登记来源区域')
        for restriction in item.get('restrictions', []):
            _check_text(restriction, f'{where}限制', 400)


def _check_effect_payload(effect, registry, where, reviewed=False, card_type=None, fixed=False):
    """Validate the same semantic fields for segments and known granted effects."""
    effect_type = effect.get('effect_type')
    if fixed or effect_type: registry.require('effect_types', effect_type, where)
    if fixed and effect_type == 'unclassified':
        raise ValueError(f'{where}须明确效果类别')
    tags = effect.get('tags', [])
    if not isinstance(tags, list) or (fixed and 'tags' not in effect):
        raise ValueError(f'{where}须登记效果 TAG 列表')
    for tag in tags:
        if not isinstance(tag, str) or tag not in registry.tags: raise ValueError(f'{where}使用未登记 TAG：{tag}')
    structure = effect.get('structure', {})
    if not isinstance(structure, dict): raise ValueError(f'{where}结构无效')
    activation = structure.get('activation')
    if fixed and (not isinstance(activation, dict) or type(activation.get('fast_effect')) is not bool):
        raise ValueError(f'{where}须登记发动条件与快速效果标记')
    if activation is not None:
        if not isinstance(activation, dict): raise ValueError(f'{where}发动条件无效')
        if 'fast_effect' in activation and type(activation['fast_effect']) is not bool:
            raise ValueError(f'{where}快速效果标记须为布尔值')
        if fixed or activation.get('timing'): registry.require('timings', activation.get('timing'), where)
        for field in ('zones', 'conditions'):
            if not isinstance(activation.get(field, []), list): raise ValueError(f'{where}发动{field}须为列表')
        for zone in activation.get('zones', []): registry.require('zones', zone, where)
        for condition in activation.get('conditions', []): _check_text(condition, f'{where}条件', 400)
    for field in ('cost', 'targeting', 'usage'):
        if not isinstance(structure.get(field, []), list): raise ValueError(f'{where}{field}须为列表')
    for cost in structure.get('cost', []):
        if not isinstance(cost, dict): raise ValueError(f'{where}费用无效')
        registry.require('cost_kinds', cost.get('kind'), f'{where}费用')
        if cost.get('text'): _check_text(cost['text'], f'{where}费用', 400)
    for target in structure.get('targeting', []):
        if isinstance(target, dict) and any(key in target for key in ('count_min', 'count_max')):
            raise ValueError(f'{where}对象数量须使用min_count/max_count或count_rule，不能使用count_min/count_max')
        if not isinstance(target, dict): raise ValueError(f'{where}对象数量无效')
        has_range = 'min_count' in target or 'max_count' in target
        if 'count_rule' in target:
            if any(field in target for field in ('count', 'min_count', 'max_count')):
                raise ValueError(f'{where}对象count_rule不能与固定数量或常量范围混用')
            rule = target['count_rule']
            if not isinstance(rule, dict) or set(rule) - {'mode', 'text', 'evaluated_at', 'minimum'}:
                raise ValueError(f'{where}对象count_rule格式或字段无效')
            if rule.get('mode') not in ('exact', 'up_to') or rule.get('evaluated_at') != 'activation':
                raise ValueError(f'{where}对象count_rule须明确exact/up_to并在activation取值')
            _check_text(rule.get('text', ''), f'{where}对象count_rule计算依据', 400)
            if rule['mode'] == 'exact':
                if 'minimum' in rule: raise ValueError(f'{where}动态固定对象数不能含minimum')
            elif type(rule.get('minimum')) is not int or rule['minimum'] < 0:
                raise ValueError(f'{where}动态对象上限须登记非负整数minimum')
        elif has_range:
            if 'count' in target or 'min_count' not in target or 'max_count' not in target:
                raise ValueError(f'{where}对象范围须同时提供min_count/max_count且不混用count')
            minimum, maximum = target['min_count'], target['max_count']
            if type(minimum) is not int or minimum < 0 or (maximum is not None and (type(maximum) is not int or maximum < minimum)):
                raise ValueError(f'{where}对象范围无效；max_count为null才表示无固定上界')
        elif type(target.get('count')) is not int or target['count'] < 0:
            raise ValueError(f'{where}对象数量无效')
        _check_text(target.get('filter', '对象'), f'{where}对象', 400)
    processing = structure.get('processing', [])
    if fixed and not processing: raise ValueError(f'{where}须登记固定处理')
    _check_processing(processing, registry, where, reviewed, card_type)
    own_nodes = list(_processing_nodes(processing, include_granted=False))
    grants = [item['granted_effect'] for _, item in own_nodes if 'granted_effect' in item]
    own_tags = effect.get('own_tags', tags)
    if grants or 'own_tags' in effect:
        if 'own_tags' not in effect or not isinstance(own_tags, list):
            raise ValueError(f'{where}含固定获赋效果时须登记本层 own_tags')
        for tag in own_tags:
            if not isinstance(tag, str) or tag not in registry.tags: raise ValueError(f'{where}本层使用未登记 TAG：{tag}')
        combined = set(own_tags).union(*(set(grant['tags']) for grant in grants))
        if set(tags) != combined:
            raise ValueError(f'{where}汇总 TAG 须与本层及固定获赋效果的 TAG 并集一致')
    if fixed or (reviewed and effect_type not in (None, 'non_effect', 'unclassified')):
        fast = (activation or {}).get('fast_effect')
        if effect_type == 'spell_continuous' and fast:
            raise ValueError(f'{where}持续适用的魔法效果不能标为快速效果')
        expected_fast = False if fixed else None
        if effect_type in ('quick', 'trap_activation', 'trap_effect'): expected_fast = True
        elif effect_type == 'trigger': expected_fast = False
        elif effect_type == 'spell_activation' and card_type is not None: expected_fast = bool(card_type & 0x10000)
        if expected_fast is not None and fast is not expected_fast:
            raise ValueError(f'{where}类别与快速效果标记不一致')
    # New explicit units must not borrow their granted children's capability tags,
    # including when the granting clause itself is non-effect text.
    if fixed or grants or (reviewed and effect_type not in (None, 'non_effect', 'unclassified')):
        expected_tags = {ACTION_TAGS[item['action']] for _, item in own_nodes if item['action'] in ACTION_TAGS}
        actual_tags = set(own_tags) & set(ACTION_TAGS.values())
        if actual_tags != expected_tags:
            raise ValueError(f'{where} TAG 与处理不一致：缺少 {sorted(expected_tags - actual_tags)}；多余 {sorted(actual_tags - expected_tags)}')
        if any(item['action'] in ('change_race', 'change_attribute', 'reverse_stat_modifiers') for _, item in own_nodes) and 'etag:stat-change' not in own_tags:
            raise ValueError(f'{where}种族／属性改变或攻守增减反转须登记etag:stat-change')
    for usage in structure.get('usage', []): registry.require('usage_limits', usage, where)
    _check_notes(effect.get('notes', []), where)
    if effect.get('engine') is not None and not isinstance(effect['engine'], dict):
        raise ValueError(f'{where}引擎依据无效')


def validate_entry(entry, registry, segment_keys=None, where='', card_type=None):
    """Structural validation; segment_keys (when given) must cover the frozen text."""
    where = where or f"卡牌 {entry.get('code')}"
    if not isinstance(entry.get('code'), int) or not 0 < entry['code'] < 2**32: raise ValueError(f'{where}卡号无效')
    if not HEX64.fullmatch(entry.get('text_digest') or ''): raise ValueError(f'{where}卡文指纹无效')
    if 'frozen_text' in entry and (not isinstance(entry['frozen_text'], str) or digest(entry['frozen_text']) != entry['text_digest']):
        raise ValueError(f'{where}卡文快照与指纹不一致')
    review = entry.get('review', {})
    if review.get('status') not in ('reviewed', 'draft') or review.get('origin') not in ('manual', 'auto', 'engine'):
        raise ValueError(f'{where}审核状态无效')
    if review.get('origin') == 'auto' and review.get('status') == 'reviewed':
        raise ValueError(f'{where}自动草稿不能标记为已核对')
    if not DATE.fullmatch(review.get('checked_on') or ''): raise ValueError(f'{where}核对日期无效')
    _check_notes(entry.get('notes', []), where)
    source_ids = set()
    for source in entry.get('sources', []):
        identifier = _check_text(source.get('id', ''), f'{where}来源编号', 120)
        url = urlparse(source.get('url', ''))
        if identifier in source_ids or url.scheme != 'https' or not url.hostname or url.username or url.password:
            raise ValueError(f'{where}来源链接或编号无效')
        source_ids.add(identifier)
        _check_text(source.get('title', ''), f'{where}来源标题', 200)
        if not DATE.fullmatch(source.get('checked_on', '')): raise ValueError(f'{where}来源核对日期无效')
    seen = set()
    for effect in entry.get('effects', []):
        key = effect.get('key')
        if key in seen: raise ValueError(f'{where}效果键重复：{key}')
        seen.add(key)
        if segment_keys is not None and key not in segment_keys:
            raise ValueError(f'{where}效果键 {key} 不在当前卡文分段中，请核对卡文')
        if effect.get('kind') not in ('numbered', 'unnumbered', 'ambiguous'): raise ValueError(f'{where}效果 {key} 类型无效')
        _check_effect_payload(effect, registry, f'{where}效果 {key}', review.get('status') == 'reviewed', card_type)
    for relation in entry.get('relations', []):
        if relation.get('kind') not in RELATION_KINDS: raise ValueError(f'{where}效果关系类型无效')
        _check_text(relation.get('text', '关系'), f'{where}效果关系', 800)
        for key in relation.get('effects', []):
            if key not in seen: raise ValueError(f'{where}关系引用了未标注的效果：{key}')
    return entry


def draft_entry(code, segs, text_digest):
    """Conservative auto candidates; origin stays auto and is never counted as reviewed."""
    effects = []
    for seg in segs:
        matched, tags, processing, usage = [], [], [], []
        for pattern, kind in DRAFT_PATTERNS:
            hit = pattern.search(seg['text'])
            if not hit: continue
            matched.append({'kind': kind, 'basis': hit[0][:80]})
            if kind == 'name_limit':
                usage.append('shared_name_once' if '任意' in hit[0] else 'name_soft_opt')
                continue
            tag = DRAFT_TAG.get(kind)
            if tag and tag not in tags: tags.append(tag)
            if kind in ('add_hand', 'add_hand_source', 'special_summon', 'normal_summon', 'return_deck',
                        'destroy', 'banish', 'negate_effect', 'negate_activation', 'hand_reveal', 'deck_reveal'):
                item = {'action': 'add_hand' if kind.startswith('add_hand') else kind,
                        'evidence': hit[0][:80]}
                if kind == 'add_hand_source':
                    item['from_zones'] = [DRAFT_SOURCE_ZONE[hit[1]]]
                processing.append(item)
        if not matched: continue
        effects.append({'key': seg['key'], 'kind': seg['kind'], 'number': seg['number'], 'block': seg['block'],
                        'tags': tags,
                        'structure': {name: value for name, value in (('processing', processing), ('usage', usage)) if value},
                        'notes': [{'text': '自动提取候选：按词表模式匹配卡文片段生成，未经人工或引擎核对，仅作待核对草稿。',
                                   'source_refs': ['auto-draft']}]})
    return {'code': code, 'text_digest': text_digest,
            'review': {'status': 'draft', 'origin': 'auto', 'checked_on': '', 'basis': '自动提取（词表模式匹配）'},
            'effects': effects, 'relations': [], 'notes': []}


class CardAnnotations:
    """Curated (in-repo) + personal (runtime) annotation layers under one view."""

    def __init__(self, store, read_json, atomic_json, now, curated_path=None, registry_path=None):
        self.store = store
        self.read_json, self.atomic_json, self._now = read_json, atomic_json, now
        self.curated_path = Path(curated_path) if curated_path else Path(__file__).parent / 'card-annotations.json'
        self.registry_path = Path(registry_path) if registry_path else Path(__file__).parent / 'annotation-tags.json'
        self.registry = Registry(json.loads(self.registry_path.read_text(encoding='utf-8')))
        self.path = store.root / 'card-annotations.json'
        self.backup_dir = store.root / 'backups' / 'annotations'
        self.curated = self._load_curated()
        self.document = self._load_user()
        self._views = {}
        self.series = CardSeries(store.catalog, store.library.builtins)

    def _load_curated(self):
        document = json.loads(self.curated_path.read_text(encoding='utf-8'))
        if document.get('version') != 1: raise ValueError('卡片标注资料版本不受支持')
        entries = {}
        for key, entry in document.get('cards', {}).items():
            try:
                # Keys are only checkable while the frozen text still matches the
                # installed card; digest drift keeps entries but freezes them.
                card = self.store.catalog.cards.get(int(key))
                segment_keys = None
                if card is not None and entry.get('text_digest') == digest(card.get('desc') or ''):
                    segment_keys = {seg['key'] for seg in segments(card.get('desc') or '', card.get('type') or 0)}
                entries[int(key)] = validate_entry({**entry, 'code': int(key)}, self.registry, segment_keys=segment_keys,
                                                   card_type=card.get('type', 0) if segment_keys is not None else None)
            except ValueError as exc:
                raise ValueError(f'内置卡片标注资料无效：{exc}') from None
        document['cards'] = entries
        return document

    def _load_user(self):
        if not self.path.exists(): return {'version': 2, 'revision': 1, 'cards': {}}
        document = self.read_json(self.path)
        if document.get('version') not in (1, 2) or not isinstance(document.get('cards'), dict) or not isinstance(document.get('revision'), int):
            raise ValueError('本地卡片标注文件无效，请从备份恢复后重试')
        return document

    def reload(self):
        """Resource updates re-anchor every annotation to the new card text."""
        self.curated = self._load_curated()
        self.document = self._load_user()
        self._views = {}
        self.series = CardSeries(self.store.catalog, self.store.library.builtins)

    # ---- assembly -------------------------------------------------------

    def _engine_links(self, code, card_digest, seg_map):
        audited = AUDITED_EFFECTS.get(code)
        if not audited or audited[0] != card_digest: return {}
        links = {}
        for rule in audited[1]:
            for prefix in ('m', 'p'):
                key = f"{prefix}{rule['number']}"
                if key in seg_map:
                    links.setdefault(key, {'script': rule['script'], 'location': rule.get('location'), 'audited': True})
                    break
        return links

    def view(self, code):
        if code in self._views: return self._views[code]
        card = self.store.catalog.cards.get(code)
        if card is None: raise ValueError(f'卡牌编号 {code} 不在当前卡库')
        current = digest(card.get('desc') or '')
        current_segs = segments(card.get('desc') or '', card.get('type') or 0)
        personal = self.document['cards'].get(str(code)) or {}
        user = personal if personal.get('text_digest') == current else {}
        personal_review_required = self._has_overlay(personal) and not user
        history = deepcopy(personal.get('history', []))
        if personal_review_required:
            history.append(self._overlay_snapshot(personal))
        curated = self.curated['cards'].get(code)
        base, provenance, stale = None, None, False
        if curated is not None:
            base = curated
            provenance = {'source': 'curated', 'id': self.curated.get('id'), 'title': self.curated.get('title'),
                          'checked_on': curated['review'].get('checked_on')}
            stale = curated.get('text_digest') != current
        draft = personal.get('draft')
        if base is None and draft is not None:
            base, provenance = draft, {'source': 'user-draft'}
            stale = personal.get('draft_digest') != current
        # Never pair an old numbered annotation with new text at the same key.
        segs = current_segs
        if stale:
            segs = segments(base['frozen_text'], card.get('type') or 0) if base.get('frozen_text') else [
                {**effect, 'text': effect.get('text', '旧卡文未保存，请查阅来源核对。'),
                 'block': 'p' if effect['key'].startswith('p') else 'm'} for effect in base.get('effects', [])]
        seg_map = {seg['key']: seg for seg in segs}
        if stale: status = 'stale'
        elif (user.get('pending') or personal_review_required) and base is not None: status = 'pending'
        elif user.get('confirmed') and base is not None and base['review'].get('origin') != 'auto': status = 'confirmed'
        elif base is not None: status = 'reviewed' if base['review']['status'] == 'reviewed' else 'auto'
        else: status = 'none'
        annotated = {effect['key']: effect for effect in (base or {}).get('effects', [])}
        # A stale view can show old corrections ONLY beside their matching old
        # frozen text. Neither its tags nor its confirmation apply to new text.
        display_digest = base.get('text_digest') if stale else current
        display_user = personal if personal.get('text_digest') == display_digest else {}
        add, remove = display_user.get('tag_add', {}), display_user.get('tag_remove', {})
        user_notes = display_user.get('notes', {})
        engine = {} if stale else self._engine_links(code, current, seg_map)
        effects, missing = [], []
        for seg in segs:
            if seg['key'] in annotated:
                effect = deepcopy(annotated[seg['key']])
                effect.update(kind=seg['kind'], number=seg['number'], block=seg['block'], text=seg['text'], annotated=True)
                tags = set(effect.get('tags', [])) | set(add.get(seg['key'], []))
                tags -= set(remove.get(seg['key'], []))
                effect['tags'] = sorted(tags, key=self.registry.tag_order)
                notes = [*deepcopy(effect.get('notes', [])), *deepcopy(user_notes.get(seg['key'], []))]
                if notes: effect['notes'] = notes
                if seg['key'] in engine and not effect.get('engine'): effect['engine'] = engine[seg['key']]
            else:
                missing.append(seg['key'])
                effect = {**seg, 'annotated': False}
                if seg['key'] in user_notes: effect['notes'] = deepcopy(user_notes[seg['key']])
            effects.append(effect)
        full = base is not None and (bool(base.get('no_effect')) or not missing)
        if status in ('reviewed', 'confirmed') and not full: status = 'partial'
        result = {'code': code, 'name': card.get('name', str(code)), 'type': card.get('type', 0),
                  'setcode': card.get('setcode'), 'status': status,
                  'series': self.series.card_series(code),
                  'full': full,
                  'origin': base['review'].get('origin') if base else None,
                  'no_effect': bool((base or {}).get('no_effect')), 'missing_keys': [] if (base or {}).get('no_effect') else missing,
                  'digest_ok': not stale, 'text_digest': (base or {}).get('text_digest', current),
                  'current_text_digest': current, 'current_text': card.get('desc') or '',
                  'review': deepcopy((base or {}).get('review')), 'provenance': provenance,
                  'personal_review_required': bool(personal_review_required), 'personal_history': history,
                  'effects': effects, 'relations': deepcopy((base or {}).get('relations', [])),
                  'notes': deepcopy((base or {}).get('notes', [])),
                  'sources': deepcopy((base or {}).get('sources', []))}
        self._views[code] = result
        return result

    def annotated_codes(self):
        curated = set(self.curated['cards'])
        codes = curated | {int(code) for code, entry in self.document['cards'].items()
                           if entry.get('draft') and int(code) not in curated}
        return sorted(code for code in codes if code in self.store.catalog.cards and not self.store.catalog.cards[code].get('type', 0) & 0x4000)

    def overview(self):
        cards = self.store.catalog.cards
        counts = {status: 0 for status in STATUSES}
        partial, stale = [], []
        for code in self.annotated_codes():
            view = self.view(code)
            status = view['status']
            if status == 'stale': stale.append(code)
            elif status == 'partial': partial.append(code)
            counts[status] += 1
        tokens = sum(1 for card in cards.values() if card.get('type', 0) & 0x4000)
        eligible = len(cards) - tokens
        counts['none'] = eligible - sum(counts[status] for status in STATUSES if status != 'none')
        return {'version': 1, 'statuses': counts,
                'catalog': {'cards': len(cards), 'sources': self.store.catalog.sources},
                'tokens': tokens, 'eligible_total': eligible,
                'annotated_total': sum(counts[status] for status in STATUSES if status != 'none'),
                'curated': {'id': self.curated.get('id'), 'title': self.curated.get('title'),
                            'checked_on': self.curated.get('checked_on'),
                            'verified_against': self.curated.get('verified_against', {})},
                'registry': {'tags': len(self.registry.tags), 'updated_on': self.registry.updated_on},
                'partial_codes': partial, 'stale_codes': stale,
                'missing_codes': sorted(set(self.curated['cards']) - set(cards)),
                'note': '未标注 ≠ 没有能力。草稿与部分标注单独统计；衍生物不参与标注。'}

    # ---- query ----------------------------------------------------------

    def _iter_processing(self, items, include_granted=True):
        yield from _processing_nodes(items, include_granted)

    def _effect_units(self, effect, path='', visible_tags=None):
        """Keep each fixed granted effect separate from its granting effect."""
        grants = [(index, item['granted_effect']) for index, item in
                  self._iter_processing(effect.get('structure', {}).get('processing'), include_granted=False)
                  if 'granted_effect' in item]
        own_tags = set(effect.get('own_tags', effect.get('tags', [])))
        if grants or 'own_tags' in effect:
            declared = own_tags.union(*(set(grant['tags']) for _, grant in grants))
            # view() applies segment-level personal tags only to the displayed
            # aggregate. New tags belong to its own unit; removals mask all units.
            own_tags |= set(effect.get('tags', [])) - declared
        visible = set(effect.get('tags', []))
        if visible_tags is not None: visible &= visible_tags
        yield path, {**effect, 'tags': sorted(own_tags & visible)}
        for index, granted in grants:
            child_path = f'{path + "." if path else ""}{index}.granted_effect'
            yield from self._effect_units(granted, child_path, visible)

    def _effect_conditions(self, effect, body):
        """All conditions must match one own or fixed-granted effect unit."""
        for path, unit in self._effect_units(effect):
            evidence = self._unit_conditions(unit, body)
            if evidence is None: continue
            if path:
                return [{**item, 'effect_source': 'granted_effect', 'effect_path': path,
                         'basis': f'固定获赋效果（{path}）：{item["basis"]}'} for item in evidence]
            return evidence
        return None

    def _processing_conditions(self, effect, body):
        """Bind an action and its source/destination to one processing item."""
        conditions = {name: body[name] for name in ('action', 'from_zone', 'to_zone') if body.get(name)}
        if not conditions: return []
        for path, item in self._iter_processing(effect.get('structure', {}).get('processing'), include_granted=False):
            evidence = []
            for name, value in conditions.items():
                if name == 'action':
                    if item.get('action') != value: break
                    basis = (f"处理：{self.registry.action_label(value)}"
                             f"（{item.get('selector', {}).get('text') or item.get('evidence', '')}）")
                else:
                    zones = item.get('from_zones' if name == 'from_zone' else 'to_zones')
                    if zones and zone_matches(value, zones):
                        basis = self.registry.zone_label(value)
                    elif name == 'to_zone' and not zones and zone_matches(value, [DEFAULT_DESTINATION.get(item.get('action'))]):
                        basis = f"隐含去向：{self.registry.action_label(item.get('action'))}"
                    else:
                        break
                evidence.append({'condition': name, 'value': value, 'basis': basis, 'processing_path': path})
            else:
                return evidence
        return None

    def _unit_conditions(self, effect, body):
        """Match one effect; action/zone filters share a processing item."""
        evidence = []
        etags = body.get('etags') or []
        if etags:
            tags = set(effect.get('tags') or [])
            if body.get('etag_mode') == 'any':
                hit = [tag for tag in etags if tag in tags]
                if not hit: return None
            else:
                if not set(etags) <= tags: return None
                hit = list(etags)
            evidence.append({'condition': 'tag', 'value': hit, 'basis': '效果 TAG'})
        processing = self._processing_conditions(effect, body)
        if processing is None: return None
        evidence.extend(processing)
        for name in CONDITION_FIELDS:
            if name in ('action', 'from_zone', 'to_zone'): continue
            value = body.get(name)
            if not value: continue
            found = None
            if name == 'usage':
                if value in (effect.get('structure', {}).get('usage') or []):
                    found = {'condition': name, 'value': value, 'basis': self.registry.usage_label(value)}
            elif name == 'cost_kind':
                for cost in effect.get('structure', {}).get('cost') or []:
                    if cost.get('kind') == value:
                        found = {'condition': name, 'value': value, 'basis': cost.get('text') or value}
                        break
            elif name == 'timing':
                activation = effect.get('structure', {}).get('activation') or {}
                if activation.get('timing') == value:
                    found = {'condition': name, 'value': value, 'basis': '发动时点'}
            if found is None: return None
            evidence.append(found)
        return evidence

    def _single_conditions(self, body):
        """Card scope may cross effects, but a movement query stays atomic."""
        singles = []
        etags = body.get('etags') or []
        if body.get('etag_mode') == 'any' and etags:
            singles.append({'etags': etags, 'etag_mode': 'any'})
        else:
            singles.extend({'etags': [tag]} for tag in etags)
        processing = {name: body[name] for name in ('action', 'from_zone', 'to_zone') if body.get(name)}
        if processing: singles.append(processing)
        singles.extend({name: body[name]} for name in CONDITION_FIELDS
                       if name not in ('action', 'from_zone', 'to_zone') and body.get(name))
        return singles

    def search(self, body):
        from plan_tags import member_ids, normalized
        query = normalized(body.get('q', ''))
        if len(body.get('q', '')) > 120: raise ValueError('搜索文字最多 120 个字符')
        statuses = body.get('status', list(STATUSES))
        if not isinstance(statuses, list) or any(status not in STATUSES for status in statuses):
            raise ValueError('标注状态筛选无效')
        etags = body.get('etags') or []
        if not isinstance(etags, list) or len(etags) > len(self.registry.tags) or any(tag not in self.registry.tags for tag in etags):
            raise ValueError('效果 TAG 筛选无效')
        scope = body.get('scope') or 'effect'
        if scope not in ('effect', 'card'): raise ValueError('查询范围无效')
        offset = body.get('offset') or 0
        if not isinstance(offset, int) or not 0 <= offset <= max(10_000, len(self.store.catalog.cards)): raise ValueError('分页参数无效')
        series_filter = body.get('series') or ''
        if not isinstance(series_filter, str) or (series_filter and series_filter not in self.series.definitions):
            raise ValueError('系列不存在，请刷新资料')
        group_by = body.get('group_by') or ''
        if group_by not in ('', 'series'): raise ValueError('卡片分组方式无效')
        member_filter = None
        if body.get('tag'):
            tags = self.store.library.all_tags()
            tag = tags.get(body['tag'])
            if tag is None: raise ValueError('TAG 不存在，请刷新标签库')
            member_filter = set(member_ids(tag, self.store.catalog.cards))
        kind = body.get('kind') or ''
        if kind not in ('', 'monster', 'spell', 'trap', 'extra'): raise ValueError('卡片类型筛选无效')
        condition_names = ({'tag'} if etags else set()) | {name for name in CONDITION_FIELDS if body.get(name)}
        matched = []
        catalog_scope = body.get('catalog_scope', 'annotated')
        if catalog_scope not in ('annotated', 'all'): raise ValueError('卡片范围无效')
        candidates = self.store.catalog.cards if catalog_scope == 'all' else self.annotated_codes()
        for code in candidates:
            card = self.store.catalog.cards[code]
            if card.get('type', 0) & 0x4000: continue
            if kind == 'monster' and not card.get('type', 0) & 1: continue
            if kind == 'spell' and not card.get('type', 0) & 2: continue
            if kind == 'trap' and not card.get('type', 0) & 4: continue
            if kind == 'extra' and not card.get('extra'): continue
            if member_filter is not None and code not in member_filter: continue
            if series_filter and series_filter not in self.series.memberships.get(code, []): continue
            if query and query not in normalized(card.get('name', '')) and query != str(code) \
                    and query not in normalized(card.get('desc') or '') and not self.series.matches_query(code, query):
                continue
            view = self.view(code)
            if view['status'] not in statuses: continue
            if condition_names and not view['digest_ok']: continue
            hits = []
            for effect in view['effects']:
                if not effect.get('annotated'): continue
                evidence = self._effect_conditions(effect, body)
                if evidence is None: continue
                hits.append({'key': effect['key'], 'number': effect.get('number'), 'block': effect.get('block'),
                             'kind': effect.get('kind'), 'text': effect.get('text'), 'tags': effect.get('tags', []),
                             'usage': effect.get('structure', {}).get('usage', []),
                             'engine': effect.get('engine'), 'evidence': evidence})
            if not condition_names:
                hits = hits or [{'key': effect['key'], 'number': effect.get('number'), 'block': effect.get('block'),
                                 'kind': effect.get('kind'), 'text': effect.get('text'), 'tags': effect.get('tags', []),
                                 'usage': effect.get('structure', {}).get('usage', []),
                                 'engine': effect.get('engine'), 'evidence': []}
                                for effect in view['effects'] if effect.get('annotated')]
            elif scope == 'effect':
                if not hits: continue
            else:
                # Card scope: each condition may be met by a different effect;
                # every condition still needs at least one effect behind it.
                merged = {}
                for single in self._single_conditions(body):
                    found = False
                    for effect in view['effects']:
                        if not effect.get('annotated'): continue
                        evidence = self._effect_conditions(effect, single)
                        if evidence is None: continue
                        found = True
                        hit = merged.setdefault(effect['key'], {'key': effect['key'], 'number': effect.get('number'),
                                                                'block': effect.get('block'), 'kind': effect.get('kind'),
                                                                'text': effect.get('text'), 'tags': effect.get('tags', []),
                                                                'usage': effect.get('structure', {}).get('usage', []),
                                                                'engine': effect.get('engine'), 'evidence': []})
                        hit['evidence'] = [*hit['evidence'], *evidence]
                    if not found: merged = None; break
                if merged is None or not merged: continue
                hits = list(merged.values())
            keys = sorted({hit['key'] for hit in hits})
            matched.append({'code': code, 'name': view['name'], 'type': card.get('type', 0),
                            'status': view['status'], 'full': view['full'], 'origin': view['origin'],
                            'hits': hits, 'no_effect': view['no_effect'], 'series': view['series'],
                            'cross_effects': scope == 'card' and bool(condition_names) and not any(
                                self._effect_conditions(effect, body) is not None
                                for effect in view['effects'] if effect.get('annotated')),
                            'hit_keys': keys})
        matched.sort(key=lambda item: (item['name'], item['code']))
        if group_by == 'series':
            return {'total': len(matched), 'folders': self.series.folders(matched)}
        return {'total': len(matched), 'offset': offset, 'scope': scope,
                'annotated_total': len(self.annotated_codes()),
                'catalog_total': len(self.store.catalog.cards),
                'note': '查询只在已标注范围内命中；未标注卡片不代表没有该能力。默认所有条件须在同一效果内成立；动作与来源、去向须匹配同一个处理项。',
                'cards': matched[offset:offset + 30]}

    # ---- personal layer -------------------------------------------------

    def _save(self, mutate):
        with self.store.lock:
            previous = deepcopy(self.document)
            updated = deepcopy(previous)
            mutate(updated)
            updated['version'] = 2
            updated['revision'] += 1
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            self.atomic_json(self.backup_dir / f"{previous['revision']}.json", previous)
            self.atomic_json(self.path, updated)
            self.document = updated
            self._views = {}

    @staticmethod
    def _has_overlay(entry):
        return bool(entry.get('confirmed') or entry.get('pending') or any(
            any(entry.get(field, {}).values()) for field in ('tag_add', 'tag_remove', 'notes')))

    @staticmethod
    def _overlay_snapshot(entry):
        return {key: deepcopy(value) for key, value in entry.items() if key not in ('history', 'draft', 'draft_digest')}

    def _card_entry(self, document, code):
        entry = document['cards'].setdefault(str(code), {})
        text = self.store.catalog.cards[code].get('desc') or ''
        current = digest(text)
        if entry.get('text_digest') != current:
            archived = self._has_overlay(entry)
            if archived:
                snapshot = self._overlay_snapshot(entry)
                snapshot['archived_on'] = self._now()
                entry.setdefault('history', []).append(snapshot)
            entry.update(text_digest=current, frozen_text=text, confirmed=False, pending=archived,
                         tag_add={}, tag_remove={}, notes={})
        return entry

    def set_review(self, body):
        code = self._require_code(body)
        value = body.get('value')
        if value not in ('confirmed', 'pending', None): raise ValueError('核对状态取值无效')
        view = self.view(code)
        if value == 'confirmed' and (not view['digest_ok'] or not view['full'] or view['origin'] == 'auto' or view['status'] == 'none'):
            raise ValueError('请先完成全部分段的人工结构标注；自动草稿或旧卡文不能直接确认为已核对')
        def mutate(document):
            entry = self._card_entry(document, code)
            entry['confirmed'] = value == 'confirmed'
            entry['pending'] = value == 'pending'
        self._save(mutate)
        return {'code': code, 'status': self.view(code)['status'], 'revision': self.document['revision']}

    def add_note(self, body):
        code, key, text = self._require_code(body), body.get('key'), body.get('text')
        if not isinstance(key, str) or not key: raise ValueError('效果编号无效')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000: raise ValueError('备注请输入 1–4000 字')
        if key not in {effect['key'] for effect in self.view(code)['effects']}:
            raise ValueError('效果编号不在当前卡文分段中')
        def mutate(document):
            entry = self._card_entry(document, code)
            entry.setdefault('notes', {}).setdefault(key, []).append({'text': text.strip(), 'ts': self._now()})
        self._save(mutate)
        return {'code': code, 'key': key, 'revision': self.document['revision']}

    def remove_note(self, body):
        code, key, index = self._require_code(body), body.get('key'), body.get('index')
        if not isinstance(key, str) or not isinstance(index, int) or index < 0: raise ValueError('备注定位无效')
        def mutate(document):
            notes = self._card_entry(document, code).get('notes', {}).get(key, [])
            if index >= len(notes): raise ValueError('备注不存在，请刷新后重试')
            notes.pop(index)
        self._save(mutate)
        return {'code': code, 'key': key, 'revision': self.document['revision']}

    def set_tags(self, body):
        code, key = self._require_code(body), body.get('key')
        add, remove = body.get('add', []), body.get('remove', [])
        if not isinstance(key, str) or not key: raise ValueError('效果编号无效')
        for field, ids in (('add', add), ('remove', remove)):
            if not isinstance(ids, list) or len(ids) > len(self.registry.tags) or any(tag not in self.registry.tags for tag in ids):
                raise ValueError(f'{field} 的效果 TAG 无效')
        if key not in {effect['key'] for effect in self.view(code)['effects']}:
            raise ValueError('效果编号不在当前卡文分段中')
        def mutate(document):
            entry = self._card_entry(document, code)
            added = (set(entry.get('tag_add', {}).get(key, [])) | set(add)) - set(remove)
            removed = (set(entry.get('tag_remove', {}).get(key, [])) | set(remove)) - set(add)
            # Removing a personal addition undoes it; tag_remove only counters curated tags.
            entry.setdefault('tag_add', {})[key] = sorted(added)
            entry.setdefault('tag_remove', {})[key] = sorted(removed)
        self._save(mutate)
        return {'code': code, 'key': key, 'revision': self.document['revision']}

    def make_draft(self, body):
        code = self._require_code(body)
        card = self.store.catalog.cards[code]
        current = digest(card.get('desc') or '')
        entry = draft_entry(code, segments(card.get('desc') or '', card.get('type') or 0), current)
        entry['frozen_text'] = card.get('desc') or ''
        if not entry['effects']: raise ValueError('未能从卡文中提取任何候选；请人工标注或稍后扩充词表')
        def mutate(document):
            personal = document['cards'].setdefault(str(code), {})
            personal['draft'] = entry
            personal['draft_digest'] = current
        self._save(mutate)
        return {'code': code, 'effects': len(entry['effects']), 'origin': 'auto', 'revision': self.document['revision']}

    def discard_draft(self, body):
        code = self._require_code(body)
        def mutate(document):
            entry = document['cards'].get(str(code))
            if entry is None or 'draft' not in entry: raise ValueError('该卡没有自动草稿')
            entry.pop('draft', None); entry.pop('draft_digest', None)
            if not self._has_overlay(entry) and not entry.get('history'):
                document['cards'].pop(str(code), None)
        self._save(mutate)
        return {'code': code, 'revision': self.document['revision']}

    def _require_code(self, body):
        code = body.get('code')
        if not isinstance(code, int) or code not in self.store.catalog.cards: raise ValueError('卡牌不在当前卡库中')
        return code

    def registry_document(self):
        return {'version': 1, 'updated_on': self.registry.updated_on, 'categories': self.registry.categories,
                'tags': sorted(self.registry.tags.values(), key=lambda tag: (tag['category'], tag['name'])),
                **self.registry.vocab}

    def snapshot(self):
        return {'registry': self.registry_document(), 'overview': self.overview(), 'revision': self.document['revision']}

    def command(self, body):
        if not isinstance(body, dict): raise ValueError('请求无效')
        op = body.get('op')
        if op == 'overview': return self.overview()
        if op == 'query': return self.search(body)
        if op == 'card': return self.view(self._require_code(body))
        if op == 'registry': return self.registry_document()
        if op in ('set-review', 'add-note', 'remove-note', 'set-tags', 'discard-draft'):
            with self.store.lock:
                if body.get('revision') != self.document['revision']:
                    raise ValueError('本地标注已更新，请刷新后重试')
                if op in ('set-tags', 'add-note', 'remove-note') and not self.view(self._require_code(body))['digest_ok']:
                    raise ValueError('卡文已变化，旧标注暂不接受标签或备注修改')
                return getattr(self, {'set-review': 'set_review', 'add-note': 'add_note', 'remove-note': 'remove_note',
                                      'set-tags': 'set_tags', 'discard-draft': 'discard_draft'}[op])(body)
        if op == 'draft': return self.make_draft(body)
        raise ValueError('未知的标注操作')
