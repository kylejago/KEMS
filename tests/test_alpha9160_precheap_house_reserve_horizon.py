"""Alpha9.161: do not protect consumption occurring after cheap import starts.

Safety tests keep the full independent 2 kWh house buffer, both the 15% target
and the 10% physical hard floor, and conservative source-quality fallbacks.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    guard_paid_agile_physical_export,
    house_forecast_to_cheap_deadline,
)

ROOT = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 10, 29, 21, 45, tzinfo=UTC)
CHEAP = NOW + timedelta(hours=1, minutes=45)
SIM = SimulationConfig(
    battery_capacity_kwh=56.42,
    battery_reserve_percent=15.0,
    discharge_efficiency=0.95,
)
CONTROL_CONFIG = ControlConfig(stale_data_seconds=180)


def _snapshot(**changes: object) -> Snapshot:
    fields = dict(
        timestamp=NOW,
        battery_soc=22.885,
        house_load_kw=0.64,
        ev_connected=False,
        ev_charging=False,
        source_data_age_seconds=5.0,
        source_age_seconds={"battery_soc": 5.0, "house_load_kw": 5.0},
        next_offpeak_start=CHEAP,
    )
    fields.update(changes)
    return Snapshot(**fields)


def _forecast():
    return SimpleNamespace(
        ready=True,
        expected_house_remaining_today_kwh=2.512,
        expected_solar_remaining_today_kwh=0.0,
        confidence_percent=90.0,
    )


def _control():
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Force Discharge",
        desired_battery_to_home_power_kw=0.64,
        desired_battery_export_power_kw=2.0,
        desired_total_discharge_power_kw=2.64,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def _load_planning():
    package_name = "kems_alpha9160_physical_planning_test"
    package = ModuleType(package_name)
    package.__path__ = [str(ROOT)]
    sys.modules[package_name] = package
    import kems_core

    sys.modules[f"{package_name}.kems_core"] = kems_core
    sys.modules[f"{package_name}.kems_core.agile_live_reserve"] = sys.modules[
        "kems_core.agile_live_reserve"
    ]
    target = f"{package_name}.agile_physical_planning"
    spec = importlib.util.spec_from_file_location(
        target, ROOT / "agile_physical_planning.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[target] = module
    spec.loader.exec_module(module)
    return module


def test_oct29_2145_house_forecast_stops_at_2330_not_midnight() -> None:
    bounded, basis = house_forecast_to_cheap_deadline(
        2.512,
        now=NOW,
        deadline=CHEAP,
        house_load_kw=0.64,
        house_age_seconds=5.0,
    )
    assert bounded == pytest.approx(2.512 * 1.75 / 2.25)
    assert basis.startswith("verified_earlier_cheap_deadline")
    # Preserve the separately applied full 2 kWh home buffer.
    assert bounded / 0.95 + 2.0 > 4.0


def test_absent_or_stale_house_never_releases_extra_export() -> None:
    for value, age, stale in (
        (None, 5.0, False),
        (0.64, None, False),
        (0.64, 91.0, False),
        (0.64, 5.0, True),
        (float("nan"), 5.0, False),
    ):
        bounded, basis = house_forecast_to_cheap_deadline(
            2.512,
            now=NOW,
            deadline=CHEAP,
            house_load_kw=value,
            house_age_seconds=age,
            house_stale=stale,
        )
        assert bounded == 2.512
        assert basis.startswith("full_calendar_day")


def test_no_horizon_shortcut_for_midnight_or_after_cheap() -> None:
    for deadline in (
        NOW,
        NOW - timedelta(minutes=1),
        NOW + timedelta(hours=3),
        NOW + timedelta(days=1),
        None,
    ):
        bounded, basis = house_forecast_to_cheap_deadline(
            2.512,
            now=NOW,
            deadline=deadline,
            house_load_kw=0.64,
            house_age_seconds=5.0,
        )
        assert bounded == 2.512
        assert basis.startswith("full_calendar_day")


def test_long_remaining_horizon_keeps_full_day_forecast() -> None:
    house, reason = house_forecast_to_cheap_deadline(
        5.0,
        now=NOW - timedelta(hours=5),
        deadline=CHEAP,
        house_load_kw=0.64,
        house_age_seconds=5.0,
    )
    assert house == 5.0
    assert reason == "full_calendar_day_cheap_window_too_far_away"


def test_measured_house_floor_prevents_optimistic_shortening() -> None:
    bounded, _ = house_forecast_to_cheap_deadline(
        2.512,
        now=NOW,
        deadline=CHEAP,
        house_load_kw=2.0,
        house_age_seconds=3.0,
    )
    assert bounded == 2.512


def test_live_guard_caps_small_surplus_without_relaxing_hard_gates() -> None:
    _, unchanged = guard_paid_agile_physical_export(
        _control(),
        _snapshot(source_age_seconds={"battery_soc": 5.0}),
        _forecast(),
        SIM,
        CONTROL_CONFIG,
        now=NOW,
    )
    assert unchanged["forecast_house_horizon_basis"].startswith("full_calendar_day")
    assert unchanged["independent_house_buffer_kwh"] == 2.0
    capped, report = guard_paid_agile_physical_export(
        _control(), _snapshot(), _forecast(), SIM, CONTROL_CONFIG, now=NOW
    )
    assert report["forecast_house_until_cheap_kwh"] == pytest.approx(1.954, abs=0.001)
    assert report["independent_house_buffer_kwh"] == 2.0
    assert report["minimum_battery_reserve_kwh"] == pytest.approx(8.463)
    assert capped.desired_battery_export_power_kw == 2.0
    assert report["status"] == "permitted_with_physical_house_budget"
    assert report["protected_home_energy_kwh"] > 4.0
    assert 3.0 < report["exportable_physical_energy_kwh"] < 3.3
    assert report["house_safety_floor_kwh"] == pytest.approx(5.642)

    for blocked in (
        _snapshot(ev_connected=True),
        _snapshot(battery_soc=None),
        _snapshot(tariff_stale_fields=("next_offpeak_start",)),
    ):
        refused, _ = guard_paid_agile_physical_export(
            _control(), blocked, _forecast(), SIM, CONTROL_CONFIG, now=NOW
        )
        assert refused.desired_battery_export_power_kw == 0.0


def test_planner_uses_identical_house_horizon_and_does_not_change_twin(
    monkeypatch,
) -> None:
    planning = _load_planning()
    snapshot = _snapshot()
    manager = SimpleNamespace(
        _kems_physical_planning_context={
            "snapshot": snapshot,
            "forecast_plan": _forecast(),
            "evidence": object(),
            "control": CONTROL_CONFIG,
        }
    )
    monkeypatch.setattr(
        planning,
        "physical_planning_soc",
        lambda *args, **kwargs: (
            22.885,
            {"available": True, "physical_energy_lower_bound_kwh": 12.912},
        ),
    )
    budget, report = planning.conservative_physical_export_budget(
        manager, now=NOW, config=SIM
    )
    assert report["forecast_house_until_cheap_kwh"] == pytest.approx(1.954, abs=0.001)
    assert report["independent_house_buffer_kwh"] == 2.0
    assert report["minimum_reserve_kwh"] == pytest.approx(8.463)
    assert 3.0 < budget < 3.3
    assert report["exportable_ac_kwh"] == pytest.approx(budget * 0.95, abs=0.001)
    assert snapshot.battery_soc == 22.885
