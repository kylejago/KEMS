"""Regression coverage for Alpha7.51 maximum-discharge plan reconciliation."""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parents[1]
KEMS = ROOT / "custom_components" / "kems"
PATCH = KEMS / "agile_alpha751_maximum_discharge_plan_reconcile.py"
LOADER = KEMS / "agile_smart_export_runtime.py"
MANIFEST = KEMS / "manifest.json"
DOC = ROOT / "docs" / "alpha751-maximum-discharge-plan-reconcile.md"


def test_alpha751_version_and_module_parse() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert str(manifest["version"]).startswith(("0.8.0-alpha8.", "0.9.0-alpha9."))
    ast.parse(PATCH.read_text(encoding="utf-8"))


def test_alpha751_installs_after_alpha750() -> None:
    loader = LOADER.read_text(encoding="utf-8")
    assert "install_alpha751_maximum_discharge_plan_reconcile_patch" in loader
    assert loader.rindex(
        "install_alpha751_maximum_discharge_plan_reconcile_patch()"
    ) > loader.rindex("install_alpha750_no_reserve_reporting_patch()")


def test_alpha751_only_targets_deadline_originated_maximum_discharge() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'targets.get("mode") or "") != "maximum_discharge"' in source
    assert '"deadline_guard_escalated_from" not in targets' in source
    assert 'guard.get("deadline_guard_active")' in source
    assert 'targets.get("battery_export_target_kw")' in source


def test_alpha751_reuses_alpha749_equal_energy_rebalance() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert "alpha749._rebalance_deadline_forced_current_slot(" in source
    assert 'plan["deadline_plan_rebalance"] = rebalance' in source
    assert 'targets["deadline_plan_rebalance"] = rebalance' in source
    assert '"maximum_discharge_plan_reconciled"' in source


def test_reported_1530_case_requires_about_0093_kwh_in_current_slot() -> None:
    """4.316 kW from 15:58:42.749 to 16:00 is about 0.093 kWh."""
    now = datetime.fromisoformat("2026-08-21T15:58:42.749112+01:00")
    slot_end = datetime.fromisoformat("2026-08-21T16:00:00+01:00")
    export_target_kw = 4.316

    remaining_hours = (slot_end - now).total_seconds() / 3600.0
    required_current_kwh = export_target_kw * remaining_hours

    assert round(required_current_kwh, 3) == 0.093


def test_alpha751_current_export_replaces_later_low_value_energy() -> None:
    """The forced 0.093 kWh is moved, not added to, the day's export plan."""
    current_kwh = 0.093
    later_low_value_kwh = 0.146
    original_total_kwh = 38.646

    rebalanced_later = later_low_value_kwh - current_kwh
    rebalanced_total = original_total_kwh - current_kwh + current_kwh

    assert round(rebalanced_later, 3) == 0.053
    assert round(rebalanced_total, 3) == original_total_kwh


def test_alpha751_preserves_deadline_safety_decision() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert 'targets["deadline_guard"] = guard' in source
    assert '"deadline_guard_active": True' in source
    assert 'targets["mode"] = "price_optimised"' not in source
    assert 'targets["battery_export_target_kw"] = 0.0' not in source


def test_alpha751_keeps_hardware_writes_blocked() -> None:
    source = PATCH.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "does not relax the deadline" in source
    assert "FoxESS hardware writes" in source


def test_alpha751_documentation_exists() -> None:
    source = DOC.read_text(encoding="utf-8")
    assert "0.7.0-alpha7.51" in source
    assert "15:30" in source
    assert "0.093 kWh" in source
    assert "4.316 kW" in source
    assert "maximum_discharge" in source
    assert "Real FoxESS hardware writes remain blocked" in source
