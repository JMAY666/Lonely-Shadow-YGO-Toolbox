"""Read-only, one-hop card relationships. References are clues, not legal targets.

Built independently from the local CDB, series table and literal Lua references.
No Lua is executed, no name prefixes are guessed and no relation changes a TAG.
"""
from collections import defaultdict
import re

from plan_tags import matches_set, normalized

TOKEN = 0x4000
QUOTES = re.compile(r'「([^「」\n]+)」|『([^『』\n]+)』|“([^“”\n]+)”|"([^"\n]+)"')
# Remove comments and string literals before looking at code. Long Lua strings
# and comments can use any number of equals signs, including zero.
LUA_NON_CODE = re.compile(
    r'--\[(=*)\[.*?\]\1\]|--[^\r\n]*|\[(=*)\[.*?\]\2\]|'
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
NUMBERS = re.compile(r'\s*(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\s*,\s*(?:0[xX][0-9a-fA-F]+|[0-9]+))*\s*')


def literals(value):
    if not NUMBERS.fullmatch(value): return ()
    return tuple(int(part.strip(), 16 if part.strip().lower().startswith('0x') else 10)
                 for part in value.split(','))


def script_references(text):
    """Intentionally limited to explicit numeric names/sets; ignore expressions."""
    text = LUA_NON_CODE.sub(' ', text)
    names, series = set(), set()
    for field, value in re.findall(r'\b\w+\.(listed_names|listed_series)\s*=\s*\{([^{}]*)\}', text):
        (names if field == 'listed_names' else series).update(literals(value))
    for method, value in re.findall(r':(IsCode|IsOriginalCode|IsFusionCode|IsSetCard|IsFusionSetCard|IsLinkSetCard)\s*\(([^()]*)\)', text):
        (series if 'SetCard' in method else names).update(literals(value))
    for value in re.findall(r'\b(?:aux|Auxiliary)\.(?:AddCodeList|IsCodeListed|IsMaterialListCode)\s*\(\s*\w+\s*,([^()]*)\)', text):
        names.update(literals(value))
    return {n for n in names if 0 < n < 2**32}, {s for s in series if 0 < s <= 0xffff}


class CardRelations:
    def __init__(self, catalog, builtins, script_dirs=(), script_code=None):
        self.catalog = catalog
        self.cards = {code: card for code, card in catalog.items() if not card.get('type', 0) & TOKEN}
        self.series = {t['setcode']: t for t in builtins.values() if t.get('setcode')}
        self.members = defaultdict(set)
        self.card_series = defaultdict(set)
        self.references = defaultdict(dict)
        self.reverse = defaultdict(dict)
        self.series_references = defaultdict(dict)
        self.script_errors = 0
        names, series_names = defaultdict(set), defaultdict(set)
        for code, card in self.cards.items():
            names[normalized(card.get('name', ''))].add(code)
            packed = int(card.get('setcode') or 0) & ((1 << 64) - 1)
            for shift in (0, 16, 32, 48):
                part = (packed >> shift) & 0xffff
                if not part: continue
                # A subtype belongs to every supported ancestor, not its siblings.
                base = part & 0xfff
                possible = [s for s in self.series if s & 0xfff == base]
                for series in possible:
                    if matches_set(part, series):
                        self.members[series].add(code)
                        self.card_series[code].add(series)
        for series, tag in self.series.items():
            for name in [tag['name'], *tag.get('aliases', [])]:
                if normalized(name): series_names[normalized(name)].add(series)
        scripts = {}
        for directory in script_dirs:
            if not directory.is_dir(): continue
            for path in directory.glob('c*.lua'):
                if re.fullmatch(r'c[0-9]+\.lua', path.name): scripts[int(path.stem[1:])] = path
        parsed = {}
        for code, card in self.cards.items():
            for match in QUOTES.finditer(card.get('desc') or ''):
                name = normalized(next(part for part in match.groups() if part is not None))
                # Ambiguous short series aliases do not silently pick a series.
                if len(series_names.get(name, ())) == 1:
                    self.series_references[next(iter(series_names[name]))][code] = 'text_series'
                for target in names.get(name, ()):
                    if target != code: self.references[code][target] = 'text_card'
            script_id = script_code(card) if script_code else code
            if script_id not in parsed:
                path = scripts.get(script_id)
                try:
                    parsed[script_id] = script_references(path.read_text(encoding='utf-8-sig', errors='replace')) if path and path.stat().st_size <= 2_000_000 else (set(), set())
                except OSError:
                    self.script_errors += 1
                    parsed[script_id] = (set(), set())
            card_ids, set_ids = parsed[script_id]
            for target in card_ids:
                if target in self.cards and target != code: self.references[code].setdefault(target, 'script_card')
            for series in set_ids:
                if series in self.series: self.series_references[series].setdefault(code, 'script_series')
            alias = int(card.get('alias') or 0)
            if alias in self.cards and alias != code: self.references[code].setdefault(alias, 'alias')
        for source, targets in self.references.items():
            for target, kind in targets.items(): self.reverse[target][source] = kind

    def related(self, seeds, series=None):
        """No transitive closure: only the selected cards and a tag's own series."""
        result = defaultdict(dict)
        visited_series = set()
        def add(code, kind, detail, source=None):
            if code not in self.cards: return
            key = (kind, detail)
            result[code][key] = {'kind': kind, 'detail': detail, **({'source_card_id': source} if source else {})}

        def add_series(value, seed=None):
            if value in visited_series: return
            visited_series.add(value)
            tag = self.series.get(value)
            if not tag: return
            name = tag['name']
            # Large parent fields should not swamp a more specific shared field.
            for code in self.members[value]:
                add(code, 'series', f'卡库系列：{name}', seed)
            for code, kind in self.series_references[value].items():
                add(code, kind, f'{"效果提及" if kind == "text_series" else "脚本引用"}系列「{name}」', seed)

        if series: add_series(series)
        for seed in sorted(set(seeds)):
            if seed not in self.cards: continue
            name = self.cards[seed]['name']
            # For a series TAG, shared membership of its cards in *other* series
            # is not itself a reason to merge the entire other archetype.
            if not series:
                for value in sorted(self.card_series[seed]): add_series(value, seed)
            for target, kind in self.references[seed].items():
                label = '效果点名' if kind == 'text_card' else '同名卡关系' if kind == 'alias' else '脚本引用'
                add(target, kind, f'「{name}」{label}此卡', seed)
            for source, kind in self.reverse[seed].items():
                label = '效果点名' if kind == 'text_card' else '同名卡关系' if kind == 'alias' else '脚本引用'
                add(source, kind, f'此卡{label}「{name}」', seed)
            if not series:
                for value, sources in self.series_references.items():
                    if seed in sources:
                        kind = sources[seed]
                        for target in self.members[value]:
                            add(target, kind, f'「{name}」引用系列「{self.series[value]["name"]}」', seed)
        return result

    def search(self, seeds, *, series=None, excluded=(), query='', kind='', offset=0):
        hidden = set(seeds) | set(excluded)
        query = normalized(query)
        priority = {'text_series': 0, 'text_card': 1, 'alias': 2, 'script_series': 3, 'script_card': 4, 'series': 5}
        matches = []
        for code, reasons in self.related(seeds, series).items():
            if code in hidden: continue
            card = self.cards[code]
            reasons = sorted(reasons.values(), key=lambda r: (priority[r['kind']], r['detail']))
            if kind: reasons = [r for r in reasons if r['kind'] == kind]
            if not reasons: continue
            if query and query not in normalized(card['name']) and query != str(code): continue
            matches.append((code, reasons))
        matches.sort(key=lambda item: (priority[item[1][0]['kind']], self.cards[item[0]]['name'], item[0]))
        return {'total': len(matches), 'offset': offset,
                'cards': [{**self.cards[code], 'relation_reasons': reasons[:4], 'relation_count': len(reasons)}
                          for code, reasons in matches[offset:offset + 60]],
                'script_errors': self.script_errors}
