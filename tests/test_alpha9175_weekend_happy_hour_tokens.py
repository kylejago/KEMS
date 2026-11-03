"""Alpha9.176: variable-cost Weekend Happy Hour tokens are not hours."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from custom_components.kems import happy_hour_auto_join as hh


def _hass(tokens: int | None, *, public_hours: int | None = 6):
    event = SimpleNamespace(
        entity_id="event.octopus_energy_a_test_octoplus_power_up_events",
        attributes={
            "available_events": [
                {
                    "code": "SATURDAY-11",
                    "start": "2026-11-07T11:00:00+00:00",
                    "end": "2026-11-07T12:00:00+00:00",
                    "availability": "available",
                }
            ],
            "events": [],
        },
    )
    states = [event]
    if public_hours is not None:
        states.append(
            SimpleNamespace(
                entity_id="sensor.octopus_energy_a_test_octoplus_weekend_happy_hours",
                state=str(public_hours),
            )
        )
    data = SimpleNamespace(weekend_happy_hours=tokens)
    account = {"POWER_UP_DOWN_COORDINATOR": SimpleNamespace(data=data)}
    return SimpleNamespace(
        states=SimpleNamespace(async_all=lambda: states),
        data={"octopus_energy": {"A-TEST": account}},
    )


def test_raw_tokens_are_not_divided_into_guaranteed_hours():
    candidates, audit = hh.discover_available_happy_hours(
        _hass(12), now=datetime(2026, 11, 3, 18, tzinfo=UTC)
    )
    assert len(candidates) == 1
    assert audit["weekend_happy_hours_tokens"] == 12
    assert audit["weekend_happy_hours_raw_coordinator"] == 12
    assert audit["weekend_happy_hours_legacy_estimate"] == 6
    assert audit["weekend_happy_hours_available"] is None
    assert audit["weekend_happy_hours_redeemable_event_day"] is None
    assert audit["weekend_happy_hours_token_cost_per_hour"] is None
    assert (
        audit["weekend_happy_hours_booking_eligibility"] == "octopus_join_service_only"
    )


def test_public_estimate_does_not_become_booking_authority_without_coordinator():
    _, audit = hh.discover_available_happy_hours(
        _hass(None, public_hours=6),
        now=datetime(2026, 11, 3, 18, tzinfo=UTC),
    )
    assert audit["weekend_happy_hours_tokens"] is None
    assert audit["weekend_happy_hours_legacy_estimate"] == 6
    assert audit["weekend_happy_hours_balance_basis"] == (
        "no_authoritative_octopus_token_balance"
    )


def test_ambiguous_coordinator_balances_fail_closed():
    hass = _hass(12)
    hass.data["octopus_energy"]["ANOTHER"] = {
        "POWER_UP_DOWN_COORDINATOR": SimpleNamespace(
            data=SimpleNamespace(weekend_happy_hours=5)
        )
    }
    assert hh._octopus_weekend_token_balance(hass) is None


def test_both_weekend_days_have_one_shared_cap():
    assert hh._weekend_start(date(2026, 11, 7)) == date(2026, 11, 7)
    assert hh._weekend_start(date(2026, 11, 8)) == date(2026, 11, 7)
    assert hh._weekend_start(date(2026, 11, 9)) == date(2026, 11, 7)


def test_service_ack_never_authorises_free_grid_import_or_refund():
    booking = {
        "bookings": [
            {
                "event_code": "SATURDAY-11",
                "booking_source": "octopus_service_pending",
                "start": "2026-11-07T11:00:00+00:00",
                "end": "2026-11-07T12:00:00+00:00",
            }
        ]
    }
    assert hh.confirmed_booking_windows(booking) == []
    assert hh.independently_confirmed_reward_hours(booking) == []

    booking["bookings"][0].update(
        {"event_id": "8136", "booking_source": "octopus_joined_events"}
    )
    assert len(hh.confirmed_booking_windows(booking)) == 1
    assert len(hh.independently_confirmed_reward_hours(booking)) == 1
