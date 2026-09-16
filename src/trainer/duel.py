"""Read-only BO1 matching against the saved library. No engine or plan writes."""
from collections import Counter
from copy import deepcopy


class Incomplete(ValueError):
    pass


def validate_hand(deck, count, hand):
    if type(count) is not int or not 1 <= count <= len(deck['main']):
        raise ValueError('起手张数必须是正整数，且不能超过主卡组总张数')
    if not isinstance(hand, list) or len(hand) != count:
        raise ValueError(f'请完整选择 {count} 张起手卡牌')
    if any(type(code) is not int or code not in deck['main'] for code in hand):
        raise ValueError('起手只能选择当前主卡组中的卡牌')
    if Counter(hand) - Counter(deck['main']):
        raise ValueError('起手同名卡数量超过主卡组实际投入数量')


def checked_rows(summary, zone):
    if not isinstance(summary, dict) or not isinstance(summary.get(zone), list):
        raise Incomplete('缺少资源或起手条件摘要')
    if summary.get('warnings'):
        raise Incomplete('原记录存在未核对的卡牌来源或份数')
    exact, generic = Counter(), 0
    for row in summary[zone]:
        if not isinstance(row, dict) or type(row.get('count')) is not int or row['count'] < 1:
            raise Incomplete('卡牌数量条件无效')
        code, constraint = row.get('code'), row.get('constraint', '')
        if code is None and constraint == '任意手牌':
            if zone == 'extra': raise Incomplete('额外资源不能使用任意手牌条件')
            generic += row['count']
        elif type(code) is int and code > 0:
            # A manually supplied predicate is free text, not a machine-readable
            # OR/set membership expression. Never pretend that identity proves it.
            if row.get('status') == '用户补充' and constraint and constraint != row.get('name'):
                raise Incomplete('用户补充的文字限制需要核对')
            exact[code] += row['count']
        else:
            raise Incomplete('包含尚不能自动判断的卡牌条件')
    return exact, generic


def shortage(summary, zone, available):
    exact, generic = checked_rows(summary, zone)
    pool = Counter(available)
    missing = exact - pool
    if missing:
        return '、'.join(f'卡号 {code} 缺 {count} 张' for code, count in missing.items())
    remaining = sum(pool.values()) - sum(exact.values())
    if remaining < generic: return f'任意手牌资源缺 {generic - remaining} 张'
    return ''


def resource_error(route, deck):
    for zone, label in (('main', '主卡组'), ('extra', '额外卡组')):
        error = shortage(route.get('requirements'), zone, deck[zone])
        if error: return f'{label}资源不足：{error}'
    return ''


def project(plan, deck, hand):
    """Each branch report already includes its inherited prefix. Siblings are
    alternatives, so do not sum their inventories or include the side deck."""
    if plan.get('expansion', {}).get('turn_order', 'first') == 'second':
        return None, 'turn_order', '此方案记录为后手展开，本期仅支持先攻展开'
    try:
        error = resource_error(plan, deck)
        if error: return None, 'resources', error
        error = shortage(plan.get('requirements'), 'opening', hand)
        if error: return None, 'opening', '起手条件不满足：' + error
    except Incomplete as exc:
        return None, 'incomplete', '条件待补全：' + str(exc)
    nodes = plan.get('review', {}).get('nodes', [])
    if not any(n.get('kind') == 'step' for n in nodes):
        return None, 'incomplete', '条件待补全：缺少可导航的步骤记录'
    result = deepcopy(plan)
    result['branches'] = []
    excluded = []
    anchors = {n['id'] for n in nodes}
    for branch in plan.get('branches', []):
        reason = ''
        if not isinstance(branch, dict):
            excluded.append({'id': None, 'name': '旧分支', 'reason': '条件待补全：分支数据无法读取'})
            continue
        source = branch.get('source') or {}
        if not isinstance(source, dict): source = {}
        if branch.get('valid') is False or source.get('node_id') not in anchors:
            reason = '分叉起点失效或无法从主线到达'
        elif not branch.get('report'):
            reason = '分支尚未记录终场'
        elif not isinstance(source.get('seq'), (int, float)):
            reason = '分叉时点待补全'
        else:
            try: reason = resource_error(branch['report'], deck)
            except (Incomplete, AttributeError, TypeError): reason = '条件待补全：分支资源无法可靠读取'
        if reason: excluded.append({'id': branch.get('id'), 'name': branch.get('name'), 'reason': reason})
        else: result['branches'].append(deepcopy(branch))
    result['duel_excluded_branches'] = excluded
    return result, '', ''


def match(store, body):
    with store.lock:
        saved = store.get_deck(body.get('deck_id', ''))
        if saved['revision'] != body.get('revision'):
            raise ValueError('卡组已修改，请返回卡组选择重新确认')
        validate_hand(saved['deck'], body.get('hand_count'), body.get('hand'))
        vocabulary = store.library.all_tags()
        favorites = set(store.plan_favorites()['plans'])
        selected = set(saved['tag_selection']['tag_ids']) & vocabulary.keys()
        result = {'matches': [], 'excluded': [], 'tag_ids': sorted(selected),
                  'counts': {'total': 0, 'tags': 0, 'resources': 0, 'opening': 0, 'incomplete': 0, 'turn_order': 0}}
        if not selected:
            result['reason'] = '当前卡组没有可用 Tag，请在卡组编辑中设置并保存'
            return result
        for path in sorted(store.plans.glob('*.json')):
            result['counts']['total'] += 1
            try:
                plan = store.library.read(path)
                classification = store.library.selection(plan, vocabulary)
                if not selected.intersection(classification['tag_ids']): continue
                result['counts']['tags'] += 1
                projected, stage, reason = project(plan, saved['deck'], body['hand'])
                if projected is None:
                    result['counts'][stage] += 1
                    result['excluded'].append({'id': plan.get('id'), 'name': plan.get('name'), 'stage': stage, 'reason': reason})
                else:
                    projected['favorite'] = projected['id'] in favorites
                    projected['duel_tags'] = [{'id': key, 'name': vocabulary[key]['name']}
                                              for key in classification['tag_ids'] if key in vocabulary]
                    result['matches'].append(projected)
            except (ValueError, KeyError, TypeError, AttributeError, OSError):
                result['counts']['incomplete'] += 1
                result['excluded'].append({'id': path.stem, 'name': '无法读取的旧方案', 'stage': 'incomplete',
                                           'reason': '条件待补全：方案数据无法可靠读取，原文件保留'})
        result['reason'] = ('没有关联 Tag 的方案' if not result['counts']['tags'] else
                            '没有满足资源和起手条件的方案') if not result['matches'] else ''
        return result
