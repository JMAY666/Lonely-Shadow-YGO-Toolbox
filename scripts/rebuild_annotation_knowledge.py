"""Preview or apply the annotation-driven purpose upgrade to an idle profile."""
import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Catalog, read_json, atomic_json, now
from annotation_knowledge import AnnotationKnowledge
from card_annotations import CardAnnotations
from card_capabilities import CardCapabilities
from desktop_runtime import ServiceLock
from intelligence import Intelligence
from opening_workspace import OpeningWorkspace
from plan_library import PlanLibrary


def profile_store(runtime):
    # Do not instantiate Store: its startup recovery can update session metadata.
    store = SimpleNamespace(runtime=runtime, root=runtime / '_trainer', lock=threading.RLock())
    store.catalog = Catalog(runtime)
    store.library = PlanLibrary(store, read_json, atomic_json, now)
    store.intelligence = Intelligence(store)
    store.card_annotations = CardAnnotations(store, read_json, atomic_json, now)
    store.card_capabilities = CardCapabilities(store)
    store.opening_workspace = OpeningWorkspace(store, read_json, atomic_json, now)
    store.annotation_knowledge = AnnotationKnowledge(store)
    return store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    runtime = args.runtime.resolve(strict=True)
    if not (runtime / 'cards.cdb').is_file(): parser.error('目标不是有效运行目录，未修改任何资料')
    lock_path = runtime / '_trainer/service.lock'
    with ServiceLock(lock_path, create=args.apply) if args.apply or lock_path.exists() else nullcontext():
        store = profile_store(runtime)
        before = store.library.document()
        had_library = store.library.path.exists()
        previous = before.get('intelligence', {})
        compiled = store.annotation_knowledge.build()
        result = {'mode': 'apply' if args.apply else 'preview', 'covered_cards': len(compiled['covered']),
                  'unavailable_cards': len(compiled['unavailable']),
                  'before': {key: len(previous.get(key, {})) for key in compiled['libraries']},
                  'generated': {key: len(rows) for key, rows in compiled['libraries'].items()},
                  'revision_before': before['revision']}
        if args.apply:
            result['changed'] = store.annotation_knowledge.upgrade()
            after = store.library.document()
            result['revision_after'] = after['revision']
            result['after'] = {key: len(after['intelligence'][key]) for key in compiled['libraries']}
            result['backup'] = str(store.root / 'backups/tags' / f"{before['revision']}.json") if result['changed'] and had_library else None
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
