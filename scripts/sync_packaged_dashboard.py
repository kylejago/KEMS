"""Keep the HACS-installed dashboard copy aligned with the repository source."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "dashboards" / "kems_master_dashboard.yaml"
TARGET = ROOT / "custom_components" / "kems" / "kems_master_dashboard.yaml"


def main() -> int:
    """Synchronise or validate the packaged dashboard copy."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    source = SOURCE.read_bytes()
    target = TARGET.read_bytes() if TARGET.exists() else None
    if source == target:
        return 0

    if args.check:
        print(
            "Packaged KEMS dashboard is out of date. "
            "Run: python scripts/sync_packaged_dashboard.py"
        )
        return 1

    TARGET.write_bytes(source)
    print(f"Updated {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
