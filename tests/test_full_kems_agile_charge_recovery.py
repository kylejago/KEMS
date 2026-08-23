"""Regression contracts for Full KEMS Agile charge and solar recovery policy."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MODULE = KEMS / "agile_charge_recovery.py"
COMPAT = KEMS / "agile_alpha7_compat.py"


@dataclass(frozen=True)
class _Snapshot:
    timestamp: datetime
    cheap_period_confirmed: bool
    forecast_maximum_overnight_soc_percent: float | None = None


def _load_force_target():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_FULL_SOC_PERCENT"
            for target in node.targets
        ):
            body.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "_force_full_charge_target":
            body.append(node)
    namespace: dict[str, Any] = {"Any": Any, "replace": replace}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
            str(MODULE),
            "exec",
        ),
        namespace,
    )
    return namespace["_force_full_charge_target"]


def test_every_authoritative_cheap_slot_keeps_100_percent_target() -> None:
    force = _load_force_target()
    cheap = _Snapshot(
        datetime(2026, 8, 23, 1, 0, tzinfo=UTC),
        True,
        80.7,
    )
    day = _Snapshot(
        datetime(2026, 8, 23, 8, 0, tzinfo=UTC),
        False,
        80.7,
    )

    result = force([cheap, day])

    assert result[0] is not cheap
    assert result[0].forecast_maximum_overnight_soc_percent == 100.0
    assert result[1] is day
    assert cheap.forecast_maximum_overnight_soc_percent == 80.7


def test_morning_recovery_window_uses_configured_overnight_schedule_only() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "_morning_recovery_window" in source
    assert "tariff.offpeak_start" in source
    assert "tariff.offpeak_end" in source
    assert "agile._next_cheap" in source
    assert "cheap_period_confirmed" not in source.split(
        "def _morning_recovery_window", 1
    )[1].split("def _event_slot_starts", 1)[0]


def test_recovery_masks_only_deliberate_battery_export_decisions() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "_RECOVERY_DECISION_RATE_PENCE = -100.0" in source
    assert "_masked_rates" in source
    assert "_restore_real_rates" in source
    assert "_restore_recovery_solar_export" in source
    assert "solar recovery to 100% before deliberate battery export" in source
    assert "export solar surplus after recovery charging" in source


def test_manual_happy_hour_slots_are_excluded_from_recovery_price_mask() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "_event_slot_starts" in source
    assert "excluded_starts=event_starts" in source
    assert "valid_from not in excluded_starts" in source


def test_recovery_finance_is_restored_to_real_agile_prices() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "_recalculate_export_finance" in source
    assert '"export_income_pence"' in source
    assert '"weighted_achieved_export_rate_pence"' in source
    assert "agile.FIXED_EXPORT_PENCE" in source
    assert 'item["rate_pence"] = round(value, 5)' in source


def test_charge_recovery_installs_immediately_before_final_reconciliation() -> None:
    source = COMPAT.read_text(encoding="utf-8")
    charge = '("agile_charge_recovery", "install_charge_recovery_policy")'
    final = (
        '("agile_dispatch_reconciliation", '
        '"install_dispatch_reconciliation")'
    )

    assert charge in source
    assert final in source
    assert source.index(charge) < source.index(final)
    assert "agile_alpha8" not in MODULE.name


def test_policy_explicitly_keeps_100_charge_and_10_reserve() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "_FULL_SOC_PERCENT = 100.0" in source
    assert '"battery_reserve_target_soc_percent": 10.0' in source
    assert "hold deliberate battery export until solar recovers 100% SOC" in source


def test_charge_recovery_cannot_enable_hardware_writes() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "real hardware writes remain blocked" in source
