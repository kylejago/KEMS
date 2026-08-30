"""Regression coverage for Alpha8.35 Agile deadline transition dominance."""

from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from kems_core.deadline_dominance import maximum_discharge_targets
from kems_core.tomorrow_soc_handoff import (
    project_tomorrow_midnight_soc,
    reconcile_precheap_projection,
)

ROOT = Path(__file__).parents[1]
LONDON = ZoneInfo("Europe/London")


def test_uploaded_1530_maximum_discharge_cannot_remain_zero() -> None:
    """A maximum-discharge scan must own the command even after a price hold."""
    targets = maximum_discharge_targets(
        battery_headroom_kw=7.0,
        house_load_kw=0.6,
        solar_kw=0.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        export_allowed=True,
    )

    # The 27 Aug 15:30 diagnostic recorded maximum_discharge with a 0/0 kW
    # target/outcome. Once that mode is active, a lower-priority zero selected
    # slot must be replaced by the maximum safe house-first battery path.
    assert targets.battery_to_home_kw == 0.6
    assert targets.battery_export_kw == 6.4
    assert targets.total_discharge_kw == 7.0


def test_deadline_dominance_remains_solar_and_export_limit_aware() -> None:
    targets = maximum_discharge_targets(
        battery_headroom_kw=4.5,
        house_load_kw=0.6,
        solar_kw=2.5,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        export_allowed=True,
    )

    assert targets.battery_to_home_kw == 0.0
    assert targets.battery_export_kw == 4.5
    assert targets.total_discharge_kw == 4.5


def test_deadline_dominance_never_bypasses_export_permission() -> None:
    targets = maximum_discharge_targets(
        battery_headroom_kw=7.0,
        house_load_kw=0.8,
        solar_kw=0.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=7.0,
        export_allowed=False,
    )

    assert targets.battery_to_home_kw == 0.8
    assert targets.battery_export_kw == 0.0
    assert targets.total_discharge_kw == 0.8


def test_uploaded_2149_unreachable_soc_handoff_uses_best_reachable_soc() -> None:
    """33.9% with only 11.748 kWh AC capacity cannot truthfully hand off 10%."""
    projected, evidence = reconcile_precheap_projection(
        projected_precheap_soc_percent=10.0,
        current_soc_percent=33.9,
        remaining_discharge_capacity_kwh=11.748,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        reserve_soc_percent=10.0,
        target_physically_reachable_now=False,
    )

    assert projected == 11.982
    assert evidence["applied"] is True
    assert evidence["best_reachable_precheap_soc_percent"] == 11.982

    midnight_soc, handoff = project_tomorrow_midnight_soc(
        now=datetime(2026, 8, 27, 21, 49, tzinfo=LONDON),
        current_soc_percent=33.9,
        projected_precheap_soc_percent=projected,
        battery_capacity_kwh=56.42,
        max_charge_kw=7.0,
        charge_efficiency=0.95,
        offpeak_start=time(23, 30),
        offpeak_end=time(5, 30),
    )
    assert handoff["starting_soc_percent"] == 11.982
    assert midnight_soc == 17.875


def test_reachable_target_keeps_forecast_projection_unchanged() -> None:
    projected, evidence = reconcile_precheap_projection(
        projected_precheap_soc_percent=10.0,
        current_soc_percent=40.0,
        remaining_discharge_capacity_kwh=20.0,
        battery_capacity_kwh=56.42,
        discharge_efficiency=0.95,
        reserve_soc_percent=10.0,
        target_physically_reachable_now=True,
    )

    assert projected == 10.0
    assert evidence["applied"] is False


def test_final_canonical_layer_runs_after_total_discharge_ledger() -> None:
    compat = (ROOT / "custom_components/kems/agile_alpha7_compat.py").read_text()
    dominance = (
        ROOT / "custom_components/kems/agile_deadline_dominance.py"
    ).read_text()
    handoff = (
        ROOT / "custom_components/kems/agile_tomorrow_soc_handoff.py"
    ).read_text()

    assert compat.rfind("install_deadline_dominance") > compat.rfind(
        "install_total_discharge_ledger"
    )
    assert '"maximum_discharge"' in dominance
    assert '"maximum_discharge_plan_reconciled": True' in dominance
    assert '"hardware_writes": "blocked"' in dominance
    assert "reconcile_precheap_projection(" in handoff
    assert ".services.async_call(" not in dominance
    assert "safe_to_write_hardware = True" not in dominance


def test_alpha835_version_and_release_scope() -> None:
    manifest = json.loads(
        (ROOT / "custom_components" / "kems" / "manifest.json").read_text()
    )
    bundle = json.loads((ROOT / "release" / "kems-bundle.template.json").read_text())

    version = str(manifest["version"])
    assert version.startswith("0.8.0-alpha8.")
    assert int(version.rsplit(".", 1)[-1]) >= 35
    assert bundle["maintenance"]["affected_components"] == ["kems_core", "dashboard"]
    assert bundle["maintenance"]["home_assistant_restart_required"] is True
    assert bundle["maintenance"]["reboot_required"] is False
    assert bundle["components"]["panel"]["version"] == "0.8.0-alpha8-panel.1"
    assert bundle["components"]["property_web"]["version"] == "0.8.0-alpha8-web.8"
