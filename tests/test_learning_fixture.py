import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
import learning_fixture


class LearningFixtureTests(unittest.TestCase):
    def test_guard_rejects_normal_mode_and_foreign_runtime(self):
        store = MagicMock()
        store.runtime = Path('/other-runtime')
        for controlled, enabled in [(False, '1'), (True, '0'), (True, '1')]:
            store.host.test_control = controlled
            with patch.dict('os.environ', {'YGO_TRAIN_LEARNING': enabled}):
                with self.assertRaisesRegex(ValueError, 'isolated test'):
                    learning_fixture.start(store, {})
            store.start.assert_not_called()

    def test_new_engine_fixture_preserves_source_and_rejects_changed_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / '.local/ygo-learning/p0b-p1/desktop-check-development-modular/runtime'
            runtime.mkdir(parents=True)
            (runtime / 'YGOPro.exe').write_bytes(b'new instrumented engine')
            store = MagicMock()
            store.runtime, store.lock = runtime, threading.RLock()
            store.host.test_control = True
            store.alive.return_value = False
            store.catalog.sources = [{'path': 'cards.cdb', 'sha256': 'fixed'}]
            store.catalog.cards = {1: {'name': 'synthetic'}}
            store.compromise.script_identity.return_value = 'scripts'
            store.session_path.side_effect = lambda sid: runtime / sid
            source = {'id': 'source', 'status': 'stopping', 'engine_sha256': 'old',
                      'sources': store.catalog.sources, 'scripts_sha256': 'scripts',
                      'catalog': {'1': {'name': 'synthetic'}}, 'selected_deck': 'public',
                      'expansion': {'engine_seed': 42, 'draw_order': [1, 2, 3]}}
            path = runtime / 'source/session.json'
            path.parent.mkdir()
            path.write_text(json.dumps(source), encoding='utf-8')
            original = path.read_bytes()
            def launch(identifier, retry_meta):
                target = runtime / 'new/session.json'
                target.parent.mkdir()
                target.write_text(json.dumps({**retry_meta, 'id': 'new'}), encoding='utf-8')
                return {'id': 'new'}
            store.start.side_effect = launch
            with patch.object(learning_fixture, 'ROOT', root), patch.dict('os.environ', {'YGO_TRAIN_LEARNING': '1'}):
                store.alive.return_value = True
                with self.assertRaisesRegex(ValueError, 'closed seeded experiment'):
                    learning_fixture.start(store, {'id': 'source', 'source_engine_sha256': 'old'})
                store.start.assert_not_called()
                store.alive.return_value = False
                result = learning_fixture.start(store, {'id': 'source', 'source_engine_sha256': 'old'})
                self.assertEqual('new', result['id'])
                self.assertEqual(original, path.read_bytes())
                created = json.loads((runtime / 'new/session.json').read_text('utf-8'))
                self.assertEqual(source['expansion'], created['expansion'])
                self.assertEqual(hashlib.sha256(b'new instrumented engine').hexdigest(), created['engine_sha256'])
                self.assertEqual('old', created['learning_fixture']['source_engine_sha256'])
                self.assertEqual('stopping', created['learning_fixture']['source_status'])
                store.compromise.script_identity.return_value = 'changed'
                with self.assertRaisesRegex(ValueError, 'assets changed'):
                    learning_fixture.start(store, {'id': 'source', 'source_engine_sha256': 'old'})
                self.assertEqual(1, store.start.call_count)


if __name__ == '__main__':
    unittest.main()
