"""Extract only factual dates/explicit card aliases from a cached public API response.

Fetch https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes once into .local/,
then run this command. Card text, images, prices and raw responses stay local.
"""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from card_release_dates import valid_date


def extract(raw, retrieved_on):
    valid_date(retrieved_on)
    cards, candidates = {}, {}
    for card in json.loads(raw)['data']:
        code = card['id']
        if type(code) is not int or not 0 < code < 2**32: raise ValueError('来源卡号无效')
        dates = ['', '']
        for misc in card.get('misc_info', []):
            for index, field in enumerate(('ocg_date', 'tcg_date')):
                if misc.get(field):
                    value = valid_date(misc[field])
                    if dates[index] and dates[index] != value: raise ValueError(f'{code}: 首发日期冲突')
                    dates[index] = value
            if type(misc.get('beta_id')) is int:
                candidates.setdefault(misc['beta_id'], set()).add(code)
        for image in card.get('card_images', []):
            if type(image.get('id')) is int and image['id'] != code:
                candidates.setdefault(image['id'], set()).add(code)
        if any(dates):
            if code in cards and cards[code] != dates: raise ValueError(f'{code}: 重复卡号日期冲突')
            cards[code] = dates
    if not cards: raise ValueError('来源没有发售日期，拒绝覆盖已有资料')
    aliases = {code: next(iter(targets)) for code, targets in candidates.items()
               if 0 < code < 2**32 and code not in cards and len(targets) == 1 and next(iter(targets)) in cards}
    return {'version': 1, 'retrieved_on': retrieved_on,
            'source': {'name': 'YGOPRODeck', 'url': 'https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes',
                       'documentation': 'https://ygoprodeck.com/api-guide/', 'sha256': hashlib.sha256(raw).hexdigest()},
            'columns': ['ocg', 'tcg'], 'cards': cards, 'aliases': aliases}


def write_document(document, target):
    # One factual record per line keeps future data updates reviewable.
    header = {key: value for key, value in document.items() if key not in ('cards', 'aliases')}
    text = json.dumps(header, ensure_ascii=False, indent=2).rstrip()[:-1].rstrip() + ',\n'
    for field in ('cards', 'aliases'):
        items = document[field]
        text += f'  "{field}": {{\n'
        text += ',\n'.join(f'    "{code}": {json.dumps(items[code], ensure_ascii=False)}' for code in sorted(items))
        text += '\n  }' + (',\n' if field == 'cards' else '\n}\n')
    Path(target).write_text(text, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='本地已缓存的 cardinfo misc=yes JSON')
    parser.add_argument('--retrieved-on', default=date.today().isoformat())
    parser.add_argument('--output', default=str(ROOT / 'src/trainer/card-release-dates.json'))
    args = parser.parse_args()
    document = extract(Path(args.input).read_bytes(), args.retrieved_on)
    write_document(document, args.output)
    print(f'PASS extracted {len(document["cards"])} dated cards and {len(document["aliases"])} explicit aliases')
