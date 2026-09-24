"""Platform-neutral, fail-closed operation evidence for read-only tutorials.

Raw messages are adapter input, never UI instructions. Instance identities are
reconstructed from ordered moves and slots, then checked against live snapshots.
No plan snapshot is used as a measurement of the game.
"""
from collections import Counter
from copy import deepcopy
import struct


class EvidenceError(ValueError):
    pass


# These messages contain no operation result needed by this first-turn matcher.
# Choices are not confirmations: their observable result must match later moves,
# targets and chain outcomes. Unknown messages stop matching, not silently skip.
NOISE = {2, 3, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
         21, 22, 23, 24, 25, 26, 30, 31, 32, 38, 39, 42, 160, 163, 164, 165}
LENGTHS = {50: 16, 53: 9, 54: 8, 60: 8, 61: 0, 62: 8, 63: 0, 64: 8,
           65: 0, 70: 16, 71: 1, 72: 1, 73: 1, 74: 0, 75: 1, 76: 1,
           40: 1, 41: 2, 91: 5, 92: 5, 94: 5, 100: 5}
CARD_MESSAGES = {50, 53, 54, 60, 62, 64, 70}
RANDOM = {81, 90, 130, 131}


def read_packet(kind, length, take):
    """Privacy filter called *before* touching card IDs in remote memory."""
    if kind in NOISE:
        return {}
    if kind == 4:
        if length not in (17, 18): raise EvidenceError('开局消息长度异常')
        return {'raw': take(0, length).hex()}
    if kind in CARD_MESSAGES:
        if length != LENGTHS[kind]: raise EvidenceError('操作消息长度异常')
        origin = take(4, 4)
        dest = take(8, 4) if kind == 50 else origin
        if origin[0] != 0 or dest[0] != 0:
            return {'opponent': True}
    elif kind in (80, 83):
        # CardSelected has a player byte; BecomeTarget does not.
        base = 2 if kind == 80 else 1
        if length < base: raise EvidenceError('对象消息不完整')
        count = take(base - 1, 1)[0]
        if length != base + 4 * count: raise EvidenceError('对象消息长度异常')
        if kind == 80 and take(0, 1)[0] != 0 or any(take(base + i*4, 1)[0] != 0 for i in range(count)):
            return {'opponent': True}
    elif kind in (33, 90):
        if length < 2: raise EvidenceError('发牌消息不完整')
        player, count = take(0, 2)
        if length != 2 + count * 4: raise EvidenceError('发牌消息长度异常')
        if player != 0: return {'opponent_draw': True}
    elif kind in LENGTHS:
        if length != LENGTHS[kind]: raise EvidenceError('对局消息长度异常')
    else:
        return {'unsupported': True}
    return {'raw': take(0, length).hex()}


def packet(kind, raw):
    """Apply the same decoder to local engine evidence and adapter evidence."""
    return {'message': kind, **read_packet(kind, len(raw), lambda at, size: raw[at:at+size])}


def loc(raw, at=0):
    return dict(zip(('controller', 'location', 'sequence', 'position'), raw[at:at+4]))


def slot(card):
    return (card['location'], card['sequence'], card['position'] if card['location'] & 128 else 0)


def visible(card):
    return card['location'] not in (0, 1) and (card['location'] != 64 or card.get('position', 0) & 5)


def signature(state):
    cards = state.get('cards', [])
    # Sequence matters for field zones and materials. Hand/grave ordering is
    # still used by the instance reducer, but not by cross-engine board checks.
    values = Counter((c['code'], c['location'], c.get('sequence', 0) if c['location'] in (4, 8) or c['location'] & 128 else 0,
                      c.get('position', 0) if c['location'] in (4, 8, 32, 64) or c['location'] & 128 else 0)
                     for c in cards if c.get('controller', 0) == 0 and visible(c))
    counts = {int(k): v for k, v in state.get('counts', {}).items() if v}
    return values, counts


class Journal:
    """Ordered stream reducer. Each material/card retains its own identity."""
    def __init__(self, hand=None, main=0, extra=0):
        self.cards = []
        self.counts = Counter({1: main, 64: extra})
        self.serial = 0
        self.turn = 0
        self.chains = set()
        self.summons = set()
        self.tokens = []
        self.started = False
        self.problem = ''
        if hand is not None:
            self.started = True
            for seq, code in enumerate(hand): self.create(code, {'location': 2, 'sequence': seq, 'position': 0})
            self.counts[1] -= len(hand); self.counts[2] = len(hand)

    def create(self, code, position):
        self.serial += 1
        card = {'uid': str(self.serial), 'code': code, 'controller': 0, **position}
        self.cards.append(card)
        return card

    def find(self, position, code=None):
        found = [c for c in self.cards if slot(c) == slot(position)]
        if len(found) != 1 or code and found[0]['code'] != code:
            raise EvidenceError('卡牌实例或位置不能唯一对应，需重新核对')
        return found[0]

    def state(self):
        return {'cards': deepcopy(self.cards), 'counts': dict(self.counts)}

    @property
    def settled(self):
        return not self.chains and not self.summons

    def apply(self, record):
        kind = record['message']
        if not self.started and kind != 4: return None
        if record.get('opponent'):
            raise EvidenceError('检测到对方操作或控制权变化，当前路线需要人工核对')
        if record.get('unsupported'):
            raise EvidenceError(f'消息 {kind} 尚无可靠完成判据，暂停自动推进')
        if kind in NOISE or record.get('opponent_draw'): return None
        raw = bytes.fromhex(record.get('raw', ''))
        if kind == 4:
            if self.started: raise EvidenceError('检测到新的开局消息')
            main, extra = struct.unpack_from('<2H', raw, len(raw)-8)
            self.counts.update({1: main, 64: extra}); self.started = True
            return None
        if kind == 40:
            self.turn += 1
            if self.turn != 1 or raw != b'\0': raise EvidenceError('已离开先攻第一回合')
            return None
        if kind == 41:
            if int.from_bytes(raw, 'little') not in (1, 2, 4): raise EvidenceError('已离开先攻主要阶段一')
            return None
        if kind in RANDOM:
            if kind != 90 or self.turn: raise EvidenceError('出现随机结果，需要报告实际结果后重新核对路线')
            if self.counts[2]: raise EvidenceError('初始发牌记录重复')
            for i in range(raw[1]):
                self.create(struct.unpack_from('<I', raw, 2+i*4)[0] & 0x7fffffff,
                            {'location': 2, 'sequence': i, 'position': 0})
            self.counts[1] -= raw[1]; self.counts[2] += raw[1]
            return None
        if kind == 33:
            codes = [struct.unpack_from('<I', raw, 2+i*4)[0] & 0x7fffffff for i in range(raw[1])]
            hand = [c for c in self.cards if c['location'] == 2]
            if Counter(codes) != Counter(c['code'] for c in hand): raise EvidenceError('洗切手牌与已知手牌份数不符')
            if len(set(codes)) != len(codes): raise EvidenceError('洗切后同名手牌实例不再能唯一对应，需要人工核对')
            for seq, code in enumerate(codes): next(c for c in hand if c['code'] == code)['sequence'] = seq
            token = {'message': kind, 'cards': deepcopy(sorted(hand, key=lambda c:c['code'])),
                     'seq': record.get('seq'), 'settled': self.settled}
            self.tokens.append(token)
            return token
        if kind in (75, 76): raise EvidenceError('发动或效果被无效，不能按成功推进')
        token = {'message': kind, 'cards': []}
        if kind in CARD_MESSAGES:
            code = struct.unpack_from('<I', raw)[0] & 0x7fffffff
            origin = loc(raw, 4)
            if origin['controller'] != 0: raise EvidenceError('路线涉及对方操作')
            if kind == 50:
                dest = loc(raw, 8)
                if visible(origin):
                    card = self.find(origin, code or None)
                else:
                    card = self.create(code, origin)
                if not card['code'] and visible(dest): raise EvidenceError('移动卡牌身份未知')
                token.update(cards=[deepcopy(card)], origin=origin, destination=dest,
                             reason=struct.unpack_from('<I', raw, 12)[0] & (0x80 | 8))
                # Xyz materials may attach while their host is still in Extra
                # (0xC0), then travel with that exact host into the monster zone.
                if not origin['location'] & 128:
                    for material in self.cards:
                        if material is not card and material['location'] == (origin['location'] | 128) and material['sequence'] == origin['sequence']:
                            self.counts[material['location']] -= 1
                            material.update(location=dest['location'] | 128, sequence=dest['sequence'])
                            self.counts[material['location']] += 1
                for other in self.cards:
                    if other is not card and other['location'] == origin['location'] and origin['location'] in (2, 16, 32, 64) and other['sequence'] > origin['sequence']:
                        other['sequence'] -= 1
                    if other is not card and origin['location'] & 128 and other['location'] == origin['location'] and other['sequence'] == origin['sequence'] and other['position'] > origin['position']:
                        other['position'] -= 1
                for other in self.cards:
                    if other is not card and other['location'] == dest['location'] and dest['location'] in (2, 16, 32, 64) and other['sequence'] >= dest['sequence']:
                        other['sequence'] += 1
                    if other is not card and dest['location'] & 128 and other['location'] == dest['location'] and other['sequence'] == dest['sequence'] and other['position'] >= dest['position']:
                        other['position'] += 1
                self.counts[origin['location']] -= 1; self.counts[dest['location']] += 1
                if self.counts[origin['location']] < 0: raise EvidenceError('区域数量不一致，可能漏采')
                card.update(dest)
                if not visible(dest): self.cards.remove(card)
            else:
                card = self.find(origin, code)
                token['cards'] = [deepcopy(card)]
                if kind == 53:
                    card['position'] = raw[8]; token['position'] = raw[8]
                if kind == 70:
                    token['description'] = struct.unpack_from('<I', raw, 11)[0]
                    token['chain'] = raw[15]; self.chains.add(raw[15])
                if kind in (60, 62, 64): self.summons.add(kind+1)
        elif kind in (61, 63, 65):
            if kind not in self.summons: raise EvidenceError('缺少召唤开始证据')
            self.summons.remove(kind)
        elif kind in (71, 72, 73):
            token['chain'] = raw[0]
            if raw[0] not in self.chains: raise EvidenceError('连锁事件不连续')
        elif kind == 74:
            self.chains.clear()
        elif kind in (80, 83):
            base = 2 if kind == 80 else 1
            token['cards'] = [deepcopy(self.find(loc(raw, base+i*4))) for i in range(raw[base-1])]
        elif kind in (91, 92, 94, 100):
            token.update(player=raw[0], amount=struct.unpack_from('<I', raw, 1)[0])
        else:
            raise EvidenceError(f'消息 {kind} 未实现可靠判据')
        token.update(seq=record.get('seq'), settled=self.settled)
        self.tokens.append(token)
        return token


def match_token(expected, actual, bindings):
    """Bind instances on first verifiable use, never just match a card name."""
    if expected['message'] != actual['message']: return False
    for key in ('description', 'chain', 'position', 'reason', 'player', 'amount'):
        if expected.get(key) != actual.get(key): return False
    for key in ('origin', 'destination'):
        a, b = expected.get(key), actual.get(key)
        if a is None and b is None: continue
        if not a or not b or a['location'] != b['location']: return False
        if (a['location'] in (4, 8) or a['location'] & 128) and (a['sequence'], a['position']) != (b['sequence'], b['position']): return False
    actual_cards = actual['cards']
    if expected['message'] == 33:
        # Saved opening requirements may be a subset of this game's hand. The
        # reducer verified the whole actual shuffle; bind only the route's cards.
        actual_cards = []
        for card in expected['cards']:
            matches = [c for c in actual['cards'] if c['code'] == card['code']]
            if len(matches) != 1: return False
            actual_cards.append(matches[0])
    if len(expected['cards']) != len(actual_cards): return False
    trial = dict(bindings)
    for a, b in zip(expected['cards'], actual_cards):
        if a['code'] != b['code'] or a['location'] != b['location']: return False
        if (a['location'] in (4, 8) or a['location'] & 128) and slot(a) != slot(b): return False
        # Unknown deck/Extra slots have no stable identity before becoming public.
        if a['uid'] in trial and trial[a['uid']] != b['uid']: return False
        if a['uid'] not in trial and b['uid'] in trial.values(): return False
        trial[a['uid']] = b['uid']
    bindings.clear(); bindings.update(trial)
    return True
