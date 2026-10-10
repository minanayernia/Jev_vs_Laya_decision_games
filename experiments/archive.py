"""Archive saved experiments with checksums: python experiments/archive.py results --out runs.zip."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

FILES = ("config.json", "decisions.jsonl", "rounds.jsonl", "summary.json")


def archive_results(source: Path, output: Path) -> int:
    source = source.resolve()
    dirs = [source] if (source / "summary.json").is_file() else sorted(
        p.parent for p in source.rglob("summary.json"))
    payload = {}
    for directory in dirs:
        for name in FILES:
            path = directory / name
            if not path.is_file():
                raise ValueError(f"incomplete experiment: {path}")
            if path.is_symlink():
                raise ValueError(f"refusing symlink: {path}")
            relative = path.relative_to(source.parent if directory == source else source)
            payload[str(relative)] = path.read_bytes()
    if not payload:
        raise ValueError("no completed experiments found")
    manifest = {"format_version": 1, "experiments": len(dirs),
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}}
    # Only the four research artifacts are included, never .env or application logs.
    with ZipFile(output, "x", compression=ZIP_DEFLATED) as bundle:
        for name, data in payload.items():
            bundle.writestr(name, data)
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
    return len(dirs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        count = archive_results(args.source, args.out)
    except (ValueError, FileExistsError) as exc:
        ap.error(str(exc))
    print(f"Archived {count} experiments to {args.out}")


if __name__ == "__main__":
    main()
