"""Content identity for the finite, native-verified hint examples.

The receipt lists shipped example coverage. It never certifies a live external
duel, a platform banlist, or an arbitrary state assembled from observations.
"""
from pathlib import Path
import hashlib
import json

from second_rules import EFFECTS, REVISION

PROOF_PATH = Path(__file__).parent / 'data/second-hints-proof.json'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def card_identity(card):
    return digest({key: card.get(key) for key in ('id', 'alias', 'type', 'attribute', 'race', 'level', 'atk', 'def', 'desc',
                                                  *(f'str{i}' for i in range(1, 17)))})


def fingerprint(runtime, catalog):
    runtime = Path(runtime)
    script_hash = hashlib.sha256()
    from superpre import installed_metadata
    patch = installed_metadata(runtime)
    if patch:
        script_hash.update(patch['sha256'].encode('ascii'))
    for root in ('script', 'expansions/script'):
        for path in sorted((runtime / root).rglob('*.lua')):
            script_hash.update(path.relative_to(runtime).as_posix().encode())
            script_hash.update(hashlib.sha256(path.read_bytes()).digest())
    databases = {}
    for source in sorted({'cards.cdb'} | {c['source'] for c in catalog.values() if c.get('source')}):
        path = (runtime / source).resolve()
        if not path.is_relative_to(runtime.resolve()) or path.suffix != '.cdb':
            raise ValueError('规则数据库来源无法核对')
        databases[source] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'engine_sha256': hashlib.sha256((runtime / 'YGOPro.exe').read_bytes()).hexdigest(),
            'scripts_sha256': script_hash.hexdigest(),
            'databases': databases,
            'cards': {str(code): card_identity(catalog[code]) for code in sorted({v['code'] for v in EFFECTS.values()}) if code in catalog}}


class HintProof:
    def __init__(self, store):
        self.store = store
        self.cached = None

    def load(self):
        try:
            proof = json.loads(PROOF_PATH.read_text(encoding='utf-8'))
            if (not isinstance(proof, dict) or proof.get('schema') != 1 or proof.get('revision') != REVISION
                    or not isinstance(proof.get('resources'), dict) or not isinstance(proof.get('cases'), dict)
                    or not proof['cases'] or any(not isinstance(v, dict) for v in proof['cases'].values())):
                raise ValueError('proof format')
            for case in proof['cases'].values():
                if (any(type(case.get(k)) is not bool for k in ('activated', 'actor_removed', 'immediate_chixiao', 'fusion_again'))
                        or case.get('negation') not in (None, 'activation', 'effect')
                        or type(case.get('gained')) is not int or case['gained'] not in (0, 1)
                        or type(case.get('responder_cards_committed')) is not int or not 0 <= case['responder_cards_committed'] <= 2):
                    raise ValueError('case format')
            return proof
        except (OSError, ValueError, TypeError):
            return None

    def check(self, force=False):
        # The shared stamp includes source database identities and script/file
        # changes. Full content hashes are recomputed whenever that stamp moves.
        stamp = self.store.modular.precompute.rules(force=force)
        proof = self.load()
        key = digest([stamp, proof, EFFECTS, REVISION])
        if self.cached and self.cached[0] == key:
            return self.cached[1]
        result = {'status': 'unverified', 'stamp': key, 'revision': REVISION, 'cases': {},
                  'reason': '本期原生验证摘要缺失或格式无法核对'}
        if proof:
            try:
                actual = fingerprint(self.store.runtime, self.store.catalog.cards)
                if actual == proof.get('resources'):
                    result.update(status='matched', cases=proof['cases'], reason='固定本地规则资源中的有限案例已通过')
                else:
                    result['reason'] = '当前规则资源与已验证案例不同，不能沿用原验证结论'
            except (OSError, ValueError, KeyError):
                result['reason'] = '当前规则资源不完整，不能确认案例适用性'
        self.cached = (key, result)
        return result
