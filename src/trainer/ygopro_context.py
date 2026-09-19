"""Bounded client context: visible phase and observed new-turn identity.

The last-message buffer is a single cache, not a reliable event stream.
Only a witnessed turn-counter transition paired with MSG_NEW_TURN is latched.
"""
import struct
import time

from ygopro_capture import CaptureError, read_order


PHASE_LABELS = {'ＤＰ': 'draw', 'ＳＰ': 'standby', 'Ｍ１': 'main1', 'ＢＰ': 'battle', 'Ｍ２': 'main2', 'ＥＰ': 'end'}


def read_phase(read, game, profile):
    pointer = struct.unpack('<Q', read(game + profile['phase_button'], 8))[0]
    if pointer < 0x10000 or pointer % 8: raise CaptureError('阶段控件尚未建立。')
    if struct.unpack('<i', read(pointer + profile['gui_id'], 4))[0] != 268:
        raise CaptureError('阶段控件身份不符，拒绝套用其他窗口。')
    visible = read(pointer + profile['gui_visible'], 1)[0]
    if visible not in (0, 1): raise CaptureError('阶段控件状态无效。')
    if not visible: return None
    text, capacity, used = struct.unpack('<QII', read(pointer + profile['gui_text'], 16))
    if not (text >= 0x10000 and text % 2 == 0 and 1 <= used <= 8 and used <= capacity <= 64):
        raise CaptureError('阶段文字边界无效，未读取其他控件内容。')
    raw = read(text, used * 2)
    if not raw.endswith(b'\0\0'): raise CaptureError('阶段文字未完整结束。')
    try: label = raw.decode('utf-16-le').rstrip('\0')
    except UnicodeError: raise CaptureError('阶段文字未稳定。') from None
    # An empty/unrecognised caption grants no phase or response permission.
    return PHASE_LABELS.get(label)


def read_turn_marker(memory, base, profile, frame):
    size = memory.read(base + profile['message_size'], 8)
    if struct.unpack('<Q', size)[0] != 2: return None
    if memory.read(base + profile['message'], 1) != b'\x28': return None
    raw = memory.read(base + profile['message'], 2)
    if (raw[0] != 40 or raw[1] not in (0, 1) or memory.read(base + profile['message'], 2) != raw
            or memory.read(base + profile['message_size'], 8) != size):
        return None
    if read_order(memory, base, profile) != {k: frame[k] for k in ('phase', 'detected_order', 'evidence')}:
        return None
    return raw[1] if frame['evidence']['is_first'] else 1 - raw[1]


class TurnObserver:
    def __init__(self):
        self.last = None
        self.player = None

    def observe(self, capture, game, frame, marker, now=None):
        now = time.monotonic() if now is None else now
        info = frame['evidence']
        if (not info.get('started') or not info.get('in_duel') or info.get('finished')
                or frame['phase'] not in ('waiting_choice', 'detected')):
            self.last = None; self.player = None; return
        key = (capture, game, info['is_first']); turn = info['turn']; old = self.last
        continuous = old and old['key'] == key and 0 <= now - old['time'] <= 2
        if not continuous or old['turn'] != turn:
            self.player = marker if continuous and turn == old['turn'] + 1 and marker in (0, 1) else None
        # A repeated or early cached MSG_NEW_TURN cannot reassign the same turn.
        self.last = {'key': key, 'turn': turn, 'time': now}

    def current(self, capture, game, first, turn, now=None):
        now = time.monotonic() if now is None else now
        last = self.last
        if (not last or last['key'] != (capture, game, first) or last['turn'] != turn
                or not 0 <= now - last['time'] <= 2):
            return None
        return self.player
