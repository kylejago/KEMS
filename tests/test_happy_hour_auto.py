"""Regression coverage for automatic Octopus Weekend Happy Hour discovery."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "kems"


def _load_auto_module():
    """Load the source-neutral Happy Hour modules without Home Assistant."""
    package_name = "kems_happy_hour_auto_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    sys.modules[package_name] = package

    for module_name in ("happy_hour", "happy_hour_auto"):
        qualified = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(
            qualified,
            INTEGRATION / f"{module_name}.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{package_name}.happy_hour_auto"]


AUTO_MODULE = _load_auto_module()
automatic_happy_hour_event = AUTO_MODULE.automatic_happy_hour_event

NOW = datetime(2026, 8, 23, 8, 30, tzinfo=UTC)  # Sunday 09:30 BST


class FakeState:
    def __init__(self, entity_id: str, attributes: dict) -> None:
        self.entity_id = entity_id
        self.attributes = attributes


class FakeStates:
    def __init__(self, states=None) -> None:
        self._states = list(states or [])

    def async_all(self):
        return list(self._states)


class FakeHass:
    def __init__(self, *, states=None, data=None) -> None:
        self.states = FakeStates(states)
        self.data = data or {}


def _event(start: datetime, end: datetime, *, event_id="hh-1", code=None):
    return {
        "id": event_id,
        "code": code,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "duration_in_minutes": (end - start).total_seconds() / 60.0,
    }


def test_public_power_up_event_is_used_automatically() -> None:
    state = FakeState(
        "event.octopus_energy_a_60624fb8_octoplus_power_up_events",
        {"events": [_event(NOW - timedelta(minutes=30), NOW + timedelta(minutes=30))]},
    )
    result = automatic_happy_hour_event(
        FakeHass(states=[state]),
        manual_options={},
        saving_session_entity=(
            "event.octopus_energy_a_60624fb8_octoplus_power_down_events"
        ),
        now=NOW,
    )
    assert result["source"] == "octopus_energy"
    assert result["automatic_status"] == "detected_active"
    assert result["duration_hours"] == 1
    assert result["fair_use_cap_kwh"] == 16.0


def test_two_consecutive_one_hour_rewards_are_merged() -> None:
    start = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
    state = FakeState(
        "event.octopus_energy_a_60624fb8_octoplus_power_up_events",
        {
            "events": [
                _event(start, start + timedelta(hours=1), event_id="one"),
                _event(
                    start + timedelta(hours=1),
                    start + timedelta(hours=2),
                    event_id="two",
                ),
            ]
        },
    )
    result = automatic_happy_hour_event(
        FakeHass(states=[state]), manual_options={}, now=NOW
    )
    assert result["source"] == "octopus_energy"
    assert result["duration_hours"] == 2
    assert result["fair_use_cap_kwh"] == 32.0
    assert result["event_ids"] == ["one", "two"]


def test_coded_free_electricity_event_is_never_happy_hour() -> None:
    start = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
    state = FakeState(
        "event.octopus_energy_a_60624fb8_octoplus_power_up_events",
        {
            "events": [
                _event(start, start + timedelta(hours=1), code="FREE-ELECTRICITY")
            ]
        },
    )
    result = automatic_happy_hour_event(
        FakeHass(states=[state]), manual_options={}, now=NOW
    )
    assert result["source"] == "manual"
    assert result["automatic_source_supported"] is True
    assert result["automatic_status"] == "no_confident_weekend_happy_hour"


def test_multiple_non_contiguous_candidates_fail_safe_to_manual() -> None:
    first = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
    second = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    state = FakeState(
        "event.octopus_energy_a_60624fb8_octoplus_power_up_events",
        {
            "events": [
                _event(first, first + timedelta(hours=1), event_id="one"),
                _event(second, second + timedelta(hours=1), event_id="two"),
            ]
        },
    )
    result = automatic_happy_hour_event(
        FakeHass(states=[state]),
        manual_options={
            "weekend_happy_hour_enabled": True,
            "weekend_happy_hour_start": "2026-08-23T15:00:00+00:00",
        },
        now=NOW,
    )
    assert result["source"] == "manual"
    assert result["automatic_status"] == "ambiguous_upcoming_power_up_events"
    assert result["enabled"] is True


def test_disabled_public_entity_uses_read_only_octopus_coordinator() -> None:
    start = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
    coordinator_event = SimpleNamespace(
        id="hh-internal",
        code=None,
        start=start,
        end=start + timedelta(hours=1),
        duration_in_minutes=60,
    )
    coordinator = SimpleNamespace(
        data=SimpleNamespace(joined_power_up_events=[coordinator_event])
    )
    hass = FakeHass(
        data={
            "octopus_energy": {
                "A-60624FB8": {"POWER_UP_DOWN_COORDINATOR": coordinator},
            }
        }
    )
    result = automatic_happy_hour_event(
        hass,
        manual_options={},
        saving_session_entity=(
            "event.octopus_energy_a_60624fb8_octoplus_power_down_events"
        ),
        now=NOW,
    )
    assert result["source"] == "octopus_energy"
    assert result["source_kind"] == "octopus_coordinator"
    assert result["source_account"] == "A-60624FB8"


def test_weekday_code_less_power_up_is_not_auto_classified() -> None:
    monday = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    state = FakeState(
        "event.octopus_energy_a_60624fb8_octoplus_power_up_events",
        {"events": [_event(monday, monday + timedelta(hours=1))]},
    )
    result = automatic_happy_hour_event(
        FakeHass(states=[state]), manual_options={}, now=NOW
    )
    assert result["source"] == "manual"
    assert result["automatic_status"] == "no_confident_weekend_happy_hour"


def test_dashboard_copy_exposes_automatic_source_and_manual_fallback() -> None:
    content = AUTO_MODULE._AUTO_DASHBOARD_INSERT
    assert "Weekend Happy Hour" in content
    assert "Octopus Energy — automatic" in content
    assert "Happy Hour fallback controls" in content
    assert "automatic_status" in content
    assert "datetime.kems_weekend_happy_hour_start" in content


def test_automatic_patch_runs_after_event_priority_installer() -> None:
    compat = (INTEGRATION / "agile_alpha7_compat.py").read_text(encoding="utf-8")
    event_priority = '("agile_event_priority", "install_event_priority")'
    automatic = '("happy_hour_auto", "install_automatic_happy_hour")'
    assert event_priority in compat
    assert automatic in compat
    assert compat.index(event_priority) < compat.index(automatic)

    runtime = (INTEGRATION / "agile_event_priority_runtime.py").read_text(encoding="utf-8")
    assert "return improve_alpha743_dashboard(content).encode(\"utf-8\")" in runtime
