"""Reviewed public card notes, imported explicitly into personal knowledge."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from intelligence_marks import effect_parts, merge_marks, notes_value
from plan_tags import normalized


def load_catalog():
    root = Path(__file__).parent
    catalog = json.loads((root / 'staples.json').read_text('utf-8'))
    texts = json.loads((root / 'staples-texts.json').read_text('utf-8'))
    if catalog.get('version') != 1: raise ValueError('常用卡资料版本不受支持')
    for card in catalog['cards']:
        card.update(texts[str(card['code'])])
    return catalog


def stable_id(value):
    return uuid.uuid5(uuid.NAMESPACE_URL, 'ygo-toolbox/staples/' + value).hex


def import_staples(service, document, knowledge, catalog=None):
    catalog = load_catalog() if catalog is None else catalog
    before = deepcopy((document['entries'], knowledge))
    result = {'added': 0, 'updated': 0, 'unchanged': 0, 'missing': [], 'pending': 0}
    tags = {}
    for card in catalog['cards']:
        code = card['code']
        if code not in service.store.catalog.cards:
            result['missing'].append({'code': code, 'name': card['name']})
            continue
        for kind, group_id in card['groups'].items():
            previous = knowledge[kind].get(str(code))
            service.check_library_card(kind, code)
            reference = catalog['id'] + ':' + str(code)
            if any(source['id'] == reference for source in (previous or {}).get('catalog_sources', [])):
                result['unchanged'] += 1
                continue
            group = catalog['groups'][group_id]
            names = {normalized(name) for name in [group['name'], *group.get('aliases', [])]}
            identifier = stable_id(kind + '/' + group_id)
            folder = knowledge['folders'].get(identifier)
            if folder is not None and folder.get('kind', 'handtraps') != kind:
                raise ValueError('常用分类编号冲突，请核对已有文件夹')
            if folder is None:
                folder = next((f for f in knowledge['folders'].values()
                               if f.get('kind', 'handtraps') == kind and normalized(f['name']) in names), None)
            if folder is None:
                folder = {'id': identifier, 'name': group['name'], 'kind': kind}
                knowledge['folders'][identifier] = folder
            parts = effect_parts(card['desc'])
            effects = {}
            for label, notes in card['effects'].items():
                matches = [str(i) for i, part in enumerate(parts)
                           if (not part.lstrip().startswith(tuple('①②③④⑤⑥⑦⑧⑨⑩')) if label == 'text'
                               else part.lstrip().startswith((label + '：', label + ':')))]
                if len(matches) != 1: raise ValueError(f'常用资料效果文本无法唯一对应：{code} / {label}')
                effects[matches[0]] = notes_value([{'text': note, 'source_refs': [reference]} for note in notes])
            incoming = service.annotation({'code': code, 'desc': card['desc'], 'effects': effects}, trusted=True)
            incoming['candidate'] = False
            existing = None if previous is None else {
                'code': code, 'candidate': False, 'desc': previous['desc'], 'effects': deepcopy(previous['effects']),
                'note': '', 'sources': [], 'unmatched_effects': deepcopy(previous.get('unmatched_effects', []))}
            merged = merge_marks(existing, incoming, target_desc=service.card(code)['desc'])
            source = {'id': reference, 'title': catalog['title'], 'checked_on': catalog['checked_on'],
                      'official_url': f'https://www.db.yugioh-card.com/yugiohdb/card_search.action?ope=2&cid={card["konami_id"]}&request_locale=ja',
                      'card_url': card['card_url'], 'note': card['note'], 'condition': card['condition']}
            record = {**(previous or {}), 'code': code,
                      'folder_id': (previous or {}).get('folder_id') or folder['id'],
                      'note': (previous or {}).get('note') or card['note'],
                      'condition': (previous or {}).get('condition') or card['condition'],
                      **{key: merged[key] for key in ('desc', 'effects', 'unmatched_effects')},
                      'catalog_sources': [*(previous or {}).get('catalog_sources', []), source]}
            knowledge[kind][str(code)] = record
            result['added' if previous is None else 'updated'] += 1
            result['pending'] += len(merged['unmatched_effects'])
            for name in card['tags']:
                tags.setdefault(name, set()).add(code)
    for name, codes in tags.items():
        title = '效果 · ' + name
        identifier = 'custom:' + stable_id('effect/' + name)
        existing = document['entries'].get(identifier)
        if existing and (existing.get('purpose') != 'effect' or existing['name'] != title):
            raise ValueError('常用效果 TAG 编号冲突，请核对已有 TAG')
        vocabulary = service.library.all_tags()
        if any(key != identifier and normalized(title) in {normalized(n) for n in [tag['name'], *tag.get('aliases', [])]}
               for key, tag in vocabulary.items()): raise ValueError(f'已有同名 TAG：{title}，请先核对')
        document['entries'][identifier] = {
            'id': identifier, 'name': title, 'aliases': [], 'setcode': None, 'source': catalog['title'],
            'kind': 'purpose', 'purpose': 'effect', 'exclude_cards': [], **(existing or {}),
            'include_cards': sorted(set((existing or {}).get('include_cards', [])) | codes)}
    result['changed'] = before != (document['entries'], knowledge)
    return result
