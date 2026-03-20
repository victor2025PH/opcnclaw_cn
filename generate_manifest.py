# -*- coding: utf-8 -*-
"""
Generate version_manifest.json for GitHub Releases.

Usage:
    python generate_manifest.py          # output to stdout
    python generate_manifest.py -o dist/version_manifest.json

The manifest contains SHA256 hashes for all project files that participate
in the auto-update system.  Excluded: .env, data/, models/, ssl/, logs/,
backup/, dist/, __pycache__, .git, node_modules, etc.
"""

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", "dist", "backup",
    "data", "models", "ssl", "logs", ".venv", "venv",
    "installer", ".cursor",
}

EXCLUDE_FILES = {
    ".env", ".env.bak", "config.ini",
}

EXCLUDE_SUFFIXES = {
    ".pyc", ".pyo", ".egg-info", ".db", ".log",
    ".bak", ".tmp", ".swp",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_files() -> dict:
    manifest = {}
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT)
        parts = rel.parts

        if any(d in EXCLUDE_DIRS for d in parts):
            continue
        if rel.name in EXCLUDE_FILES:
            continue
        if rel.suffix in EXCLUDE_SUFFIXES:
            continue

        rel_posix = rel.as_posix()
        manifest[rel_posix] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
    return manifest


def main():
    version_file = PROJECT_ROOT / "version.txt"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "0.0.0"

    files = collect_files()
    manifest = {
        "version": version,
        "file_count": len(files),
        "files": files,
    }

    output = json.dumps(manifest, indent=2, ensure_ascii=False)

    if len(sys.argv) > 2 and sys.argv[1] == "-o":
        out_path = Path(sys.argv[2])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Manifest written to {out_path} ({len(files)} files, version {version})")
    else:
        print(output)


if __name__ == "__main__":
    main()
