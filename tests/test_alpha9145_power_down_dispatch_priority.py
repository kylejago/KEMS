"""Alpha9.145: active Power Down target beats an unrelated Agile rolling zero."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kems_core import ControlConfig, ControlEngine, SimulationState, Snapshot

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"


def _plan(
    *,
    active: bool = True,
    session_target: float | None = 4.867,
    rolling_export: float | None = 0.002,
    house: float = 2.404,
    inverter_limit: float = 7.0,
    export_limit: float = 7.0,
    battery_limit: float = 7.0,
    emergency_stop: bool = False,
):
    now = datetime(2026, 10, 26, 18, 47, tzinfo=UTC)
    snapshot = Snapshot(
        timestamp=now,
        saving_session_active=active,
        saving_session_joined=active,
        saving_session_start=datetime(2026, 10, 26, 18, tzinfo=UTC),
        saving_session_end=datetime(2026, 10, 26, 19, tzinfo=UTC),
        house_load_kw=house,
        battery_soc=40.0,
        solar_power_kw=0.0,
        grid_import_kw=0.0,
        grid_export_kw=0.0,
        off_peak=False,
    )
    simulated = SimulationState(
        ready=True,
        saving_session_active=active,
        saving_session_joined=active,
        saving_session_export_target_kw=session_target,
        current_simulated_battery_export_power_kw=rolling_export,
        current_simulated_battery_to_home_power_kw=house,
        current_simulated_house_load_kw=house,
        current_simulated_solar_power_kw=0.0,
        export_tariff_active=True,
    )
    config = ControlConfig(
        operating_mode="control",
        control_enabled=True,
        commissioned=True,
        emergency_stop=emergency_stop,
        normal_reserve_percent=15.0,
        max_discharge_kw=battery_limit,
        inverter_limit_kw=inverter_limit,
        export_limit_kw=export_limit,
    )
    return ControlEngine().plan(snapshot, simulated, now, config)


def test_active_joined_event_prefers_reserved_power_down_target() -> None:
    control = _plan()
    assert control.operating_reason == "power_down_session"
    # Site output is capped at 7 kW: 2.404 kW house + 4.596 kW export.
    assert control.desired_battery_export_power_kw == 4.596
    assert control.desired_total_discharge_power_kw == 7.0
    assert control.desired_work_mode == "Feed-in First"
    assert control.desired_ev_charging_allowed is False
    assert control.commands_permitted is False  # Planner is not the writer.
    assert control.real_backend_available is False


def test_explicit_zero_event_target_is_not_replaced_by_rolling_export() -> None:
    control = _plan(session_target=0.0, rolling_export=4.0)
    assert control.desired_battery_export_power_kw == 0.0
    assert control.desired_work_mode == "Self Use"


def test_missing_event_target_preserves_previous_fallback() -> None:
    control = _plan(session_target=None, rolling_export=1.5)
    assert control.desired_battery_export_power_kw == 1.5


def test_high_home_load_and_dno_limit_constrain_event_export() -> None:
    assert _plan(house=7.5).desired_battery_export_power_kw == 0.0
    control = _plan(house=1.0, export_limit=2.0)
    assert control.desired_battery_export_power_kw == 2.0
    assert control.desired_total_discharge_power_kw == 3.0
    assert _plan(house=1.0, battery_limit=1.1).desired_battery_export_power_kw == 0.1


def test_inactive_event_preserves_normal_non_event_dispatch() -> None:
    control = _plan(active=False, session_target=4.867, rolling_export=0.002)
    assert control.operating_reason != "power_down_session"


def test_emergency_stop_still_blocks_event_export() -> None:
    control = _plan(emergency_stop=True)
    assert control.operating_reason == "emergency_stop"
    assert control.desired_battery_export_power_kw == 0.0


def test_no_bypass_of_physical_guard_or_live_joined_authority() -> None:
    src = (ROOT / "coordinator.py").read_text()
    foxess = (ROOT / "foxess_control_backend.py").read_text()
    for token in (
        "guard_paid_agile_physical_export(",
        "active_joined_power_down_window(",
        "power_down_export_authorised=power_down_export_authorised",
        "await self._foxess_control.async_update(",
    ):
        assert token in src
    assert "_bounded_paid_export_discharge_setpoint(" in foxess
    assert "_PAID_EXPORT_STAGE_KW = 1.0" in foxess
    assert "_PAID_EXPORT_PROOF_SAMPLES = 2" in foxess
