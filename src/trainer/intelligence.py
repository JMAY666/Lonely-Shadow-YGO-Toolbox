"""Personal card knowledge, committed atomically with the shared TAG vocabulary.

General marks are never consulted by route evaluation and never write a plan.
Hand-trap TAG membership is a projection of the same records, not a second list.
"""
from copy import deepcopy
import hashlib
import json
import uuid
from intelligence_marks import effect_parts, normalize_mark, note_items, notes_value, refs, merge_marks

HANDTRAP_ID = 'purpose:handtrap'
BREAKER_ID = 'purpose:boardbreaker'
CARD_LIBRARIES = {'handtraps': ('handtrap', '手坑', HANDTRAP_ID), 'breakers': ('boardbreaker', '解场', BREAKER_ID)}
EXTRA_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000


def main_card(card):
    return bool(card.get('type', 0) & 7) and not card.get('type', 0) & (EXTRA_TYPES | 0x4000)


def card_library_id(document, kind='handtraps'):
    from plan_tags import normalized
    purpose, name, default = CARD_LIBRARIES[kind]
    saved = document.get('intelligence', {}).get(purpose + '_tag_id')
    if saved: return saved
    # Reuse an existing user-named TAG's identity; saved deck references survive.
    matching = [key for key, tag in document.get('entries', {}).items()
                if normalized(tag['name']) == name]
    return matching[0] if matching else default


def handtrap_data(value, catalog):
    annotation = normalize_mark({
        'desc': value.get('desc', catalog.get(value['code'], {}).get('desc', '')),
        'effects': value.get('effects', {}), 'unmatched_effects': value.get('unmatched_effects', [])})
    return {'note': '', 'condition': '', 'folder_id': None, **deepcopy(value),
            **{key: annotation[key] for key in ('desc', 'effects', 'unmatched_effects')}}


def data(document, catalog):
    from plan_tags import member_ids
    if 'intelligence' in document:
        value = deepcopy(document['intelligence'])
        if value.get('version') != 1: raise ValueError('情报站资料版本不受支持，原文件已保留')
        value['endboards'] = {key: normalize_mark(mark) for key, mark in value['endboards'].items()}
        for kind, (purpose, _, _) in CARD_LIBRARIES.items():
            value[purpose + '_tag_id'] = card_library_id(document, kind)
            if kind not in value:
                previous = document.get('entries', {}).get(value[purpose + '_tag_id'], {})
                value[kind] = {str(code): {'code': code} for code in member_ids(previous, catalog)}
            value[kind] = {key: handtrap_data(mark, catalog) for key, mark in value[kind].items()}
        return value
    value = {'version': 1, 'endboards': {}, 'folders': {}, 'topics': {}, 'records': {}}
    for kind, (purpose, _, _) in CARD_LIBRARIES.items():
        identifier = card_library_id(document, kind)
        previous = document.get('entries', {}).get(identifier, {})
        value[purpose + '_tag_id'] = identifier
        value[kind] = {str(code): handtrap_data({'code': code}, catalog) for code in member_ids(previous, catalog)}
    return value


def purpose_tag(document, catalog=None, kind='handtraps'):
    purpose, name, _ = CARD_LIBRARIES[kind]
    identifier = card_library_id(document, kind)
    previous = document.get('entries', {}).get(identifier, {})
    members = (document.get('intelligence') or {}).get(kind)
    managed = bool(document.get('intelligence', {}).get('annotation_sync'))
    return {**previous, **({'managed_by': 'card-annotations'} if managed else {}),
            'id': identifier, 'name': name, 'aliases': previous.get('aliases', []),
            'setcode': previous.get('setcode') if members is None else None,
            'source': '卡片标注 · 自动用途分类' if managed else '情报站 · 功能用途', 'kind': 'purpose', 'purpose': purpose,
            'include_cards': sorted(map(int, members)) if members is not None else previous.get('include_cards', []),
            'exclude_cards': previous.get('exclude_cards', []) if members is None else []}


def text(value, limit=4000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'文字须为{1 if required else 0}–{limit}个字符')
    return value.strip()


class Intelligence:
    def __init__(self, store):
        self.store = store

    @property
    def library(self): return self.store.library

    def card(self, code):
        value = self.store.catalog.cards.get(code)
        return deepcopy(value) if value else {'id': code, 'name': f'卡库缺失 · {code}', 'desc': '', 'type': 0, 'missing': True}

    def snapshot(self):
        with self.store.lock:
            if hasattr(self.store, 'annotation_knowledge'): self.store.annotation_knowledge.synchronize()
            from plan_tags import contains_card
            document = self.library.document()
            knowledge = data(document, self.store.catalog.cards)
            codes = set(map(int, knowledge['endboards'])) | set(map(int, knowledge['handtraps'])) | set(map(int, knowledge['breakers']))
            for record in knowledge['records'].values(): codes.update(self.record_codes(record))
            tags = self.library.all_tags()
            capabilities = {}
            service = getattr(self.store, 'card_capabilities', None)
            for code in codes if service else ():
                value = service.card(code)
                capabilities[str(code)] = {key: value[key] for key in ('trusted', 'tags', 'status', 'version')}
            return {**knowledge, 'revision': document['revision'],
                    'capabilities': capabilities,
                    'cards': {str(code): self.card(code) for code in codes},
                    'card_tags': {str(code): [key for key, tag in tags.items() if contains_card(tag, code, self.store.catalog.cards.get(code, {}))] for code in codes},
                    'tags': list(tags.values())}

    @staticmethod
    def record_codes(record):
        codes = {code for step in record.get('steps', [])
                for code in [step.get('opponent'), *(c for response in step.get('responses', []) for c in response.get('cards', []))]
                if code is not None}
        walkthrough = record.get('research', {}).get('walkthrough', {})
        codes.update(step['card'] for step in walkthrough.get('sequence', []) if step.get('card') is not None)
        return codes

    def check_code(self, code, retained=()):
        if type(code) is not int or not 0 < code < 2**32: raise ValueError('卡牌编号无效')
        if code not in self.store.catalog.cards and code not in retained: raise ValueError('卡库缺少这张卡，新引用请从卡库选择')
        return code

    def check_handtrap(self, code, retained=()):
        self.check_code(code, retained)
        card = self.store.catalog.cards.get(code)
        if card and not main_card(card): raise ValueError('手坑只允许主卡组卡牌，不能加入额外卡组卡牌或衍生物')

    def check_library_card(self, kind, code, retained=()):
        if kind == 'handtraps': return self.check_handtrap(code, retained)
        self.check_code(code, retained)
        card = self.store.catalog.cards.get(code)
        if card and (not card.get('type', 0) & 7 or card['type'] & 0x4000): raise ValueError('解场资料不能加入衍生物或非卡牌条目')

    def sync_members(self, document, selected, kind='handtraps'):
        if not isinstance(selected, list) or len(selected) > 20000: raise ValueError('手坑卡牌列表无效')
        knowledge = data(document, self.store.catalog.cards)
        retained = set(map(int, knowledge[kind]))
        for code in selected: self.check_library_card(kind, code, retained)
        knowledge[kind] = {str(code): knowledge[kind].get(str(code),
            handtrap_data({'code': code}, self.store.catalog.cards)) for code in sorted(set(selected))}
        document['intelligence'] = knowledge
        tag = purpose_tag(document, kind=kind)
        document['entries'][tag['id']] = tag

    def sources(self):
        """Keep provenance snapshots intact while allowing an explicit knowledge union."""
        with self.store.lock:
            groups, warnings = {}, []
            for path in sorted(self.store.plans.glob('*.json')):
                try: plan = self.library.read(path)
                except (OSError, ValueError):
                    warnings.append(f'{path.stem} 暂不可读，未导入'); continue
                routes = [(None, plan)] + [(b.get('id'), b['report']) for b in plan.get('branches', []) if b.get('report')]
                for branch_id, route in routes:
                    edits = route.get('annotations') or {}
                    final = next((n.get('state') for n in route.get('review', {}).get('nodes', []) if n.get('kind') == 'final'), None) or route.get('final_state') or {}
                    for card in final.get('cards', []):
                        instance = str(card.get('instance_id'))
                        mark = edits.get('final_marks', {}).get(instance, {})
                        code = card.get('code')
                        if not mark.get('marked') or type(code) is not int or code <= 0: continue
                        details = route.get('catalog', {}).get(str(code), plan.get('catalog', {}).get(str(code), {}))
                        annotation = {'code': code, 'candidate': True, 'note': edits.get('cards', {}).get(instance, ''),
                                      'effects': deepcopy(mark.get('effects', {})), 'desc': details.get('desc', '')}
                        key = f'{plan["id"]}:{branch_id or "main"}:{instance}'
                        digest = hashlib.sha256(json.dumps(annotation, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                        source = {'key': key, 'fingerprint': digest, 'plan_id': plan['id'], 'plan_name': plan.get('name', path.stem),
                                  'branch_id': branch_id, 'instance_id': instance, 'location': card.get('location'),
                                  'annotation': annotation}
                        group = groups.setdefault(code, {'code': code, 'card': self.card(code), 'sources': []})
                        group['sources'].append(source)
            return {'groups': list(groups.values()), 'warnings': warnings}

    def annotation(self, value, previous=None, trusted=False):
        code = self.check_code(value.get('code'), [previous['code']] if previous else ([value.get('code')] if trusted else []))
        desc = value.get('desc', self.card(code)['desc'])
        text(desc, 50000)
        if not trusted and desc != self.card(code)['desc'] and desc != (previous or {}).get('desc'):
            raise ValueError('卡牌文本已更新，请重新打开标注并核对')
        parts, checked = effect_parts(desc), {}
        def checked_notes(item, old):
            if old and 'note' in item and item.get('notes') == old.get('notes') and item['note'] != old.get('note'):
                return note_items({'note': item['note']})
            return note_items(item)
        effects = value.get('effects', {})
        if not isinstance(effects, dict) or len(effects) > 100: raise ValueError('效果标注格式无效')
        for key, item in effects.items():
            if key not in {str(i) for i in range(len(parts))} or not isinstance(item, dict): raise ValueError('效果编号已改变，请核对卡面文本')
            checked[key] = {**notes_value(checked_notes(item, (previous or {}).get('effects', {}).get(key))), 'source_refs': refs(item.get('source_refs', []))}
        return normalize_mark({'code': code, **notes_value(checked_notes(value, previous)),
                'desc': desc, 'effects': checked, 'sources': deepcopy((previous or {}).get('sources', [])),
                'merged_source_refs': deepcopy((previous or {}).get('merged_source_refs', [])),
                'unmatched_effects': deepcopy(value.get('unmatched_effects', []))})

    def endboard(self, value, previous=None, trusted=False):
        if type(value.get('candidate', True)) is not bool: raise ValueError('终场候选标记无效')
        return {**self.annotation(value, previous, trusted), 'candidate': value.get('candidate', True)}

    def validate_record(self, value, knowledge, previous, trusted=False):
        title = text(value.get('title', ''), 120, True)
        topic = value.get('topic_id')
        if topic not in knowledge['topics']: raise ValueError('请选择适用主题')
        retained = self.record_codes(previous or {})
        steps = value.get('steps', [])
        if not isinstance(steps, list) or not 1 <= len(steps) <= 100: raise ValueError('每条记录需要 1–100 个步骤')
        result = []
        for step in steps:
            if not isinstance(step, dict): raise ValueError('断点步骤格式无效')
            opponent = step.get('opponent')
            if opponent is not None: self.check_code(opponent, [opponent] if trusted else retained)
            responses = step.get('responses', [])
            if not isinstance(responses, list) or len(responses) > 30: raise ValueError('每步最多 30 个应对选项')
            options = []
            for response in responses:
                if not isinstance(response, dict): raise ValueError('应对选项格式无效')
                cards = response.get('cards', [])
                if not isinstance(cards, list) or len(cards) > 20: raise ValueError('应对卡牌数量无效')
                for code in cards: self.check_code(code, [code] if trusted else retained)
                mode = response.get('mode', 'alternative')
                if mode not in ('alternative', 'combination'): raise ValueError('应对方式无效')
                if len(cards) > 1 and mode != 'combination': raise ValueError('多个不同应对请分别添加选项；多卡配合须选择组合')
                options.append({'cards': list(dict.fromkeys(cards)), 'mode': mode,
                                **{k: text(response.get(k, '')) for k in ('method', 'condition', 'expected', 'note')}})
            result.append({'opponent': opponent, **{k: text(step.get(k, '')) for k in ('action', 'timing', 'condition', 'note')}, 'responses': options})
        status = '待核对' if all(s['opponent'] and s['action'] and s['timing'] and s['condition'] and s['responses'] and
            all((r['cards'] or r['method']) and r['condition'] and r['expected'] for r in s['responses']) for s in result) else '待补充'
        record = {'title': title, 'topic_id': topic, 'steps': result, 'note': text(value.get('note', '')), 'status': status}
        if 'reference_copy' in value or 'reference_copy' in (previous or {}):
            record['reference_copy'] = text(value.get('reference_copy', (previous or {}).get('reference_copy', '')), 100000)
        return record

    def command(self, body):
        with self.store.lock:
            if body.get('op') == 'annotations.sync':
                if body.get('revision') != self.library.document()['revision']: raise ValueError('资料已更新，请刷新后同步')
                self.store.annotation_knowledge.synchronize(enable=True, force=True)
                return self.snapshot()
            if hasattr(self.store, 'annotation_knowledge'): self.store.annotation_knowledge.synchronize()
            document = self.library.document()
            if body.get('revision') != document['revision']: raise ValueError('资料已在其他入口更新，当前输入保留；请刷新并核对后重试')
            knowledge = data(document, self.store.catalog.cards)
            op, value = body.get('op'), body.get('value', {})
            if not isinstance(value, dict): raise ValueError('资料格式无效')
            if not isinstance(op, str): raise ValueError('情报站操作无效')
            if knowledge.get('annotation_sync'):
                kind = {'handtrap': 'handtraps', 'breaker': 'breakers', 'endboard': 'endboards'}.get(op.split('.')[0])
                if kind and value.get('code') in set(self.store.annotation_knowledge.build()['covered']):
                    raise ValueError('该卡用途已由统一标注管理，请到卡片标注修改；局部方案说明仍在方案中编辑')
                if op in ('staples.import', 'endboard.import', 'endboard.merge-sources'):
                    raise ValueError('旧资料导入已由统一标注同步替代，请使用重新同步')
                if op.startswith('folder.') and knowledge['folders'].get(value.get('id'), {}).get('managed_by') == 'card-annotations':
                    raise ValueError('自动用途分类由标注生成，不能单独改名或删除')
            identifier = value.get('id')
            merged_count = None
            import_result = None
            if op == 'staples.import':
                from intelligence_staples import import_staples
                import_result = import_staples(self, document, knowledge)
                if not import_result['changed']:
                    return {**self.snapshot(), 'import_result': import_result}
            elif op == 'matchups.import':
                from intelligence_matchups import import_matchups
                import_result = import_matchups(self, document, knowledge)
                if not import_result['changed']:
                    return {**self.snapshot(), 'import_result': import_result}
            elif op in ('endboard.import', 'endboard.merge-sources'):
                selected = [{'key': value.get('source_key'), 'fingerprint': value.get('fingerprint')}] if op == 'endboard.import' else value.get('sources')
                if not isinstance(selected, list) or not 1 <= len(selected) <= 10000: raise ValueError('请选择需要合并的来源标注')
                available = {s['key']: s for group in self.sources()['groups'] for s in group['sources']}
                changed = set()
                for selection in selected:
                    if not isinstance(selection, dict): raise ValueError('来源选择格式无效')
                    source = available.get(selection.get('key'))
                    if not source or source['fingerprint'] != selection.get('fingerprint'): raise ValueError('来源方案已改变，请刷新来源后合并')
                    code = source['annotation']['code']; previous = knowledge['endboards'].get(str(code))
                    incoming = self.endboard(source['annotation'], trusted=True)
                    knowledge['endboards'][str(code)] = merge_marks(previous, incoming, source=source,
                        target_desc=self.store.catalog.cards.get(code, {}).get('desc'))
                    changed.add(code)
                merged_count = len(changed)
            elif op in ('endboard.save', 'endboard.merge'):
                previous = knowledge['endboards'].get(str(value.get('code')))
                if op == 'endboard.merge' and previous:
                    # Re-saving an unchanged flattened plan copy must not create a new composite note.
                    if 'notes' not in value and value.get('note', '') == previous['note']: value['notes'] = deepcopy(previous['notes'])
                    for key, effect in value.get('effects', {}).items():
                        old = previous['effects'].get(key, {})
                        if value.get('desc', previous['desc']) == previous['desc'] and 'notes' not in effect and effect.get('note', '') == old.get('note'):
                            effect['notes'] = deepcopy(old.get('notes', []))
                annotation = self.endboard(value, previous)
                if op == 'endboard.merge': annotation = merge_marks(previous, annotation)
                knowledge['endboards'][str(annotation['code'])] = annotation
            elif op == 'endboard.remove': knowledge['endboards'].pop(str(value.get('code')), None)
            elif op in ('handtrap.save', 'breaker.save'):
                kind = 'handtraps' if op == 'handtrap.save' else 'breakers'
                code = value.get('code'); self.check_library_card(kind, code, set(map(int, knowledge[kind])))
                previous = knowledge[kind].get(str(code), {})
                folder = value.get('folder_id', previous.get('folder_id'))
                if folder is not None and folder not in knowledge['folders']: raise ValueError('文件夹不存在')
                if folder and knowledge['folders'][folder].get('kind', 'handtraps') != kind: raise ValueError('请选择当前资料分类的文件夹')
                annotation = self.annotation({**previous, **value}, previous or None)
                knowledge[kind][str(code)] = {**previous, 'code': code, 'folder_id': folder,
                    'note': text(value.get('note', previous.get('note', ''))), 'condition': text(value.get('condition', previous.get('condition', ''))),
                    **{key: annotation[key] for key in ('desc', 'effects', 'unmatched_effects')}}
            elif op in ('handtrap.remove', 'breaker.remove'):
                knowledge['handtraps' if op == 'handtrap.remove' else 'breakers'].pop(str(value.get('code')), None)
            elif op in ('folder.save', 'topic.save'):
                key = 'folders' if op.startswith('folder') else 'topics'
                if identifier is not None and identifier not in knowledge[key]: raise ValueError('资料不存在，请刷新')
                identifier = identifier or uuid.uuid4().hex
                name = text(value.get('name', ''), 80, True)
                previous_group = knowledge[key].get(identifier)
                kind = previous_group.get('kind', 'handtraps') if previous_group is not None else value.get('kind', 'handtraps')
                if key == 'folders' and kind not in CARD_LIBRARIES: raise ValueError('文件夹分类无效')
                from plan_tags import normalized
                if any(normalized(v['name']) == normalized(name) and k != identifier and (key != 'folders' or v.get('kind', 'handtraps') == kind) for k, v in knowledge[key].items()): raise ValueError('已有同名资料')
                item = {'id': identifier, 'name': name}
                if key == 'folders': item['kind'] = kind
                if key == 'topics':
                    previous = knowledge[key].get(identifier, {})
                    tag_ids = value.get('tag_ids', [])
                    tags = self.library.all_tags()
                    if not isinstance(tag_ids, list) or len(tag_ids) > 30 or any(t not in tags and t not in previous.get('tag_ids', []) for t in tag_ids): raise ValueError('关联 TAG 无效')
                    deck = value.get('deck_id')
                    if deck is not None and deck != previous.get('deck_id'): self.store.get_deck(deck)
                    item.update(tag_ids=list(dict.fromkeys(tag_ids)), deck_id=deck, note=text(value.get('note', '')))
                knowledge[key][identifier] = item
            elif op == 'folder.remove':
                if identifier not in knowledge['folders']: raise ValueError('文件夹不存在')
                del knowledge['folders'][identifier]
                for item in [*knowledge['handtraps'].values(), *knowledge['breakers'].values()]:
                    if item['folder_id'] == identifier: item['folder_id'] = None
            elif op == 'topic.remove':
                if any(r['topic_id'] == identifier for r in knowledge['records'].values()): raise ValueError('主题仍有断点记录，请先移动或删除这些记录')
                knowledge['topics'].pop(identifier, None)
            elif op == 'record.save':
                if identifier is not None and identifier not in knowledge['records']: raise ValueError('断点记录不存在')
                previous = knowledge['records'].get(identifier)
                record = self.validate_record(value, knowledge, previous)
                from intelligence_matchups import save_research
                save_research(record, value, previous)
                identifier = identifier or uuid.uuid4().hex
                knowledge['records'][identifier] = {**record, 'id': identifier}
            elif op == 'record.remove': knowledge['records'].pop(identifier, None)
            else: raise ValueError('未知的情报站操作')
            document['intelligence'] = knowledge
            if op != 'matchups.import':
                for kind in CARD_LIBRARIES:
                    tag = purpose_tag(document, kind=kind)
                    document['entries'][tag['id']] = tag
            document['revision'] += 1
            self.library.save_vocabulary(document)
            return {**self.snapshot(), 'saved_id': identifier, 'merged_count': merged_count, 'import_result': import_result}
