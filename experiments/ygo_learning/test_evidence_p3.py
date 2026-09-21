"""Lossless evidence storage must preserve failures as well as successful states."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

import evidence_p3 as evidence


class EvidenceTests(unittest.TestCase):
    def test_deferred_verification_is_explicit_and_restored_snapshots_do_not_alias(self):
        state = {'raw': '00', 'state': {'cards': [1]}, 'learning': {}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.json.gz'
            stats = evidence.write_archive(path, [state, state], verify=False)
            self.assertFalse(stats['restoration_verified'])
            restored = evidence.read_archive(path)
            restored[0]['state']['cards'].append(2)
            self.assertEqual([1], restored[1]['state']['cards'])

    def test_native_numeric_counters_use_json_keys_without_collision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.json.gz'
            evidence.write_archive(path, {'coverage': {11: 5, 23: 2}})
            self.assertEqual({'coverage': {'11': 5, '23': 2}}, evidence.read_archive(path))
            with self.assertRaisesRegex(ValueError, 'collid'):
                evidence.write_archive(Path(folder) / 'bad.json.gz', {11: 1, '11': 2})

    def test_roundtrip_deduplicates_states_without_reserved_key_collisions(self):
        state = {'raw': '0b00', 'state': {'cards': [1, 2]}, 'learning': {'schema': 2}}
        record = {'steps': [{'before': state, 'after': state}], '$snapshot': 'literal',
                  'failure': None, 'unicode': '相剑', 'other': [True, 1.5]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.json.gz'
            stats = evidence.write_archive(path, record)
            self.assertEqual(record, evidence.read_archive(path))
            self.assertEqual(1, stats['unique_snapshots'])
            self.assertEqual(2, stats['snapshot_references'])
            with self.assertRaises(FileExistsError):
                evidence.write_archive(path, record)

    def test_corrupted_snapshot_is_rejected(self):
        record = {'raw': '0b00', 'state': {'turn': 1}, 'learning': {'schema': 2}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.json.gz'
            evidence.write_archive(path, record)
            value = json.loads(gzip.decompress(path.read_bytes()))
            next(iter(value['snapshots'].values()))['state']['turn'] = 2
            path.write_bytes(gzip.compress(json.dumps(value).encode()))
            with self.assertRaisesRegex(ValueError, 'hash'):
                evidence.read_archive(path)

    def test_missing_reference_is_rejected(self):
        record = {'raw': '0b00', 'state': {}, 'learning': {}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'case.json.gz'
            evidence.write_archive(path, record)
            value = json.loads(gzip.decompress(path.read_bytes()))
            value['snapshots'].clear()
            path.write_bytes(gzip.compress(json.dumps(value).encode()))
            with self.assertRaises(ValueError):
                evidence.read_archive(path)


if __name__ == '__main__':
    unittest.main()
