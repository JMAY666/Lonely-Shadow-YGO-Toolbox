"""Synthetic packages exercise transactions and compatibility without network or player data."""
from contextlib import closing
import json
import hashlib
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Store, Catalog
from desktop_runtime import write_json, prepare_resources, resource_allowed
import superpre


def database(path, cards):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE datas(id INTEGER PRIMARY KEY,ot INTEGER,alias INTEGER,setcode INTEGER,type INTEGER,atk INTEGER,def INTEGER,level INTEGER,race INTEGER,attribute INTEGER,category INTEGER)')
        db.execute('CREATE TABLE texts(id INTEGER PRIMARY KEY,name TEXT,desc TEXT,' + ','.join(f'str{i} TEXT' for i in range(1, 17)) + ')')
        for code, name in cards:
            db.execute('INSERT INTO datas VALUES(?,3,0,746,33,1000,1000,4,1,1,0)', (code,))
            db.execute('INSERT INTO texts(id,name,desc) VALUES(?,?,?)', (code, name, '合成测试卡效果'))
        db.commit()


class SuperpreTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.local/test-runs'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='superpre-', dir=root)
        self.root = Path(self.temp.name)
        self.runtime = self.root / 'runtime'; self.runtime.mkdir()
        database(self.runtime / 'cards.cdb', [(1, '基础卡'), (2, '旧文本')])
        (self.runtime / 'script').mkdir()
        (self.runtime / 'script/c1.lua').write_text('-- base', encoding='utf-8')
        (self.runtime / 'strings.conf').write_text('!setname 0x2ea 基础系列', encoding='utf-8')
        self.store = Store(self.runtime)
        self.release = {'version': 'test.1', 'updated_ms': 1789430221000, 'checked_ms': 1789430221000,
                        'download_url': superpre.CDN + 'archive/ygopro-super-pre-test.1.ypk'}
        self.package = self.make_package('one', [(2, '补丁修正文本'), (900001, '补丁新增卡')])

    def tearDown(self):
        if self.store.superpre.thread: self.store.superpre.thread.join(10)
        self.temp.cleanup()

    def make_package(self, label, cards):
        db = self.root / (label + '.cdb'); database(db, cards)
        archive = self.root / (label + '.ypk')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.write(db, 'test-release.cdb')
            z.writestr('test-strings.conf', '!setname 0x2ea 补丁系列\n')
            for code, _ in cards:
                z.writestr(f'script/c{code}.lua', '-- ' + label)
                z.writestr(f'pics/{code}.jpg', b'synthetic-image')
        return archive

    def operation(self, action, *, package=None, release=None):
        def download(_url, target, progress):
            shutil.copyfile(package or self.package, target)
            progress('downloading', 'fixture', target.stat().st_size, target.stat().st_size)
        with patch('superpre.fetch_release', return_value=release or self.release), patch('superpre.download_release', side_effect=download):
            self.store.superpre.start(action)
            self.store.superpre.thread.join(10)
            self.assertFalse(self.store.superpre.thread.is_alive())
        result = self.store.superpre.status()
        if action == 'install': self.assertFalse(result['job']['error'], result['job']['error'])
        return result

    def test_install_update_uninstall_and_reinstall_preserve_data_and_refresh_resources(self):
        saved = self.store.root / 'plans/saved.json'; saved.write_bytes(b'{"frozen":"unchanged"}')
        player = self.runtime / 'deck/personal.ydk'; player.parent.mkdir(); player.write_bytes(b'#main\n900001\n')
        original_db = (self.runtime / 'cards.cdb').read_bytes()
        initial_scripts = self.store.compromise.script_identity()
        state = self.operation('install')
        self.assertFalse(state['job']['error'], state['job']['error'])
        self.assertEqual(state['installed']['card_count'], 2)
        self.assertEqual(self.store.catalog.cards[2]['name'], '补丁修正文本')
        self.assertTrue(self.store.catalog.cards[900001]['script_available'])
        self.assertEqual(self.store.library.builtins['set:2ea']['name'], '补丁系列')
        self.assertNotEqual(self.store.compromise.script_identity(), initial_scripts)
        self.assertEqual(Store(self.runtime).catalog.cards[900001]['name'], '补丁新增卡')
        generation = superpre.resource_root(self.runtime)
        self.assertTrue((generation / 'pics/900001.jpg').exists())

        newer = self.make_package('two', [(2, '更新后的文本'), (900002, '替换后的新卡')])
        latest = {**self.release, 'version': 'test.2', 'updated_ms': self.release['updated_ms'] + 1000,
                  'download_url': superpre.CDN + 'archive/ygopro-super-pre-test.2.ypk'}
        self.assertTrue(self.operation('check', release=latest)['update_available'])
        state = self.operation('update', package=newer, release=latest)
        self.assertFalse(state['job']['error'], state['job']['error'])
        self.assertNotIn(900001, self.store.catalog.cards)
        self.assertEqual(self.store.catalog.cards[900002]['name'], '替换后的新卡')
        self.assertFalse(state['update_available'])
        self.assertTrue(generation.exists(), 'Previous package remains available for recovery')
        self.assertIsNone(self.operation('uninstall')['installed'])
        self.assertEqual(self.store.catalog.cards[2]['name'], '旧文本')
        self.assertNotIn(900002, self.store.catalog.cards)
        self.assertEqual(self.store.compromise.script_identity(), initial_scripts)
        self.assertFalse(superpre.archive_path(self.runtime).exists())
        self.assertEqual((self.runtime / 'cards.cdb').read_bytes(), original_db)
        self.assertEqual(player.read_bytes(), b'#main\n900001\n')
        self.assertEqual(saved.read_bytes(), b'{"frozen":"unchanged"}')
        self.assertFalse(self.operation('install')['job']['error'])

    def test_failed_update_and_crash_recovery_restore_the_previous_generation(self):
        self.operation('install')
        before = superpre.installed_metadata(self.runtime)
        old_bytes = superpre.archive_path(self.runtime).read_bytes()
        newer = self.make_package('two', [(900002, '另一张卡')])
        reload = self.store.reload_resources
        with patch.object(self.store, 'reload_resources', side_effect=[OSError('simulated failure'), None]):
            state = self.operation('update', package=newer)
        reload()
        self.assertIn('simulated failure', state['job']['error'])
        self.assertEqual(superpre.archive_path(self.runtime).read_bytes(), old_bytes)
        self.assertEqual(superpre.installed_metadata(self.runtime), before)
        self.assertIn(900001, self.store.catalog.cards)

        # Crash between archive replacement and metadata update, including an uninstall.
        write_json(self.store.superpre.root / 'transaction.json', {'previous': before, 'next': None})
        superpre.archive_path(self.runtime).unlink()
        recovered = Store(self.runtime)
        self.assertEqual(recovered.catalog.cards[900001]['name'], '补丁新增卡')
        self.assertEqual(superpre.archive_path(self.runtime).read_bytes(), old_bytes)
        self.assertFalse((self.store.superpre.root / 'transaction.json').exists())

    def test_bad_packages_and_external_conflicts_do_not_change_active_resources(self):
        self.operation('install')
        before = superpre.archive_path(self.runtime).read_bytes()
        broken = self.root / 'broken.ypk'; broken.write_bytes(b'partial download')
        self.assertTrue(self.operation('update', package=broken)['job']['error'])
        self.assertEqual(superpre.archive_path(self.runtime).read_bytes(), before)
        superpre.archive_path(self.runtime).write_bytes(b'external edit')
        self.assertIn('外部修改', self.operation('uninstall')['job']['error'])
        self.assertEqual(superpre.archive_path(self.runtime).read_bytes(), b'external edit')

    def test_failed_rollback_blocks_new_engines_and_keeps_the_recovery_journal(self):
        self.operation('install')
        newer = self.make_package('two', [(900002, '另一张卡')])
        with patch.object(self.store, 'reload_resources', side_effect=OSError('disk full')), \
                patch.object(self.store.superpre, 'recover', side_effect=OSError('restore denied')):
            self.assertIn('restore denied', self.operation('update', package=newer)['job']['error'])
        self.assertTrue((self.store.superpre.root / 'transaction.json').exists())
        with self.assertRaisesRegex(ValueError, '恢复尚未完成'): self.store.superpre.start('uninstall')
        with self.assertRaisesRegex(ValueError, '补丁正在变更'): self.store.start('missing')
        recovered = Store(self.runtime)
        self.assertIn(900001, recovered.catalog.cards)
        self.assertNotIn(900002, recovered.catalog.cards)

    def test_network_failure_keeps_local_install_and_last_known_release(self):
        self.operation('install')
        with patch('superpre.fetch_release', side_effect=OSError('offline')):
            self.store.superpre.start('check'); self.store.superpre.thread.join(10)
        state = self.store.superpre.status()
        self.assertIn('offline', state['job']['error'])
        self.assertEqual(state['latest']['version'], 'test.1')
        self.assertTrue(self.store.catalog.cards[900001]['script_available'])

    def test_desktop_base_resource_upgrade_preserves_managed_patch(self):
        self.operation('install')
        archive = superpre.archive_path(self.runtime)
        before = archive.read_bytes()
        upgraded = self.root / 'upgraded-base.cdb'
        database(upgraded, [(1, '新版基础卡'), (2, '新版基础文本')])
        payload = upgraded.read_bytes()
        files = {'cards.cdb': {'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}}
        manifest = {'schema': 1, 'version': hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), 'files': files}
        bundle = self.root / 'base-resources.zip'
        with zipfile.ZipFile(bundle, 'w') as z:
            z.writestr('cards.cdb', payload)
            z.writestr('bundle-manifest.json', json.dumps(manifest))
        prepare_resources(bundle, self.runtime)
        current = Store(self.runtime)
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(current.catalog.cards[1]['name'], '新版基础卡')
        self.assertEqual(current.catalog.cards[2]['name'], '补丁修正文本')
        self.assertIn(900001, current.catalog.cards)
        self.assertFalse(resource_allowed('expansions/' + superpre.ARCHIVE_NAME))
        self.assertFalse(resource_allowed('_trainer/patches/superpre/generations/example/files/test.cdb'))

    def test_active_engine_planning_and_duplicate_operations_are_blocked(self):
        self.store.processes['engine'] = Mock(poll=Mock(return_value=None))
        with self.assertRaisesRegex(ValueError, '先结束'): self.store.superpre.start('install')
        self.store.processes.clear()
        with self.store.modular.planning_lock:
            with self.assertRaisesRegex(ValueError, '先结束'): self.store.superpre.start('install')
        release_gate = threading.Event()
        def metadata():
            release_gate.wait(5)
            return self.release
        try:
            with patch('superpre.fetch_release', side_effect=metadata):
                self.store.superpre.start('install')
                with self.assertRaisesRegex(ValueError, '正在进行'): self.store.superpre.start('check')
                with self.assertRaisesRegex(ValueError, '补丁正在变更'): self.store.start('missing')
                with patch('superpre.download_release', side_effect=OSError('fixture cancelled')):
                    release_gate.set(); self.store.superpre.thread.join(10)
        finally: release_gate.set()
        self.assertFalse(self.store.superpre.mutating)
        self.assertTrue(self.store.modular.planning_lock.acquire(blocking=False))
        self.store.modular.planning_lock.release()

    def test_projection_tampering_and_unknown_archives_are_not_silently_loaded(self):
        self.operation('install')
        root = superpre.resource_root(self.runtime)
        (root / 'script/c900001.lua').write_text('-- external mutation')
        with self.assertRaisesRegex(ValueError, '副本校验失败'): Catalog(self.runtime)
        (self.runtime / 'expansions/unmanaged.ypk').write_bytes(b'unknown')
        self.assertIn('其他扩展', self.operation('uninstall')['job']['error'])

    def test_zip_traversal_duplicates_native_format_and_schema_are_rejected(self):
        for member in ('../outside.lua', '/absolute.lua', 'script/../../outside.lua', 'script/CON.lua', 'script/evil.exe', 'script/c1.lua:stream'):
            with self.subTest(member=member):
                with self.assertRaises(ValueError): superpre.validate_member(member)
        for label, entries in [('duplicate', [('script/c1.lua', b'a'), ('SCRIPT/C1.LUA', b'b')]),
                               ('database', [('test.cdb', b'invalid sqlite')])]:
            archive = self.root / (label + '.ypk')
            with zipfile.ZipFile(archive, 'w') as z:
                for name, data in entries: z.writestr(name, data)
            with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                superpre.inspect_archive(archive, self.root / (label + '-files'))

    def test_official_metadata_and_download_hosts_are_checked(self):
        mirrored = self.release['download_url'].replace('cdntx.', 'cdncf.')
        self.assertEqual(superpre.validate_url(mirrored, archive=True), mirrored)
        with patch('superpre.remote_text', side_effect=['1789430221', self.release['download_url']]):
            release = superpre.fetch_release()
        self.assertEqual(release['updated_ms'], 1789430221000)
        self.assertEqual(release['version'], 'test.1')
        for url in ('http://cdntx.moecube.com/ygopro-super-pre/archive/ygopro-super-pre.ypk',
                    'https://example.com/ygopro-super-pre/archive/ygopro-super-pre.ypk',
                    'https://cdntx.moecube.com/ygopro-super-pre/archive/other.exe'):
            with self.assertRaises(ValueError): superpre.validate_url(url, archive=True)
        with patch('superpre.remote_text', return_value='<html>unavailable</html>'):
            with self.assertRaises(ValueError): superpre.fetch_release()


if __name__ == '__main__': unittest.main()
