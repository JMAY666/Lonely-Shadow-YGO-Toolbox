"""Knowledge adapter acceptance on the real core in a hidden, isolated test host."""
from copy import deepcopy
import json


def run(runtime, evidence, api, start, current, answer, choose, save, finish, wait, session_id):
    assert 'desktop-check-' in str(runtime) and '-modular-knowledge' in str(runtime)
    normal = 1184620
    deck = {'main': [normal] * 40, 'extra': [], 'side': []}
    start(deck, [normal] * 3, 'knowledge source / free-practice fixture')
    choose('summon', normal); choose(place=[0, 4, 1])
    # The fixture has no optional effects; settle actual native acknowledgement windows.
    from modular_decisions import model
    for _ in range(15):
        state = current(); prompt = model(state['raw'], state['state'], state.get('effects'))
        if prompt['message'] == 11: break
        response = next(c['response'] for c in prompt['choices'] if c['semantic']['kind'] in ('pass', 'no'))
        answer(response, state)
    original = save(mark_field=True)
    original_bytes = (runtime / '_trainer/plans' / (original['id'] + '.json')).read_bytes()
    command = lambda op, **body: api('/api/knowledge', {'op': op, **body})
    project = command('project.create', name='TEST ONLY 知识包原生验证', theme='synthetic free practice')
    project = command('project.import-source', id=project['id'], revision=project['revision'],
        kind='plan', source_id=original['id'], source_revision=original['edit_revision'])
    route = next(r['id'] for r in project['document']['records'].values() if r['kind'] == 'route')
    build = next(r['id'] for r in project['document']['records'].values() if r['kind'] == 'build')
    assert project['document']['records'][route]['data']['representation'] == 'decisions'
    body = {'project_id': project['id'], 'route_id': route, 'build_id': build,
            'cases': [{'hand': [normal] * 3, 'scenario': 'none'}],
            'limits': {'seconds': 12, 'nodes': 100, 'depth': 4}}
    job = command('job.start', **body)
    done = wait(lambda: (j if (j := command('job.poll', id=job['id']))['status'] in ('completed', 'failed', 'stale') else None), timeout=120)
    (evidence / 'knowledge-native-job.json').write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding='utf-8')
    assert done['status'] == 'completed', done
    assert done['cases'][0]['status'] == 'passed', done
    assert done['cases'][0]['evidence']['confirmed_candidates'] > 0
    assert done['limits'] == body['limits'], done
    assert done['cases'][0]['evidence']['limits']['depth'] == body['limits']['depth'], done
    assert done['cases'][0]['evidence']['limits']['nodes'] == body['limits']['nodes'], done
    assert (runtime / '_trainer/plans' / (original['id'] + '.json')).read_bytes() == original_bytes
    project = command('project.get', id=project['id'])
    assert any(c['type'] == 'engine' and c['state'] == 'passed' for c in project['inspection']['checks'])
    # A new editing project using identical evidence reuses the checked scene, not new search.
    clone = command('project.import', document=project['document'])
    reused = command('job.start', **{**body, 'project_id': clone['id']})
    reused = wait(lambda: (j if (j := command('job.poll', id=reused['id']))['status'] in ('completed', 'failed', 'stale') else None), timeout=60)
    assert reused['status'] == 'completed' and reused['reused'] == 1, reused
    bundle = command('project.publish', id=project['id'], revision=project['revision'], version='1.0.0')
    pid = bundle['document']['package']['id']
    snapshot = api('/api/knowledge')
    command('package.install', bundle=bundle, digest=bundle['digest'], revision=snapshot['revision'], enable=True)
    library = api('/api/modular/library')
    assert not any(s.get('knowledge_package') == pid for s in library['sources']), 'Installation cannot grant calculation permission'
    snapshot = api('/api/knowledge')
    command('package.compute', package_id=pid, revision=snapshot['revision'], enabled=True)
    library = api('/api/modular/library')
    source = next(s for s in library['sources'] if s.get('knowledge_package') == pid and s.get('available_for_new'))
    assert source['status'] == 'ready', source
    saved = api('/api/deck?id=' + __import__('urllib.parse', fromlist=['quote']).quote(original['selected_deck']))
    request = {'deck_id': saved['id'], 'revision': saved['revision'], 'hand_count': 3, 'hand': [normal] * 3}
    matched = api('/api/duel/match', request)
    assert any(p['id'] == source['id'] and p['knowledge_origin']['version'] == '1.0.0' for p in matched['matches'])
    forecast = api('/api/modular/dispatch', {**request, 'consumer': 'duel', 'intent': 'plan',
        'sources': [source['id']], 'preference': 'shortest'})['result']
    try:
        assert forecast['result']['candidates'], forecast
        project = command('project.get', id=project['id'])
        changed = deepcopy(project['document']); changed['records'][route]['title'] += ' · 新版标题'
        updated = command('project.save', id=project['id'], revision=project['revision'], document=changed)
        assert not updated['impact']['semantic_changed'], updated['impact']
        newer = command('project.publish', id=project['id'], revision=updated['revision'], version='1.1.0')
        command('package.install', bundle=newer, digest=newer['digest'], revision=api('/api/knowledge')['revision'], enable=True)
        new_sources = api('/api/modular/library')['sources']
        pinned = next(s for s in new_sources if s['id'] == source['id'])
        assert pinned['status'] == 'pinned' and not pinned['available_for_new'], pinned
        assert command('package.get', package_id=pid, version='1.0.0')['document']['records'][route]['title'] != changed['records'][route]['title']
        match_new = api('/api/duel/match', request)
        assert not any(p['id'] == source['id'] for p in match_new['matches'])
        assert any(p.get('knowledge_origin', {}).get('version') == '1.1.0' for p in match_new['matches'])
        adopted = api('/api/modular/dispatch', {'consumer': 'duel', 'intent': 'plan-adopt', 'id': forecast['id'],
                                              'candidate': forecast['result']['candidates'][0]['id']})['result']
        assert adopted, 'Pinned v1 candidate remains adoptable without mixing newer steps'
        command('package.disable', package_id=pid, revision=api('/api/knowledge')['revision'])
        assert not any(p.get('knowledge_origin', {}).get('package_id') == pid for p in api('/api/duel/match', request)['matches'])
    finally:
        api('/api/modular/dispatch', {'consumer': 'duel', 'intent': 'plan-close', 'id': forecast['id']})
    (evidence / 'knowledge-native-summary.json').write_text(json.dumps({
        'actual_rule_core': True, 'model_training': False, 'source_id': source['id'], 'job': job['id'],
        'cache_reused': True, 'source_original_unchanged': True, 'installed_not_auto_enabled_for_compute': True,
        'match_and_calculation_adapter': True, 'active_version_pinned': True,
        'scope': 'One synthetic normal-summon scene under free-practice rules, no claim of strategic optimality'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS Knowledge native evidence import, local bounded engine verification, cached scene reuse, permission gate, matching, calculation and pinned-version update', flush=True)
