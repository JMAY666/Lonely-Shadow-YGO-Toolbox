"""Limited native-prompt adapter. Unknown cards/windows fail closed.

This experimental observation uses database base stats because TrainingState
does not expose current ATK/DEF/type/level. It is not a production duel advisor.
"""
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from modular_decisions import model, encode_binding

LOCATIONS = {1: 'deck', 2: 'hand', 4: 'mzone', 8: 'szone', 16: 'grave', 32: 'removed', 64: 'extra'}
POSITIONS = {0: 'none', 1: 'faceup_attack', 2: 'facedown_attack', 4: 'faceup_defense', 8: 'facedown_defense', 5: 'faceup', 10: 'facedown'}
PHASES = {1: 'draw', 2: 'standby', 4: 'main1', 8: 'battle_start', 16: 'battle_step', 32: 'damage', 64: 'damage_calculation', 128: 'battle', 256: 'main2', 512: 'end'}
ATTRIBUTES = ['earth', 'water', 'fire', 'wind', 'light', 'dark', 'divine']
RACES = ['warrior', 'spellcaster', 'fairy', 'fiend', 'zombie', 'machine', 'aqua', 'pyro', 'rock', 'wingbeast', 'plant', 'insect', 'thunder', 'dragon', 'beast', 'beast_warrior', 'dinosaur', 'fish', 'sea_serpent', 'reptile', 'psycho', 'devine', 'creator_god', 'wyrm', 'cyberse', 'illusion']
# The upstream schema spells Winged Beast as "windbeast".
RACES[9] = 'windbeast'
TYPE_BITS = {1: 'monster', 2: 'spell', 4: 'trap', 16: 'normal', 32: 'effect', 64: 'fusion', 128: 'ritual', 256: 'trap_monster', 512: 'spirit', 1024: 'union', 2048: 'dual', 4096: 'tuner', 8192: 'synchro', 16384: 'token', 65536: 'quick_play', 131072: 'continuous', 262144: 'equip', 524288: 'field', 1048576: 'counter', 2097152: 'flip', 4194304: 'toon', 8388608: 'xyz', 16777216: 'pendulum', 33554432: 'special', 67108864: 'link'}
IDLE = {'summon': 'summon', 'special': 'sp_summon', 'position': 'reposition', 'monster_set': 'mset', 'spell_set': 'set', 'activate': 'activate', 'battle': 'to_bp', 'end_turn': 'to_ep'}
LABELS = {'summon': '通常召唤', 'special': '特殊召唤', 'position': '改变表示', 'monster_set': '盖放怪兽', 'spell_set': '盖放', 'activate': '发动', 'yes': '选择是／发动', 'no': '选择否', 'pass': '不响应', 'end_turn': '结束回合', 'battle': '进入战斗阶段', 'main2': '进入主要阶段2', 'attack': '攻击', 'card': '选择卡牌', 'material': '选择素材', 'select': '选择素材', 'unselect': '取消素材', 'finish_selection': '完成选择', 'cancel_selection': '取消选择', 'position_choice': '选择表示', 'option': '选择效果选项', 'place': '选择区域'}


def u32(raw, offset=0):
    return struct.unpack_from('<I', raw, offset)[0]


def integer(raw):
    return int.from_bytes(bytes.fromhex(raw)[:4], 'little', signed=True)


def hidden(card):
    return card['controller'] == 1 and (card['location'] in (1, 2, 64) or card['position'] & 10)


def enum_bit(value, names):
    if value == 0: return 'none'
    if value & (value - 1) or value.bit_length() > len(names):
        raise ValueError(f'Unsupported attribute/race bits: {value}')
    return names[value.bit_length() - 1]


class NativeInput:
    def __init__(self, snapshot, catalog):
        if snapshot['player'] != 0 or snapshot['answered']:
            raise ValueError('Current unanswered player decision required')
        self.snapshot, self.catalog = snapshot, catalog
        self.prompt = model(snapshot['raw'], snapshot['state'], snapshot.get('effects'))
        self.raw = bytes.fromhex(snapshot['raw'])
        state = snapshot['state']
        self.global_ = {'my_lp': state['lp'][0], 'op_lp': state['lp'][1], 'turn': state['turn'],
                        'phase': PHASES[state['phase']], 'is_first': True, 'is_my_turn': state['turn_player'] == 0}
        if state['turn'] != 1 or state['turn_player'] != 0:
            raise ValueError('Pilot is restricted to the first player first turn')
        self.locations, self.cards = {}, []
        if any(c['location'] not in LOCATIONS for c in state['cards']):
            raise ValueError('Overlay or unknown zones are outside this pilot')
        for player in (0, 1):
            for zone in LOCATIONS:
                group = [c for c in state['cards'] if c['controller'] == player and c['location'] == zone]
                # Deck order is private. Canonicalize the known own multiset and
                # remap selection references without exposing the shuffled order.
                group.sort(key=lambda c: (c['code'], c['sequence']) if zone == 1 and player == 0 else c['sequence'])
                for index, card in enumerate(group):
                    seq = index if zone == 1 else card['sequence']
                    self.locations[(player, zone, card['sequence'])] = {
                        'controller': 'me' if player == 0 else 'opponent', 'location': LOCATIONS[zone],
                        'sequence': seq, 'overlay_sequence': -1}
                    private = hidden(card)
                    row = {} if private else catalog[card['code']]
                    self.cards.append({**self.locations[(player, zone, card['sequence'])],
                        'code': 0 if private else card['code'],
                        'position': 'none' if private and zone in (1, 2, 64) else POSITIONS[card['position']],
                        'attribute': enum_bit(row.get('attribute', 0), ATTRIBUTES),
                        'race': enum_bit(row.get('race', 0), RACES),
                        'level': row.get('level', 0) & 255,
                        'counter': 0 if private or not card.get('counters') else card['counters'][0]['count'],
                        'negated': False if private else bool(card.get('disabled') or card.get('status_flags', 0) & 0x4000000),
                        'attack': row.get('atk', 0), 'defense': row.get('def', 0),
                        'types': [name for bit, name in TYPE_BITS.items() if row.get('type', 0) & bit]})
        if len(self.cards) > 160: raise ValueError('Model card capacity exceeded')

    def location(self, card):
        return self.locations[(card['controller'], card['location'], card['sequence'])]

    def info(self, card):
        return {k: v for k, v in {**self.location(card), 'code': card['code']}.items() if k != 'overlay_sequence'}

    def input(self, selected=None):
        p, raw = self.prompt, self.raw
        choices, msg = p['choices'], p['message']
        selected = selected or []
        if len(choices) > 24 or (msg == 23 and len(choices) > 16):
            raise ValueError('Native decision exceeds the pilot action/search capacity')
        if msg == 11:
            commands = []
            for c in choices:
                kind = c['semantic']['kind']
                data = None if not c.get('card') else {'card_info': self.info(c['card']),
                    'effect_description': (c.get('effect') or {}).get('description', 0), 'response': integer(c['response'])}
                commands.append({'cmd_type': IDLE[kind], 'data': data})
            action = {'msg_type': 'select_idlecmd', 'idle_cmds': commands}
        elif msg == 16:
            action = {'msg_type': 'select_chain', 'forced': not any(c['semantic']['kind'] == 'pass' for c in choices),
                'chains': [{'code': c['card']['code'], 'location': self.location(c['card']),
                    'effect_description': (c.get('effect') or {}).get('description', 0), 'response': integer(c['response'])}
                    for c in choices if c['semantic']['kind'] == 'activate']}
        elif msg == 12:
            c = choices[0]
            action = {'msg_type': 'select_effectyn', 'code': c['card']['code'],
                      'location': self.location(c['card']), 'effect_description': u32(raw, 10)}
        elif msg == 13:
            action = {'msg_type': 'select_yesno', 'effect_description': u32(raw, 2)}
        elif msg == 14:
            action = {'msg_type': 'select_option', 'options': [{'code': c['semantic']['value'], 'response': integer(c['response'])} for c in choices]}
        elif msg == 19:
            action = {'msg_type': 'select_position', 'code': u32(raw, 2), 'positions': [POSITIONS[c['semantic']['value']] for c in choices]}
        elif msg == 18 and p['minimum'] == 1:
            action = {'msg_type': 'select_place', 'count': 1, 'places': [
                {'controller': 'me' if c['semantic']['place'][0] == 0 else 'opponent',
                 'location': LOCATIONS[c['semantic']['place'][1]], 'sequence': c['semantic']['place'][2]} for c in choices]}
        elif msg in (15, 20):
            action = {'msg_type': 'select_card' if msg == 15 else 'select_tribute',
                      'cancelable': p['cancel'], 'min': p['minimum'], 'max': p['maximum'], 'selected': selected,
                      'cards': [{'location': self.location(c['card']), 'response': c['response'],
                                 **({'level': c['semantic']['tribute_value']} if msg == 20 else {})} for c in choices]}
        elif msg == 26:
            if any(c['semantic']['kind'] == 'unselect' for c in choices):
                raise ValueError('Unselecting already selected materials is not covered by the upstream model')
            action = {'msg_type': 'select_unselect_card', 'finishable': bool(raw[2]), 'cancelable': bool(raw[3]),
                'min': raw[4], 'max': raw[5], 'selected_cards': [], 'selectable_cards': [
                    {'location': self.location(c['card']), 'response': i} for i, c in enumerate(choices) if c['semantic']['kind'] == 'select']}
        elif msg == 23:
            required = []
            for i in range(p['mandatory']):
                offset = 10 + i * 11
                key = tuple(raw[offset + 4:offset + 7])
                value = u32(raw, offset + 7)
                required.append({'location': self.locations[key], 'level1': value & 65535, 'level2': value >> 16, 'response': i})
            action = {'msg_type': 'select_sum', 'overflow': bool(p['sum_mode']), 'level_sum': p['target'],
                'min': p['minimum'], 'max': p['maximum'], 'must_cards': required, 'selected': selected,
                'cards': [{'location': self.location(c['card']), 'response': c['response'],
                    'level1': c['semantic']['value'] & 65535, 'level2': c['semantic']['value'] >> 16} for c in choices]}
        else:
            raise ValueError(f'Native prompt {msg} is outside the pilot adapter coverage')
        return {'global': self.global_, 'cards': self.cards, 'action_msg': {'data': action}}

    def response(self, prediction, selected):
        p = self.prompt
        if p['mode'] in ('cards', 'sum'):
            return encode_binding({}, p, selected)
        if p['mode'] == 'places':
            return p['choices'][prediction['response']]['response']
        if p['message'] == 26:
            if prediction['response'] == -1:
                return next(c['response'] for c in p['choices'] if c['semantic']['kind'] == 'finish_selection')
            return p['choices'][prediction['response']]['response']
        return next(c['response'] for c in p['choices'] if integer(c['response']) == prediction['response'])

    def label(self, response):
        from modular_decisions import semantic_response
        semantic = semantic_response(self.prompt, response)
        labels = []
        for c in semantic.get('selection', []):
            label = LABELS.get(c['kind'], c['kind'])
            if c.get('card'): label += ' ' + self.catalog[c['card']['code']]['name']
            if c.get('place'): label += f' {LOCATIONS[c["place"][1]]} {c["place"][2] + 1}'
            if 'value' in c: label += f' [{c["value"]}]'
            labels.append(label)
        return '；'.join(labels)
