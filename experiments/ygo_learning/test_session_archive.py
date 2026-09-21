"""Native evidence must survive compact storage byte-for-byte and fail closed."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import session_archive as archive


class SessionArchiveTests(unittest.TestCase):
    def fixture(self, root):
        base = Path(root) / 'p0b-p1'
        sid = '11111111-1111-4111-8111-111111111111'
        folder = base / 'desktop-check-development-modular/runtime/_trainer/sessions' / sid
        folder.mkdir(parents=True)
        meta = {'id': sid, 'status': 'completed', 'pid': 1234, 'process_identity': 'finished-test'}
        (folder / 'session.json').write_text(json.dumps(meta), encoding='utf-8')
        (folder / 'native.jsonl').write_text('{"test_control": true}\n{"kind": "end"}\n', encoding='utf-8')
        (folder / 'restore-1.txt').write_bytes(b'exact restore bytes\r\n')
        (folder / 'report-v14.json').write_text('{"name":"相剑"}', encoding='utf-8')
        (Path(root) / 'p2-p3').mkdir()
        target = Path(root) / 'p2-p3/session.zip'
        return base, sid, folder, target

    def test_compact_retains_full_bytes_and_restores_without_overwriting(self):
        with tempfile.TemporaryDirectory() as root:
            base, sid, folder, target = self.fixture(root)
            original = {p.name: p.read_bytes() for p in folder.iterdir()}
            with patch.object(archive, 'BASE', base), patch('app.process_identity', return_value=None):
                result = archive.pack_session(folder, target, sid, compact=True)
                self.assertFalse((folder / 'native.jsonl').exists())
                self.assertTrue((folder / 'session.json').exists())
                self.assertTrue((folder / 'report-v14.json').exists())
                with archive.restored_session(target, result['sha256']) as restored:
                    self.assertEqual(original, {p.name: p.read_bytes() for p in restored.iterdir()})
                    with self.assertRaises(FileExistsError):
                        archive.restore_archive(target, restored, result['sha256'])
                with self.assertRaisesRegex(ValueError, 'hash'):
                    archive.restore_archive(target, Path(root) / 'bad', '0' * 64)

    def test_live_session_is_rejected_without_removing_a_file(self):
        with tempfile.TemporaryDirectory() as root:
            base, sid, folder, target = self.fixture(root)
            expected = archive.files(folder)
            with patch.object(archive, 'BASE', base), patch('app.process_identity', return_value='finished-test'):
                with self.assertRaisesRegex(ValueError, 'live'):
                    archive.pack_session(folder, target, sid, compact=True)
            self.assertEqual(expected, archive.files(folder))
            self.assertFalse(target.exists())

    def test_traversal_and_unmanifested_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            for ordinal, name in enumerate(['../escaped', 'C:escaped', 'safe/escaped']):
                target = Path(root) / f'bad-{ordinal}.zip'
                manifest = {'schema': archive.SCHEMA, 'files': {name: {
                    'size': 1, 'sha256': hashlib.sha256(b'x').hexdigest()}}}
                with zipfile.ZipFile(target, 'w') as z:
                    z.writestr(archive.MANIFEST, json.dumps(manifest))
                    z.writestr(name, b'x')
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    archive.restore_archive(target, Path(root) / f'restored-{ordinal}', archive.sha256(target))
                self.assertFalse((Path(root) / 'escaped').exists())


if __name__ == '__main__':
    unittest.main()
