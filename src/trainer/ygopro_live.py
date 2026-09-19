"""Player-visible resource snapshots for one fingerprinted YGOPro layout.

Polling is not an event tape. No rules, response permissions, persistent card
instances, deck order, or causes of movement are inferred from these snapshots.
"""
import struct

from ygopro_capture import CaptureError, read_order


LAYOUT = 'ygopro-55dd3e8e-public-resources-v1'
ZONES = (1, 2, 4, 8, 16, 32, 64)
MISSING = ['当前阶段与回合玩家', '完整连锁及合法响应窗口', '素材与指示物', '效果次数、持续限制与召唤权限',
           '两次采样之间的公开事件、费用及移动原因', '卡池与禁限表认证']


def read_snapshot(memory, base, profile):
    before = read_order(memory, base, profile)
    if before['phase'] != 'detected':
        raise CaptureError('仅在已确认的普通玩家对局中读取公开资源；准备、录像、观战及单人谜题不支持。')
    guards = []
    def read(address, size):
        raw = memory.read(address, size)
        guards.append((address, raw))
        return raw
    game = struct.unpack('<Q', read(base + profile['game'], 8))[0]
    if read(game + profile['building'], 2) != b'\0\0':
        raise CaptureError('编辑或换副期间不能读取本局资源。')
    # Adjacent fields in the pinned client sources: DuelInfo.lp follows its
    # twelve bools; ClientCard owner/controller/location/sequence/position are
    # five consecutive bytes. Existing probes anchor duel_info, code and d1.
    lp = list(struct.unpack('<2i', read(game + profile['duel_info'] + 12, 8)))
    if any(v < 0 or v > 2**31 - 1 for v in lp):
        raise CaptureError('生命值暂不完整，等待结算稳定。')
    counts, cards, seen = [dict(), dict()], [], set()
    for zone_index, location in enumerate(ZONES):
        for player in (0, 1):
            header = read(game + profile['field_vectors'] + 24 * (2 * zone_index + player), 24)
            start, end, capacity = struct.unpack('<3Q', header)
            limit = 7 if location == 4 else 8 if location == 8 else 120
            if start == end == capacity == 0:
                pointers = []
            elif (0x10000 <= start <= end <= capacity < 0x7fffffffffff and
                  start % 8 == end % 8 == capacity % 8 == 0 and end - start <= limit * 8 and capacity - start <= 8192):
                pointers = [p for p, in struct.iter_unpack('<Q', read(start, end - start))]
            else:
                raise CaptureError('区域容器未稳定或超出读取范围。')
            counts[player][str(location)] = sum(p != 0 for p in pointers)
            if location not in (4, 8) and any(p == 0 for p in pointers):
                raise CaptureError('非场上区域出现空指针，等待区域完整。')
            # Neither deck is inspected, nor is the opponent's hand dereferenced.
            if location == 1 or player == 1 and location == 2:
                continue
            for sequence, pointer in enumerate(pointers):
                if not pointer and location in (4, 8): continue
                if pointer < 0x10000 or pointer % 8 or pointer in seen:
                    raise CaptureError('卡牌指针重复或区域正在移动。')
                seen.add(pointer)
                owner, controller, actual_location, actual_sequence, position = read(pointer + profile['client_controller'] - 1, 5)
                if owner not in (0, 1) or controller != player or actual_location != location or actual_sequence != sequence:
                    raise CaptureError('卡牌位置与所属区域不一致，等待下一次快照。')
                if position not in (1, 2, 4, 8, 5, 10) or location == 4 and position not in (1, 2, 4, 8):
                    raise CaptureError('卡牌表示形式未稳定。')
                public = player == 0 or location == 16 or bool(position & 5)
                code = None
                if public:
                    code = struct.unpack('<I', read(pointer + profile['client_code'], 4))[0]
                    if not 0 < code <= 0x0fffffff:
                        raise CaptureError('已公开卡牌身份尚未完整，等待下一次快照。')
                # Unknown extra-deck cards stay aggregate counts, never a private
                # order. Sequence is only a snapshot location, not an instance id.
                if player == 1 and location == 64 and not public: continue
                cards.append({'controller': player, 'owner': owner, 'location': location,
                              'sequence': sequence, 'position': position, 'code': code})
    if any(memory.read(a, len(b)) != b for a, b in guards) or read_order(memory, base, profile) != before:
        raise CaptureError('读取期间局面变化，未发布混合快照。')
    return {'layout': LAYOUT, 'game': f'{game:x}', 'turn': before['evidence']['turn'],
            'order': before['detected_order'], 'lp': lp, 'counts': counts, 'cards': cards,
            'missing': MISSING, 'phase': None, 'rules_complete': False}
