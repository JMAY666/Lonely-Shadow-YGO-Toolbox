"""Shared decision boundaries for Step, replay, branches and modular search.

Step IDs remain annotation anchors. Their states and temporal connections are
projections of this graph; only recorded native decisions can become executable
source edges. A legacy observation is never promoted to a decision.
"""
from copy import deepcopy

from modular_decisions import digest, model, public_state, semantic_response, response_bindings


def decision_id(row):
    return str(row.get('node', 'seq:' + str(row['seq'])))


def decision_boundaries(rows, folder=None):
    boundaries = []
    for row in rows:
        if row.get('kind') == 'checkpoint':
            node = deepcopy(row)
            if not node.get('raw') and folder is not None and 'node' in node:
                restore = folder / f"restore-{node['node']}.txt"
                if restore.exists():
                    lines = restore.read_text(encoding='utf-8').splitlines()
                    if len(lines) > 3: node['raw'] = lines[3]
            boundaries.append({'node': node, 'responses': []})
        elif row.get('kind') == 'response' and boundaries:
            boundaries[-1]['responses'].append(row)
    return boundaries


def visible_state(state):
    if state is None: return None
    value = public_state(state)
    for card in value.get('cards', []):
        card['identity_known'] = bool(card.get('code')) and not card.get('unknown')
        if not card['identity_known']: card.update(code=None, name='未知卡牌')
    return value


def attach_modules(review, report, rows=None):
    """Attach a graph to a new projection, or adapt frozen legacy data in memory."""
    if review.get('module_graph', {}).get('schema') == 1:
        return project_steps(review)
    modules, connections = [], []
    boundaries = decision_boundaries(rows or [])
    for index, entry in enumerate(boundaries):
        node = entry['node']
        own = node.get('player') == 0
        module = {'id': decision_id(node), 'seq': node['seq'], 'kind': 'decision',
                  'checkpoint': node.get('node'), 'player': node.get('player'),
                  'prompt': node.get('prompt'), 'state': visible_state(node.get('state')),
                  'raw': node.get('raw') if own else None,
                  'effects': deepcopy(node.get('effects', {})) if own else {},
                  'restorable': bool(node.get('restorable')), 'status': 'recorded'}
        modules.append(module)
        if index + 1 >= len(boundaries): continue
        edge = {'from': module['id'], 'to': decision_id(boundaries[index+1]['node']),
                'response_refs': [r['seq'] for r in entry['responses']],
                'status': 'incomplete', 'reusable': False}
        if len(entry['responses']) == 1:
            edge['status'] = 'observed'
            if own and node.get('raw'):
                try:
                    prompt = model(node['raw'], node['state'], node.get('effects'))
                    decision = semantic_response(prompt, entry['responses'][0]['raw'])
                    exact = all(not c.get('effect') or c['effect'].get('operation_line') is not None
                                for c in decision.get('selection', []))
                    edge.update(decision=decision, bindings=response_bindings(prompt, entry['responses'][0]['raw']), status='recorded' if exact else 'incomplete', reusable=exact)
                except (ValueError, KeyError, IndexError, TypeError, StopIteration):
                    pass
        connections.append(edge)
    by_seq = {m['seq']: m for m in modules}
    for step in review['nodes']:
        seq = step.get('state_ref')
        module = by_seq.get(seq) if seq is not None else None
        if module is None:
            key = f'observed:{seq}' if seq is not None else 'unknown:' + step['id']
            module = next((m for m in modules if m['id'] == key), None)
            if module is None:
                module = {'id': key, 'seq': seq, 'kind': 'observation',
                          'state': visible_state(step.get('state')), 'restorable': False,
                          'status': 'legacy' if rows is None else 'observed' if step.get('state') else 'incomplete'}
                modules.append(module)
                if seq is not None: by_seq[seq] = module
        step['module_id'] = module['id']
        start, end = step.get('range', [seq, seq])
        step['module_ids'] = [m['id'] for m in modules if start is not None and end is not None
                              and m['seq'] is not None and start <= m['seq'] <= end]
        if module['id'] not in step['module_ids']: step['module_ids'].append(module['id'])
    modules.sort(key=lambda m: (m['seq'] is None, m['seq'] or 0, m['id']))
    links = []
    for previous, following in zip(review['nodes'], review['nodes'][1:]):
        lo, hi = previous.get('state_ref'), following.get('state_ref')
        path = [m['id'] for m in modules if lo is not None and hi is not None and m['seq'] is not None and lo <= m['seq'] <= hi]
        links.append({'from': previous['id'], 'to': following['id'], 'from_module': previous['module_id'],
                      'to_module': following['module_id'], 'module_path': path,
                      'status': 'legacy' if rows is None else 'recorded' if path else 'incomplete'})
    graph = {'schema': 1, 'source': report.get('id'), 'modules': modules,
             'connections': connections, 'step_links': links,
             'step_order': [n['id'] for n in review['nodes']]}
    graph['revision'] = digest(graph)
    review['module_graph'] = graph
    return project_steps(review)


def project_steps(review):
    graph = review['module_graph']
    modules = {m['id']: m for m in graph['modules']}
    steps = {step['id']: step for step in review['nodes']}
    # The compatibility state field is derived afresh, never an alternate truth.
    review['nodes'] = [steps[key] for key in graph['step_order'] if key in steps]
    for step in review['nodes']:
        module = modules.get(step.get('module_id'), {})
        step['state'] = deepcopy(module.get('state'))
        step['module_status'] = module.get('status', 'incomplete')
        step['previous'] = [edge['from'] for edge in graph['step_links'] if edge['to'] == step['id']]
        step['next'] = [edge['to'] for edge in graph['step_links'] if edge['from'] == step['id']]
    return review
