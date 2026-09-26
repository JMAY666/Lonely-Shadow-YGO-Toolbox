"""Prepare, resume, assemble and verify OCG batches without inferring card rules."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from threading import get_ident
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/trainer'))
from app import Catalog
from card_annotations import Registry, digest, segments, validate_entry
from card_series import CardSeries
from plan_tags import builtin_tags
from annotation_batch_support import atomic_bytes, atomic_json, contained_path, content_hash, read_json

PENDING_STATES = {'not_yet_reviewed', 'needs_ruling', 'requires_schema',
                  'requires_vocabulary', 'identity_problem', 'missing_sources'}


def now():
    return datetime.now(timezone.utc).isoformat()


def index_rows(rows):
    indexed = {}
    for row in rows:
        code = row['code']
        if type(code) is not int or not 0 < code < 2**32 or code in indexed:
            raise ValueError('Invalid or duplicate local integer card identity')
        indexed[code] = row
    return indexed


def batch_operation(method):
    """Serialize same-batch mutations; nested verification during apply is reentrant."""
    @wraps(method)
    def run(self, batch_id, *args, **kwargs):
        owner = get_ident()
        if self._lock_owners.get(batch_id) == owner:
            return method(self, batch_id, *args, **kwargs)
        folder = self.folder(batch_id)
        if not folder.is_dir():
            raise ValueError('Batch does not exist; prepare it first')
        lock = folder / 'operation.lock'
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise ValueError('Batch is busy, or a previous operation lock needs inspection') from error
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                stream.write(f'{os.getpid()} {method.__name__}\n')
            self._lock_owners[batch_id] = owner
            return method(self, batch_id, *args, **kwargs)
        finally:
            self._lock_owners.pop(batch_id, None)
            lock.unlink()
    return run


def compile_entry(row, decision):
    """Fill mechanical fields from frozen inputs; approval must be authored explicitly."""
    entry = deepcopy(decision)
    review = entry.get('review', {})
    if review.get('status') != 'reviewed' or review.get('origin') != 'manual' or not review.get('basis', '').strip():
        raise ValueError(f'{row["code"]}: explicit manual review is required')
    for key, value in [('code', row['code']), ('frozen_text', row['desc']), ('text_digest', row['text_digest'])]:
        if key in entry and entry[key] != value:
            raise ValueError(f'{row["code"]}: authored {key} conflicts with frozen input')
        entry[key] = value
    if 'source_ids' in entry:
        if 'sources' in entry:
            raise ValueError('Specify sources or source_ids, not both')
        originals = {s['id']: s for s in (row.get('source_record') or {}).get('sources', [])}
        if len(set(entry['source_ids'])) != len(entry['source_ids']):
            raise ValueError('Duplicate selected source id')
        entry['sources'] = []
        for identifier in entry.pop('source_ids'):
            source = originals[identifier]
            if source['status'] != 'saved':
                raise ValueError(f'{row["code"]}: source was not saved')
            url = urlparse(source['final_url'])
            if (url.scheme != 'https' or url.hostname != 'www.db.yugioh-card.com'
                    or url.username or url.password or parse_qs(url.query).get('request_locale') != ['ja']):
                raise ValueError('Compact source_ids require Japanese KONAMI OCG URLs; use explicitly reviewed bindings for other evidence')
            entry['sources'].append({'id': identifier, 'title': source['page_title'],
                                     'url': source['final_url'], 'format': 'OCG',
                                     'region': 'Japan', 'checked_on': review['checked_on']})
    if not entry.get('sources'):
        raise ValueError(f'{row["code"]}: reviewed sources are required')
    authored = entry.get('effects', {})
    if isinstance(authored, list):
        if len({e['key'] for e in authored}) != len(authored):
            raise ValueError('Duplicate effect key')
        authored = {e['key']: e for e in authored}
    expected = {s['key']: {k: v for k, v in s.items() if k != 'text'} for s in row['segments']}
    # Normal-monster flavor is preserved as frozen text, without manufacturing effects.
    if (entry.get('no_effect') is True and row['type'] & 0x1 and row['type'] & 0x10
            and not row['type'] & 0x1000020 and not authored):
        expected = {}
    if set(authored) != set(expected):
        raise ValueError(f'{row["code"]}: all frozen segments must be reviewed')
    entry['effects'] = []
    for key, base in expected.items():
        payload = deepcopy(authored[key])
        for field, value in base.items():
            if field in payload and payload[field] != value:
                raise ValueError(f'{row["code"]}: authored segment metadata changed')
        entry['effects'].append({**base, **payload})
    entry.setdefault('relations', [])
    entry.setdefault('notes', [])
    return entry


class Pipeline:
    def __init__(self, workspace=ROOT):
        self.root = Path(workspace).resolve(strict=True)
        self.private = self.root / '.local/annotation-pipeline'
        self.formal = self.root / 'src/trainer/card-annotations.json'
        self.tags = self.root / 'src/trainer/annotation-tags.json'
        self._lock_owners = {}
        if not self.formal.resolve().is_relative_to(self.root) or not self.tags.resolve().is_relative_to(self.root):
            raise ValueError('Built-in documents must stay inside the workspace')

    def folder(self, batch_id):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', batch_id):
            raise ValueError('Use a short lowercase batch id')
        folder = self.private / batch_id
        if (not (self.root / '.local').resolve().is_relative_to(self.root)
                or not folder.resolve().is_relative_to((self.root / '.local').resolve())):
            raise ValueError('Batch output must stay in workspace .local')
        return folder

    def prepare(self, batch_id, runtime, source_pack, *, codes=None, series_ids=None, all_remaining=False,
                include_reviewed=False):
        folder = self.folder(batch_id)
        if folder.exists():
            raise ValueError('Batch already exists; use status/resume rather than replacing it')
        runtime, source_pack = Path(runtime).resolve(strict=True), Path(source_pack).resolve(strict=True)
        catalog = Catalog(runtime)
        series = CardSeries(catalog, builtin_tags(runtime))
        formal = read_json(self.formal)
        source_rows = index_rows(read_json(source_pack / 'manifest.json')['cards'])
        if all_remaining:
            selected = set(catalog.cards)
        elif series_ids:
            unknown = set(series_ids) - series.members.keys()
            if unknown:
                raise ValueError(f'Unknown series: {sorted(unknown)}')
            selected = set().union(*(series.members[k] for k in series_ids))
        elif codes:
            selected = set(codes)
            if len(selected) != len(codes):
                raise ValueError('Duplicate selected code')
        else:
            raise ValueError('Select explicit codes, complete series, or all remaining cards')
        if selected - catalog.cards.keys():
            raise ValueError('Selected code is missing from the actual Catalog')
        rows, skipped = [], []
        for code in sorted(selected):
            card = catalog.cards[code]
            if card['type'] & 0x4000:
                skipped.append({'code': code, 'reason': 'token'})
                continue
            existing = formal['cards'].get(str(code))
            if (not include_reviewed and existing and existing['text_digest'] == digest(card['desc'])
                    and existing['review']['status'] == 'reviewed' and existing['review']['origin'] == 'manual'):
                skipped.append({'code': code, 'reason': 'already_reviewed_current_text'})
                continue
            source = source_rows.get(code)
            readable = bool(source and any(s.get('kind') == 'card' and s.get('status') == 'saved'
                                          for s in source.get('sources', [])))
            rows.append({'code': code, 'name': card['name'], 'type': card['type'], 'desc': card['desc'],
                         'text_digest': digest(card['desc']), 'segments': segments(card['desc'], card['type']),
                         'series': series.memberships[code], 'source_record': source,
                         'preparation_status': 'source_candidate' if readable else 'missing_sources',
                         'existing_annotation_conflict': existing is not None})
        task = {'version': 1, 'id': batch_id, 'prepared_at': now(), 'runtime': str(runtime),
                'source_pack': str(source_pack),
                'source_manifest_sha256': content_hash((source_pack / 'manifest.json').read_bytes()),
                'baseline_sha256': content_hash(self.formal.read_bytes()),
                'vocabulary_sha256': content_hash(self.tags.read_bytes()),
                'selection': {'series': series_ids or [], 'all_remaining': all_remaining,
                              'complete_series': bool(series_ids), 'include_reviewed': include_reviewed},
                'scope': 'Mechanical preparation only; source candidates and templates are not reviewed annotations.',
                'cards': rows, 'skipped': skipped}
        templates = {'version': 1, 'cards': {}, 'pending': [], 'query_cases': [], 'semantic_cases': [],
                     'purpose_cases': [], 'source_bindings': {}}
        for row in rows:
            templates['cards'][str(row['code'])] = {
                'review': {'status': 'draft', 'origin': 'auto', 'checked_on': '', 'basis': ''},
                'source_ids': [], 'effects': {s['key']: {'effect_type': 'unclassified', 'tags': [],
                                                       'structure': {}, 'notes': []} for s in row['segments']},
                'relations': [], 'notes': []}
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise ValueError('Batch was created by another writer; do not overwrite it') from error
        atomic_json(folder / 'task.json', task)
        atomic_json(folder / 'templates.json', templates)
        shapes = Counter((row['type'], len(row['segments']), tuple(s['block'] for s in row['segments'])) for row in rows)
        registry = read_json(self.tags)
        atomic_json(folder / 'schema-outline.json', {
            'scope': 'Structural grouping for advance review; no effect/category/rule decisions inferred.',
            'shapes': [{'type': shape[0], 'segments': shape[1], 'blocks': shape[2], 'count': count}
                       for shape, count in sorted(shapes.items())],
            'vocabularies': registry['vocabularies']})
        atomic_json(folder / 'ledger.json', {'version': 1, 'id': batch_id, 'phase': 'prepared',
                                           'task_sha256': content_hash(task), 'prepared_at': task['prepared_at'],
                                           'input_count': len(rows), 'reviewed_count': 0, 'integrated_count': 0})
        return {'batch': batch_id, 'prepared': len(rows), 'skipped': len(skipped),
                'source_candidates': sum(r['preparation_status'] == 'source_candidate' for r in rows),
                'reviewed': 0, 'integrated': 0}

    def task(self, batch_id):
        folder = self.folder(batch_id)
        task, ledger = read_json(folder / 'task.json'), read_json(folder / 'ledger.json')
        if task['id'] != batch_id or ledger['task_sha256'] != content_hash(task):
            raise ValueError('Frozen task changed; create a new batch instead of modifying its identity')
        return folder, task, ledger

    @batch_operation
    def packet(self, batch_id, codes):
        """Prepare faithful text packets in parallel; only the checkpoint is written serially."""
        folder, task, ledger = self.task(batch_id)
        rows = index_rows(task['cards'])
        if len(set(codes)) != len(codes) or set(codes) - rows.keys():
            raise ValueError('Packet codes must be distinct members of the frozen batch')
        pack = Path(task['source_pack'])
        if content_hash((pack / 'manifest.json').read_bytes()) != task['source_manifest_sha256']:
            raise ValueError('Source manifest changed; re-audit before preparing evidence')
        def collect(code):
            row = rows[code]
            sources = []
            for source in (row.get('source_record') or {}).get('sources', []):
                if source.get('status') != 'saved':
                    continue
                data = {}
                for kind in ('raw', 'text'):
                    path = contained_path(pack, source[kind + '_path'])
                    data[kind] = path.read_bytes()
                    if content_hash(data[kind]) != source[kind + '_sha256']:
                        raise ValueError(f'{code}: {kind} snapshot hash mismatch')
                sources.append({'metadata': source, 'text': data['text'].decode('utf-8')})
            packet = {'version': 1, 'code': code, 'name': row['name'], 'desc': row['desc'],
                      'text_digest': row['text_digest'], 'segments': row['segments'], 'sources': sources,
                      'status': 'prepared_only', 'identity_status': (row.get('source_record') or {}).get('identity_status'),
                      'preparation_status': row['preparation_status'],
                      'collection_issues': (row.get('source_record') or {}).get('issues', []),
                      'unavailable_sources': [s for s in (row.get('source_record') or {}).get('sources', [])
                                              if s.get('status') != 'saved'],
                      'scope': 'Faithful source text, not identity confirmation or rule review.'}
            atomic_json(folder / 'evidence' / f'{code}.json', packet)
            return code
        with ThreadPoolExecutor(max_workers=4) as pool:
            completed = list(pool.map(collect, codes))
        ledger['evidence_prepared_codes'] = sorted(set(ledger.get('evidence_prepared_codes', [])) | set(completed))
        ledger['evidence_prepared_at'] = now()
        atomic_json(folder / 'ledger.json', ledger)
        return {'packets': len(completed), 'codes': completed, 'reviewed': ledger['reviewed_count']}

    @batch_operation
    def assemble(self, batch_id, decisions_path, *, baseline=None, reviewed_manifest=None, supplemental_root=None):
        folder, task, ledger = self.task(batch_id)
        if ledger['phase'] == 'integrated':
            raise ValueError('Integrated batch is immutable; start a new batch for corrections')
        catalog = Catalog(Path(task['runtime']))
        registry = Registry(read_json(self.tags))
        decisions = read_json(decisions_path)
        baseline = Path(baseline) if baseline else self.formal
        baseline_bytes = baseline.read_bytes()
        document = read_json(baseline)
        rows = index_rows(task['cards'])
        if decisions.get('version') != 1 or document.get('version') != 1:
            raise ValueError('Unsupported annotation document version')
        authored = decisions.get('cards', {})
        if not isinstance(authored, dict) or any(str(int(k)) != k for k in authored):
            raise ValueError('Use canonical local integer card keys')
        pending = index_rows(decisions.get('pending', []))
        if set(map(int, authored)) - rows.keys() or pending.keys() - rows.keys():
            raise ValueError('Decisions contain cards outside the frozen task')
        if set(map(int, authored)) & pending.keys():
            raise ValueError('A card cannot be both reviewed and pending')
        manifest = read_json(reviewed_manifest) if reviewed_manifest else {
            'version': 1, 'checked_on': now()[:10], 'source_pack': Path(task['source_pack']).name,
            'source_manifest_sha256': task['source_manifest_sha256'], 'scope': task['scope'],
            'cards': [], 'updated_cards': [], 'pending': [],
            **{k: decisions.get(k, [] if k != 'source_bindings' else {})
               for k in ('query_cases', 'semantic_cases', 'purpose_cases', 'source_bindings')}}
        if manifest.get('updated_cards'):
            raise ValueError('Corrections require a separate reviewed correction workflow')
        if manifest['source_manifest_sha256'] != task['source_manifest_sha256']:
            raise ValueError('Reviewed manifest references a different source package')
        expected_rows = index_rows(manifest['cards']) if reviewed_manifest else None
        accepted, waiting, new_codes = [], [], []
        for code, row in rows.items():
            actual = catalog.cards.get(code)
            if (not actual or (actual['name'], actual['type'], actual['desc']) != (row['name'], row['type'], row['desc'])
                    or segments(actual['desc'], actual['type']) != row['segments'] or digest(actual['desc']) != row['text_digest']):
                raise ValueError(f'{code}: actual card identity/text changed')
            decision = authored.get(str(code))
            if code in pending or not decision or decision.get('review', {}).get('status') == 'draft':
                hold = pending.get(code, {'code': code, 'status': 'not_yet_reviewed', 'reason': 'Manual review not completed'})
                if hold['status'] not in PENDING_STATES or not hold.get('reason', '').strip():
                    raise ValueError(f'{code}: pending status and concrete reason are required')
                waiting.append({**hold, 'name': row['name']})
                continue
            entry = compile_entry(row, decision)
            validate_entry(entry, registry, {s['key'] for s in row['segments']}, card_type=row['type'])
            old = document['cards'].get(str(code))
            if old is not None and old != entry:
                raise ValueError(f'{code}: refusing to overwrite an existing annotation')
            if old is None:
                new_codes.append(code)
            document['cards'][str(code)] = entry
            metadata = {'code': code, 'local_name': row['name'], 'local_type': row['type'],
                        'text_digest': row['text_digest'],
                        'official_cid': (row.get('source_record') or {}).get('official_cid'), 'group': batch_id}
            if expected_rows is not None:
                metadata = expected_rows[code]
                if (metadata['local_name'], metadata['local_type'], metadata['text_digest']) != (row['name'], row['type'], row['text_digest']):
                    raise ValueError(f'{code}: reviewed manifest identity conflicts with task')
            accepted.append(metadata)
        if expected_rows is not None:
            if set(expected_rows) != {r['code'] for r in accepted}:
                raise ValueError('Reviewed manifest and decisions have different accepted cards')
            expected_pending = index_rows(manifest.get('pending', []))
            if {k: (v['status'], v['reason']) for k, v in expected_pending.items()} != {
                    r['code']: (r['status'], r['reason']) for r in waiting}:
                raise ValueError('Reviewed manifest and decisions have different pending cards')
        manifest['cards'], manifest['pending'] = accepted, waiting
        if not reviewed_manifest:
            manifest['groups'] = [{'name': batch_id, 'input_count': len(rows), 'accepted_count': len(accepted),
                                   'pending_count': len(waiting)}]
        assembly = {'version': 1, 'baseline_sha256': content_hash(baseline_bytes),
                    'new_codes': new_codes, 'already_present': len(accepted) - len(new_codes),
                    'document_sha256': content_hash(document), 'manifest_sha256': content_hash(manifest),
                    'supplemental_root': str(Path(supplemental_root).resolve(strict=True)) if supplemental_root else None,
                    'decisions_sha256': content_hash(Path(decisions_path).read_bytes())}
        atomic_json(folder / 'candidate-document.json', document)
        atomic_json(folder / 'batch-manifest.json', manifest)
        atomic_json(folder / 'assembly.json', assembly)
        ledger.update({'phase': 'assembled', 'reviewed_count': len(accepted), 'new_count': len(new_codes),
                       'pending_count': len(waiting), 'pending_states': dict(Counter(r['status'] for r in waiting)),
                       'assembled_at': now()})
        ledger.pop('verification', None)
        atomic_json(folder / 'ledger.json', ledger)
        return ledger

    @batch_operation
    def verify(self, batch_id, *, full=False):
        from check_annotation_source_batch import check
        folder, task, ledger = self.task(batch_id)
        assembly = read_json(folder / 'assembly.json')
        for filename, key in [('candidate-document.json', 'document_sha256'), ('batch-manifest.json', 'manifest_sha256')]:
            if content_hash(read_json(folder / filename)) != assembly[key]:
                raise ValueError('Assembled output changed; assemble again before checking')
        started = perf_counter()
        try:
            result = check(task['runtime'], folder / 'batch-manifest.json', task['source_pack'],
                           assembly['supplemental_root'], document_path=folder / 'candidate-document.json',
                           cache_path=folder / 'checkpoint-cache.json', full=full)
        except Exception as error:
            ledger['verification'] = {'status': 'failed', 'at': now(), 'error': str(error), 'full': full}
            if ledger['phase'] != 'integrated':
                ledger['phase'] = 'validation_failed'
            atomic_json(folder / 'ledger.json', ledger)
            raise
        result.update({'elapsed_seconds': round(perf_counter() - started, 6), 'full': full, 'at': now()})
        ledger['verification'] = result
        if ledger['phase'] != 'integrated':
            ledger['phase'] = 'verified'
        atomic_json(folder / 'ledger.json', ledger)
        return result

    @batch_operation
    def apply(self, batch_id, public_manifest):
        """Full verification, recoverable backup, optimistic concurrency, exact-path writes."""
        folder, task, ledger = self.task(batch_id)
        public_manifest = Path(public_manifest)
        public_manifest = public_manifest if public_manifest.is_absolute() else self.root / public_manifest
        if (not (self.root / 'docs').resolve().is_relative_to(self.root)
                or not public_manifest.resolve().is_relative_to((self.root / 'docs').resolve())):
            raise ValueError('Public manifest must stay in workspace docs')
        lock = self.private / 'publication.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as error:
            raise ValueError('Another publication is active, or a previous lock needs inspection') from error
        try:
            os.close(descriptor)
            self.verify(batch_id, full=True)
            assembly = read_json(folder / 'assembly.json')
            document, manifest = read_json(folder / 'candidate-document.json'), read_json(folder / 'batch-manifest.json')
            if content_hash(document) != assembly['document_sha256'] or content_hash(manifest) != assembly['manifest_sha256']:
                raise ValueError('Candidate changed after verification; assemble and verify again')
            if not manifest['cards'] or any(r['status'] == 'not_yet_reviewed' for r in manifest['pending']):
                raise ValueError('Finish the cohort review before integration; checkpoints can remain partial')
            current = self.formal.read_bytes()
            already_present = read_json(self.formal) == document
            if content_hash(current) != assembly['baseline_sha256'] and not already_present:
                raise ValueError('Built-in document changed; reassemble against the new baseline')
            if public_manifest.exists() and read_json(public_manifest) != manifest:
                raise ValueError('Refusing to replace a different public manifest')
            if not already_present:
                backup = folder / ('baseline-' + content_hash(current) + '.json')
                if backup.exists() and backup.read_bytes() != current:
                    raise ValueError('Baseline backup was modified')
                if not backup.exists():
                    atomic_bytes(backup, current)
                if content_hash(self.formal.read_bytes()) != content_hash(current):
                    raise ValueError('Concurrent annotation change before publication')
            # A retry after an interrupted manifest write can complete this operation.
            atomic_json(public_manifest, manifest)
            if not already_present:
                if self.formal.read_bytes() != current:
                    raise ValueError('Concurrent annotation change; document was not replaced')
                atomic_json(self.formal, document)
            ledger = read_json(folder / 'ledger.json')
            ledger.update({'phase': 'integrated', 'integrated_count': len(assembly['new_codes']),
                           'integrated_at': now(), 'public_manifest': str(public_manifest),
                           'published_document_sha256': content_hash(self.formal.read_bytes())})
            atomic_json(folder / 'ledger.json', ledger)
            return {'new': 0 if already_present else len(assembly['new_codes']),
                    'cohort_new_count': len(assembly['new_codes']), 'already_present': assembly['already_present'],
                    'total': len(document['cards']), 'idempotent': already_present}
        finally:
            lock.unlink()

    def status(self, batch_id):
        _, task, ledger = self.task(batch_id)
        return {**ledger, 'prepared_count': len(task['cards']),
                'source_candidates': sum(r['preparation_status'] == 'source_candidate' for r in task['cards']),
                'scope': 'Last checkpoint, not a fresh validation or a full-library completion claim.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare', help='Freeze inputs and generate draft templates only')
    prepare.add_argument('--batch', required=True)
    prepare.add_argument('--runtime', required=True)
    prepare.add_argument('--source-pack', required=True)
    prepare.add_argument('--include-reviewed', action='store_true', help='Include existing cards for replay/revalidation; never overwrite them')
    selection = prepare.add_mutually_exclusive_group(required=True)
    selection.add_argument('--codes', nargs='+', type=int)
    selection.add_argument('--series', nargs='+', dest='series_ids')
    selection.add_argument('--all-remaining', action='store_true')
    packet = sub.add_parser('packet', help='Prepare complete faithful source-text packets, using four mechanical workers')
    packet.add_argument('--batch', required=True)
    packet.add_argument('--codes', nargs='+', type=int, required=True)
    assemble = sub.add_parser('assemble', help='Compile explicitly reviewed decisions into a private candidate')
    assemble.add_argument('--batch', required=True)
    assemble.add_argument('--decisions', required=True)
    assemble.add_argument('--baseline', help='Optional immutable baseline for replay; apply checks actual current data')
    assemble.add_argument('--reviewed-manifest', help='Reuse an existing reviewed batch contract, including semantic cases')
    assemble.add_argument('--supplemental-root')
    verify = sub.add_parser('verify', help='Run actual source/structure/query checks; exact-content checkpoint cache')
    verify.add_argument('--batch', required=True)
    verify.add_argument('--full', action='store_true')
    apply = sub.add_parser('apply', help='Full revalidation and backed-up integration into built-in data')
    apply.add_argument('--batch', required=True)
    apply.add_argument('--public-manifest', required=True)
    status = sub.add_parser('status', help='Read the saved checkpoint without claiming current validity')
    status.add_argument('--batch', required=True)
    args = vars(parser.parse_args())
    command, batch = args.pop('command'), args.pop('batch')
    pipeline = Pipeline()
    if command == 'prepare':
        result = pipeline.prepare(batch, **args)
    elif command == 'assemble':
        args['decisions_path'] = args.pop('decisions')
        result = pipeline.assemble(batch, **args)
    else:
        result = getattr(pipeline, command)(batch, **args)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
