"""Alpha9.188: paid export stops at 15%, confirmed household Self Use can reach 10%.

This tests the pure planning/authority policy and ensures the live hardware
handover does not lower the physical export floor in Force Discharge.
"""
from __future__ import annotations

from pathlib import Path

from kems_core import ControlState
from kems_core.control_write_authority import (
    assess_foxess_control_write_authority,
    resolve_live_min_soc_on_grid,
)

ROOT = Path(__file__).parents[1]
BACKEND = ROOT / "custom_components" / "kems" / "foxess_control_backend.py"


def _control(*, export: float) -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Force Discharge" if export else "Self Use",
        desired_battery_export_power_kw=export,
        desired_total_discharge_power_kw=1.0 + export,
        desired_battery_to_home_power_kw=1.0,
        desired_min_soc_percent=15.0 if export else 10.0,
        desired_grid_export_allowed=True,
        grid_available=True,
        data_fresh=True,
        plan_safe=True,
        preflight_passed=15,
        preflight_total=15,
    )


def _decision(export: float):
    return assess_foxess_control_write_authority(
        _control(export=export),
        technical_ready=True,
        binding_ready=True,
        reviewed_version_matches=True,
        no_paid_export_mode=False,
        cheap_period_confirmed=False,
        user_commissioned=True,
        master_control_enabled=True,
        emergency_stop=False,
        effective_export_limit_kw=7.0,
    )


def test_paid_export_retains_fifteen_percent_physical_floor() -> None:
    decision = _decision(3.0)
    assert decision.commands_permitted
    assert decision.action == "force_discharge"
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=10.0,
        )
        == 15.0
    )


def test_household_only_self_use_can_use_ten_percent() -> None:
    decision = _decision(0.0)
    assert decision.commands_permitted
    assert decision.action == "self_use"
    assert (
        resolve_live_min_soc_on_grid(
            decision,
            cheap_period_confirmed=False,
            previous_min_soc_on_grid=15.0,
        )
        == 10.0
    )


def test_household_lowering_requires_confirmed_no_ev_and_no_export() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    guard = source.split("household_floor_authorised = bool(", 1)[1].split(
        "effective_min_soc = resolve_live_min_soc_on_grid(", 1
    )[0]
    for check in (
        "ev_confirmed_unplugged",
        "ev_connected is False",
        "snapshot.ev_connected is False",
        "snapshot.ev_charging is False",
        "control.desired_battery_export_power_kw <= 0.001",
        "not power_down_export_authorised",
        "not happy_hour_charge_authorised",
        "not pending_intelligent_ev_hold_active",
    ):
        assert check in guard


def test_live_handover_orders_self_use_before_lowering_on_grid_floor() -> None:
    src = BACKEND.read_text(encoding="utf-8")
    start = src.index("household_floor_transition = bool(")
    scope = src[start : src.index("elif effective_min_soc is None:", start)]
    mode_write = scope.index("household_mode_verified = await self._async_select(")
    mode_verify = scope.index("household_mode_verified = await self._async_wait_state(")
    sensor_read = scope.index('self._observation_entity_id(')
    low_write = scope.index("min_soc_ok = await self._async_number(")
    physical_proof = scope.index("min_soc_ok = await self._async_wait_number(")
    assert mode_write < mode_verify < sensor_read < low_write < physical_proof
    assert '"min_soc_on_grid"' in scope
    assert "force_write=True" in scope
    assert "timedelta(seconds=120)" in scope


def test_unverified_household_10_never_claims_hardware_success() -> None:
    src = BACKEND.read_text(encoding="utf-8")
    assert 'self._household_floor_status = "readback_unverified"' in src
    assert 'self._household_floor_status = "retry_throttled"' in src
    assert 'self._household_floor_status = "verified_10_percent"' in src
    assert "and household_mode_verified" in src
    assert '"household_only_floor_verified": household_floor_verified' in src
    assert '"household_only_floor_status": self._household_floor_status' in src
    assert "if not force_write and current is not None" in src
