"""Twenty training-family paired T0/B1 experiments, never formal evaluation."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
import uuid

from native_session import ROOT, BASE
sys.path.insert(0, str(ROOT))
from contract_v2 import build, digest, known, Unsupported
from modular_decisions import canonical_state, model, semantic_response
from protocol import packets
from provenance import runtime_identity, sha256
from budget import Budget, folder_bytes
from evidence_p3 import write_archive, read_archive, json_value, canonical
from teacher_p3 import choose
from journal_audit import audit
from experiments.ygo_agent.adapter import NativeInput
from experiments.ygo_agent.policy import Policy

CALIBRATION = ROOT / '.local/ygo-learning/p2-p3'


class CalibrationBudget(Budget):
    """Persist compute progress and enforce cumulative limits inside each turn."""
    def __init__(self, session, output, previous_compute):
        self.progress_path = Path(output) / 'compute-progress.json'
        self.previous_compute = previous_compute
        self.compute_started = time.monotonic()
        self.last_saved = 0
        super().__init__(session, [])

    def check(self, disk=False):
        elapsed = time.monotonic() - self.compute_started
        if elapsed - self.last_saved >= 1 or disk:
            temporary = self.progress_path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'worker_seconds': elapsed}), encoding='utf-8')
            temporary.replace(self.progress_path)
            self.last_saved = elapsed
        if self.previous_compute + elapsed >= 7200:
            raise ValueError('P2/P3 cumulative two-hour compute budget exhausted')
        return super().check(disk=disk)

class TurnObserver:
    def __init__(self):
        self.terminal = None
        self.terminal_seq = None
        self.draws = 0
        self.offset = 0
        self.pending = b''

    def consume(self, row):
        state = row.get('state', {})
        if self.terminal is None and state.get('turn', 0) > 1:
            self.terminal = deepcopy(state)
            self.terminal_seq = row['seq']
        if row.get('kind') == 'batch' and state.get('turn') == 1:
            for _, message, body in packets(bytes.fromhex(row.get('raw', ''))):
                if message == 90 and body[0] == 0:
                    self.draws += body[1]

    def update(self, path):
        with Path(path).open('rb') as stream:
            stream.seek(self.offset)
            chunk = stream.read()
        self.offset += len(chunk)
        lines = (self.pending + chunk).split(b'\n')
        self.pending = lines.pop()
        for line in lines:
            if line.strip():
                self.consume(json.loads(line))

def goal_view(state):
    return {'schema': 'p2_goal_card_view_v1', 'cards': [
        {'controller': c['controller'], 'location': c['location'], 'position': c['position'],
         'identity_known': known(c), 'code': c['code'] if known(c) else 0,
         'disabled': c.get('disabled')} for c in state['cards']]}


def candidate_index(bundle, state, response):
    indexes = [i for i, c in enumerate(bundle['candidates']) if response in c['responses']]
    if not indexes:
        prompt = model(state['raw'], state['state'], state.get('effects'))
        def key(raw):
            value = semantic_response(prompt, raw)
            value['selection'] = sorted(value.get('selection', []), key=digest)
            return digest(value)
        expected = key(response)
        indexes = [i for i, c in enumerate(bundle['candidates']) if key(c['response']) == expected]
    if len(indexes) != 1:
        raise Unsupported('legacy_response_not_in_v2_candidates')
    return indexes[0]


def source_registry():
    """Only explicitly public P1 recipes; no user plan database is read."""
    folder = BASE / 'demonstrations-20260919-134647'
    sources = []
    for path in sorted(folder.glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        if not record.get('steps') or record.get('status') != 'passed':
            continue
        hand = sorted(c['code'] for c in record['steps'][0]['before']['state']['cards']
                      if c['controller'] == 0 and c['location'] == 2)
        sources.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path), 'hand': hand})
    if not sources:
        raise ValueError('Frozen public source baseline is unavailable')
    return sources


def restart(session, previous, expansion_hash):
    if session.sid:
        raise ValueError('Previous isolated run is still active')
    began = time.perf_counter()
    session.sid = session.api('/api/restart', {'id': previous})['id']
    state = session.current()
    session.samples = []
    session.start_seconds = time.perf_counter() - began
    meta = session.read('session.json')
    if digest(meta['expansion']) != expansion_hash:
        raise ValueError('Paired replay changed the initial random condition')
    with (session.folder / 'native.jsonl').open(encoding='utf-8') as stream:
        if json.loads(stream.readline()).get('test_control') is not True:
            raise ValueError('Paired session is not test-controlled')
    return state


def latest_condition_session(folder, original, expansion_hash):
    """Follow only this family's immutable retry chain; never resample on resume."""
    seen = set()
    current = original
    while True:
        if not isinstance(current, str) or str(uuid.UUID(current)) != current or current in seen:
            raise ValueError('Invalid or cyclic condition session chain')
        seen.add(current)
        meta = json.loads((Path(folder) / current / 'session.json').read_text(encoding='utf-8'))
        if digest(meta['expansion']) != expansion_hash:
            raise ValueError('Saved family random condition changed')
        if not meta.get('retry_id'):
            return current
        current = meta['retry_id']


def run_policy(session, state, catalog, family, mode, policy, budget, evaluate_goal):
    record = {'family_id': family['id'], 'scenario': family['scenario'], 'mode': mode,
              'status': 'running', 'steps': [], 'replayed': False, 'model_calls': 0,
              'model_proposal_failures': [], 'nodes': 0, 'multi_choice_windows': 0,
              'single_choice_windows': 0, 'uncertain_branches': 0, 'aborted_searches': []}
    began = time.perf_counter()
    observer = TurnObserver()
    visits = Counter()
    try:
        for _ in range(120):
            observer.update(session.folder / 'native.jsonl')
            if observer.terminal is not None:
                record['status'] = 'turn_completed'
                break
            if time.perf_counter() - began > 180:
                record['status'] = 'time_budget_stopped'
                break
            budget.check()
            bundle = build(state, catalog)
            decision_key = bundle['state_key'] + digest([c['public'] for c in bundle['candidates']])
            visits[decision_key] += 1
            if visits[decision_key] > 3:
                record['status'] = 'strategy_cycle_stopped'
                break
            count = len(bundle['candidates'])
            record['multi_choice_windows' if count > 1 else 'single_choice_windows'] += 1
            advice = None
            choice = {'index': 0, 'nodes': 0, 'uncertain_branches': 0, 'source': 'unique_legal_choice'}
            response = bundle['candidates'][0]['response']
            if count > 1 or mode == 'B1':
                preferred = None
                try:
                    if mode == 'T0':
                        policy.rstate = policy.features.init_rstate()
                        policy.history = policy.features.HistoryActions()
                        policy.pending = None
                    advice = policy.recommend(NativeInput(state, catalog))
                    record['model_calls'] += 1
                    preferred = candidate_index(bundle, state, advice['response'])
                except (ValueError, KeyError) as error:
                    if mode == 'B1':
                        raise Unsupported(str(error)) from error
                    record['model_proposal_failures'].append(str(error))
                    policy.pending = None
                if mode == 'B1':
                    choice = {'index': preferred, 'nodes': 0, 'uncertain_branches': 0,
                              'source': 'frozen_recurrent_TFLite'}
                    response = advice['response']
                else:
                    stops = [i for i, c in enumerate(bundle['candidates'])
                             if any(s['kind'] == 'end_turn' for s in c['public']['selection'])]
                    reached = evaluate_goal(goal_view(state['state']), family['goal'],
                                            completed=True, actual_draw_count=observer.draws)['success']
                    if reached and stops:
                        choice = {'index': stops[0], 'nodes': 0, 'uncertain_branches': 0,
                                  'source': 'frozen_goal_satisfied_stop'}
                    else:
                        choice = choose(session, state, catalog, preferred, budget_check=budget.check)
                    if choice.get('stopped'):
                        record['aborted_searches'].append(choice)
                        record['nodes'] += choice['nodes']
                        record['uncertain_branches'] += choice['uncertain_branches']
                        record.update(status='budget_stopped' if 'budget' in choice['stopped'] else 'execution_error',
                                      error=choice['stopped'])
                        break
                    response = bundle['candidates'][choice['index']]['response']
                    policy.pending = None
            # Legality/replay validation never supplies a future-state score.
            proof = session.probe(state, [state['raw'] + ':' + response])
            if proof['status'] != 'ok':
                raise ValueError('selected_response_probe_failed: ' + str(proof))
            before = state
            state = session.answer(before, response)
            if mode == 'B1' and advice is not None:
                policy.commit(before['version'], before['raw'], response)
            record['nodes'] += choice['nodes']
            record['uncertain_branches'] += choice['uncertain_branches']
            record['steps'].append({'before': before, 'after': state, 'response': response,
                                    'candidate_index': choice['index'], 'decision': choice,
                                    'selected_replay': proof, 'acknowledgement': deepcopy(session.samples[-1])})
        else:
            record['status'] = 'decision_budget_stopped'
    except Unsupported as error:
        record.update(status='unsupported', error=str(error))
    except Exception as error:
        record.update(status='execution_error', error=f'{type(error).__name__}: {error}')
    finally:
        observer.update(session.folder / 'native.jsonl')
        try:
            final = session.current()
            replay = session.probe(final)
            if (replay['status'] != 'ok' or canonical_state(replay['state']) != canonical_state(final['state'])
                    or replay['learning'] != final['learning']):
                raise ValueError('Full-prefix replay differs from executed state')
            record.update(replayed=True, final_replay=replay, final=final)
        except Exception as error:
            record['replay_error'] = str(error)
        observer.update(session.folder / 'native.jsonl')
        terminal = observer.terminal
        record['goal'] = evaluate_goal(goal_view(terminal or state['state']), family['goal'],
                                      completed=terminal is not None, actual_draw_count=observer.draws)
        record.update(goal_native_seq=observer.terminal_seq, actual_draw_count=observer.draws,
                      terminal_goal_view=goal_view(terminal) if terminal else None)
        record['session'] = session.finish()
        try:
            record['journal_audit'] = audit(record)
        except Exception as error:
            record.update(status='journal_mismatch', audit_error=str(error))
        record['native_evidence_bytes'] = folder_bytes(Path(record['session']['folder']))
        record['seconds'] = time.perf_counter() - began + record['session']['start_seconds']
    return record


def run(session, catalog, output, protocol_path, first=1, count=20):
    from protocol_p2 import load_protocol, calibration_families, evaluate_goal
    from mechanisms import deck, ASH, NORMAL
    output = Path(output)
    protocol = load_protocol(Path(protocol_path))
    families = calibration_families(protocol)
    if not 1 <= first <= 20 or not 1 <= count <= 20 or first + count - 1 > 20:
        raise ValueError('Calibration may access only the frozen 20 training families')
    selected = families[first - 1:first - 1 + count]
    sources = source_registry()
    runtime = runtime_identity(session.runtime)
    previous_compute = 0
    for directory in CALIBRATION.glob('teacher-*'):
        times = [json.loads(p.read_text(encoding='utf-8')).get('worker_seconds', 0)
                 for p in (directory / 'summary.json', directory / 'compute-progress.json') if p.is_file()]
        previous_compute += max(times, default=0)
    if previous_compute >= 7200:
        raise ValueError('P2/P3 cumulative two-hour compute budget exhausted')
    budget = CalibrationBudget(session, output, previous_compute)
    source_paths = [*Path(__file__).parent.glob('*.py'), Path(__file__).with_name('desktop_p1.cjs')]
    code = {p.name: sha256(p) for p in source_paths}
    manifest = {'scope': '20_training_family_cost_calibration_not_quality_validation',
                'protocol_fingerprint': protocol['fingerprint'], 'family_ids': [f['id'] for f in selected],
                'runtime': runtime, 'sources': sources, 'code': code, 'paid_calls': 0,
                'B2_scope': 'exact_opening_match_to_frozen_public_P1_recipes_not_all_product_modules',
                'search': {'nodes': 24, 'depth': 6, 'seconds': 2.0, 'width': 2, 'branching': 3},
                'initial_directory_bytes': folder_bytes(ROOT / '.local/ygo-learning')}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    frozen = output / 'source'
    frozen.mkdir()
    for path in source_paths:
        (frozen / path.name).write_bytes(path.read_bytes())
    summaries = []
    condition_folder = CALIBRATION / 'conditions'
    condition_folder.mkdir(exist_ok=True)
    began = time.perf_counter()
    try:
        for ordinal, family in enumerate(selected, first):
            budget.check(disk=True)
            if previous_compute + time.perf_counter() - began >= 7200:
                raise ValueError('P2/P3 cumulative two-hour compute budget exhausted')
            matches = [s for s in sources if s['hand'] == sorted(family['hand'])]
            if matches:
                raise ValueError('A calibration family overlaps the excluded source recipes')
            previous = expansion_hash = initial_observation = None
            for mode in ('B1', 'T0'):
                policy = Policy()
                if previous is None:
                    condition_path = condition_folder / f'{family["id"]}.json'
                    if condition_path.exists():
                        condition = json.loads(condition_path.read_text(encoding='utf-8'))
                        if (condition['protocol_fingerprint'] != protocol['fingerprint'] or
                                condition['runtime'] != str(session.runtime)):
                            raise ValueError('Saved condition belongs to another protocol/runtime')
                        expansion_hash = condition['expansion_sha256']
                        last = latest_condition_session(session.runtime / '_trainer/sessions',
                                                        condition['session'], expansion_hash)
                        state = restart(session, last, expansion_hash)
                    else:
                        opposing = {'name': 'TEST ONLY P3 declared opponent', 'deck': deck(ASH, ASH, ASH),
                                    'opening': [ASH] + [NORMAL] * 4 if family['scenario'] == 'one_ash' else [NORMAL] * 5}
                        state = session.start(protocol['deck'], family['hand'], f'P3-{family["id"]}',
                                              opposing, family['scenario'] == 'one_ash')
                    meta = session.read('session.json')
                    if meta['expansion']['engine_seed'] != family['engine_seed']:
                        raise ValueError('Native test random seed differs from frozen protocol')
                    if sorted(meta['expansion']['actual_opening']) != family['hand'] or meta['deck'] != protocol['deck']:
                        raise ValueError('Native opening/deck differs from the frozen family')
                    expansion_hash = digest(meta['expansion'])
                    initial_observation = build(state, catalog)['observation']
                    if not condition_path.exists():
                        with condition_path.open('x', encoding='utf-8') as stream:
                            json.dump({'protocol_fingerprint': protocol['fingerprint'],
                                       'runtime': str(session.runtime), 'session': session.sid,
                                       'expansion_sha256': expansion_hash}, stream, indent=2)
                    # Saved before either policy runs; neither policy receives this truth.
                    (output / f'{family["id"]}-condition.json').write_text(json.dumps({
                        'family_id': family['id'], 'session': session.sid,
                        'expansion_sha256': expansion_hash, 'initial_observation_sha256': digest(initial_observation)},
                        indent=2), encoding='utf-8')
                else:
                    state = restart(session, previous, expansion_hash)
                    if build(state, catalog)['observation'] != initial_observation:
                        raise ValueError('Paired initial observations differ')
                record = run_policy(session, state, catalog, family, mode, policy, budget, evaluate_goal)
                previous = record['session']['id']
                record.update(expansion_sha256=expansion_hash, B2='no_matching_public_source')
                record = json_value(record)
                # Keep this calibration's uncompressed collector record as well
                # as native evidence until compressed storage is adopted later.
                (output / f'{family["id"]}-{mode}.json').write_bytes(canonical(record))
                path = output / f'{family["id"]}-{mode}.json.gz'
                stats = write_archive(path, record)
                # Explicitly audit the restored record against the untouched native journal.
                audit(read_archive(path))
                summary = {k: record[k] for k in ('family_id', 'scenario', 'mode', 'status', 'replayed',
                          'model_calls', 'nodes', 'multi_choice_windows', 'single_choice_windows',
                          'uncertain_branches', 'seconds', 'goal', 'native_evidence_bytes')}
                summary.update(archive=path.name, storage=stats,
                               proposal_failures=len(record['model_proposal_failures']),
                               execution_error=record.get('error'), B2=record['B2'])
                summaries.append(summary)
                (output / 'progress.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
                print(f'CAL {ordinal}/20 {mode} {record["status"]} goal={record["goal"]["success"]} '
                      f'windows={len(record["steps"])} nodes={record["nodes"]} replay={record["replayed"]}', flush=True)
                if not record['replayed'] or record['status'] in ('execution_error', 'journal_mismatch'):
                    raise ValueError('Calibration reliability gate failed; evidence retained')
            if {p.name: sha256(p) for p in source_paths} != code:
                raise ValueError('Calibration source changed during execution')
    finally:
        try:
            resources = budget.check(disk=True)
        except Exception as error:
            resources = {'budget_stop': str(error), 'peak_sampled_working_bytes': budget.peak,
                         'checked_disk_bytes': budget.disk_peak}
        report = {'scope': manifest['scope'], 'protocol_fingerprint': protocol['fingerprint'],
                  'cases': summaries, 'completed_pairs': len(summaries) // 2,
                  'requested_pairs': len(selected), 'worker_seconds': time.perf_counter() - began,
                  'resources': resources, 'previous_compute_seconds': previous_compute,
                  'directory_bytes': folder_bytes(ROOT / '.local/ygo-learning'),
                  'holdout_opened': False, 'formal_sampling_started': False, 'LLM_calls': 0,
                  'quality_claim': 'not_evaluated_on_independent_validation_families'}
        (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
