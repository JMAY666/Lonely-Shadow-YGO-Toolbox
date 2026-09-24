"""Read-only OCG evidence, full-segment and semantic gate for the second series phase."""
import argparse
import csv
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from app import Catalog
from card_annotations import CardAnnotations, digest, segments
from plan_tags import builtin_tags


def check(runtime, expected, require_snapshots=False):
    with (ROOT / 'docs/card-annotation-batch-2026-09-25-phase2.csv').open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    evidence_path = ROOT / '.local/anno-batch5-research/official-index.json'
    if require_snapshots and not evidence_path.exists():
        raise ValueError('缺少本轮官方来源快照索引')
    evidence = json.loads(evidence_path.read_text('utf-8')) if evidence_path.exists() else None
    added = [row for row in rows if row['outcome'] == 'reviewed-added']
    assert len(added) == expected, (len(added), expected)
    for row in added:
        code = int(row['code'])
        card = catalog.cards[code]
        entry = document['cards'][str(code)]
        assert row['local_name'] == card['name'] and int(row['local_type']) == card['type']
        assert entry['review']['status'] == 'reviewed' and entry['review']['origin'] == 'manual'
        assert entry['frozen_text'] == card['desc'] and entry['text_digest'] == digest(card['desc'])
        assert {seg['key'] for seg in segments(card['desc'], card['type'])} == {effect['key'] for effect in entry['effects']}
        assert all(urlparse(source['url']).hostname == 'www.db.yugioh-card.com' and source['format'] == 'OCG'
                   for source in entry['sources'])
        refs = {source['id'] for source in entry['sources']}
        assert all(set(note['source_refs']) <= refs for effect in entry['effects'] for note in effect['notes'])
        if evidence is not None:
            proof = evidence[str(code)]
            assert int(row['official_cid']) == proof['cid']
            assert proof['official_text'] == proof['faq_text'] and proof['supplement']
    fake = SimpleNamespace(catalog=catalog, library=SimpleNamespace(builtins=builtin_tags(Path(runtime))),
                           root=ROOT / '.local/anno-batch5-readonly-empty')
    service = CardAnnotations(fake, lambda _: None, lambda *_: None, lambda: '2026-09-25')
    assert service.overview()['annotated_total'] == len(document['cards'])

    def hits(code, **condition):
        result = service.search({'q': str(code), **condition})
        return {hit['key'] for item in result['cards'] if item['code'] == code for hit in item['hits']}

    if expected >= 20:
        assert hits(1041278, cost_kind='tribute') == {'m1'}
        assert hits(1041278, action='special_summon') == {'m1'}
        assert hits(17751597, action='negate_activation') == {'m1'}
        assert not hits(17751597, action='negate_effect')
        assert hits(29948294, action='discard_hand') == {'m1'}
        assert not hits(29948294, cost_kind='discard')
        assert hits(36637374, action='discard_hand') == {'m1'}
        assert not hits(36637374, cost_kind='discard')
        assert hits(60442460, action='banish') == {'m1'}
        assert hits(60442460, action='negate_effect') == {'m1'}
        assert not hits(60442460, action='negate_activation')
        assert hits(81767888, cost_kind='banish') == {'m1'}
        assert not hits(81767888, action='banish')
        assert hits(32756828, action='place_faceup_card') == {'m2'}
        assert not hits(32756828, action='set_card')
    if expected >= 40:
        assert hits(82738008, action='add_hand', from_zone='grave') == {'m1'}
        assert hits(82738008, action='banish', from_zone='hand') == {'m1'}
        assert hits(99543666, action='use_as_fusion_material') == {'m1'}
        assert not hits(99543666, cost_kind='send_grave_cost')
        assert hits(90179822, cost_kind='discard_self') == {'m1'}
        assert hits(90179822, action='negate_effect') == {'m1'}
        assert not hits(90179822, action='negate_activation')
        assert hits(4055337, cost_kind='banish_self_from_grave') == {'m2'}
        assert not hits(4055337, action='banish')
        assert hits(4055337, action='send_grave', from_zone='deck') == {'m2'}
        assert hits(48835607, cost_kind='send_grave_cost') == {'m1'}
        assert not hits(48835607, cost_kind='discard')
        assert hits(48835607, cost_kind='banish') == {'m2'}
        assert hits(29666221, cost_kind='tribute') == {'m1'}
        assert hits(29666221, action='banish', from_zone='opponent_monster') == {'m1'}
    if expected >= 60:
        assert hits(55051920, cost_kind='banish') == {'m1'}
        assert not hits(55051920, action='banish')
        assert hits(55051920, action='send_grave') == {'m2'}
        assert hits(90351981, action='modify_activation_window') == {'m1'}
        assert not hits(90351981, action='special_summon')
        assert hits(74820316, action='take_control') == {'m1'}
        assert hits(74820316, cost_kind='banish_self_from_grave') == {'m2'}
        assert hits(93854893, action='attach_material') == {'m1'}
        assert hits(93854893, action='send_grave') == {'m1'}
        assert hits(93854893, action='detach_material') == {'m2'}
        assert not hits(93854893, cost_kind='detach_material')
        assert hits(2129638, action='banish') == {'m3'}
        assert not hits(2129638, action='special_summon')
        assert all(document['cards'][str(code)]['no_effect'] for code in (23995346,23995347,23995348,23995349,23995350))
    if expected >= 80:
        assert hits(53183600, action='require_attack_payment') == {'m2'}
        assert not hits(53183600, cost_kind='lp')
        assert hits(53183600, action='allow_direct_attack') == {'m3'}
        assert hits(54475145, cost_kind='discard_self') == {'m1'}
        assert hits(54475145, action='send_grave') == {'m3'}
        assert hits(55410871, action='grant_piercing') == {'m2'}
        assert not hits(55410871, action='burn')
        assert hits(56532353, cost_kind='send_grave_cost') == {'m1'}
        assert not hits(56532353, action='send_grave')
        assert hits(59822133, action='negate_activation') == {'m2'}
        assert not hits(59822133, action='negate_effect')
        assert hits(64202399, cost_kind='banish_self_from_grave') == {'m3'}
        assert not hits(64202399, action='banish')
        assert hits(89604813, action='negate_activation') == {'m2'}
        assert not hits(89604813, action='negate_effect')
    if expected == 94:
        assert len(rows) == 100 and sum(row['outcome'] == 'skip-existing-reviewed' for row in rows) == 6
        for series_id in ('set:15d', 'set:164', 'set:11b', 'set:dd'):
            assert all(service.view(code)['status'] == 'reviewed' and service.view(code)['full']
                       for code in service.series.members[series_id]), series_id
    source_check = 'with OCG snapshots' if evidence is not None else 'without local snapshots'
    print(f'PASS phase2 {len(added)} cards {source_check}: full segments, source references and query boundaries')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--expected', type=int, required=True)
    parser.add_argument('--require-snapshots', action='store_true')
    args = parser.parse_args()
    check(args.runtime, args.expected, args.require_snapshots)
