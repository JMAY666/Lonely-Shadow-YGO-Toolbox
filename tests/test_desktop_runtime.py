import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from desktop_runtime import OwnedJob, ServiceLock, digest, migrate_data, prepare_resources, resource_allowed, write_json


class DesktopDataTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / '.local/test-runs'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.root = Path(self.temp.name)
        self.source = self.root / 'legacy'
        self.runtime = self.root / 'desktop/runtime'
        (self.source / '_trainer/decks').mkdir(parents=True)
        (self.source / '_trainer/decks/测试.ydk').write_bytes(b'#main\n55144522\n#extra\n!side\n')
        (self.source / 'system.conf').write_bytes(b'window_width = 1000\n')
        (self.source / '_trainer/card-favorites.json').write_bytes(b'{"cards":[55144522]}\n')

    def tearDown(self):
        self.temp.cleanup()

    def bundle(self, files):
        path = self.root / 'resources.zip'
        info = {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in files.items()}
        manifest = {'version': hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest(), 'files': info}
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('bundle-manifest.json', json.dumps(manifest))
            for name, data in files.items():
                z.writestr(name, data)
        return path

    def test_migrate_backup_hashes_source_unchanged_and_idempotent(self):
        before = digest(self.source / '_trainer/decks/测试.ydk')
        state = migrate_data(self.source, self.runtime)
        self.assertEqual(state['status'], 'complete')
        for name, info in state['files'].items():
            self.assertEqual(digest(self.runtime / name), info['sha256'])
            self.assertEqual(digest(Path(state['backup']) / 'files' / name), info['sha256'])
        self.assertEqual(digest(self.source / '_trainer/decks/测试.ydk'), before)
        self.assertFalse((self.source / '_trainer/service.lock').exists(), 'Migration must not create files in the source')
        (self.runtime / 'system.conf').write_bytes(b'user changed preferences')
        migrate_data(self.source, self.runtime)
        self.assertEqual((self.runtime / 'system.conf').read_bytes(), b'user changed preferences')

    def test_existing_desktop_data_is_never_overwritten(self):
        (self.runtime / '_trainer/decks').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, '目标已有'):
            migrate_data(self.source, self.runtime)
        self.assertFalse((self.runtime / '_trainer/decks/测试.ydk').exists())

    def test_resume_interrupted_copy_from_verified_backup(self):
        state = migrate_data(self.source, self.runtime)
        state['status'] = 'copying'
        write_json(self.runtime.parent / 'migration.json', state)
        (self.runtime / '_trainer/decks/测试.ydk').unlink()
        state = migrate_data(self.source, self.runtime)
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(digest(self.runtime / '_trainer/decks/测试.ydk'), digest(self.source / '_trainer/decks/测试.ydk'))

    def test_resume_refuses_conflicting_target(self):
        state = migrate_data(self.source, self.runtime)
        state['status'] = 'copying'
        write_json(self.runtime.parent / 'migration.json', state)
        (self.runtime / 'system.conf').write_bytes(b'newer user settings')
        with self.assertRaisesRegex(ValueError, '目标文件已改变'):
            migrate_data(self.source, self.runtime)
        self.assertEqual((self.runtime / 'system.conf').read_bytes(), b'newer user settings')

    @unittest.skipUnless(os.name == 'nt', 'Windows lock')
    def test_migration_refuses_active_service(self):
        with ServiceLock(self.source / '_trainer/service.lock'):
            with self.assertRaisesRegex(RuntimeError, '另一服务'):
                migrate_data(self.source, self.runtime)
        self.assertFalse((self.runtime.parent / 'migration.json').exists())

    def test_resource_upgrade_preserves_decks_config_and_records(self):
        migrate_data(self.source, self.runtime)
        bundle = self.bundle({'YGOPro.exe': b'engine1', 'cards.cdb': b'cards1', 'system.conf': b'default'})
        prepare_resources(bundle, self.runtime)
        before = digest(self.runtime / '_trainer/decks/测试.ydk')
        bundle = self.bundle({'YGOPro.exe': b'engine2', 'cards.cdb': b'cards2', 'system.conf': b'new-default'})
        prepare_resources(bundle, self.runtime)
        self.assertEqual((self.runtime / 'YGOPro.exe').read_bytes(), b'engine2')
        self.assertEqual((self.runtime / 'system.conf').read_bytes(), b'window_width = 1000\n')
        self.assertEqual((self.runtime / '_trainer/card-favorites.json').read_bytes(), b'{"cards":[55144522]}\n')
        self.assertEqual(digest(self.runtime / '_trainer/decks/测试.ydk'), before)
        (self.runtime / 'cards.cdb').unlink()
        prepare_resources(bundle, self.runtime)
        self.assertEqual((self.runtime / 'cards.cdb').read_bytes(), b'cards2')

    def test_resource_archive_cannot_write_user_data_or_escape(self):
        for name in ('../escape.txt', '_trainer/decks/existing.ydk', 'deck/existing.ydk', 'pics/../../escape.jpg'):
            with self.subTest(name=name):
                bundle = self.bundle({name: b'bad'})
                with self.assertRaises(ValueError):
                    prepare_resources(bundle, self.runtime)
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_packaging_allowlist_excludes_private_or_unused_files(self):
        for name in ('_trainer/card-favorites.json', '_trainer/sessions/x/session.json', '_profile/logs/stdout.log', 'deck/a.ydk', 'WindBot/a.exe', 'Bot.exe', 'replay/a.yrp', 'private.json'):
            self.assertFalse(resource_allowed(name), name)
        for name in ('cards.cdb', 'script/c1.lua', 'pics/field/1.jpg', 'textures/cover.jpg'):
            self.assertTrue(resource_allowed(name), name)

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Object')
    def test_job_closes_only_owned_process(self):
        owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], creationflags=subprocess.CREATE_NO_WINDOW)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], creationflags=subprocess.CREATE_NO_WINDOW)
        job = OwnedJob()
        try:
            job.assign(owned)
            job.close()
            owned.wait(timeout=5)
            self.assertIsNone(unrelated.poll())
        finally:
            job.close()
            for process in (owned, unrelated):
                if process.poll() is None: process.terminate()
                process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
