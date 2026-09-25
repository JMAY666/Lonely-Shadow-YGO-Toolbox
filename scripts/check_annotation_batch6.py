"""Read-only source, segment and mechanism checks for the third complete-series phase."""
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
from card_annotations import CardAnnotations, digest, segments, zone_matches
from plan_tags import builtin_tags


def check(runtime, expected, require_snapshots=False):
    with (ROOT / 'docs/card-annotation-batch-2026-09-25-phase3.csv').open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    evidence_path = ROOT / '.local/anno-batch6-research/official-index.json'
    if require_snapshots and not evidence_path.exists():
        raise ValueError('缺少本阶段官方页面快照索引')
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
        assert {s['key'] for s in segments(card['desc'], card['type'])} == {e['key'] for e in entry['effects']}
        assert all(e.get('effect_type') not in ('unclassified', None) and e.get('notes') for e in entry['effects'])
        assert all(urlparse(src['url']).hostname == 'www.db.yugioh-card.com' and src['format'] == 'OCG'
                   for src in entry['sources'])
        refs = {src['id'] for src in entry['sources']}
        assert all(set(note['source_refs']) <= refs for effect in entry['effects'] for note in effect['notes'])
        if evidence is not None:
            proof = evidence[str(code)]
            assert int(row['official_cid']) == proof['cid']
            assert proof['official_name'] and proof['official_text'] == proof['faq_text']
            assert proof['supplement'] or entry.get('no_effect')
            if require_snapshots:
                snapshot_dir = ROOT / '.local/anno-batch6-research'
                for kind in ('card', 'faq'):
                    snapshot = snapshot_dir / f'{kind}-{proof["cid"]}.html'
                    assert snapshot.is_file() and snapshot.stat().st_size > 1000, snapshot
    fake = SimpleNamespace(catalog=catalog, library=SimpleNamespace(builtins=builtin_tags(Path(runtime))),
                           root=ROOT / '.local/anno-batch6-readonly-empty')
    service = CardAnnotations(fake, lambda _: None, lambda *_: None, lambda: '2026-09-25')
    assert service.overview()['annotated_total'] == len(document['cards'])

    def hits(code, **condition):
        result = service.search({'q': str(code), **condition})
        return {hit['key'] for item in result['cards'] if item['code'] == code for hit in item['hits']}

    if expected >= 20:
        assert hits(13408726, action='banish', from_zone='spell') == {'p1'}
        assert hits(13408726, action='banish', from_zone='opponent_monster') == {'m1', 'm2'}
        assert hits(14735698, action='banish', from_zone='grave') == {'m1'}
        assert hits(14735698, cost_kind='banish') == {'m2'}
        assert hits(21105106, cost_kind='discard') == {'m1'}
        assert hits(21105106, action='banish') == {'m2'}
        assert hits(25857246, action='tribute') == {'m2'}
        assert not hits(25857246, cost_kind='tribute')
        assert hits(25857246, action='end_battle_phase') == {'m1'}
        assert hits(39468724, cost_kind='discard_self') == {'m1'}
        assert hits(39468724, action='tribute') == {'m1'}
        assert hits(39468724, cost_kind='tribute') == {'m2'}
        assert hits(50596425, action='send_grave', from_zone='extra') == {'m1'}
        assert not hits(50596425, action='banish')
        assert hits(50596425, cost_kind='banish') == {'m2'}
        assert hits(84388461, cost_kind='tribute') == {'m1'}
        assert hits(84388461, action='use_as_ritual_material') == {'m1'}
        assert hits(88240999, action='destroy') == {'m2'}
        assert hits(88240999, action='banish') == {'m2'}
    if expected >= 40:
        assert hits(89463537, cost_kind='discard_self') == {'m1'}
        assert hits(89463537, action='negate_effect') == {'m2'}
        assert hits(90307777, action='modify_summon_material') == {'m1'}
        assert not hits(90307777, action='special_summon')
        assert hits(97211663, action='use_as_ritual_material') == {'m1'}
        assert hits(97211663, cost_kind='banish') == {'m2'}
        assert hits(6772168, action='banish', from_zone='opponent_monster') == {'m2'}
        assert not hits(6772168, action='banish', from_zone='xyz_material')
        assert hits(33166263, action='deck_reveal', from_zone='extra') == {'m1'}
        assert document['cards']['48791583']['no_effect']
        assert hits(75286621, cost_kind='send_grave_cost') == {'m1'}
        assert not hits(75286621, action='send_grave')
        assert hits(75286621, action='negate_activation') == {'m1'}
        assert hits(80635735, cost_kind='banish') == {'m2'}
        assert hits(80635735, action='negate_effect') == {'m2'}
        assert not hits(80635735, action='negate_activation')
        assert hits(85908279, action='attack_in_defense') == {'m2'}
        assert hits(572850, action='send_grave', from_zone='hand') == {'m1'}
        assert not hits(572850, cost_kind='send_grave_cost')
        assert hits(572850, action='return_deck') == {'m2'}
    if expected >= 60:
        assert hits(1329620, action='negate_activation') == {'m1'}
        assert not hits(1329620, action='negate_effect')
        assert hits(1329620, action='send_grave', from_zone='hand') == {'m1'}
        assert not hits(1329620, cost_kind='send_grave_cost')
        assert hits(4928565, action='banish') == {'m1'}
        assert not hits(4928565, cost_kind='banish')
        assert hits(74078255, action='return_deck') == {'m2'}
        assert hits(74920585, action='send_grave') == {'m1'}
        assert not hits(74920585, cost_kind='send_grave_cost')
        assert hits(84330567, action='negate_activation') == {'m2'}
        assert hits(84330567, action='send_grave') == {'m2'}
        assert hits(92731385, action='choose_branch') == {'m1'}
        assert hits(20618850, action='draw', from_zone='opponent_deck') == {'m1'}
        assert hits(20618850, action='special_summon', to_zone='extra_monster_zone') == {'m1'}
        assert hits(30430448, action='negate_effect') == {'m1'}
        assert not hits(30430448, action='negate_activation')
        assert hits(47219274, action='damage_modify') == {'m2'}
        assert not hits(47219274, action='burn')
        assert zone_matches('monster', ['extra_monster_zone'])
        assert not zone_matches('extra_monster_zone', ['monster'])
    if expected >= 80:
        assert hits(66712905, action='discard_hand', from_zone='opponent_hand') == {'m1'}
        assert not hits(66712905, cost_kind='discard')
        assert hits(68957034, action='destroy', from_zone='opponent_monster') == {'m1'}
        assert hits(68957034, action='special_summon', to_zone='extra_monster_zone') == {'m1'}
        assert hits(92107604, action='modify_activation_window') == {'m1'}
        assert hits(92107604, action='draw') == {'m2'}
        assert hits(92385016, action='negate_activation') == {'m2'}
        assert not hits(92385016, action='negate_effect')
        assert hits(14307929, cost_kind='send_grave_cost') == {'m2'}
        assert not hits(14307929, action='send_grave')
        assert hits(24779554, action='return_deck', from_zone='grave') == {'m3'}
        assert hits(25592142, cost_kind='send_grave_cost') == {'m1'}
        assert not hits(25592142, action='send_grave')
        assert hits(4398189, action='treat_as_tuner') == {'m3'}
        assert hits(5800323, action='place_faceup_card', from_zone='grave') == {'m1'}
        assert hits(5800323, action='use_as_synchro_material', from_zone='monster') == {'m2'}
        assert hits(39491690, action='return_hand', from_zone='field') == {'m1'}
        assert not hits(39491690, action='return_deck')
    if expected == 100:
        assert hits(60145298, cost_kind='send_grave_cost') == {'m1'}
        assert hits(60145298, action='send_grave', from_zone='deck') == {'m2'}
        assert hits(61980241, action='special_summon', from_zone='hand') == {'m1'}
        assert hits(61980241, action='add_hand', from_zone='deck') == {'m1'}
        assert hits(62995268, action='use_as_synchro_material') == {'m1'}
        assert hits(93723936, cost_kind='tribute') == {'m1'}
        assert not hits(93723936, action='tribute')
        assert hits(93723936, action='negate_effect') == {'m1'}
        assert not hits(93723936, action='negate_activation')
        assert hits(4709881, cost_kind='tribute') == {'m2'}
        assert hits(21893603, cost_kind='send_grave_cost') == {'m2'}
        assert hits(30194529, action='send_grave', from_zone='field') == {'m2'}
        assert not hits(30194529, cost_kind='send_grave_cost')
        assert hits(57288708, cost_kind='tribute') == {'m1'}
        assert hits(57288708, action='send_grave') == {'m1'}
        assert hits(77610772, action='send_grave', from_zone='monster') == {'m2'}
        assert hits(84899094, action='negate_activation') == {'m1'}
        assert not hits(84899094, action='negate_effect')
        assert hits(95793022, action='burn') == {'m2'}
        assert hits(95793022, cost_kind='banish') == {'m2'}
        assert not hits(95793022, action='banish')
        for code in (22916281,58400390,95511642):
            assert document['cards'][str(code)]['no_effect']
            assert not hits(code, action='special_summon')
        assert len(rows) == 101 and sum(row['outcome'] == 'skip-existing-reviewed' for row in rows) == 1
        for series_id in ('set:b4','set:f4','set:181','set:17f','set:1b1','set:fd'):
            assert all(service.view(code)['status'] == 'reviewed' and service.view(code)['full']
                       for code in service.series.members[series_id]), series_id
    print(f'PASS phase3 {len(added)} cards: OCG sources, snapshots, full segments and query boundaries')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--expected', type=int, required=True)
    parser.add_argument('--require-snapshots', action='store_true')
    args = parser.parse_args()
    check(args.runtime, args.expected, args.require_snapshots)
