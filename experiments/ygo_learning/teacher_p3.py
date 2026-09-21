"""Bounded, visible-only T0 teacher for the frozen public training calibration."""
import time
from contract_v2 import build, digest, observation, Unsupported
from modular_decisions import model, next_prompt
from protocol_p2 import ALLOWED_SYNCHRO_IDS as SYNCHROS

STARTERS = {20001443, 55273560, 56495147}
TENYI = {23431858, 87052196, 98159737}
CONFIG = {'version': 'T0-correction-v5', 'nodes': 24, 'depth': 12,
          'seconds': 2.0, 'width': 2, 'branching': 3}


def decision_key(bundle):
    return digest([bundle['observation'], [c['public'] for c in bundle['candidates']]])


def opponent_response(raw, scenario):
    """Respond to declared conditions, never infer a hidden opponent hand."""
    data = bytes.fromhex(raw)
    actor = data[2] if data[0] == 23 else data[1]
    if actor != 1:
        raise Unsupported('not_an_opponent_boundary')
    if scenario == 'one_ash':
        # This conditional simulation uses the same pinned policy as the
        # experimental opponent. It is not an inference about an unknown hand.
        return {'response': 'ai', 'source': 'declared_one_ash_core_policy'}
    if scenario != 'no_extra_response':
        raise Unsupported('unknown_opponent_scenario')
    # Only public pass/no flags affect this choice, never hidden hand identities.
    prompt = model(raw, {}, {})
    for choice in prompt['choices']:
        if choice['semantic']['kind'] in ('pass', 'no'):
            return {'response': choice['response'], 'source': 'explicit_no_response'}
    raise Unsupported('opponent_has_no_declared_pass')


def bounded_search(root, expand, rank, score, *, max_nodes=24, max_depth=6,
                   seconds=2.0, width=2, branching=3, uncertainty_bonus=None):
    if not (0 < max_nodes <= 128 and 0 < max_depth <= 120 and 0 < seconds <= 10
            and 0 < width <= 8 and 0 < branching <= 64):
        raise ValueError('Teacher limits exceed the frozen safety ceiling')
    began = time.monotonic()
    deadline = began + seconds
    order = rank(root)
    if not order:
        raise Unsupported('no_untried_legal_choices')
    best = {index: float('-inf') for index in order}
    frontier = [((), root, 0)]
    trace, failures, uncertain = [], [], 0
    nodes = 0
    stopped = None
    while frontier and nodes < max_nodes and time.monotonic() < deadline:
        following = []
        for path, bundle, depth in frontier:
            parent_score = score(bundle)
            for index in rank(bundle)[:branching]:
                if nodes >= max_nodes or time.monotonic() >= deadline or depth >= max_depth:
                    break
                child = (*path, index)
                allowance = min(max_nodes - nodes, max_depth - depth)
                item = {'path': list(child)}
                try:
                    if getattr(expand, 'accepts_budget', False):
                        result = expand(child, allowance, deadline)
                    else:
                        result = expand(child)
                except Exception as error:
                    consumed = max(1, getattr(expand, 'attempted_nodes', 1))
                    if consumed > allowance:
                        raise ValueError('Interrupted expansion exceeded its allowance') from error
                    nodes += consumed
                    stopped = f'{type(error).__name__}: {error}'
                    failures.append({**item, 'error': stopped, 'decision_nodes': consumed})
                    break
                consumed = result.get('decision_nodes', 1)
                if type(consumed) is not int or not 1 <= consumed <= allowance:
                    raise ValueError('Search expansion exceeded its native decision allowance')
                nodes += consumed
                item.update(decision_nodes=consumed, native_depth=depth + consumed,
                            opponent_steps=result.get('opponent_steps', []),
                            forced_steps=result.get('forced_steps', []))
                if result.get('error'):
                    failures.append({**item, 'error': result['error']})
                    continue
                if result.get('uncertain'):
                    # Neither score nor rank may inspect this hidden successor.
                    uncertain += 1
                    value = parent_score
                    if uncertainty_bonus:
                        value += uncertainty_bonus(bundle)
                    item.update(boundary='unobserved_random_result', score=value)
                else:
                    successor = result['bundle']
                    value = score(successor)
                    item.update(boundary='observed_scope', score=value,
                                observation_sha256=digest(successor['observation']))
                    if successor['candidates'] and not result.get('ended') and depth + consumed < max_depth:
                        following.append((value, child, successor, depth + consumed))
                best[child[0]] = max(best[child[0]], value)
                trace.append(item)
            if stopped or nodes >= max_nodes or time.monotonic() >= deadline:
                break
        if stopped or not following:
            break
        following.sort(key=lambda row: -row[0])
        frontier = [(path, bundle, depth) for _, path, bundle, depth in following[:width]]
    valid = [index for index in order if best[index] != float('-inf')]
    chosen = None if stopped or not valid else max(valid, key=lambda index: best[index])
    expanded_roots = {row['path'][0] for row in trace + failures}
    return {'index': chosen, 'nodes': nodes, 'seconds': time.monotonic() - began,
            'uncertain_branches': uncertain, 'failures': failures, 'trace': trace,
            'stopped': stopped or ('no_evaluable_search_branch' if chosen is None else None),
            'root_candidates': len(root['candidates']), 'root_candidates_expanded': len(expanded_roots),
            'root_candidates_omitted': len(root['candidates']) - len(expanded_roots),
            'source': CONFIG['version'],
            'limits': {'nodes': max_nodes, 'depth': max_depth, 'seconds': seconds,
                       'beam_width': width, 'branching': branching}}


def board_score(bundle, goal=None, actual_draw_count=0):
    """Heuristic progress, never a claim that an interruption remains usable."""
    observed = bundle['observation']
    own = [c for c in observed['cards'] if c['controller'] == 0]
    field = [c for c in own if c['location'] == 4 and c['position'] & 5 and not c.get('disabled')]
    allowed = set((goal or {}).get('allowed_synchro_codes') or SYNCHROS)
    bosses = sum(c['code'] in allowed for c in field)
    hand = [c for c in own if c['location'] == 2]
    minimum_hand = (goal or {}).get('minimum_retained_hand_cards', 1)
    # A summon must not erase all starter value just because the once-per-turn
    # normal summon has been spent: its currently legal effect can still start
    # the line. Potential is derived from offered legal actions, not card text.
    normal_available = observed.get('normal_used', 0) < observed.get('normal_limit', 1)
    starter_access = normal_available and any(c['code'] in {20001443, 55273560, 56495147} for c in hand)
    offered = [selection for candidate in bundle.get('candidates', [])
               for selection in candidate['public']['selection']]
    effect_access = any(s['kind'] in ('activate', 'yes') and
                        s.get('card', {}).get('code') in STARTERS | {93490856, 56465981}
                        for s in offered)
    synchro_access = any(s['kind'] == 'special' and s.get('card', {}).get('code') in allowed
                         for s in offered)
    value = (100 * min(bosses, 1) + 8 * min(len(hand), minimum_hand) +
             3 * min(len(field), 2) + 10 * (starter_access or effect_access) +
             50 * (synchro_access and not bosses) + .1 * len(hand))
    if (bundle.get('_terminal') and bosses >= 1 and len(hand) >= minimum_hand and
            actual_draw_count >= (goal or {}).get('minimum_actual_draw_count', 0)):
        value += 25
    return value


def heuristic_order(bundle, preferred=None, proposals=()):
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
            if kind == 'special' and code == 69248256:
                value += 30
            if kind == 'summon' and code in STARTERS:
                value += 50
            if kind == 'activate' and code in STARTERS | TENYI | {69248256, 56465981, 93490856}:
                value += 35
            if kind in ('card', 'select', 'material'):
                if context in (69248256, 56465981, 55273560):
                    value += (40 if code == 20001443 and code not in hand and
                              bundle['observation'].get('normal_used', 0) == 0 else
                              35 if code == 93490856 and code not in hand else
                              25 if code == 20001443 and context == 55273560 else 0)
                elif context == 93490856:
                    value += 25 if code in TENYI else -10 if code in STARTERS else 0
                elif context == 23431858:
                    value += 25 if code == 98159737 else 10 if code == 23434538 else 0
            if kind == 'position_choice':
                value += 1 if choice.get('value') == 1 else 0
            values.append(value)
        return sum(values) + (12 if index == preferred else 0) + (20 if index in proposals else 0)
    return sorted(range(len(bundle['candidates'])), key=lambda index: (-priority(index), index))


def microchoice(bundle):
    """Frozen placement/position heuristic, reported separately from search.

    This scope does not claim these choices are universally interchangeable.
    All offered choices remain recorded and the selected response is replayed.
    """
    messages = {c['public']['message'] for c in bundle['candidates']}
    if messages in ({18}, {19}):
        return {'index': heuristic_order(bundle)[0], 'nodes': 0, 'uncertain_branches': 0,
                'source': 'declared_first_legal_zone_attack_position_heuristic'}
    if messages in ({15}, {20}, {23}, {26}):
        forward = [i for i, c in enumerate(bundle['candidates']) if not c['public']['cancel']
                   and c['public']['selection'] and all(s['kind'] not in
                       ('cancel_selection', 'unselect') for s in c['public']['selection'])]
        if len(forward) == 1:
            return {'index': forward[0], 'nodes': 0, 'uncertain_branches': 0,
                    'source': 'declared_unique_completion_over_cancel_heuristic'}
    return None


def choose(session, state, catalog, preferred=None, budget_check=None, *,
           scenario='no_extra_response', goal=None, actual_draw_count=0,
           blocked_responses=(), avoid_state_keys=(), proposal_library=None):
    root = build(state, catalog)
    snapshots, bundles, guards = {(): state}, {(): root}, {(): []}
    keys = {(): {decision_key(root)}}
    probes = []
    proposed = {}

    def expand(path, allowance, deadline):
        expand.attempted_nodes = 0
        parent = path[:-1]
        previous = snapshots[parent]
        option = bundles[parent]['candidates'][path[-1]]
        guarded = guards[parent] + [previous['raw'] + ':' + option['response']]
        consumed, opponent_steps, forced_steps = 0, [], []
        branch_keys = set(keys[parent])
        while True:
            if budget_check:
                budget_check()
            consumed += 1
            expand.attempted_nodes = consumed
            result = session.probe(state, guarded)
            probes.append({'path': list(path), 'guards': list(guarded), 'result': result})
            meta = {'decision_nodes': consumed, 'opponent_steps': list(opponent_steps),
                    'forced_steps': list(forced_steps)}
            if result['status'] != 'ok':
                return {**meta, 'error': result.get('error', 'probe_failed')}
            try:
                raw, uncertain = next_prompt(result['batches'])
            except ValueError as error:
                return {**meta, 'error': 'unsupported_packet: ' + str(error)}
            if uncertain or result.get('private_cards'):
                return {**meta, 'uncertain': True}
            if result.get('ended') or result['state']['turn'] > 1:
                terminal = {**result, 'player': 0, 'answered': False}
                visible, _ = observation(terminal, catalog)
                return {**meta, 'bundle': {'observation': visible, 'candidates': [],
                                           '_terminal': True}, 'ended': True}
            if not raw:
                return {**meta, 'error': 'missing_native_decision'}
            if not bytes.fromhex(result['boundary_raw']).endswith(bytes.fromhex(raw)):
                raise ValueError('Probe boundary does not contain its guarded native prompt')
            data = bytes.fromhex(raw)
            actor = data[2 if data[0] == 23 else 1]
            if actor == 1:
                if consumed >= allowance or time.monotonic() >= deadline:
                    return {**meta, 'error': 'bounded_opponent_boundary'}
                reply = opponent_response(raw, scenario)
                guarded.append(raw + ':' + reply['response'])
                opponent_steps.append({'prompt': raw, **reply})
                continue
            if actor != 0:
                return {**meta, 'error': 'unknown_boundary_actor'}
            successor = {**result, 'raw': raw, 'player': actor, 'answered': False}
            try:
                bundle = build(successor, catalog)
            except Unsupported as error:
                return {**meta, 'error': 'unsupported_branch: ' + str(error)}
            # Advance only declared deterministic microchoices. Each one gets
            # its own guarded native probe and consumes node AND depth budget.
            forced = ({'index': 0, 'source': 'unique_legal_choice'}
                      if len(bundle['candidates']) == 1 else microchoice(bundle))
            key = decision_key(bundle)
            # Consecutive empty acknowledgement windows can have the same
            # observation. Only strategic decisions qualify as policy cycles.
            if forced is None:
                if key in branch_keys or key in avoid_state_keys:
                    return {**meta, 'error': 'visible_decision_cycle'}
                branch_keys.add(key)
            if forced is not None and consumed < allowance and time.monotonic() < deadline:
                response = bundle['candidates'][forced['index']]['response']
                forced_steps.append({'prompt': raw, 'response': response, 'source': forced['source']})
                guarded.append(raw + ':' + response)
                continue
            snapshots[path], bundles[path], guards[path] = successor, bundle, guarded
            keys[path] = branch_keys
            return {**meta, 'bundle': bundle}

    expand.accepts_budget = True

    def rank(bundle):
        proposals = []
        if proposal_library is not None:
            snapshot = next((snapshots[key] for key, value in bundles.items() if value is bundle), None)
            if snapshot:
                matches = proposal_library.propose(snapshot, bundle)
                proposals = list(matches)
                proposed[decision_key(bundle)] = matches
        order = heuristic_order(bundle, preferred if bundle is root else None, proposals)
        if bundle is root:
            order = [i for i in order if bundle['candidates'][i]['response'] not in blocked_responses]
        return order

    def uncertain_progress(bundle):
        # Reward reaching an observation opportunity when the goal asks for a
        # draw. No unknown card identity or hidden successor score enters here.
        required = (goal or {}).get('minimum_actual_draw_count', 0)
        draw_pending = any(((chain.get('effect') or {}).get('category') or 0) & 0x20000
                           for chain in bundle['observation'].get('chains', []))
        return 15 if required > actual_draw_count and draw_pending else 0

    result = bounded_search(root, expand, rank, lambda b: board_score(b, goal, actual_draw_count),
                            max_nodes=CONFIG['nodes'], max_depth=CONFIG['depth'],
                            seconds=CONFIG['seconds'], width=CONFIG['width'],
                            branching=CONFIG['branching'], uncertainty_bonus=uncertain_progress)
    result['proposals'] = proposed
    result['probes'] = probes
    result['blocked_responses'] = list(blocked_responses)
    result['preferred'] = preferred
    return result
