import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, atomic_json, safe_child
from report import REPORT_VERSION


class StoreTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / '.local/test-runs'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.root = Path(self.temp.name)
        (self.root/'script').mkdir()
        (self.root/'script/c55144522.lua').write_text('-- synthetic test')
        (self.root/'script/c23995346.lua').write_text('-- synthetic test')
        with closing(sqlite3.connect(self.root/'cards.cdb')) as db:
            db.execute('CREATE TABLE datas(id INTEGER PRIMARY KEY, type INTEGER, level INTEGER, atk INTEGER, def INTEGER)')
            db.execute('CREATE TABLE texts(id INTEGER PRIMARY KEY, name TEXT, desc TEXT,'+','.join(f'str{i} TEXT' for i in range(1,17))+')')
            for code, name, flags in [(55144522,'强欲之壶',2),(1184620,'魔物狩人',17),(23995346,'青眼究极龙',0x41)]:
                db.execute('INSERT INTO datas VALUES(?,?,4,0,0)',(code,flags))
                db.execute('INSERT INTO texts(id,name,desc) VALUES(?,?,?)',(code,name,'测试资料'))
            db.commit()
        self.store=Store(self.root)
        self.deck={'main':[55144522]*20+[1184620]*20,'extra':[23995346],'side':[55144522]}

    def tearDown(self):
        assert self.root.resolve().is_relative_to(Path(__file__).resolve().parents[1] / '.local/test-runs')
        self.temp.cleanup()

    def test_save_reopen_and_overwrite_backup(self):
        first=self.store.save_deck({'name':'验收','deck':self.deck})
        self.assertEqual(self.store.get_deck(first['id'])['deck'],self.deck)
        original=(self.store.decks/'验收.ydk').read_bytes()
        edited={**self.deck,'side':[]}
        self.store.save_deck({**first,'name':'验收','deck':edited})
        self.assertEqual(next((self.store.root/'backups').glob('*.ydk')).read_bytes(),original)
        with self.assertRaises(ValueError): self.store.save_deck({**first,'name':'验收','deck':self.deck})

    def test_existing_deck_is_not_overwritten(self):
        (self.root/'deck').mkdir()
        path=self.root/'deck/original.ydk'; path.write_bytes(self.store.ydk(self.deck))
        before=path.read_bytes()
        with self.assertRaisesRegex(ValueError, '同名'):
            self.store.save_deck({'name':'original','deck':{**self.deck,'side':[]}})
        self.store.save_deck({'name':'original - 练习','deck':{**self.deck,'side':[]}})
        self.assertEqual(path.read_bytes(),before)

    def test_rename_keeps_identifier_order_backup_and_revision(self):
        first = self.store.save_deck({'name': '原名称', 'deck': self.deck})
        original = (self.store.decks / '原名称.ydk').read_bytes()
        edited = {**self.deck, 'side': [1184620, 55144522, 1184620]}
        saved = self.store.save_deck({**first, 'name': '新名称', 'deck': edited})
        self.assertEqual(saved['id'], first['id'])
        reopened = Store(self.root)
        self.assertEqual(reopened.get_deck(first['id']), saved)
        self.assertEqual(saved['name'], '新名称')
        self.assertEqual(saved['deck'], edited)
        self.assertEqual(reopened.list_decks(), [{'id':first['id'], 'name':'新名称', 'source':'library',
            'tag_selection': {'tag_ids': [], 'primary_ids': []}, 'tag_names': {}, 'tag_error': '', 'representatives': [None]*3}])
        self.assertEqual(next((self.store.root/'backups').glob('*.ydk')).read_bytes(), original)
        self.assertEqual(self.store.parse_deck(self.store.ydk(edited, '新名称')), edited)
        with self.assertRaises(ValueError): self.store.save_deck({**first, 'name':'其他名称'})
        other = self.store.save_deck({'name':'其他名称', 'deck':self.deck})
        with self.assertRaisesRegex(ValueError, '同名'): self.store.save_deck({**saved, 'name':other['name']})
        self.assertEqual(self.store.get_deck(saved['id']), saved)
        replacement = self.store.save_deck({'name':'原名称', 'deck':self.deck})
        self.assertNotEqual(replacement['id'], first['id'])
        self.assertEqual(replacement['name'], '原名称')
        self.assertEqual(self.store.get_deck(first['id']), saved)

    def test_representatives_persist_without_changing_deck_and_survive_rename(self):
        saved = self.store.save_deck({'name': '代表卡', 'deck': self.deck,
                                     'representatives': [55144522, 1184620, 23995346]})
        self.assertEqual(saved['deck'], self.deck)
        self.assertEqual(saved['representatives'], [55144522, 1184620, 23995346])
        reopened = Store(self.root)
        self.assertEqual(reopened.list_decks()[0]['representatives'], saved['representatives'])
        renamed = reopened.rename_deck({**saved, 'name': '新代表卡'})
        self.assertEqual(renamed['representatives'], saved['representatives'])
        edited = {**self.deck, 'extra': []}
        resaved = reopened.save_deck({'id': renamed['id'], 'revision': renamed['revision'],
                                     'name': renamed['name'], 'deck': edited})
        self.assertEqual(resaved['representatives'], [55144522, 1184620, None])
        before = reopened.get_deck(resaved['id'])
        for invalid in [[55144522], [True, None, None], [23995346, None, None]]:
            with self.assertRaises(ValueError): reopened.save_deck({**resaved, 'representatives': invalid})
            self.assertEqual(reopened.get_deck(resaved['id']), before)
        with patch('app.atomic_bytes', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): reopened.save_deck({**resaved, 'representatives': [None]*3})
        self.assertEqual(reopened.get_deck(resaved['id']), before)

    def test_legacy_deck_has_empty_representatives_and_settings_are_persistent(self):
        data = self.store.ydk(self.deck, '旧卡组')
        self.assertEqual(self.store.deck_representatives(data, self.deck), [None]*3)
        self.assertEqual(self.store.duel_settings(), {'hand_count': 5})
        self.store.duel_settings({'hand_count': 4})
        self.assertEqual(Store(self.root).duel_settings(), {'hand_count': 4})
        for invalid in [0, 61, 1.5, True, None]:
            with self.assertRaises(ValueError): self.store.duel_settings({'hand_count': invalid})
        self.assertEqual(self.store.duel_settings(), {'hand_count': 4})

    def test_malformed_deck_does_not_block_other_library_tiles(self):
        self.store.save_deck({'name': '有效卡组', 'deck': self.deck})
        (self.store.decks / '损坏卡组.ydk').write_text('#representatives: [55144522, null, null]\n#main\nnot-a-card\n', encoding='utf-8')
        listed = self.store.list_decks()
        self.assertEqual(len(listed), 2)
        self.assertEqual(next(d for d in listed if d['name'] == '损坏卡组')['representatives'], [None]*3)
        with self.assertRaises(ValueError): self.store.get_deck('library/损坏卡组.ydk')

    def test_favorites_persist_and_failed_writes_keep_original(self):
        self.assertEqual(self.store.favorites(), {'cards':[]})
        self.store.set_favorite({'id':55144522, 'favorite':True})
        self.store.set_favorite({'id':1184620, 'favorite':True})
        expected = {'cards':[1184620,55144522]}
        self.assertEqual(Store(self.root).favorites(), expected)
        self.store.set_favorite({'id':1184620, 'favorite':True})
        self.assertEqual(self.store.favorites(), expected)
        with patch('app.atomic_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.set_favorite({'id':55144522, 'favorite':False})
        self.assertEqual(self.store.favorites(), expected)
        self.store.set_favorite({'id':55144522, 'favorite':False})
        self.assertEqual(Store(self.root).favorites(), {'cards':[1184620]})
        for body in ({'id':True,'favorite':True}, {'id':999,'favorite':True}, {'id':1184620,'favorite':'false'}):
            with self.assertRaises(ValueError): self.store.set_favorite(body)
        path = self.store.root/'card-favorites.json'
        path.write_text('corrupt', encoding='utf8')
        with self.assertRaises(ValueError): self.store.set_favorite({'id':1184620,'favorite':False})
        self.assertEqual(path.read_text(), 'corrupt')

    def test_management_rename_preserves_existing_bytes_id_unknown_cards_and_backup(self):
        (self.root/'deck').mkdir()
        path = self.root/'deck/原有.ydk'
        data = b'\xef\xbb\xbf#keep this comment\r\n#main\r\n1184620\r\n55144522\r\n#extra\r\n23995346\r\n!side\r\n99999999\r\n'
        path.write_bytes(data)
        original = self.store.get_deck('existing/原有.ydk')
        renamed = self.store.rename_deck({**original, 'name':'改名的旧卡组'})
        self.assertEqual(renamed['id'], original['id'])
        self.assertEqual(renamed['deck'], original['deck'])
        self.assertEqual(renamed['name'], '改名的旧卡组')
        self.assertEqual(b'\xef\xbb\xbf'+b''.join(path.read_bytes()[3:].splitlines(keepends=True)[1:]), data)
        self.assertEqual(next((self.store.root/'backups').glob('*.ydk')).read_bytes(), data)
        self.assertEqual(Store(self.root).get_deck(renamed['id']), renamed)
        self.assertEqual(Store(self.root).list_decks()[0]['name'], renamed['name'])
        before = path.read_bytes()
        with self.assertRaises(ValueError): self.store.rename_deck({**original, 'name':'过期改名'})
        with patch('app.atomic_bytes', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.rename_deck({**renamed, 'name':'失败改名'})
        self.assertEqual(path.read_bytes(), before)
        other = self.store.save_deck({'name':'其他卡组', 'deck':self.deck})
        with self.assertRaisesRegex(ValueError, '同名'): self.store.rename_deck({**renamed, 'name':other['name']})
        final = self.store.rename_deck({**renamed, 'name':'再次改名'})
        self.assertEqual(path.read_bytes().count(b'#name: '),1)
        self.assertEqual(final['deck'], original['deck'])

    def test_name_search_filters_and_favorites_intersect_before_pagination(self):
        catalog = self.store.catalog
        catalog.cards[1184620].update(attribute=32, race=1, level=4)
        self.assertEqual(catalog.search('测试资料')['total'], 3)  # legacy API remains searchable by effect
        self.assertEqual(catalog.search('测试资料', name_only=True)['total'], 0)
        result = catalog.search('魔物', 'monster', name_only=True, favorites={1184620}, attribute='32', race='1', level='4')
        self.assertEqual([c['id'] for c in result['cards']], [1184620])
        self.assertEqual(catalog.search('魔物','spell',favorites={1184620})['total'], 0)
        self.assertEqual(catalog.search('',favorites=set())['total'], 0)
        self.assertEqual(catalog.search('魔物',attribute='16')['total'], 0)
        self.assertEqual(catalog.search('魔物',race='2')['total'], 0)
        self.assertEqual(catalog.search('魔物',level='8')['total'], 0)
        self.assertEqual(catalog.search('魔物',offset=60,favorites={1184620})['total'], 1)
        self.assertEqual(catalog.search('魔物',offset=60,favorites={1184620})['cards'], [])

    def test_export_ydk_roundtrip_preserves_saved_name_zones_order_and_source(self):
        saved = self.store.save_deck({'name':'导出测试', 'deck':self.deck})
        before = (self.store.decks/'导出测试.ydk').read_bytes()
        exported = self.store.export_deck(saved['id'])
        self.assertEqual(exported['name'], saved['name'])
        self.assertEqual(self.store.parse_deck(exported['text'].encode('utf8')), self.deck)
        self.assertIn('#main\n', exported['text'])
        self.assertIn('#extra\n', exported['text'])
        self.assertIn('!side\n', exported['text'])
        self.assertEqual((self.store.decks/'导出测试.ydk').read_bytes(), before)
        with self.assertRaises(ValueError): self.store.export_deck('library/../../outside.ydk')

    def test_path_unknown_id_and_extra_zone_validation(self):
        with self.assertRaises(ValueError): safe_child(self.root,'../outside')
        with self.assertRaises(ValueError): self.store.save_deck({'name':'../escape','deck':self.deck})
        with self.assertRaises(ValueError): self.store.validate({**self.deck,'main':[99999999]})
        with self.assertRaises(ValueError): self.store.validate({**self.deck,'main':[23995346]*40},True)
        with self.assertRaises(ValueError): self.store.validate({**self.deck,'main':[55144522]},True)
        self.store.validate(self.deck,True)

    def test_delete_deck_verifies_revision_and_retains_backup_and_history(self):
        saved = self.store.save_deck({'name': '可删除构筑', 'deck': self.deck})
        sid, session = self.session('manual')
        journal = (session / 'native.jsonl').read_bytes()
        before = (self.store.decks / '可删除构筑.ydk').read_bytes()
        with self.assertRaises(ValueError):
            self.store.delete_deck({'id': saved['id'], 'revision': 'stale'})
        self.assertTrue((self.store.decks / '可删除构筑.ydk').exists())
        result = self.store.delete_deck(saved)
        self.assertFalse((self.store.decks / '可删除构筑.ydk').exists())
        self.assertEqual((self.store.root / result['backup'] / 'deck.ydk').read_bytes(), before)
        self.assertEqual((session / 'native.jsonl').read_bytes(), journal)
        self.assertNotIn(saved['id'], [d['id'] for d in self.store.list_decks()])

    def test_delete_existing_copy_is_scoped_and_active_training_is_protected(self):
        (self.root / 'deck').mkdir()
        original = self.root / 'deck/原有构筑.ydk'
        original.write_bytes(self.store.ydk(self.deck))
        selected = self.store.get_deck('existing/原有构筑.ydk')
        sid, session = self.session()
        meta = json.loads((session / 'session.json').read_text('utf8'))
        meta['selected_deck'] = selected['id']
        atomic_json(session / 'session.json', meta)
        with patch('app.process_identity', return_value={'created': 5}):
            with self.assertRaisesRegex(ValueError, '正在训练'):
                self.store.delete_deck(selected)
        self.assertTrue(original.exists())
        with patch('app.process_identity', return_value=None):
            result = self.store.delete_deck(selected)
        self.assertEqual((self.store.root / result['backup'] / 'deck.ydk').read_bytes(), self.store.ydk(self.deck))
        with self.assertRaises(ValueError):
            self.store.delete_deck({'id': 'existing/../../outside.ydk', 'revision': ''})

    def session(self, end=None, pid=123):
        sid=str(uuid.uuid4()); p=self.store.session_path(sid); p.mkdir()
        meta={'id':sid,'name':'测试','started_ms':1,'status':'running','pid':pid,'process_identity':{'created':5},'deck':self.deck,'catalog':{}}
        atomic_json(p/'session.json',meta)
        rows=[{'session':sid,'seq':1,'time_ms':2,'kind':'begin'}]
        if end: rows.append({'session':sid,'seq':2,'time_ms':3,'kind':'end','reason':end})
        (p/'native.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf8')
        return sid,p

    def test_manual_end_and_crash_are_distinct(self):
        manual,p=self.session('manual'); crashed,q=self.session()
        with patch('app.process_identity',return_value=None): self.store.refresh()
        self.assertEqual(json.loads((p/'session.json').read_text())['status'],'completed')
        self.assertEqual(json.loads((q/'session.json').read_text())['status'],'interrupted')
        self.assertEqual(self.store.report(crashed)['end_reason'],'native_exit_without_end')

    def test_restart_reattaches_and_reused_pid_is_not_alive(self):
        sid,p=self.session()
        with patch('app.process_identity',return_value={'created':5}):
            reopened=Store(self.root)
            self.assertEqual(reopened.history()[0]['status'],'running')
            with self.assertRaises(ValueError): reopened.start('library/unused.ydk')
        with patch('app.process_identity',return_value={'created':6}): reopened.refresh()
        self.assertEqual(json.loads((p/'session.json').read_text())['status'],'interrupted')

    def test_report_upgrade_preserves_source_and_original_report(self):
        sid,p=self.session('manual')
        with patch('app.process_identity',return_value=None): self.store.refresh()
        originals={f:hashlib.sha256((p/f).read_bytes()).hexdigest() for f in ['native.jsonl','session.json','report.json']}
        new=self.store.report(sid)
        self.assertIn('actions',new)
        self.assertTrue((p/f'report-v{REPORT_VERSION}.json').exists())
        for f,digest in originals.items(): self.assertEqual(hashlib.sha256((p/f).read_bytes()).hexdigest(),digest)

    def test_v5_battle_report_reopens_with_filtered_steps_and_preserves_old_files(self):
        sid, p = self.session('manual')
        with patch('app.process_identity', return_value=None): self.store.refresh()
        payload = bytes([110]) + bytes(8) + bytes([113, 111]) + bytes(26) + bytes([91, 1, 58, 7, 0, 0, 114])
        state = {'cards': [], 'turn': 3, 'phase': 8, 'lp': [8000, 6150]}
        row = {'session': sid, 'seq': 1, 'time_ms': 2, 'kind': 'batch', 'raw': payload.hex(), 'state': state}
        (p / 'native.jsonl').write_text(json.dumps(row) + '\n', encoding='utf8')
        (p / 'deck.ydk').write_bytes(self.store.ydk(self.deck))
        atomic_json(p / 'report-v5.json', {'report_version': 5, 'actions': [{'summary': '攻击宣言'}]})
        files = ['native.jsonl', 'session.json', 'deck.ydk', 'report.json', 'report-v5.json']
        originals = {name: (p / name).read_bytes() for name in files}
        upgraded = self.store.report(sid)
        self.assertEqual(upgraded['report_version'], REPORT_VERSION)
        self.assertEqual(upgraded['actions'], [])
        self.assertEqual(upgraded['statistics']['展开步骤'], 0)
        self.assertEqual(len(upgraded['events']), 5)
        self.assertEqual(upgraded, Store(self.root).report(sid))
        for name, content in originals.items(): self.assertEqual((p / name).read_bytes(), content)


if __name__=='__main__': unittest.main()
