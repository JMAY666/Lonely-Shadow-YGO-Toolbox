"""Read-only, version-bound projections of effect annotations for product modules.

Purpose suggestions are candidates, never membership, route goals or legal moves.
No personal knowledge or historical record is written by this service.
"""
from copy import deepcopy
import hashlib
import json

from card_annotations import digest, effect_units, _processing_nodes
from intelligence_marks import effect_parts


STATUS_NAMES = {'none': '未标注', 'auto': '自动草稿', 'partial': '部分标注',
                'reviewed': '已核对', 'confirmed': '已确认', 'pending': '待核对',
                'stale': '卡文已变化', 'missing': '当前卡库缺卡', 'mismatch': '与记录卡文不同'}
BOUNDARY = '静态能力参考；费用、对象、时点、共享次数和互斥分支须结合局面核对，不代表当前可发动或可用阻抗次数。'
ROLE_NAMES = {'handtraps': '手坑候选', 'breakers': '解场候选', 'endboards': '终场能力候选'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def processing_nodes(items):
    for _, item in _processing_nodes(items, include_granted=False):
        yield item


def purpose_candidates(effect):
    result = []
    for path, unit in effect_units(effect):
        if unit.get('effect_type') == 'delayed_resolution': continue
        for row in _unit_purpose_candidates(unit):
            result.append({**row, **({'effect_path': path, 'unit_label': unit.get('label', '')} if path else {})})
    return result


def _unit_purpose_candidates(effect):
    """Conservative, explained suggestions from structure, not personal TAGs."""
    structure = effect.get('structure') or {}
    activation = structure.get('activation') or {}
    zones = set(activation.get('zones') or [])
    nodes = list(processing_nodes(structure.get('processing')))
    actions = {row.get('action') for row in nodes}
    disruptive_lock = any(row.get('action') == 'lock' and not row.get('self_only')
                          and not row.get('summon_response_only') and not row.get('attack_response_only') for row in nodes)
    interaction = bool(actions & {'negate_effect', 'negate_activation'}) or disruptive_lock
    removal = {'destroy', 'banish', 'send_grave', 'return_deck', 'return_hand', 'add_hand', 'take_control', 'set_position'}
    opposing_removal = any(row.get('action') in removal and (
        any(zone.startswith('opponent_') for zone in row.get('from_zones') or [])
        or '对方' in (row.get('selector') or {}).get('text', '')) for row in nodes)
    forced_opposing_send = any(row.get('action') == 'require_player_send_grave'
                              and 'opponent' in (row.get('players') or []) for row in nodes)
    opposing_removal = opposing_removal or forced_opposing_send
    result = []
    if 'hand' in zones and activation.get('fast_effect') and (interaction or opposing_removal):
        result.append({'role': 'handtraps', 'label': ROLE_NAMES['handtraps'],
                       'reason': '标注包含手卡发动、快速效果与干扰处理；具体窗口及条件见原文。'})
    if opposing_removal or any(row.get('action') == 'negate_effect' and (
            any(zone.startswith('opponent_') for zone in row.get('from_zones') or [])
            or '对方' in (row.get('selector') or {}).get('text', '')) for row in nodes):
        result.append({'role': 'breakers', 'label': ROLE_NAMES['breakers'],
                       'reason': ('要求对方玩家送走怪兽，未直接作用于怪兽；实际数量及能否使用需要局面核对。'
                                  if forced_opposing_send else '存在处理对方卡牌的分支；对象、费用与能否使用需要另行核对。')})
    if zones & {'monster', 'spell', 'field', 'field_spell', 'pendulum', 'grave', 'banished'} and (
            activation.get('fast_effect') and (interaction or opposing_removal)
            or effect.get('effect_type') in ('continuous', 'spell_continuous') and (disruptive_lock or 'protect' in actions)):
        result.append({'role': 'endboards', 'label': ROLE_NAMES['endboards'],
                       'reason': '具有可供终场考虑的干扰或持续能力；是否作为本方案目标由你选择。'})
    return result


class CardCapabilities:
    def __init__(self, store):
        self.store = store

    @property
    def annotations(self):
        return self.store.card_annotations

    def facts(self, effect):
        registry = self.annotations.registry
        if effect.get('units'):
            rows = [{'label': '效果单元', 'text': '各单元分别匹配条件、费用与次数；不互相借用。'}]
            if effect.get('selection_rule'):
                rows.append({'label': '选择规则', 'text': effect['selection_rule']})
            for unit in effect['units']:
                rows.append({'label': '独立单元', 'text': unit['label']})
                rows.extend({'label': unit['label'] + '·' + row['label'], 'text': row['text']}
                            for row in self.facts(unit))
            return rows
        structure = effect.get('structure') or {}
        activation = structure.get('activation') or {}
        rows = []
        def add(label, value):
            if value: rows.append({'label': label, 'text': value})
        add('效果类别', registry.vocab.get('effect_types', {}).get(effect.get('effect_type'), ''))
        passive = effect.get('effect_type') in ('continuous', 'spell_continuous', 'non_effect', 'no_chain_effect')
        add('处理区域' if effect.get('effect_type') == 'delayed_resolution' else '适用区域' if passive else '发动区域',
            '、'.join(registry.zone_label(v) for v in activation.get('zones') or []))
        add('时点', registry.vocab['timings'].get(activation.get('timing'), ''))
        add('条件', '；'.join(activation.get('conditions') or []))
        add('费用', '；'.join(row.get('text') or registry.vocab['cost_kinds'].get(row.get('kind'), '') for row in structure.get('cost') or []))
        def target_text(row):
            if 'count' in row: quantity = str(row['count'])
            elif 'min_count' in row and 'max_count' in row:
                quantity = (f"至少{row['min_count']}个" if row['max_count'] is None
                            else f"{row['min_count']}至{row['max_count']}个")
            elif isinstance(row.get('count_rule'), dict) and row['count_rule'].get('mode') in ('exact', 'up_to') \
                    and row['count_rule'].get('evaluated_at') == 'activation':
                rule = row['count_rule']
                quantity = ('动态固定：N个' if rule.get('mode') == 'exact'
                            else f"动态上限：{rule.get('minimum', '')}至N个")
                quantity += f"，N＝{rule.get('text', '')}（发动时确定）"
            else: quantity = ''
            return quantity + ' ' + row.get('filter', '')
        add('对象', '；'.join(target_text(row) for row in structure.get('targeting') or []))
        add('次数', '；'.join(registry.usage_label(v) for v in structure.get('usage') or []))
        add('次数说明', structure.get('usage_text'))
        def processing(items, prefix='处理'):
            for row in items or []:
                value = registry.action_label(row.get('action', ''))
                selector = (row.get('selector') or {}).get('text')
                if selector: value += '：' + selector
                if 'min_count' in row and 'max_count' in row:
                    quantity = f"至少{row['min_count']}个" if row['max_count'] is None else f"{row['min_count']}至{row['max_count']}个"
                    value += '；数量 ' + quantity
                rule = row.get('count_rule')
                if isinstance(rule, dict) and rule.get('mode') in ('exact', 'up_to') and rule.get('evaluated_at') in ('activation', 'resolution'):
                    quantity = '动态固定：N个' if rule['mode'] == 'exact' else f"动态上限：{rule.get('minimum', '')}至N个"
                    timing = '发动' if rule['evaluated_at'] == 'activation' else '处理'
                    value += f"；数量 {quantity}，N＝{rule.get('text', '')}（{timing}时确定）"
                if row.get('from_zones'): value += '；来源 ' + '、'.join(registry.zone_label(z) for z in row['from_zones'])
                if row.get('to_zones'): value += '；去向 ' + '、'.join(registry.zone_label(z) for z in row['to_zones'])
                if row.get('restrictions'): value += '；限制 ' + '；'.join(row['restrictions'])
                if row.get('condition'): value += f'；前提 {row["condition"]}'
                if row.get('duration'): value += '；持续 ' + row['duration']
                if row.get('attribute_selection') == 'material_attributes':
                    value += '；动态追加素材怪兽的各属性，持续更新并保留原属性'
                if row.get('action') == 'redirect_battle_damage':
                    names = {'self': '自己', 'opponent': '对方'}
                    value += f'；承受者 {names[row["source_player"]]} → {names[row["recipient"]]}（仍为战斗伤害）'
                add(prefix, value)
                granted = row.get('granted_effect')
                if row.get('action') == 'schedule_resolution' and row.get('scheduled_effect'):
                    add('延迟处理', row['delay'] + '；届时不另开连锁，不支付本次发动费用。')
                    for fact in self.facts(row['scheduled_effect']):
                        add('延迟处理·' + fact['label'], fact['text'])
                elif row.get('action') == 'grant_effect' and isinstance(granted, dict) and isinstance(granted.get('structure'), dict):
                    add('固定获赋效果', '以下效果须另行满足自己的发动或适用条件。')
                    for fact in self.facts(granted):
                        add('固定获赋效果·' + fact['label'], fact['text'])
                else:
                    processing(row.get('then'), '后续处理')
                for index, branch in enumerate(row.get('branches') or []):
                    add(f'分支 {index + 1}', branch.get('condition', '依原文选择或满足条件'))
                    processing(branch.get('actions'), f'分支 {index + 1} 处理')
                    processing(branch.get('then'), f'分支 {index + 1} 后续')
        processing(structure.get('processing'))
        return rows

    def card(self, code, expected_text=None, *, classify=True):
        if type(code) is not int or code <= 0: raise ValueError('卡号必须为正整数')
        if expected_text is not None and (not isinstance(expected_text, str) or len(expected_text) > 50000):
            raise ValueError('用于核对的卡文无效')
        with self.store.lock:
            current = self.store.catalog.cards.get(code)
            result = {'schema': 1, 'code': code, 'name': (current or {}).get('name', str(code)),
                      'status': 'missing', 'trusted': False, 'effects': [], 'tags': [],
                      'relations': [], 'sources': [], 'boundary': BOUNDARY,
                      'text_digest': digest(expected_text) if expected_text is not None else None,
                      'revision': self.annotations.document['revision']}
            if current:
                view = self.annotations.view(code)
                result.update(status=view['status'], text_digest=view['current_text_digest'],
                              no_effect=view['no_effect'], origin=view['origin'])
                if expected_text is not None and digest(expected_text) != view['current_text_digest']:
                    result['status'] = 'mismatch'
                elif view['digest_ok']:
                    result['trusted'] = view['status'] in ('reviewed', 'confirmed', 'partial') and view['origin'] != 'auto'
                    parts = effect_parts(current.get('desc', ''))
                    for effect in view['effects']:
                        if not effect.get('annotated'): continue
                        matches = [str(i) for i, part in enumerate(parts) if digest(part) == digest(effect['text'])]
                        tags = [deepcopy(self.annotations.registry.tags[t]) for t in effect.get('tags', [])]
                        row = {'key': effect['key'], 'text': effect['text'],
                               'label': ('灵摆' if effect['key'].startswith('p') else '怪兽' if current.get('type', 0) & 1 else '')
                                        + (f"效果 {effect['number']}" if effect.get('number') else '前置／未编号文本'),
                               'ref': {'code': code, 'effect_key': effect['key'], 'text_digest': view['text_digest']},
                               'legacy_key': matches[0] if len(matches) == 1 else None,
                               'tags': tags, 'facts': self.facts(effect),
                               'notes': deepcopy(effect.get('notes') or []),
                               'structure': deepcopy(effect.get('structure') or {}),
                               'candidates': purpose_candidates(effect) if result['trusted'] else []}
                        if effect.get('units'):
                            row.update(units=deepcopy(effect['units']), unit_mode=effect['unit_mode'],
                                       selection_rule=effect.get('selection_rule', ''))
                        result['effects'].append(row)
                    result['relations'] = deepcopy(view['relations'])
                    result['sources'] = deepcopy(view['sources'])
                    result['tags'] = list({tag['id']: tag for row in result['effects'] for tag in row['tags']}.values())
            result['status_label'] = STATUS_NAMES[result['status']]
            # Content version includes personal notes/TAGs and vocabulary, not just a file mtime.
            result['version'] = fingerprint({k: v for k, v in result.items() if k != 'revision'})
            knowledge = getattr(self.store, 'annotation_knowledge', None)
            if classify and result['trusted'] and knowledge and knowledge.enabled():
                knowledge.classify(result)
            return result

    def command(self, body):
        if not isinstance(body, dict): raise ValueError('能力资料请求无效')
        if body.get('op') == 'options':
            return {'tags': list(self.annotations.registry.tags.values()), 'roles': ROLE_NAMES}
        if body.get('op') == 'card': return self.card(body.get('code'), body.get('text'))
        rows = body.get('cards')
        if not isinstance(rows, list) or len(rows) > 120 or any(not isinstance(row, dict) for row in rows):
            raise ValueError('每次最多查询 120 张卡片')
        with self.store.lock:
            return {'cards': {str(row.get('code')): self.card(row.get('code'), row.get('text')) for row in rows}}

    def matching_codes(self, tag='', role=''):
        if tag and tag not in self.annotations.registry.tags: raise ValueError('效果能力筛选无效')
        if role and role not in ROLE_NAMES: raise ValueError('用途候选筛选无效')
        with self.store.lock:
            knowledge = getattr(self.store, 'annotation_knowledge', None)
            classified = knowledge.build()['libraries'][role] if role and knowledge and knowledge.enabled() else None
            result = set()
            for code in self.annotations.annotated_codes():
                view = self.annotations.view(code)
                if view['status'] not in ('reviewed', 'confirmed', 'partial') or view['origin'] == 'auto': continue
                # Both filters must match the SAME effect; never join different abilities.
                for effect in view['effects']:
                    if not effect.get('annotated'): continue
                    for path, unit in effect_units(effect):
                        if tag and tag not in unit.get('tags', []): continue
                        if role:
                            if classified is not None and not effect.get('units') and not path:
                                if effect['key'] not in classified.get(str(code), {}).get('effect_keys', []): continue
                            elif not any(row['role'] == role for row in _unit_purpose_candidates(unit)) \
                                    or unit.get('effect_type') == 'delayed_resolution': continue
                        result.add(code); break
            return result

    def freeze_report(self, report):
        """Called only when a new plan is saved; old reports are not backfilled."""
        if 'annotation_snapshot' not in report:
            report['annotation_snapshot'] = {str(code): self.card(int(code), card.get('desc', ''))
                                             for code, card in report.get('catalog', {}).items()}
        for branch in report.get('branches', []):
            if branch.get('report'): self.freeze_report(branch['report'])


def marked_capabilities(targets):
    """Describe marked effects without changing the established route score."""
    tags, effects, unknown = {}, [], 0
    for target in targets:
        snapshot = target.get('capabilities')
        if not snapshot or not snapshot.get('trusted'):
            unknown += 1; continue
        selected = set(target['mark'].get('effects', {}))
        matched = [row for row in snapshot['effects'] if row.get('legacy_key') in selected]
        if len(matched) < len(selected) or not selected: unknown += 1
        for row in matched:
            effects.append({'code': snapshot['code'], 'key': row['key'], 'ref': row['ref'],
                            'facts': row['facts'], 'relations': snapshot['relations']})
            for tag in row['tags']: tags[tag['id']] = tag['name']
    return {'tags': list(tags.values()), 'effects': effects, 'unknown_cards': unknown,
            'basis': '来源方案保存的静态能力；不累计为可用阻抗次数，未保存标注的旧方案保持未知。'}
