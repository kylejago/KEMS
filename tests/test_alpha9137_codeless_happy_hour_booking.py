"""Alpha9.137: external Octopus IDs are bookings, not missing event codes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import custom_components.kems.happy_hour_auto_join as hh


def _joined(second: bool) -> SimpleNamespace:
    events = [
        {
            "id": 7723,
            "code": None,
            "start": "2026-10-25T11:00:00+00:00",
            "end": "2026-10-25T12:00:00+00:00",
        }
    ]
    if second:
        events.append(
            {
                "id": 7724,
                "code": None,
                "start": "2026-10-25T12:00:00+00:00",
                "end": "2026-10-25T13:00:00+00:00",
            }
        )
    source = SimpleNamespace(
        entity_id="event.octopus_energy_test_octoplus_power_up_events",
        attributes={"events": events},
    )
    return SimpleNamespace(
        states=SimpleNamespace(async_all=lambda: [source]),
        services=SimpleNamespace(),
    )


def _candidate(hour: int) -> hh.HappyHourCandidate:
    start = datetime(2026, 10, 25, hour, tzinfo=UTC)
    return hh.HappyHourCandidate(
        code=f"EVENT-{hour}",
        start=start,
        end=start + timedelta(hours=1),
        availability="available",
        source="test",
        source_entity="event.octopus_energy_test_octoplus_power_up_events",
    )


def test_code_less_confirmation_uses_time_windows_to_avoid_duplicate_join():
    booked = hh.confirmed_booking_windows(
        {
            "bookings": hh.verified_octopus_joined_bookings(
                _joined(second=False),
                now=datetime(2026, 10, 24, 19, tzinfo=UTC),
            )
        }
    )
    result = hh.select_reward_booking_codes(
        candidates=[_candidate(11), _candidate(12), _candidate(13)],
        booked_codes=set(),
        booked_windows=booked,
        scored={},
        target_count=2,
    )
    assert result == ["EVENT-12"]


def test_two_external_id_only_bookings_exhaust_daily_allowance():
    booked = hh.confirmed_booking_windows(
        {
            "bookings": hh.verified_octopus_joined_bookings(
                _joined(second=True),
                now=datetime(2026, 10, 24, 19, tzinfo=UTC),
            )
        }
    )
    assert len(booked) == 1
    assert len(booked[0]["event_codes"]) == 2
    assert booked[0]["start"].isoformat() == "2026-10-25T11:00:00+00:00"
    assert booked[0]["end"].isoformat() == "2026-10-25T13:00:00+00:00"
    assert hh.select_reward_booking_codes(
        candidates=[_candidate(11), _candidate(12), _candidate(13)],
        booked_codes=set(),
        booked_windows=booked,
        scored={},
        target_count=2,
    ) == []


@pytest.mark.parametrize("second,expected_calls", [(False, 1), (True, 0)])
def test_coordinator_respects_code_less_joined_hours_without_third_booking(
    monkeypatch: pytest.MonkeyPatch, second: bool, expected_calls: int
):
    async def exercise():
        now = datetime(2026, 10, 24, 20, tzinfo=UTC)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz or UTC)

        monkeypatch.setattr(hh, "datetime", Clock)
        hass = _joined(second=second)
        calls = []

        async def join(_domain, _service, payload, **_kwargs):
            calls.append(payload)
            return {"success": True}

        hass.services.async_call = join
        hass.services.has_service = lambda *_args: True
        choices = [_candidate(hour) for hour in (11, 12, 13)]
        monkeypatch.setattr(
            hh,
            "discover_available_happy_hours",
            lambda *_args, **_kwargs: (
                choices,
                {"weekend_happy_hours_available": 8},
            ),
        )
        monkeypatch.setattr(hh, "discover_octopus_rates", lambda _hass: ([], []))
        monkeypatch.setattr(hh, "day_rate_coverage", lambda *_args: 1.0)
        monkeypatch.setattr(hh, "score_candidate", lambda *_args, **_kwargs: None)
        control = SimpleNamespace(
            operating_mode="control",
            control_enabled=True,
            commissioned=True,
            emergency_stop=False,
        )
        simulation = SimpleNamespace(
            battery_capacity_kwh=56.42,
            battery_reserve_percent=15,
            max_charge_kw=7,
            max_discharge_kw=10,
            export_limit_kw=7,
            charge_efficiency=0.95,
            discharge_efficiency=0.95,
            export_rate_pence=5,
        )
        controller = hh.HappyHourAutoJoinController.__new__(
            hh.HappyHourAutoJoinController
        )
        controller.hass = hass
        controller.entry = SimpleNamespace(
            options={"happy_hour_auto_join_enabled": True, "battery_installed": True}
        )
        controller.coordinator = SimpleNamespace(
            hass=hass,
            entry=controller.entry,
            settings=SimpleNamespace(control=control, simulation=simulation),
            agile_smart_export_state={},
        )
        controller._persisted = {}
        controller.state = {}
        controller.async_load = AsyncMock()
        controller._async_save = AsyncMock()
        await controller.async_update(
            SimpleNamespace(
                snapshot=SimpleNamespace(battery_soc=25),
                forecast_plan=SimpleNamespace(
                    expected_house_tomorrow_kwh=8,
                    expected_solar_tomorrow_kwh=0,
                ),
            )
        )
        assert len(calls) == expected_calls
        assert controller.state["status"] == "booked"
        assert controller.state["booking_limit_reached"] is second
        assert controller.state["externally_confirmed_reward_hours"] == (
            2 if second else 1
        )
        assert controller.state["confirmed_booked_windows"][0]["start"] == (
            "2026-10-25T11:00:00+00:00"
        )
        if not second:
            assert calls[0]["event_code"] == "EVENT-12"
            assert len(controller.state["bookings"]) == 2
        else:
            assert controller.state["confirmed_booked_windows"][0]["end"] == (
                "2026-10-25T13:00:00+00:00"
            )
            assert controller._persisted == {}

    asyncio.run(exercise())


def test_release_diagnostics_expose_booking_control_and_error_state():
    from pathlib import Path

    root = Path(__file__).parents[1]
    diagnostics = (
        root / "custom_components" / "kems" / "diagnostics.py"
    ).read_text(encoding="utf-8")
    assert '"happy_hour_auto_join": happy_hour_auto_join_state(coordinator)' in (
        diagnostics
    )
