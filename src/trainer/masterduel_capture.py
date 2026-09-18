"""Read-only Master Duel adapter for an explicitly verified IL2CPP build.

Read only our initialized deck and visible hand. No game calls, injection,
inputs, opponent identities, account data, or inspection of deck order.
"""
from functools import lru_cache
import hashlib
from pathlib import Path
import struct

from capture_memory import CheckedMemory
from ygopro_capture import CaptureError


IMAGE_HASH = 'f3b38f5419161dd5a70ffc51821761855a4ee9b63665cb47e5c2d86ca06448d6'
COMPONENTS = {
    'GameAssembly.dll': 'ca24a284a86dc394f6b0cbeaad455d29e5f6b95fc8db8fc42812b29de3c7620c',
    'UnityPlayer.dll': 'a181c9e0f270e41cb90d761d9248210d3fe9ea764d0f0e416410290d1b1341f1',
    'masterduel_Data/il2cpp_data/Metadata/global-metadata.dat': 'a49ae92c7036e19982b9c2cc25b2f7472825314d20b47eb6d4770bdbca319d88',
}
CLASSES = {'DuelClient': 0x3ab0b40, 'Engine': 0x3abcf30}
# Ordinary two-player modes only; replay, audience, tag and alternate rules fail closed.
MODES = {0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20}


def verify_build(image, digest):
    unsupported = {'supported': False, 'version': '未适配的 Master Duel 构建'}
    if digest != IMAGE_HASH: return unsupported
    hashes = {}
    for relative, expected in COMPONENTS.items():
        path = image.parent / relative
        if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024: return unsupported
        with path.open('rb') as stream:
            hashes[relative] = hashlib.file_digest(stream, 'sha256').hexdigest()
        if hashes[relative] != expected: return unsupported
    return {'supported': True, 'version': 'Master Duel · Unity / IL2CPP x64（已核实构建）', 'component_hashes': hashes}


@lru_cache(maxsize=1)
def card_ids():
    """Upstream's first mapping is canonical; later rows include beta aliases."""
    result = {}
    path = Path(__file__).parent / 'data/masterduel-ydk-ids.txt'
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        code, internal = map(int, line.split())
        if not 0 < code <= 0xffffffff or not 0 < internal < 100000: raise CaptureError('Master Duel 卡号映射资料无效。')
        result.setdefault(internal, code)
    return result


class Reader(CheckedMemory):
    def __init__(self, memory, assembly_base):
        self.memory, self.base, self.guards = memory, assembly_base, {}
        self.game = format(assembly_base, '016x')

    @staticmethod
    def fail():
        raise CaptureError('Master Duel 数据尚未稳定或布局不符，等待下一次读取。')

    def typename(self, obj):
        klass = self.pointer(obj)
        return self.cstring(self.pointer(klass + 16, aligned=False))

    def static(self, name):
        slot = struct.unpack('<Q', self.read(self.base + CLASSES[name], 8))[0]
        # IL2CPP leaves tagged metadata in a type slot until its first use.
        if slot < 0x10000 or slot & 1: return 0
        klass = self.pointer(self.base + CLASSES[name])
        if (self.cstring(self.pointer(klass + 16, aligned=False)) != name
                or self.cstring(self.pointer(klass + 24, aligned=False)) != 'YgomGame.Duel'): self.fail()
        return self.pointer(klass + 0xb8, nullable=True)

    def array(self, obj, element='Q', limit=60):
        count = struct.unpack('<Q', self.read(obj + 24, 8))[0]
        if not 0 <= count <= limit: self.fail()
        return list(struct.unpack('<' + str(count) + element, self.read(obj + 32, count * struct.calcsize(element))))

    def settings(self, obj):
        if self.typename(obj) != 'Dictionary`2': self.fail()
        # Guard the header/version and keys; never dereference unrelated values.
        self.read(obj + 16, 32)
        entries, count = self.pointer(obj + 24), self.integer(obj + 32)
        capacity = struct.unpack('<Q', self.read(entries + 24, 8))[0]
        if not 0 <= count <= capacity <= 512: self.fail()
        wanted = {'MyID', 'MyType', 'FirstPlayer', 'GameMode', 'Type', 'tag', 'is_pvp'}
        values = {}
        for index in range(count):
            address = entries + 32 + 24 * index
            hashcode, _, key, value = struct.unpack('<iiQQ', self.read(address, 24))
            if hashcode < 0 or not key: continue
            name = self.string(key)
            if name not in wanted: continue
            if name in values or not value: self.fail()
            kind = self.typename(value)
            if name in ('tag', 'is_pvp'):
                if kind != 'Boolean': self.fail()
                values[name] = self.boolean(value + 16)
            else:
                if kind not in ('Int32', 'Int64'): self.fail()
                values[name] = self.integer(value + 16) if kind == 'Int32' else struct.unpack('<q', self.read(value + 16, 8))[0]
        if values.keys() != wanted: self.fail()
        return values

    def translate(self, internal):
        code = card_ids().get(internal)
        if not code or code > 0x0fffffff: raise CaptureError(f'Master Duel 卡号 {internal} 尚无已核实映射，请更新适配资料。')
        return code

    def deck(self, initializer, mine):
        decks = self.pointer(initializer + 16)
        count = struct.unpack('<Q', self.read(decks + 24, 8))[0]
        if count not in (2, 4) or not 0 <= mine < count: self.fail()
        # Select our player before reading any card array.
        own = self.pointer(decks + 32 + 8 * mine)
        zones = self.array(own, limit=3)
        if len(zones) != 3: self.fail()
        result = {}
        for zone, array, limit in zip(('main', 'extra', 'side'), zones, (60, 15, 15)):
            result[zone] = [self.translate(code) for code in self.array(array, 'i', limit)] if array else []
        if not 40 <= len(result['main']) <= 60: raise CaptureError('Master Duel 本局主卡组不完整，需要 40–60 张。')
        return result

    def hand(self, client):
        manager = self.pointer(client + 0xd0)
        if not self.boolean(manager + 0x30) or self.boolean(manager + 0x31): self.fail()
        cards = []
        for item in self.sequence(self.pointer(manager + 16), limit=60):
            if self.boolean(item + 0x18): self.fail()
            cards.append((self.integer(item + 0x20), self.integer(item + 16)))
        cards.sort()
        if [i for i, _ in cards] != list(range(len(cards))): self.fail()
        return [self.translate(code) for _, code in cards]

    def engine_state(self, engine, mine, online):
        work = self.pointer(engine + (0x118 if online else 0x128))
        data = self.pointer(work + (0x18 if online else 0x10))
        info = self.pointer(data + 16)
        turn = self.integer(info + (0x14 if online else 0x10))
        phase = self.integer(info + (0x18 if online else 0x14))
        player = self.read(info + 0x24, 1)[0] if online else self.integer(info + 0x18)
        effect = self.integer(work + (0x60 if online else 0x68))
        if not 0 <= turn <= 100000 or phase not in (0, 1, 2, 3, 4, 5, 7) or player not in (0, 1) or not -1 <= effect <= 93: self.fail()
        matrix = self.pointer(info + (0x50 if online else 0x20))
        if struct.unpack('<Q', self.read(matrix + 24, 8))[0] != 38: self.fail()
        bounds = self.pointer(matrix + 16)
        # Il2CppArrayBounds is 16 bytes: uintptr length, int32 lower bound, padding.
        if (struct.unpack('<Qi', self.read(bounds, 12)) != (2, 0)
                or struct.unpack('<Qi', self.read(bounds + 16, 12)) != (19, 0)): self.fail()
        counts = []
        for position in range(18):
            cell = self.pointer(matrix + 32 + 8 * (mine * 19 + position))
            count = struct.unpack('<H', self.read(cell + 0x28, 2))[0] if online else self.integer(cell + 0x54)
            if not 0 <= count <= 60: self.fail()
            counts.append(count)
        return turn, phase, player, effect, counts

    def sample(self, with_deck=True, with_opening=True):
        evidence = {'started': False, 'in_duel': False, 'finished': False, 'is_first': False, 'turn': 0,
                    'player_type': 0, 'lobby_visible': True, 'rps_visible': False, 'order_visible': False,
                    'duel_token': None, 'selection_mechanism': 'coin_toss'}
        frame = {'phase': 'waiting_start', 'detected_order': None, 'evidence': evidence}
        result = {'frame': frame, 'game': self.game}
        client_static = self.static('DuelClient')
        client = self.pointer(client_static, nullable=True) if client_static else 0
        if client:
            step = self.integer(client + 0x1c4)
            if not 0 <= step <= 26: self.fail()
            if 17 <= step <= 25:
                frame['phase'] = 'ended'; evidence['finished'] = True
            elif step < 16 or step == 26:
                frame['phase'] = 'waiting_choice'; evidence.update(started=True, lobby_visible=False)
            else:
                self.live(result, client, with_deck, with_opening)
        self.verify()
        return result

    def live(self, result, client, with_deck, with_opening):
        frame, ev = result['frame'], result['frame']['evidence']
        if not self.boolean(client + 0x1f8): self.fail()
        initializer = self.pointer(client + 0xc0)
        if self.typename(initializer) != 'EngineInitializerByServer':
            frame['phase'] = 'unsupported'; return
        settings = self.settings(self.pointer(initializer + 0x28))
        mine, first = settings['MyID'], settings['FirstPlayer']
        if (mine not in (0, 1) or first not in (0, 1) or settings['MyType'] != 0
                or settings['GameMode'] not in MODES or settings['Type'] != 0 or settings['tag']):
            frame['phase'] = 'unsupported'; return
        engine = self.pointer(self.static('Engine') + 8)
        if (self.integer(self.pointer(engine + 16) + 16) != mine
                or self.integer(engine + 0xcc) != settings['GameMode']
                or self.boolean(engine + 0xc9) != settings['is_pvp']): self.fail()
        turn, phase, player, effect, counts = self.engine_state(engine, mine, settings['is_pvp'])
        if turn == 0 and player != first: self.fail()
        initial = turn == 0 and phase == 7 and effect == 1
        ev.update(started=True, in_duel=True, lobby_visible=False, is_first=mine == first,
                  turn=0 if turn == 0 and phase == 7 else turn + 1, player_type=mine,
                  duel_token=f'{client:x}:{initializer:x}', game_mode=settings['GameMode'],
                  initial_deal=initial, engine_turn=turn, engine_phase=phase)
        frame['phase'] = 'waiting_choice' if ev['turn'] == 0 else 'detected'
        if frame['phase'] == 'detected': frame['detected_order'] = 'first' if mine == first else 'second'
        if with_opening:
            hand = self.hand(client)
            if len(hand) != counts[13]: self.fail()
            # DuelStart runs only after the initial deal, before the first phase.
            draw = hand if initial and len(hand) == 5 else None
            frame['opening_sample'] = {'hand': hand, 'draw': draw, 'turn': ev['turn'],
                                       'method': 'masterduel-duel-start-and-own-hand'}
        if with_deck:
            try:
                if not initial: raise CaptureError('已错过 Master Duel 初始发牌窗口，请等待下一局。')
                deck = self.deck(initializer, mine)
                if (counts[15] + counts[13] != len(deck['main']) or counts[14] != len(deck['extra'])
                        or any(counts[:13]) or any(counts[16:])):
                    raise CaptureError('Master Duel 本局构筑与我方开局区域尚未对应。')
                result['construction'] = {'deck': deck, 'method': 'masterduel-initializer-and-duel-start',
                    'evidence': {'game': self.game, 'turn': ev['turn'], 'duel_token': ev['duel_token'],
                                 'own_counts': [counts[i] for i in (15, 13, 0, 7, 16, 17, 14)]}}
            except CaptureError as error: result['deck_error'] = str(error)

    def submitted_deck(self):
        sample = self.sample(False, False)
        if sample['frame']['phase'] != 'detected': raise CaptureError('Master Duel 尚未进入有效对局，无法核对本局构筑。')
        client = self.pointer(self.static('DuelClient'))
        deck = self.deck(self.pointer(client + 0xc0), sample['frame']['evidence']['player_type'])
        self.verify()
        return deck
