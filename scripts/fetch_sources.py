"""Fetch pinned public build inputs into the ignored local build directory."""

from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

WORKSPACE = Path(__file__).resolve().parents[1]
SOURCE = WORKSPACE / ".local" / "upstream"
DOWNLOADS = WORKSPACE / ".local" / "downloads"


def fetch(item):
    name, url, expected, strip = item
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    archive = DOWNLOADS / (name + (".zip" if ".zip" in url or "codeload" in url else ".tar.gz"))
    if not archive.exists():
        with urllib.request.urlopen(url, timeout=90) as response:
            archive.write_bytes(response.read())
    data = archive.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if expected and actual != expected:
        raise RuntimeError(f"Checksum mismatch: {name}")
    target = SOURCE if name in ("premake", "client") else SOURCE / name
    target.mkdir(parents=True, exist_ok=True)

    def output_path(filename):
        parts = Path(filename).parts[1:] if strip else Path(filename).parts
        if not parts:
            return None
        path = target.joinpath(*parts).resolve()
        if not path.is_relative_to(target.resolve()):
            raise RuntimeError("Archive path escaped its destination")
        return path

    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.infolist():
                p = output_path(member.filename)
                if p is None:
                    continue
                if member.is_dir():
                    p.mkdir(parents=True, exist_ok=True)
                else:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(z.read(member))
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as z:
            for member in z.getmembers():
                p = output_path(member.name)
                if p is None:
                    continue
                if member.isdir():
                    p.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(z.extractfile(member).read())
                elif member.issym() or member.islnk():
                    # Build inputs do not need archive symlinks.
                    continue
    print(f"Fetched and checked {name}", flush=True)
    return {"name": name, "url": url, "sha256": actual}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true', help='Verify cached archives without unpacking or changing source')
    args = parser.parse_args()
    lock = json.loads((WORKSPACE / 'scripts/source-lock.json').read_text(encoding='utf-8'))
    if args.verify_only:
        for item in [lock['client_archive'], *lock['inputs']]:
            suffix = '.zip' if '.zip' in item['url'] or 'codeload' in item['url'] else '.tar.gz'
            archive = DOWNLOADS / (item['name'] + suffix)
            if hashlib.sha256(archive.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Checksum mismatch: ' + item['name'])
        print('All pinned archives verified; existing source unchanged')
        return
    if not (SOURCE / 'gframe/gframe.cpp').exists():
        item = lock['client_archive']
        fetch((item['name'], item['url'], item['sha256'], True))
    items = [(item['name'], item['url'], item['sha256'], item['name'] != 'premake') for item in lock['inputs']]
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch, items))
    for folder in ["premake", "resource"]:
        for p in (SOURCE / folder).iterdir():
            destination = SOURCE / p.name
            if p.is_dir():
                shutil.copytree(p, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(p, destination)
    shutil.copy2(SOURCE / "premake/event/msvc-event-config.h", SOURCE / "event/include/event2/event-config.h")
    shutil.copy2(SOURCE / "event/WIN32-Code/nmake/evconfig-private.h", SOURCE / "event/include/evconfig-private.h")
    shutil.copy2(SOURCE / "jpeg/src/jversion.h.in", SOURCE / "jpeg/src/jversion.h")
    shutil.copy2(SOURCE / "png/scripts/pnglibconf.h.prebuilt", SOURCE / "png/pnglibconf.h")



if __name__ == "__main__":
    main()
