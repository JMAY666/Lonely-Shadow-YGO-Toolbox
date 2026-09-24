"""Read-only series folders for annotations; never expand membership via support cards.

The installed CDB setcode is the membership authority. Curated samples only
provide checked Chinese names, presentation and evidence, not member overrides.
Personal TAG inclusions/exclusions and effect annotation review stay separate.
"""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from plan_tags import matches_set, normalized
from card_release_dates import ReleaseDates

UNASSIGNED = 'unassigned'
EMBLEMS = {'dragon-eye', 'flame', 'swords', 'halo', 'wave'}
TONES = {'ice', 'flame', 'jade', 'violet', 'pink'}


def load_presentation(path=None):
    path = Path(path) if path else Path(__file__).with_name('annotation-series.json')
    document = json.loads(path.read_text(encoding='utf-8'))
    if document.get('version') != 1 or not isinstance(document.get('series'), list):
        raise ValueError('系列展示资料版本或格式无效')
    seen = set()
    for item in document['series']:
        identifier = item.get('id', '')
        if not re.fullmatch(r'set:[0-9a-f]{1,4}', identifier) or identifier in seen:
            raise ValueError('系列展示编号无效或重复')
        seen.add(identifier)
        if int(identifier[4:], 16) != item.get('setcode') or not item.get('name'):
            raise ValueError(f'{identifier}: 系列编号或中文名称无效')
        if item.get('emblem') not in EMBLEMS or item.get('tone') not in TONES:
            raise ValueError(f'{identifier}: 未登记的系列徽记或颜色')
        if not isinstance(item.get('aliases'), list) or any(not isinstance(v, str) for v in item['aliases']):
            raise ValueError(f'{identifier}: 系列别名无效')
        refs = set()
        for source in item.get('sources', []):
            url = urlparse(source.get('url', ''))
            if (url.scheme != 'https' or url.hostname != 'www.db.yugioh-card.com'
                    or url.username or url.password or not source.get('id') or source['id'] in refs
                    or not source.get('title') or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', source.get('checked_on', ''))):
                raise ValueError(f'{identifier}: 系列来源无效')
            refs.add(source['id'])
        samples = item.get('samples', [])
        codes = set()
        for sample in samples:
            code = sample.get('code')
            if (type(code) is not int or not 0 < code < 2**32 or code in codes
                    or type(sample.get('type')) is not int or type(sample.get('setcode')) is not int
                    or not matches_set(sample['setcode'], item['setcode'])
                    or not sample.get('source_refs') or not set(sample['source_refs']) <= refs):
                raise ValueError(f'{identifier}: 系列代表样本无效')
            codes.add(code)
        if not samples or item.get('cover_code') not in codes:
            raise ValueError(f'{identifier}: 封面必须是有来源的代表样本')
    return document


class CardSeries:
    def __init__(self, catalog, builtins, presentation=None, releases=None):
        self.cards = catalog.cards
        document = presentation if presentation is not None else load_presentation()
        self.curated = {item['id']: deepcopy(item) for item in document['series']}
        self.definitions = {key: {**deepcopy(tag), 'emblem': 'folder', 'tone': 'neutral',
                                  'name_basis': '本地卡库译名 · 未逐系列联网核对'}
                            for key, tag in builtins.items() if tag.get('setcode')}
        for key, item in self.curated.items():
            old = self.definitions.get(key, {})
            self.definitions[key] = {**item, 'aliases': list(dict.fromkeys([
                *item['aliases'], *old.get('aliases', []), *([old['name']] if old.get('name') != item['name'] and old.get('name') else [])])),
                'name_basis': '官方简体中文系列名 · 已联网核对'}
        self.definitions[UNASSIGNED] = {
            'id': UNASSIGNED, 'name': '无系列归属', 'aliases': [], 'setcode': 0,
            'emblem': 'folder', 'tone': 'neutral', 'name_basis': '当前卡库未登记系列；不等于没有配合对象'}
        by_base = defaultdict(list)
        for key, definition in self.definitions.items():
            if definition['setcode']: by_base[definition['setcode'] & 0xfff].append(key)
        self.memberships = {}
        self.members = defaultdict(set)
        packed_cards = {}
        for code, card in self.cards.items():
            if card.get('type', 0) & 0x4000: continue
            packed = int(card.get('setcode') or 0) & ((1 << 64) - 1)
            packed_cards[code] = packed
            for shift in (0, 16, 32, 48):
                part = (packed >> shift) & 0xffff
                if not part: continue
                # An unregistered subtype retains its own folder as well as
                # any known parent; it is never silently called "no series".
                identifier = f'set:{part:x}'
                if identifier not in self.definitions:
                    self.definitions[identifier] = {
                        'id': identifier, 'setcode': part, 'name': f'未命名系列 · 0x{part:X}',
                        'aliases': [], 'emblem': 'folder', 'tone': 'neutral',
                        'name_basis': '卡库有系列编号，中文译名待补充'}
                    by_base[part & 0xfff].append(identifier)
        # Complete the vocabulary before matching, including unknown parents
        # that occur after their subtypes in the catalog's insertion order.
        for code, packed in packed_cards.items():
            keys = set()
            for shift in (0, 16, 32, 48):
                part = (packed >> shift) & 0xffff
                if not part: continue
                keys.update(key for key in by_base[part & 0xfff]
                            if matches_set(part, self.definitions[key]['setcode']))
            if not keys: keys.add(UNASSIGNED)
            self.memberships[code] = sorted(keys)
            for key in keys: self.members[key].add(code)
        dates = releases if releases is not None else ReleaseDates()
        # Series debut is based on its entire membership, independent of the
        # currently visible query results, selected cover or annotation count.
        self.releases = {key: dates.first(codes) for key, codes in self.members.items() if key != UNASSIGNED}

    def metadata(self, identifier):
        item = self.definitions[identifier]
        return {key: deepcopy(item.get(key)) for key in
                ('id', 'name', 'aliases', 'setcode', 'emblem', 'tone', 'name_basis')}

    def card_series(self, code):
        result = []
        card = self.cards[code]
        for identifier in self.memberships.get(code, []):
            meta = self.metadata(identifier)
            item = self.curated.get(identifier, {})
            sample = next((sample for sample in item.get('samples', []) if sample['code'] == code), None)
            meta['sample_review'] = ('checked' if sample['setcode'] == card.get('setcode') and sample['type'] == card.get('type')
                                     else 'changed') if sample else 'database'
            meta['sources'] = deepcopy(item.get('sources', []))
            result.append(meta)
        return result

    def matches_query(self, code, query):
        return any(query in normalized(name) for key in self.memberships.get(code, [])
                   for name in [self.definitions[key]['name'], *self.definitions[key].get('aliases', [])])

    def folders(self, cards):
        grouped = defaultdict(list)
        for card in cards:
            for identifier in self.memberships[card['code']]: grouped[identifier].append(card)
        folders = []
        for identifier, entries in grouped.items():
            meta = self.metadata(identifier)
            codes = {entry['code'] for entry in entries}
            cover = self.curated.get(identifier, {}).get('cover_code')
            if cover not in codes:
                cover = next((entry['code'] for entry in entries if entry['status'] != 'none'), entries[0]['code'])
            meta.update(count=len(entries), annotated=sum(entry['status'] != 'none' for entry in entries),
                        cover_code=cover, designed=identifier in self.curated,
                        release=deepcopy(self.releases.get(identifier, {})))
            folders.append(meta)
        return folders
