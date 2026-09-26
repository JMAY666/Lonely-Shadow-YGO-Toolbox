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
from annotation_batch_support import (atomic_json, cached_result, read_json,
                                      snapshot_hashes, validation_fingerprint)

QUERY_FIELDS = {'q', 'status', 'etags', 'etag_mode', 'scope', 'offset', 'series', 'group_by',
                'tag', 'kind', 'catalog_scope', 'action', 'from_zone', 'to_zone', 'usage', 'cost_kind', 'timing'}


def check(runtime, manifest, source_pack=None, supplemental_root=None, *,
          document_path=None, cache_path=None, full=False):
    if sys.flags.optimize:
        raise ValueError('Annotation checks must run without Python -O')
    batch = read_json(manifest)
    document_path = Path(document_path) if document_path else ROOT / 'src/trainer/card-annotations.json'
    document = read_json(document_path)
    catalog = Catalog(Path(runtime))
    evidence = None
    if source_pack:
        source_pack = Path(source_pack).resolve(strict=True)
        raw = (source_pack / 'manifest.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != batch['source_manifest_sha256']:
            raise ValueError('Source manifest changed; re-audit the collected package')
        evidence = {row['code']: row for row in read_json(source_pack / 'manifest.json')['cards']}
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
    builtins = builtin_tags(Path(runtime))
    hashes = snapshot_hashes(batch, document, source_pack, supplemental_root) if source_pack else {}
    fingerprint = validation_fingerprint(ROOT, batch, document, catalog, builtins, hashes) if cache_path else None
    if cache_path and not full:
        result = cached_result(cache_path, fingerprint)
        if result:
            print(f'PASS checkpoint cache: {result["cards"]} cards, {result["search_cases"]} search cases; '
                  f'{len(hashes)} source files freshly hashed')
            return {**result, 'cache_hit': True, 'fingerprint': fingerprint}
    with TemporaryDirectory(prefix='ygo-annotation-source-batch-') as temporary:
        store = SimpleNamespace(catalog=catalog, root=Path(temporary),
                                library=SimpleNamespace(builtins=builtins))
        service = CardAnnotations(store, lambda _: None, lambda *_: None, lambda: batch['checked_on'],
                                  curated_path=document_path, registry_path=ROOT / 'src/trainer/annotation-tags.json')
        for row in [*batch['cards'], *updated]:
            code = row['code']
            card = catalog.cards[code]
            entry = document['cards'][str(code)]
            assert (card['name'], card['type']) == (row['local_name'], row['local_type']), code
            assert entry['code'] == code and entry['frozen_text'] == card['desc'], code
            assert entry['text_digest'] == row['text_digest'] == digest(card['desc']), code
            assert entry['review']['status'] == 'reviewed' and entry['review']['origin'] == 'manual', code
            keys = {part['key'] for part in segments(card['desc'], card['type'])}
            normal_flavor = (entry.get('no_effect') is True and card['type'] & 0x1
                             and card['type'] & 0x10 and not card['type'] & 0x1000020 and not entry['effects'])
            assert normal_flavor or keys == {effect['key'] for effect in entry['effects']}, code
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
            if set(case['query']) - QUERY_FIELDS:
                raise ValueError(f'{code}: query case contains unsupported filter fields')
            found = service.search({**case['query'], 'q': str(code)})
            actual = {hit['key'] for row in found['cards'] if row['code'] == code for hit in row['hits']}
            assert actual == set(case['expected_keys']), (code, case['reason'], actual, case['expected_keys'])
        for case in batch.get('semantic_cases', []):
            # These assertions freeze manually reviewed rule distinctions, not inferred keywords.
            assert case['code'] in checked_codes, 'Rule case references a card outside this batch'
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
            assert case['code'] in checked_codes, 'Purpose case references a card outside this batch'
            effect = next(e for e in document['cards'][str(case['code'])]['effects'] if e['key'] == case['effect_key'])
            roles = {item['role'] for item in purpose_candidates(effect)}
            assert (case['role'] in roles) is case['expected'], (case['code'], case['reason'], roles)
    result = {'cards': len(codes), 'updated_cards': len(updated_codes),
              'search_cases': len(batch['query_cases']), 'rule_cases': len(batch.get('semantic_cases', [])),
              'purpose_cases': len(batch.get('purpose_cases', [])), 'source_files': len(hashes),
              'source_snapshots_verified': evidence is not None}
    if cache_path:
        atomic_json(cache_path, {'protocol': 1, 'fingerprint': fingerprint, 'status': 'passed', 'result': result})
    print(f'PASS {len(codes)} cards' + (f' + {len(updated_codes)} corrected existing cards' if updated_codes else '')
          + f', {len(batch["query_cases"])} search cases, '
          f'{len(batch.get("semantic_cases", []))} rule distinctions; '
          + (f'{len(hashes)} source files verified' if evidence else 'local snapshots not rechecked'))
    return {**result, 'cache_hit': False, 'fingerprint': fingerprint}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--manifest', required=True, help='Reviewed public batch manifest')
    parser.add_argument('--source-pack', help='Private collected-source directory; raw content stays local')
    parser.add_argument('--supplemental-root', help='Private directory of explicitly bound additional OCG snapshots')
    parser.add_argument('--document', help='Staged annotation document; default is the built-in document')
    parser.add_argument('--cache', help='Private checkpoint cache; actual source bytes are hashed on every run')
    parser.add_argument('--full', action='store_true', help='Run all checks even on a cache hit (required before integration)')
    args = parser.parse_args()
    check(args.runtime, args.manifest, args.source_pack, args.supplemental_root,
          document_path=args.document, cache_path=args.cache, full=args.full)
