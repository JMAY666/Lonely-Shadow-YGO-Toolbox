"""Knowledge store: persistence for editable deck-knowledge projects and
immutable installed knowledge packages (not model training)."""

import copy
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from knowledge_schema import (
    digest,
    dependencies,
    impact as compute_impact,
    inputs_for,
    inspect_document,
    merge_value,
    new_document,
    validate_document,
    _VER_RE,
)

BUNDLE_FORMAT = 'ygo-deck-knowledge-bundle'
_REGISTRY = 'registry.json'
_SEMVER = _VER_RE


def _now():
    return datetime.now(timezone.utc).isoformat()


def _new_id():
    return uuid.uuid4().hex


def _version_tuple(value):
    main, _, suffix = str(value).partition('-')
    if not _SEMVER.fullmatch(str(value)): raise ValueError('版本号格式无效')
    pre = tuple((0, int(part)) if part.isdigit() else (1, part) for part in suffix.split('.')) if suffix else ()
    return (*map(int, main.split('.')), not bool(suffix), pre)


class KnowledgeStore:
    def __init__(self, root, read, write, cards=None, app_version='1.42.0'):
        self._root = Path(root)
        self._read = read
        self._write = write
        self._cards = cards
        self._app_version = app_version
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- paths

    def _key(self, *parts):
        return str(digest(list(parts)))[:32]

    def _safe_path(self, rel):
        if not isinstance(rel, str) or not rel:
            raise ValueError('invalid storage path')
        if self._root.is_symlink() or getattr(self._root, 'is_junction', lambda: False)():
            raise ValueError('知识包目录不能是符号链接或目录联接')
        base = self._root.resolve()
        current = self._root
        for segment in rel.split('/'):
            if (not segment or segment in ('.', '..') or segment.startswith('.')
                    or any(ch in segment for ch in '\\:*?"<>|')):
                raise ValueError('unsafe storage path: %r' % rel)
            current = current / segment
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise ValueError('symlink rejected: %s' % segment)
            resolved = current.resolve()
            if resolved != base and base not in resolved.parents:
                raise ValueError('storage path escapes root')
        return current

    def _read_json(self, rel):
        path = self._safe_path(rel)
        if not path.is_file():
            if path.exists(): raise ValueError('知识包存储路径不是文件，请保留数据并检查目录')
            return None
        data = self._read(path)
        if not isinstance(data, dict):
            raise ValueError('corrupt storage object: %s' % rel)
        return data

    def _write_json(self, rel, obj):
        path = self._safe_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write(path, copy.deepcopy(obj))

    # ------------------------------------------------------------- registry

    def _load_registry(self):
        raw = self._read_json(_REGISTRY)
        if raw is None:
            return {'revision': 0, 'packages': {}, 'overrides': {}}
        if (type(raw.get('revision')) is not int or raw['revision'] < 0
                or not isinstance(raw.get('packages'), dict)
                or not isinstance(raw.get('overrides'), dict)
                or not isinstance(raw.setdefault('projects', {}), dict)):
            raise ValueError('registry corrupt')
        return raw

    def _commit(self, registry, expected):
        previous = self._load_registry()
        if type(expected) is not int or registry.get('revision') != expected or previous['revision'] != expected:
            raise ValueError('知识包列表已更新，当前输入保留；请刷新后核对')
        self._write_json('registry-history/%d-%s.json' % (expected, digest(previous)), previous)
        registry['revision'] = expected + 1
        self._write_json(_REGISTRY, registry)
        return registry['revision']

    def registry(self):
        with self._lock:
            return copy.deepcopy(self._load_registry())

    def snapshot(self):
        with self._lock:
            registry = self._load_registry()
            projects = []
            for project_id, meta in registry.get('projects', {}).items():
                row = {'id': project_id, 'revision': meta.get('revision'),
                       'name': meta.get('name', ''), 'theme': meta.get('theme', ''),
                       'updated': meta.get('updated')}
                try:
                    current = self._load_project(project_id)
                    package = current['document']['package']
                    row.update({'revision': current['revision'], 'name': package.get('name', ''),
                                'theme': package.get('theme', ''), 'updated': current.get('updated')})
                except (ValueError, OSError, KeyError, TypeError) as error:
                    row['error'] = str(error)
                projects.append(row)
            packages = []
            for package_id, entry in registry['packages'].items():
                versions = [{'version': version, 'digest': slot.get('digest'),
                             'installed': bool(slot.get('installed'))}
                            for version, slot in sorted(entry.get('versions', {}).items(),
                                                        key=lambda item: _version_tuple(item[0]))]
                active = entry.get('active')
                status = 'inactive' if active is None else ('active' if entry.get('enabled') else 'disabled')
                packages.append({'id': package_id, 'name': entry.get('name', ''),
                                 'theme': entry.get('theme', ''), 'active': active,
                                 'enabled': bool(entry.get('enabled')),
                                 'versions': versions, 'status': status, 'compute_enabled': bool(entry.get('compute_enabled')),
                                 'environment': entry.get('versions', {}).get(active, {}).get('environment', ''),
                                 'counts': entry.get('versions', {}).get(active, {}).get('counts', {})})
            overrides = sum(len(records)
                            for versions in registry['overrides'].values()
                            for records in versions.values())
            return copy.deepcopy({'revision': registry['revision'], 'projects': projects,
                                  'packages': packages, 'personal_overrides': overrides})

    # ------------------------------------------------------------- projects

    def _project_dir(self, project_id):
        return 'projects/%s' % self._key('project', project_id)

    def _load_project(self, project_id):
        meta = self._load_registry().get('projects', {}).get(project_id)
        if not meta: raise ValueError('制作项目不存在')
        data = self._read_json(meta['snapshot'])
        if data is None:
            raise ValueError('project not found: %s' % project_id)
        if not isinstance(data.get('document'), dict) or not isinstance(data.get('revision'), int):
            raise ValueError('project corrupt: %s' % project_id)
        if data.get('id') != project_id or data['revision'] != meta['revision'] or digest(data) != meta.get('digest'):
            raise ValueError('制作项目快照与版本索引不一致，已保留原文件')
        validate_document(data['document'])
        return data

    def _persist_project(self, project, registry):
        folder = self._project_dir(project['id'])
        fingerprint = digest(project)
        snapshot = '%s/revisions/%d-%s.json' % (folder, project['revision'], fingerprint)
        if self._read_json(snapshot) is None: self._write_json(snapshot, project)
        package = project['document']['package']
        registry.setdefault('projects', {})[project['id']] = {
            'id': project['id'], 'revision': project['revision'], 'updated': project['updated'],
            'name': package.get('name', ''), 'theme': package.get('theme', ''),
            'package_id': package.get('id', ''),
            'snapshot': snapshot, 'digest': fingerprint,
        }

    def _inspect(self, document):
        cards = self._cards() if callable(self._cards) else None
        return inspect_document(copy.deepcopy(document), cards)

    def _view(self, project, extra=None):
        result = copy.deepcopy(project)
        result['inspection'] = self._inspect(project['document'])
        if extra:
            result.update(copy.deepcopy(extra))
        return result

    def create(self, name='新知识包', theme='', document=None):
        with self._lock:
            registry = self._load_registry()
            if document is None:
                doc = validate_document(new_document(name, theme))
            else:
                doc = validate_document(document)
            project = {'id': _new_id(), 'revision': 1, 'updated': _now(), 'document': doc}
            self._persist_project(project, registry)
            self._commit(registry, registry['revision'])
            return self._view(project)

    def project(self, project_id):
        with self._lock:
            return self._view(self._load_project(project_id))

    def save(self, project_id, revision, document):
        with self._lock:
            registry = self._load_registry()
            project = self._load_project(project_id)
            if type(revision) is not int or project['revision'] != revision:
                raise ValueError('制作项目已更新，当前输入保留；请刷新后核对')
            old_doc = project['document']
            if (not isinstance(document, dict)
                    or document.get('package', {}).get('id') != old_doc['package'].get('id')):
                raise ValueError('package id is immutable')
            new_doc = validate_document(document)
            if new_doc.get('checks') != old_doc.get('checks'):
                raise ValueError('checks are immutable; only review() may append checks')
            records = {}
            for record_id, record in new_doc['records'].items():
                previous = old_doc['records'].get(record_id)
                if previous is None:
                    record['revision'] = 1
                else:
                    if record['kind'] != previous['kind']: raise ValueError('既有记录的类型不能改变，请新建记录')
                    payload = {k: v for k, v in record.items() if k != 'revision'}
                    old_payload = {k: v for k, v in previous.items() if k != 'revision'}
                    record['revision'] = (previous['revision'] if payload == old_payload
                                          else previous['revision'] + 1)
                records[record_id] = record
            for record_id, previous in old_doc['records'].items():
                if record_id not in records:
                    tombstone = copy.deepcopy(previous)
                    tombstone['deleted'] = True
                    tombstone['revision'] = previous['revision'] + (0 if previous.get('deleted') else 1)
                    records[record_id] = tombstone
            new_doc['records'] = records
            impact = compute_impact(copy.deepcopy(old_doc), copy.deepcopy(new_doc))
            project['document'] = new_doc
            project['revision'] = revision + 1
            project['updated'] = _now()
            self._persist_project(project, registry)
            self._commit(registry, registry['revision'])
            return self._view(project, {'impact': impact})

    def review(self, project_id, revision, target, note='', kind='human'):
        with self._lock:
            if kind not in ('human', 'structure'):
                raise ValueError('review kind must be human or structure')
            registry = self._load_registry()
            project = self._load_project(project_id)
            if type(revision) is not int or project['revision'] != revision:
                raise ValueError('制作项目已更新，当前输入保留；请刷新后核对')
            doc = project['document']
            if target not in doc.get('records', {}):
                raise ValueError('unknown review target: %s' % target)
            if kind == 'structure':
                scope = set(inputs_for(doc, target) or [])
                scope.add(target)
                blocking = [issue for issue in self._inspect(doc)['issues']
                            if issue.get('blocking') and issue.get('record') in scope]
                status = 'failed' if blocking else 'passed'
            else:
                status = 'passed'
            check = {'id': _new_id(), 'target': target, 'type': kind,
                     'status': status, 'at': _now(), 'note': note, 'inputs': inputs_for(doc, target)}
            doc['checks'] = list(doc.get('checks', [])) + [check]
            project['document'] = validate_document(doc)
            project['revision'] = revision + 1
            project['updated'] = _now()
            self._persist_project(project, registry)
            self._commit(registry, registry['revision'])
            return self._view(project)

    def record_engine_check(self, project_id, expected_inputs, check):
        """Internal rule worker commit; there is deliberately no HTTP operation for this."""
        with self._lock:
            registry = self._load_registry(); project = self._load_project(project_id)
            if inputs_for(project['document'], check['target']) != expected_inputs: return False
            prior = next((old for old in project['document']['checks'] if old['id'] == check['id']), None)
            if prior:
                if prior['status'] == 'passed' or prior['status'] == check['status']: return True
                # A later, stronger run is a new immutable check, never an overwritten old result.
                check = {**check, 'id': check['id'][:100] + '-' + _new_id()[:12]}
            project['document']['checks'].append(copy.deepcopy(check))
            project['document'] = validate_document(project['document'])
            project['revision'] += 1; project['updated'] = _now()
            self._persist_project(project, registry); self._commit(registry, registry['revision'])
            return True

    # -------------------------------------------------- bundle and publishing

    def bundle(self, project_id, revision, version):
        with self._lock:
            if not isinstance(version, str) or not _SEMVER.fullmatch(version):
                raise ValueError('version must be semver X.Y.Z')
            project = self._load_project(project_id)
            if type(revision) is not int or project['revision'] != revision:
                raise ValueError('制作项目已更新，不能发布旧的编辑状态')
            doc = copy.deepcopy(project['document'])
            doc['package']['version'] = version
            doc = validate_document(doc, strict=True)
            package_id = doc['package']['id']
            document_digest = digest(doc)
            published_rel = 'published/%s.json' % self._key('published', package_id, version)
            published = self._read_json(published_rel)
            if published is not None:
                if published.get('digest') != document_digest:
                    raise ValueError('package %s %s already published with different digest'
                                     % (package_id, version))
            release_rel = '%s/releases/%s.json' % (self._project_dir(project_id),
                                                   self._key('release', version, document_digest))
            if self._read_json(release_rel) is None:
                self._write_json(release_rel, {'format': BUNDLE_FORMAT, 'schema': 1,
                                               'document': doc, 'digest': document_digest})
            if published is None:
                self._write_json(published_rel, {'package_id': package_id, 'version': version,
                    'digest': document_digest, 'project_id': project_id, 'revision': revision,
                    'release': release_rel, 'at': _now()})
            return {'format': BUNDLE_FORMAT, 'schema': 1,
                    'document': copy.deepcopy(doc), 'digest': document_digest}

    # ----------------------------------------------------------- preview path

    def _compatibility(self, package):
        app_min = package.get('app_min') or '0.0.0'
        if _version_tuple(app_min) <= _version_tuple(self._app_version):
            return True, ''
        return False, '当前应用 %s，知识包要求至少 %s' % (self._app_version, app_min)

    def _overlay_conflicts(self, doc, overrides):
        conflicts = []
        for record_id, override in overrides.items():
            base = override.get('base')
            local = override.get('local')
            incoming = doc.get('records', {}).get(record_id)
            if not isinstance(incoming, dict) or incoming.get('deleted'):
                conflicts.append({'record': record_id, 'paths': ['<deleted>'],
                                  'base': copy.deepcopy(base), 'local': copy.deepcopy(local),
                                  'incoming': copy.deepcopy(incoming), 'merged': None})
                continue
            merged, paths = merge_value(copy.deepcopy(base), copy.deepcopy(local),
                                        copy.deepcopy(incoming))
            merged['revision'] = incoming['revision']
            paths = [p for p in paths if p != 'revision']
            if paths:
                conflicts.append({'record': record_id, 'paths': paths,
                                  'base': copy.deepcopy(base), 'local': copy.deepcopy(local),
                                  'incoming': copy.deepcopy(incoming), 'merged': merged})
        return conflicts

    def _preview(self, bundle, registry):
        if (not isinstance(bundle, dict) or bundle.get('format') != BUNDLE_FORMAT
                or type(bundle.get('schema')) is not int or bundle['schema'] != 1 or not isinstance(bundle.get('document'), dict)):
            raise ValueError('invalid bundle wrapper')
        raw_digest = bundle.get('digest')
        if raw_digest != digest(bundle['document']):
            raise ValueError('bundle digest mismatch')
        doc = validate_document(bundle['document'], strict=True)
        if digest(doc) != raw_digest:
            raise ValueError('bundle content not canonically normalized')
        package = doc['package']
        entry = registry['packages'].get(package['id'], {})
        existing = entry.get('versions', {}).get(package['version'])
        duplicate = False
        if existing is not None:
            if existing.get('digest') != raw_digest:
                raise ValueError('package %s %s already installed with different digest'
                                 % (package['id'], package['version']))
            duplicate = True
        active = entry.get('active')
        overrides = registry['overrides'].get(package['id'], {}).get(active, {}) if active else {}
        compatible, reason = self._compatibility(package)
        return {'digest': raw_digest, 'package': copy.deepcopy(package),
                'inspection': self._inspect(doc), 'compatible': compatible,
                'compatibility_reason': reason, 'duplicate': duplicate,
                'conflicts': self._overlay_conflicts(doc, overrides)}

    def preview(self, bundle):
        with self._lock:
            return copy.deepcopy(self._preview(bundle, self._load_registry()))

    # ------------------------------------------------- resolution and overlay

    def _check_resolutions(self, resolutions):
        if resolutions is None:
            return {}
        if not isinstance(resolutions, dict):
            raise ValueError('resolutions must be a dict')
        for record_id, choice in resolutions.items():
            if choice not in ('local', 'incoming'):
                raise ValueError('resolution for %s must be local or incoming' % record_id)
        return resolutions

    def _resolve_conflicts(self, conflicts, resolutions):
        choices = {}
        for conflict in conflicts:
            record_id = conflict['record']
            choice = resolutions.get(record_id)
            if choice not in ('local', 'incoming'):
                raise ValueError('未解决的覆盖冲突（%s）；可继续使用可用旧版，或提供 resolutions 后重试'
                                 % record_id)
            choices[record_id] = choice
        return choices

    @staticmethod
    def _pick_paths(merged, source, paths):
        for path in paths:
            segments = str(path).split('.')
            target_map, source_map = merged, source
            for segment in segments[:-1]:
                if not isinstance(target_map, dict) or not isinstance(source_map, dict):
                    target_map = None
                    break
                target_map = target_map.get(segment)
                source_map = source_map.get(segment)
            if (isinstance(target_map, dict) and isinstance(source_map, dict)
                    and segments[-1] in source_map):
                target_map[segments[-1]] = copy.deepcopy(source_map[segments[-1]])
        return merged

    def _migrate_overrides(self, registry, package_id, from_version, to_version,
                           incoming_doc, choices):
        if not from_version or from_version == to_version:
            return
        source = registry['overrides'].get(package_id, {}).get(from_version, {})
        if not source:
            return
        target = {}
        incoming_records = incoming_doc.get('records', {})
        for record_id, override in source.items():
            base, local = override.get('base'), override.get('local')
            incoming = incoming_records.get(record_id)
            if not isinstance(incoming, dict) or incoming.get('deleted'):
                if choices.get(record_id) == 'local' and isinstance(local, dict):
                    orphan = copy.deepcopy(local)
                    orphan['personal_orphan'] = True
                    target[record_id] = {'base': copy.deepcopy(incoming), 'local': orphan,
                                         'note': override.get('note', '')}
                continue
            merged, paths = merge_value(copy.deepcopy(base), copy.deepcopy(local),
                                        copy.deepcopy(incoming))
            paths = [p for p in paths if p != 'revision']
            merged['revision'] = incoming['revision']
            if paths:
                choice = choices.get(record_id)
                if choice == 'incoming':
                    merged, _ = merge_value(copy.deepcopy(base), copy.deepcopy(incoming), copy.deepcopy(local))
                    merged['revision'] = incoming['revision']
            if merged != incoming or override.get('note'):
                target[record_id] = {'base': copy.deepcopy(incoming), 'local': merged,
                                     'note': override.get('note', '')}
        registry['overrides'].setdefault(package_id, {})[to_version] = target

    # ------------------------------------------------------- install lifecycle

    def _load_package_document(self, package_id, version):
        stored = self._read_json('packages/%s/document.json'
                                 % self._key('package', package_id, version))
        if stored is None:
            raise ValueError('package document missing: %s %s' % (package_id, version))
        doc = stored.get('document')
        if not isinstance(doc, dict) or stored.get('digest') != digest(doc):
            raise ValueError('package document digest mismatch: %s %s' % (package_id, version))
        package = doc.get('package', {})
        if package.get('id') != package_id or package.get('version') != version:
            raise ValueError('package document mismatch: %s %s' % (package_id, version))
        expected = self._load_registry()['packages'].get(package_id, {}).get('versions', {}).get(version, {}).get('digest')
        if expected != stored['digest']: raise ValueError('知识包文件与安装时摘要不一致，已停止读取')
        validate_document(doc, strict=True)
        return copy.deepcopy(doc)

    def _record_index(self, record):
        # Index editable descriptions and card IDs; retain raw attachments only in source records.
        data = {key: value for key, value in record['data'].items()
                if key not in ('content', 'plan', 'original_branch')}
        return {'text': ' '.join([record['title'], record['kind'], str(data)]).casefold(),
                'dependencies': dependencies(record), 'tags': record.get('tags', [])}

    def _build_index(self, document, inspection):
        rows, generated, reused = {}, 0, 0
        for record_id, record in document['records'].items():
            if record.get('deleted'): continue
            content = {key: value for key, value in record.items() if key != 'revision'}
            identity = digest(['knowledge-record-index-v1', content])
            location = 'record-index/%s.json' % identity
            cached = self._read_json(location)
            if cached is None:
                cached = self._record_index(record)
                self._write_json(location, cached); generated += 1
            else:
                reused += 1
            rows[record_id] = {'identity': identity, **cached}
        return {'package_id': document['package']['id'], 'version': document['package']['version'],
                'digest': digest(document), 'counts': inspection['counts'],
                'capabilities': inspection['capabilities'], 'records': rows,
                'statistics': {'generated': generated, 'reused': reused}}

    def index_info(self, package_id, version):
        with self._lock:
            return copy.deepcopy(self._read_json('packages/%s/index.json' % self._key('package', package_id, version)) or {})

    def install(self, bundle, expected_digest, revision, enable=False, resolutions=None):
        with self._lock:
            registry = self._load_registry()
            current_revision = registry['revision']
            if type(revision) is not int or revision != current_revision:
                raise ValueError('知识包列表已更新，当前输入保留；请刷新后核对')
            if type(enable) is not bool: raise ValueError('启用状态需要明确的布尔值')
            result = self._preview(bundle, registry)
            if expected_digest != result['digest']:
                raise ValueError('bundle fingerprint mismatch')
            package = result['package']
            package_id, version = package['id'], package['version']
            document = validate_document(bundle['document'], strict=True)
            storage = 'packages/%s' % self._key('package', package_id, version)
            entry = registry['packages'].get(package_id)
            duplicate = result['duplicate']
            changed = False
            if entry is None:
                entry = {'name': package.get('name', ''), 'theme': package.get('theme', ''),
                         'active': None, 'enabled': False, 'versions': {}}
                registry['packages'][package_id] = entry
                changed = True
            slot = entry.setdefault('versions', {}).get(version)
            if slot is None:
                slot = {'digest': result['digest'], 'installed': True, 'environment': package.get('environment', ''),
                        'counts': result['inspection']['counts']}
                entry['versions'][version] = slot
                changed = True
            elif not slot.get('installed'):
                slot['installed'] = True
                changed = True
            if self._read_json('%s/document.json' % storage) is None:
                self._write_json('%s/document.json' % storage,
                                 {'format': BUNDLE_FORMAT, 'schema': 1,
                                  'digest': result['digest'], 'document': document})
            else:
                existing_document = self._read_json('%s/document.json' % storage)
                if existing_document.get('digest') != result['digest'] or digest(existing_document.get('document')) != result['digest']:
                    raise ValueError('已有版本对象不一致，拒绝覆盖；原可用版本保持不变')
            if self._read_json('%s/index.json' % storage) is None:
                self._write_json('%s/index.json' % storage,
                                 self._build_index(document, result['inspection']))
            if enable:
                if not result['compatible']:
                    raise ValueError('bundle incompatible: %s' % result['compatibility_reason'])
                choices = self._resolve_conflicts(
                    result['conflicts'], self._check_resolutions(resolutions))
                active = entry.get('active')
                if active != version:
                    self._migrate_overrides(registry, package_id, active, version,
                                            document, choices)
                    entry['active'] = version
                    changed = True
                if not entry.get('enabled'):
                    entry['enabled'] = True
                    changed = True
                entry.update(name=package['name'], theme=package['theme'])
            enabled = bool(entry.get('enabled'))
            new_revision = self._commit(registry, current_revision) if changed else current_revision
            return {'duplicate': duplicate, 'revision': new_revision, 'package_id': package_id,
                    'version': version, 'enabled': enabled, 'conflicts': []}

    def activate(self, package_id, version, revision, resolutions=None):
        with self._lock:
            registry = self._load_registry()
            current_revision = registry['revision']
            if type(revision) is not int or revision != current_revision:
                raise ValueError('知识包列表已更新，当前输入保留；请刷新后核对')
            entry = registry['packages'].get(package_id)
            if entry is None or version not in entry.get('versions', {}):
                raise ValueError('unknown package version: %s %s' % (package_id, version))
            if not entry['versions'][version].get('installed'):
                raise ValueError('version not installed: %s %s' % (package_id, version))
            if entry.get('active') == version and entry.get('enabled'):
                return self.snapshot()
            document = self._load_package_document(package_id, version)
            compatible, reason = self._compatibility(document['package'])
            if not compatible:
                raise ValueError('incompatible version: %s' % reason)
            active = entry.get('active')
            if active != version:
                overrides = registry['overrides'].get(package_id, {}).get(active, {}) if active else {}
                choices = self._resolve_conflicts(
                    self._overlay_conflicts(document, overrides),
                    self._check_resolutions(resolutions))
                self._migrate_overrides(registry, package_id, active, version, document, choices)
                entry['active'] = version
            entry['enabled'] = True
            entry.update(name=document['package']['name'], theme=document['package']['theme'])
            self._commit(registry, current_revision)
            return self.snapshot()

    def disable(self, package_id, revision):
        with self._lock:
            registry = self._load_registry()
            current_revision = registry['revision']
            if type(revision) is not int or revision != current_revision:
                raise ValueError('知识包列表已更新，当前输入保留；请刷新后核对')
            entry = registry['packages'].get(package_id)
            if entry is None:
                raise ValueError('unknown package: %s' % package_id)
            if entry.get('enabled'):
                entry['enabled'] = False
                self._commit(registry, current_revision)
            return self.snapshot()

    def uninstall(self, package_id, revision):
        with self._lock:
            registry = self._load_registry()
            current_revision = registry['revision']
            if type(revision) is not int or revision != current_revision:
                raise ValueError('知识包列表已更新，当前输入保留；请刷新后核对')
            entry = registry['packages'].get(package_id)
            if entry is None:
                raise ValueError('unknown package: %s' % package_id)
            changed = False
            for slot in entry.get('versions', {}).values():
                if slot.get('installed'):
                    slot['installed'] = False
                    changed = True
            if entry.get('enabled'):
                entry['enabled'] = False
                changed = True
            if changed:
                self._commit(registry, current_revision)
            return self.snapshot()

    # ------------------------------------------------------------ reading

    def document(self, package_id, version=None, effective=True):
        with self._lock:
            registry = self._load_registry()
            entry = registry['packages'].get(package_id)
            if entry is None:
                raise ValueError('unknown package: %s' % package_id)
            if version is None:
                version = entry.get('active')
                if not version:
                    raise ValueError('package has no active version: %s' % package_id)
            elif version not in entry.get('versions', {}):
                raise ValueError('unknown package version: %s %s' % (package_id, version))
            doc = self._load_package_document(package_id, version)
            if effective:
                for record_id, override in registry['overrides'].get(package_id, {}).get(version, {}).items():
                    local = override.get('local')
                    if not isinstance(local, dict):
                        continue
                    if record_id in doc.get('records', {}) or local.get('personal_orphan'):
                        doc.setdefault('records', {})[record_id] = copy.deepcopy(local)
            return copy.deepcopy(doc)

    def overlay(self, package_id, version, record_id, local, note, revision):
        with self._lock:
            registry = self._load_registry()
            current_revision = registry['revision']
            if type(revision) is not int or revision != current_revision:
                raise ValueError('知识包列表已更新，当前输入保留；请刷新后核对')
            entry = registry['packages'].get(package_id)
            if entry is None or version not in entry.get('versions', {}):
                raise ValueError('unknown package version: %s %s' % (package_id, version))
            if not entry['versions'][version].get('installed'):
                raise ValueError('version not installed: %s %s' % (package_id, version))
            doc = self._load_package_document(package_id, version)
            base = doc.get('records', {}).get(record_id)
            if not isinstance(base, dict):
                raise ValueError('unknown record: %s' % record_id)
            if (not isinstance(local, dict) or local.get('id') != record_id
                    or local.get('kind') != base.get('kind')):
                raise ValueError('local overlay must retain record id and kind')
            candidate = copy.deepcopy(doc)
            candidate['records'][record_id] = copy.deepcopy(local)
            normalized = validate_document(candidate)['records'][record_id]
            normalized['revision'] = base['revision']
            registry['overrides'].setdefault(package_id, {}).setdefault(version, {})[record_id] = {
                'base': copy.deepcopy(base), 'local': normalized, 'note': str(note or '')}
            self._commit(registry, current_revision)
            return self.snapshot()

    def catalog(self, kinds=None):
        with self._lock:
            registry = self._load_registry()
            wanted = {kinds} if isinstance(kinds, str) else (set(kinds) if kinds is not None else None)
            results = []
            for package_id, entry in registry['packages'].items():
                if not entry.get('enabled'):
                    continue
                version = entry.get('active')
                if not version:
                    continue
                doc = self.document(package_id, version, effective=True)
                inspection = self._inspect(doc)
                index = self.index_info(package_id, version)
                issues = inspection.get('issues', [])
                checks = inspection.get('checks', [])
                for record_id, record in doc.get('records', {}).items():
                    if record.get('deleted'):
                        continue
                    if wanted is not None and record.get('kind') not in wanted:
                        continue
                    scope = inputs_for(doc, record_id)
                    indexed = index.get('records', {}).get(record_id)
                    if not indexed or registry['overrides'].get(package_id, {}).get(version, {}).get(record_id):
                        indexed = self._record_index(record)
                    results.append({
                        'package_id': package_id, 'version': version,
                        'package_name': entry.get('name', ''),
                        'record': copy.deepcopy(record),
                        'checks': [copy.deepcopy(c) for c in checks if c.get('target') == record_id],
                        'issues': [copy.deepcopy(i) for i in issues if i.get('record') in scope],
                        'search_text': indexed['text'], 'dependencies': indexed['dependencies'],
                        'origin': 'knowledge', 'editable': False,
                    })
            return results
