"""Parity contracts for canonical Alpha8 deadline/price-plan reconciliation."""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
CANONICAL = KEMS / "agile_deadline_plan_reconciliation.py"


def test_canonical_deadline_plan_reconciliation_parses() -> None:
    ast.parse(CANONICAL.read_text(encoding="utf-8"), filename=str(CANONICAL))


def test_deadline_following_keeps_solar_aware_coverage_contract() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert "alpha734._capacity_segments(" in source
    assert 'targets.get("mode") or "") != "deadline_following"' in source
    assert '"deadline_guard_escalated_from" not in targets' in source
    assert "future_capacity + _COVERAGE_TOLERANCE_KWH >= required" in source
    assert '"deadline_guard_suppressed_by_plan_coverage": True' in source
    assert '"deadline_guard_active": False' in source
    assert '"mode": "price_optimised"' in source


def test_deadline_forced_export_keeps_equal_energy_rebalance_contract() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert '"deadline_forced": True' in source
    assert '"selected_slots": selected' in source
    assert '"next_export_slot": next_slot' in source
    assert '"required_in_current_slot_kwh": round(new_current, 3)' in source
    assert '"deadline_plan_rebalanced": True' in source
    assert "required early export replaces lowest-value later selected export" in source

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


def test_maximum_discharge_reconciliation_preserves_deadline_decision() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert 'targets.get("mode") or "") != "maximum_discharge"' in source
    assert '"deadline_guard_escalated_from" not in targets' in source
    assert 'guard.get("deadline_guard_active")' in source
    assert 'targets.get("battery_export_target_kw")' in source
    assert "_rebalance_deadline_forced_current_slot(" in source
    assert '"maximum_discharge_plan_reconciled"' in source
    assert '"deadline_guard_active": True' in source

    now = datetime.fromisoformat("2026-08-21T15:58:42.749112+01:00")
    slot_end = datetime.fromisoformat("2026-08-21T16:00:00+01:00")
    required_current_kwh = 4.316 * (slot_end - now).total_seconds() / 3600.0
    assert round(required_current_kwh, 3) == 0.093


def test_canonical_deadline_module_does_not_depend_on_retired_749_or_751() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert "agile_alpha749_deadline_plan_coverage" not in source
    assert "agile_alpha751_maximum_discharge_plan_reconcile" not in source


def test_canonical_deadline_module_keeps_hardware_writes_blocked() -> None:
    source = CANONICAL.read_text(encoding="utf-8")
    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real FoxESS hardware writes remain blocked" in source
