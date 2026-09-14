"""Plan tags and exchange share the store lock and atomic snapshot commit point."""
from copy import deepcopy
import json
import uuid

import plan_tags as tags
import plan_sharing as sharing


class PlanLibrary:
    def __init__(self, store, read, write, clock):
        self.store, self.read, self.write, self.clock = store, read, write, clock
        self.builtins = tags.builtin_tags(store.runtime)
        self.path = store.root / 'tag-library.json'

    def document(self):
        return self.read(self.path) if self.path.exists() else {'version': 1, 'revision': 0, 'entries': {}}

    def all_tags(self):
        return tags.vocabulary(self.builtins, self.document())

    def selection(self, plan, vocabulary=None):
        return tags.classification(plan, vocabulary or self.all_tags(), self.store.catalog.cards)

    def info(self, identifier):
        with self.store.lock:
            plan = self.read(self.store.plan_path(identifier))
            document = self.document()
            vocabulary = tags.vocabulary(self.builtins, document)
            return {'id': identifier, 'edit_revision': plan.get('edit_revision', 0),
                    'classification': self.selection(plan, vocabulary),
                    'suggestions': tags.suggest(plan, vocabulary, self.store.catalog.cards),
                    'tags': list(vocabulary.values()), 'tag_revision': document['revision']}

    def save_vocabulary(self, document):
        if self.path.exists():
            previous = self.read(self.path)
            self.write(self.store.root / 'backups/tags' / f"{previous['revision']}.json", previous)
        self.write(self.path, document)

    def edit_tag(self, body):
        with self.store.lock:
            document = self.document()
            if body.get('revision') != document['revision']: raise ValueError('标签库已更新，请重新打开后编辑；当前输入仍保留')
            tag = tags.edit_tag(body, tags.vocabulary(self.builtins, document))
            if 'card_ids' in body: tag = tags.edit_members(tag, body['card_ids'], self.store.catalog.cards)
            document['entries'][tag['id']] = tag
            document['revision'] += 1
            self.save_vocabulary(document)
            return {'tag': tag, 'revision': document['revision']}

    def members(self, identifier):
        with self.store.lock:
            tag = self.all_tags().get(identifier)
            if not tag: raise ValueError('标签不存在')
            return {'tag': tag, 'revision': self.document()['revision'],
                    'cards': [self.store.catalog.cards.get(code, {'id': code, 'name': f'未安装卡牌 {code}', 'desc': '', 'type': 0})
                              for code in tags.member_ids(tag, self.store.catalog.cards)]}

    def save_selection(self, body):
        with self.store.lock:
            target = self.store.plan_path(body.get('id', ''))
            plan = self.read(target)
            if body.get('revision') != plan.get('edit_revision', 0): raise ValueError('方案已更新，请重新打开标签面板；当前选择仍保留')
            vocabulary = self.all_tags()
            if body.get('automatic') is True: selected = tags.suggest(plan, vocabulary, self.store.catalog.cards)
            else: selected = tags.validate_selection(body.get('classification'), vocabulary)
            if plan.get('classification') == selected: return plan
            backup = self.store.plans / 'revisions' / target.stem / f"{plan.get('edit_revision', 0)}.json"
            if not backup.exists(): self.write(backup, plan)
            plan['classification'] = selected
            plan['edit_revision'] = plan.get('edit_revision', 0) + 1
            self.write(target, plan)
            return plan

    def export(self, identifier):
        with self.store.lock:
            plan = self.read(self.store.plan_path(identifier))
            vocabulary = self.all_tags()
            selection = self.selection(plan, vocabulary)
            document = {'format': sharing.FORMAT, 'version': sharing.VERSION, 'plan': sharing.portable(plan),
                        'tags': [{**{k: t[k] for k in ('id', 'name', 'aliases', 'setcode', 'primary')},
                                  'include_cards': t.get('include_cards', []), 'exclude_cards': t.get('exclude_cards', [])}
                                 for t in tags.tag_list(selection, vocabulary)]}
            # Export and import use the same validator; unusable files never get a successful download.
            document = sharing.validate(document)
            if len(json.dumps(document, ensure_ascii=False).encode('utf-8')) >= sharing.MAX_BYTES:
                raise ValueError('方案超过 20 MB 分享上限，请使用一图流导出')
            return document

    def mapped_tags(self, incoming):
        document = self.document()
        vocabulary = tags.vocabulary(self.builtins, document)
        selected, primary, notes = [], [], []
        for item in incoming:
            # Series identity is the numeric setcode. Custom tags use an exact
            # unambiguous name/alias match; conflicting remote aliases are ignored.
            key = item['id']
            if key.startswith('custom:'):
                matching = [tag['id'] for tag in vocabulary.values() if tags.normalized(item['name']) in
                            {tags.normalized(s) for s in [tag['name'], *tag.get('aliases', [])]}]
                if len(matching) == 1: key = matching[0]
                elif key in vocabulary: key = 'custom:' + uuid.uuid4().hex
            if key not in vocabulary:
                occupied = {tags.normalized(s) for tag in vocabulary.values() for s in [tag['name'], *tag.get('aliases', [])]}
                name = item['name'].strip()
                if tags.normalized(name) in occupied:
                    name = f"{name[:45]} ({key[4:] if key.startswith('set:') else key[-8:]})"
                tag = {'id': key, 'name': name, 'aliases': [a for a in item['aliases'] if tags.normalized(a) not in occupied],
                       'setcode': item['setcode'], 'source': '分享文件',
                       'include_cards': item.get('include_cards', []), 'exclude_cards': item.get('exclude_cards', [])}
                vocabulary[key] = document['entries'][key] = tag
            else:
                existing = vocabulary[key]
                if any(item.get(field, []) != existing.get(field, []) for field in ('include_cards', 'exclude_cards')):
                    notes.append(f'“{existing["name"]}”的卡牌范围不同，保留本地设置')
                occupied = {tags.normalized(s) for identifier, tag in vocabulary.items() if identifier != key for s in [tag['name'], *tag.get('aliases', [])]}
                old = {tags.normalized(s) for s in [existing['name'], *existing['aliases']]}
                extra = []
                for alias in [item['name'], *item['aliases']]:
                    n = tags.normalized(alias)
                    if n in occupied:
                        notes.append(f'别名“{alias}”已有其他归属，保留本地定义')
                    elif n not in old:
                        old.add(n); extra.append(alias)
                if extra:
                    updated = {**existing, 'aliases': [*existing['aliases'], *extra][:30]}
                    vocabulary[key] = document['entries'][key] = updated
            selected.append(key)
            if item['primary']: primary.append(key)
        value = tags.validate_selection({'tag_ids': selected, 'primary_ids': primary}, vocabulary)
        value['mode'] = 'imported'
        return document, value, notes

    def import_document(self, body, preview=False):
        with self.store.lock:
            document = sharing.validate(body.get('document'))
            digest = sharing.fingerprint(document)
            duplicates = []
            for path in self.store.plans.glob('*.json'):
                try:
                    existing = self.read(path)
                    if existing.get('import_fingerprint') == digest:
                        duplicates.append(existing)
                except (OSError, ValueError): pass
            plan = document['plan']
            vocabulary, selection, notes = self.mapped_tags(document['tags'])
            missing = [c for c in set(sum(plan['deck'].values(), [])) if c not in self.store.catalog.cards]
            result = {'name': plan['name'], 'steps': len(plan['actions']), 'deck_count': {k: len(v) for k, v in plan['deck'].items()},
                      'tags': tags.tag_list(selection, tags.vocabulary(self.builtins, vocabulary)), 'notes': notes,
                      'missing_cards': missing, 'duplicate_id': duplicates[0]['id'] if duplicates else None,
                      'fingerprint': digest}
            if preview: return result
            if body.get('fingerprint') != digest: raise ValueError('请先预览当前分享文件，再导入')
            if duplicates: return {'id': duplicates[0]['id'], 'name': duplicates[0]['name'], 'duplicate': True}
            # Fresh identity never overwrites a saved plan or source session.
            identifier = str(uuid.uuid4())
            imported = deepcopy(plan)
            imported.update(id=identifier, selected_deck='', plan_stage='saved', saved_ms=self.clock(), edit_revision=1,
                            classification=selection, imported=True, import_fingerprint=digest)
            if vocabulary != self.document():
                original_vocabulary = self.document()
                vocabulary['revision'] += 1
                self.save_vocabulary(vocabulary)
                try: self.write(self.store.plan_path(identifier), imported)
                except OSError:
                    self.write(self.path, original_vocabulary)
                    raise
            else: self.write(self.store.plan_path(identifier), imported)
            return {'id': identifier, 'name': imported['name'], 'duplicate': False}
