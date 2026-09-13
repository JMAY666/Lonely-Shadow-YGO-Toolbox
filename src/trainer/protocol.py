"""Framing for pinned ygopro-core 8ff3583, verified against SinglePlayAnalyze.

Raw bytes are retained. Unknown or truncated messages stop this batch's decoder;
we never guess a length and reinterpret subsequent bytes as reliable events.
"""
import struct

NAMES = {
    1: '响应被引擎拒绝', 2: '引擎提示', 5: '引擎结束', 10: '选择战斗操作',
    11: '选择主要阶段操作', 12: '选择是否发动', 13: '是非选择', 14: '选择选项',
    15: '选择卡牌', 16: '选择连锁', 18: '选择区域', 19: '选择表示形式',
    20: '选择祭品', 22: '选择指示物', 23: '选择数值合计', 24: '选择不可用区域',
    25: '排列卡牌', 26: '选择或取消卡牌', 30: '确认卡组顶', 31: '确认卡牌',
    32: '洗切卡组', 33: '洗切手牌', 34: '刷新卡组', 35: '交换墓地与卡组',
    36: '洗切盖放卡', 37: '反转卡组', 38: '卡组顶信息', 39: '洗切额外卡组',
    40: '回合开始', 41: '阶段开始', 42: '确认额外卡组顶', 50: '区域移动',
    53: '表示形式变化', 54: '盖放', 55: '交换位置', 56: '区域禁用',
    60: '通常召唤开始', 61: '通常召唤成功', 62: '特殊召唤开始', 63: '特殊召唤成功',
    64: '反转召唤开始', 65: '反转召唤成功', 70: '效果发动', 71: '加入连锁',
    72: '连锁开始结算', 73: '连锁结算完成', 74: '连锁结束', 75: '发动被无效',
    76: '效果被无效', 80: '卡牌选择结果', 81: '随机选择结果', 83: '成为效果对象',
    90: '抽卡', 91: '受到伤害', 92: '回复生命值', 93: '装备', 94: '生命值更新',
    95: '解除装备', 96: '建立卡牌关系', 97: '解除卡牌关系', 100: '支付生命值费用',
    101: '增加指示物', 102: '移除指示物', 110: '攻击宣言', 111: '战斗结果',
    112: '攻击无效', 113: '伤害步骤开始', 114: '伤害步骤结束', 120: '错过发动时点',
    130: '投硬币', 131: '掷骰子', 132: '猜拳选择', 133: '猜拳结果',
    140: '宣言种族', 141: '宣言属性', 142: '宣言卡牌', 143: '宣言数字',
    160: '卡牌提示', 161: '组队交换', 162: '载入场面', 163: '占位名称',
    164: '显示提示', 165: '玩家提示', 170: '比赛结束标志'
}
FIXED = {1:0, 2:6, 5:2, 12:13, 13:5, 18:6, 19:6, 24:6, 32:1, 34:1,
         35:1, 37:0, 38:6, 40:1, 41:2, 50:16, 53:9, 54:8, 55:16, 56:4,
         60:8, 61:0, 62:8, 63:0, 64:8, 65:0, 70:16, 71:1, 72:1, 73:1,
         74:0, 75:1, 76:1, 91:5, 92:5, 93:8, 94:5, 95:4, 96:8, 97:8,
         100:5, 101:7, 102:7, 110:8, 111:26, 112:0, 113:0, 114:0, 120:8,
         132:1, 133:1, 140:6, 141:6, 160:9, 165:6, 170:4}
PROMPTS = set(range(10, 27)) | {132, 140, 141, 142, 143}


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('事件数据不完整')
        value = self.data[self.pos:self.pos + n]
        self.pos += n
        return value

    def byte(self):
        return self.take(1)[0]

    def group(self, width):
        self.take(self.byte() * width)


def packets(data):
    r = Reader(data)
    while r.pos < len(data):
        start, msg = r.pos, r.byte()
        if msg in FIXED:
            r.take(FIXED[msg])
        elif msg == 10:
            r.take(1); r.group(11); r.group(8); r.take(2)
        elif msg == 11:
            r.take(1)
            for _ in range(5): r.group(7)
            r.group(11); r.take(3)
        elif msg in (14, 33, 39, 80, 81, 90, 142, 143):
            r.take(1); r.group(4)
        elif msg in (15, 20):
            r.take(4); r.group(8)
        elif msg == 16:
            r.take(1); count = r.byte(); r.take(9 + count * 14)
        elif msg == 22:
            r.take(5); r.group(9)
        elif msg == 23:
            r.take(8); r.group(11); r.group(11)
        elif msg in (25, 30, 42):
            r.take(1); r.group(7)
        elif msg == 26:
            r.take(5); r.group(8); r.group(8)
        elif msg == 31:
            r.take(2); r.group(7)
        elif msg == 36:
            r.take(1); r.group(8)
        elif msg == 83:
            r.group(4)
        elif msg in (130, 131):
            r.take(1); r.group(1)
        elif msg == 161:
            header = r.take(9); r.take((header[2] + header[4]) * 4)
        elif msg == 162:
            r.take(1)
            for _ in range(2):
                r.take(4)
                for _ in range(7):
                    if r.byte(): r.take(2)
                for _ in range(8):
                    if r.byte(): r.take(1)
                r.take(6)
            r.group(15)
        elif msg in (163, 164):
            length = struct.unpack('<H', r.take(2))[0]; r.take(length + 1)
        else:
            raise ValueError(f'未知协议事件 {msg}，本批剩余字节保留为原始数据')
        yield start, msg, data[start + 1:r.pos]


def u32(data, offset=0):
    return struct.unpack_from('<I', data, offset)[0]


def location(data, offset=0):
    return dict(zip(('controller', 'location', 'sequence', 'position'), data[offset:offset + 4]))
