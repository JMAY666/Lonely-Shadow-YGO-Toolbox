"""Read-only acceptance gate for human/agent-authored card annotations."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from card_annotations import Registry, digest, segments, validate_entry


def check(runtime=None):
    registry = Registry(json.loads((ROOT / 'src/trainer/annotation-tags.json').read_text('utf-8')))
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = None
    if runtime:
        from app import Catalog
        catalog = Catalog(Path(runtime))
        if not catalog.cards:
            raise ValueError('指定卡库没有卡片')
    for code, entry in document['cards'].items():
        if int(code) != entry['code']:
            raise ValueError(f'{code}: 卡号与键不一致')
        if not entry.get('frozen_text') or digest(entry['frozen_text']) != entry['text_digest']:
            raise ValueError(f'{code}: 必须保存与指纹一致的卡文快照')
        if not entry.get('sources'):
            raise ValueError(f'{code}: 缺少外部核对来源')
        validate_entry(entry, registry)
        refs = {source['id'] for source in entry['sources']}
        for item in [entry, *entry['effects']]:
            for note in item.get('notes', []):
                if not note.get('source_refs') or not set(note['source_refs']) <= refs:
                    raise ValueError(f'{code}: 备注缺少可解析来源')
        for effect in entry['effects']:
            if not effect.get('effect_type'):
                raise ValueError(f'{code}/{effect["key"]}: 缺少效果类别')
            if any(registry.tags[tag].get('deprecated') for tag in effect['tags']):
                raise ValueError(f'{code}: 新参考样本不能使用兼容旧标签')
        if catalog:
            card = catalog.cards.get(int(code))
            if not card or card.get('type', 0) & 0x4000:
                raise ValueError(f'{code}: 当前卡库缺卡或为衍生物')
            if digest(card.get('desc')) != entry['text_digest']:
                raise ValueError(f'{code}: 当前卡文已变化，须重新核对')
            keys = {part['key'] for part in segments(card.get('desc'), card.get('type', 0))}
            validate_entry(entry, registry, keys)
            if entry['review']['status'] == 'reviewed' and not entry.get('no_effect') and keys != {e['key'] for e in entry['effects']}:
                raise ValueError(f'{code}: 已核对条目缺少卡文分段')
    print(f'PASS {len(document["cards"])} annotations: vocabulary, sources, text snapshots'
          + (', installed card text and segment coverage' if catalog else ' (installed catalog not checked)'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', help='含 cards.cdb 的卡库目录；仅以只读方式核对')
    check(parser.parse_args().runtime)
