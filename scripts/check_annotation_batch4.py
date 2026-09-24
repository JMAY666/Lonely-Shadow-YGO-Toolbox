"""Read-only source and semantic gate for the 2026-09-25 annotation expansion."""
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
    with (ROOT / 'docs/card-annotation-batch-2026-09-25.csv').open(encoding='utf-8-sig', newline='') as file:
        rows = list(csv.DictReader(file))
    document = json.loads((ROOT / 'src/trainer/card-annotations.json').read_text('utf-8'))
    catalog = Catalog(Path(runtime))
    evidence_path = ROOT / '.local/anno-batch4-research/official-index.json'
    if require_snapshots and not evidence_path.exists():
        raise ValueError('缺少本轮官方页面快照索引，不能声称完成来源复核')
    evidence = json.loads(evidence_path.read_text('utf-8')) if evidence_path.exists() else None
    added = [row for row in rows if row['outcome'] == 'reviewed-added']
    assert len(added) == expected, (len(added), expected)
    if expected == 100:
        assert len(rows) == 119
        assert sum(row['outcome'] == 'skip-existing-reviewed' for row in rows) == 19
    for row in added:
        code = int(row['code'])
        card = catalog.cards[code]
        entry = document['cards'][str(code)]
        proof = evidence[str(code)] if evidence is not None else None
        assert row['local_name'] == card['name']
        assert int(row['local_type']) == card['type']
        assert int(row['official_cid']) > 0
        assert entry['review']['status'] == 'reviewed' and entry['review']['origin'] == 'manual'
        assert entry['frozen_text'] == card['desc'] and entry['text_digest'] == digest(card['desc'])
        assert {part['key'] for part in segments(card['desc'], card['type'])} == {part['key'] for part in entry['effects']}
        if proof is not None:
            assert int(row['official_cid']) == proof['cid']
            assert proof['official_text'] == proof['faq_text'] and proof['supplement']
        assert all(urlparse(src['url']).hostname == 'www.db.yugioh-card.com' and src['format'] == 'OCG'
                   for src in entry['sources'])
        refs = {src['id'] for src in entry['sources']}
        assert all(set(note['source_refs']) <= refs for effect in entry['effects'] for note in effect['notes'])
    fake = SimpleNamespace(catalog=catalog, library=SimpleNamespace(builtins=builtin_tags(Path(runtime))),
                           root=ROOT / '.local/anno-batch4-readonly-empty')
    service = CardAnnotations(fake, lambda _: None, lambda *_: None, lambda: '2026-09-25')
    assert service.overview()['annotated_total'] == len(document['cards'])
    if expected == 100:
        for series_id in ('set:1d5', 'set:16b', 'set:172', 'set:119', 'set:12c'):
            assert all(service.view(code)['status'] == 'reviewed' and service.view(code)['full']
                       for code in service.series.members[series_id]), series_id

    def hits(code, **condition):
        result = service.search({'q': str(code), **condition})
        return {hit['key'] for item in result['cards'] if item['code'] == code for hit in item['hits']}

    if expected >= 20:
        assert hits(15665977, cost_kind='banish') == {'m3'}
        assert not hits(15665977, action='banish')  # cost is not effect removal
        assert hits(65681983, action='negate_effect') == {'m1'}
        assert not hits(65681983, action='negate_activation')
        assert hits(43904702, action='banish', from_zone='extra') == {'m2'}
        assert not hits(43904702, action='banish', from_zone='deck')
        assert hits(56495147, cost_kind='banish') == {'m1'}
        assert not hits(56495147, action='banish')
        assert hits(56495147, action='send_grave', from_zone='deck') == {'m2'}
        assert hits(62849088, action='choose_branch') == {'m2'}
        branch = document['cards']['62849088']['effects'][2]['structure']['processing'][0]['branches']
        assert [b['actions'][0]['action'] for b in branch] == ['special_summon', 'draw', 'destroy']
    if expected >= 40:
        assert hits(52335937, action='discard_hand') == {'m1'}
        assert not hits(52335937, cost_kind='discard')  # discard follows search during resolution
        assert hits(77675029, action='change_effect') == {'m2'}
        assert not hits(77675029, action='negate_effect')
        assert not hits(77675029, cost_kind='detach_material')
        assert hits(77675029, action='detach_material') == {'m2'}
        assert hits(59242458, action='return_deck', from_zone='xyz_material') == {'m3'}
        assert not hits(59242458, action='return_deck', from_zone='grave')
        assert document['cards']['42741437']['text_digest'] == document['cards']['42741438']['text_digest']
        assert document['cards']['42741438']['code'] != document['cards']['42741437']['code']
    if expected >= 60:
        assert hits(20788863, cost_kind='discard') == {'m1', 'm2'}
        assert hits(20788863, action='send_grave') == {'m1'}
        assert not hits(20788863, action='discard_hand')
        assert hits(14934922, action='choose_branch') == {'m1'}
        branch = document['cards']['14934922']['effects'][1]['structure']['processing'][0]['branches']
        assert len(branch) == 2 and '费用' in branch[0]['condition'] and '无送墓费用' in branch[1]['condition']
        assert hits(38784726, action='use_as_ritual_material') == {'m1'}
        assert not hits(38784726, cost_kind='tribute')
        assert hits(28534130, action='negate_effect') == {'m1'}
        assert hits(28534130, cost_kind='banish_self_from_grave') == {'m2'}
    if expected >= 80:
        assert hits(53490455, cost_kind='send_grave_self') == {'m1'}
        assert not hits(53490455, action='send_grave')
        assert hits(57357130, action='return_deck', from_zone='grave') == {'m2'}
        assert hits(57357130, action='special_summon', to_zone='opponent_monster') == {'m2'}
        assert not hits(57357130, cost_kind='return_deck')
        assert hits(71861848, timing='end_phase') == {'m1'}
        assert hits(84755744, action='modify_summon_material') == {'m2'}
        assert not hits(84755744, action='special_summon', timing='condition_text')
        assert hits(88540324, action='grant_piercing') == {'m2'}
        assert not hits(88540324, action='burn')
        assert hits(83533296, action='choose_branch') == {'m1'}
        assert len(document['cards']['83533296']['effects'][1]['structure']['processing'][0]['branches']) == 2
    if expected >= 100:
        assert hits(5041348, action='banish') == {'m1'}
        assert not hits(5041348, action='negate_activation')
        assert not hits(5041348, action='negate_effect')
        assert hits(21834870, action='negate_activation') == {'m1'}
        assert not hits(21834870, action='negate_effect')
        assert hits(52854600, action='lose_lp') == {'m2'}
        assert not hits(52854600, action='burn')
        assert not hits(52854600, cost_kind='lp')
        assert hits(77946022, action='send_grave') == {'m3'}
        assert hits(77946022, action='place_field_spell') == {'m3'}
        assert not hits(77946022, cost_kind='send_grave_self')
        assert hits(89484053, cost_kind='banish_self_from_grave') == {'m2'}
        assert not hits(89484053, action='banish')
        assert all(document['cards'][str(code)]['no_effect'] for code in (5402805, 32519092))
    source_check = 'official snapshots and OCG links' if evidence is not None else 'OCG links; local snapshots unavailable'
    print(f'PASS {len(added)} batch cards: {source_check}, frozen text, full segments, semantic query positives/negatives')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--expected', type=int, required=True)
    parser.add_argument('--require-snapshots', action='store_true')
    args = parser.parse_args()
    check(args.runtime, args.expected, args.require_snapshots)
