"""Alpha9.97: plugged-in idle Ohme may export; real charging stops it.

Only paid Agile Control is changed. No Paid Export and the physical/EV
charging MinSOC hold remain independent and never inherit this permission.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    assess_paid_agile_ev_continuity,
    guard_paid_agile_physical_export,
)
from kems_core.control_event_refresh import meaningful_ev_power_transition

NOW = datetime(2026, 10, 14, 16, 44, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "kems"


def _snapshot(**changes: object) -> Snapshot:
    args = dict(
        timestamp=NOW,
        battery_soc=93.0,
        battery_power_kw=0.0,
        source_data_age_seconds=2.0,
        source_age_seconds={"battery_soc": 2.0, "battery_power_kw": 2.0},
        next_offpeak_start=NOW + timedelta(hours=6),
        ev_connected=True,
        ev_charging=False,
        ev_power_kw=0.0,
        ev_power_age_seconds=2.0,
    )
    args.update(changes)
    return Snapshot(**args)


def _plan() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_export_power_kw=3.0,
        desired_battery_to_home_power_kw=0.6,
        desired_total_discharge_power_kw=3.6,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def _assess(
    snapshot: Snapshot, previous_unplugged: datetime | None = None
) -> tuple[bool, datetime | None, str]:
    return assess_paid_agile_ev_continuity(
        snapshot, now=NOW, last_confirmed_unplugged_at=previous_unplugged
    )


def _guard(
    snapshot: Snapshot, *, safe: bool, evidence: str
) -> tuple[ControlState, dict]:
    return guard_paid_agile_physical_export(
        _plan(),
        snapshot,
        SimpleNamespace(
            ready=True,
            expected_house_remaining_today_kwh=2.0,
            expected_solar_remaining_today_kwh=0.0,
            confidence_percent=0.0,
        ),
        SimulationConfig(
            battery_capacity_kwh=56.42,
            battery_reserve_percent=15.0,
            discharge_efficiency=0.95,
        ),
        ControlConfig(stale_data_seconds=180),
        now=NOW,
        ev_export_safe=safe,
        ev_export_evidence=evidence,
    )


@pytest.mark.parametrize("power_kw", [0.0, 0.05, 0.1])
def test_plugged_in_idle_is_eligible_for_paid_export(power_kw: float) -> None:
    snapshot = _snapshot(ev_power_kw=power_kw)
    safe, anchor, evidence = _assess(
        snapshot, previous_unplugged=NOW - timedelta(seconds=20)
    )
    assert safe is True
    # A connected car MUST NOT retain a previous unplugged outage grace.
    assert anchor is None
    assert evidence == "confirmed_connected_idle_zero_power"
    desired, report = _guard(snapshot, safe=safe, evidence=evidence)
    assert desired.desired_battery_export_power_kw == 3.0
    assert report["status"] == "permitted_with_physical_house_budget"
    assert report["ev_export_evidence"] == evidence


@pytest.mark.parametrize(
    "changes",
    [
        {"ev_charging": True},
        {"ev_charging": None},
        {"ev_power_kw": 0.101},
        {"ev_power_kw": 7.0},
        {"ev_power_kw": -1.0},
        {"ev_power_kw": None},
        {"ev_power_age_seconds": None},
        {"ev_power_age_seconds": 30.1},
        {"ev_power_age_seconds": 181.0},
        {"stale_fields": ("ev_power_kw",)},
    ],
)
def test_plugged_in_active_uncertain_or_stale_does_not_export(
    changes: dict[str, object],
) -> None:
    snapshot = _snapshot(**changes)
    safe, anchor, _ = _assess(snapshot)
    assert not safe and anchor is None
    desired, report = _guard(
        snapshot, safe=True, evidence="confirmed_connected_idle_zero_power"
    )
    assert desired.desired_battery_export_power_kw == 0.0, report
    assert report["status"] == "blocked"


def test_guard_rejects_spoofed_connected_permission_and_legacy_calls() -> None:
    snapshot = _snapshot()
    for fake in ("confirmed_unplugged", "bounded_unplugged_source_grace", "unknown"):
        blocked, report = _guard(snapshot, safe=True, evidence=fake)
        assert blocked.desired_battery_export_power_kw == 0.0, report

    legacy, report = guard_paid_agile_physical_export(
        _plan(),
        snapshot,
        None,
        SimulationConfig(),
        ControlConfig(),
        now=NOW,
    )
    assert legacy.desired_battery_export_power_kw == 0.0, report


def test_connected_idle_cannot_create_unknown_status_grace() -> None:
    safe, anchor, _ = _assess(_snapshot())
    assert safe and anchor is None
    lost = _snapshot(ev_connected=None, ev_charging=None)
    safe, next_anchor, reason = _assess(lost, previous_unplugged=anchor)
    assert not safe and next_anchor is None
    assert "uncertain" in reason


def test_previous_unplugged_grace_is_cleared_as_soon_as_car_plugs_in() -> None:
    safe, unplugged_anchor, _ = _assess(
        _snapshot(ev_connected=False, ev_charging=False)
    )
    assert safe and unplugged_anchor == NOW
    safe, new_anchor, evidence = _assess(
        _snapshot(), previous_unplugged=unplugged_anchor
    )
    assert safe and evidence == "confirmed_connected_idle_zero_power"
    assert new_anchor is None


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("0.0", "0.2", True),
        ("0.0", "7.0", True),
        ("0.1", "0.11", True),
        ("7.0", "0.0", True),
        ("unavailable", "0.0", True),
        ("0.0", "unavailable", True),
        ("7.0", "unavailable", True),
        ("0.0", "0.05", False),
        ("6.5", "7.0", False),
        ("0.0", "0.1", False),
        ("unknown", "unavailable", False),
        ("unknown", "unknown", False),
    ],
)
def test_ev_charger_power_threshold_triggers_fast_control_scan(
    before: str, after: str, expected: bool
) -> None:
    assert meaningful_ev_power_transition(before, after) is expected


def test_coordinator_registers_power_threshold_without_status_change() -> None:
    code = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    events = (ROOT / "kems_core" / "control_event_refresh.py").read_text(
        encoding="utf-8"
    )
    assert "entities.ev_power_kw," in code
    assert "if entity_id == self.entities.ev_power_kw:" in code
    assert "meaningful_ev_power_transition(" in code
    assert "self.hass.async_create_task(self.async_request_refresh())" in code
    assert "_ALPHA975_FOLLOW_UP_REFRESH_SECONDS = 2" in code
    assert "return 1 if watts > threshold_kw else 0" in events


def test_no_paid_export_cheap_and_frozen_ev_hold_policy_are_untouched() -> None:
    from dataclasses import replace

    plan = replace(_plan(), desired_battery_export_power_kw=0.0)
    unchanged, report = guard_paid_agile_physical_export(
        plan,
        _snapshot(),
        None,
        SimulationConfig(),
        ControlConfig(),
        now=NOW,
        ev_export_safe=True,
        ev_export_evidence="confirmed_connected_idle_zero_power",
    )
    assert unchanged is plan
    assert report["status"] == "no_deliberate_export_requested"

    unchanged, report = guard_paid_agile_physical_export(
        _plan(),
        _snapshot(off_peak=True),
        None,
        SimulationConfig(),
        ControlConfig(),
        now=NOW,
        ev_export_safe=False,
    )
    assert unchanged is not None
    assert report["status"] == "higher_priority_cheap_or_event"

    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    assert "if tariff_type == EXPORT_TARIFF_TYPE_AGILE:" in coordinator
    assert "self._ev_grid_hold.async_apply(" in coordinator
    assert "paid_agile_ev_hold_eligible=paid_agile_ev_hold_eligible" in coordinator
