"""Editable sample from shipped public research; no invented engine verification."""
from copy import deepcopy
import json
from pathlib import Path

from knowledge_schema import new_document


def sample_document():
    root = Path(__file__).parent
    opponents = json.loads((root / 'opponents.json').read_text(encoding='utf-8'))
    matchups = json.loads((root / 'matchups.json').read_text(encoding='utf-8'))
    doc = new_document('烙印 · 知识包制作样例', '烙印')
    doc['package'].update(id='sample-branded-public', environment='Master Duel · 2026年8—9月资料快照',
                          description='两套公开构筑、两条资料路线、一条条件妥协与一份对策。未逐条引擎验证，不代表当前禁限合法性。')
    records = doc['records']

    def add(key, kind, title, data, refs=(), tags=()):
        records[key] = {'id': key, 'kind': kind, 'revision': 1, 'title': title,
                        'tags': list(tags), 'data': deepcopy(data),
                        'refs': [{'id': r, 'relation': 'uses'} for r in refs]}
        return key

    # Keep original list, period, attribution and research flags as editable evidence.
    ids = ['md-202608-branded-ehl6l', 'md-202609-branded-p3rn1']
    chosen = [next(d for d in opponents['decks'] if d['id'] == identifier) for identifier in ids]
    source_ids = {s for d in chosen for s in d['source_ids']}
    for d in chosen:
        for route in d['routes']: source_ids.update(route['source_ids'])
    add('source-decks', 'source', '原始公开构筑与路线 · 2026-09-20 核对', {
        'content': {'revision': opponents['revision'], 'checked_at': opponents['checked_at'], 'decks': chosen,
                    'periods': [p for p in opponents['periods'] if p['id'] in {d['period_id'] for d in chosen}],
                    'sources': [s for s in opponents['sources'] if s['id'] in source_ids]},
        'note': '保留原资料；本样例只重组展示，不增加引擎验证声明。'})
    add('shared-conditions', 'fragment', '本样例共用适用边界', {
        'steps': ['shared-step'], 'representation': 'tutorial',
        'conditions': '明确先攻、通常召唤权限、起手和卡组资源；未指定的手牌、对方响应保持未知。',
        'notes': '共用文字说明不代表不同构筑下的路线已经互换验证。'})
    add('shared-step', 'step', '核对实际资源', {'cards': [], 'action': '核对所列起手、额外资源与次数限制。',
        'result': '未满足条件时停止套用教程；已消耗费用与权限不恢复。', 'costs': '', 'targets': '', 'limits': ''})
    for index, deck in enumerate(chosen, 1):
        b, r = f'build-{index}', f'route-{index}'
        # Distinct mechanisms, with original per-build prerequisites retained.
        route = deck['routes'][0 if index == 1 else 1]
        cards = lambda rows: [row['code'] for row in rows for _ in range(row['quantity'])]
        add(b, 'build', deck['name'] + (' · 八月' if index == 1 else ' · 九月'), {
            'main': cards(deck['main']), 'extra': cards(deck['extra']),
            'side': None if deck['side'] is None else cards(deck['side']),
            'conditions': deck.get('legality_status', 'as_published_not_revalidated'),
            'notes': '原始构筑快照；未重新核对当前环境禁限。', 'source_id': deck['id']}, ['source-decks'], deck['tag_ids'])
        steps = []
        for step in route['steps']:
            key = f'{r}-{step["id"]}'; steps.append(key)
            add(key, 'step', step['action'], {**step, 'costs': '详见原始动作及结果，待单独结构化核对',
                'targets': '按当前步骤与实际合法对象核对', 'limits': route.get('notes', '')}, ['source-decks'])
        add(r, 'route', route['title'], {'steps': steps, 'representation': 'strategy',
            'opening': {'cards': cards(route['opening']['cards']), 'other_cards': route['opening']['other_cards'],
                        'notes': route['opening']['conditions']},
            'conditions': route['opening']['conditions'], 'notes': route['notes'],
            'source_validation': route['validation'], 'replay_ready': False}, [b, 'shared-conditions'], deck['tag_ids'])
        add(f'endboard-{index}', 'endboard', route['title'] + ' · 关键终场', {
            'cards': cards(route['endboard']), 'effects': [], 'resources': json.dumps(route['endboard'], ensure_ascii=False),
            'constraints': '仅列来源明确说明的关键资源；效果费用、互斥及同名次数未完成结构化核对，不累计阻抗。',
            'notes': '预期终场，非本机引擎实测。'}, [r])
    guide = next(g for g in matchups['guides'] if g['id'] == 'md-branded')
    add('source-counter', 'source', '原始烙印对策与卡文引用', {'content': {
        'version': matchups['version'], 'reviewed_at': matchups['reviewed_at'], 'guide': guide,
        'sources': [s for s in matchups['sources'] if s['id'] in guide['source_ids']]}})
    breakpoint = next(s for s in guide['steps'] if s['opponent'] == 73819701)
    add('compromise-1', 'branch', '白龙之落胤登场效果受阻 · 条件资料', {
        'anchor': 'route-1-s02', 'route': 'route-1', 'timing': breakpoint['timing'],
        'interference': '假设登场拉怪效果被无效；尚未录制实际干扰事件。',
        'resources': '已支付的额外送墓费用与场上白龙之落胤继续保留；其他手牌未知。',
        'conditions': breakpoint['condition'], 'notes': breakpoint['note'] + '\n这里只记录条件和可保留资源；后续完整操作需另行补录与验证。',
        'continuation': '核对墓地已送入的融合怪兽，在适用结束阶段条件成立时再处理其效果。'},
        ['source-counter'])
    add('countermeasure-1', 'countermeasure', guide['title'], {
        'opponent': '烙印', 'situation': breakpoint['action'],
        'responses': '\n'.join(f"{r['method']}\n前提：{r['condition']}\n预期：{r['expected']}" for r in breakpoint['responses']),
        'exceptions': breakpoint['note'], 'notes': '2026-09-20 资料快照；属于人工条件推演，尚未逐场景引擎验证。'},
        ['source-counter', 'route-1-s02'])
    return doc
