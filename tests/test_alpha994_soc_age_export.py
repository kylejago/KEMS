"""Alpha9.94: safe extended physical SOC corroboration for paid Agile export."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import guard_paid_agile_physical_export

NOW = datetime(2026, 10, 14, 5, 21, 51, tzinfo=UTC)


def _snapshot(**changes: object) -> Snapshot:
    values = dict(
        timestamp=NOW,
        battery_soc=100.0,
        battery_power_kw=1.118,
        house_load_kw=0.975,
        grid_import_kw=0.0,
        grid_export_kw=0.269,
        ev_connected=False,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=28.7,
        source_data_age_seconds=9.2,
        source_age_seconds={
            "battery_soc": 1515.3,
            "battery_power_kw": 9.2,
            "house_load_kw": 9.2,
            "grid_import_kw": 9.2,
            "grid_export_kw": 9.2,
            "solar_power_kw": 1515.3,
        },
        next_offpeak_start=NOW + timedelta(hours=17),
    )
    values.update(changes)
    return Snapshot(**values)


def _control() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_to_home_power_kw=0.975,
        desired_battery_export_power_kw=1.362,
        desired_total_discharge_power_kw=2.337,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def _guard(
    snapshot: Snapshot | None = None,
    control: ControlState | None = None,
) -> tuple[ControlState, dict[str, object]]:
    return guard_paid_agile_physical_export(
        control or _control(),
        snapshot or _snapshot(),
        SimpleNamespace(
            ready=True,
            expected_house_remaining_today_kwh=19.503,
            expected_solar_remaining_today_kwh=11.958,
            confidence_percent=72.0,
        ),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_reserve_percent=15.0,
            discharge_efficiency=0.95,
            max_discharge_kw=7.0,
        ),
        ControlConfig(stale_data_seconds=180),
        now=NOW,
        ev_export_safe=True,
        ev_export_evidence="confirmed_unplugged",
    )


def test_real_morning_1515_second_soc_can_prove_safe_agile_export() -> None:
    plan, detail = _guard()
    assert plan.desired_battery_export_power_kw == 1.362
    assert detail["status"] == "permitted_with_physical_house_budget"
    assert detail["soc_freshness_basis"] == (
        "same_device_cohort_with_worst_case_discharge"
    )
    assert detail["raw_physical_soc_age_seconds"] == 1515.3
    assert 15.0 < detail["physical_soc_lower_bound_percent"] < 100.0
    assert detail["pessimistic_soc_aging_discharge_kwh"] > 4.4
    assert detail["minimum_battery_reserve_kwh"] == 8.463
    assert detail["protected_home_energy_kwh"] > 24.0
    assert detail["exportable_physical_energy_kwh"] > 0.0


def test_extended_window_is_pessimistic_and_caps_available_energy() -> None:
    fresh, fresh_detail = _guard(
        _snapshot(source_age_seconds={"battery_soc": 9.2})
    )
    aged, aged_detail = _guard()
    assert aged.desired_battery_export_power_kw <= (
        fresh.desired_battery_export_power_kw
    )
    assert aged_detail["physical_soc_lower_bound_percent"] < (
        fresh_detail["physical_soc_lower_bound_percent"]
    )
    assert aged_detail["exportable_physical_energy_kwh"] < (
        fresh_detail["exportable_physical_energy_kwh"]
    )
    upper, upper_detail = _guard(
        _snapshot(
            source_age_seconds={
                "battery_soc": 3600.0,
                "battery_power_kw": 1.0,
            },
        )
    )
    assert upper.desired_battery_export_power_kw > 0.0
    assert upper_detail["raw_physical_soc_age_seconds"] == 3600.0


def test_extended_age_with_low_physical_soc_still_protects_house_and_reserve() -> None:
    rejected, detail = _guard(_snapshot(battery_soc=60.0))
    assert rejected.desired_battery_export_power_kw == 0.0
    assert detail["physical_soc_lower_bound_percent"] < 60.0
    assert detail["status"] == "blocked"
    assert "reserved for house and safety" in detail["reason"]


def test_missing_unverified_or_expired_soc_never_authorises_agile_export() -> None:
    for source in (
        _snapshot(battery_soc=None),
        _snapshot(stale_fields=("battery_soc",)),
        _snapshot(source_data_age_seconds=181.0),
        _snapshot(source_age_seconds={"battery_soc": 1515.3}),
        _snapshot(
            source_age_seconds={
                "battery_soc": 3600.1,
                "battery_power_kw": 1.0,
            }
        ),
        _snapshot(
            source_age_seconds={
                "battery_soc": 1515.3,
                "battery_power_kw": 181.0,
            }
        ),
        _snapshot(source_age_seconds={}),
    ):
        blocked, detail = _guard(source)
        assert blocked.desired_battery_export_power_kw == 0.0, detail
        assert detail["status"] == "blocked", detail


def test_expired_soc_blocks_even_when_foxess_power_is_fresh() -> None:
    blocked, detail = _guard(
        _snapshot(
            source_age_seconds={
                "battery_soc": 5000.0,
                "battery_power_kw": 0.1,
                "grid_import_kw": 0.1,
            },
        )
    )
    assert blocked.desired_battery_export_power_kw == 0.0
    assert "too old to bound" in detail["reason"]


def test_cheap_charge_and_zero_export_routes_remain_untouched() -> None:
    from dataclasses import replace

    idle = replace(_control(), desired_battery_export_power_kw=0.0)
    untouched, detail = _guard(control=idle)
    assert untouched is idle
    assert detail["status"] == "no_deliberate_export_requested"

    cheap = _snapshot(cheap_period_confirmed=True)
    unchanged, detail = _guard(snapshot=cheap)
    assert unchanged is not None
    assert detail["status"] == "higher_priority_cheap_or_event"
