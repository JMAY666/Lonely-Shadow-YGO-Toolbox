"""Cross-check controller evidence against the independent native input journal."""
from collections import Counter
import json
from pathlib import Path
import sys
from native_session import ROOT,BASE
sys.path.insert(0,str(ROOT/'src/trainer'))
from module_graph import decision_boundaries
from modular_decisions import model


def audit(record):
    folder=Path(record['session']['folder']).resolve()
    if not folder.is_relative_to(BASE.resolve()):raise ValueError('journal outside isolated experiment')
    rows=[json.loads(line) for line in (folder/'native.jsonl').read_text(encoding='utf-8').splitlines()]
    if rows[0].get('test_control') is not True:raise ValueError('journal is not test-controlled')
    entries=decision_boundaries(rows,folder);by_node={entry['node']['node']:entry for entry in entries}
    controlled={step['before']['node']:step for step in record['steps']}
    if len(controlled)!=len(record['steps']):raise ValueError('duplicate committed checkpoint')
    for node,step in controlled.items():
        entry=by_node[node]
        if entry['node']['raw']!=step['before']['raw'] or len(entry['responses'])!=1:
            raise ValueError('native window/response mismatch')
        response=entry['responses'][0]
        if response['raw']!=step['response'] or response['actor']!='modular_ai':raise ValueError('actual native response differs')
        following=by_node.get(step['after']['node'])
        if not following or following['node']['seq']<=response['seq']:raise ValueError('missing accepted successor')
    auto_empty=opponent=0;coverage=Counter()
    for entry in entries:
        if not entry['responses']:continue
        node=entry['node']
        if node['player']!=0:opponent+=len(entry['responses']);continue
        coverage[node['prompt']]+=1
        if node['node'] in controlled:continue
        raw=bytes.fromhex(node['raw'])
        prompt=model(node['raw'],node['state'],node.get('effects'))
        if raw[0]!=16 or raw[2]!=0 or len(prompt['choices'])!=1:
            raise ValueError('meaningful own decision bypassed the controller')
        auto_empty+=1
    return {'recorded_controller_windows':len(controlled),'automatic_empty_chains':auto_empty,
            'opponent_responses':opponent,'native_answered_windows':sum(len(e['responses']) for e in entries),
            'own_prompt_coverage':dict(coverage),'meaningful_unrecorded_choices':0}
