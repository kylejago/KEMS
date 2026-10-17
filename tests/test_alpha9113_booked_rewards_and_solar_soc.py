"""Alpha9.113: reconcile joined Octopus rewards and project physical solar SOC."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from kems_core.forecast_path_scheduler import allocate_forecast_path_exports

import custom_components.kems.happy_hour_auto_join as joining
from custom_components.kems.happy_hour_auto_join import (
    HappyHourCandidate,
    booked_happy_hour_matches_plan,
    confirmed_booking_windows,
    day_rate_coverage,
    published_agile_export_rates,
    verified_octopus_joined_bookings,
)

LONDON = ZoneInfo("Europe/London")


def _joined_hass() -> SimpleNamespace:
    event = SimpleNamespace(
        entity_id="event.octopus_energy_a_test_octoplus_power_up_events",
        attributes={
            "events": [
                {
                    "id": "octopus-7244",
                    "code": None,
                    "start": "2026-10-18T11:00:00+01:00",
                    "end": "2026-10-18T12:00:00+01:00",
                },
                {
                    "id": "octopus-7245",
                    "code": None,
                    "start": "2026-10-18T12:00:00+01:00",
                    "end": "2026-10-18T13:00:00+01:00",
                },
                {
                    "id": "not-reward",
                    "code": "ordinary-power-up",
                    "start": "2026-10-18T13:00:00+01:00",
                    "end": "2026-10-18T14:00:00+01:00",
                },
            ],
            "available_events": [
                {
                    "code": "NOT-BOOKED",
                    "start": "2026-10-18T14:00:00+01:00",
                    "end": "2026-10-18T15:00:00+01:00",
                }
            ],
        },
    )
    return SimpleNamespace(states=SimpleNamespace(async_all=lambda: [event]))


def test_two_code_less_joined_hours_are_confirmed_without_inventing_codes() -> None:
    now = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
    confirmed = verified_octopus_joined_bookings(_joined_hass(), now=now)
    assert len(confirmed) == 2
    assert all(item.get("event_code") is None for item in confirmed)
    assert {item["event_id"] for item in confirmed} == {"octopus-7244", "octopus-7245"}
    joined = {"status": "booked", "bookings": confirmed}
    windows = confirmed_booking_windows(joined)
    assert len(windows) == 1
    assert windows[0]["start"] == datetime(2026, 10, 18, 10, tzinfo=UTC)
    assert windows[0]["end"] == datetime(2026, 10, 18, 12, tzinfo=UTC)
    assert booked_happy_hour_matches_plan(
        joined,
        {"start": windows[0]["start"], "end": windows[0]["end"]},
        datetime(2026, 10, 18, 10, 30, tzinfo=UTC),
    )


def test_unavailable_and_ambiguous_octopus_sources_cannot_authorise() -> None:
    now = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
    hass = _joined_hass()
    event = hass.states.async_all()[0]
    assert (
        verified_octopus_joined_bookings(
            SimpleNamespace(states=SimpleNamespace(async_all=lambda: [event, event])),
            now=now,
        )
        == []
    )
    event.attributes["events"] = []
    assert verified_octopus_joined_bookings(hass, now=now) == []


def test_published_agile_export_fallback_preserves_missing_prices() -> None:
    now = datetime.now(UTC)
    local_tomorrow = now.astimezone(LONDON).date() + timedelta(days=1)
    start = datetime.combine(local_tomorrow, datetime.min.time(), tzinfo=LONDON)
    start = start.astimezone(UTC)
    slots = [
        {
            "valid_from": (start + timedelta(minutes=30 * i)).isoformat(),
            "valid_to": (start + timedelta(minutes=30 * (i + 1))).isoformat(),
            "rate_pence": 20.0 + i / 10,
        }
        for i in range(46)
    ]
    coordinator = SimpleNamespace(
        agile_smart_export_state={
            "generated_at": now.isoformat(),
            "tariff_code": "E-1R-AGILE-OUTGOING",
            "tomorrow_slots": slots,
        }
    )
    rates = published_agile_export_rates(coordinator, target_day=local_tomorrow)
    assert len(rates) == 46
    assert day_rate_coverage(rates, local_tomorrow) == pytest.approx(46 / 48)
    assert all(rate.value_pence >= 20.0 for rate in rates)
    coordinator.agile_smart_export_state["generated_at"] = (
        now - timedelta(hours=1)
    ).isoformat()
    assert published_agile_export_rates(coordinator, target_day=local_tomorrow) == []


def test_confirmed_octopus_hours_never_trigger_duplicate_bookings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        now = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz or UTC)

        monkeypatch.setattr(joining, "datetime", Clock)
        hass = _joined_hass()
        calls: list[object] = []
        hass.services = SimpleNamespace(
            async_call=lambda *args, **kwargs: calls.append(args)
        )
        options = {"happy_hour_auto_join_enabled": True, "battery_installed": True}
        entry = SimpleNamespace(options=options)
        control = SimpleNamespace(
            operating_mode="control",
            commissioned=True,
            control_enabled=True,
            emergency_stop=False,
        )
        coordinator = SimpleNamespace(
            hass=hass,
            entry=entry,
            settings=SimpleNamespace(control=control),
        )
        first = datetime(2026, 10, 18, 10, tzinfo=UTC)
        candidates = [
            HappyHourCandidate(
                code=f"EVENT-{i}",
                start=first + timedelta(hours=i),
                end=first + timedelta(hours=i + 1),
                availability="available",
                source="test",
                source_entity=hass.states.async_all()[0].entity_id,
            )
            for i in range(4)
        ]
        monkeypatch.setattr(
            joining,
            "discover_available_happy_hours",
            lambda _hass, now: (candidates, {"weekend_happy_hours_available": 10}),
        )
        controller = joining.HappyHourAutoJoinController.__new__(
            joining.HappyHourAutoJoinController
        )
        controller.hass = hass
        controller.entry = entry
        controller.coordinator = coordinator
        controller._persisted = {}
        controller.state = {}
        controller.async_load = AsyncMock()
        controller._async_save = AsyncMock()
        await controller.async_update(SimpleNamespace())
        assert calls == []
        assert controller.state["booked_reward_hours"] == 2
        assert controller.state["status"] == "booked"
        assert controller.state["booked_event_codes"] == []
        assert len(confirmed_booking_windows(controller.state)) == 1
        assert controller._persisted == {}
        # Disabling future auto-join does not hide already joined hours.
        options["happy_hour_auto_join_enabled"] = False
        await controller.async_update(SimpleNamespace())
        assert controller.state["booked_reward_hours"] == 2

    asyncio.run(exercise())


def test_solar_chronological_slot_soc_tracks_recharge_after_arrival() -> None:
    start = datetime(2026, 10, 17, 8, tzinfo=UTC)
    slots = [
        {
            "valid_from": (start + timedelta(minutes=30 * index)).isoformat(),
            "valid_to": (start + timedelta(minutes=30 * (index + 1))).isoformat(),
            "rate_pence": [20.0, 8.0, 22.0][index],
        }
        for index in range(3)
    ]
    segments = [
        {
            "start": (start + timedelta(minutes=5 * index)).isoformat(),
            "end": (start + timedelta(minutes=5 * (index + 1))).isoformat(),
            "solar_kw": 4.0 if 6 <= index < 12 else 0.0,
            "battery_kw": 7.0,
        }
        for index in range(18)
    ]
    plan = allocate_forecast_path_exports(
        slots=slots,
        capacity_segments=segments,
        now=start,
        deadline=start + timedelta(minutes=90),
        battery_capacity_kwh=10.0,
        soc_percent=40.0,
        target_soc_percent=20.0,
        charge_efficiency=1.0,
        discharge_efficiency=1.0,
        max_charge_kw=7.0,
        house_kw=0.0,
        export_limit_kw=7.0,
        minimum_export_rate_pence=3.5,
    )
    assert plan.available
    assert plan.forecast_solar_stored_kwh > 0.0
    assert all(a.ending_soc_percent is not None for a in plan.allocations)
    assert (
        plan.allocations[1].ending_soc_percent > plan.allocations[0].ending_soc_percent
    )
    assert plan.allocations[-1].ending_soc_percent == pytest.approx(
        plan.ending_soc_percent, abs=0.002
    )
