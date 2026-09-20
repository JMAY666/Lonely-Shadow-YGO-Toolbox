"""Conservative no-LLM search teacher for the isolated calibration only.

Future draws/reveals terminate a search branch before its state is scored.
The teacher replans after the actual observed event. This is a bounded research
heuristic, not an optimal policy or a claim of usable negation capacity.
"""
import time
from contract_v2 import build, digest, observation, Unsupported
from modular_decisions import next_prompt
from protocol_p2 import ALLOWED_SYNCHRO_IDS as SYNCHROS

STARTERS = {20001443, 55273560, 93490856}
TENYI = {23431858, 23434538, 98159737}


def bounded_search(root, expand, rank, score, *, max_nodes=24, max_depth=6,
                   seconds=2.0, width=2, branching=3):
    if not (0 < max_nodes <= 128 and 0 < max_depth <= 120 and 0 < seconds <= 10):
        raise ValueError('Teacher limits exceed the frozen safety ceiling')
    began = time.monotonic()
    order = rank(root)
    if not order:
        raise ValueError('Teacher has no legal choices')
    best = {index: float('-inf') for index in order}
    frontier = [((), root)]
    trace, failures, uncertain = [], [], 0
    nodes = 0
    stopped = None
    for _ in range(max_depth):
        following = []
        for path, bundle in frontier:
            parent_score = score(bundle)
            for index in rank(bundle)[:branching]:
                if nodes >= max_nodes or time.monotonic() - began >= seconds:
                    break
                child = (*path, index)
                nodes += 1
                item = {'path': list(child)}
                try:
                    result = expand(child)
                except Exception as error:
                    stopped = f'{type(error).__name__}: {error}'
                    failures.append({**item, 'error': stopped})
                    break
                if result.get('error'):
                    failures.append({**item, 'error': result['error']})
                    continue
                if result.get('uncertain'):
                    # Do not inspect, hash, rank, or score the hidden successor.
                    uncertain += 1
                    value = parent_score
                    item.update(boundary='unobserved_random_result', score=value)
                else:
                    successor = result['bundle']
                    value = score(successor)
                    item.update(boundary='observed_scope', score=value,
                                observation_sha256=digest(successor['observation']))
                    if successor['candidates'] and not result.get('ended'):
                        following.append((value, child, successor))
                best[child[0]] = max(best[child[0]], value)
                trace.append(item)
            if stopped or nodes >= max_nodes or time.monotonic() - began >= seconds:
                break
        if stopped or not following or nodes >= max_nodes or time.monotonic() - began >= seconds:
            break
        following.sort(key=lambda row: -row[0])  # Stable source order resolves ties.
        frontier = [(path, bundle) for _, path, bundle in following[:width]]
    chosen = None if stopped else max(order, key=lambda index: best[index])
    expanded_roots = {row['path'][0] for row in trace + failures}
    return {'index': chosen, 'nodes': nodes, 'seconds': time.monotonic() - began,
            'uncertain_branches': uncertain, 'failures': failures, 'trace': trace,
            'stopped': stopped,
            'root_candidates': len(order), 'root_candidates_expanded': len(expanded_roots),
            'root_candidates_omitted': len(order) - len(expanded_roots),
            'source': 'experimental_T0_visible_heuristic_and_frozen_model_proposal',
            'limits': {'nodes': max_nodes, 'depth': max_depth, 'seconds': seconds,
                       'beam_width': width, 'branching': branching}}


def board_score(bundle):
    cards = bundle['observation']['cards']
    own = [c for c in cards if c['controller'] == 0]
    field = [c for c in own if c['location'] == 4 and c['position'] & 5 and not c.get('disabled')]
    bosses = sum(c['code'] in SYNCHROS for c in field)
    return 100 * bosses + 8 * len(field) + .5 * sum(c['location'] == 2 for c in own)


def heuristic_order(bundle, preferred=None):
    """Frozen visible-only proposals; no raw native IDs or deck-order queries."""
    hand = [c['code'] for c in bundle['observation']['cards']
            if c['controller'] == 0 and c['location'] == 2]

    def priority(index):
        public = bundle['candidates'][index]['public']
        context = (public.get('context') or {}).get('handler_code')
        values = []
        for choice in public['selection']:
            kind = choice['kind']
            code = choice.get('card', {}).get('code', 0)
            value = {'summon': 40, 'special': 50, 'activate': 30, 'yes': 35,
                     'no': -5, 'pass': -5, 'end_turn': -30, 'spell_set': -10,
                     'monster_set': -15, 'position': -20, 'cancel_selection': -25,
                     'unselect': -25, 'finish_selection': 30}.get(kind, 0)
            if kind == 'special' and code in SYNCHROS:
                value += 100
            if kind == 'summon' and code in STARTERS:
                value += 50
            if kind == 'activate' and code in STARTERS | TENYI | {69248256, 56465981}:
                value += 35
            if kind in ('card', 'select', 'material'):
                if context == 69248256:  # Chixiao's search; retain duplicate/unknown context ties.
                    value += (40 if code == 93490856 and code not in hand else
                              25 if code == 55273560 and code not in hand else 0)
                elif context == 93490856:
                    value += 25 if code in TENYI else -10 if code in STARTERS else 0
                elif context == 23431858:
                    value += 25 if code == 98159737 else 10 if code == 23434538 else 0
            if kind == 'position_choice':
                value += 1 if choice.get('value') == 1 else 0
            values.append(value)
        return sum(values) + (12 if index == preferred else 0)
    return sorted(range(len(bundle['candidates'])), key=lambda index: (-priority(index), index))


def choose(session, state, catalog, preferred=None, budget_check=None):
    root = build(state, catalog)
    snapshots, bundles, guards = {(): state}, {(): root}, {(): []}
    probes = []

    def expand(path):
        if budget_check:
            budget_check()
        parent = path[:-1]
        previous = snapshots[parent]
        option = bundles[parent]['candidates'][path[-1]]
        guarded = guards[parent] + [previous['raw'] + ':' + option['response']]
        result = session.probe(state, guarded)
        # Raw truth belongs to the evidence collector only, never to score/rank.
        probes.append({'path': list(path), 'guards': guarded, 'result': result})
        if result['status'] != 'ok':
            return {'error': result.get('error', 'probe_failed')}
        try:
            raw, uncertain = next_prompt(result['batches'])
        except ValueError as error:
            return {'error': 'unsupported_packet: ' + str(error)}
        if uncertain or result.get('private_cards'):
            return {'uncertain': True}
        if result.get('ended') or result['state']['turn'] > 1:
            # No further decision is requested at a terminal. The observation
            # perspective remains player 0 even if the next actor is player 1.
            terminal = {**result, 'player': 0, 'answered': False}
            visible, _ = observation(terminal, catalog)
            return {'bundle': {'observation': visible, 'candidates': []}, 'ended': True}
        if not raw:
            return {'error': 'missing_native_decision'}
        if not bytes.fromhex(result['boundary_raw']).endswith(bytes.fromhex(raw)):
            raise ValueError('Probe boundary does not contain its guarded native prompt')
        actor = bytes.fromhex(raw)[2 if bytes.fromhex(raw)[0] == 23 else 1]
        if actor != 0:
            return {'error': 'opponent_boundary'}
        successor = {**result, 'raw': raw, 'player': actor, 'answered': False}
        try:
            bundle = build(successor, catalog)
        except Unsupported as error:
            return {'error': 'unsupported_branch: ' + str(error)}
        snapshots[path], bundles[path], guards[path] = successor, bundle, guarded
        return {'bundle': bundle}

    def rank(bundle):
        return heuristic_order(bundle, preferred if bundle is root else None)

    result = bounded_search(root, expand, rank, board_score)
    result['probes'] = probes
    return result
