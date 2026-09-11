"""Temporary Alpha9.27 successor-release assertion migration."""

from __future__ import annotations

from pathlib import Path

FILES = (
    "tests/test_alpha8_consolidation.py",
    "tests/test_alpha913_forecast_path_scheduler.py",
    "tests/test_alpha919_runtime_recorder_owner.py",
    "tests/test_alpha920_shadow_recorder_owner.py",
    "tests/test_alpha921_planning_target_house_floor.py",
    "tests/test_alpha922_flow_contract_startup.py",
    "tests/test_alpha924_flow_parity_export_floor.py",
    "tests/test_alpha925_observability_clarity.py",
    "tests/test_alpha926_panel_layout_profiles.py",
    "tests/test_alpha9_baseline.py",
)

OLD = 'assert manifest["version"] == "0.9.0-alpha9.26"'
NEW = 'assert manifest["version"] == "0.9.0-alpha9.27"'


def main() -> None:
    for filename in FILES:
        path = Path(filename)
        text = path.read_text(encoding="utf-8")
        count = text.count(OLD)
        if count != 1:
            raise SystemExit(f"{filename}: expected exactly one current-release assertion, found {count}")
        path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
        print(f"migrated {filename}")


if __name__ == "__main__":
    main()
