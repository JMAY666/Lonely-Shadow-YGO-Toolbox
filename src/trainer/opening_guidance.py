"""Reviewed card-text explanations, kept separate from recorded route evidence."""
from collections import Counter
import json
from pathlib import Path
import re

from opening_analysis import digest


def normalized(text):
    return re.sub(r'\s+', '', text or '')


def load_guide():
    data = json.loads((Path(__file__).parent / 'opening-kewl-tune.json').read_text('utf-8'))
    if data.get('schema') != 1 or not isinstance(data.get('cards'), list):
        raise ValueError('卡组关键资料版本无效')
    return data


def describe(deck, hand, catalog, data=None):
    data = data or load_guide()
    definitions = {row['code']: row for row in data['cards']}
    present, stale, identities = {}, [], {}
    for code in sorted(set(deck['main'] + deck['extra'])):
        current = catalog.get(code, {})
        if not current:
            stale.append({'code': code, 'name': str(code), 'reason': '卡库缺失，未核对类型与用途'}); continue
        base = code
        alias = current.get('alias')
        if base not in definitions and type(alias) is int and abs(code-alias) < 20:
            base = alias
        if base not in definitions: continue
        row = definitions[base]
        if normalized(row['text']) != normalized(current.get('desc')) or current.get('type') != row['type']:
            stale.append({'code': code, 'name': current.get('name', row['name']), 'reason': '卡文或类型与参考版本不同'}); continue
        present[code] = {**row, 'code': code, 'base_code': base, 'name': current.get('name', row['name']),
                         'basis': '官方卡文＋条件化用途说明', 'readonly': True}
        identities.setdefault(base, []).append(code)
    core = set(definitions) - {61049315, 99243014}
    active = len(core & set(identities)) >= 2
    held = Counter(hand)
    held_bases = {r['base_code'] for c, r in present.items() if held[c]}
    hand_cards = []
    for code, count in held.items():
        row = present.get(code)
        if row:
            hand_cards.append({'code': code, 'count': count, 'label': row['label'], 'roles': row['roles'],
                               'summary': row['summary'], 'details': row['details'], 'source': row['source']})
    highlights, warnings = [], []
    if active and 16387555 in held_bases:
        highlights.append({'kind': 'starter', 'text': '提示员提供通常召唤入口，可从手牌、卡组或墓地拉出其他调整；完整路线仍需核对实际条件。',
                           'codes': identities[16387555]})
        if 61049315 in held_bases:
            highlights.append({'kind': 'interaction', 'text': '自然蔷薇鞭可被提示员从手牌拉出。它可以留作魔陷卡发动限制点，也可以作素材，上手不等于废件。',
                               'codes': [*identities[16387555], *identities[61049315]]})
    if active:
        hand_material_sources = [c for c, row in present.items() if held[c] and '手卡1只调整也能作为同调素材' in normalized(row['text'])]
        tuners = [c for c in held if catalog.get(c, {}).get('type', 0) & 0x1000 and c not in present]
        if hand_material_sources and tuners:
            names = '、'.join(catalog[c].get('name', str(c)) for c in tuners)
            highlights.append({'kind': 'material', 'text': f'本家在场并满足对应同调手续时，{names}也可作手牌调整素材；用作素材会消耗原本保留的干扰或资源。',
                               'codes': [*hand_material_sources, *tuners]})
        restrictions = held_bases & {16387555, 14442329, 78058681}
        non_tuners = [c for c in deck['extra'] if c in catalog and not catalog[c].get('type', 0) & 0x1000]
        if restrictions and non_tuners:
            names = '、'.join(dict.fromkeys(catalog[c].get('name', str(c)) for c in non_tuners))
            warnings.append({'codes': [c for base in sorted(restrictions) for c in identities[base]],
                             'text': f'选择带“只特召调整”限制的本家效果时，要核对其适用时段。本构筑的非调整额外怪兽（{names}）不能在该限制适用时直接特召。'})
        if 99243014 in held_bases:
            warnings.append({'codes': identities[99243014], 'text': '同调超车需要额外中具名记载的素材，且只从卡组／墓地取得；它还限制本回合从额外仅特召同调怪兽。'})
    stages = []
    if active:
        for stage in data['stages']:
            codes = [c for base in stage['codes'] for c in identities.get(base, [])]
            if codes: stages.append({**stage, 'codes': codes})
    return {'id': data['id'], 'active': active, 'title': data['title'], 'scope': data['scope'],
            'cards': list(present.values()), 'hand_cards': hand_cards, 'highlights': highlights,
            'warnings': warnings, 'stages': stages, 'stale': stale,
            'version': digest([data, [(c, catalog.get(c, {}).get('desc'), catalog.get(c, {}).get('type')) for c in sorted(set(deck['main']+deck['extra']))]])}
