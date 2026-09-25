"""Read-only installed-runtime/source and mechanism audit for the fourth series phase."""
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
    with (ROOT / 'docs/card-annotation-batch-2026-09-25-phase4.csv').open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 96 and len({r['code'] for r in rows}) == 96
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    evidence_path = ROOT / '.local/anno-batch7-research/official-index.json'
    if require_snapshots and not evidence_path.is_file():
        raise ValueError('缺少本阶段官方来源快照索引')
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
                snapshot_dir = ROOT / '.local/anno-batch7-research'
                for kind in ('card', 'faq'):
                    snapshot = snapshot_dir / f'{kind}-{proof["cid"]}.html'
                    assert snapshot.is_file() and snapshot.stat().st_size > 1000, snapshot

    fake = SimpleNamespace(catalog=catalog, library=SimpleNamespace(builtins=builtin_tags(Path(runtime))),
                           root=ROOT / '.local/anno-batch7-readonly-empty')
    service = CardAnnotations(fake, lambda _: None, lambda *_: None, lambda: '2026-09-25')
    assert service.overview()['annotated_total'] == len(document['cards'])

    def hits(code, **condition):
        result = service.search({'q': str(code), **condition})
        return {hit['key'] for item in result['cards'] if item['code'] == code for hit in item['hits']}

    if expected >= 20:
        assert hits(8491308, action='allow_direct_attack') == {'m1'}
        assert hits(8491308, action='send_grave', from_zone='deck') == {'m2'}
        assert hits(9726840, action='send_grave', from_zone='field') == {'m1'}
        assert not hits(9726840, cost_kind='send_grave_cost')
        assert hits(9726840, action='special_summon', to_zone='extra_monster_zone') == {'m1'}
        assert hits(17217034, action='negate_effect') == {'m1'}
        assert not hits(17217034, action='negate_activation')
        assert hits(20357457, cost_kind='discard') == {'m1'}
        assert hits(20357457, action='choose_branch') == {'m3'}
        assert hits(21623008, action='return_deck', from_zone='opponent_extra_monster_zone') == {'m1'}
        assert not hits(21623008, action='return_deck', from_zone='extra_monster_zone')
        assert hits(22790910, cost_kind='banish') == {'m2'}
        assert not hits(22790910, action='banish')
        assert hits(22790910, action='negate_effect') == {'m2'}
        assert not hits(22790910, action='negate_activation')
        assert hits(23530726, action='destroy') == {'m1'}
        assert hits(24010609, action='send_grave', from_zone='field') == {'m1'}
        assert not hits(24010609, cost_kind='send_grave_cost')
        assert hits(25072579, action='change_effect') == {'m1'}
        assert not hits(25072579, action='negate_effect')
        assert hits(33331231, action='special_summon') == {'m1'}
        assert not hits(33331231, action='tribute')
        assert not hits(33331231, cost_kind='tribute')
        assert hits(34433770, action='return_hand', from_zone='field') == {'m1'}
        assert hits(34433770, action='use_as_link_material', from_zone='monster') == {'m2'}
        assert hits(34433770, cost_kind='banish') == {'m2'}
        assert zone_matches('opponent_monster', ['opponent_extra_monster_zone'])
        assert not zone_matches('extra_monster_zone', ['opponent_extra_monster_zone'])
    if expected >= 40:
        assert hits(34456146, cost_kind='banish') == {'m2'}
        assert hits(34456146, action='special_summon', from_zone='grave') == {'m2'}
        assert hits(34456146, action='give_control', to_zone='opponent_monster') == {'m2'}
        assert not hits(34456146, action='take_control')
        assert hits(37351133, action='negate_effect') == {'m2'}
        assert not hits(37351133, action='negate_activation')
        assert hits(46271408, action='choose_branch') == {'m1'}
        assert hits(50005218, action='deck_reveal', from_zone='deck_top') == {'m1'}
        assert hits(50005218, action='send_grave', from_zone='field') == {'m1'}
        assert not hits(50005218, cost_kind='send_grave_cost')
        assert hits(51227866, action='banish', from_zone='opponent_grave') == {'m1'}
        assert hits(51227866, action='special_summon', from_zone='opponent_grave') == {'m1'}
        assert hits(56741506, action='equip_as_spell', from_zone='opponent_monster') == {'m1'}
        assert not hits(56741506, action='special_summon', from_zone='opponent_monster')
        assert hits(61151074, action='equip_as_spell', from_zone='grave') == {'m2'}
        assert hits(63013339, action='send_grave', from_zone='opponent_monster') == {'m2'}
        assert hits(63013339, action='special_summon', to_zone='opponent_monster') == {'m2'}
        assert hits(63166095, action='add_hand') == {'m1'}
        assert hits(63166095, action='draw') == {'m1'}
        assert hits(75147529, action='banish') == {'m1'}
        assert hits(75147529, action='send_grave') == {'m2'}
        assert hits(76072561, cost_kind='tribute') == {'m2'}
        assert not hits(76072561, action='tribute')
        assert hits(90673288, action='add_hand') == {'m2'}
    if expected >= 60:
        assert hits(96084564, action='equip_as_spell', from_zone='hand') == {'m1'}
        assert hits(96084564, action='send_grave', from_zone='deck') == {'m3'}
        assert hits(96795312, action='banish', from_zone='grave') == {'m2'}
        assert not hits(96795312, cost_kind='banish')
        assert hits(97616504, action='draw') == {'m2'}
        assert hits(97616504, action='return_deck') == {'m3'}
        assert hits(98338152, action='negate_effect') == {'m1'}
        assert not hits(98338152, action='negate_activation')
        assert hits(98462037, action='send_grave', from_zone='monster') == {'m1'}
        assert not hits(98462037, cost_kind='send_grave_cost')
        assert hits(12163590, cost_kind='discard_self') == {'m1'}
        assert hits(12163590, action='return_hand') == {'m3'}
        assert hits(13171876, action='send_grave', from_zone='deck_top') == {'m1'}
        assert hits(14625090, action='lock') == {'m3'}
        assert hits(15754711, action='special_summon', from_zone='hand') == {'m1'}
        assert hits(15848542, cost_kind='discard_self') == {'m1'}
        assert not hits(15848542, action='negate_effect')
        assert hits(16960120, action='send_grave', from_zone='hand') == {'m1'}
        assert not hits(16960120, cost_kind='send_grave_cost')
        assert hits(24799107, action='negate_activation') == {'m2'}
        assert not hits(24799107, action='negate_effect')
        assert hits(24799107, action='return_deck', to_zone='extra') == {'m2'}
        assert hits(40110009, action='use_as_fusion_material') == {'m1'}
        assert hits(40110009, action='return_hand') == {'m2'}
        assert hits(41232647, action='destroy', from_zone='opponent_monster') == {'m2'}
    if expected >= 80:
        assert hits(42055234, cost_kind='discard_self') == {'m1'}
        assert hits(48658295, action='use_as_fusion_material', from_zone='banished') == {'m2'}
        assert hits(49575521, action='return_deck', from_zone='opponent_grave') == {'m1'}
        assert hits(57416183, action='return_hand', from_zone='monster') == {'m1'}
        assert hits(57416183, action='add_hand', from_zone='opponent_grave') == {'m1'}
        assert hits(57416183, cost_kind='banish') == {'m2'}
        assert hits(77515704, action='choose_branch') == {'m1'}
        assert hits(78231355, action='send_grave', from_zone='deck') == {'m1'}
        assert not hits(78231355, cost_kind='send_grave_cost')
        assert hits(14025912, action='special_summon', from_zone='grave') == {'m1'}
        assert hits(14393464, cost_kind='send_grave_cost') == {'m2'}
        assert not hits(14393464, action='send_grave')
        assert hits(16360142, action='stat_change') == {'m1'}
        assert hits(17946349, action='negate_effect') == {'m2'}
        assert not hits(17946349, action='negate_activation')
        assert hits(27182739, action='modify_summon_material') == {'m2'}
        assert not hits(27182739, action='special_summon', from_zone='monster')
        assert hits(36521307, cost_kind='send_grave_cost') == {'m1'}
        assert not hits(36521307, action='send_grave')
        assert hits(41410651, cost_kind='send_grave_cost') == {'m1'}
        assert not hits(41410651, action='send_grave')
        assert hits(42632209, action='damage_modify', from_zone='extra_monster_zone') == {'m2'}
        assert not hits(42632209, action='burn')
        assert hits(52354896, action='change_level') == {'m1'}
        assert hits(53577438, cost_kind='tribute') == {'m1'}
        assert not hits(53577438, action='tribute')
    if expected == 96:
        assert hits(80965043, action='stat_change') == {'m1'}
        assert hits(85692042, cost_kind='detach_material') == {'m1'}
        assert hits(85692042, cost_kind='tribute') == {'m2'}
        assert hits(87804365, action='use_as_synchro_material') == {'m1'}
        assert hits(87804365, action='use_as_xyz_material') == {'m1'}
        assert hits(88021907, cost_kind='detach_material') == {'m1'}
        assert hits(88021907, action='detach_material', from_zone='xyz_material') == {'m2'}
        assert hits(88021907, action='send_grave', from_zone='opponent_hand') == {'m1'}
        assert not hits(88021907, cost_kind='send_grave_cost')
        assert hits(89743495, cost_kind='tribute') == {'m1'}
        assert not hits(89743495, action='tribute')
        assert hits(21293424, action='draw') == {'m1'}
        assert hits(21293424, action='add_hand') == {'m1'}
        assert hits(24393683, cost_kind='banish_self_from_grave') == {'m2'}
        assert hits(24393683, action='return_deck') == {'m1', 'm2'}
        assert document['cards']['24639891']['no_effect']
        assert not hits(24639891, action='destroy')
        assert hits(42377643, cost_kind='reveal') == {'m1'}
        assert hits(42377643, action='change_level') == {'m2'}
        assert hits(61027400, action='deck_reveal') == {'m2'}
        assert hits(62200831, action='require_lp_payment') == {'m2'}
        assert not hits(62200831, action='lose_lp')
        assert not hits(62200831, action='burn')
        assert hits(62200831, action='use_as_xyz_material') == {'m2'}
        assert hits(63748694, action='treat_as_name', from_zone='deck') == {'m1'}
        assert hits(63748694, action='use_as_xyz_material') == {'m2'}
        assert hits(75215744, action='grant_extra_attack') == {'m1'}
        assert hits(78362751, action='return_deck', to_zone='deck_top') == {'m2'}
        assert hits(83008724, action='place_counter') == {'m1'}
        assert hits(83008724, action='require_lp_payment') == {'m2'}
        assert not hits(83008724, action='lose_lp')
        assert not hits(83008724, action='burn')
        assert hits(94798725, action='allow_direct_attack') == {'m1'}
        assert hits(94798725, action='negate_effect') == {'m2'}
        assert not hits(94798725, action='negate_activation')
        assert all(row['outcome'] == 'reviewed-added' for row in rows)
        for series_id in ('set:115','set:133','set:132','set:166'):
            assert all(service.view(code)['status'] == 'reviewed' and service.view(code)['full']
                       for code in service.series.members[series_id]), series_id
    print(f'PASS phase4 {len(added)} cards: OCG sources, snapshots, full segments and query boundaries')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--expected', type=int, required=True)
    parser.add_argument('--require-snapshots', action='store_true')
    args = parser.parse_args()
    check(args.runtime, args.expected, args.require_snapshots)
