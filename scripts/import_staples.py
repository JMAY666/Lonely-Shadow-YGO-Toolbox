"""Preview or explicitly import the reviewed catalog into an inactive profile."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/trainer'))
from app import Catalog, atomic_json, read_json, now
from desktop_runtime import ServiceLock
from intelligence import Intelligence, data
from intelligence_staples import import_staples
from plan_library import PlanLibrary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    runtime = args.runtime.resolve(strict=True)
    if not (runtime / 'cards.cdb').is_file(): parser.error('Runtime must contain cards.cdb')
    with ServiceLock(runtime / '_trainer/service.lock'):
        store = SimpleNamespace(runtime=runtime, root=runtime / '_trainer', lock=threading.RLock(), catalog=Catalog(runtime))
        store.library = PlanLibrary(store, read_json, atomic_json, now)
        store.intelligence = Intelligence(store)
        existed = store.library.path.exists()
        document = store.library.document()
        original = deepcopy(document)
        knowledge = data(document, store.catalog.cards)
        preview = import_staples(store.intelligence, document, knowledge)
        report = {'applied': args.apply, 'revision_before': original['revision'], 'result': preview,
                  'counts': {kind: len(knowledge[kind]) for kind in ('handtraps', 'breakers', 'folders')}}
        if args.apply:
            result = store.intelligence.command({'revision': original['revision'], 'op': 'staples.import'})
            report['revision_after'] = result['revision']
            report['backup'] = str(store.root / 'backups/tags' / f"{original['revision']}.json") if preview['changed'] and existed else None
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
