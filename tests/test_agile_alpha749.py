"""Regression coverage for Alpha7.49 deadline/price-plan reconciliation."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha749_deadline_plan_coverage.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha749-deadline-price-plan-coverage.md"


def test_alpha749_version_and_module_parse() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    version = str(manifest["version"])
    assert version.startswith("0.7.0-alpha7.")
    assert int(version.rsplit(".", 1)[-1]) >= 49
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha749_installs_after_alpha748() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha749_deadline_plan_coverage_patch" in loader
    assert loader.rindex(
        "install_alpha749_deadline_plan_coverage_patch()"
    ) > loader.rindex("install_alpha748_full_battery_solar_patch()")


def test_alpha749_uses_solar_aware_capacity_before_suppressing_guard() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "alpha734._capacity_segments(" in source
    assert 'targets.get("mode") or "") != "deadline_following"' in source
    assert '"deadline_guard_escalated_from" not in targets' in source
    assert "future_capacity + _COVERAGE_TOLERANCE_KWH >= required" in source
    assert '"deadline_guard_suppressed_by_plan_coverage": True' in source
    assert '"deadline_guard_active": False' in source


def test_reported_case_does_not_trust_non_solar_aware_slot_margin() -> None:
    """The 21 Aug evidence has only 0.331 kWh physical deadline margin."""
    required_discharge_kwh = 48.239
    solar_aware_remaining_capacity_kwh = 48.571
    rolling_slot_capacity_kwh = 53.754
    rolling_exportable_kwh = 38.086
    rolling_planned_export_kwh = 38.086

    physical_margin = solar_aware_remaining_capacity_kwh - required_discharge_kwh
    slot_margin = rolling_slot_capacity_kwh - rolling_exportable_kwh

    assert round(physical_margin, 3) == 0.332
    assert round(slot_margin, 3) == 15.668
    assert rolling_planned_export_kwh == rolling_exportable_kwh
    assert physical_margin < 0.5


def test_alpha749_rebalances_forced_export_from_lowest_value_future_slot() -> None:
    """Required early export must replace, not add to, the economic plan."""
    future = [
        {"label": "16:00", "rate": 21.11, "kwh": 3.5},
        {"label": "19:00", "rate": 16.67, "kwh": 3.086},
        {"label": "19:30", "rate": 16.78, "kwh": 3.5},
    ]
    moved = 0.7
    original_total = sum(item["kwh"] for item in future)

    remaining = moved
    for item in sorted(future, key=lambda row: row["rate"]):
        reduction = min(item["kwh"], remaining)
        item["kwh"] -= reduction
        remaining -= reduction
        if remaining <= 1e-6:
            break

    assert round(future[1]["kwh"], 3) == 2.386
    assert round(sum(item["kwh"] for item in future) + moved, 3) == round(
        original_total,
        3,
    )


def test_alpha749_reconciles_current_slot_and_next_export_evidence() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert '"deadline_forced": True' in source
    assert '"selected_slots": selected' in source
    assert '"next_export_slot": next_slot' in source
    assert '"required_in_current_slot_kwh": round(new_current, 3)' in source
    assert '"deadline_plan_rebalanced": True' in source
    assert "required early export replaces lowest-value later selected export" in source


def test_alpha749_keeps_hardware_writes_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real FoxESS hardware writes remain blocked" in source


def test_alpha749_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.49" in source
    assert "48.239 kWh" in source
    assert "48.571 kWh" in source
    assert "15.668 kWh" in source
    assert "lowest-value" in source
    assert "Real FoxESS hardware writes remain blocked" in source
