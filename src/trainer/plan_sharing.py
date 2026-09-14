"""Versioned, data-only plan exchange. No local paths, executable code or sessions."""
from copy import deepcopy
import hashlib
import json
import re

FORMAT, VERSION, MAX_BYTES = 'ygo-trainer-plan', 1, 20 * 1024 * 1024
PLAN_FIELDS = set('name deck_name deck catalog expansion events actions initial_hand initial_hand_ref final_state final_state_ref review annotations requirements started_ms ended_ms duration_ms status end_reason loaded_verified warnings limitations statistics raw_statistics statistics_note report_version record_count active_record_count rule'.split())
EXPANSION_FIELDS = set('name notes conditions actual_opening opponent_ai opponent_responses opponent_config turn_order player_lp opponent_lp timer'.split())
CARD_FIELDS = set('id name desc type alias setcode level atk def race attribute extra script_available'.split()) | {f'str{i}' for i in range(1, 17)}
REF = re.compile(r'^[a-zA-Z0-9:_-]{1,100}$')


def portable(plan):
    result = {key: deepcopy(value) for key, value in plan.items() if key in PLAN_FIELDS}
    result['expansion'] = {key: value for key, value in result.get('expansion', {}).items() if key in EXPANSION_FIELDS}
    opponent = result['expansion'].get('opponent_config')
    if opponent:
        result['expansion']['opponent_config'] = {key: value for key, value in opponent.items() if key in ('name', 'description', 'deck', 'conditions', 'opening')}
    result['catalog'] = {key: {k: v for k, v in value.items() if k in CARD_FIELDS} for key, value in result.get('catalog', {}).items()}
    # A packed setcode can exceed JavaScript's exact integer range. Portable
    # files use decimal strings so browser preview/import never rounds it.
    for card in result['catalog'].values():
        if type(card.get('setcode')) is int: card['setcode'] = str(card['setcode'])
    return result


def fingerprint(document):
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate(document):
    def need(ok, text='分享文件结构无效'):
        if not ok: raise ValueError(text)
    need(isinstance(document, dict) and document.get('format') == FORMAT, '请选择本软件导出的展开方案 JSON 文件')
    need(type(document.get('version')) is int and document['version'] == VERSION, '不支持此分享文件版本，请使用兼容版本的软件')
    # Reject prototype keys, excessive nesting, non-finite numbers and malformed
    # shared shapes before any local file is written or a renderer sees the data.
    budget = [0]
    def walk(value, depth=0, path=()):
        budget[0] += 1
        need(depth <= 35 and budget[0] <= 1_000_000, '分享文件内容过多或嵌套过深')
        if isinstance(value, dict):
            for key, item in value.items():
                need(key not in ('__proto__', 'constructor', 'prototype'), '分享文件包含不支持的字段')
                if key in ('cards', 'materials', 'native_material_cards', 'targets', 'initial_hand') and item is not None and path[-1:] != ('annotations',):
                    need(isinstance(item, list) and all(isinstance(c, dict) for c in item), '卡牌记录格式无效')
                if key == 'lp' and item is not None:
                    need(type(item) is int or isinstance(item, list) and len(item) == 2 and all(type(v) is int for v in item), '生命值记录无效')
                if key == 'setcode' and isinstance(item, str):
                    need(bool(re.fullmatch(r'-?\d{1,20}', item)) and -(2**63) <= int(item) < 2**64, '系列编号无效')
                elif key in ('code', 'instance_id', 'controller', 'location', 'sequence', 'position', 'type', 'setcode', 'native_seq', 'byte_offset', 'number', 'count', 'turn', 'phase', 'chain_depth', 'final_state_ref') and item is not None and not (key == 'type' and isinstance(item, str)):
                    need(type(item) is int, '卡牌或步骤数值无效')
                if key in ('name', 'desc', 'summary', 'text', 'note', 'notes') and item is not None:
                    need(isinstance(item, str), '名称或说明格式无效')
                walk(item, depth + 1, (*path, key))
        elif isinstance(value, list):
            need(len(value) <= 30000, '分享文件列表过长')
            for item in value: walk(item, depth + 1, path)
        elif isinstance(value, str): need(len(value) <= 100000, '分享文件文字过长')
        elif isinstance(value, float): need(False, '分享文件包含不支持的数值')
    walk(document)
    plan = document.get('plan')
    need(isinstance(plan, dict))
    need(isinstance(plan.get('name'), str) and 0 < len(plan['name'].strip()) <= 80, '方案名称无效')
    for key in ('deck', 'catalog', 'expansion', 'statistics'):
        need(isinstance(plan.get(key), dict), f'缺少有效的 {key} 数据')
    for key in ('events', 'actions', 'warnings', 'limitations'):
        need(isinstance(plan.get(key), list), f'缺少有效的 {key} 数据')
    for key in ('warnings', 'limitations'):
        need(all(isinstance(v, str) for v in plan[key]))
    need(set(plan['deck']) == {'main', 'extra', 'side'}, '构筑分区无效')
    for zone, maximum in (('main', 60), ('extra', 15), ('side', 15)):
        cards = plan['deck'].get(zone)
        need(isinstance(cards, list) and len(cards) <= maximum and all(type(c) is int and 0 < c < 2**32 for c in cards), '构筑快照无效')
    for key, card in plan['catalog'].items():
        need(key.isdigit() and isinstance(card, dict) and isinstance(card.get('name'), str) and isinstance(card.get('desc'), str), '冻结卡片资料无效')
        need(type(card.get('type', 0)) is int, '卡片类型无效')
    need(all(str(c) in plan['catalog'] for cards in plan['deck'].values() for c in cards), '缺少构筑中的冻结卡片资料')
    for key in ('events', 'actions'):
        ids = set()
        for item in plan[key]:
            need(isinstance(item, dict) and isinstance(item.get('id'), str) and REF.fullmatch(item['id']), '步骤编号无效')
            need(item['id'] not in ids, '步骤编号重复'); ids.add(item['id'])
            need(isinstance(item.get('cards'), list), '步骤卡牌列表无效')
            if key == 'actions':
                need(isinstance(item.get('evidence_refs'), list) and all(isinstance(v, str) and REF.fullmatch(v) for v in item['evidence_refs']), '步骤依据无效')
                for field in ('costs', 'results', 'execution'):
                    need(isinstance(item.get(field, []), list) and all(isinstance(v, dict) for v in item.get(field, [])), '效果流程无效')
                for step in item.get('execution', []):
                    need(isinstance(step.get('text'), str) and isinstance(step.get('cards'), list), '效果处理记录无效')
    def state(value):
        need(value is None or isinstance(value, dict) and isinstance(value.get('cards'), list), '场面快照无效')
        if value and 'lp' in value: need(isinstance(value['lp'], list) and len(value['lp']) == 2 and all(type(v) is int for v in value['lp']), '生命值记录无效')
    state(plan.get('final_state'))
    review = plan.get('review')
    if review is not None:
        need(isinstance(review, dict) and isinstance(review.get('nodes'), list), '回看节点无效')
        need(len(review['nodes']) >= 2, '缺少初始或终场节点')
        ids = set()
        action_ids = {a['id'] for a in plan['actions']}
        for node in review['nodes']:
            need(isinstance(node, dict) and isinstance(node.get('id'), str) and REF.fullmatch(node['id']) and node['id'] not in ids, '回看节点编号无效')
            ids.add(node['id'])
            need(node.get('kind') in ('initial', 'step', 'final') and type(node.get('number')) is int, '回看节点类型无效')
            need(isinstance(node.get('action_ids'), list) and all(v in action_ids for v in node['action_ids']), '回看动作引用无效')
            state(node.get('state'))
        need(review['nodes'][0]['id'] == 'initial' and review['nodes'][0]['kind'] == 'initial' and review['nodes'][-1]['id'] == 'final' and review['nodes'][-1]['kind'] == 'final', '缺少初始或终场节点')
    from expansion import plan_text, training_settings, validate_conditions
    from review import annotations_for
    plan_text({'name': plan['name'], 'notes': plan['expansion'].get('notes', '')})
    training_settings(plan['expansion'])
    if 'conditions' in plan['expansion']: validate_conditions(plan['deck']['main'], plan['expansion']['conditions'])
    if 'annotations' in plan:
        need(isinstance(plan['annotations'], dict), '方案说明无效')
        annotations_for(plan, plan['annotations'])
    # Validate summary structures without substituting unverified observations.
    if 'requirements' in plan:
        summary = plan['requirements']
        need(isinstance(summary, dict), '条件摘要无效')
        for field in ('main', 'extra', 'opening', 'random', 'costs', 'warnings'):
            need(isinstance(summary.get(field, []), list), '条件摘要条目无效')
        for field in ('main', 'extra', 'opening', 'random'):
            need(all(isinstance(x, dict) for x in summary.get(field, [])), '条件摘要卡牌无效')
            for row in summary.get(field, []):
                need(type(row.get('count')) is int and 0 <= row['count'] <= 60, '条件摘要数量无效')
                for refs in ('nodes', 'uses'):
                    need(isinstance(row.get(refs, []), list) and all(isinstance(v, str) for v in row.get(refs, [])), '条件摘要依据无效')
        need(isinstance(summary.get('final', {}), dict), '终场摘要无效')
    tags = document.get('tags', [])
    need(isinstance(tags, list) and len(tags) <= 30, '分享标签无效')
    seen = set()
    for tag in tags:
        need(isinstance(tag, dict) and isinstance(tag.get('id'), str) and re.fullmatch(r'(set:[0-9a-f]{1,4}|custom:[0-9a-f]{32})', tag['id']), '分享标签编号无效')
        need(tag['id'] not in seen, '分享标签重复'); seen.add(tag['id'])
        need(isinstance(tag.get('name'), str) and 0 < len(tag['name'].strip()) <= 60, '分享标签正名无效')
        need(isinstance(tag.get('aliases'), list) and len(tag['aliases']) <= 30 and all(isinstance(v, str) and 0 < len(v.strip()) <= 60 for v in tag['aliases']), '分享标签别名无效')
        need(type(tag.get('primary')) is bool, '主标签标记无效')
        expected = int(tag['id'][4:], 16) if tag['id'].startswith('set:') else None
        need(tag.get('setcode') == expected, '分享标签系列编号不一致')
        for field in ('include_cards', 'exclude_cards'):
            values = tag.get(field, [])
            need(isinstance(values, list) and len(values) <= 20000 and all(type(c) is int and 0 < c < 2**32 for c in values), '标签卡牌范围无效')
    return {'format': FORMAT, 'version': VERSION, 'plan': portable(plan),
            'tags': [{**{k: deepcopy(t[k]) for k in ('id', 'name', 'aliases', 'setcode', 'primary')},
                      **{k: deepcopy(t[k]) for k in ('include_cards', 'exclude_cards') if k in t}} for t in tags]}
