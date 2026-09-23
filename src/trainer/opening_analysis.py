"""Read-only, source-bound opening resource analysis. Never executes a route."""
from collections import Counter, defaultdict
import hashlib
import json

from actions import project_actions
from card_semantics import card_activation
from duel import checked_rows, resource_error, shortage, Incomplete
from implicit_conditions import check as check_implicit
from opening_conditions import match_hand
from plan_tags import contains_card, matches_set

DEFAULTS = {'dual_ratio': .8, 'dual_minimum': .15, 'representatives': 8}
# Broad card-name search families are useful references, not independent deck engines.
# Preserve TAG membership; exclude only these built-in umbrella labels from this ranking.
SUPPORT_POOLS = {'set:17': 0x17, 'set:46': 0x46}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def concentration(deck, tags, catalog, settings):
    """Group only known numeric parent/subseries, then split shared copies."""
    copies = Counter(deck['main'] + deck['extra'])
    pools = {key: tag for key, tag in tags.items() if key in SUPPORT_POOLS and tag.get('setcode') == SUPPORT_POOLS[key]}
    members = {key: {c for c in copies if contains_card(tag, c, catalog.get(c, {}))}
               for key, tag in tags.items() if tag.get('kind') != 'purpose' and key not in pools}
    members = {key: ids for key, ids in members.items() if ids}
    parents = {key: key for key in members}

    def root(key):
        while parents[key] != key: key = parents[key]
        return key

    keys = sorted(members)
    for index, key in enumerate(keys):
        a = tags[key].get('setcode')
        for other in keys[index+1:]:
            b = tags[other].get('setcode')
            if a and b and (matches_set(a, b) or matches_set(b, a)):
                parents[root(other)] = root(key)
    grouped = defaultdict(list)
    for key in keys: grouped[root(key)].append(key)
    groups = []
    for ids in grouped.values():
        ids.sort(key=lambda k: (-sum(copies[c] for c in members[k]),
                               -int(tags[k].get('setcode') or 0).bit_count(), k))
        groups.append({'id': ids[0], 'name': tags[ids[0]]['name'], 'members': ids,
                       'hierarchy': [tags[k]['name'] for k in ids],
                       'codes': sorted(set().union(*(members[k] for k in ids)))})
    owners = Counter(c for group in groups for c in group['codes'])
    total = sum(copies.values())
    for group in groups:
        group['exclusive'] = sum(copies[c] for c in group['codes'] if owners[c] == 1)
        group['shared'] = sum(copies[c] / owners[c] for c in group['codes'] if owners[c] > 1)
        group['weighted'] = group['exclusive'] + group['shared']
        group['ratio'] = group['weighted'] / total if total else 0
        group['main'] = sum(c in group['codes'] for c in deck['main'])
        group['extra'] = sum(c in group['codes'] for c in deck['extra'])
    groups.sort(key=lambda g: (-g['weighted'], g['id']))
    near = [g['id'] for g in groups[1:] if g['weighted'] / groups[0]['weighted'] >= settings['dual_ratio']
            and g['ratio'] >= settings['dual_minimum']] if groups else []
    ambiguous = len(near) > 1
    return {'total': total, 'groups': groups, 'primary': [] if ambiguous else ([groups[0]['id'], *near] if groups else []),
            'status': '多个系列接近，主系列待核对' if ambiguous else '双主系列' if near else '单主系列' if groups else '未识别系列',
            'unclassified': sum(n for c, n in copies.items() if not owners[c]), 'settings': settings,
            'support_tags': [{'id': key, 'name': tag['name'], 'count': sum(n for c, n in copies.items() if contains_card(tag, c, catalog.get(c, {})))}
                             for key, tag in pools.items() if any(contains_card(tag, c, catalog.get(c, {})) for c in copies)]}


def semantic(value):
    """Drop transport identities/presentation, keep ordered rule-relevant evidence."""
    ignored = {'id', 'instance_id', 'time_ms', 'native_seq', 'byte_offset', 'event_ref', 'event_refs',
               'evidence_refs', 'activation_ref', 'cost_activation_ref', 'resolution_source_ref',
               'effect_id', 'effect_handle', 'handler_instance', 'name', 'summary', 'text', 'node',
               'seq', 'timestamp', 'saved_ms'}
    if isinstance(value, list): return [semantic(v) for v in value]
    if isinstance(value, dict): return {k: semantic(v) for k, v in value.items() if k not in ignored}
    return value


def route_key(report, premises):
    req = report.get('requirements') or {}
    return digest({'resources': {z: [{k: r.get(k) for k in ('code', 'count', 'constraint', 'status')}
                                     for r in req.get(z, [])] for z in ('main', 'extra', 'opening')},
                   'conditions': report.get('expansion', {}).get('conditions'), 'premises': semantic(premises),
                   'events': semantic(report.get('events', [])), 'initial': semantic(report.get('initial_state')),
                   'final': semantic(report.get('final_state')), 'engine': report.get('engine_sha256'),
                   'sources': report.get('sources'), 'catalog': report.get('catalog'),
                   'rule': report.get('rule'), 'turn_order': report.get('expansion', {}).get('turn_order', 'first')})


def terminal(report, catalog):
    state = next((n.get('state') for n in report.get('review', {}).get('nodes', []) if n.get('kind') == 'final'), None) or report.get('final_state') or {}
    marks = report.get('annotations', {}).get('final_marks', {})
    rows = {}
    for card in state.get('cards', []):
        mark = marks.get(str(card.get('instance_id')), {})
        if not mark.get('marked') or not card.get('code') or card.get('controller') != 0: continue
        code = card['code']
        for effect, value in mark.get('effects', {}).items():
            if not value: continue
            key = f'{code}:{effect}'
            row = rows.setdefault(key, {'key': key, 'code': code, 'effect': effect, 'copies': [],
                'name': catalog.get(code, {}).get('name', str(code)), 'status': '待核对',
                'note': '来源标记；共享次数、费用、触发与下回合状态尚未完整验证，不折算阻抗次数'})
            row['copies'].append({'instance': card.get('instance_id'), 'location': card.get('location'),
                                  'disabled': bool(card.get('disabled'))})
    for row in rows.values():
        if all(c['disabled'] for c in row['copies']): row['status'] = '不可用'
    return list(rows.values())


def analyze_routes(plans, deck, hand, catalog, limit):
    unique, errors = {}, []
    for plan in plans:
        anchors = {n.get('id') for n in plan.get('review', {}).get('nodes', [])}
        routes = [(None, plan, {})]
        for branch in plan.get('branches', []):
            if branch.get('valid') is False or not branch.get('report') or branch.get('source', {}).get('node_id') not in anchors:
                errors.append(f"{plan.get('name', '方案')}：分支起点失效或没有完整记录"); continue
            report = {**branch['report'], 'expansion': plan.get('expansion', {})}
            routes.append((branch, report, {'if_condition': branch.get('if_condition'), 'premises': branch.get('premises')}))
        for branch, report, premises in routes:
            source = {'plan_id': plan['id'], 'branch_id': branch.get('id') if branch else None,
                      'name': plan.get('name', '') + (' · ' + branch.get('name', '分支') if branch else ''),
                      'revision': digest(report)}
            try:
                key = route_key(report, premises)
                if key in unique: unique[key]['sources'].append(source); continue
                exact, generic = checked_rows(report.get('requirements'), 'opening')
                resource = resource_error(report, deck)
                # A route needing cards absent from this construction is irrelevant.
                if resource: errors.append(source['name'] + '：' + resource); continue
                condition = check_implicit(report, deck, hand) if hand else {'status': 'pending', 'reason': '尚未录入手牌'}
                opening_error = shortage(report.get('requirements'), 'opening', hand) if hand else ''
                definition = report.get('expansion', {}).get('conditions', {})
                if 'slots' in definition and hand:
                    ok, why = match_hand(hand, definition, catalog)
                    if not ok: opening_error = why
                if any(c in hand for c in definition.get('banned', [])): opening_error = '包含方案禁止上手的组件'
                if opening_error: condition = {'status': 'unmet', 'reason': opening_error}
                independent = not branch or (premises.get('if_condition') or {}).get('kind') == 'unconditional' and (premises.get('if_condition') or {}).get('status') == 'verified' and not premises.get('premises')
                if not independent and condition['status'] == 'satisfied':
                    condition = {'status': 'pending', 'reason': '资源满足，但此分支的受阻场景／额外前提尚未在本局确认'}
                nodes = report.get('review', {}).get('nodes', [])
                recorded = bool(report.get('review', {}).get('complete') and report.get('events') and any(n.get('kind') == 'step' for n in nodes))
                if not recorded: condition = {'status': 'pending', 'reason': '缺少完整录制依据，保留为资料候选'}
                stale = any(catalog.get(int(code), {}).get('desc') != card.get('desc') for code, card in report.get('catalog', {}).items())
                if stale: condition = {'status': 'pending', 'reason': '来源卡文与当前卡库不一致，旧依据待核对'}
                single = sum(exact.values()) + generic == 1 and condition['status'] == 'satisfied'
                if single:
                    minimal = list(exact.elements())
                    single = bool(minimal and check_implicit(report, deck, minimal)['status'] == 'satisfied')
                actions = project_actions(report) if recorded else []
                effects, participants = {}, defaultdict(set)
                for action in actions:
                    for c in action.get('cards', []):
                        if c.get('code') and c.get('controller') == 0: participants[c['code']].add('发动' if action['kind'] == 'effect' else '素材／移动／召唤参与')
                    for role in ('costs', 'targets', 'results'):
                        for item in action.get(role, []):
                            for c in item.get('cards', []):
                                if c.get('code') and c.get('controller') == 0: participants[c['code']].add({'costs': '费用', 'targets': '对象', 'results': '处理参与'}[role])
                    if action['kind'] != 'effect': continue
                    c = next((c for c in action['cards'] if c.get('controller') == 0), None)
                    if not c or not c.get('code'): continue
                    number = action.get('effect_number')
                    activation = card_activation(action, report.get('catalog', {})) if number is None else None
                    # Keep the pre-existing note identity; changing the display label
                    # must not orphan annotations made before activation recognition.
                    eid = f"{c['code']}:{number if number is not None else 'unknown'}"
                    item = effects.setdefault(eid, {'key': eid, 'code': c['code'], 'number': number,
                        'text': action.get('selected_effect_text') or activation or '效果身份待核对',
                        'kind': 'card_activation' if activation else 'effect', 'attempts': 0, 'resolved': 0,
                        'negated': 0, 'applied': 0, 'evidence': []})
                    if number is None and (item['kind'] == 'card_activation') != bool(activation):
                        item.update(kind='mixed', text='卡片发动与尚未对应编号的效果')
                    item['attempts'] += 1
                    item['resolved'] += action['status'] == 'resolved'
                    item['negated'] += action['status'] in ('negated', 'disabled')
                    # Resolution alone does not prove successful resource production.
                    item['applied'] += bool(number is not None and action['status'] == 'resolved' and action.get('results'))
                    item['evidence'].extend(action['evidence_refs'])
                endboard = terminal(report, catalog)
                unique[key] = {'key': key, 'sources': [source], 'opening': [{'code': c, 'count': n} for c, n in exact.items()],
                    'generic_cost': generic, 'required_hand': sum(exact.values()) + generic,
                    'one_card': single,
                    'condition': condition, 'premises': premises, 'verified_sample': recorded and not stale,
                    'effects': list(effects.values()), 'participants': {str(c): sorted(v) for c, v in participants.items()},
                    'endboard': endboard, 'endboard_count': sum(e['status'] != '不可用' for e in endboard),
                    'steps': [a['summary'] for a in actions[:12]], 'idea': report.get('expansion', {}).get('notes', ''),
                    'implicit': condition.get('implicit', {}).get('conditions', []),
                    'relative_unused': [c for c in sorted(set(hand)) if c not in exact and str(c) not in {str(x) for x in participants}],
                    'turn_order': report.get('expansion', {}).get('turn_order', 'first')}
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                errors.append(source['name'] + '：资料无法可靠归纳（' + str(exc)[:100] + '），原文件保留')
    # Diversify by starting requirements before taking second routes per entry.
    ordered = sorted(unique.values(), key=lambda r: (r['condition']['status'] != 'satisfied', not r['verified_sample'], r['required_hand'], r['key']))
    selected, deferred, seen = [], [], set()
    for row in ordered:
        signature = digest(row['opening'])
        (deferred if signature in seen else selected).append(row); seen.add(signature)
    selected = (selected + deferred)[:limit]
    stats = effect_statistics(selected)
    comparisons = []
    for i, a in enumerate(selected):
        for b in selected[i+1:]:
            ea, eb = ({e['key'] for e in r['endboard'] if e['status'] != '不可用'} for r in (a, b))
            if not ea or not eb: continue
            relation = '来源标记效果清单相同' if ea == eb else '来源标记效果更多' if ea < eb or eb < ea else '效果清单不同'
            comparisons.append({'a': a['key'], 'b': b['key'], 'relation': relation,
                'difference': b['endboard_count'] - a['endboard_count'],
                'note': '替代／增强补点候选；起点、费用、次数与其他终场资源仍须核对，不保证能连续执行或结果等价'})
    return {'routes': selected, 'groups': len(unique), 'omitted': max(0, len(unique)-len(selected)),
            'coverage_gaps': ['尚无逐局斩杀／受阻续接验证；现有路线不保证突破未知对手场面',
                              *([f'本次代表方案不足 {limit} 组，保留资料缺口'] if len(selected) < limit else [])],
            'errors': errors, 'effects': stats, 'comparisons': comparisons}


def effect_statistics(routes):
    cards, effects = defaultdict(set), {}
    for route in routes:
        if not route['verified_sample']: continue
        for code in route['participants']: cards[code].add(route['key'])
        for effect in route['effects']:
            item = effects.setdefault(effect['key'], {**effect, 'groups': set(), 'attempts': 0, 'resolved': 0, 'negated': 0, 'applied': 0, 'sources': []})
            for field in ('attempts', 'resolved', 'negated', 'applied'): item[field] += effect[field]
            if effect['applied']: item['groups'].add(route['key'])
            item['sources'].append({'route': route['key'], 'evidence': effect['evidence']})
    rows = []
    for item in effects.values():
        item['sample_count'] = len(cards[str(item['code'])]); item['coverage_count'] = len(item.pop('groups'))
        item['coverage'] = item['coverage_count'] / max(1, item['sample_count'])
        item['card_coverage'] = item['sample_count'] / max(1, sum(r['verified_sample'] for r in routes))
        rows.append(item)
    for item in rows:
        ranked = sorted((x for x in rows if x['code'] == item['code']), key=lambda x: (-x['coverage'], x['key']))
        best = ranked[0]['coverage']
        item['recommendation'] = '主要效果' if item in ranked[:2] and item['sample_count'] >= 3 and item['coverage_count'] and best - item['coverage'] <= .10000001 else '候选'
    return sorted(rows, key=lambda e: (e['code'], -e['coverage'], e['key']))
