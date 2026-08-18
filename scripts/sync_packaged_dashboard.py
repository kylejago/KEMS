"""Keep HACS-installed dashboard copies aligned with repository sources."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).parents[1]
DASHBOARD_PAIRS = (
    (
        ROOT / "dashboards" / "kems_master_dashboard.yaml",
        ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml",
    ),
    (
        ROOT / "dashboards" / "kems_agile_smart_export_builtin.yaml",
        ROOT / "custom_components" / "kems" / "kems_agile_smart_export_dashboard.yaml",
    ),
)


def main() -> int:
    """Synchronise or validate every packaged managed dashboard copy."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    mismatches: list[tuple[Path, Path]] = []
    for source, target in DASHBOARD_PAIRS:
        source_bytes = source.read_bytes()
        target_bytes = target.read_bytes() if target.exists() else None
        if source_bytes == target_bytes:
            continue
        mismatches.append((source, target))
        if not args.check:
            target.write_bytes(source_bytes)
            print(f"Updated {target.relative_to(ROOT)}")

    if args.check and mismatches:
        for source, target in mismatches:
            print(
                f"Packaged dashboard {target.relative_to(ROOT)} is out of date "
                f"with {source.relative_to(ROOT)}."
            )
        print("Run: python scripts/sync_packaged_dashboard.py")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
