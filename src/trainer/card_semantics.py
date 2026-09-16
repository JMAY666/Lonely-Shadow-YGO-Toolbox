"""Display terminology and conservative mappings to the frozen card effect text.

Numbered card text and engine description indexes are different namespaces.
Never assume Stringid(code, 0) means effect 1, or that a monster's card type
proves how that particular instance was summoned.
"""
import hashlib
import re
from copy import deepcopy

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
    6128460: ('d2ae487bcad5f0f78e4bfadb15457af3a1717db638a6e32722d3a34a55813f25', [
        {'number':3,'description':0,'location':16,'script':'c6128460.thop'},
    ]),
    49959355: ('5b47170262c009d57a053fc97d49f9e87670252ae22daf9efdd16cea6baf9f34', [
        {'number':1,'description':49959355*16,'location':4,'script':'c49959355.lvop1'},
        {'number':2,'description':49959355*16+1,'location':4,'script':'c49959355.lvop2'},
    ]),
    57473560: ('4a854d782bde6e564a211c5a28cce49757f88c57eccf29cff93341055e506f50', [
        {'number':2,'description':57473560*16,'location':16,'script':'c57473560.tgop'},
        {'number':3,'description':57473560*16+1,'location':16,'script':'c57473560.spop'},
    ]),
    65518099: ('c06b86700b031c27f253d34934c2b25cc586de9a47cd0caa0e0197a31724f585', [
        {'number':2,'description':65518099*16,'location':8,'script':'c65518099.operation'},
    ]),
    79606837: ('08f66bb7a99a3e5f6571708b96a137358a0c2ffb617ccd8046264a9cf490141b', [
        {'number':2,'description':79606837*16,'location':4,'script':'c79606837.disop'},
        {'number':3,'description':79606837*16+1,'location':16,'script':'c79606837.thop'},
    ]),
    51124303: ('9678558b2a44d4bd947bc9e230e07a4eb97f1ca8be5060e2476ba05634bdb9bf', [
        {'number':1,'description':0,'location':8,'script':'c51124303.activate'},
        {'number':2,'description':0,'location':16,'script':'c51124303.thop'},
    ]),
    20001443: ('55a283ef674ce04076e0ddcae2c7e9ca6f97d290f27730d51b4f98b4364b4f72', [
        {'number': 1, 'description': 20001443 * 16, 'location': 4, 'script': 'c20001443.spop'},
        {'number': 2, 'description': 0, 'location': 16, 'script': 'c20001443.drop'},
    ]),
    93490856: ('cfdb1755fd1aab4350e9c03720b04df77700109ed75b23f4b76792308c5e8eb1', [
        {'number': 1, 'description': 93490856 * 16, 'location': 2, 'script': 'c93490856.spop'},
        {'number': 2, 'description': 93490856 * 16 + 1, 'location': 16, 'script': 'c93490856.damop'},
    ]),
    69248256: ('c534d80ebd8e63c15d28f0c02a110e97d80245ec89ea60549fb7e0000af3bbac', [
        {'number': 1, 'description': 69248256 * 16, 'location': 4, 'script': 'c69248256.thop'},
        {'number': 2, 'description': 69248256 * 16 + 1, 'location': 4, 'script': 'c69248256.disop'},
    ]),
    84815190: ('b229a6d40674cd5f79e2c11a1f87f108523b528632eca5d57d6c78e2291f6c14', [
        {'number': 1, 'description': 84815190 * 16, 'location': 4, 'script': 'c84815190.desop'},
        {'number': 2, 'description': 84815190 * 16 + 1, 'location': 4, 'script': 'c84815190.disop'},
        {'number': 3, 'description': 84815190 * 16 + 2, 'location': 4, 'script': 'c84815190.spop'},
    ]),
    36577931: ('130d23c808bcec7a4adf042a512f1cdea306e09bb718264bb932108db7ecb54b', [
        {'number': 1, 'description': 36577931 * 16, 'script': 'c36577931.thop'},
        {'number': 2, 'description': 36577931 * 16 + 1, 'location': 16, 'script': 'c36577931.setop'},
    ]),
    44146295: ('bec757496a9fdc5ba6e4880f4d519695e6527aeec4bcc17d388b6b971b73233d', [
        {'number': 2, 'description': 44146295 * 16, 'location': 4, 'script': 'c44146295.rmop'},
        {'number': 3, 'description': 44146295 * 16 + 1, 'script': 'c44146295.desop'},
    ]),
    62962630: ('0e90e1c8b4c6778b8c6ac041fde36619e33656d5b83ae94040652fb955647237', [
        {'number': 1, 'description': 62962630 * 16, 'location': 4, 'script': 'c62962630.thop'},
        {'number': 2, 'description': 62962630 * 16 + 1, 'location': 16, 'script': 'c62962630.spop'},
    ]),
    20618081: ('3d662e65faf2657bc64ad4b8388aa64808c1cc95dffa49b45602ad409de3a48c', [
        {'number': 1, 'description': 20618081 * 16, 'location': 16, 'script': 'c20618081.setop'},
        {'number': 2, 'description': 20618081 * 16 + 1, 'location': 16, 'script': 'c20618081.spop'},
    ]),
    94620082: ('7905baed076beed060931d91c0279c95e2284e10ec84e38ccf8646ea9d8ea0a0', [
        {'number': 1, 'description': 94620082 * 16, 'location': 4, 'script': 'c94620082.thop'},
        # Index 1 is a UI question, not a third printed effect.
        {'number': 2, 'description': 94620082 * 16 + 2, 'location': 16, 'script': 'c94620082.spop'},
    ]),
    81275020: ('01d18acef99f90dcaddf32ff9604f0981808fcb370508f96b616ae927452cbe2', [
        {'number': 2, 'description': 81275020 * 16, 'location': 4, 'script': 'c81275020.thop'},
    ]),
    53932291: ('51434c196c74b6f2065d177d5fc534f4308ccf481255842db81ba769c5851ab2', [
        {'number': 2, 'description': 53932291 * 16, 'script': 'c53932291.spop'},
    ]),
    71166481: ('8a83b8614f7830eaa50f02ffe851f004997fe36569a28833e21700da6d01e868', [
        {'number': 1, 'description': 71166481 * 16, 'location': 4, 'script': 'c71166481.chop'},
        {'number': 2, 'description': 71166481 * 16 + 1, 'location': 4, 'script': 'c71166481.xop'},
    ]),
    26889158: ('0a8336205e3f014b7f54ab718f3ee53f6719fff8c74189c3f2c7e812b6301577', [
        {'number': 1, 'description': 26889158 * 16, 'location': 2, 'script': 'c26889158.spop'},
        {'number': 2, 'description': 26889158 * 16 + 1, 'location': 4, 'script': 'c26889158.tgop'},
    ]),
    52277807: ('58280e8b955c84c1e78323a3d3679690a5e0598307863140ddfe323977f9e6a9', [
        {'number': 1, 'description': 52277807 * 16, 'location': 2, 'script': 'c52277807.atkop'},
        {'number': 2, 'description': 52277807 * 16 + 1, 'location': 16, 'script': 'c52277807.spop'},
    ]),
    14812471: ('fbc44ac288d5b1819facb518f01ff3eaf208cae0b5fb22a3f249d939b11fb7ed', [
        {'number': 1, 'description': 14812471 * 16, 'location': 4, 'script': 'c14812471.thop'},
    ]),
    87871125: ('b9169646cd3c0dfc79c85c8d1613800aceb59b46485b938185a4419c0126b81d', [
        {'number': 1, 'description': 87871125 * 16, 'location': 4, 'script': 'c87871125.thop1'},
        {'number': 2, 'description': 87871125 * 16 + 1, 'location': 4, 'script': 'c87871125.thop2'},
    ]),
    56003780: ('9a7287f6b8a480b9e970ed3993361425cb2e6a1ff987d539e0ffba6e309fab8b', [
        {'number': 2, 'description': 56003780 * 16, 'location': 16, 'script': 'c56003780.spop'},
    ]),
    87327776: ('881d63d3a1263586c4408bda1a1f3a6e4351cd380a94779758d78cdc0546755e', [
        {'number': 1, 'description': 87327776 * 16, 'location': 4, 'script': 'c87327776.spop'},
        {'number': 2, 'description': 87327776 * 16 + 1, 'location': 16, 'script': 'c87327776.thop'},
    ]),
    51339637: ('f1f777a040bcc1428119e430663abc322604f0719efac19b883dd61f260aa5c5', [
        {'number': 1, 'description': 51339637 * 16, 'location': 8, 'script': 'c51339637.activate'},
        {'number': 2, 'description': 51339637 * 16 + 1, 'location': 16, 'script': 'c51339637.setop'},
    ]),
    42741437: ('9af896d3091b95cfb9be47f9a6b4f3ca89e688f1a3e727b934272d67eaaeaff4', [
        {'number': 1, 'description': 42741437 * 16, 'location': 4, 'script': 'c42741437.rmop'},
        {'number': 3, 'description': 42741437 * 16 + 1, 'location': 4, 'script': 'c42741437.thop'},
    ]),
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
    native = event.get('engine_effect') or {}
    scoped=text
    if definition.get('type',0)&0x1000000:
        marker=re.search(r'【怪兽(?:效果|描述)】',text)
        if marker:
            pendulum=bool(native.get('range',0)&0x200) or event.get('triggering_location',card.get('location'))==8
            scoped=text[:marker.start()] if pendulum else text[marker.end():]
    parts = clauses(scoped)
    answer = {'full_text': text or None, 'text': None, 'number': None, 'count': len(parts), 'source': 'unknown'}
    if definition.get('type',0) & 0x1000000 and native.get('effect_type',0) & 0x10:
        return {**answer,'source':'pendulum_card_activation'}
    # Effects copied from another owner require the source card's text, not the handler's text.
    if native.get('owner_code') not in (None, code): return answer
    if len(parts) == 1:
        number = next(iter(parts))
        return {**answer, 'number': number, 'text': parts[number], 'source': 'single_numbered_clause'}
    descriptor = (event.get('effect') or {}).get('description_id')
    audited = AUDITED_EFFECTS.get(code)
    if audited and hashlib.sha256(text.encode('utf-8')).hexdigest() == audited[0]:
        matches = [rule for rule in audited[1]
                   if rule.get('location', event.get('triggering_location',card.get('location'))) == event.get('triggering_location',card.get('location'))
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


def display_effects(report):
    """Refresh labels on a view copy; frozen plans, IDs and annotations stay put."""
    result=deepcopy(report)
    from review import legacy_review
    result['review'] = legacy_review(result)
    events={event.get('id'):event for event in result.get('events',[])}
    for action in result.get('actions',[]):
        if action.get('kind')!='effect':continue
        event=events.get(action.get('activation_ref') or action.get('id'))
        if not event:continue
        clause=effect_clause(event,result.get('catalog',{}))
        action.update(effect_text=clause['full_text'],effect_number=clause['number'],effect_count=clause['count'],
                      selected_effect_text=clause['text'],effect_text_source=clause['source'])
    for branch in result.get('branches',[]):
        if branch.get('report'):branch['report']=display_effects(branch['report'])
    return result


def material_method(reason):
    if not reason or not reason & 8: return None
    matches = [name for flag, name in MATERIAL_REASONS.items() if reason & flag]
    if len(matches) == 1: return matches[0]
    if reason & 0x10: return '上级召唤'
    return None


def card_activation(action, catalog):
    card = next(iter(action.get('cards', [])), {})
    native = action.get('engine_effect') or {}
    kind = catalog.get(str(card.get('code')), {}).get('type', 0)
    if not native.get('effect_type', 0) & 0x10: return None
    if kind & 0x1000000:return '发动灵摆卡'
    if kind & 2:
        for flag, name in ((0x80000, '场地'), (0x20000, '永续'), (0x40000, '装备'), (0x10000, '速攻'), (0x80, '仪式')):
            if kind & flag: return f'发动{name}魔法卡'
        return '发动魔法卡'
    if kind & 4: return '发动' + ('永续' if kind & 0x20000 else '反击' if kind & 0x100000 else '') + '陷阱卡'
    return None


def summon_method(info):
    return SUMMON_TYPES.get(info & 0xff000000) if type(info) is int else None


def zone_name(location, sequence=-1):
    if location & 0x80: return '叠放素材'
    if location == 4 and sequence in (5, 6): return f'额外怪兽区 {sequence - 4}'
    if location == 4: return '主怪兽区' + (f' {sequence + 1}' if sequence >= 0 else '')
    names = {1:'卡组',2:'手卡',8:'魔法陷阱区',16:'墓地',32:'除外区',64:'额外卡组'}
    return names.get(location, '未知区域') + (f' {sequence + 1}' if location == 8 and sequence >= 0 else '')
