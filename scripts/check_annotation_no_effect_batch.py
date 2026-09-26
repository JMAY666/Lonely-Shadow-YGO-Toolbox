"""Verify ordinary and non-effect extra/ritual cards against explicit evidence."""
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
from card_annotations import CardAnnotations, digest, segments
from plan_tags import builtin_tags


def check(runtime, evidence=None, extra_evidence=None):
    manifest = json.loads((ROOT / 'docs/card-annotation-batch-2026-09-26-normal.json').read_text('utf-8'))
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    extra_manifest = json.loads((ROOT / 'docs/card-annotation-batch-2026-09-26-noneffect-extra.json').read_text('utf-8'))
    rows = manifest['cards'] + extra_manifest['cards']
    codes = {row['code'] for row in rows}
    if len(codes) != len(rows):
        raise ValueError('通常怪兽交付清单卡号重复')
    proof = None
    if evidence or extra_evidence:
        if not evidence or not extra_evidence:
            raise ValueError('来源快照检查须同时提供通常怪兽与额外／仪式怪兽证据')
        proof = {}
        for path in (evidence, extra_evidence):
            for row in json.loads(Path(path).read_text('utf-8'))['cards']:
                if row['code'] in proof:
                    raise ValueError('来源证据卡号重复')
                proof[row['code']] = row
    for row in rows:
        code = row['code']
        card = catalog.cards[code]
        entry = document['cards'][str(code)]
        assert card['name'] == row['local_name'] and card['type'] == row['local_type']
        ordinary = row.get('group') != 'extra_or_ritual'
        if ordinary:
            assert card['type'] in (17, 4113), (code, '通常怪兽类别不符')
        else:
            assert card['type'] & (0x40 | 0x80 | 0x2000 | 0x800000 | 0x4000000)
            assert not card['type'] & (0x20 | 0x4000 | 0x1000000), (code, '效果、衍生物和灵摆不属于本批')
        assert entry['code'] == code and entry['no_effect'] is True
        assert entry['review']['status'] == 'reviewed' and entry['review']['origin'] == 'manual'
        assert entry['frozen_text'] == card['desc']
        assert digest(card['desc']) == entry['text_digest'] == row['text_digest']
        assert {part['key'] for part in segments(card['desc'], card['type'])} == {effect['key'] for effect in entry['effects']}
        for effect in entry['effects']:
            assert effect['effect_type'] == 'non_effect'
            assert effect['tags'] == ([] if ordinary else ['etag:material-rule'])
            assert not effect['structure'].get('processing')
        if ordinary:
            assert not entry['relations']
        else:
            kind = 'summon_condition' if card['type'] & 0x80 else 'material_rule'
            assert entry['relations'] == [{'kind': kind, 'effects': [effect['key'] for effect in entry['effects']], 'text': card['desc']}]
        source_ids = {source['id'] for source in entry['sources']}
        for source in entry['sources']:
            url = urlparse(source['url'])
            query = parse_qs(url.query)
            assert url.scheme == 'https' and url.hostname == 'www.db.yugioh-card.com'
            assert query.get('cid') == [str(row['official_cid'])] and query.get('request_locale') == ['ja']
            assert source['format'] == 'OCG'
        for item in [entry, *entry['effects']]:
            assert item['notes']
            assert all(note['source_refs'] and set(note['source_refs']) <= source_ids for note in item['notes'])
        if proof is not None:
            p = proof[code]
            assert p['cid'] == row['official_cid']
            card_proof, faq_proof = p['evidence']['card'], p['evidence']['faq_index']
            assert card_proof['text'] and card_proof['text'] == faq_proof['text']
            assert '効果' not in card_proof['species']
            if ordinary:
                assert '通常' in card_proof['species']
            else:
                assert '通常' not in card_proof['species']
                assert 'モンスター効果を持たない' in faq_proof['supplement']
            for source in (card_proof, faq_proof):
                path = (ROOT / source['path']).resolve(strict=True)
                if not path.is_relative_to(ROOT / '.local'):
                    raise ValueError(f'{code}: 来源证据路径不在本地资料目录')
                assert hashlib.sha256(path.read_bytes()).hexdigest() == source['sha256']
    store = SimpleNamespace(catalog=catalog, root=ROOT / '.local/normal-batch-readonly-empty',
                            library=SimpleNamespace(builtins=builtin_tags(Path(runtime))))
    service = CardAnnotations(store, lambda _: None, lambda *_: None, lambda: '2026-09-26')
    for code in codes:
        view = service.view(code)
        assert view['status'] == 'reviewed'
        assert all(set(effect['tags']) <= {'etag:material-rule'} for effect in view['effects'])
    # The word rules in Wattaildragon's flavor text is not an action restriction.
    if 87151205 in codes:
        result = service.search({'q': '87151205', 'action': 'lock'})
        assert not any(card['code'] == 87151205 for card in result['cards'])
    # Listing summon materials cannot imply a special-summon effect.
    for code in (1641882, 5405694, 9053187, 77637979):
        result = service.search({'q': str(code), 'action': 'special_summon'})
        assert not any(card['code'] == code for card in result['cards'])
    print(f'PASS {len(rows)} non-effect cards: explicit classification, frozen text, sources, full segments, summon rules separated from effects'
          + ('; local official snapshots verified' if proof is not None else '; local snapshots not rechecked'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--evidence', help='本地 normal-source-results.json；不提供时不声称重验来源快照')
    parser.add_argument('--extra-evidence', help='本地 extra-source-results.json，与 --evidence 一起使用')
    args = parser.parse_args()
    check(args.runtime, args.evidence, args.extra_evidence)
