"""Read-only MDPro3 IL2CPP opening capture for one fingerprinted Windows build.

Only read the target's submitted construction and our opening hand. No injected
code, remote calls, game inputs, deck-file imports or opponent card identities.
"""
import hashlib
import struct
import time

from capture_memory import CheckedMemory
from ygopro_capture import CaptureError


IMAGE_HASH = '73f8a589192da5833a637f87da1fde95b63591e0e3109c482f1be9df84a3001a'
COMPONENTS = {
    'GameAssembly.dll': '9807f77924e30d216a5700474e6263e23705d4ecc6772c7657d720d1ce0ae8a9',
    'UnityPlayer.dll': '40e6f3bf23ba46e8db03b75a307f87f2008601719d4e12bbabd4453f0243812e',
    'MDPro3_Data/il2cpp_data/Metadata/global-metadata.dat': 'f3b9acf0d253674edb97e7a1968386486deb772c03d93469ade57cd291b76056',
}
CLASSES = {
    'Program': (0x49a93f0, 'MDPro3'),
    'TcpHelper': (0x49473e0, 'MDPro3'),
    'OcgCore': (0x49988c8, 'MDPro3.Servant'),
    'RoomServant': (0x49b9fb0, 'MDPro3.Servant'),
}


def verify_build(image, digest):
    unsupported = {'supported': False, 'version': '未适配的 MDPRO3 构建'}
    if digest != IMAGE_HASH: return unsupported
    hashes = {}
    for relative, expected in COMPONENTS.items():
        path = image.parent / relative
        if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024: return unsupported
        with path.open('rb') as stream:
            hashes[relative] = hashlib.file_digest(stream, 'sha256').hexdigest()
        if hashes[relative] != expected: return unsupported
    return {'supported': True, 'version': 'MDPRO3 · Unity / IL2CPP x64（已核实构建）', 'component_hashes': hashes}


class Reader(CheckedMemory):
    def __init__(self, memory, assembly_base):
        self.memory, self.base, self.guards = memory, assembly_base, {}
        program = self.pointer(self.static('Program') + 8)
        self.core = self.pointer(program + 0xc8)
        self.room = self.pointer(program + 0xd0)
        self.cs, self.rs, self.tcp = self.static('OcgCore'), self.static('RoomServant'), self.static('TcpHelper')
        self.game = format(self.core, '016x')

    @staticmethod
    def fail():
        raise CaptureError('MDPRO3 数据尚未稳定或布局不符，等待下一次读取。')

    def static(self, name):
        rva, namespace = CLASSES[name]
        klass = self.pointer(self.base + rva)
        if (self.cstring(self.pointer(klass + 0x10, aligned=False)) != name
                or self.cstring(self.pointer(klass + 0x18, aligned=False)) != namespace): self.fail()
        return self.pointer(klass + 0xb8)

    def packet(self, package, prefix=None):
        stream = self.pointer(self.pointer(package + 16) + 16)
        buffer = self.pointer(stream + 0x28)
        origin, length = self.integer(stream + 0x30), self.integer(stream + 0x38)
        if origin != 0 or not 0 <= length <= 8192: self.fail()
        capacity = struct.unpack('<Q', self.read(buffer + 24, 8))[0]
        if not length <= capacity <= 1024 * 1024: self.fail()
        return self.read(buffer + 32, length if prefix is None else min(length, prefix))

    def packages(self):
        all_list, pending_list = self.pointer(self.cs + 0x198), self.pointer(self.cs + 0x190)
        packets = self.sequence(all_list, limit=200000, prefix=128)
        pending = self.sequence(pending_list, limit=200000, prefix=1)
        total, remaining = self.integer(all_list + 24), self.integer(pending_list + 24)
        if remaining > total: self.fail()
        processed = total - remaining
        if pending:
            head = self.pointer(self.pointer(all_list + 16) + 32 + 8 * processed)
            if head != pending[0]: self.fail()
        return packets, processed

    def state(self):
        cs, rs = self.cs, self.rs
        lobby, shown = self.boolean(self.room + 0x30), self.boolean(self.core + 0x30)
        ended = self.boolean(self.room + 0x48) or (shown and self.boolean(cs + 0x70))
        reconnect = self.boolean(rs + 0x1a)
        mode, player = self.read(rs + 5, 1)[0], self.integer(rs + 0x14)
        condition, turns = self.integer(cs + 0x7c), self.integer(cs + 0x28)
        first, observer = self.boolean(cs + 0x10), self.boolean(cs + 0x11)
        if not 0 <= player <= 15 or not 0 <= condition <= 3 or not 0 <= turns <= 100000: self.fail()
        unsupported = (mode != 0 or player >= 2 or self.boolean(rs + 0x19) or self.boolean(rs + 0x1b)
                       or (shown and (condition != 1 or observer or self.boolean(cs + 8) or self.boolean(cs + 9))))
        packets, processed = self.packages() if shown and not lobby and not unsupported else ([], 0)
        start = None
        for i, package in enumerate(packets[:processed]):
            if self.integer(package + 24) == 4:
                payload = self.packet(package)
                if len(payload) not in (17, 18): self.fail()
                start = (package, i, payload)
                break
        in_duel = bool(start and shown and not lobby and not reconnect and not unsupported and not ended)
        order = None
        if unsupported: phase = 'unsupported'
        elif lobby: phase = 'waiting_start'
        elif ended: phase = 'ended'
        elif in_duel:
            if start[2][0] not in (0, 1) or first != (start[2][0] == 0) or self.integer(cs + 0xc) != start[2][0]: self.fail()
            phase = 'detected' if turns >= 1 else 'waiting_choice'
            if turns >= 1: order = 'first' if first else 'second'
        elif reconnect or shown: phase = 'waiting_choice'
        else: phase = 'waiting_start'
        return {'phase': phase, 'detected_order': order, 'evidence': {
            'started': phase in ('waiting_choice', 'detected'), 'in_duel': in_duel,
            'finished': ended, 'is_first': first, 'turn': turns if in_duel else 0,
            'player_type': player, 'lobby_visible': lobby, 'rps_visible': False, 'order_visible': False,
            'duel_token': format(start[0], 'x') if in_duel else None,
        }}, start, packets, processed

    def deck(self):
        obj = self.pointer(self.tcp + 0x28)
        result = {}
        for zone, offset, limit in (('main', 16, 60), ('extra', 24, 15), ('side', 32, 15)):
            cards = self.sequence(self.pointer(obj + offset), 'I', limit)
            if not all(0 < code <= 0x0fffffff for code in cards): self.fail()
            result[zone] = cards
        if not 40 <= len(result['main']) <= 60: raise CaptureError('MDPRO3 本局主卡组不完整，需要 40–60 张。')
        return result

    def own_zones(self):
        counts, hand = [0] * 7, []
        locations = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6}
        for card in self.sequence(self.pointer(self.cs + 0xe0), limit=512):
            gps = self.pointer(card + 0x30)
            controller, location, seq, _ = struct.unpack('<4I', self.read(gps + 16, 16))
            if controller != 0 or location == 0: continue
            if location not in locations: raise CaptureError('开局区域已有叠放或未知位置，不能核对初始构筑。')
            counts[locations[location]] += 1
            if location == 2:
                code = self.integer(self.pointer(card + 0x20) + 0x10)
                if not 0 <= code <= 0x0fffffff: self.fail()
                hand.append((seq, code))
        hand.sort()
        if [seq for seq, _ in hand] != list(range(len(hand))) or any(n > 60 for n in counts): self.fail()
        return counts, [code for _, code in hand]

    def opening(self, frame, start, packets, processed, hand):
        draw = None
        if frame['evidence']['turn'] == 0:
            # Include the current message during its animation; hand equality
            # proves completion. Never use a later queued draw or a turn-1 hand.
            for package in packets[start[1] + 1:min(processed + 1, len(packets))]:
                kind = self.integer(package + 24)
                if kind == 40: break
                if kind != 90: continue
                head = self.packet(package, prefix=2)
                if len(head) != 2: self.fail()
                if head[0] != start[2][0]: continue
                raw = self.packet(package)
                if not 1 <= head[1] <= 60 or len(raw) != 2 + 4 * head[1] or draw is not None: self.fail()
                draw = [c & 0x7fffffff for (c,) in struct.iter_unpack('<I', raw[2:])]
                if not all(0 < c <= 0x0fffffff for c in draw): self.fail()
        return {'hand': hand, 'draw': draw, 'turn': frame['evidence']['turn']}

    def sample(self, with_deck=True, with_opening=True):
        frame, start, packets, processed = self.state()
        result = {'frame': frame, 'game': self.game}
        if frame['evidence']['in_duel'] and (with_deck or with_opening):
            counts, hand = self.own_zones()
            if with_opening: frame['opening_sample'] = self.opening(frame, start, packets, processed, hand)
            if with_deck:
                try:
                    if frame['evidence']['turn'] > 1: raise CaptureError('已错过正式开局构筑核对窗口，请等待下一局。')
                    deck = self.deck()
                    sizes = struct.unpack_from('<4H', start[2], len(start[2]) - 8)
                    own = sizes[:2] if frame['evidence']['is_first'] else sizes[2:]
                    if (own != (len(deck['main']), len(deck['extra'])) or counts[0] + counts[1] != own[0]
                            or counts[6] != own[1] or any(counts[2:6])):
                        raise CaptureError('MDPRO3 已提交构筑与服务器开局区域尚未对应，等待发牌稳定。')
                    result['construction'] = {'deck': deck, 'method': 'mdpro3-submitted-deck-and-msg-start',
                        'evidence': {'game': self.game, 'turn': frame['evidence']['turn'], 'own_counts': counts,
                                     'duel_token': frame['evidence']['duel_token']}}
                except CaptureError as error: result['deck_error'] = str(error)
        self.verify()
        return result

    def submitted_deck(self):
        frame, _, _, _ = self.state()
        if frame['phase'] != 'detected': raise CaptureError('MDPRO3 尚未进入有效对局，无法核对本局构筑。')
        deck = self.deck()
        self.verify()
        return deck

    def follow_sample(self, offset=0):
        """Read processed, retained packets, never pending animation results.

        Every ordinal is retained, including redacted/unsupported messages. This
        lets the consumer detect holes without reading hidden opponent identities.
        A bounded overlap checks that a cursor still addresses the same stream.
        """
        from duel_follow_events import read_packet
        frame, start, _, processed = self.state()
        if not start or not frame['evidence']['in_duel']:
            raise CaptureError('当前不在可跟随的正式对局中。')
        if frame['detected_order'] != 'first' or frame['evidence']['turn'] != 1:
            raise CaptureError('实时跟随首版仅支持 BO1 先攻第一回合。')
        if type(offset) is not int or not 0 <= offset <= processed or processed - offset > 4096:
            raise CaptureError('消息游标失效或积压超出上限，请重新同步。')
        all_list = self.pointer(self.cs + 0x198)
        array = self.pointer(all_list + 16)
        records = []
        for i in range(max(0, offset - 1), processed):
            package = self.pointer(array + 32 + i * 8)
            kind = self.integer(package + 24)
            stream = self.pointer(self.pointer(package + 16) + 16)
            buffer = self.pointer(stream + 0x28)
            origin, length = self.integer(stream + 0x30), self.integer(stream + 0x38)
            capacity = struct.unpack('<Q', self.read(buffer + 24, 8))[0]
            if origin or not 0 <= length <= 8192 or not length <= capacity <= 1024 * 1024:
                self.fail()
            def take(at, size):
                if at < 0 or at + size > length: self.fail()
                return self.read(buffer + 32 + at, size)
            records.append({'seq': i, 'ref': format(package, 'x'), 'message': kind,
                            **read_packet(kind, length, take)})
        own, counts = [], {}
        for card in self.sequence(self.pointer(self.cs + 0xe0), limit=512):
            gps = self.pointer(card + 0x30)
            controller, location, seq, pos = struct.unpack('<4I', self.read(gps + 16, 16))
            if controller != 0 or not location: continue
            if location not in (1, 2, 4, 8, 16, 32, 64, 132, 192): self.fail()
            counts[str(location)] = counts.get(str(location), 0) + 1
            # Deck / facedown Extra identities are unnecessary for following.
            if location == 1 or location == 64 and not pos & 5: continue
            code = self.integer(self.pointer(card + 0x20) + 0x10)
            if not 0 < code <= 0x0fffffff: self.fail()
            own.append({'instance_id': format(card, 'x'), 'code': code, 'controller': 0,
                        'location': location, 'sequence': seq, 'position': pos})
        pending = self.sequence(self.pointer(self.cs + 0x190), limit=200000, prefix=1)
        head = self.integer(pending[0] + 24) if pending else None
        self.verify()
        return {'schema': 1, 'game': self.game, 'duel_token': frame['evidence']['duel_token'],
                'turn': frame['evidence']['turn'], 'processed': processed, 'records': records,
                'prompt': head, 'sampled_ms': int(time.time() * 1000),
                'state': {'cards': own, 'counts': counts, 'source': 'mdpro3-read-only'}}
