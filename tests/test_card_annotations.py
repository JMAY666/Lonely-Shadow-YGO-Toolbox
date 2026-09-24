import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, read_json, now
from card_annotations import CardAnnotations, Registry, draft_entry, segments

SEARCHER = '①：从卡组把1只「测试」怪兽加入手卡。'
RECYCLER = '①：以自己墓地1只「测试」怪兽为对象才能发动。那只怪兽加入手卡。'
DUAL = '这个卡名的①②的效果1回合各能使用1次。\n①：从卡组把1只怪兽特殊召唤。这个回合，自己不是怪兽不能特殊召唤。\n②：把对方场上1只怪兽破坏。'
PENDULUM = '「测试灵摆」的灵摆效果1回合只能使用1次。\n①：从卡组把1只「测试」怪兽加入手卡。\n【怪兽效果】\n①：把这张卡破坏，从卡组把1只怪兽特殊召唤。'
FLAVOR = '用于测试的通常怪兽，没有任何效果文本。'

CARDS = [
    (20000001, 2, 0, SEARCHER),
    (20000002, 2, 0, RECYCLER),
    (20000003, 0x21, 0x1d5, DUAL),
    (20000004, 0x1000021, 0xaf, PENDULUM),
    (20000005, 0x11, 0, FLAVOR),
]


def make_entry(code, desc, effects, **extra):
    return {'code': code,
            'text_digest': hashlib.sha256(desc.replace('\r\n', '\n').strip().encode()).hexdigest(),
            'review': {'status': 'reviewed', 'origin': 'manual', 'checked_on': '2026-09-24', 'basis': '测试标注'},
            'frozen_text': desc, 'effects': effects, 'relations': [], 'notes': [], **extra}


def simple_effect(key, number, tags, processing, usage=()):
    return {'key': key, 'kind': 'numbered', 'number': number, 'tags': list(tags),
            'structure': {'activation': {'timing': 'manual', 'zones': ['hand'], 'conditions': [], 'fast_effect': False},
                          'cost': [], 'targeting': [], 'processing': processing, 'usage': list(usage)},
            'notes': []}


class CardAnnotationTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / '.local/test-runs'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.root = Path(self.temp.name)
        (self.root / 'script').mkdir()
        with closing(sqlite3.connect(self.root / 'cards.cdb')) as db:
            db.execute('CREATE TABLE datas(id INTEGER PRIMARY KEY, ot INTEGER, alias INTEGER, setcode INTEGER, type INTEGER, atk INTEGER, def INTEGER, level INTEGER, race INTEGER, attribute INTEGER, category INTEGER)')
            db.execute('CREATE TABLE texts(id INTEGER PRIMARY KEY, name TEXT, desc TEXT, str1 TEXT, str2 TEXT, str3 TEXT, str4 TEXT, str5 TEXT, str6 TEXT, str7 TEXT, str8 TEXT, str9 TEXT, str10 TEXT, str11 TEXT, str12 TEXT, str13 TEXT, str14 TEXT, str15 TEXT, str16 TEXT)')
            for code, card_type, setcode, desc in CARDS:
                db.execute('INSERT INTO datas VALUES(?,?,?,?,?,0,0,1,1,1,0)', (code, 0, 0, setcode, card_type))
                db.execute('INSERT INTO texts(id,name,desc) VALUES(?,?,?)', (code, f'测试卡{code}', desc))
            db.commit()
        self.store = Store(self.root)
        self.curated_path = self.root / 'curated-annotations.json'
        self.write_curated()
        self.service = CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)

    def tearDown(self):
        assert self.root.resolve().is_relative_to(Path(__file__).resolve().parents[1] / '.local/test-runs')
        self.temp.cleanup()

    def write_curated(self, mutate=None):
        entries = {
            '20000001': make_entry(20000001, SEARCHER, [
                simple_effect('m1', 1, ['etag:add-hand'],
                              [{'action': 'add_hand', 'count': '1', 'from_zones': ['deck'], 'to_zones': ['hand'],
                                'selector': {'text': '1只「测试」怪兽'}}])]),
            '20000002': make_entry(20000002, RECYCLER, [
                simple_effect('m1', 1, ['etag:add-hand'],
                              [{'action': 'add_hand', 'count': '1', 'from_zones': ['grave'], 'to_zones': ['hand'],
                                'selector': {'text': '对象怪兽'}}])]),
            '20000003': make_entry(20000003, DUAL, [
                {'key': 'm-pre', 'kind': 'unnumbered', 'number': None, 'tags': [], 'structure': {}, 'notes': []},
                simple_effect('m1', 1, ['etag:special-summon', 'etag:lock'],
                              [{'action': 'special_summon', 'count': '1', 'from_zones': ['deck'], 'to_zones': ['monster'],
                                'selector': {'text': '1只怪兽'},
                                'restrictions': ['这个回合，自己不是怪兽不能特殊召唤']}], ['per_effect_name_soft_opt']),
                simple_effect('m2', 2, ['etag:destroy'],
                              [{'action': 'destroy', 'count': '1', 'selector': {'text': '对方场上1只怪兽'}}],
                              ['per_effect_name_soft_opt'])],
                relations=[{'kind': 'usage_limit_group', 'effects': ['m1', 'm2'], 'text': '这个卡名的①②的效果1回合各能使用1次。'}]),
            '20000005': make_entry(20000005, FLAVOR, [], no_effect=True),
        }
        if mutate: mutate(entries)
        document = {'version': 1, 'id': 'test-annotations', 'title': '测试标注', 'checked_on': '2026-09-24',
                    'verified_against': {}, 'cards': entries}
        self.curated_path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')

    def test_segments_cover_pre_numbered_pendulum_and_ambiguous(self):
        self.assertEqual([s['key'] for s in segments(DUAL, 0x21)], ['m-pre', 'm1', 'm2'])
        pendulum = segments(PENDULUM, 0x1000021)
        self.assertEqual([s['key'] for s in pendulum], ['p-pre', 'p1', 'm1'])
        self.assertEqual([s['block'] for s in pendulum], ['p', 'p', 'm'])
        self.assertEqual([s['key'] for s in segments(FLAVOR, 0x11)], ['m-all'])
        ambiguous = segments('①：效果。①：重复编号。', 0x21)
        self.assertEqual([s['kind'] for s in ambiguous], ['ambiguous'])

    def test_same_tag_keeps_source_zone_difference(self):
        by_deck = self.service.search({'etags': ['etag:add-hand'], 'from_zone': 'deck'})
        by_grave = self.service.search({'etags': ['etag:add-hand'], 'from_zone': 'grave'})
        self.assertEqual([c['code'] for c in by_deck['cards']], [20000001])
        self.assertEqual([c['code'] for c in by_grave['cards']], [20000002])
        both = self.service.search({'etags': ['etag:add-hand']})
        self.assertEqual(both['total'], 2)
        evidence = both['cards'][0]['hits'][0]['evidence']
        self.assertTrue(any(item['condition'] == 'tag' for item in evidence))

    def test_conditions_do_not_cross_effects(self):
        strict = self.service.search({'etags': ['etag:special-summon', 'etag:destroy'], 'etag_mode': 'all'})
        self.assertEqual(strict['total'], 0)
        loose = self.service.search({'etags': ['etag:special-summon', 'etag:destroy'], 'etag_mode': 'all', 'scope': 'card'})
        self.assertEqual(loose['total'], 1)
        self.assertTrue(loose['cards'][0]['cross_effects'])
        self.assertEqual(sorted(loose['cards'][0]['hit_keys']), ['m1', 'm2'])

    def test_unknown_cards_are_not_negatives(self):
        result = self.service.search({'etags': ['etag:add-hand']})
        self.assertEqual(result['catalog_total'], len(CARDS))
        self.assertEqual(result['annotated_total'], 4)  # 20000004 stays unannotated, never returned.
        self.assertNotIn(20000004, [card['code'] for card in result['cards']])
        only_none = self.service.search({'etags': ['etag:add-hand'], 'status': ['none']})
        self.assertEqual(only_none['total'], 0)

    def test_usage_and_action_filters(self):
        locked = self.service.search({'etags': ['etag:special-summon'], 'usage': 'per_effect_name_soft_opt'})
        self.assertEqual([c['code'] for c in locked['cards']], [20000003])
        destroyed = self.service.search({'action': 'destroy'})
        self.assertEqual([c['code'] for c in destroyed['cards']], [20000003])
        self.assertEqual(destroyed['cards'][0]['hits'][0]['key'], 'm2')

    def test_overview_counts_full_and_partial(self):
        overview = self.service.overview()
        self.assertEqual(overview['statuses']['reviewed'], 4)
        self.assertEqual(overview['statuses']['none'], 1)
        self.assertEqual(overview['annotated_total'], 4)
        self.write_curated(mutate=lambda entries: entries['20000003']['effects'].pop(0))
        self.service.reload()
        self.assertEqual(self.service.overview()['statuses']['partial'], 1)

    def test_digest_mismatch_marks_stale_and_keeps_entry(self):
        view = self.service.view(20000001)
        self.assertEqual(view['status'], 'reviewed')
        with closing(sqlite3.connect(self.root / 'cards.cdb')) as db:
            db.execute('UPDATE texts SET desc=? WHERE id=?', (SEARCHER + '卡文已改动。', 20000001))
            db.commit()
        self.store.reload_resources()
        self.service.reload()
        view = self.service.view(20000001)
        self.assertEqual(view['status'], 'stale')
        self.assertFalse(view['digest_ok'])
        self.assertTrue(view['effects'][0]['annotated'], '旧标注按冻结文本保留')
        fresh = self.service.search({'etags': ['etag:add-hand'], 'status': ['reviewed']})
        self.assertNotIn(20000001, [card['code'] for card in fresh['cards']])

    def test_draft_flow_and_review_statuses(self):
        made = self.service.command({'op': 'draft', 'code': 20000004})
        self.assertEqual(made['origin'], 'auto')
        view = self.service.view(20000004)
        self.assertEqual(view['status'], 'auto')
        self.assertTrue(all(effect.get('notes') for effect in view['effects'] if effect.get('annotated')))
        self.assertEqual(self.service.overview()['statuses']['auto'], 1)
        revision = made['revision']
        with self.assertRaises(ValueError):
            self.service.command({'op': 'set-review', 'code': 20000004, 'value': 'confirmed', 'revision': revision})
        pending = self.service.command({'op': 'set-review', 'code': 20000004, 'value': 'pending', 'revision': revision})
        self.assertEqual(pending['status'], 'pending')
        with self.assertRaises(ValueError):
            self.service.command({'op': 'set-review', 'code': 20000004, 'value': None, 'revision': revision})
        noted = self.service.command({'op': 'add-note', 'code': 20000004, 'key': 'p1', 'text': '人工核对备注', 'revision': revision + 1})
        self.assertEqual(noted['revision'], revision + 2)
        view = self.service.view(20000004)
        self.assertTrue(any(note['text'] == '人工核对备注' for effect in view['effects'] for note in effect.get('notes', [])))
        discarded = self.service.command({'op': 'discard-draft', 'code': 20000004, 'revision': revision + 2})
        self.assertEqual(discarded['revision'], revision + 3)
        self.assertEqual(self.service.view(20000004)['status'], 'none')

    def test_tag_overrides_apply_and_can_be_undone(self):
        revision = self.service.document['revision']
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': ['etag:draw'], 'remove': [], 'revision': revision})
        view = self.service.view(20000002)
        self.assertIn('etag:draw', view['effects'][0]['tags'])
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': [], 'remove': ['etag:draw'], 'revision': revision + 1})
        self.assertNotIn('etag:draw', self.service.view(20000002)['effects'][0]['tags'])
        self.assertIn('etag:add-hand', self.service.view(20000002)['effects'][0]['tags'])

    def test_invalid_curated_data_fails_closed(self):
        self.write_curated(mutate=lambda entries: entries['20000001']['effects'][0]['tags'].append('etag:not-registered'))
        with self.assertRaises(ValueError):
            CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)
        self.write_curated(mutate=lambda entries: entries['20000001']['effects'][0].update(key='m9'))
        with self.assertRaises(ValueError):
            CardAnnotations(self.store, read_json, atomic_json, now, curated_path=self.curated_path)

    def test_browsing_includes_no_effect_and_unknown_only_when_requested(self):
        regular = self.service.search({})
        self.assertIn(20000005, [card['code'] for card in regular['cards']])
        self.assertTrue(all(not card['cross_effects'] for card in regular['cards']))
        unknown = self.service.search({'catalog_scope': 'all', 'status': ['none']})
        self.assertEqual([card['code'] for card in unknown['cards']], [20000004])
        self.assertEqual(self.service.search({'status': []})['total'], 0)

    def test_stale_text_is_not_rebound_and_never_matches_abilities(self):
        self.service.command({'op': 'add-note', 'code': 20000001, 'key': 'm1', 'text': '保留备注', 'revision': 1})
        self.store.catalog.cards[20000001]['desc'] = '①：把场上1张卡破坏。'
        self.service.reload()
        view = self.service.view(20000001)
        self.assertEqual(view['effects'][0]['text'], SEARCHER)
        self.assertNotEqual(view['current_text_digest'], view['text_digest'])
        self.assertIn('保留备注', str(view['effects'][0]['notes']))
        self.assertNotIn(20000001, [card['code'] for card in self.service.search({'etags': ['etag:add-hand']})['cards']])
        self.assertEqual(self.service.search({'status': ['stale']})['total'], 1)

    def test_partial_status_is_consistent_and_tokens_are_not_unannotated(self):
        self.write_curated(mutate=lambda entries: entries['20000003']['effects'].pop(0))
        self.service.reload()
        self.assertEqual(self.service.view(20000003)['status'], 'partial')
        self.assertEqual(self.service.search({'status': ['partial']})['total'], 1)
        self.store.catalog.cards[99999999] = {'name': '测试衍生物', 'type': 0x4011, 'desc': ''}
        overview = self.service.overview()
        self.assertEqual(overview['tokens'], 1)
        self.assertEqual(overview['eligible_total'], 5)
        self.assertEqual(overview['statuses']['none'], 1)
        self.assertEqual(self.service.search({'catalog_scope': 'all'})['total'], 5)

    def test_removed_builtin_tag_can_be_restored(self):
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': [], 'remove': ['etag:add-hand'], 'revision': 1})
        self.assertNotIn('etag:add-hand', self.service.view(20000002)['effects'][0]['tags'])
        self.service.command({'op': 'set-tags', 'code': 20000002, 'key': 'm1', 'add': ['etag:add-hand'], 'remove': [], 'revision': 2})
        self.assertIn('etag:add-hand', self.service.view(20000002)['effects'][0]['tags'])

    def test_registry_rejects_bad_documents(self):
        with self.assertRaises(ValueError):
            Registry({'version': 2})
        with self.assertRaises(ValueError):
            Registry({'version': 1, 'tags': [{'id': 'not-an-etag', 'name': 'x', 'definition': 'y', 'category': 'resource'}],
                      'vocabularies': {'categories': {'resource': '资源'}}})

    def test_snapshot_and_automatic_review_cannot_forge_trust(self):
        self.write_curated(mutate=lambda entries: entries['20000001'].update(frozen_text='不同的卡文'))
        with self.assertRaises(ValueError):
            self.service.reload()
        self.write_curated(mutate=lambda entries: entries['20000001']['review'].update(origin='auto'))
        with self.assertRaises(ValueError):
            self.service.reload()

    def test_draft_entry_records_evidence_only(self):
        entry = draft_entry(20000003, segments(DUAL, 0x21), '0' * 64)
        self.assertEqual(entry['review']['origin'], 'auto')
        self.assertEqual(entry['review']['status'], 'draft')
        keys = {effect['key']: effect for effect in entry['effects']}
        self.assertIn('etag:special-summon', keys['m1']['tags'])
        self.assertIn('etag:destroy', keys['m2']['tags'])
        self.assertTrue(keys['m1']['structure']['processing'][0].get('evidence'))

    def test_folders_apply_effect_filters_and_card_counts_without_changing_personal_data(self):
        before = json.dumps(self.service.document, sort_keys=True)
        query = {'catalog_scope': 'all', 'etags': ['etag:add-hand'], 'from_zone': 'grave'}
        flat = self.service.search(query)
        grouped = self.service.search({**query, 'group_by': 'series'})
        self.assertEqual(grouped['total'], flat['total'])
        for folder in grouped['folders']:
            cards = self.service.search({**query, 'series': folder['id']})
            self.assertEqual(cards['total'], folder['count'])
            self.assertIn(folder['cover_code'], [c['code'] for c in cards['cards']])
        self.assertEqual(json.dumps(self.service.document, sort_keys=True), before)

    def test_unknown_folder_is_rejected_and_catalog_reload_updates_membership(self):
        with self.assertRaises(ValueError):
            self.service.search({'series': 'set:missing'})
        with self.assertRaises(ValueError):
            self.service.search({'series': ['set:dd']})
        with closing(sqlite3.connect(self.root / 'cards.cdb')) as db:
            db.execute('UPDATE datas SET setcode=? WHERE id=?', (0x172, 20000001))
            db.commit()
        self.store.reload_resources()
        self.service.reload()
        view = self.service.view(20000001)
        self.assertEqual(view['series'][0]['name'], '驱魔姐妹')
        self.assertEqual(self.service.search({'q': '救祓少女'})['cards'][0]['code'], 20000001)


if __name__ == '__main__':
    unittest.main()
