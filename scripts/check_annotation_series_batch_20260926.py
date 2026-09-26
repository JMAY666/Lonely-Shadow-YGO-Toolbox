"""Read-only runtime and behavior gate for the Raidraptor/Superheavy source batch."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from app import Catalog
from card_annotations import CardAnnotations, digest, segments, validate_entry
from plan_tags import builtin_tags


def check(runtime, source_pack=None):
    batch = json.loads((ROOT / 'docs/card-annotation-batch-2026-09-26-series.json').read_text('utf-8'))
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    store = SimpleNamespace(catalog=catalog, root=ROOT / '.local/series-20260926-readonly-empty',
                            library=SimpleNamespace(builtins=builtin_tags(Path(runtime))))
    service = CardAnnotations(store, lambda _: None, lambda *_: None, lambda: '2026-09-26')
    evidence = None
    if source_pack:
        source_pack = Path(source_pack).resolve(strict=True)
        path = source_pack / 'manifest.json'
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != batch['source_manifest_sha256']:
            raise ValueError('来源包索引已变化，需重新接收审计')
        evidence = {row['code']: row for row in json.loads(raw)['cards']}
    hashes = {}
    codes = {row['code'] for row in batch['cards']}
    assert len(codes) == len(batch['cards'])
    for row in batch['cards']:
        code = row['code']
        card = catalog.cards[code]
        entry = document['cards'][str(code)]
        assert (card['name'], card['type']) == (row['local_name'], row['local_type'])
        assert entry['code'] == code and entry['frozen_text'] == card['desc']
        assert entry['text_digest'] == row['text_digest'] == digest(card['desc'])
        assert entry['review']['status'] == 'reviewed' and entry['review']['origin'] == 'manual'
        keys = {part['key'] for part in segments(card['desc'], card['type'])}
        assert keys == {effect['key'] for effect in entry['effects']}
        validate_entry(entry, service.registry, keys, card_type=card['type'])
        assert all(effect['effect_type'] != 'unclassified' and effect.get('notes') for effect in entry['effects'])
        assert row['series'] in service.series.memberships[code]
        refs = {s['id'] for s in entry['sources']}
        for item in [entry, *entry['effects']]:
            assert all(note.get('source_refs') and set(note['source_refs']) <= refs for note in item.get('notes', []))
        by_source_id = {s['id']: s for s in evidence[code]['sources']} if evidence else {}
        for source in entry['sources']:
            url = urlparse(source['url'])
            assert url.scheme == 'https' and url.hostname == 'www.db.yugioh-card.com'
            assert source['format'] == 'OCG'
            if 'cid' in parse_qs(url.query):
                assert parse_qs(url.query)['cid'] == [str(row['official_cid'])]
            if evidence:
                original = by_source_id[source['id']]
                assert source['url'] == original['final_url']
                assert original['status'] == 'saved' and original['locale'].startswith('ja;')
                for name in ('raw', 'text'):
                    path = (source_pack / original[name + '_path']).resolve(strict=True)
                    if not path.is_relative_to(source_pack):
                        raise ValueError(f'{code}: 来源路径越界')
                    if path not in hashes:
                        hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
                    assert hashes[path] == original[name + '_sha256']
    for case in batch['query_cases']:
        assert case['code'] in codes
        found = service.search(case['query'])
        hits = [hit for card in found['cards'] if card['code'] == case['code'] for hit in card['hits']]
        actual = {hit['key'] for hit in hits}
        assert actual == set(case['expected_keys']), (case['code'], case['reason'], actual, case['expected_keys'])
        if case.get('require_granted_evidence'):
            assert hits and all(all(item.get('effect_source') == 'granted_effect' for item in hit['evidence']) for hit in hits)
    for series in ('set:ba', 'set:9a'):
        assert all(service.view(code)['status'] in ('reviewed', 'confirmed') for code in service.series.members[series])
    print(f'PASS {len(codes)} cards, {len(batch["query_cases"])} mechanism queries, two complete series'
          + (f', {len(hashes)} source files verified' if evidence else '; local source files not rechecked'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--source-pack', help='本地全库来源包目录；原文文件不进入 Git')
    args = parser.parse_args()
    check(args.runtime, args.source_pack)
