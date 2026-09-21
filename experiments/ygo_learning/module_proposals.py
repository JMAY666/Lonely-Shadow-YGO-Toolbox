"""Rebind only the five frozen public P1 demonstrations to current legal choices.

These are proposals, not complete applicable routes. No user source database is
read, and the teacher must validate each response in its disposable engine.
"""
import json
from pathlib import Path
from contract_v2 import digest
from modular_decisions import model, semantic_response, bind_variants
from provenance import ROOT, sha256


class PublicModules:
    def __init__(self, sources):
        self.by_message = {}
        self.edges = 0
        for source in sources:
            path = (ROOT / source['path']).resolve()
            allowed = (ROOT / '.local/ygo-learning/p0b-p1/demonstrations-20260919-134647').resolve()
            if path.parent != allowed or sha256(path) != source['sha256']:
                raise ValueError('Public proposal source path/hash mismatch')
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('status') != 'passed':
                raise ValueError('Public proposal source did not pass')
            for ordinal, step in enumerate(record['steps']):
                before = step['before']
                prompt = model(before['raw'], before['state'], before.get('effects'))
                if prompt['player'] != 0:
                    continue
                semantic = semantic_response(prompt, step['response'])
                # Stopping/declining a demonstration is not a reusable strategy.
                if not semantic.get('selection') or all(c['kind'] in
                        ('end_turn', 'pass', 'no', 'cancel_selection', 'unselect')
                        for c in semantic['selection']):
                    continue
                key = digest(semantic)
                group = self.by_message.setdefault(prompt['message'], {})
                group.setdefault(key, {'semantic': semantic, 'sources': []})['sources'].append(
                    {'file': source['path'], 'sha256': source['sha256'], 'step': ordinal})
                self.edges += 1

    def propose(self, snapshot, bundle):
        prompt = model(snapshot['raw'], snapshot['state'], snapshot.get('effects'))
        matched = {}
        for edge in self.by_message.get(prompt['message'], {}).values():
            for response in bind_variants(edge['semantic'], prompt, precise=False, limit=3):
                for index, candidate in enumerate(bundle['candidates']):
                    if response in candidate['responses']:
                        matched.setdefault(index, []).extend(edge['sources'])
        return matched
