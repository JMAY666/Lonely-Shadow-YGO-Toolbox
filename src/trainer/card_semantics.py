"""Display terminology and conservative mappings to the frozen card effect text.

Numbered card text and engine description indexes are different namespaces.
Never assume Stringid(code, 0) means effect 1, or that a monster's card type
proves how that particular instance was summoned.
"""
import hashlib
import re

CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
SUMMON_TYPES = {
    0x10000000: '通常召唤', 0x11000000: '上级召唤', 0x12000000: '二重召唤',
    0x20000000: '反转召唤', 0x40000000: '特殊召唤', 0x43000000: '融合召唤',
    0x45000000: '仪式召唤', 0x46000000: '同调召唤', 0x49000000: '超量召唤',
    0x4a000000: '灵摆召唤', 0x4c000000: '连接召唤',
}
MATERIAL_REASONS = {0x40000: '融合召唤', 0x80000: '同调召唤', 0x100000: '仪式召唤',
                    0x200000: '超量召唤', 0x10000000: '连接召唤'}

# Audited against the working-copy scripts. Frozen-text digests fail closed on
# changed wording; predicates identify an activation, never invent its outcome.
AUDITED_EFFECTS = {
    8240199: ('6b1821b44d4c4c4313752ef133f6f96ad08c65111c7874d56e4f51c08ba5d291', [
        {'number': 1, 'location': 4, 'description': 0, 'script': 'c8240199.thop'},
        {'number': 2, 'location': 2, 'description': 0, 'script': 'c8240199.gvop'},
    ]),
    41999284: ('76ddd4089e5965554a265d178ee1711b75e5844fdc02f1a562b1f32d566897c8', [
        {'number': 1, 'location': 4, 'description': 0, 'script': 'c41999284.atkop'},
        {'number': 2, 'location': 16, 'description': 0, 'script': 'c41999284.spop'},
    ]),
    71039903: ('29c2545cdad9537ecfd1b0615e2bfd5f96df864da7e2980c0381dcb7f80f91a7', [
        {'number': 2, 'description': 71039903 * 16, 'script': 'c71039903.operation'},
        {'number': 1, 'description': 71039903 * 16 + 1, 'script': 'c71039903.spop'},
    ]),
    38517737: ('43fc7deae16f5f55694952698ced64fc8a7756d32bf8af9d019b8017273d1efa', [
        {'number': 2, 'description': 38517737 * 16, 'location': 4, 'script': 'c38517737.desop'},
    ]),
    95440946: ('783c32bf37c24e31885800d9c06ef82a01b419fd4fd034b4e129be5eb276e008', [
        {'number': 1, 'description': 95440946 * 16, 'location': 2, 'script': 'c95440946.tgop'},
        {'number': 2, 'description': 95440946 * 16 + 1, 'location': 16, 'script': 'c95440946.thop'},
    ]),
    20612097: ('90d48c191cd1b6fb0f2d37031edbefd9d0fe48ecd5e1e4bfb4d2b049309e50d1', [
        {'number': 1, 'description': 20612097 * 16, 'script': 'c20612097.activate'},
        {'number': 2, 'description': 20612097 * 16 + 1, 'location': 16, 'script': 'c20612097.setop'},
    ]),
}


def clauses(text):
    # A restriction such as "这个卡名的②的效果..." is not an effect heading.
    matches = list(re.finditer(r'(?m)(?:^|(?<=[。]))[ \t]*([' + CIRCLED + r'])\s*[:：]', text))
    result = {}
    for i, match in enumerate(matches):
        number = CIRCLED.index(match[1]) + 1
        if number in result: return {}  # Ambiguous numbering (e.g. two separate text blocks).
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        result[number] = text[match.start():end].strip()
    return result


def effect_clause(event, catalog):
    card = next(iter(event.get('cards', [])), {})
    code = card.get('code')
    definition = catalog.get(str(code), {})
    text = definition.get('desc', '').replace('\r\n', '\n').strip()
    parts = clauses(text)
    answer = {'full_text': text or None, 'text': None, 'number': None, 'count': len(parts), 'source': 'unknown'}
    native = event.get('engine_effect') or {}
    # Effects copied from another owner require the source card's text, not the handler's text.
    if native.get('owner_code') not in (None, code): return answer
    if len(parts) == 1:
        number = next(iter(parts))
        return {**answer, 'number': number, 'text': parts[number], 'source': 'single_numbered_clause'}
    descriptor = (event.get('effect') or {}).get('description_id')
    audited = AUDITED_EFFECTS.get(code)
    if audited and hashlib.sha256(text.encode('utf-8')).hexdigest() == audited[0]:
        matches = [rule for rule in audited[1]
                   if rule.get('location', card.get('location')) == card.get('location')
                   and rule.get('description', descriptor) == descriptor]
        if len(matches) == 1 and matches[0]['number'] in parts:
            number = matches[0]['number']
            return {**answer, 'number': number, 'text': parts[number], 'source': 'audited_text_and_activation', 'script_reference': matches[0]['script']}
    if descriptor and descriptor >> 4 == code:
        label = (definition.get(f'str{(descriptor & 15) + 1}') or '').strip()
        if len(label) >= 4:
            matches = [n for n, part in parts.items() if label in part]
            if len(matches) == 1:
                number = matches[0]
                return {**answer, 'number': number, 'text': parts[number], 'source': 'unique_description_text'}
    if not parts and text: answer.update(text=text, source='unnumbered_full_text')
    return answer


def material_method(reason):
    if not reason or not reason & 8: return None
    matches = [name for flag, name in MATERIAL_REASONS.items() if reason & flag]
    if len(matches) == 1: return matches[0]
    if reason & 0x10: return '上级召唤'
    return None


def summon_method(info):
    return SUMMON_TYPES.get(info & 0xff000000) if type(info) is int else None


def zone_name(location, sequence=-1):
    if location & 0x80: return '叠放素材'
    if location == 4 and sequence in (5, 6): return f'额外怪兽区 {sequence - 4}'
    if location == 4: return '主怪兽区' + (f' {sequence + 1}' if sequence >= 0 else '')
    names = {1:'卡组',2:'手卡',8:'魔法陷阱区',16:'墓地',32:'除外区',64:'额外卡组'}
    return names.get(location, '未知区域') + (f' {sequence + 1}' if location == 8 and sequence >= 0 else '')
