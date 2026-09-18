"""Read-only YGOPRO2 opening adapter for an explicitly fingerprinted Mono build.

Resolve the loaded assembly and static singleton through Mono metadata on every
sample. Never call remote functions, inject code, scan for card ids, or use deck
files. Object offsets below were checked against this build's runtime metadata.
"""
import hashlib
import struct

from capture_memory import CheckedMemory
from ygopro_capture import CaptureError


IMAGE_HASH = '41f8e00d3b06251156a872078d7dd2a1e394f605a29e42778c022e33ffc76594'
COMPONENTS = {
    'Mono/mono.dll': 'bd7220882de40904bb6081540427937b06602ef6d4309d2b311f2cf74be2b076',
    'Managed/Assembly-CSharp.dll': 'e18b96ba7649075cb1132c5993201326ad2df0ddd7eccfce809f87801510bb1d',
    'Managed/mscorlib.dll': '57e3a820a75c409fa1965a550d8f0d74eb4e1364d98afd0424a7f617c7b4487f',
    'Managed/UnityEngine.dll': '879924003f092619e29ba6da93f599e82df671868494ae1b32927d9d5b3fd66d',
}


def verify_build(image, digest):
    result = {'supported': False, 'version': '未适配的 YGOPRO2 构建'}
    if digest != IMAGE_HASH: return result
    hashes = {}
    for relative, expected in COMPONENTS.items():
        path = image.parent / (image.stem + '_Data') / relative
        if not path.is_file() or path.stat().st_size > 128 * 1024 * 1024: return result
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        if hashes[relative] != expected: return result
    return {'supported': True, 'version': 'YGOPRO2 · Unity / Mono x64（已核实构建）', 'component_hashes': hashes}


class Reader(CheckedMemory):
    def __init__(self, memory, mono_base):
        self.memory, self.base, self.guards = memory, mono_base, {}
        domain = self.pointer(mono_base + 0x2655e0)
        self.domain_id = self.integer(domain + 0xbc)
        if not 0 <= self.domain_id < 256: self.fail()
        node = self.pointer(mono_base + 0x265310, nullable=True)
        image, visited = None, set()
        for _ in range(128):
            if not node: break
            if node in visited: self.fail()
            visited.add(node)
            assembly = self.pointer(node)
            candidate = self.pointer(assembly + 0x58)
            if self.cstring(self.pointer(candidate + 0x28, aligned=False)) == 'Assembly-CSharp':
                image = candidate
                break
            node = self.pointer(node + 8, nullable=True)
        if image is None: raise CaptureError('YGOPRO2 尚未加载游戏程序集，请稍后重新捕捉。')
        self.image = image
        program_static = self.static(0x020001e9, 'Program')
        self.program = self.pointer(program_static)
        self.core = self.pointer(self.program + 1136)
        self.room = self.pointer(self.program + 1112)
        self.tcp = self.static(0x020001c5, 'TcpHelper')
        self.game = format(self.core, '016x')

    @staticmethod
    def fail():
        raise CaptureError('YGOPRO2 数据尚未稳定或布局不符，等待下一次读取。')

    def static(self, token, name):
        table = self.image + 0x3d0
        size = self.integer(table + 0x18)
        if not 1 <= size <= 65536: self.fail()
        slots = self.pointer(table + 0x20)
        klass = self.pointer(slots + 8 * (token % size), nullable=True)
        for _ in range(128):
            if not klass: break
            if self.integer(klass + 0x58) == token:
                if self.pointer(klass + 0x40) != self.image or self.cstring(self.pointer(klass + 0x48, aligned=False)) != name:
                    self.fail()
                runtime = self.pointer(klass + 0xf8)
                if struct.unpack('<H', self.read(runtime, 2))[0] < self.domain_id: self.fail()
                vtable = self.pointer(runtime + 8 + 8 * self.domain_id)
                if self.pointer(vtable) != klass: self.fail()
                return self.pointer(vtable + 0x18)
            klass = self.pointer(klass + 0x100, nullable=True)
        raise CaptureError('YGOPRO2 尚未初始化所需对象，请稍后重新捕捉。')

    def packages(self):
        return self.sequence(self.pointer(self.core + 232), limit=200000, prefix=128)

    def packet(self, package, prefix=None):
        master = self.pointer(package + 16)
        stream = self.pointer(master + 16)
        length = self.integer(stream + 32)
        initial = self.integer(stream + 48)
        if initial != 0 or not 0 <= length <= 8192: self.fail()
        buffer = self.pointer(stream + 40)
        capacity = struct.unpack('<Q', self.read(buffer + 24, 8))[0]
        if not length <= capacity <= 1024 * 1024: self.fail()
        return self.read(buffer + 32, length if prefix is None else min(length, prefix))

    def state(self):
        core, room = self.core, self.room
        lobby = self.boolean(room + 104)
        shown = self.boolean(core + 104)
        ended = self.boolean(room + 188)
        side = self.boolean(room + 189) or self.boolean(room + 190)
        reconnect = self.boolean(room + 191)
        player = self.integer(room + 212)
        mode = self.read(room + 197, 1)[0]
        condition = self.integer(core + 456)
        turns = self.integer(core + 536)
        index = self.integer(core + 472)
        first, observer = self.boolean(core + 582), self.boolean(core + 583)
        swapped = self.boolean(self.pointer(core + 128) + 128)
        choice = self.string(self.pointer(room + 72, nullable=True)) if self.pointer(room + 80, nullable=True) else ''
        if not (-1 <= index <= 200000 and 0 <= turns <= 100000 and 0 <= condition <= 3 and 0 <= player <= 15): self.fail()
        start = None
        packets = self.packages() if shown and not lobby else []
        for i, p in enumerate(packets):
            if i > index: break
            if self.integer(p + 24) == 4:
                payload = self.packet(p)
                if len(payload) not in (17, 18): self.fail()
                start = (p, i, payload)
                break
        in_duel = bool(start and shown and not reconnect and not lobby)
        unsupported = mode != 0 or side or condition in (2, 3) or player >= 2 or (shown and (observer or swapped))
        order = None
        if unsupported: phase = 'unsupported'
        elif lobby: phase = 'waiting_start'
        elif ended: phase = 'ended'
        elif in_duel:
            if start[2][0] not in (0, 1) or first != (start[2][0] == 0): self.fail()
            phase = 'detected' if turns >= 1 else 'waiting_choice'
            if turns >= 1: order = 'first' if first else 'second'
        elif choice == 'StocMessage_SelectTp': phase = 'choose_order'
        elif choice == 'StocMessage_SelectHand': phase = 'rps'
        elif reconnect and condition == 1: phase = 'waiting_choice'
        else: phase = 'waiting_start'
        return {'phase': phase, 'detected_order': order, 'evidence': {
            'started': phase in ('rps', 'choose_order', 'waiting_choice', 'detected'),
            'in_duel': in_duel, 'finished': ended, 'is_first': first, 'turn': turns if in_duel else 0,
            'player_type': player, 'lobby_visible': lobby, 'rps_visible': choice == 'StocMessage_SelectHand',
            'order_visible': choice == 'StocMessage_SelectTp', 'duel_token': format(start[0], 'x') if in_duel else None,
        }}, start, packets, index

    def deck(self):
        deck = self.pointer(self.tcp + 40)
        result = {}
        for zone, offset, limit in (('main', 16, 60), ('extra', 24, 15), ('side', 32, 15)):
            cards = self.sequence(self.pointer(deck + offset), 'I', limit)
            if not all(0 < code <= 0x0fffffff for code in cards): self.fail()
            result[zone] = cards
        if not 40 <= len(result['main']) <= 60: raise CaptureError('YGOPRO2 本局主卡组不完整，需要 40–60 张。')
        return result

    def own_zones(self):
        counts = [0] * 7
        hand = []
        locations = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6}
        for card in self.sequence(self.pointer(self.core + 144), limit=512):
            controller, location, sequence, _ = struct.unpack('<4I', self.read(card + 280, 16))
            if controller != 0 or location == 0: continue
            if location not in locations: raise CaptureError('开局区域已有叠放或未知位置，不能核对初始构筑。')
            counts[locations[location]] += 1
            if location == 2:
                code = self.integer(self.pointer(card + 40) + 72)
                if not 0 <= code <= 0x0fffffff: self.fail()
                hand.append((sequence, code))
        hand.sort()
        if [s for s, _ in hand] != list(range(len(hand))) or any(n > 60 for n in counts): self.fail()
        return counts, [code for _, code in hand]

    def opening(self, frame, start, packets, index, hand):
        draw = None
        if frame['evidence']['turn'] == 0:
            for i in range(start[1] + 1, min(index + 1, len(packets))):
                package = packets[i]
                kind = self.integer(package + 24)
                if kind == 40: break  # Initial draws must precede the first turn.
                if kind != 90: continue
                head = self.packet(package, prefix=2)
                if len(head) != 2: self.fail()
                if head[0] != start[2][0]: continue  # Never read the other player's card ids.
                raw = self.packet(package)
                if not 1 <= head[1] <= 60 or len(raw) != 2 + 4 * head[1] or draw is not None: self.fail()
                draw = [c & 0x7fffffff for (c,) in struct.iter_unpack('<I', raw[2:])]
                if not all(0 < c <= 0x0fffffff for c in draw): self.fail()
        return {'hand': hand, 'draw': draw, 'turn': frame['evidence']['turn']}

    def sample(self, with_deck=True, with_opening=True):
        frame, start, packets, index = self.state()
        result = {'frame': frame, 'game': self.game}
        if frame['phase'] in ('waiting_choice', 'detected') and frame['evidence']['in_duel']:
            if with_deck or with_opening:
                counts, hand = self.own_zones()
                if with_opening: frame['opening_sample'] = self.opening(frame, start, packets, index, hand)
                if with_deck:
                    try:
                        if frame['evidence']['turn'] > 1: raise CaptureError('已错过正式开局构筑核对窗口，请等待下一局。')
                        deck = self.deck()
                        sizes = struct.unpack_from('<4H', start[2], len(start[2]) - 8)
                        own = sizes[:2] if frame['evidence']['is_first'] else sizes[2:]
                        if (own != (len(deck['main']), len(deck['extra'])) or counts[0] + counts[1] != own[0]
                                or counts[6] != own[1] or any(counts[2:6])):
                            raise CaptureError('YGOPRO2 已提交构筑与服务器开局区域尚未对应，等待发牌稳定。')
                        result['construction'] = {'deck': deck, 'method': 'ygopro2-submitted-deck-and-msg-start',
                            'evidence': {'game': self.game, 'turn': frame['evidence']['turn'], 'own_counts': counts,
                                         'duel_token': frame['evidence']['duel_token']}}
                    except CaptureError as error: result['deck_error'] = str(error)
        self.verify()
        return result

    def submitted_deck(self):
        frame, _, _, _ = self.state()
        if frame['phase'] != 'detected': raise CaptureError('YGOPRO2 尚未进入有效对局，无法核对本局构筑。')
        deck = self.deck()
        self.verify()
        return deck
