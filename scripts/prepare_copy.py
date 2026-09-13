"""Copy a YGOPro installation without changing it; keep private evidence local."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil


def inventory(root: Path) -> dict:
    paths = sorted(root.rglob("*"))
    if any(p.is_symlink() or p.is_junction() for p in paths):
        raise RuntimeError("Refusing a source containing links or junctions")

    def describe(path: Path):
        stat = path.stat()
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return path.relative_to(root).as_posix(), {
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": digest,
        }

    with ThreadPoolExecutor(max_workers=8) as workers:
        files = dict(workers.map(describe, (p for p in paths if p.is_file())))
    return {
        "files": files,
        "directories": {
            p.relative_to(root).as_posix(): p.stat().st_mtime_ns
            for p in paths if p.is_dir()
        },
        "bytes": sum(item["size"] for item in files.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    source = args.source.resolve(strict=True)
    target = workspace / ".local" / "YGOPro-Lite"
    evidence = workspace / ".local" / "evidence"
    baseline = evidence / "source-baseline.json"
    if source == target or source in target.parents or target in source.parents:
        raise RuntimeError("Source and copy must be independent directories")
    if args.verify:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
        actual = inventory(source)
        if actual != expected:
            changed = sorted(set(actual["files"]) ^ set(expected["files"]))
            changed += [name for name in actual["files"].keys() & expected["files"].keys()
                        if actual["files"][name] != expected["files"][name]]
            raise RuntimeError(f"Original changed: {changed!r}")
        print(f"Original unchanged: {len(actual['files'])} files, {actual['bytes']} bytes")
        return
    if target.exists() or baseline.exists():
        raise RuntimeError("Refusing to overwrite an existing copy or baseline")
    evidence.mkdir(parents=True, exist_ok=True)
    before = inventory(source)
    baseline.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Source recorded: {len(before['files'])} files, {before['bytes']} bytes", flush=True)
    shutil.copytree(source, target, copy_function=shutil.copy2)
    copied = inventory(target)
    if copied["files"] != before["files"]:
        raise RuntimeError("Copy verification failed")
    if inventory(source) != before:
        raise RuntimeError("Source changed during copy")
    print(f"Verified independent copy: {target}", flush=True)


if __name__ == "__main__":
    main()
