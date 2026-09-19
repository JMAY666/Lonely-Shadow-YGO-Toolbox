"""Export accepted public pilot choices for an environment-only student probe.

Run with the existing ygo-agent pilot Python. Never reads production user data.
This reuses the pilot's limited observation contract, including base card stats.
"""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / '.local/ygo-agent-pilot'
OUTPUT = ROOT / '.local/ygo-learning/smoke-data'
CASES = ('baseline', 'single-starter', 'ash')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_session(session):
    base = (PILOT / 'desktop-check-development-modular/runtime/_trainer/sessions').resolve()
    folder = (base / session).resolve()
    if folder.parent != base:
        raise ValueError('Only direct children of the isolated pilot sessions are allowed')
    return folder


def require_confirmed(step, node, responses, following):
    if step.get('engine_accepted') is not True:
        raise ValueError('Unconfirmed teacher action')
    if node.get('player') != 0 or node.get('raw') != step['prompt']:
        raise ValueError('Recommendation does not match the native decision')
    if len(responses) != 1 or responses[0].get('raw') != step['response']:
        raise ValueError('Response differs or has ambiguous retries')
    if not following or following.get('seq', -1) <= node['seq']:
        raise ValueError('Missing later engine checkpoint')


def main():
    sys.path.insert(0, str(ROOT))
    from experiments.ygo_agent.bootstrap import verify_assets
    verify_assets()
    sys.path.insert(0, str(ROOT / 'src/trainer'))
    sys.path.insert(0, str(PILOT / 'upstream'))
    import numpy as np
    from ygoinf import features as f
    from experiments.ygo_agent.adapter import NativeInput
    from module_graph import decision_boundaries
    from app import Catalog

    f.init_code_list(str(PILOT / 'code_list.txt'))
    runtime = PILOT / 'desktop-check-development-modular/runtime'
    catalog_source = Catalog(runtime)
    fields = {key: [] for key in ('cards', 'global', 'history', 'actions', 'legal', 'target')}
    records, sources, seen = [], [], {}
    single_choices = duplicates = accepted_windows = skipped_unconfirmed = 0
    for case in CASES:
        paths = sorted((PILOT / 'evidence').glob(case + '-*/result.json'))
        if not paths:
            raise ValueError(f'Missing completed public pilot case: {case}')
        result_path = paths[-1]
        result = json.loads(result_path.read_text(encoding='utf-8'))
        if result.get('case') != case or result.get('status') != 'model_recommended_end_turn':
            raise ValueError(f'Latest pilot case is incomplete: {case}')
        folder = checked_session(result['session'])
        journal = folder / 'native.jsonl'
        rows = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines() if line]
        if not rows or rows[0].get('test_control') is not True:
            raise ValueError('Only explicitly marked test sessions may be used')
        if result['source_identity'].get('sources') != catalog_source.sources:
            raise ValueError('The runtime card databases differ from the recorded pilot')
        boundaries = decision_boundaries(rows, folder)
        by_node = {entry['node']['node']: entry for entry in boundaries}
        catalog = catalog_source.cards
        for code, frozen in result['source_identity']['catalog'].items():
            current = catalog[int(code)]
            for key in ('atk', 'def', 'type', 'level', 'race', 'attribute'):
                if frozen.get(key) != current.get(key):
                    raise ValueError(f'Card data differs from the recorded pilot: {code}/{key}')
        history = f.HistoryActions()
        sources.append({'case': case, 'result_sha256': sha256(result_path),
                        'journal_sha256': sha256(journal), 'test_control': True})
        for step_index, step in enumerate(result['steps']):
            if step.get('engine_accepted') is not True:
                if step_index != len(result['steps']) - 1 or step.get('response') != '07000000':
                    raise ValueError('Only the final unexecuted end-turn suggestion may be excluded')
                skipped_unconfirmed += 1
                continue
            if not step.get('rankings'):
                raise ValueError('An accepted action has no recorded micro choices')
            entry = by_node[step['version']]
            node = entry['node']
            following = by_node.get(step['next_version'], {}).get('node')
            require_confirmed(step, node, entry['responses'], following)
            accepted_windows += 1
            native = NativeInput({**node, 'answered': False, 'version': step['version']}, catalog)
            selected = []
            for micro_index, ranking in enumerate(step['rankings']):
                value = f.Input.model_validate(native.input(selected))
                actions = f.get_legal_actions(value.action_msg)
                if not 0 < len(actions) <= f.MAX_ACTIONS or len(ranking) != len(actions):
                    raise ValueError('Truncated or mismatched legal choices')
                if sorted(r['index'] for r in ranking) != list(range(len(actions))):
                    raise ValueError('Recorded action indices are not a complete permutation')
                for prediction in ranking:
                    if actions[prediction['index']].response != prediction['response']:
                        raise ValueError('Upstream action mapping changed')
                prediction = ranking[0]
                target = prediction['index']
                cards, specs = f.encode_cards(value.cards)
                with redirect_stdout(io.StringIO()):
                    encoded = f.encode_legal_actions(actions, specs)
                sample = {'cards': cards.copy(), 'global': f.encode_global(value.global_, value.cards),
                          'history': history.encode(value.global_.turn).copy(), 'actions': encoded.copy(),
                          'legal': np.arange(f.MAX_ACTIONS) < len(actions), 'target': np.int64(target)}
                if len(actions) > 1:
                    fingerprint = hashlib.sha256(b''.join(sample[k].tobytes()
                        for k in ('cards', 'global', 'history', 'actions', 'legal'))).hexdigest()
                    if fingerprint in seen:
                        if seen[fingerprint] != target:
                            raise ValueError('Identical observations have conflicting labels')
                        duplicates += 1
                    else:
                        seen[fingerprint] = target
                        for key, item in sample.items():
                            fields[key].append(item)
                        records.append({'case': case, 'checkpoint': node['node'], 'micro_choice': micro_index,
                                        'legal_count': len(actions), 'input_sha256': fingerprint})
                else:
                    single_choices += 1
                history.update(encoded[target], value.global_.turn, value.global_.phase)
                if native.prompt['mode'] in ('cards', 'sum') and prediction['response'] != -1:
                    if prediction['response'] in selected:
                        raise ValueError('Duplicate material in accepted choice')
                    selected.append(prediction['response'])
            if native.response(prediction, selected) != step['response']:
                raise ValueError('Micro choices do not reproduce the accepted native response')

    if len(records) < 10:
        raise ValueError('Too few distinct real multi-choice observations for a probe')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target_path = OUTPUT / 'accepted-choices.npz'
    packed = {key: np.stack(values) for key, values in fields.items()}
    if target_path.exists():
        previous = json.loads((OUTPUT / 'manifest.json').read_text(encoding='utf-8'))
        with np.load(target_path, allow_pickle=False) as saved:
            equal = set(saved.files) == set(packed) and all(np.array_equal(saved[k], v) for k, v in packed.items())
        if not equal or previous['data_sha256'] != sha256(target_path) or previous['sources'] != sources:
            raise FileExistsError('Existing smoke data differs; preserve it and use a new experiment directory')
        print(f'PASS existing immutable dataset: {len(records)} distinct multi-choice observations')
        return
    np.savez_compressed(target_path, **packed)
    manifest = {'schema': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'environment_only_overfit_probe_not_strategy_evaluation',
                'limitations': ['three public first-turn pilot cases', 'base rather than complete dynamic card stats',
                                'no held-out quality claim', 'no fresh full-engine replay in this extraction'],
                'accepted_windows': accepted_windows, 'distinct_multi_choices': len(records),
                'single_choices_excluded': single_choices, 'duplicate_inputs_excluded': duplicates,
                'unconfirmed_end_suggestions_excluded': skipped_unconfirmed,
                'features_commit': verify_assets()['commit'], 'data_sha256': sha256(target_path),
                'catalog_sources': catalog_source.sources,
                'sources': sources, 'records': records}
    (OUTPUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in manifest.items() if key not in ('records', 'sources')}, indent=2))


if __name__ == '__main__':
    main()
