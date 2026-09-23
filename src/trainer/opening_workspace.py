"""Opening analysis API and versioned personal overlays, separate from sources."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from duel import validate_hand
from intelligence_staples import load_catalog
from intelligence_marks import effect_parts
from opening_analysis import DEFAULTS, digest, concentration, analyze_routes

ROLE_NAMES = {'handtrap': '手坑', 'breaker': '解场', 'protection': '护航', 'resource': '资源补充'}


def reviewed_effects(catalog, public):
    result = {}
    for card in public['cards']:
        code = card['code']
        if code not in catalog: continue
        parts = effect_parts(card['desc'])
        for label, notes in card['effects'].items():
            matches = [part for part in parts if (not part.lstrip().startswith(tuple('①②③④⑤⑥⑦⑧⑨⑩')) if label == 'text' else part.lstrip().startswith((label + '：', label + ':')))]
            if len(matches) != 1: continue
            roles = []
            if 'handtraps' in card['groups']: roles.append('handtrap')
            if 'breakers' in card['groups']: roles.append('breaker')
            if code in (24224830, 65681983): roles.append('protection')
            if card['groups'].get('handtraps') == 'draw-pressure': roles.append('resource')
            key = f'{code}:{label}'
            result[key] = {'key': key, 'code': code, 'name': catalog[code]['name'], 'text': matches[0],
                'roles': roles, 'allowed_roles': roles, 'priority': 'primary', 'note': '',
                'condition': card['condition'], 'explanation': notes,
                'source': {'id': public['id'], 'checked_on': public['checked_on'],
                           'url': f'https://www.db.yugioh-card.com/yugiohdb/card_search.action?ope=2&cid={card["konami_id"]}&request_locale=ja'},
                'version': digest({'card': card, 'current_text': catalog[code].get('desc'), 'source': public['id']}),
                'reviewed': catalog[code].get('desc') == card['desc']}
    return result


class OpeningWorkspace:
    def __init__(self, store, read, write, now):
        self.store, self.read, self.write, self.now = store, read, write, now
        self.path = store.root / 'opening-analysis-v1.json'

    def document(self):
        if not self.path.exists():
            return {'schema': 1, 'revision': 0, 'settings': dict(DEFAULTS), 'overrides': {}, 'notes': {}, 'candidates': {}}
        try:
            value = self.read(self.path)
            if (not isinstance(value, dict) or value.get('schema') != 1 or type(value.get('revision')) is not int
                    or value['revision'] < 0 or any(not isinstance(value.get(k), dict) for k in ('settings', 'overrides', 'notes', 'candidates'))):
                raise ValueError()
            self.settings(value['settings'])
            for key, row in value['overrides'].items():
                if not isinstance(key, str) or not isinstance(row, dict) or not isinstance(row.get('version'), str): raise ValueError()
                self.presentation(row.get('value'), list(ROLE_NAMES))
            for row in value['notes'].values():
                if not isinstance(row, dict) or not isinstance(row.get('version'), str) or not isinstance(row.get('text'), str): raise ValueError()
            for row in value['candidates'].values():
                if not isinstance(row, dict) or not isinstance(row.get('version'), str): raise ValueError()
                self.presentation(row.get('value'), list(ROLE_NAMES))
            return value
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            raise ValueError('起手分析个人资料缺损或版本不支持；原文件保留，请从备份恢复，不能按空资料覆盖') from None

    @staticmethod
    def settings(value):
        if not isinstance(value, dict) or set(value) != set(DEFAULTS): raise ValueError('分析参数字段无效')
        for key in ('dual_ratio', 'dual_minimum'):
            if type(value[key]) not in (int, float) or not 0 < value[key] <= 1: raise ValueError('双主阈值应在 0 与 1 之间')
        if type(value['representatives']) is not int or not 1 <= value['representatives'] <= 10: raise ValueError('代表方案数量应为 1—10')
        return deepcopy(value)

    @staticmethod
    def presentation(value, allowed):
        if not isinstance(value, dict) or set(value) != {'roles', 'priority', 'note'}: raise ValueError('只允许修改通用用途、展示优先与备注；规则和局部角色只读')
        roles = value['roles']
        if not isinstance(roles, list) or any(not isinstance(v, str) or v not in allowed for v in roles) or len(roles) != len(set(roles)):
            raise ValueError('用途必须来自该效果已核对的候选集合，且不能重复')
        if value['priority'] not in ('primary', 'secondary'): raise ValueError('展示优先级无效')
        if not isinstance(value['note'], str) or len(value['note']) > 4000: raise ValueError('备注最多 4000 字')
        return deepcopy(value)

    def knowledge(self, document):
        public = load_catalog()
        effects = reviewed_effects(self.store.catalog.cards, public)
        protection = json.loads((Path(__file__).parent / 'opening-protection.json').read_text('utf-8'))
        effects.update(reviewed_effects(self.store.catalog.cards, protection))
        for key, effect in effects.items():
            override = document['overrides'].get(key)
            effect['override'] = override
            effect['override_stale'] = bool(override and (override['version'] != effect['version'] or not effect['reviewed']))
            if override and not effect['override_stale']: effect.update(deepcopy(override['value']))
            effect['candidate'] = document['candidates'].get(key)
            effect['candidate_stale'] = bool(effect['candidate'] and effect['candidate']['version'] != effect['version'])
        return effects

    def automatic_input(self, body):
        """Copy a server-owned frozen snapshot; client cannot supply its hand."""
        recognition = body.get('recognition_id')
        if recognition:
            smart = self.store.ygopro_smart
            with smart.lock:
                job = smart.jobs.get(recognition)
                if not job or not smart.current(job) or job['stage'] != 'second' or job.get('reading_error'):
                    raise ValueError('自动识别已失效，请重新监测本局')
                frame = deepcopy(job['frame'])
                saved = deepcopy(job['construction'])
                saved['name'] = '自动识别本局构筑'
        else:
            monitor = self.store.ygopro_order
            with monitor.lock:
                frame = monitor.public()
                if frame.get('monitor_id') != body.get('monitor_id'): raise ValueError('先后攻监测已变化')
                if frame.get('phase') != 'detected': raise ValueError('本局监测已失效')
                saved = self.store.automatic_duel.checked_input(body.get('deck_context'),
                    self.store.ygopro_capture.submitted_deck(monitor.capture_id), (frame.get('opening') or {}).get('cards', []))
        opening = frame.get('opening') or {}
        if (frame.get('confirmed') or {}).get('order') != 'second' or opening.get('status') != 'ready' or not opening.get('snapshot_id'):
            raise ValueError('请先确认本局后攻与完整起手')
        if body.get('round_id') != frame.get('round_id') or body.get('snapshot_id') != opening['snapshot_id']:
            raise ValueError('本局或起手快照已变化，请重新分析')
        return saved['deck'], list(opening['cards']), {'kind': 'automatic', 'recognition_id': recognition,
            'round_id': frame['round_id'], 'snapshot_id': opening['snapshot_id'], 'name': saved['name']}

    def inputs(self, body):
        if body.get('source') == 'automatic':
            deck, frozen, source = self.automatic_input(body)
        else:
            saved = self.store.get_deck(body.get('deck_id', ''))
            if body.get('revision') != saved['revision']: raise ValueError('构筑已变化，请重新选择')
            deck, frozen = saved['deck'], body.get('hand', [])
            if not isinstance(frozen, list): raise ValueError('起手格式无效')
            source = {'kind': 'manual', 'name': saved['name'], 'deck_id': saved['id'], 'revision': saved['revision']}
        supplemental = body.get('supplemental', [])
        if not isinstance(supplemental, list) or len(supplemental) > 60: raise ValueError('人工补充手牌格式无效')
        if frozen: validate_hand(deck, len(frozen), frozen)
        hand = list(frozen) + supplemental
        if hand: validate_hand(deck, len(hand), hand)
        return deck, frozen, supplemental, source

    def analyze(self, body):
        deck, frozen, supplemental, source = self.inputs(body)
        with self.store.lock:
            document = self.document()
            knowledge = self.knowledge(document)
            tags = self.store.library.all_tags()
            plans, read_errors = [], []
            for path in sorted(self.store.plans.glob('*.json')):
                try:
                    plan = self.read(path)
                    if not isinstance(plan, dict) or not plan.get('id'): raise ValueError()
                    plans.append(plan)
                except (ValueError, OSError): read_errors.append(f'方案 {path.stem} 无法读取；原文件保留')
            hand = frozen + supplemental
            routes = analyze_routes(plans, deck, hand, self.store.catalog.cards, document['settings']['representatives'])
            routes['errors'] += read_errors
            codes = set(deck['main'] + deck['extra'])
            effects = [value for value in knowledge.values() if value['code'] in codes]
            counts = Counter(hand)
            cards = []
            for code, count in counts.items():
                entries = [e for e in effects if e['code'] == code]
                roles = sorted({role for e in entries if e['reviewed'] for role in e['roles']})
                cards.append({'code': code, 'count': count, 'name': self.store.catalog.cards.get(code, {}).get('name', str(code)),
                    'roles': roles, 'status': '已核对通用资料' if roles else '用途待补充／依方案判断',
                    'effects': [e['key'] for e in entries]})
            warnings = self.conflicts(counts, knowledge, routes['routes'])
            version = digest({'deck': deck, 'tags': tags, 'plans': [digest(p) for p in plans],
                              'catalog': self.store.catalog.sources, 'knowledge': {k: v['version'] for k, v in knowledge.items()}})
            result = {'schema': 1, 'revision': document['revision'], 'source_version': version, 'source': source,
                'frozen': frozen, 'supplemental': supplemental, 'hand_count': len(hand), 'cards': cards,
                'handtrap_count': sum(c['count'] for c in cards if 'handtrap' in c['roles']),
                'concentration': concentration(deck, tags, self.store.catalog.cards, document['settings']),
                'knowledge': effects, 'role_names': ROLE_NAMES, 'analysis': routes, 'warnings': warnings,
                'notes': document['notes'], 'settings': document['settings'],
                'boundary': '仅分析已知起手资源；持有不等于已经发动。手坑张数不等于可用次数，未知对手场面不作补全。',
                'direction': '现有终场效果可供比较；斩杀与长盘收益待真实场面核对，不提供保证值。'}
        # A late analysis of a closed/changed round must never be accepted.
        if body.get('source') == 'automatic' and self.inputs(body) != (deck, frozen, supplemental, source):
            raise ValueError('本局输入已变化，请重新分析')
        return result

    @staticmethod
    def conflicts(counts, effects, routes):
        reviewed = {e['code'] for e in effects.values() if e['reviewed']}
        held = set(counts) & reviewed
        rows = []
        def add(codes, text):
            rows.append({'codes': codes, 'text': text, 'sources': [e['source'] for e in effects.values() if e['code'] in codes]})
        if 94145021 in held:
            draw = sorted(held & {23434538, 42141493, 84192580, 87126721})
            if draw: add([94145021, *draw], '若锁鸟已适用，本回合双方不能从卡组加手，抽牌威慑不能继续获得抽牌收益；持有两者不代表限制已生效。')
        if 91800273 in held:
            add([91800273], '次元吸引者要求我方墓地为空并把自身从手牌送墓；若其效果已适用，双方送墓改为除外，持续至下回合结束。先送其他牌入墓可能失去发动条件。')
            if held & {23434538, 94145021}:
                add([91800273, *sorted(held & {23434538, 94145021})], '吸引者已适用后，增殖的G／锁鸟不能支付送墓费用；发动前、连锁中与已适用状态须区分。')
            affected = [r['sources'][0]['name'] for r in routes if any(c.get('location') == 16 for c in r['implicit'])]
            if affected: add([91800273], '自身依赖墓地资源的方案需重核：' + '、'.join(affected))
            else: add([91800273], '自身送墓费用、墓地触发与回收路线需重核；当前资料不足以证明我方不受影响。')
        if 54693926 in held: add([54693926], '冥王结界波适用的回合，对方受到的所有伤害为 0；不能把使用后本回合斩杀计作已成立。')
        return rows

    def command(self, body):
        allowed = {'action', 'revision', 'source_version', 'key', 'version', 'value', 'input'}
        if not isinstance(body, dict) or set(body) - allowed: raise ValueError('包含只读或未知字段')
        action = body.get('action')
        if body.get('key') is not None and not isinstance(body['key'], str): raise ValueError('编辑目标格式无效')
        if not isinstance(body.get('input'), dict) or body['input'].get('source') == 'automatic':
            raise ValueError('请在情报站选择本地构筑后维护资料')
        if action not in ('settings', 'override', 'restore', 'note', 'suggest', 'apply'):
            raise ValueError('起手资料操作无效')
        # Do not acquire a monitor lock while holding store.lock.
        analysis = self.analyze(body.get('input') or {})
        with self.store.lock:
            document = self.document()
            if type(body.get('revision')) is not int or body['revision'] != document['revision']:
                raise ValueError('个人资料已更新，请刷新后核对；当前输入请保留')
            # Sources may have changed after the first analysis acquired the lock.
            fresh = self.analyze({**(body.get('input') or {}), 'source': 'manual'}) if (body.get('input') or {}).get('source') != 'automatic' else analysis
            if body.get('source_version') != fresh['source_version']: raise ValueError('源资料版本已过期，请重新归纳')
            key = body.get('key')
            if action == 'settings': document['settings'] = self.settings(body.get('value'))
            elif action == 'note':
                if not isinstance(key, str) or key not in {'deck', *(r['key'] for r in analysis['analysis']['routes']), *(e['key'] for e in analysis['analysis']['effects'])}:
                    raise ValueError('局部备注目标不存在')
                value = body.get('value')
                if not isinstance(value, str) or len(value) > 4000: raise ValueError('备注最多 4000 字')
                document['notes'][key] = {'text': value, 'version': fresh['source_version'], 'source': 'human', 'saved_ms': self.now()}
            else:
                effects = self.knowledge(document)
                effect = effects.get(key)
                if not effect or not effect['reviewed']: raise ValueError('只可编辑已核对的通用效果；局部角色只读')
                if body.get('version') != effect['version']: raise ValueError('卡文或效果依据已变化，旧版本不能应用')
                if action == 'restore': document['overrides'].pop(key, None)
                elif action == 'suggest':
                    # Locally generated using the very same allowlist as human edits.
                    value = self.presentation({'roles': effect['allowed_roles'], 'priority': 'primary', 'note': ''}, effect['allowed_roles'])
                    document['candidates'][key] = {'value': value, 'version': effect['version'], 'source': 'local-catalog',
                                                  'evidence': effect['source'], 'saved_ms': self.now()}
                else:
                    if action == 'apply':
                        candidate = document['candidates'].get(key)
                        if not candidate or candidate['version'] != effect['version']: raise ValueError('候选已过期，请重新归纳')
                        value = candidate['value']
                    else: value = body.get('value')
                    document['overrides'][key] = {'value': self.presentation(value, effect['allowed_roles']),
                        'version': effect['version'], 'source': 'human', 'evidence': effect['source'], 'saved_ms': self.now()}
            previous = self.document()
            self.write(self.store.root / 'backups/opening-analysis' / f"{previous['revision']}.json", previous)
            document['revision'] += 1
            self.write(self.path, document)
        return {'revision': document['revision']}
