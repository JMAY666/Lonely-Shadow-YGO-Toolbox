"""Verify a reviewed source batch against the actual Catalog and search service."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from app import Catalog
from card_annotations import CardAnnotations, digest, segments, validate_entry
from plan_tags import builtin_tags


def check(runtime, manifest, source_pack=None, supplemental_root=None):
    batch = json.loads(Path(manifest).read_text('utf-8'))
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    evidence = None
    if source_pack:
        source_pack = Path(source_pack).resolve(strict=True)
        raw = (source_pack / 'manifest.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != batch['source_manifest_sha256']:
            raise ValueError('Source manifest changed; re-audit the collected package')
        evidence = {row['code']: row for row in json.loads(raw)['cards']}
    codes = {row['code'] for row in batch['cards']}
    assert len(codes) == len(batch['cards']), 'Duplicate batch card'
    assert not codes.intersection(row['code'] for row in batch.get('pending', []))
    updated = batch.get('updated_cards', [])
    updated_codes = {row['code'] for row in updated}
    assert len(updated_codes) == len(updated) and not codes.intersection(updated_codes)
    checked_codes = codes | updated_codes
    bindings = batch.get('source_bindings', {})
    used_bindings = set()
    if supplemental_root:
        supplemental_root = Path(supplemental_root).resolve(strict=True)
    hashes = {}
    with TemporaryDirectory(prefix='ygo-annotation-source-batch-') as temporary:
        store = SimpleNamespace(catalog=catalog, root=Path(temporary),
                                library=SimpleNamespace(builtins=builtin_tags(Path(runtime))))
        service = CardAnnotations(store, lambda _: None, lambda *_: None, lambda: batch['checked_on'])
        for row in [*batch['cards'], *updated]:
            code = row['code']
            card = catalog.cards[code]
            entry = document['cards'][str(code)]
            assert (card['name'], card['type']) == (row['local_name'], row['local_type']), code
            assert entry['code'] == code and entry['frozen_text'] == card['desc'], code
            assert entry['text_digest'] == row['text_digest'] == digest(card['desc']), code
            assert entry['review']['status'] == 'reviewed' and entry['review']['origin'] == 'manual', code
            keys = {part['key'] for part in segments(card['desc'], card['type'])}
            assert keys == {effect['key'] for effect in entry['effects']}, code
            validate_entry(entry, service.registry, keys, card_type=card['type'])
            assert all(e['effect_type'] != 'unclassified' and e.get('notes') for e in entry['effects']), code
            refs = {s['id'] for s in entry['sources']}
            for item in [entry, *entry['effects']]:
                assert all(n.get('source_refs') and set(n['source_refs']) <= refs for n in item.get('notes', [])), code
            for source in entry['sources']:
                binding_key = f'{code}/{source["id"]}'
                binding = bindings.get(binding_key)
                if binding:
                    assert binding['kind'] in ('pack', 'supplement'), binding_key
                    used_bindings.add(binding_key)
                source_code = binding.get('source_code', code) if binding else code
                expected_cid = binding['official_cid'] if binding else row['official_cid']
                locale = binding.get('locale', 'ja') if binding else 'ja'
                assert locale in ('ja', 'ae'), binding_key
                url = urlparse(source['url'])
                assert url.scheme == 'https' and url.hostname == 'www.db.yugioh-card.com' and not url.username, code
                query = parse_qs(url.query)
                assert source['format'] == 'OCG' and query.get('request_locale') == [locale], code
                if 'cid' in query:
                    assert query['cid'] == [str(expected_cid)], code
                if evidence:
                    if binding and binding['kind'] == 'supplement':
                        if supplemental_root is None:
                            raise ValueError('This batch requires --supplemental-root for complete source verification')
                        original = binding
                        base = supplemental_root
                        assert source['url'] == original['url'], code
                    else:
                        by_id = {s['id']: s for s in evidence[source_code]['sources']}
                        original = by_id[binding['source_id'] if binding else source['id']]
                        base = source_pack
                        assert original['status'] == 'saved' and source['url'] == original['final_url'], code
                    for kind in ('raw', 'text'):
                        path = (base / original[kind + '_path']).resolve(strict=True)
                        if not path.is_relative_to(base):
                            raise ValueError(f'{code}: source path escapes its package')
                        if path not in hashes:
                            hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
                        assert hashes[path] == original[kind + '_sha256'], (code, kind)
        for case in batch['query_cases']:
            code = case['code']
            assert code in checked_codes
            found = service.search({**case['query'], 'q': str(code)})
            actual = {hit['key'] for row in found['cards'] if row['code'] == code for hit in row['hits']}
            assert actual == set(case['expected_keys']), (code, case['reason'], actual, case['expected_keys'])
        for case in batch.get('semantic_cases', []):
            # These assertions freeze manually reviewed rule distinctions, not inferred keywords.
            value = document['cards'][str(case['code'])]
            for part in case['path']:
                value = value[part]
            if case.get('absent_key'):
                assert case['absent_key'] not in value, (case['code'], case['reason'], value)
            else:
                assert value == case['expected'], (case['code'], case['reason'], value)
        assert used_bindings == set(bindings), 'Unused or mismatched supplemental source binding'
        for case in batch.get('purpose_cases', []):
            from card_capabilities import purpose_candidates
            effect = next(e for e in document['cards'][str(case['code'])]['effects'] if e['key'] == case['effect_key'])
            roles = {item['role'] for item in purpose_candidates(effect)}
            assert (case['role'] in roles) is case['expected'], (case['code'], case['reason'], roles)
    print(f'PASS {len(codes)} cards' + (f' + {len(updated_codes)} corrected existing cards' if updated_codes else '')
          + f', {len(batch["query_cases"])} search cases, '
          f'{len(batch.get("semantic_cases", []))} rule distinctions; '
          + (f'{len(hashes)} source files verified' if evidence else 'local snapshots not rechecked'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--manifest', required=True, help='Reviewed public batch manifest')
    parser.add_argument('--source-pack', help='Private collected-source directory; raw content stays local')
    parser.add_argument('--supplemental-root', help='Private directory of explicitly bound additional OCG snapshots')
    args = parser.parse_args()
    check(args.runtime, args.manifest, args.source_pack, args.supplemental_root)
