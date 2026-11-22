"""Report exact duplicate KEMS Python modules without altering runtime code.

An identical blob does not prove either import path is unused: old Alpha7
module names and semantic runtime names may both be imported by compatibility
code. This tool only reports candidates for a separately reviewed migration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def duplicate_python_modules(root: Path) -> list[dict[str, object]]:
    """Return exact duplicate Python-file groups under KEMS, sorted by path."""
    directory = root / "custom_components" / "kems"
    if not directory.is_dir():
        raise ValueError(f"KEMS integration directory not found: {directory}")
    groups: dict[tuple[int, str], list[str]] = defaultdict(list)
    for path in sorted(directory.rglob("*.py")):
        if path.is_symlink():
            continue
        content = path.read_bytes()
        key = len(content), hashlib.sha256(content).hexdigest()
        groups[key].append(path.relative_to(root).as_posix())
    return [
        {"bytes_per_file": size, "sha256": digest, "paths": paths}
        for (size, digest), paths in sorted(groups.items(), key=lambda item: item[1][0])
        if len(paths) > 1
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only exact Python duplicate inventory for KEMS."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root containing custom_components/kems",
    )
    arguments = parser.parse_args()
    groups = duplicate_python_modules(arguments.root)
    repeated_bytes = sum(
        int(item["bytes_per_file"]) * (len(item["paths"]) - 1) for item in groups
    )
    print(
        json.dumps(
            {
                "groups": len(groups),
                "repeated_bytes": repeated_bytes,
                "candidate_groups": groups,
                "runtime_files_deleted": 0,
                "requires_import_graph_review": True,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
