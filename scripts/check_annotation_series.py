"""Read-only gate for researched series names, emblems and representative cards."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from card_series import CardSeries, load_presentation
from plan_tags import builtin_tags


def check(runtime):
    from app import Catalog
    runtime = Path(runtime)
    catalog = Catalog(runtime)
    document = load_presentation()
    series = CardSeries(catalog, builtin_tags(runtime), document)
    for item in document['series']:
        for sample in item['samples']:
            card = catalog.cards.get(sample['code'])
            if not card or card.get('type') != sample['type'] or card.get('setcode') != sample['setcode']:
                raise ValueError(f'{item["id"]}/{sample["code"]}: 卡库类型或系列归属与核对快照不一致')
            if item['id'] not in series.memberships[sample['code']]:
                raise ValueError(f'{item["id"]}/{sample["code"]}: 代表卡不属于当前系列')
    print(f'PASS {len(document["series"])} series / {sum(len(s["samples"]) for s in document["series"])} samples: '
          'Chinese names, source references, emblems, covers, installed membership and types')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, help='含 cards.cdb 的卡库目录；仅做只读检查')
    check(parser.parse_args().runtime)
