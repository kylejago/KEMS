"""Alpha9.67 physical cheap-charge authority regressions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from kems_core import ControlConfig, ControlEngine, SimulationState, Snapshot
from kems_core.control_write_authority import assess_foxess_control_write_authority

ROOT = Path(__file__).resolve().parents[1]
KEMS = ROOT / "custom_components" / "kems"
MANIFEST = KEMS / "manifest.json"
BUNDLE = ROOT / "release" / "kems-bundle.template.json"

NOW = datetime(2026, 9, 20, 8, 42, tzinfo=UTC)


def _config() -> ControlConfig:
    return ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        normal_reserve_percent=15.0,
        island_reserve_percent=20.0,
        max_charge_kw=7.0,
        max_discharge_kw=7.0,
        inverter_limit_kw=7.0,
        export_limit_kw=6.4,
        eps_limit_kw=7.0,
        site_import_limit_kw=14.5,
    )


def _live_extra_slot_snapshot(*, soc: float | None = 16.0) -> Snapshot:
    return Snapshot(
        timestamp=NOW,
        current_import_rate=3.4933,
        next_import_rate=28.3036,
        # Cheap-slot confirmation itself is proven separately by the tariff
        # resolver regressions. This test exercises the downstream Control
        # boundary after that authority has already been confirmed.
        off_peak=True,
        intelligent_slot=True,
        ev_charging=True,
        ev_power_kw=6.071,
        house_load_kw=12.074,
        solar_power_kw=1.278,
        grid_import_kw=14.544,
        grid_export_kw=0.0,
        battery_soc=soc,
        battery_power_kw=-3.751,
        tariff_source_age_seconds={"intelligent_slot": 23.8},
        tariff_stale_fields=(),
        stale_fields=(),
    )


def _divergent_twin() -> SimulationState:
    return SimulationState(
        ready=True,
        no_export_mode_active=True,
        export_tariff_active=False,
        simulated_battery_soc=80.3,
        overnight_charge_target_percent=27.4,
        current_simulated_house_load_kw=12.074,
        current_simulated_solar_power_kw=1.278,
        current_simulated_grid_import_kw=10.796,
        current_simulated_grid_export_kw=0.0,
        current_simulated_battery_power_kw=0.0,
        current_simulated_battery_charge_power_kw=0.0,
        current_simulated_battery_to_home_power_kw=0.0,
        current_simulated_battery_export_power_kw=0.0,
        current_simulated_grid_bypass_power_kw=10.796,
        current_simulated_total_site_import_kw=10.796,
    )


def test_live_extra_slot_uses_physical_soc_not_divergent_twin() -> None:
    snapshot = _live_extra_slot_snapshot()
    control = ControlEngine().plan(snapshot, _divergent_twin(), NOW, _config())

    assert snapshot.cheap_period_confirmed is True
    assert control.operating_reason == "awaiting_export_tariff_charge"
    assert control.desired_work_mode == "Force Charge"
    assert control.desired_charge_power_kw == 3.704
    assert control.desired_min_soc_percent == 28.0
    assert control.grid_bypass_power_kw == 10.796
    assert control.total_site_import_kw == 14.5
    assert control.site_import_headroom_kw == 0.0
    assert control.plan_safe is True

    decision = assess_foxess_control_write_authority(
        control,
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=True,
        cheap_period_confirmed=True,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
    )
    assert decision.commands_permitted is True
    assert decision.action == "force_charge"
    assert decision.force_charge_power_kw == 3.704
    assert decision.min_soc_on_grid_percent == 28.0


def test_physical_target_reached_returns_to_self_use_even_if_twin_disagrees() -> None:
    snapshot = _live_extra_slot_snapshot(soc=28.0)
    simulation = _divergent_twin()
    control = ControlEngine().plan(snapshot, simulation, NOW, _config())

    assert control.desired_work_mode == "Self Use"
    assert control.desired_charge_power_kw == 0.0
    assert control.desired_min_soc_percent == 28.0
    assert "Hold the battery" in control.next_action


def test_missing_physical_soc_never_uses_twin_soc_to_authorise_charge() -> None:
    snapshot = _live_extra_slot_snapshot(soc=None)
    control = ControlEngine().plan(snapshot, _divergent_twin(), NOW, _config())

    assert control.desired_work_mode == "Self Use"
    assert control.desired_charge_power_kw == 0.0
    assert "fresh physical battery SOC" in control.next_action


def test_alpha967_release_identity_and_scope() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    reason = str(bundle["maintenance"]["reason"])

    assert manifest["version"] == "0.9.0-alpha9.68"
    assert reason.startswith("Alpha9.67 makes fresh physical battery SOC authoritative")
    assert "simulated SOC" in reason
    assert "solar-aware no-export target" in reason
    assert "site-import headroom" in reason
    assert "Self Use" in reason
    assert "Force Charge" in reason
    assert "Import Power Limit" in reason
    assert "Export Power Limit" in reason
