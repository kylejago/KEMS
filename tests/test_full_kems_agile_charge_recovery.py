"""Regression contracts for Full KEMS Agile charge/recovery intent."""

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


def test_100_percent_is_an_aim_not_an_export_gate() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "_FULL_SOC_PERCENT = 100.0" in source
    assert '"full_soc_is_export_gate": False' in source
    assert '"forecast_headroom_export_can_precede_full_soc": True' in source
    assert "profit-first forecast headroom export may occur before 100%" in source
    assert "_RECOVERY_DECISION_RATE_PENCE" not in source
    assert "_masked_rates" not in source


def test_charge_recovery_preserves_configured_reserve_instead_of_raising_it() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "config.battery_reserve_percent" in source
    assert '"battery_reserve_target_soc_percent"' in source
    assert "minimum_precheap_soc" not in source


def test_profit_first_headroom_installs_after_forecast_arbitrage() -> None:
    source = COMPAT.read_text(encoding="utf-8")
    forecast = '("agile_forecast_arbitrage", "install_forecast_arbitrage")'
    profit = '("agile_profit_first_headroom", "install_profit_first_headroom")'
    charge = '("agile_charge_recovery", "install_charge_recovery_policy")'

    assert forecast in source
    assert profit in source
    assert charge in source
    assert source.index(forecast) < source.index(profit) < source.index(charge)


def test_policy_documentation_keeps_100_charge_and_10_reserve() -> None:
    notes = (ROOT / "docs" / "alpha8.3-release-notes.md").read_text(encoding="utf-8")

    assert "100% is a charge/recovery aim, not a hard gate" in notes
    assert "10%" in notes
    assert "overnight replacement" in notes
    assert "highest" in notes


def test_charge_recovery_cannot_enable_hardware_writes() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert ".services.async_call(" not in source
    assert "providers.foxess" not in source
    assert "safe_to_write_hardware = True" not in source
    assert "commands_permitted = True" not in source
    assert "Real hardware writes remain blocked" in source
