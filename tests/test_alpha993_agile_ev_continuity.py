"""Alpha9.93: uninterrupted paid Agile export across brief unplugged Ohme dropouts.

The state is short-lived, needs a genuinely fresh zero-power measurement, and
never weakens connected EV, charging, or No Paid Export protection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from kems_core import ControlConfig, ControlState, SimulationConfig, Snapshot
from kems_core.agile_live_reserve import (
    assess_paid_agile_ev_continuity,
    guard_paid_agile_physical_export,
)

NOW = datetime(2026, 10, 13, 21, 45, tzinfo=UTC)


def _snapshot(**overrides: object) -> Snapshot:
    data = {
        "timestamp": NOW,
        "battery_soc": 90.0,
        "source_data_age_seconds": 2.0,
        "source_age_seconds": {"battery_soc": 2.0},
        "next_offpeak_start": NOW + timedelta(hours=1),
        "ev_connected": False,
        "ev_charging": False,
        "ev_power_kw": 0.0,
        "ev_power_age_seconds": 3.0,
    }
    data.update(overrides)
    return Snapshot(**data)


def _assess(
    snapshot: Snapshot,
    *,
    now: datetime = NOW,
    previous: datetime | None = None,
) -> tuple[bool, datetime | None, str]:
    return assess_paid_agile_ev_continuity(
        snapshot, now=now, last_confirmed_unplugged_at=previous
    )


def _control() -> ControlState:
    return ControlState(
        operating_mode="control",
        operating_reason="agile_rolling_price_optimised",
        desired_work_mode="Feed-in First",
        desired_battery_to_home_power_kw=0.6,
        desired_battery_export_power_kw=5.8,
        desired_total_discharge_power_kw=6.4,
        desired_grid_export_allowed=True,
        data_fresh=True,
        plan_safe=True,
    )


def _dispatch(snap: Snapshot, allowed: bool) -> tuple[ControlState, dict[str, object]]:
    return guard_paid_agile_physical_export(
        _control(),
        snap,
        SimpleNamespace(
            ready=True,
            expected_house_remaining_today_kwh=1.0,
            expected_solar_remaining_today_kwh=0.0,
            confidence_percent=0.0,
        ),
        SimulationConfig(),
        ControlConfig(stale_data_seconds=180),
        now=NOW,
        ev_export_safe=allowed,
        ev_export_evidence="bounded_unplugged_source_grace",
    )


def test_confirmed_unplugged_proof_and_missing_charging_flag() -> None:
    ok, anchor, reason = _assess(_snapshot())
    assert ok and anchor == NOW and reason == "confirmed_unplugged"
    ok, anchor, reason = _assess(_snapshot(ev_charging=None))
    assert ok and anchor == NOW
    assert reason == "unplugged_with_fresh_zero_ev_power"


def test_ev_unavailable_for_40_seconds_preserves_agile_export() -> None:
    _, anchor, _ = _assess(_snapshot())
    during_dropout = NOW + timedelta(seconds=40)
    unavailable = _snapshot(ev_connected=None, ev_charging=None)
    ok, retained, reason = _assess(unavailable, now=during_dropout, previous=anchor)
    assert ok and retained == anchor
    assert reason == "bounded_unplugged_source_grace"
    controlled, detail = _dispatch(unavailable, allowed=ok)
    assert controlled.desired_battery_export_power_kw > 0.0
    assert detail["ev_export_evidence"] == reason


def test_ev_becomes_connected_or_draws_current_clears_grace_immediately() -> None:
    for changes in (
        {"ev_connected": True, "ev_charging": False},
        {"ev_connected": True, "ev_charging": True},
        {"ev_connected": None, "ev_charging": True},
        {"ev_power_kw": 0.2},
        {"ev_power_kw": 7.0, "ev_connected": None, "ev_charging": None},
    ):
        snap = _snapshot(**changes)
        ok, anchor, _ = _assess(snap, previous=NOW)
        assert not ok and anchor is None
        controlled, detail = _dispatch(snap, allowed=True)
        assert controlled.desired_battery_export_power_kw == 0.0
        assert detail["status"] == "blocked"


def test_90_second_limit_and_restart_without_anchor_fail_closed() -> None:
    lost = _snapshot(ev_connected=None, ev_charging=None)
    for seconds in (1, 40, 90):
        ok, _, _ = _assess(lost, now=NOW + timedelta(seconds=seconds), previous=NOW)
        assert ok
    for previous, seconds in ((None, 40), (NOW, 91)):
        ok, anchor, _ = _assess(
            lost, now=NOW + timedelta(seconds=seconds), previous=previous
        )
        assert not ok and anchor is None
    assert _dispatch(lost, allowed=False)[0].desired_battery_export_power_kw == 0.0


def test_stale_or_missing_ev_power_cannot_authorise_unavailable_source() -> None:
    for changes in (
        {"ev_power_kw": None},
        {"ev_power_age_seconds": None},
        {"ev_power_age_seconds": 181.0},
        {"ev_power_kw": -1.0},
        {"stale_fields": ("ev_power_kw",)},
    ):
        snap = _snapshot(ev_connected=None, ev_charging=None, **changes)
        ok, anchor, _ = _assess(snap, previous=NOW)
        assert not ok and anchor is None
        assert _dispatch(snap, allowed=True)[0].desired_battery_export_power_kw == 0.0


def test_unplugged_proof_must_be_recent_and_cannot_arrive_from_future() -> None:
    uncertain = _snapshot(ev_connected=None, ev_charging=False)
    assert not _assess(uncertain, previous=NOW + timedelta(seconds=1))[0]
    assert not _assess(uncertain, previous=None)[0]
    assert _assess(uncertain, previous=NOW)[0]


def test_cheap_and_no_paid_export_software_routes_are_untouched() -> None:
    code = (
        Path(__file__).parents[1] / "custom_components" / "kems" / "coordinator.py"
    ).read_text(encoding="utf-8")
    assert "if tariff_type == EXPORT_TARIFF_TYPE_AGILE:" in code
    assert "self._paid_agile_last_unplugged_at = None" in code
    assert "assess_paid_agile_ev_continuity(" in code
    assert "ev_export_safe=ev_export_safe" in code
    from dataclasses import replace

    plan = replace(_control(), desired_battery_export_power_kw=0.0)
    untouched, detail = guard_paid_agile_physical_export(
        plan,
        _snapshot(ev_connected=None, ev_charging=None),
        SimpleNamespace(ready=True),
        SimulationConfig(),
        ControlConfig(),
        now=NOW,
        ev_export_safe=False,
    )
    assert untouched is plan
    assert detail["status"] == "no_deliberate_export_requested"
