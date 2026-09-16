"""Select a single route from an append-only journal; abandoned evidence stays on disk."""


def route_rows(rows):
    parents, entries, heads, nodes = {}, {}, {}, []
    head = None
    for row in rows:
        kind = row.get('kind')
        if kind == 'rewind':
            target = row.get('target')
            if target not in heads:
                raise ValueError('回退节点缺少原始记录，无法可靠读取当前路线')
            head = heads[target]
        elif kind == 'branch':
            target = row.get('target')
            if target not in nodes:
                raise ValueError('分支节点缺少原始记录，无法可靠读取当前路线')
            discarded = nodes[nodes.index(target) + 1:]
            nodes = nodes[:nodes.index(target) + 1]
            for node in discarded: heads.pop(node, None)
        seq = row['seq']
        parents[seq], entries[seq], head = head, row, seq
        if kind == 'checkpoint':
            node = row['node']
            heads[node] = head
            nodes.append(node)

    def collect(last):
        selected = []
        while last is not None:
            selected.append(entries[last])
            last = parents[last]
        return list(reversed(selected))

    active = collect(head)
    # A restored route's later nodes remain available until the next actual input.
    full = collect(heads[nodes[-1]]) if nodes else active
    return active, full, nodes


def timeline_nodes(rows, actions):
    # The ordinary live timeline retains its familiar settled operation nodes.
    # Fine-grained response checkpoints are exposed separately by compromise.py.
    from module_graph import decision_boundaries, decision_id
    boundaries = [entry['node'] for entry in decision_boundaries(rows) if
                  ('restorable' not in entry['node'] or entry['node'].get('player') == 0 and entry['node'].get('prompt') in (10, 11)
                   and not entry['node'].get('state', {}).get('chain_depth', 0))]
    nodes, used = [], set()
    for index, row in enumerate(boundaries):
        steps = []
        for number, action in enumerate(actions, 1):
            if number in used: continue
            end = max(int(ref.split(':')[0]) for ref in action['evidence_refs'])
            # Do not display a later action ahead of an earlier action whose
            # evidence is still incomplete. Merge that contiguous group later.
            if end > row['seq']: break
            if end <= row['seq']:
                steps.append({'number': number, 'id': action['id'], 'kind': action['kind'],
                              'summary': action['summary'], 'cards': action['cards'],
                              'observed_summary': action.get('observed_summary')})
                used.add(number)
        state = row['state']
        nodes.append({'id': row['node'], 'module_id': decision_id(row), 'ordinal': index, 'initial': index == 0, 'steps': steps,
                      'turn': state['turn'], 'phase': state['phase'], 'lp': state['lp']})
    pending = [{'number': i, 'kind': a['kind'], 'summary': a['summary'], 'cards': a['cards']}
               for i, a in enumerate(actions, 1) if i not in used]
    return nodes, pending
