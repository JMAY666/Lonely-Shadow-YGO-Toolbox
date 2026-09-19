"""Local series vocabulary, aliases and explainable route-based classification."""
from copy import deepcopy
from collections import Counter
from pathlib import Path
import json
import re
import unicodedata
import uuid

MIN_CARDS, MIN_RATIO = 2, 0.20


def normalized(value):
    return unicodedata.normalize('NFKC', value).strip().casefold()


def builtin_tags(runtime):
    from superpre import resource_files
    result = {}
    for path in (runtime / 'strings.conf', runtime / 'expansions/strings.conf', *resource_files(runtime, '.conf')):
        if not path.exists(): continue
        for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
            match = re.match(r'^!setname\s+(0x[\da-fA-F]+)\s+(.+)', line)
            if not match: continue
            code = int(match[1], 16)
            names = [part.strip() for part in match[2].split('\t') if part.strip()]
            identifier = f'set:{code:x}'
            result[identifier] = {'id': identifier, 'name': names[0], 'aliases': names[1:],
                                  'setcode': code, 'source': '卡库系列表'}
    # Verified official Chinese naming takes priority; preserve database names as aliases.
    source = json.loads((Path(__file__).parent / 'series-official.json').read_text(encoding='utf-8'))
    for tag in source:
        old = result.get(tag['id'], {})
        result[tag['id']] = {**tag, 'aliases': list(dict.fromkeys([*tag['aliases'], *old.get('aliases', []),
                                                                 *([old['name']] if old.get('name') != tag['name'] and old.get('name') else [])]))}
    return result


def vocabulary(builtins, document):
    return {**deepcopy(builtins), **deepcopy(document.get('entries', {}))}


def edit_tag(body, tags):
    identifier = body.get('id') or 'custom:' + uuid.uuid4().hex
    if not re.fullmatch(r'(?:set:[0-9a-f]{1,4}|custom:[0-9a-f]{32})', identifier): raise ValueError('标签编号无效')
    previous = tags.get(identifier)
    if previous is None and body.get('id'): raise ValueError('标签不存在，请刷新标签库')
    name, aliases = body.get('name'), body.get('aliases', [])
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60: raise ValueError('标签正名请输入 1–60 个字符')
    if not isinstance(aliases, list) or len(aliases) > 30 or any(not isinstance(a, str) or not a.strip() or len(a.strip()) > 60 for a in aliases):
        raise ValueError('别名最多 30 个，每个请输入 1–60 个字符')
    name = name.strip()
    if previous and previous['name'] != name: aliases = [*aliases, previous['name']]
    names = {normalized(name)}
    unique = []
    for alias in aliases:
        if normalized(alias) not in names:
            names.add(normalized(alias)); unique.append(alias.strip())
    if len(unique) > 30: raise ValueError('改名会保留旧名作为别名，请先移除一个别名再保存')
    for key, tag in tags.items():
        if key != identifier and names & {normalized(s) for s in [tag['name'], *tag.get('aliases', [])]}:
            raise ValueError(f'名称或别名已属于“{tag["name"]}”，请使用已有标签或换一个叫法')
    return {**(previous or {'setcode': None, 'source': '用户自定义'}), 'id': identifier, 'name': name, 'aliases': unique}


def matches_set(packed, series):
    # YGO packs four 16-bit setcodes in a signed SQLite int64. A subtype contains
    # its base series, but sibling subtype bits are never treated as a match.
    packed = int(packed or 0) & ((1 << 64) - 1)
    return any((part & 0xfff) == (series & 0xfff) and (part & series & 0xf000) == (series & 0xf000)
               for part in ((packed >> shift) & 0xffff for shift in (0, 16, 32, 48)) if part)


def contains_card(tag, code, card):
    if code in tag.get('exclude_cards', []): return False
    return code in tag.get('include_cards', []) or bool(tag.get('setcode') and matches_set(card.get('setcode'), tag['setcode']))


def membership_basis(tag, code, card):
    if code in tag.get('exclude_cards', []): return '手动排除'
    if code in tag.get('include_cards', []): return '手动加入'
    if tag.get('setcode') and matches_set(card.get('setcode'), tag['setcode']): return '卡库系列'
    return ''


def member_ids(tag, catalog):
    baseline = {code for code, card in catalog.items() if tag.get('setcode') and matches_set(card.get('setcode'), tag['setcode'])}
    return sorted((baseline | set(tag.get('include_cards', []))) - set(tag.get('exclude_cards', [])))


def edit_members(tag, selected, catalog):
    if not isinstance(selected, list) or len(selected) > 20000 or any(type(code) is not int or not 0 < code < 2**32 for code in selected):
        raise ValueError('标签卡牌列表无效，最多 20000 张不同卡牌')
    retained = set(tag.get('include_cards', []))
    if any(code not in catalog and code not in retained for code in selected): raise ValueError('新添加的卡牌不在当前卡库中')
    baseline = {code for code, card in catalog.items() if tag.get('setcode') and matches_set(card.get('setcode'), tag['setcode'])}
    missing_exclusions = set(tag.get('exclude_cards', [])) - set(catalog)
    return {**tag, 'include_cards': sorted(set(selected) - baseline),
            'exclude_cards': sorted((baseline - set(selected)) | missing_exclusions)}


def used_codes(plan):
    codes = set()
    def add(cards):
        for c in cards or []:
            if c.get('controller') == 0 and type(c.get('code')) is int and c['code'] > 0:
                codes.add(c['code'])
            add(c.get('materials', []))
    events = {e['id']: e for e in plan.get('events', [])}
    for action in plan.get('actions', []):
        # Revealed/drawn cards count only if subsequently used in an action.
        if events.get(action['id'], {}).get('message') not in (30, 31, 90): add(action.get('cards'))
        for ref in action.get('evidence_refs', []):
            event = events.get(ref, {})
            if event.get('message') in (50, 53, 54, 60, 61, 62, 63, 64, 65, 70):
                if event.get('deck_operation') or event.get('reason', 0) and event.get('reason', 0) & 0x400: continue
                add(event.get('cards'))
    return codes


def suggest(plan, tags, catalog):
    codes = used_codes(plan)
    basis = '实际参与路线的我方卡牌种类（同名去重）'
    counts, evidence = Counter(), {}
    for code in sorted(codes):
        # Frozen setcode is authoritative when available; older snapshots can
        # use the installed database, never effect text substring matching.
        card = plan.get('catalog', {}).get(str(code), {})
        if 'setcode' not in card: card = catalog.get(code, card)
        for identifier, tag in tags.items():
            if contains_card(tag, code, card):
                counts[identifier] += 1
                evidence.setdefault(identifier, []).append({'code': code, 'name': card.get('name', str(code)),
                                                            'basis': membership_basis(tag, code, card)})
    ranked = sorted(counts, key=lambda key: (-counts[key], -((tags[key].get('setcode') or 0) >> 12).bit_count(), tags[key]['name'], key))
    candidates = [{'id': key, 'count': counts[key], 'total': len(codes), 'ratio': counts[key] / len(codes),
                   'cards': evidence[key], 'eligible': counts[key] >= MIN_CARDS and counts[key] / len(codes) >= MIN_RATIO}
                  for key in ranked]
    selected = [item['id'] for item in candidates if item['eligible']][:30]
    return {'version': 1, 'tag_ids': selected, 'primary_ids': selected[:1], 'mode': 'automatic',
            'basis': basis, 'minimum_cards': MIN_CARDS, 'minimum_ratio': MIN_RATIO, 'total': len(codes), 'candidates': candidates}


def validate_selection(value, tags):
    if not isinstance(value, dict): raise ValueError('标签分类无效')
    result = {'version': 1, 'mode': 'manual'}
    for field in ('tag_ids', 'primary_ids'):
        ids = value.get(field, [])
        if not isinstance(ids, list) or len(ids) > 30 or any(not isinstance(key, str) or key not in tags for key in ids):
            raise ValueError('标签不存在或超过 30 个，请刷新标签库')
        result[field] = list(dict.fromkeys(ids))
    if not set(result['primary_ids']) <= set(result['tag_ids']): raise ValueError('主标签必须属于已选择的标签')
    return result


def classification(plan, tags, catalog):
    saved = plan.get('classification')
    return deepcopy(saved) if saved is not None and saved.get('mode') != 'automatic' else suggest(plan, tags, catalog)


def tag_list(selection, tags):
    return [{**tags[key], 'primary': key in selection.get('primary_ids', [])}
            for key in selection.get('tag_ids', []) if key in tags]
