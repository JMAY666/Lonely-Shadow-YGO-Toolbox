"""Read-only public-zone snapshots for the pinned YGOPro build.

This is NOT an event stream or a verified response window. Hidden opposing
identities and either deck order are never read. Gaps invalidate derived advice.
"""
import hashlib
import struct
from ygopro_capture import CaptureError, WindowsProcess, PROFILES, read_order

ZONE_NAMES = ('deck', 'hand', 'monster', 'spell', 'grave', 'banished', 'extra')
LOCATIONS = (1, 2, 4, 8, 16, 32, 64)


def read_snapshot(memory, base, profile, capture_id):
    before = read_order(memory, base, profile)
    if before['phase'] != 'detected': raise CaptureError('需要已开始的普通玩家对局；观战、录像或换边不支持')
    pointer_data = memory.read(base + profile['game'], 8)
    game = struct.unpack('<Q', pointer_data)[0]
    if memory.read(game + profile['building'], 2) != b'\x00\x00': raise CaptureError('编辑或换副期间不读取实战局面')
    info = memory.read(game + profile['duel_info'], 34)
    lp = list(struct.unpack_from('<2i', info, 12))
    if any(not 0 <= n <= 99999999 for n in lp): raise CaptureError('LP 数据尚未稳定')
    records, cards, counts, seen = [], [], {}, set()
    for zone_index, (zone, location) in enumerate(zip(ZONE_NAMES, LOCATIONS)):
        for player in (0, 1):
            address = game + profile['field_vectors'] + (zone_index * 2 + player) * 24
            header = memory.read(address, 24); records.append((address, header))
            start, end, capacity = struct.unpack('<3Q', header)
            if start == end == capacity == 0: pointers = b''
            elif (0x10000 <= start <= end <= capacity < 0x7fffffffffff and start % 8 == end % 8 == capacity % 8 == 0
                  and end-start <= 100*8 and capacity-start <= 8192):
                pointers = memory.read(start, end-start); records.append((start, pointers))
            else: raise CaptureError('区域边界或数量无效，等待稳定快照')
            nonzero = [r[0] for r in struct.iter_unpack('<Q', pointers) if r[0]]
            counts[f'{player}:{zone}'] = len(nonzero)
            if zone == 'deck' or player == 1 and zone in ('hand', 'extra'): continue
            for pointer in nonzero:
                if pointer < 0x10000 or pointer % 4: raise CaptureError('卡片指针无效')
                if pointer in seen: raise CaptureError('实体卡在多个位置重复出现，等待稳定快照')
                seen.add(pointer)
                # owner/controller/location/sequence/position follow the already
                # pinned ClientCard layout (code + 18 uint32 fields).
                address = pointer + profile['client_controller'] - 1
                metadata = memory.read(address, 5); records.append((address, metadata))
                owner, controller, card_location, sequence, position = metadata
                if owner not in (0, 1) or controller != player or card_location != location:
                    raise CaptureError('卡片正跨区域或变更控制权，等待下一快照')
                # Spell/trap and non-field zones also use POS_FACEUP (5) and
                # POS_FACEDOWN (10). Mixed faceup/facedown masks are not public.
                if zone in ('monster','spell','banished') and position not in (1,2,4,8,5,10):
                    raise CaptureError('公开表示状态尚未稳定，不读取该卡身份')
                faceup = bool(position & 5) or zone in ('hand', 'grave')
                code = 0
                level = tuner = None
                visible = player == 0 or zone == 'grave' or faceup
                if visible:
                    raw = memory.read(pointer + profile['client_code'], 4); records.append((pointer + profile['client_code'], raw))
                    code = struct.unpack('<I', raw)[0]
                    if not 0 <= code <= 0x0fffffff: raise CaptureError('卡号无效')
                    stats_address=pointer+profile['client_code']+12
                    stats=memory.read(stats_address,8);records.append((stats_address,stats))
                    card_type,level=struct.unpack('<2I',stats)
                    if level>255: raise CaptureError('当前等级超出已覆盖范围')
                    tuner=bool(card_type&0x1000)
                    if not card_type: level=tuner=None
                identifier = hashlib.sha256(f'{capture_id}:{pointer}'.encode()).hexdigest()[:32]
                cards.append({'id': identifier, 'code': code, 'owner': owner, 'controller': player, 'zone': zone,
                              'faceup': faceup, 'disabled': None, 'attack': None, 'attacks_left': None,
                              'level':level,'tuner':tuner,
                              'attack_position': position == 1, 'revealed': False})
    if (memory.read(base+profile['game'], 8) != pointer_data or memory.read(game+profile['duel_info'], 34) != info
            or any(memory.read(a, len(raw)) != raw for a, raw in records) or read_order(memory, base, profile) != before):
        raise CaptureError('读取时局面正在变化，未采用不一致快照')
    turn = before['evidence']['turn']
    first = before['evidence']['is_first']
    return {'turn': turn, 'order':before['detected_order'], 'player': 0 if (turn % 2 == 1) == first else 1, 'lp': lp,
            'cards': cards, 'opponent_hand': counts.get('1:hand'), 'counts': counts,
            'source': 'ygopro_public_snapshot', 'history_complete': False, 'window_verified': False,
            'capabilities': {'current_hand': True, 'public_zones': True, 'lp': True,
                             'card_level_and_tuner':True,
                             'events': False, 'phase': False, 'effect_usage': False, 'response_window': False},
            'note': '公开局面快照；阶段、连锁、次数和持续限制仍需核对，不能据此补造过程'}


def capture(capture_service, capture_id):
    with capture_service.lock:
        attached = capture_service.attached
        if not attached or attached.get('capture_id') != capture_id or attached.get('platform', 'ygopro') != 'ygopro':
            raise CaptureError('需要当前已连接的 YGOPro 进程')
        if attached['image_hash'] not in PROFILES: raise CaptureError('此客户端构建未覆盖公开局面读取')
        with WindowsProcess(attached['pid']) as memory:
            if memory.identity() != (attached['path'], attached['created']): raise CaptureError('客户端进程身份已变化')
            return read_snapshot(memory, memory.image_base(attached['pid']), PROFILES[attached['image_hash']], capture_id)
