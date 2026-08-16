"""Regression tests for optional Octopus Intelligent timestamp freshness."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "kems"
NOW = datetime(2026, 8, 14, 21, 30, tzinfo=UTC)


def _load_octopus_provider(monkeypatch):
    """Load the provider with a minimal Home Assistant state stub."""
    homeassistant = ModuleType("homeassistant")
    core = ModuleType("homeassistant.core")
    const = ModuleType("homeassistant.const")
    util = ModuleType("homeassistant.util")
    dt = ModuleType("homeassistant.util.dt")

    class State:
        def __init__(self, state: str, *, last_reported: datetime) -> None:
            self.state = state
            self.attributes = {"unit_of_measurement": ""}
            self.last_updated = last_reported
            self.last_reported = last_reported

    core.HomeAssistant = object
    core.State = State
    const.ATTR_UNIT_OF_MEASUREMENT = "unit_of_measurement"
    const.STATE_OFF = "off"
    const.STATE_ON = "on"
    const.STATE_UNAVAILABLE = "unavailable"
    const.STATE_UNKNOWN = "unknown"
    dt.now = lambda: NOW
    dt.parse_datetime = datetime.fromisoformat
    util.dt = dt
    for name, module in {
        "homeassistant": homeassistant,
        "homeassistant.core": core,
        "homeassistant.const": const,
        "homeassistant.util": util,
        "homeassistant.util.dt": dt,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    package_name = "kems_optional_tariff_timestamp_test"
    package = ModuleType(package_name)
    package.__path__ = [str(INTEGRATION)]
    providers = ModuleType(f"{package_name}.providers")
    providers.__path__ = [str(INTEGRATION / "providers")]
    entity_map = ModuleType(f"{package_name}.providers.entity_map")
    entity_map.KEMSEntities = object
    for name, module in {
        package_name: package,
        f"{package_name}.providers": providers,
        f"{package_name}.providers.entity_map": entity_map,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    for module_name, path in (
        ("providers.base", INTEGRATION / "providers" / "base.py"),
        ("providers.octopus", INTEGRATION / "providers" / "octopus.py"),
    ):
        qualified = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(qualified, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, qualified, module)
        spec.loader.exec_module(module)
        if module_name == "providers.octopus":
            octopus = module
    return octopus, State


def _entities(**overrides):
    values = {
        "current_import_rate": None,
        "next_import_rate": None,
        "current_export_rate": None,
        "electricity_standing_charge": None,
        "off_peak": None,
        "intelligent_slot": None,
        "next_offpeak_start": None,
        "offpeak_end": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_unknown_offpeak_end_is_absent_not_stale(monkeypatch) -> None:
    """An old unknown boundary is not an operational stale-data warning."""
    octopus, State = _load_octopus_provider(monkeypatch)
    states = {
        "sensor.offpeak_end": State(
            "unknown",
            last_reported=NOW - timedelta(minutes=30),
        )
    }
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))

    result = octopus.OctopusProvider(
        hass,
        _entities(offpeak_end="sensor.offpeak_end"),
        stale_data_seconds=180,
    ).get_state(NOW)

    assert result.offpeak_end is None
    assert result.stale_fields == ()
    assert "offpeak_end" not in result.source_age_seconds


def test_old_real_offpeak_end_still_becomes_stale(monkeypatch) -> None:
    """A real positive timestamp remains subject to the Intelligent timeout."""
    octopus, State = _load_octopus_provider(monkeypatch)
    states = {
        "sensor.offpeak_end": State(
            "2026-08-14T22:00:00+00:00",
            last_reported=NOW - timedelta(seconds=361),
        )
    }
    hass = SimpleNamespace(states=SimpleNamespace(get=states.get))

    result = octopus.OctopusProvider(
        hass,
        _entities(offpeak_end="sensor.offpeak_end"),
        stale_data_seconds=180,
    ).get_state(NOW)

    assert result.offpeak_end is None
    assert result.source_age_seconds["offpeak_end"] == 361.0
    assert result.stale_fields == ("offpeak_end",)
