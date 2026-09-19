"""Shared vocabulary, copy-weighted deck suggestions and atomic YDK metadata."""
from collections import Counter
import json

from plan_tags import contains_card, membership_basis, normalized, validate_selection

PREFIX = '#trainer-tags: '
MIN_CARDS, MIN_RATIO = 2, 0.05


def empty_selection():
    return {'tag_ids': [], 'primary_ids': []}


def selection(value, vocabulary):
    checked = validate_selection(value, vocabulary)
    return {key: checked[key] for key in ('tag_ids', 'primary_ids')}


def read_selection(data):
    for line in data.decode('utf-8-sig', errors='replace').splitlines():
        if not line.startswith(PREFIX): continue
        try:
            value = json.loads(line[len(PREFIX):])
            if not isinstance(value, dict) or value.get('version') != 1: raise ValueError()
            ids = value.get('tag_ids', [])
            if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids): raise ValueError()
            # Preserve references when an installed vocabulary no longer has a tag.
            return selection(value, dict.fromkeys(ids))
        except (ValueError, TypeError):
            raise ValueError('卡组 TAG 注释无效，原文件已保留，请从备份恢复后重试') from None
    return empty_selection()


def comment(value):
    return PREFIX + json.dumps({'version': 1, **value}, ensure_ascii=False, separators=(',', ':')) + '\n'


def suggest(deck, tags, catalog):
    copies = Counter(deck['main'] + deck['extra'])
    total = sum(copies.values())
    candidates = []
    for key, tag in tags.items():
        cards = [{'code': code, 'name': catalog[code]['name'], 'count': count, 'basis': membership_basis(tag, code, catalog[code])}
                 for code, count in sorted(copies.items()) if contains_card(tag, code, catalog[code])]
        count = sum(card['count'] for card in cards)
        if count:
            candidates.append({'id': key, 'count': count, 'total': total, 'ratio': count / total, 'cards': cards,
                               'eligible': count >= MIN_CARDS and count / total >= MIN_RATIO})
    candidates.sort(key=lambda item: (-item['count'], -((tags[item['id']].get('setcode') or 0) >> 12).bit_count(),
                                      tags[item['id']]['name'], item['id']))
    primary = [candidates[0]['id']] if candidates else []
    selected = (primary + [c['id'] for c in candidates[1:] if c['eligible']])[:30]
    return {'tag_ids': selected, 'primary_ids': primary, 'total': total, 'candidates': candidates,
            'minimum_cards': MIN_CARDS, 'minimum_ratio': MIN_RATIO}


def options(deck, tags, catalog, query='', card_ids=None):
    if not isinstance(query, str) or len(query) > 120: raise ValueError('搜索文字最多 120 个字符')
    deck_ids = set(deck['main'] + deck['extra'] + deck['side'])
    if card_ids is None: card_ids = []
    if not isinstance(card_ids, list) or len(card_ids) > 90 or any(type(code) is not int or code not in deck_ids for code in card_ids):
        raise ValueError('请从本卡组中选择关联卡牌')
    query = normalized(query)
    matching_cards = [card for code, card in catalog.items()
                      if query and (query in normalized(card['name']) or query == str(code))]
    suggestions = suggest(deck, tags, catalog)
    rank = {item['id']: index for index, item in enumerate(suggestions['candidates'])}
    result = []
    for key, tag in tags.items():
        if card_ids and not any(contains_card(tag, code, catalog[code]) for code in card_ids): continue
        if query and not (any(query in normalized(name) for name in [tag['name'], *tag.get('aliases', [])])
                          or any(contains_card(tag, card['id'], card) for card in matching_cards)): continue
        result.append({'id': key, 'name': tag['name'], 'aliases': tag.get('aliases', []),
                       'deck_card_ids': [code for code in sorted(deck_ids) if contains_card(tag, code, catalog[code])]})
    result.sort(key=lambda tag: (rank.get(tag['id'], len(rank)), tag['name'], tag['id']))
    return {'tags': result, 'suggestions': suggestions,
            'tag_names': {key: tags[key]['name'] for key in suggestions['tag_ids']}}
