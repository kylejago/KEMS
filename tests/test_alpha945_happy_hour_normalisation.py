"""Alpha9.45 Weekend Happy Hour balance and event-day policy contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from custom_components.kems.happy_hour_auto_join import (
    HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY,
    HappyHourCandidate,
    _event_day_redeemable_reward_hours,
    _reward_hours_for_candidate,
    _weekend_happy_hour_count,
    discover_available_happy_hours,
)


class _States:
    def __init__(self, values):
        self._values = list(values)

    def async_all(self):
        return list(self._values)


def _coordinator_hass(*, raw_count: int, available_events=None):
    data = SimpleNamespace(
        weekend_happy_hours=raw_count,
        available_power_up_events=list(available_events or []),
    )
    return SimpleNamespace(
        states=_States([]),
        data={
            "octopus_energy": {
                "A-TEST": {
                    "POWER_UP_DOWN_COORDINATOR": SimpleNamespace(data=data),
                }
            }
        },
    )


def test_alpha945_coordinator_six_progress_units_are_three_rewards() -> None:
    hass = _coordinator_hass(raw_count=6)
    assert _weekend_happy_hour_count(hass) == 3


def test_alpha945_public_sensor_count_is_already_normalised() -> None:
    state = SimpleNamespace(
        entity_id="sensor.octopus_energy_a_test_octoplus_weekend_happy_hours",
        state="3",
        attributes={},
    )
    hass = SimpleNamespace(states=_States([state]), data={})
    assert _weekend_happy_hour_count(hass) == 3


def test_alpha945_banked_balance_never_becomes_more_than_two_hours_in_one_day() -> None:
    now = datetime(2026, 9, 18, 18, tzinfo=UTC)
    events = []
    for offset, hour in enumerate((9, 10, 11, 12), start=1):
        start = datetime(2026, 9, 19, hour, tzinfo=UTC)
        events.append(
            {
                "code": f"HH-{offset}",
                "start": start,
                "end": start + timedelta(hours=1),
                "availability": "available",
            }
        )
    hass = _coordinator_hass(raw_count=8, available_events=events)

    candidates, metadata = discover_available_happy_hours(hass, now=now)

    assert len(candidates) == 4
    assert metadata["weekend_happy_hours_raw_coordinator"] == 8
    assert metadata["weekend_happy_hours_available"] == 4
    assert metadata["weekend_happy_hours_event_day_limit"] == 2
    assert metadata["weekend_happy_hours_redeemable_event_day"] == 2
    assert metadata["weekend_happy_hours_balance_basis"] == (
        "octopus coordinator progress / 2"
    )
    assert _event_day_redeemable_reward_hours(1) == 1
    assert _event_day_redeemable_reward_hours(4) == 2
    assert HAPPY_HOUR_MAX_REWARDS_PER_EVENT_DAY == 2


def test_alpha945_candidate_reward_accounting_is_capped_at_two_hours() -> None:
    start = datetime(2026, 9, 19, 9, tzinfo=UTC)
    one_hour = HappyHourCandidate(
        code="ONE",
        start=start,
        end=start + timedelta(minutes=55),
        availability="available",
        source="test",
    )
    two_hour = HappyHourCandidate(
        code="TWO",
        start=start,
        end=start + timedelta(minutes=125),
        availability="available",
        source="test",
    )
    assert _reward_hours_for_candidate(one_hour) == 1
    assert _reward_hours_for_candidate(two_hour) == 2


def test_alpha945_dashboard_explains_banked_balance_and_daily_limit() -> None:
    source = (
        __import__("pathlib").Path(__file__).parents[1]
        / "dashboards"
        / "kems_master_dashboard.yaml"
    ).read_text(encoding="utf-8")
    packaged = (
        __import__("pathlib").Path(__file__).parents[1]
        / "custom_components"
        / "kems"
        / "kems_master_dashboard.yaml"
    ).read_text(encoding="utf-8")
    assert "Happy Hours banked" in source
    assert "Redeemable this event day" in source
    assert "Event-day limit" in source
    assert "weekend_happy_hours_redeemable_event_day" in source
    assert source == packaged


def test_alpha945_release_identity_and_scope() -> None:
    import json
    from pathlib import Path

    root = Path(__file__).parents[1]
    manifest = json.loads(
        (root / "custom_components" / "kems" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    bundle = json.loads(
        (root / "release" / "kems-bundle.template.json").read_text(encoding="utf-8")
    )
    reason = str(bundle["maintenance"]["reason"])
    assert manifest["version"] == "0.9.0-alpha9.64"
    assert reason.startswith("Alpha9.63")
    assert "Alpha9.45" in reason
    assert "raw 6 reports 3 rewards rather than 6" in reason
    assert "two-one-hour-reward event-day limit" in reason
    assert "16 kWh-per-reward-hour cap" in reason
    assert "does not broaden external Octopus booking authority" in reason
    assert "FoxESS hardware-write authority" in reason
