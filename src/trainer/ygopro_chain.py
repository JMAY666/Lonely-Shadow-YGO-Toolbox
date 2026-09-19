"""Public chain-list and narrowly confirmed own client-menu observations.

This reads current client presentation, not a complete event tape or a rules
engine's permission. No opaque native response bytes are returned or executed.
"""
import struct

from ygopro_capture import CaptureError


def vector_span(read, address, stride, limit):
    start, end, capacity = struct.unpack('<3Q', read(address, 24))
    if start == end == capacity == 0: return 0, 0
    if not (0x10000 <= start <= end <= capacity < 0x7fffffffffff and start % 8 == 0
            and (end-start) % stride == 0 and (capacity-start) % stride == 0
            and end-start <= limit*stride and capacity-start <= 8192):
        raise CaptureError('连锁或选择列表边界无效，未读取不确定内容。')
    return start, end-start


def vector(read, address, stride, limit):
    start, size = vector_span(read, address, stride, limit)
    return read(start, size) if size else b''


def chain_snapshot(read, game, profile, message):
    if message in (70, 74):
        return {'status':'updating', 'links':[], 'notice':'客户端正在更新连锁列表，空列表不能解释为没有连锁'}
    raw = vector(read, game + profile['chain_vector'], 64, 32)
    links = []
    for index in range(0, len(raw), 64):
        code, description, player, location, sequence, started = struct.unpack_from('<IIiiiB', raw, index+24)
        if (not 0 < code <= 0x0fffffff or player not in (0,1) or location not in (1,2,4,8,16,32,64,128,132)
                or not 0 <= sequence < 120 or started not in (0,1)):
            raise CaptureError('连锁条目尚未稳定，不能猜测发动来源。')
        if location in (4,8) and sequence >= (7 if location==4 else 8):
            raise CaptureError('连锁来源位置无效。')
        links.append({'link': len(links)+1, 'code': code, 'description': description, 'controller': player,
                      'location': location, 'sequence': sequence if location in (4,8) else None,
                      'processing_started': bool(started), 'source': 'client_announced_chain'})
    return {'status':'snapshot', 'links':links,
            'notice':'当前客户端已入列的公开条目；处理开始不等于已结算，无效类型与对象尚未读取'}


def response_snapshot(read, base, game, profile, first, message, cards, references):
    unknown = {'status':'unconfirmed', 'choices':[], 'omitted':0, 'rules_verified':False,
               'notice':'尚未确认本期支持的我方连锁选择；不表示没有合法响应'}
    if message != 16: return unknown
    hint = struct.unpack('<Q', read(game + profile['hint_widget'], 8))[0]
    if not 0x10000 <= hint < 0x7fffffffffff or hint % 8: raise CaptureError('选择提示控件未稳定。')
    visible = read(hint + profile['gui_visible'], 1)[0]
    if visible not in (0,1): raise CaptureError('选择提示可见标记无效。')
    if not visible: return unknown
    length = struct.unpack('<Q', read(base + profile['message_size'], 8))[0]
    if not 12 <= length <= 12+120*14: return unknown
    # Verify the addressed player before reading any choice payload. A cached
    # message for another player does not become our known decision information.
    head = read(base + profile['message'], 2)
    if head[0] != 16 or head[1] not in (0,1) or (head[1] if first else 1-head[1]) != 0:
        return unknown
    header = read(base + profile['message'], 12);count = header[2]
    if length != 12 + 14*count: return unknown
    if header[3] == 0x7f:
        return {**unknown,'notice':'当前为诱发效果选择，尚未认证为交康响应窗口'}
    pointers, pointer_size = vector_span(read, game + profile['activation_vector'], 8, 120)
    descriptions, description_size = vector_span(read, game + profile['activation_descriptions'], 8, 120)
    if pointer_size != count*8 or description_size != count*8: return unknown
    known = {(c['controller'],c['location'],c['sequence']):c for c in cards if c.get('code') and c['location'] != 128}
    choices, omitted = [], 0
    for index in range(count):
        offset = base + profile['message'] + 12+14*index
        flag, forced = read(offset, 2)
        player, location, sequence, _position = read(offset+6, 4)
        if player not in (0,1) or forced not in (0,1): return unknown
        local = player if first else 1-player
        key = (local,location,sequence);card = known.get(key)
        # Deck identities/order, overlays, reset operations and foreign effects
        # require their own evidence. They are omitted without a legality claim.
        if flag or local != 0 or location not in (2,4,8,16,32,64) or not card:
            omitted += 1;continue
        # Do not read identity/description payloads for unsupported or unknown
        # locations, even when they happen to exist in our addressed message.
        code = struct.unpack('<I', read(offset+2, 4))[0]
        if card['code'] != code: return unknown
        description = struct.unpack('<I', read(offset+10, 4))[0]
        pointer = struct.unpack('<Q', read(pointers+index*8, 8))[0]
        desc, flags = struct.unpack('<II', read(descriptions+index*8, 8))
        if pointer != references.get(key) or desc != description or flags != (flag | forced<<8):
            return unknown
        selectable = read(pointer + profile['client_selectable'],1)[0]
        commands = struct.unpack('<I',read(pointer + profile['client_commands'],4))[0]
        if selectable != 1 or not commands & 1:
            return unknown  # SendResponse clears these even while the old cache remains.
        choices.append({'option':index+1,'code':code,'description':description,'controller':0,
                        'location':location,'sequence':sequence,'forced':bool(forced),
                        'source':'client_visible_selection'})
    if not choices: return {**unknown,'omitted':omitted}
    return {'status':'client_selection','choices':choices,'omitted':omitted,'rules_verified':False,
            'notice':'消息、提示区、已知实例和可选标记相符；仅表示客户端当前列出的候选，费用、对象及规则仍需核对'}
