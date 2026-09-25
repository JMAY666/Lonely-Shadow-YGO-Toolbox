"""Build the product's purpose libraries and opening roles from annotations.

The older public catalogues provide reviewed PURPOSE membership only. Effect
text, conditions, notes and version identities come from current annotations.
"""
from copy import deepcopy
import json
from pathlib import Path

from card_annotations import digest, processing_actions
from card_capabilities import fingerprint, purpose_candidates
from intelligence import CARD_LIBRARIES, data, handtrap_data, main_card, purpose_tag
from intelligence_marks import notes_value, normalize_mark
from intelligence_staples import load_catalog


MANAGER = 'card-annotations'
OPENING_ROLES = {'handtraps': 'handtrap', 'breakers': 'breaker'}


class AnnotationKnowledge:
    def __init__(self, store):
        self.store = store
        self._cache_key = None
        self._cache = None
        self._enabled_stamp = None
        self._enabled = False
        self.public = load_catalog()
        self.protection = json.loads((Path(__file__).parent / 'opening-protection.json').read_text('utf-8'))

    def enabled(self, document=None):
        if document is not None: return bool(document.get('intelligence', {}).get('annotation_sync'))
        try: stat = self.store.library.path.stat()
        except FileNotFoundError: return False
        stamp = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        if stamp != self._enabled_stamp:
            self._enabled = self.enabled(self.store.library.document())
            self._enabled_stamp = stamp
        return self._enabled

    def build(self):
        annotations = self.store.card_annotations
        cache_key = (id(annotations.curated), id(annotations.document), id(annotations._views), id(self.store.catalog))
        if self._cache_key == cache_key: return self._cache
        seeds = {card['code']: card for card in self.public['cards']}
        protection = {card['code']: card for card in self.protection['cards']}
        covered = set(annotations.curated['cards']) | {int(code) for code, row in annotations.document['cards'].items()
            if row.get('draft', {}).get('review', {}).get('origin') in ('manual', 'engine')
            and row['draft']['review'].get('status') == 'reviewed'}
        libraries = {kind: {} for kind in ('endboards', *CARD_LIBRARIES)}
        folders, opening, versions, unavailable = {}, {}, {}, []
        for code in sorted(covered):
            capability = self.store.card_capabilities.card(code, classify=False)
            versions[str(code)] = capability['version']
            if not capability['trusted']:
                unavailable.append(code); continue
            card = self.store.catalog.cards[code]
            raw_effects = {row['key']: row for row in annotations.view(code)['effects']}
            selected = {kind: [] for kind in libraries}
            bases = {kind: set() for kind in libraries}
            for effect in capability['effects']:
                raw = raw_effects[effect['key']]
                label = chr(0x245f + raw['number']) if raw.get('number') else 'text'
                seed = seeds.get(code)
                known = bool(seed and digest(seed['desc']) == capability['text_digest'] and label in seed['effects'])
                roles = {row['role'] for row in purpose_candidates(raw)}
                actions = list(processing_actions(raw.get('structure', {}).get('processing', [])))
                if known:
                    # A card-level purpose must not leak onto its unrelated search
                    # or follow-up effect merely because the old notes include it.
                    zones = raw.get('structure', {}).get('activation', {}).get('zones', [])
                    if 'handtraps' in seed['groups'] and ('hand' in zones or raw.get('effect_type') == 'trap_activation'):
                        roles.add('handtraps')
                    if 'breakers' in seed['groups'] and (set(actions) & {
                            'destroy', 'banish', 'send_grave', 'return_deck', 'return_hand', 'negate_effect',
                            'negate_activation', 'set_position', 'take_control', 'lock'} or label == 'text' or
                            'special_summon' in actions and '对方' in effect['text'] or
                            any(row.get('action') == 'add_hand' and set(row.get('from_zones', [])) & {
                                'field', 'monster', 'spell', 'opponent_monster', 'field_spell', 'pendulum'}
                                for row in raw.get('structure', {}).get('processing', []))): roles.add('breakers')
                if not main_card(card): roles.discard('handtraps')
                for role in roles & libraries.keys():
                    selected[role].append(effect)
                    bases[role].add('已核对用途' if known and role in seed['groups'] else '标注推导')
                opening_roles = sorted({OPENING_ROLES[role] for role in roles if role in OPENING_ROLES})
                protector = protection.get(code)
                if protector and digest(protector['desc']) == capability['text_digest'] and label in protector['effects']:
                    opening_roles.append('protection')
                if 'draw' in actions or any(row.get('action') == 'add_hand' and
                        set(row.get('from_zones', [])) & {'deck', 'grave', 'banished'} and
                        '对方' not in row.get('selector', {}).get('text', '')
                        for row in raw.get('structure', {}).get('processing', [])):
                    opening_roles.append('resource')
                if opening_roles:
                    sources = capability['sources']
                    source = next((row for row in sources if 'db.yugioh-card.com' in row.get('url', '')), sources[0] if sources else {})
                    key = f'{code}:{effect["key"]}'
                    opening[key] = {'key': key, 'code': code, 'name': card['name'], 'text': effect['text'],
                        'roles': list(dict.fromkeys(opening_roles)), 'allowed_roles': list(dict.fromkeys(opening_roles)),
                        'priority': 'primary', 'note': '', 'reviewed': True, 'managed_by': MANAGER,
                        'condition': self.conditions([effect]),
                        'explanation': [f'{row["label"]}：{row["text"]}' for row in effect['facts'] if row['label'] not in ('条件', '时点')]
                                       + [row['text'] for row in effect['notes'] if row.get('text')],
                        'source': {'id': 'card-annotations', 'url': source.get('url', ''), 'checked_on': source.get('checked_on', '')},
                        'version': fingerprint({'annotation': capability['version'], 'roles': opening_roles}), 'effect_ref': effect['ref'],
                        'basis': '已核对用途' if known else '标注推导'}
            for kind, effects in selected.items():
                if not effects: continue
                names = list(dict.fromkeys(tag['name'] for effect in effects for tag in effect['tags']))
                folder_id = None
                if kind in CARD_LIBRARIES:
                    group = next((tag['category'] for effect in effects for tag in effect['tags'] if tag['category'] in ('disruption', 'removal', 'restriction', 'resource')), 'utility')
                    folder_id = f'annotation:{kind}:{group}'
                    folders[folder_id] = {'id': folder_id, 'name': annotations.registry.categories[group], 'kind': kind, 'managed_by': MANAGER}
                legacy = {effect['legacy_key']: notes_value([{'text': f'{row["label"]}：{row["text"]}'} for row in effect['facts']] + effect['notes'])
                          for effect in effects if effect['legacy_key'] is not None}
                note = '、'.join(names) or '具体用途见效果与条件'
                record = {'code': code, 'desc': card['desc'], 'candidate': kind == 'endboards',
                    **notes_value([{'text': note}]), 'condition': self.conditions(effects), 'folder_id': folder_id,
                    'effects': legacy, 'effect_keys': [effect['key'] for effect in effects],
                    'effect_refs': [effect['ref'] for effect in effects], 'unmatched_effects': [], 'sources': [],
                    'managed_by': MANAGER, 'annotation_version': capability['version'], 'classification_basis': ' / '.join(sorted(bases[kind]))}
                libraries[kind][str(code)] = normalize_mark(record) if kind == 'endboards' else handtrap_data(record, self.store.catalog.cards)
        result = {'libraries': libraries, 'folders': folders, 'opening': opening, 'covered': sorted(covered),
                  'unavailable': unavailable, 'version': fingerprint({'schema': 1, 'versions': versions, 'libraries': libraries, 'opening': opening})}
        self._cache_key, self._cache = cache_key, result
        return result

    def classify(self, capability):
        compiled = self.build()
        names = {'handtraps': '手坑', 'breakers': '解场', 'endboards': '终场用途'}
        roles = []
        for kind, rows in compiled['libraries'].items():
            record = rows.get(str(capability['code']))
            if record:
                roles.append({'role': kind, 'name': names[kind], 'basis': record['classification_basis'],
                              'effects': list(record['effect_keys'])})
        capability['roles'] = roles
        for effect in capability['effects']:
            effect['roles'] = [role for role in roles if effect['key'] in role['effects']]
        capability['version'] = fingerprint({'annotation': capability['version'], 'roles': roles})

    @staticmethod
    def conditions(effects):
        lines = list(dict.fromkeys(f'{row["label"]}：{row["text"]}' for effect in effects for row in effect['facts']
                                  if row['label'] in ('条件', '时点', '费用', '次数')))
        text = '\n'.join(lines)
        return text if len(text) <= 3800 else text[:3780] + '…完整条件见统一标注。'

    def synchronize(self, *, enable=False, force=False):
        with self.store.lock:
            document = self.store.library.document()
            if not enable and not self.enabled(document): return False
            compiled = self.build()
            old = document.get('intelligence', {}).get('annotation_sync') or {}
            knowledge = data(document, self.store.catalog.cards)
            covered = set(compiled['covered']) | set(old.get('covered_codes', []))
            current = {kind: {code: row for code, row in knowledge[kind].items()
                             if int(code) in covered or row.get('managed_by') == MANAGER} for kind in compiled['libraries']}
            if old.get('version') == compiled['version'] and current == compiled['libraries'] and not force: return False
            for kind, generated in compiled['libraries'].items():
                knowledge[kind] = {code: row for code, row in knowledge[kind].items()
                                   if int(code) not in covered and row.get('managed_by') != MANAGER}
                knowledge[kind].update(deepcopy(generated))
            knowledge['folders'] = {key: row for key, row in knowledge['folders'].items() if row.get('managed_by') != MANAGER}
            knowledge['folders'].update(deepcopy(compiled['folders']))
            used_folders = {row.get('folder_id') for kind in CARD_LIBRARIES for row in knowledge[kind].values()}
            knowledge['folders'] = {key: row for key, row in knowledge['folders'].items() if key in used_folders}
            knowledge['annotation_sync'] = {'schema': 1, 'version': compiled['version'],
                'covered_codes': compiled['covered'], 'unavailable_codes': compiled['unavailable'],
                'counts': {kind: len(rows) for kind, rows in compiled['libraries'].items()},
                'backup_revision': old.get('backup_revision', document['revision'])}
            document['intelligence'] = knowledge
            for kind in CARD_LIBRARIES:
                tag = purpose_tag(document, kind=kind)
                tag.update(managed_by=MANAGER, source='卡片标注 · 自动用途分类')
                document['entries'][tag['id']] = tag
            document['revision'] += 1
            # Existing atomic writes back up the complete old TAG/knowledge file first.
            self.store.library.save_vocabulary(document)
            return True

    def upgrade(self):
        changed = self.synchronize(enable=True)
        workspace = self.store.opening_workspace
        with self.store.lock:
            if not workspace.path.exists(): return changed
            previous = workspace.document()
            updated = deepcopy(previous)
            covered = set(self.build()['covered'])
            for field in ('overrides', 'candidates'):
                updated[field] = {key: row for key, row in updated[field].items()
                                  if not key.split(':')[0].isdigit() or int(key.split(':')[0]) not in covered}
            if updated != previous:
                workspace.write(self.store.root / 'backups/opening-analysis' / f"{previous['revision']}.json", previous)
                updated['revision'] += 1
                workspace.write(workspace.path, updated)
        return changed
