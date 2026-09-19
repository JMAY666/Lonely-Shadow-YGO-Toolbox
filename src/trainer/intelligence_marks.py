"""Lossless unions of personal end-board knowledge; never mutate saved plans."""
from copy import deepcopy
import hashlib
import json
import re


def effect_parts(desc):
    return [part for part in re.split(r'(?=[①②③④⑤⑥⑦⑧⑨⑩][：:])', desc or '') if part]


def source_ref(source):
    fingerprint = source.get('fingerprint') or hashlib.sha256(json.dumps(source['annotation'], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return source['key'] + '@' + fingerprint


def refs(values):
    if not isinstance(values, list) or len(values) > 10000 or any(not isinstance(v, str) or len(v) > 600 for v in values):
        raise ValueError('备注来源格式无效')
    return list(dict.fromkeys(values))


def note_items(value, fallback_refs=()):
    """Legacy scalar notes become one row; paragraphs are not guessed as rows."""
    items = value.get('notes')
    if items is None: items = [{'text': value.get('note', ''), 'source_refs': list(fallback_refs)}]
    if not isinstance(items, list) or len(items) > 500: raise ValueError('每处最多保留 500 条并列备注')
    result, by_text = [], {}
    for item in items:
        if not isinstance(item, dict): raise ValueError('并列备注格式无效')
        content = item.get('text', '')
        if not isinstance(content, str) or len(content) > 4000: raise ValueError('每条备注最多 4000 字')
        content = content.replace('\r\n', '\n').strip()
        provenance = refs(item.get('source_refs', []))
        if not content: continue
        if content in by_text:
            row = by_text[content]; row['source_refs'] = refs(row['source_refs'] + provenance)
        else:
            row = {'text': content, 'source_refs': provenance}; by_text[content] = row; result.append(row)
    return result


def note_text(value):
    return '\n\n'.join(item['text'] for item in note_items(value))


def notes_value(items):
    rows = note_items({'notes': items})
    return {'notes': rows, 'note': '\n\n'.join(row['text'] for row in rows)}


def normalize_mark(value):
    result = deepcopy(value)
    result['merged_source_refs'] = refs(result.get('merged_source_refs', []))
    sources = result.get('sources', [])
    card_refs = [source_ref(s) for s in sources if s['annotation'].get('note', '').strip() == result.get('note', '').strip()]
    result.update(notes_value(note_items(result, card_refs)))
    parts = effect_parts(result.get('desc', ''))
    for key, item in result.get('effects', {}).items():
        matching = []
        if key.isdecimal() and int(key) < len(parts):
            for source in sources:
                annotation = source['annotation']; source_parts = effect_parts(annotation.get('desc', ''))
                if any(index.isdecimal() and int(index) < len(source_parts) and source_parts[int(index)].strip() == parts[int(key)].strip()
                       and effect.get('note', '').strip() == item.get('note', '').strip()
                       for index, effect in annotation.get('effects', {}).items()): matching.append(source_ref(source))
        item.update(notes_value(note_items(item, matching)))
        item['source_refs'] = refs(item.get('source_refs', matching))
    pending = result.get('unmatched_effects', [])
    if not isinstance(pending, list) or len(pending) > 500: raise ValueError('待核对效果数量或格式无效')
    result['unmatched_effects'] = []
    for item in pending:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or len(item['text']) > 50000:
            raise ValueError('待核对效果文本无效')
        result['unmatched_effects'].append({'text': item['text'], **notes_value(note_items(item)), 'source_refs': refs(item.get('source_refs', []))})
    return result


def merge_marks(previous, incoming, *, source=None, target_desc=None):
    incoming = normalize_mark(incoming)
    result = normalize_mark(previous) if previous else {
        'code': incoming['code'], 'candidate': False, 'note': '', 'notes': [], 'effects': {},
        'desc': target_desc if target_desc is not None else incoming['desc'], 'sources': [], 'unmatched_effects': [], 'merged_source_refs': []}
    if result['code'] != incoming['code']: raise ValueError('只能合并同一卡号的标注')
    if source:
        reference = source_ref(source)
        # An already merged source version cannot undo subsequent manual edits/resolution.
        # Legacy provenance alone does not mean its notes were ever merged.
        if reference in result['merged_source_refs']: return result
        result['merged_source_refs'].append(reference)
        incoming['sources'] = [*incoming.get('sources', []), deepcopy(source)]
        for item in [incoming, *incoming['effects'].values(), *incoming['unmatched_effects']]:
            for row in item['notes']: row['source_refs'] = refs(row['source_refs'] + [reference])
            item['source_refs'] = refs(item.get('source_refs', []) + [reference])
    result['candidate'] = bool(result['candidate'] or incoming['candidate'])
    result.update(notes_value(result['notes'] + incoming['notes']))
    known_sources = {source_ref(s) for s in result['sources']}
    for item in incoming.get('sources', []):
        if source_ref(item) not in known_sources:
            result['sources'].append(deepcopy(item)); known_sources.add(source_ref(item))
    target_parts, source_parts = effect_parts(result['desc']), effect_parts(incoming['desc'])
    additions = []
    for key, item in incoming['effects'].items():
        if not key.isdecimal() or int(key) >= len(source_parts): raise ValueError('来源效果文本缺失，请先核对来源方案')
        additions.append({**item, 'text': source_parts[int(key)], 'key': key if result['desc'] == incoming['desc'] else None})
    additions.extend(incoming['unmatched_effects'])
    for item in additions:
        candidates = [str(i) for i, part in enumerate(target_parts) if part.strip() == item['text'].strip()]
        key = item.get('key') or (candidates[0] if len(candidates) == 1 else None)
        if key is not None:
            target = result['effects'].setdefault(key, {'notes': [], 'note': '', 'source_refs': []})
        else:
            target = next((p for p in result['unmatched_effects'] if p['text'] == item['text']), None)
            if target is None:
                target = {'text': item['text'], 'notes': [], 'note': '', 'source_refs': []}; result['unmatched_effects'].append(target)
        target.update(notes_value(target['notes'] + item['notes']))
        target['source_refs'] = refs(target.get('source_refs', []) + item.get('source_refs', []))
    return normalize_mark(result)
