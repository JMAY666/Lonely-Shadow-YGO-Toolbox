"""Unified per-effect card annotations: segmentation, tags, structure, coverage and query.

This module holds STATIC capability knowledge: what a card's printed text says.
Whether an effect can be activated, will resolve or forms a combo in a live
duel stays with the rule engine and recorded state; a tag hit is never an
activation verdict (docs/card-annotation-system.md).

Identity rules mirror the rest of the toolbox: cards are integer codes from
the installed catalog, effect keys are stable per frozen card text, and every
annotation is validated against the current text digest (fail-closed like
card_semantics.AUDITED_EFFECTS).
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from card_semantics import AUDITED_EFFECTS, CIRCLED

CLAUSE = re.compile(r'(?m)(?:^|(?<=[。]))[ \t]*([' + CIRCLED + r'])\s*[:：]')
PENDULUM_MONSTER_MARKER = re.compile(r'【怪兽(?:效果|描述)】')
PENDULUM_HEADER = re.compile(r'(?m)^[^\n]*【灵摆】[^\n]*$')
TAG_ID = re.compile(r'etag:[a-z0-9-]+')
HEX64 = re.compile(r'[0-9a-f]{64}')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
RELATION_KINDS = {'material_rule', 'summon_condition', 'shared_limit', 'usage_limit_group',
                  'exclusive_choice', 'choose_branch', 'order', 'depends_on'}
STATUSES = ('none', 'auto', 'partial', 'reviewed', 'confirmed', 'pending', 'stale')
CONDITION_FIELDS = ('action', 'from_zone', 'to_zone', 'usage', 'cost_kind', 'timing')

# Implied destinations keep queries honest when an annotation omits to_zones:
# the action itself names the zone it moves a card to.
DEFAULT_DESTINATION = {'add_hand': 'hand', 'draw': 'hand', 'special_summon': 'monster',
                       'normal_summon': 'monster', 'return_deck': 'deck', 'banish': 'banished',
                       'send_grave': 'grave'}

# Draft patterns are deliberately conservative: they propose candidates with
# the matched snippet as evidence and never mark anything reviewed.
DRAFT_PATTERNS = (
    (re.compile(r'(?:从|在)[^。；\n]{0,16}?(卡组|墓地|除外|额外卡组)[^。；\n]{0,24}?(?:加入手[卡牌]|回到手[卡牌])'), 'add_hand_source'),
    (re.compile(r'(?:加入手[卡牌]|回到手[卡牌])'), 'add_hand'),
    (re.compile(r'特殊召唤'), 'special_summon'),
    (re.compile(r'进行[^。；\n]{0,8}召唤'), 'normal_summon'),
    (re.compile(r'破坏'), 'destroy'),
    (re.compile(r'(?!除外状态)[^。；\n]{0,24}除外'), 'banish'),
    (re.compile(r'发动[^。；\n]{0,8}?无效'), 'negate_activation'),
    (re.compile(r'无效'), 'negate_effect'),
    (re.compile(r'(?:回到|放回)[^。；\n]{0,12}卡组'), 'return_deck'),
    (re.compile(r'确认[^。；\n]{0,8}?手卡|观看[^。；\n]{0,8}?手卡'), 'hand_reveal'),
    (re.compile(r'翻开'), 'deck_reveal'),
    (re.compile(r'这个卡名[^。；\n]{0,16}?1回合[^。；\n]{0,10}?只能[^。；\n]{0,12}?1次'), 'name_limit'),
)
DRAFT_TAG = {'add_hand': 'etag:add-hand', 'add_hand_source': 'etag:add-hand',
             'special_summon': 'etag:special-summon', 'normal_summon': 'etag:normal-summon',
             'destroy': 'etag:destroy', 'banish': 'etag:banish',
             'negate_effect': 'etag:negate-effect', 'negate_activation': 'etag:negate-activation',
             'return_deck': 'etag:return-deck', 'hand_reveal': 'etag:hand-look',
             'deck_reveal': 'etag:deck-look'}
DRAFT_SOURCE_ZONE = {'卡组': 'deck', '墓地': 'grave', '除外': 'banished', '额外卡组': 'extra'}


def digest(text):
    """Same normalization as card_semantics.effect_clause so AUDITED digests align."""
    return hashlib.sha256((text or '').replace('\r\n', '\n').strip().encode('utf-8')).hexdigest()


def block_segments(block, prefix, out):
    if not block.strip(): return
    matches = list(CLAUSE.finditer(block))
    numbers = [CIRCLED.index(match[1]) + 1 for match in matches]
    if numbers and len(set(numbers)) == len(numbers):
        leading = block[:matches[0].start()].strip()
        if leading:
            out.append({'key': f'{prefix}-pre', 'block': prefix, 'number': None, 'kind': 'unnumbered', 'text': leading})
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
            number = numbers[index]
            out.append({'key': f'{prefix}{number}', 'block': prefix, 'number': number, 'kind': 'numbered',
                        'text': block[match.start():end].strip()})
    else:
        out.append({'key': f'{prefix}-all', 'block': prefix, 'number': None,
                    'kind': 'ambiguous' if numbers else 'unnumbered', 'text': block.strip()})


def segments(desc, card_type):
    """Split frozen card text into stable per-effect segments (p*/m* keys)."""
    text = (desc or '').replace('\r\n', '\n').strip()
    result = []
    if card_type & 0x1000000:
        marker = PENDULUM_MONSTER_MARKER.search(text)
        pendulum, monster = (text[:marker.start()], text[marker.end():]) if marker else (text, '')
        block_segments(PENDULUM_HEADER.sub('', pendulum).strip(), 'p', result)
        block_segments(monster.strip(), 'm', result)
    else:
        block_segments(text, 'm', result)
    return result


class Registry:
    """Generic effect tags and controlled vocabularies, shared by every annotator."""

    def __init__(self, document):
        if document.get('version') != 1: raise ValueError('效果 TAG 词表版本不受支持')
        self.updated_on = document.get('updated_on', '')
        self.categories = document.get('vocabularies', {}).get('categories', {})
        self.tags = {}
        for tag in document.get('tags', []):
            identifier = tag.get('id', '')
            if not TAG_ID.fullmatch(identifier) or identifier in self.tags: raise ValueError(f'效果 TAG 编号无效：{identifier}')
            if tag.get('category') not in self.categories: raise ValueError(f'效果 TAG 分类无效：{identifier}')
            if not tag.get('name') or not tag.get('definition'): raise ValueError(f'效果 TAG 缺少名称或定义：{identifier}')
            self.tags[identifier] = tag
        self.vocab = {}
        for name, values in document.get('vocabularies', {}).items():
            if name == 'categories': continue
            if not isinstance(values, dict) or not values: raise ValueError(f'受控词表无效：{name}')
            self.vocab[name] = values

    def require(self, vocabulary, value, where):
        values = self.vocab.get(vocabulary)
        if values is None or value not in values:
            raise ValueError(f'{where}使用了未登记的{vocabulary}取值：{value}')
        return value

    def zone_label(self, value): return self.vocab.get('zones', {}).get(value, value)
    def action_label(self, value): return self.vocab.get('actions', {}).get(value, value)
    def usage_label(self, value): return self.vocab.get('usage_limits', {}).get(value, value)
    def tag_order(self, tag): return (self.tags[tag]['name'], tag)


def _check_text(value, where, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{where}文本无效')
    return value.strip()


def _check_notes(value, where):
    if not isinstance(value, list): raise ValueError(f'{where}备注无效')
    for item in value:
        if not isinstance(item, dict): raise ValueError(f'{where}备注格式无效')
        _check_text(item.get('text', ''), f'{where}备注')
        refs = item.get('source_refs', [])
        if not isinstance(refs, list) or any(not isinstance(r, str) or len(r) > 600 for r in refs):
            raise ValueError(f'{where}备注来源无效')


def _check_processing(items, registry, where):
    if not isinstance(items, list): raise ValueError(f'{where}处理无效')
    for item in items:
        if not isinstance(item, dict): raise ValueError(f'{where}处理项无效')
        registry.require('actions', item.get('action'), where)
        count = item.get('count')
        if count is not None and not (isinstance(count, int) or count in ('all', 'up_to_1') or re.fullmatch(r'\d+', str(count))):
            raise ValueError(f'{where}数量无效')
        for field in ('from_zones', 'to_zones'):
            zones = item.get(field)
            if zones is not None:
                if not isinstance(zones, list) or not zones: raise ValueError(f'{where}{field}无效')
                for zone in zones: registry.require('zones', zone, where)
        selector = item.get('selector')
        if selector is not None and (not isinstance(selector, dict) or not selector.get('text')):
            raise ValueError(f'{where}选择器缺少文字说明')
        if item.get('then') is not None: _check_processing(item['then'], registry, f'{where}后续')
        if item.get('branches') is not None:
            branches = item['branches']
            if not isinstance(branches, list): raise ValueError(f'{where}分支无效')
            for branch in branches:
                if not isinstance(branch, dict): raise ValueError(f'{where}分支格式无效')
                _check_text(branch.get('condition', '分支'), f'{where}分支条件', 400)
                _check_processing(branch.get('actions', []), registry, f'{where}分支')
                if branch.get('then') is not None: _check_processing(branch['then'], registry, f'{where}分支后续')
        for restriction in item.get('restrictions', []):
            _check_text(restriction, f'{where}限制', 400)


def validate_entry(entry, registry, segment_keys=None, where=''):
    """Structural validation; segment_keys (when given) must cover the frozen text."""
    where = where or f"卡牌 {entry.get('code')}"
    if not isinstance(entry.get('code'), int) or not 0 < entry['code'] < 2**32: raise ValueError(f'{where}卡号无效')
    if not HEX64.fullmatch(entry.get('text_digest') or ''): raise ValueError(f'{where}卡文指纹无效')
    review = entry.get('review', {})
    if review.get('status') not in ('reviewed', 'draft') or review.get('origin') not in ('manual', 'auto', 'engine'):
        raise ValueError(f'{where}审核状态无效')
    if not DATE.fullmatch(review.get('checked_on') or ''): raise ValueError(f'{where}核对日期无效')
    _check_notes(entry.get('notes', []), where)
    seen = set()
    for effect in entry.get('effects', []):
        key = effect.get('key')
        if key in seen: raise ValueError(f'{where}效果键重复：{key}')
        seen.add(key)
        if segment_keys is not None and key not in segment_keys:
            raise ValueError(f'{where}效果键 {key} 不在当前卡文分段中，请核对卡文')
        if effect.get('kind') not in ('numbered', 'unnumbered', 'ambiguous'): raise ValueError(f'{where}效果 {key} 类型无效')
        for tag in effect.get('tags', []):
            if tag not in registry.tags: raise ValueError(f'{where}效果 {key} 使用未登记 TAG：{tag}')
        structure = effect.get('structure', {})
        if not isinstance(structure, dict): raise ValueError(f'{where}效果 {key} 结构无效')
        activation = structure.get('activation')
        if activation is not None:
            if activation.get('timing'): registry.require('timings', activation['timing'], f'{where}效果 {key}')
            for zone in activation.get('zones', []): registry.require('zones', zone, f'{where}效果 {key}')
            for condition in activation.get('conditions', []): _check_text(condition, f'{where}效果 {key}条件', 400)
        for cost in structure.get('cost', []):
            registry.require('cost_kinds', cost.get('kind'), f'{where}效果 {key}费用')
            if cost.get('text'): _check_text(cost['text'], f'{where}效果 {key}费用', 400)
        for target in structure.get('targeting', []):
            if not isinstance(target.get('count'), int) or target['count'] < 0: raise ValueError(f'{where}效果 {key}对象数量无效')
            _check_text(target.get('filter', '对象'), f'{where}效果 {key}对象', 400)
        _check_processing(structure.get('processing', []), registry, f'{where}效果 {key}')
        for usage in structure.get('usage', []): registry.require('usage_limits', usage, f'{where}效果 {key}')
        _check_notes(effect.get('notes', []), f'{where}效果 {key}')
        if effect.get('engine') is not None and not isinstance(effect['engine'], dict):
            raise ValueError(f'{where}效果 {key} 引擎依据无效')
    for relation in entry.get('relations', []):
        if relation.get('kind') not in RELATION_KINDS: raise ValueError(f'{where}效果关系类型无效')
        _check_text(relation.get('text', '关系'), f'{where}效果关系', 800)
        for key in relation.get('effects', []):
            if key not in seen: raise ValueError(f'{where}关系引用了未标注的效果：{key}')
    return entry


def draft_entry(code, segs, text_digest):
    """Conservative auto candidates; origin stays auto and is never counted as reviewed."""
    effects = []
    for seg in segs:
        matched, tags, processing, usage = [], [], [], []
        for pattern, kind in DRAFT_PATTERNS:
            hit = pattern.search(seg['text'])
            if not hit: continue
            matched.append({'kind': kind, 'basis': hit[0][:80]})
            if kind == 'name_limit':
                usage.append('shared_name_once' if '任意' in hit[0] else 'name_soft_opt')
                continue
            tag = DRAFT_TAG.get(kind)
            if tag and tag not in tags: tags.append(tag)
            if kind in ('add_hand', 'add_hand_source', 'special_summon', 'normal_summon', 'return_deck',
                        'destroy', 'banish', 'negate_effect', 'negate_activation', 'hand_reveal', 'deck_reveal'):
                item = {'action': 'add_hand' if kind.startswith('add_hand') else kind,
                        'evidence': hit[0][:80]}
                if kind == 'add_hand_source':
                    item['from_zones'] = [DRAFT_SOURCE_ZONE[hit[1]]]
                processing.append(item)
        if not matched: continue
        effects.append({'key': seg['key'], 'kind': seg['kind'], 'number': seg['number'], 'block': seg['block'],
                        'tags': tags,
                        'structure': {name: value for name, value in (('processing', processing), ('usage', usage)) if value},
                        'notes': [{'text': '自动提取候选：按词表模式匹配卡文片段生成，未经人工或引擎核对，仅作待核对草稿。',
                                   'source_refs': ['auto-draft']}]})
    return {'code': code, 'text_digest': text_digest,
            'review': {'status': 'draft', 'origin': 'auto', 'checked_on': '', 'basis': '自动提取（词表模式匹配）'},
            'effects': effects, 'relations': [], 'notes': []}


class CardAnnotations:
    """Curated (in-repo) + personal (runtime) annotation layers under one view."""

    def __init__(self, store, read_json, atomic_json, now, curated_path=None, registry_path=None):
        self.store = store
        self.read_json, self.atomic_json, self._now = read_json, atomic_json, now
        self.curated_path = Path(curated_path) if curated_path else Path(__file__).parent / 'card-annotations.json'
        self.registry_path = Path(registry_path) if registry_path else Path(__file__).parent / 'annotation-tags.json'
        self.registry = Registry(json.loads(self.registry_path.read_text(encoding='utf-8')))
        self.path = store.root / 'card-annotations.json'
        self.backup_dir = store.root / 'backups' / 'annotations'
        self.curated = self._load_curated()
        self.document = self._load_user()
        self._views = {}

    def _load_curated(self):
        document = json.loads(self.curated_path.read_text(encoding='utf-8'))
        if document.get('version') != 1: raise ValueError('卡片标注资料版本不受支持')
        entries = {}
        for key, entry in document.get('cards', {}).items():
            try:
                # Keys are only checkable while the frozen text still matches the
                # installed card; digest drift keeps entries but freezes them.
                card = self.store.catalog.cards.get(int(key))
                segment_keys = None
                if card is not None and entry.get('text_digest') == digest(card.get('desc') or ''):
                    segment_keys = {seg['key'] for seg in segments(card.get('desc') or '', card.get('type') or 0)}
                entries[int(key)] = validate_entry({**entry, 'code': int(key)}, self.registry, segment_keys=segment_keys)
            except ValueError as exc:
                raise ValueError(f'内置卡片标注资料无效：{exc}') from None
        document['cards'] = entries
        return document

    def _load_user(self):
        if not self.path.exists(): return {'version': 1, 'revision': 1, 'cards': {}}
        document = self.read_json(self.path)
        if document.get('version') != 1 or not isinstance(document.get('cards'), dict) or not isinstance(document.get('revision'), int):
            raise ValueError('本地卡片标注文件无效，请从备份恢复后重试')
        return document

    def reload(self):
        """Resource updates re-anchor every annotation to the new card text."""
        self.curated = self._load_curated()
        self.document = self._load_user()
        self._views = {}

    # ---- assembly -------------------------------------------------------

    def _engine_links(self, code, card_digest, seg_map):
        audited = AUDITED_EFFECTS.get(code)
        if not audited or audited[0] != card_digest: return {}
        links = {}
        for rule in audited[1]:
            for prefix in ('m', 'p'):
                key = f"{prefix}{rule['number']}"
                if key in seg_map:
                    links.setdefault(key, {'script': rule['script'], 'location': rule.get('location'), 'audited': True})
                    break
        return links

    def view(self, code):
        if code in self._views: return self._views[code]
        card = self.store.catalog.cards.get(code)
        if card is None: raise ValueError(f'卡牌编号 {code} 不在当前卡库')
        current = digest(card.get('desc') or '')
        segs = segments(card.get('desc') or '', card.get('type') or 0)
        seg_map = {seg['key']: seg for seg in segs}
        user = self.document['cards'].get(str(code)) or {}
        curated = self.curated['cards'].get(code)
        base, provenance, stale = None, None, False
        if curated is not None:
            base = curated
            provenance = {'source': 'curated', 'id': self.curated.get('id'), 'title': self.curated.get('title'),
                          'checked_on': curated['review'].get('checked_on')}
            stale = curated.get('text_digest') != current
        draft = user.get('draft')
        if base is None and draft is not None:
            if user.get('draft_digest') == current:
                base, provenance = draft, {'source': 'user-draft'}
            else:
                stale = True
        if stale: status = 'stale'
        elif user.get('pending'): status = 'pending'
        elif user.get('confirmed') and base is not None: status = 'confirmed'
        elif base is not None: status = 'reviewed' if base['review']['status'] == 'reviewed' else 'auto'
        else: status = 'none'
        annotated = {effect['key']: effect for effect in (base or {}).get('effects', [])}
        add, remove = user.get('tag_add', {}), user.get('tag_remove', {})
        user_notes = user.get('notes', {})
        engine = self._engine_links(code, current, seg_map)
        effects, missing = [], []
        for seg in segs:
            if seg['key'] in annotated:
                effect = deepcopy(annotated[seg['key']])
                effect.update(kind=seg['kind'], number=seg['number'], block=seg['block'], text=seg['text'], annotated=True)
                tags = set(effect.get('tags', [])) | set(add.get(seg['key'], []))
                tags -= set(remove.get(seg['key'], []))
                effect['tags'] = sorted(tags, key=self.registry.tag_order)
                notes = [*deepcopy(effect.get('notes', [])), *deepcopy(user_notes.get(seg['key'], []))]
                if notes: effect['notes'] = notes
                if seg['key'] in engine and not effect.get('engine'): effect['engine'] = engine[seg['key']]
            else:
                missing.append(seg['key'])
                effect = {**seg, 'annotated': False}
                if seg['key'] in user_notes: effect['notes'] = deepcopy(user_notes[seg['key']])
            effects.append(effect)
        result = {'code': code, 'name': card.get('name', str(code)), 'type': card.get('type', 0),
                  'setcode': card.get('setcode'), 'status': status,
                  'full': base is not None and (bool(base.get('no_effect')) or not missing),
                  'origin': base['review'].get('origin') if base else None,
                  'no_effect': bool((base or {}).get('no_effect')), 'missing_keys': missing,
                  'digest_ok': not stale, 'text_digest': current,
                  'review': deepcopy((base or {}).get('review')), 'provenance': provenance,
                  'effects': effects, 'relations': deepcopy((base or {}).get('relations', [])),
                  'notes': deepcopy((base or {}).get('notes', []))}
        self._views[code] = result
        return result

    def annotated_codes(self):
        curated = set(self.curated['cards'])
        codes = curated | {int(code) for code, entry in self.document['cards'].items()
                           if entry.get('draft') and int(code) not in curated}
        return sorted(code for code in codes if code in self.store.catalog.cards)

    def overview(self):
        cards = self.store.catalog.cards
        counts = {status: 0 for status in STATUSES}
        partial, stale = [], []
        for code in self.annotated_codes():
            view = self.view(code)
            status = view['status']
            if status == 'stale': stale.append(code)
            elif status in ('reviewed', 'confirmed') and not view['full']:
                status, _ = 'partial', partial.append(code)
            counts[status] += 1
        counts['none'] = len(cards) - sum(counts[status] for status in STATUSES if status != 'none')
        return {'version': 1, 'statuses': counts,
                'catalog': {'cards': len(cards), 'sources': self.store.catalog.sources},
                'tokens': sum(1 for card in cards.values() if card.get('type', 0) & 0x4000),
                'annotated_total': sum(counts[status] for status in STATUSES if status != 'none'),
                'curated': {'id': self.curated.get('id'), 'title': self.curated.get('title'),
                            'checked_on': self.curated.get('checked_on'),
                            'verified_against': self.curated.get('verified_against', {})},
                'registry': {'tags': len(self.registry.tags), 'updated_on': self.registry.updated_on},
                'partial_codes': partial, 'stale_codes': stale,
                'missing_codes': sorted(set(self.curated['cards']) - set(cards)),
                'note': '未标注 ≠ 没有能力；覆盖清单只统计已完成核对的效果，未知内容保持未知。'}

    # ---- query ----------------------------------------------------------

    def _iter_processing(self, items):
        for index, item in enumerate(items or []):
            yield str(index), item
            for sub_index, sub in self._iter_processing(item.get('then')):
                yield f'{index}.then.{sub_index}', sub
            for branch_index, branch in enumerate(item.get('branches') or []):
                for sub_index, sub in self._iter_processing(branch.get('actions') or []):
                    yield f'{index}.branch{branch_index}.{sub_index}', sub
                for sub_index, sub in self._iter_processing(branch.get('then') or []):
                    yield f'{index}.branch{branch_index}.then.{sub_index}', sub

    def _effect_conditions(self, effect, body):
        """Evaluate every requested condition inside ONE effect; None on any miss."""
        evidence = []
        etags = body.get('etags') or []
        if etags:
            tags = set(effect.get('tags') or [])
            if body.get('etag_mode') == 'any':
                hit = [tag for tag in etags if tag in tags]
                if not hit: return None
            else:
                if not set(etags) <= tags: return None
                hit = list(etags)
            evidence.append({'condition': 'tag', 'value': hit, 'basis': '效果 TAG'})
        for name in CONDITION_FIELDS:
            value = body.get(name)
            if not value: continue
            found = None
            if name == 'action':
                for _, item in self._iter_processing(effect.get('structure', {}).get('processing')):
                    if item.get('action') == value:
                        found = {'condition': name, 'value': value,
                                 'basis': f"处理：{self.registry.action_label(value)}"
                                          f"（{item.get('selector', {}).get('text') or item.get('evidence', '')}）"}
                        break
            elif name in ('from_zone', 'to_zone'):
                field = 'from_zones' if name == 'from_zone' else 'to_zones'
                for _, item in self._iter_processing(effect.get('structure', {}).get('processing')):
                    zones = item.get(field)
                    if zones and value in zones:
                        found = {'condition': name, 'value': value, 'basis': self.registry.zone_label(value)}
                        break
                    if name == 'to_zone' and not zones and DEFAULT_DESTINATION.get(item.get('action')) == value:
                        found = {'condition': name, 'value': value,
                                 'basis': f"隐含去向：{self.registry.action_label(item.get('action'))}"}
                        break
            elif name == 'usage':
                if value in (effect.get('structure', {}).get('usage') or []):
                    found = {'condition': name, 'value': value, 'basis': self.registry.usage_label(value)}
            elif name == 'cost_kind':
                for cost in effect.get('structure', {}).get('cost') or []:
                    if cost.get('kind') == value:
                        found = {'condition': name, 'value': value, 'basis': cost.get('text') or value}
                        break
            elif name == 'timing':
                activation = effect.get('structure', {}).get('activation') or {}
                if activation.get('timing') == value:
                    found = {'condition': name, 'value': value, 'basis': '发动时点'}
            if found is None: return None
            evidence.append(found)
        return evidence

    def _single_conditions(self, body):
        """Card-scope evaluation unit: one tag or one structure field each."""
        singles = []
        etags = body.get('etags') or []
        if body.get('etag_mode') == 'any' and etags:
            singles.append({'etags': etags, 'etag_mode': 'any'})
        else:
            singles.extend({'etags': [tag]} for tag in etags)
        singles.extend({name: body[name]} for name in CONDITION_FIELDS if body.get(name))
        return singles

    def search(self, body):
        from plan_tags import contains_card, member_ids, normalized
        query = normalized(body.get('q', ''))
        if len(body.get('q', '')) > 120: raise ValueError('搜索文字最多 120 个字符')
        statuses = body.get('status') or list(STATUSES)
        if not isinstance(statuses, list) or not statuses or any(status not in STATUSES for status in statuses):
            raise ValueError('标注状态筛选无效')
        etags = body.get('etags') or []
        if not isinstance(etags, list) or len(etags) > 12 or any(tag not in self.registry.tags for tag in etags):
            raise ValueError('效果 TAG 筛选无效')
        scope = body.get('scope') or 'effect'
        if scope not in ('effect', 'card'): raise ValueError('查询范围无效')
        offset = body.get('offset') or 0
        if not isinstance(offset, int) or not 0 <= offset <= 10_000: raise ValueError('分页参数无效')
        member_filter = None
        if body.get('tag'):
            tags = self.store.library.all_tags()
            tag = tags.get(body['tag'])
            if tag is None: raise ValueError('TAG 不存在，请刷新标签库')
            member_filter = set(member_ids(tag, self.store.catalog.cards))
        kind = body.get('kind') or ''
        if kind not in ('', 'monster', 'spell', 'trap', 'extra'): raise ValueError('卡片类型筛选无效')
        condition_names = ({'tag'} if etags else set()) | {name for name in CONDITION_FIELDS if body.get(name)}
        matched = []
        for code in self.annotated_codes():
            card = self.store.catalog.cards[code]
            if kind == 'monster' and not card.get('type', 0) & 1: continue
            if kind == 'spell' and not card.get('type', 0) & 2: continue
            if kind == 'trap' and not card.get('type', 0) & 4: continue
            if kind == 'extra' and not card.get('extra'): continue
            if member_filter is not None and code not in member_filter: continue
            if query and query not in normalized(card.get('name', '')) and query != str(code) \
                    and query not in normalized(card.get('desc') or ''):
                continue
            view = self.view(code)
            if view['status'] not in statuses: continue
            hits = []
            for effect in view['effects']:
                if not effect.get('annotated'): continue
                evidence = self._effect_conditions(effect, body)
                if evidence is None: continue
                hits.append({'key': effect['key'], 'number': effect.get('number'), 'block': effect.get('block'),
                             'kind': effect.get('kind'), 'text': effect.get('text'), 'tags': effect.get('tags', []),
                             'usage': effect.get('structure', {}).get('usage', []),
                             'engine': effect.get('engine'), 'evidence': evidence})
            if not condition_names:
                hits = hits or [{'key': effect['key'], 'number': effect.get('number'), 'block': effect.get('block'),
                                 'kind': effect.get('kind'), 'text': effect.get('text'), 'tags': effect.get('tags', []),
                                 'usage': effect.get('structure', {}).get('usage', []),
                                 'engine': effect.get('engine'), 'evidence': []}
                                for effect in view['effects'] if effect.get('annotated')]
                if not hits: continue
            elif scope == 'effect':
                if not hits: continue
            else:
                # Card scope: each condition may be met by a different effect;
                # every condition still needs at least one effect behind it.
                merged = {}
                for single in self._single_conditions(body):
                    found = False
                    for effect in view['effects']:
                        if not effect.get('annotated'): continue
                        evidence = self._effect_conditions(effect, single)
                        if evidence is None: continue
                        found = True
                        hit = merged.setdefault(effect['key'], {'key': effect['key'], 'number': effect.get('number'),
                                                                'block': effect.get('block'), 'kind': effect.get('kind'),
                                                                'text': effect.get('text'), 'tags': effect.get('tags', []),
                                                                'usage': effect.get('structure', {}).get('usage', []),
                                                                'engine': effect.get('engine'), 'evidence': []})
                        hit['evidence'] = [*hit['evidence'], *evidence]
                    if not found: merged = None; break
                if merged is None or not merged: continue
                hits = list(merged.values())
            keys = sorted({hit['key'] for hit in hits})
            matched.append({'code': code, 'name': view['name'], 'type': card.get('type', 0),
                            'status': view['status'], 'full': view['full'], 'origin': view['origin'],
                            'hits': hits, 'cross_effects': len(keys) > 1,
                            'hit_keys': keys})
        matched.sort(key=lambda item: (item['name'], item['code']))
        return {'total': len(matched), 'offset': offset, 'scope': scope,
                'annotated_total': len(self.annotated_codes()),
                'catalog_total': len(self.store.catalog.cards),
                'note': '查询只在已标注范围内命中；未标注卡片不代表没有该能力。同一卡的不同效果不串用条件：默认范围下所有条件须在同一效果内成立。',
                'cards': matched[offset:offset + 30]}

    # ---- personal layer -------------------------------------------------

    def _save(self, mutate):
        with self.store.lock:
            previous = deepcopy(self.document)
            mutate(self.document)
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            self.atomic_json(self.backup_dir / f"{self.document['revision']}.json", previous)
            self.document['revision'] += 1
            self.atomic_json(self.path, self.document)
            self._views = {}

    def _card_entry(self, code):
        entry = self.document['cards'].get(str(code))
        if entry is None:
            entry = {'confirmed': False, 'pending': False, 'tag_add': {}, 'tag_remove': {}, 'notes': {}}
            self.document['cards'][str(code)] = entry
        return entry

    def set_review(self, body):
        code = self._require_code(body)
        value = body.get('value')
        if value not in ('confirmed', 'pending', None): raise ValueError('核对状态取值无效')
        def mutate(document):
            entry = self._card_entry(code)
            entry['confirmed'] = value == 'confirmed'
            entry['pending'] = value == 'pending'
        self._save(mutate)
        return {'code': code, 'status': self.view(code)['status'], 'revision': self.document['revision']}

    def add_note(self, body):
        code, key, text = self._require_code(body), body.get('key'), body.get('text')
        if not isinstance(key, str) or not key: raise ValueError('效果编号无效')
        if not isinstance(text, str) or not text.strip() or len(text) > 4000: raise ValueError('备注请输入 1–4000 字')
        if key not in {effect['key'] for effect in self.view(code)['effects']}:
            raise ValueError('效果编号不在当前卡文分段中')
        def mutate(document):
            entry = self._card_entry(code)
            entry.setdefault('notes', {}).setdefault(key, []).append({'text': text.strip(), 'ts': self._now()})
        self._save(mutate)
        return {'code': code, 'key': key, 'revision': self.document['revision']}

    def remove_note(self, body):
        code, key, index = self._require_code(body), body.get('key'), body.get('index')
        if not isinstance(key, str) or not isinstance(index, int) or index < 0: raise ValueError('备注定位无效')
        def mutate(document):
            notes = self._card_entry(code).get('notes', {}).get(key, [])
            if index >= len(notes): raise ValueError('备注不存在，请刷新后重试')
            notes.pop(index)
        self._save(mutate)
        return {'code': code, 'key': key, 'revision': self.document['revision']}

    def set_tags(self, body):
        code, key = self._require_code(body), body.get('key')
        add, remove = body.get('add', []), body.get('remove', [])
        if not isinstance(key, str) or not key: raise ValueError('效果编号无效')
        for field, ids in (('add', add), ('remove', remove)):
            if not isinstance(ids, list) or len(ids) > 18 or any(tag not in self.registry.tags for tag in ids):
                raise ValueError(f'{field} 的效果 TAG 无效')
        if key not in {effect['key'] for effect in self.view(code)['effects']}:
            raise ValueError('效果编号不在当前卡文分段中')
        def mutate(document):
            entry = self._card_entry(code)
            added = set(entry.get('tag_add', {}).get(key, [])) | set(add)
            removed = set(entry.get('tag_remove', {}).get(key, [])) | set(remove)
            # Removing a personal addition undoes it; tag_remove only counters curated tags.
            added -= removed
            removed -= added
            entry.setdefault('tag_add', {})[key] = sorted(added)
            entry.setdefault('tag_remove', {})[key] = sorted(removed)
        self._save(mutate)
        return {'code': code, 'key': key, 'revision': self.document['revision']}

    def make_draft(self, body):
        code = self._require_code(body)
        card = self.store.catalog.cards[code]
        current = digest(card.get('desc') or '')
        entry = draft_entry(code, segments(card.get('desc') or '', card.get('type') or 0), current)
        if not entry['effects']: raise ValueError('未能从卡文中提取任何候选；请人工标注或稍后扩充词表')
        def mutate(document):
            self._card_entry(code)['draft'] = entry
            self._card_entry(code)['draft_digest'] = current
        self._save(mutate)
        return {'code': code, 'effects': len(entry['effects']), 'origin': 'auto', 'revision': self.document['revision']}

    def discard_draft(self, body):
        code = self._require_code(body)
        def mutate(document):
            entry = document['cards'].get(str(code))
            if entry is None or 'draft' not in entry: raise ValueError('该卡没有自动草稿')
            entry.pop('draft', None); entry.pop('draft_digest', None)
            if not any(entry.get(field) for field in ('confirmed', 'pending', 'tag_add', 'tag_remove', 'notes')):
                document['cards'].pop(str(code), None)
        self._save(mutate)
        return {'code': code, 'revision': self.document['revision']}

    def _require_code(self, body):
        code = body.get('code')
        if not isinstance(code, int) or code not in self.store.catalog.cards: raise ValueError('卡牌不在当前卡库中')
        return code

    def registry_document(self):
        return {'version': 1, 'updated_on': self.registry.updated_on, 'categories': self.registry.categories,
                'tags': sorted(self.registry.tags.values(), key=lambda tag: (tag['category'], tag['name'])),
                **self.registry.vocab}

    def snapshot(self):
        return {'registry': self.registry_document(), 'overview': self.overview(), 'revision': self.document['revision']}

    def command(self, body):
        if not isinstance(body, dict): raise ValueError('请求无效')
        op = body.get('op')
        if op == 'overview': return self.overview()
        if op == 'query': return self.search(body)
        if op == 'card': return self.view(self._require_code(body))
        if op == 'registry': return self.registry_document()
        if op in ('set-review', 'add-note', 'remove-note', 'set-tags', 'discard-draft'):
            if body.get('revision') != self.document['revision']:
                raise ValueError('本地标注已更新，请刷新后重试')
            return getattr(self, {'set-review': 'set_review', 'add-note': 'add_note', 'remove-note': 'remove_note',
                                  'set-tags': 'set_tags', 'discard-draft': 'discard_draft'}[op])(body)
        if op == 'draft': return self.make_draft(body)
        raise ValueError('未知的标注操作')
