"""Offline physical-card release dates; no network access or user-data writes."""
from datetime import date
from functools import lru_cache
import json
from pathlib import Path


def valid_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('发售日期必须是 YYYY-MM-DD')
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('发售日期无效')
    return value


@lru_cache(maxsize=1)
def load_release_dates():
    document = json.loads(Path(__file__).with_name('card-release-dates.json').read_text('utf-8'))
    if document.get('version') != 1 or document.get('columns') != ['ocg', 'tcg']:
        raise ValueError('发售日期资料版本或列定义无效')
    valid_date(document['retrieved_on'])
    for code, dates in document['cards'].items():
        if not code.isdecimal() or not 0 < int(code) < 2**32 or len(dates) != 2 or not any(dates):
            raise ValueError('卡片发售资料无效')
        for value in dates:
            if value: valid_date(value)
    for alias, code in document['aliases'].items():
        if not alias.isdecimal() or not 0 < int(alias) < 2**32 or str(code) not in document['cards']:
            raise ValueError('发售资料卡号映射无效')
    return document


class ReleaseDates:
    def __init__(self, document=None):
        self.document = document if document is not None else load_release_dates()

    def card(self, code):
        canonical = str(code)
        if canonical not in self.document['cards']:
            canonical = str(self.document.get('aliases', {}).get(canonical, ''))
        values = self.document['cards'].get(canonical, ['', ''])
        choices = [(value, region) for value, region in zip(values, ('OCG', 'TCG')) if value]
        if not choices: return None
        first = min(value for value, _ in choices)
        return {'date': first, 'region': '/'.join(region for value, region in choices if value == first),
                'card_code': code, 'source_code': int(canonical)}

    def first(self, codes):
        known = [value for code in codes if (value := self.card(code))]
        first = min(known, key=lambda value: (value['date'], value['card_code'])) if known else {}
        return {**first, 'known_cards': len(known), 'total_cards': len(codes),
                'scheduled': bool(first and first['date'] > date.today().isoformat()),
                'source': 'YGOPRODeck · OCG/TCG 实体卡首发',
                'retrieved_on': self.document['retrieved_on']}
