"""Installed-runtime and official-snapshot semantic checks for the fifth series phase."""
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
    with (ROOT / 'docs/card-annotation-batch-2026-09-25-phase5.csv').open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 97 and len({r['code'] for r in rows}) == 97
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    evidence_path = ROOT / '.local/anno-batch8-research/official-index.json'
    if require_snapshots and not evidence_path.is_file():
        raise ValueError('缺少本阶段官方页面快照索引')
    evidence = json.loads(evidence_path.read_text('utf-8')) if evidence_path.is_file() else None
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
                snapshot_dir = ROOT / '.local/anno-batch8-research'
                for kind in ('card', 'faq'):
                    snapshot = snapshot_dir / f'{kind}-{proof["cid"]}.html'
                    assert snapshot.is_file() and snapshot.stat().st_size > 1000, snapshot
    fake = SimpleNamespace(catalog=catalog, library=SimpleNamespace(builtins=builtin_tags(Path(runtime))),
                           root=ROOT / '.local/anno-batch8-readonly-empty')
    service = CardAnnotations(fake, lambda _: None, lambda *_: None, lambda: '2026-09-25')
    assert service.overview()['annotated_total'] == len(document['cards'])
    def hits(code, **condition):
        result = service.search({'q': str(code), **condition})
        return {hit['key'] for item in result['cards'] if item['code'] == code for hit in item['hits']}

    if expected >= 20:
        assert hits(2311090, action='negate_effect') == {'m2'}
        assert not hits(2311090, action='negate_activation')
        assert hits(15443125, action='lose_lp') == {'m1'}
        assert not hits(15443125, action='burn')
        assert hits(54498517, action='detach_material', from_zone='xyz_material') == {'m2'}
        assert not hits(54498517, cost_kind='detach_material')
        assert hits(68250822, action='attach_material') == {'m1'}
        assert hits(68250822, action='take_control') == {'m1'}
        assert hits(68250822, action='special_summon') == {'m1'}
        assert hits(72329844, cost_kind='detach_material') == {'m2'}
        assert not hits(72329844, action='detach_material')
        assert hits(75922381, action='negate_effect') == {'m2'}
        assert not hits(75922381, action='negate_activation')
        assert hits(88836438, cost_kind='banish') == {'m1'}
        assert hits(88836438, action='choose_branch') == {'m1'}
        assert hits(10793085, cost_kind='send_grave_cost') == {'m1'}
        assert not hits(10793085, action='send_grave')
        assert hits(14816857, cost_kind='banish') == {'m1'}
        assert not hits(14816857, action='banish')
        assert hits(19096726, action='negate_effect') == {'m1'}
        assert not hits(19096726, action='negate_activation')
        assert hits(25908748, cost_kind='send_grave_cost') == {'m2'}
        assert not hits(25908748, action='send_grave')
        assert hits(26847978, action='return_deck', to_zone='deck_bottom') == {'m2'}
        assert not hits(26847978, cost_kind='return_deck')
    if expected >= 40:
        assert hits(33781156, action='send_grave', from_zone='extra') == {'m1'}
        assert not hits(33781156, cost_kind='send_grave_cost')
        assert hits(40975243, action='use_as_link_material', from_zone='monster') == {'m1'}
        assert hits(47163170, cost_kind='discard') == {'m1'}
        assert hits(47163170, action='return_deck', to_zone='deck_bottom') == {'m2'}
        assert not hits(47163170, cost_kind='return_deck')
        assert hits(50810455, cost_kind='discard') == {'m1'}
        assert hits(50810455, cost_kind='banish') == {'m2'}
        assert hits(51097887, action='special_summon', from_zone='deck') == {'m1'}
        assert hits(52331012, action='special_summon', from_zone='grave') == {'m1'}
        assert hits(56196385, action='send_grave', from_zone='deck') == {'m2'}
        assert not hits(56196385, cost_kind='send_grave_cost')
        assert hits(86379342, cost_kind='banish_self_from_grave') == {'m2'}
        assert hits(86379342, action='negate_effect') == {'m2'}
        assert not hits(86379342, action='negate_activation')
        assert hits(87209160, cost_kind='send_grave_self') == {'m1'}
        assert hits(87209160, action='send_grave', from_zone='deck') == {'m1'}
        assert hits(92269002, action='choose_branch') == {'m1'}
        assert hits(96378317, action='banish', from_zone='grave') == {'m2'}
        assert not hits(96378317, cost_kind='banish')
        assert hits(99726621, action='banish', from_zone='field') == {'m1'}
        assert hits(1174075, action='detach_material', from_zone='xyz_material') == {'m2'}
        assert hits(1174075, cost_kind='detach_material') == {'m3'}
        assert hits(1174075, action='negate_activation') == {'m3'}
        assert not hits(1174075, action='negate_effect')
        assert hits(22420202, action='hand_reveal') == {'m1'}
        assert not hits(22420202, cost_kind='reveal')
        assert hits(22398665, action='use_as_ritual_material') == {'m1'}
        assert hits(24166324, cost_kind='tribute') == {'m1'}
        assert hits(24166324, cost_kind='reveal') == {'m2'}
        assert hits(24166324, action='use_as_ritual_material') == {'m2'}
    if expected >= 60:
        assert hits(33543890, action='return_grave', from_zone='banished') == {'m1'}
        assert not hits(33543890, action='send_grave')
        assert hits(56863746, action='negate_activation') == {'m2'}
        assert not hits(56863746, action='negate_effect')
        assert hits(56863746, usage='up_to_two_per_turn') == {'m2'}
        assert hits(58793369, action='change_level') == {'m3'}
        assert hits(69815951, cost_kind='banish') == {'m3'}
        assert hits(69815951, action='send_grave') == {'m3'}
        assert not hits(69815951, action='banish')
        assert hits(84965420, action='negate_summon') == {'m1'}
        assert not hits(84965420, action='negate_activation')
        assert hits(89771220, action='substitute_tribute_cost') == {'m2'}
        assert not hits(89771220, cost_kind='tribute')
        assert hits(94187078, action='destroy') == {'m1'}
        assert hits(95209656, action='special_summon', from_zone='grave') == {'m3'}
        assert hits(17827173, action='normal_summon') == {'m1'}
        assert not hits(17827173, action='special_summon')
        assert hits(17827173, action='banish', from_zone='monster') == {'m2'}
        assert not hits(17827173, cost_kind='banish')
        assert hits(28126717, action='hand_reveal') == {'m1'}
        assert not hits(28126717, cost_kind='reveal')
        assert hits(28126717, action='normal_summon') == {'m1', 'm2'}
        assert hits(41215808, action='normal_summon') == {'m1'}
        assert hits(41215808, cost_kind='banish_self_from_grave') == {'m2'}
        assert hits(53212882, action='increase_normal_summon_limit') == {'m1'}
        assert not hits(53212882, action='normal_summon')
        assert hits(53212882, action='grant_piercing') == {'m2'}
        assert not hits(53212882, action='burn')
        assert hits(55521751, action='modify_summon_material') == {'m1'}
        assert not hits(55521751, action='send_grave')
        assert hits(55521751, action='return_deck', to_zone='deck_bottom') == {'m2'}
    if expected >= 80:
        assert hits(69087397, cost_kind='banish') == {'m1'}
        assert not hits(69087397, action='banish')
        assert hits(69087397, action='heal') == {'m1'}
        assert hits(77610503, action='negate_summon') == {'m1'}
        assert hits(77610503, action='return_unsummoned') == {'m1'}
        assert not hits(77610503, action='negate_activation')
        assert hits(77610503, action='increase_normal_summon_limit') == {'m1'}
        assert hits(80433039, action='banish', from_zone='grave') == {'m1'}
        assert hits(80433039, action='normal_summon') == {'m1'}
        assert not hits(80433039, cost_kind='banish')
        assert hits(80611581, action='normal_summon') == {'m1'}
        assert hits(4145852, action='negate_activation') == {'m2'}
        assert hits(4145852, cost_kind='detach_material') == {'m2'}
        assert hits(4367330, action='negate_activation') == {'m2'}
        assert hits(11510448, action='attach_material', from_zone='grave') == {'m2'}
        assert hits(14970113, action='detach_material', from_zone='xyz_material') == {'m3'}
        assert not hits(14970113, cost_kind='detach_material')
        assert hits(20155904, action='return_deck', from_zone='grave') == {'m1'}
        assert hits(31755044, action='attach_material', from_zone='hand') == {'m1'}
        assert hits(31755044, action='banish', from_zone='opponent_monster') == {'m2'}
        assert hits(46060017, action='destroy', from_zone='field') == {'m1'}
        assert hits(46060017, action='attach_material', from_zone='grave') == {'m2'}
        assert hits(73881652, cost_kind='banish_self_from_grave') == {'m2'}
        assert hits(73881652, action='draw') == {'m2'}
        assert hits(74393852, action='send_grave', from_zone='opponent_hand') == {'m3'}
        assert not hits(74393852, cost_kind='send_grave_cost')
        assert hits(77150143, action='discard_hand') == {'m1'}
        assert not hits(77150143, cost_kind='discard')
        assert hits(78872731, action='special_summon', from_zone='deck') == {'m2'}
        assert hits(98918572, action='substitute_detach_source') == {'m1'}
        assert not hits(98918572, action='detach_material')
        assert hits(6609736, cost_kind='reveal') == {'m1'}
        assert hits(6609736, action='send_grave', from_zone='hand') == {'m1'}
        assert not hits(6609736, cost_kind='send_grave_cost')
    if expected == 97:
        assert hits(11441009, cost_kind='lp') == {'m1'}
        assert hits(11441009, cost_kind='detach_material') == {'m1', 'm2'}
        assert hits(11441009, action='negate_activation') == {'m2'}
        assert not hits(11441009, action='negate_effect')
        assert hits(13258285, action='use_as_fusion_material') == {'m1'}
        assert hits(13258285, action='use_as_synchro_material') == {'m2'}
        assert hits(17691568, action='destroy') == {'m1'}
        assert hits(17691568, action='protect') == {'m2'}
        assert hits(18313046, cost_kind='tribute') == {'m1'}
        assert hits(18313046, action='grant_extra_attack') == {'m2'}
        assert hits(19535693, cost_kind='lp') == {'m1'}
        assert hits(28403802, action='choose_branch') == {'m1'}
        assert hits(28403802, action='send_grave', from_zone='deck') == {'m1'}
        assert not hits(28403802, cost_kind='send_grave_cost')
        assert hits(43685562, action='negate_effect') == {'m1'}
        assert not hits(43685562, action='negate_activation')
        assert hits(43685562, action='heal') == {'m1'}
        assert hits(44708154, action='return_hand', from_zone='field') == {'m1'}
        assert hits(49370016, cost_kind='banish') == {'m1'}
        assert hits(49370016, usage='up_to_two_per_turn') == {'m2'}
        assert hits(49370016, action='draw') == {'m2'}
        assert hits(55920742, cost_kind='send_grave_self') == {'m2'}
        assert hits(55920742, action='send_grave', from_zone='hand') == {'m2'}
        assert hits(55920742, action='heal') == {'m3'}
        assert hits(70070211, action='destroy', from_zone='field') == {'m1'}
        assert hits(75046994, action='set_position') == {'m3'}
        assert not hits(75046994, action='negate_effect')
        assert hits(81192859, action='protect') == {'m2'}
        assert hits(81914447, cost_kind='send_grave_self') == {'m2'}
        assert hits(81914447, action='stat_change') == {'m3'}
        assert not hits(81914447, action='negate_effect')
        assert hits(82041999, cost_kind='lp') == {'m1'}
        assert hits(82041999, action='stat_change') == {'m2'}
        assert all(row['outcome'] == 'reviewed-added' for row in rows)
        for series_id in ('set:180','set:14d','set:154','set:16d','set:f1','set:171'):
            assert all(service.view(code)['status'] == 'reviewed' and service.view(code)['full']
                       for code in service.series.members[series_id]), series_id
    print(f'PASS phase5 {len(added)} cards: OCG sources, snapshots, full segments and query boundaries')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--expected', type=int, required=True)
    parser.add_argument('--require-snapshots', action='store_true')
    args = parser.parse_args()
    check(args.runtime, args.expected, args.require_snapshots)
